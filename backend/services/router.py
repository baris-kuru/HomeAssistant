from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import asdict, dataclass
import re
import time
from typing import Sequence

from ..schemas import RouteResponse
from .fireworks_service import chat_structured

logger = logging.getLogger(__name__)

ROUTER_MODEL = os.getenv(
    "FIREWORKS_ROUTER_MODEL",
    "accounts/fireworks/models/gpt-oss-20b",
)
# When set, run this model in the background on every route call and log any
# disagreement with ROUTER_MODEL. Lets us A/B new routers against real traffic
# without exposing users to their mistakes.
ROUTER_SHADOW_MODEL = os.getenv("FIREWORKS_ROUTER_SHADOW_MODEL") or None


SEARCH_HINTS = {
    "latest",
    "today",
    "news",
    "current",
    "currently",
    "why",
    "compare",
    "comparison",
    "research",
    "best",
    "explain",
    "vs",
}
CALENDAR_HINTS = {"calendar", "event", "meeting", "appointment", "schedule"}
DEVICE_HINTS = {"light", "lights", "thermostat", "vacuum", "door", "tv", "device", "devices"}
MEMORY_HINTS = {"remember", "memory", "forgot", "recall", "note this", "don't forget"}
DOCUMENT_HINTS = {"upload", "uploaded", "attachment", "pdf", "doc", "document", "file"}
WEATHER_HINTS = {"weather", "rain", "forecast", "temperature", "wind"}
IDENTITY_HINTS = {"password", "login", "switch user", "change password"}


@dataclass(slots=True)
class RouteDecision:
    lane: str
    domain: str
    use_search: bool
    queries: list[str]
    confidence: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── LLM-based routing cache ──────────────────────────────────────────
# {normalized_text: (RouteDecision, timestamp)}
_route_cache: dict[str, tuple[RouteDecision, float]] = {}
_CACHE_TTL = 300  # 5 minutes


