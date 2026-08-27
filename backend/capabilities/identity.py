from __future__ import annotations

from typing import AsyncGenerator

from ..services.router import RouteDecision
from ..services.user_store import canonical_user_id, resolve_user, update_password, verify_password


async def handle_identity(
    messages: list[dict],
    user_id: str,
    location: dict | None,
    attachments: list[str],
    decision: RouteDecision,
) -> AsyncGenerator[str, None]:
    """Handle user switching and password changes."""
    latest_text = messages[-1].get("content", "").lower() if messages else ""

    if "switch" in latest_text or "login" in latest_text:
        yield "To switch users, please provide username and password in the format: 'switch to [username] with password [password]'"
    elif "password" in latest_text and ("change" in latest_text or "reset" in latest_text or "update" in latest_text):
        yield "To change your password, please provide current password and new password."
    elif "who am i" in latest_text or "my name" in latest_text:
        user = resolve_user(user_id)
        yield f"You are {user.get('name', user_id)}."
    else:
        # This shouldn't happen with the new routing guard, but as a fallback
        # pass through to general handler behavior instead of a dead-end message.
        yield "I'm your home assistant. I can help you manage your calendar, check weather, control devices, recall memories, or search the web. What would you like to do?"
