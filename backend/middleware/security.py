from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException, Request


class RateLimiter:
    """Simple in-memory rate limiter keyed by (endpoint, identifier).

    Not distributed-safe (single-process only), but sufficient for a
    personal home-assistant running on one host.
    """

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._store: dict[str, list[float]] = {}

    def _key(self, endpoint: str, identifier: str) -> str:
        return f"{endpoint}:{identifier}"

    def check(self, endpoint: str, identifier: str):
        now = time.time()
        window_start = now - self.window
        key = self._key(endpoint, identifier)
        requests = self._store.get(key, [])
        requests = [t for t in requests if t > window_start]
        if len(requests) >= self.max_requests:
            raise HTTPException(429, "Too many requests. Try again later.")
        requests.append(now)
        self._store[key] = requests


class WebSocketRateLimiter:
    """Rate limiter for WebSocket connections per user."""

    def __init__(self, max_messages: int = 30, window_seconds: int = 60):
        self.max_messages = max_messages
        self.window = window_seconds
        self._store: dict[str, list[float]] = {}

    def check(self, user_id: str):
        now = time.time()
        window_start = now - self.window
        requests = self._store.get(user_id, [])
        requests = [t for t in requests if t > window_start]
        if len(requests) >= self.max_messages:
            raise HTTPException(429, "Too many messages. Slow down.")
        requests.append(now)
        self._store[user_id] = requests


def get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For if behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def sanitize_messages(messages: list[dict]) -> list[dict]:
    """Sanitize and bound message arrays before sending to the LLM.

    - Caps history depth at 20 messages
    - Limits each message to 8000 chars
    - Validates roles (user/assistant only; maps unknown to user)
    """
    cleaned: list[dict] = []
    for msg in messages[-20:]:
        role = str(msg.get("role", "user"))
        if role not in ("user", "assistant"):
            role = "user"
        content = str(msg.get("content", ""))[:8000]
        cleaned.append({"role": role, "content": content})
    return cleaned


# Shared limiter instances (module-level singletons)
auth_rate_limiter = RateLimiter(max_requests=5, window_seconds=60)
ws_rate_limiter = WebSocketRateLimiter(max_messages=30, window_seconds=60)
