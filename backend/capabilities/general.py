from __future__ import annotations

from typing import AsyncGenerator

from ..services.fireworks_service import chat_once, chat_stream
from ..services.router import RouteDecision
from ..services.user_store import canonical_user_id


PERSONAS = {
    "baris": """Baris is an AI engineer at BASF in Berlin. Tone: direct, technical, lightly dry, concise, peer-to-peer.""",
}


def _persona_text(user: str) -> str:
    return PERSONAS.get(canonical_user_id(user), "Tone: friendly, concise, practical.")


def _system_context(user: str, location: dict | None = None) -> str:
    user = canonical_user_id(user)
    loc_str = f"lat {location['lat']:.4f}, lon {location['lon']:.4f}" if location else "Bonn, Germany (default)"
    if user == "guest":
        return (
            "You are Baris's personal assistant in Bonn. "
            f"User location: {loc_str}.\n"
            "The current person is not identified yet. Be brief and ask who they are if needed."
        )
    return (
        f"Current user: {user.capitalize()}.\n"
        f"Location: {loc_str}.\n"
        f"Persona: {_persona_text(user)}\n"
        "Context: This is Baris's personal assistant environment on his own devices.\n"
    )


async def handle_general(
    messages: list[dict],
    user_id: str,
    location: dict | None,
    attachments: list[str],
    decision: RouteDecision,
) -> AsyncGenerator[str, None]:
    """Handle general chat with no tools.

    Uses non-streaming Fireworks API. With sufficient max_tokens (600),
    reasoning models like Qwen 3.6 Plus output both reasoning_content
    and a clean final answer in the content field.
    """
    system = _system_context(user_id, location)

    # Trim to recent history
    trimmed = messages[-8:]
    chat_messages = [{"role": item.get("role", "user"), "content": str(item.get("content", ""))} for item in trimmed]

    # Non-streaming call — with 2048 tokens, reasoning models have room to
    # finish their chain-of-thought and output a clean final answer in content
    response = await chat_once(
        chat_messages,
        system=system,
        max_tokens=2048,
        temperature=0.35,
    )

    # Simulate streaming by yielding word-by-word for UI responsiveness
    words = response.split(" ")
    for i, word in enumerate(words):
        prefix = " " if i > 0 else ""
        yield f"{prefix}{word}"
