from __future__ import annotations

from typing import AsyncGenerator

from ..capabilities import CAPABILITY_HANDLERS
from ..services.fireworks_service import chat_stream
from ..services.router import RouteDecision, route_request
from ..services.search import search_service
from ..services.user_store import canonical_user_id


ROUTER_DEBUG = False


def _recent_history(messages: list[dict]) -> list[dict]:
    trimmed = messages[-8:]
    return [{"role": item.get("role", "user"), "content": str(item.get("content", ""))} for item in trimmed]


async def stream_agent(
    messages: list[dict],
    user_id: str,
    location: dict | None = None,
    attachments: list[str] | None = None,
    decision: RouteDecision | None = None,
    max_tool_rounds: int | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream agent responses using capability-based routing.

    Flow:
    1. Route the request (LLM-based with keyword fallback)
    2. Dispatch to the appropriate capability handler
    3. Yield text chunks back to WebSocket
    """
    user = canonical_user_id(user_id)
    attachments = [item for item in (attachments or []) if item]

    # Route if not provided
    if decision is None:
        decision = await route_request(messages, attachments=attachments)

    yield {"type": "thinking"}
    if ROUTER_DEBUG:
        yield {"type": "status", "content": f"route: {decision.lane}/{decision.domain} ({decision.reason})"}

    # Perform search if needed
    search_payload = None
    if decision.use_search and decision.queries:
        yield {"type": "tool_call", "name": "search_web"}
        search_payload = await search_service.search(
            queries=decision.queries,
            include_pages=True,
            lane=decision.lane,
        )

    # Get the capability handler
    handler = CAPABILITY_HANDLERS.get(decision.domain)
    if handler is None:
        # Fallback to general
        handler = CAPABILITY_HANDLERS["general"]

    # Stream response from capability
    async for chunk in handler(messages, user, location, attachments, decision):
        yield {"type": "text", "content": chunk}

    yield {"type": "done"}