def _latest_user_text(messages: Sequence[dict]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user":
            return str(item.get("content", "")).strip()
    return ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_any(text: str, needles: set[str]) -> bool:
    return any(needle in text for needle in needles)


def _query_variants(text: str, lane: str, fanout: int = 3) -> list[str]:
    base = re.sub(r"^/think\s*", "", text, flags=re.I).strip()
    if not base:
        return []
    variants = [base]
    compact = re.sub(r"[^\w\s-]", " ", base)
    compact = re.sub(r"\s+", " ", compact).strip()
    if lane in {"search", "deep"} and compact and compact != base:
        variants.append(compact)
    if lane in {"search", "deep"}:
        variants.append(f"{compact or base} 2026")

    deduped: list[str] = []
    seen: set[str] = set()
    for query in variants:
        query = query.strip()
        if not query:
            continue
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    return deduped[:fanout]


def _keyword_route(text: str, attachments: list[str]) -> RouteDecision:
    """Pure keyword-based routing (fallback)."""
    lane = "fast"
    domain = "general"
    reason = "default fast direct answer"
    confidence = 0.55

    has_document_signal = bool(attachments) or _contains_any(text, DOCUMENT_HINTS)

    if _contains_any(text, IDENTITY_HINTS):
        domain = "identity"
        reason = "identity or password keyword"
        confidence = 0.9
    elif has_document_signal:
        domain = "documents"
        reason = "attachment or document keyword"
        confidence = 0.92
    elif _contains_any(text, CALENDAR_HINTS):
        domain = "calendar"
        reason = "calendar keyword"
        confidence = 0.86
    elif _contains_any(text, DEVICE_HINTS):
        domain = "devices"
        reason = "device keyword"
        confidence = 0.84
    elif _contains_any(text, MEMORY_HINTS):
        domain = "memory"
        reason = "memory keyword"
        confidence = 0.84
    elif _contains_any(text, WEATHER_HINTS):
        domain = "weather"
        reason = "weather keyword"
        confidence = 0.88

    if text.startswith("/think"):
        lane = "deep"
        reason = "explicit /think request"
        confidence = 1.0
    elif _contains_any(text, SEARCH_HINTS):
        lane = "search"
        reason = f"{reason}; current-fact or research keyword"
        confidence = max(confidence, 0.78)

    use_search = lane in {"search", "deep"}
    queries = _query_variants(text, lane)
    return RouteDecision(
        lane=lane,
        domain=domain,
        use_search=use_search,
        queries=queries,
        confidence=round(confidence, 2),
        reason=reason,
    )


LLM_ROUTE_PROMPT = """You are a message router. Classify the user's message into a domain and lane.

Respond with a JSON object containing exactly these fields:
- lane: "fast" | "search" | "deep"
- domain: "calendar" | "weather" | "memory" | "documents" | "general" | "identity" | "devices"
- confidence: a float between 0 and 1
- reason: a short explanation (1 sentence)

CRITICAL RULES:
- "identity" domain is ONLY for account management: passwords, logins, user switching, changing credentials.
- Normal chat, questions about yourself (the AI), "who are you", "what model", general conversation → domain "general"
- /think prefix → lane "deep"
- Current facts, news, research, comparisons, "why", "latest", "explain" → lane "search"
- Calendar/events/meetings → domain "calendar"
- Weather/temperature/forecast → domain "weather"
- Remember/forget/recall notes → domain "memory"
- Uploaded files/PDFs/documents → domain "documents"
- Smart home lights/thermostat/devices → domain "devices"
- When in doubt → domain "general", lane "fast"
"""


async def route_request_llm(messages: Sequence[dict], attachments: Sequence[str] | None = None) -> RouteDecision:
    """LLM-based router using Fireworks API with 5s timeout."""
    latest = _latest_user_text(messages)
    text = _normalize(latest)
    attachments = [item for item in (attachments or []) if item]

    # Check cache
    cache_key = text
    now = time.monotonic()
    if cache_key in _route_cache:
        decision, ts = _route_cache[cache_key]
        if now - ts < _CACHE_TTL:
            return decision
        del _route_cache[cache_key]

    # Build the message for LLM routing
    attachment_note = f"\nAttachments: {len(attachments)}" if attachments else ""
    user_input = f"{text}{attachment_note}"

    try:
        parsed = await asyncio.wait_for(
            chat_structured(
                messages=[{"role": "user", "content": user_input}],
                schema=RouteResponse,
                system=LLM_ROUTE_PROMPT,
                model=ROUTER_MODEL,
                max_tokens=150,
                temperature=0.1,
            ),
            timeout=5.0,
        )
    except (asyncio.TimeoutError, Exception):
        parsed = None

    if ROUTER_SHADOW_MODEL:
        asyncio.create_task(_shadow_compare(user_input, parsed))

    if parsed is None:
        decision = _keyword_route(text, attachments)
        _route_cache[cache_key] = (decision, now)
        return decision

    # SECURITY: override identity domain if no actual identity keywords present.
    # Prevents models from misclassifying normal chat ("which model are you")
    # as identity management.
    domain = parsed.domain
    if domain == "identity" and not _contains_any(text, IDENTITY_HINTS):
        domain = "general"

    decision = RouteDecision(
        lane=parsed.lane,
        domain=domain,
        use_search=parsed.lane in {"search", "deep"},
        queries=_query_variants(latest, parsed.lane),
        confidence=round(parsed.confidence, 2),
        reason=parsed.reason,
    )
    _route_cache[cache_key] = (decision, now)
    return decision


async def _shadow_compare(user_input: str, primary: RouteResponse | None) -> None:
    """Run the shadow model and log when it disagrees with the primary decision."""
    try:
        shadow = await asyncio.wait_for(
            chat_structured(
                messages=[{"role": "user", "content": user_input}],
                schema=RouteResponse,
                system=LLM_ROUTE_PROMPT,
                model=ROUTER_SHADOW_MODEL,  # type: ignore[arg-type]
                max_tokens=150,
                temperature=0.1,
            ),
            timeout=5.0,
        )
    except (asyncio.TimeoutError, Exception):
        return
    if shadow is None or primary is None:
        return
    if shadow.lane != primary.lane or shadow.domain != primary.domain:
        logger.info(
            "router_shadow_disagree text=%r primary=%s/%s shadow=%s/%s",
            user_input,
            primary.lane, primary.domain,
            shadow.lane, shadow.domain,
        )


async def route_request(messages: Sequence[dict], attachments: Sequence[str] | None = None) -> RouteDecision:
    """Route a user message to the appropriate lane and domain.

    Strategy:
    1. Check in-memory cache (TTL 5 min)
    2. Try LLM routing with 5s timeout
    3. Fall back to keyword routing on any failure
    """
    return await route_request_llm(messages, attachments)
