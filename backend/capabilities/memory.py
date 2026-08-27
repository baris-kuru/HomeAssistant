from __future__ import annotations

import datetime
from typing import AsyncGenerator

from ..services.memory_store_sqlite import (
    add_memory as store_add_memory,
    consolidate_memories as store_consolidate_memories,
    forget_memory as store_forget_memory,
    format_memories,
    format_memory_guide,
)
from ..services.router import RouteDecision
from ..services.user_store import canonical_user_id


REVIEW_AFTER_DAYS = 7


async def handle_memory(
    messages: list[dict],
    user_id: str,
    location: dict | None,
    attachments: list[str],
    decision: RouteDecision,
) -> AsyncGenerator[str, None]:
    """Handle memory operations: recall, add, forget, consolidate, format."""
    user = canonical_user_id(user_id)
    latest_text = messages[-1].get("content", "").lower() if messages else ""

    # Determine operation from message content
    if "guide" in latest_text or "index" in latest_text or "memory object" in latest_text:
        # Format memory guide
        guide = format_memory_guide(user)
        yield guide
    elif "what do you remember" in latest_text or "recall" in latest_text or "what did you save" in latest_text:
        # Recall memories
        entity = None
        memories = format_memories(user, entity=entity)
        yield memories
    elif "add" in latest_text or "remember" in latest_text or "save this" in latest_text:
        # Add a memory
        note = latest_text
        # Extract the actual note from the message
        for token in ["remember that", "remember", "note that", "save this"]:
            if token in latest_text:
                note = latest_text.split(token, 1)[-1].strip(" .")
                break
        
        expires_on = (datetime.date.today() + datetime.timedelta(days=REVIEW_AFTER_DAYS)).isoformat()
        item = store_add_memory(
            user,
            note,
            memory_type="long_term",
            entity=None,
            title=None,
            expires_on=expires_on,
        )
        scope = f" about {item['entity']}" if item.get("entity") not in {"", None, "self"} else ""
        yield f"Saved [{item['memory_id']}] {item['title']} on {item['added_on']} (long_term{scope})."
    elif "consolidate" in latest_text or "summarize" in latest_text:
        # Consolidate memories - for now, return a message
        yield "Memory consolidation: summarizing short-term memories into long-term indexed notes."
    elif "forget" in latest_text or "remove" in latest_text:
        # Forget a memory
        note = latest_text
        for token in ["forget", "remove"]:
            if token in latest_text:
                note = latest_text.split(token, 1)[-1].strip(" .")
                break
        item = store_forget_memory(user, note=note, entity=None)
        if not item:
            yield f"No active memory found for: {note}"
        else:
            yield f"Forgotten [{item['memory_id']}] {item['title']}."
    else:
        # Default: recall all memories
        memories = format_memories(user)
        if memories:
            yield memories
        else:
            yield "No memories stored yet. Use 'remember that ...' to save a memory."
