"""
Auto-memory capture: silently extracts memory-worthy content from conversations
after the assistant responds.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .memory_store_sqlite import SqlMemoryStore


MEMORY_WORTHY_PATTERNS = [
    # Explicit saving phrases
    r'\bremember that\b.*?\b[.!?,;]',
    r'\bremember\b\s+\bthe\b\s+.*?\b[.!?,;]',
    r'\bnote that\b.*?\b[.!?,;]',
    r'\bsave this\b[:\s].*?\b[.!?,;]',
    
    # Implicit facts
    r'\bI work at\b\s+.*?\b[.!?,;]',
    r'\bI live in\b\s+.*?\b[.!?,;]',
    r'\bI prefer\b\s+.*?\b[.!?,;]',
    r'\bI (like|love|hate|dislike)\b\s+.*?\b[.!?,;]',
    r'\bI usually\b\s+.*?\b[.!?,;]',
    r'\bI always\b\s+.*?\b[.!?,;]',
    r'\bI never\b\s+.*?\b[.!?,;]',
    r'\bI (try to|want to|hope to|plan to|need to)\b\s+.*?\b[.!?,;]',
    
    # Relationships
    r'\bmy (friend|partner|wife|husband|colleague|boss|doctor|dentist)\b\s+.*?\b[.!?,;]',
    r'\bmy name is\b\s+.*?\b[.!?,;]',
    r'\bI am a\b\s+.*?\b[.!?,;]',
    r'\bI\'?m\s+a\s+.*?\b[.!?,;]',
]


def _extract_sentences(text: str) -> List[str]:
    """Split text into sentences."""
    sentences = re.split(r'[.!?]+', text)
    return [s.strip() for s in sentences if s.strip()]


def _score_memory_candidate(sentence: str) -> float:
    """
    Heuristic score for whether a sentence contains memory-worthy content.
    Returns 0.0-1.0
    """
    score = 0.0
    lower = sentence.lower()
    
    # High signal patterns
    if re.search(r'\b(my|I)\s+\w+\s+(is|are|like|love|hate|want|need|plan|prefer|usually|often)\b', lower):
        score += 0.4
    if re.search(r'\bremember\b', lower):
        score += 0.3
    if re.search(r'\bnote that\b', lower):
        score += 0.3
    
    # Medium signal
    if lower.startswith('i '):
        score += 0.15
    if 'because ' in lower:
        score += 0.1
    if any(word in lower for word in ['always', 'never', 'usually', 'often']):
        score += 0.15
    
    # Penalize questions and commands
    if sentence.endswith('?'):
        score -= 0.2
    if lower.startswith(('can you', 'please', 'could you')):
        score -= 0.15
    
    # Penalize very short sentences
    if len(sentence.split()) < 4:
        score -= 0.2
    if len(sentence.split()) > 30:
        score -= 0.1  # Penalize overly long
    
    return max(0.0, min(score, 1.0))


def _extract_entity(sentence: str, user_id: str) -> Optional[str]:
    """Try to extract an entity from the memory sentence."""
    lower = sentence.lower()
    
    # Check for person/entity mentions
    patterns = [
        (r'\bmy\s+(\w+)\b', lambda m: m.group(1) if m.group(1) in ['friend', 'partner', 'wife', 'husband', 'colleague', 'boss'] else None),
        (r'\b(?:friend|partner|wife|husband|colleague)\s+(?:is\s+|called\s+|named\s+)(\w+)', lambda m: m.group(1)),
        (r'\b(?:work at|works at)\s+([A-Z][a-zA-Z\s&]+?)(?:\.|[!?,;]|$)', lambda m: m.group(1).strip() if m else None),
        (r'\b(?:live in|lives in)\s+([A-Z][a-zA-Z\s]+?)(?:\.|[!?,;]|$)', lambda m: m.group(1).strip() if m else None),
    ]
    
    for pattern, extractor in patterns:
        match = re.search(pattern, sentence)
        if match:
            entity = extractor(match)
            if entity:
                return entity
    
    # If no entity found, use user_id
    return user_id


def capture_memories_auto(
    user_id: str,
    conversation_history: List[Dict[str, str]],
    assistant_response: str
) -> List[Dict[str, Any]]:
    """
    Analyze conversation for memory-worthy content and auto-save to short-term memory.
    
    Args:
        user_id: The current user ID
        conversation_history: List of message dicts with 'role' and 'content'
        assistant_response: The assistant's response text
    
    Returns:
        List of captured memory dicts
    """
    captured_memories = []
    all_text = " ".join([msg.get('content', '') for msg in conversation_history[-6:]])  # Last 6 messages
    sentences = _extract_sentences(all_text)
    
    for sentence in sentences:
        score = _score_memory_candidate(sentence)
        if score >= 0.7:
            # Extract entity
            entity = _extract_entity(sentence, user_id)
            
            # Avoid duplicates
            title = " ".join(sentence.split()[:6])
            if any(title in m.get('content', '') for m in captured_memories):
                continue
                
            try:
                memory = SqlMemoryStore.add_memory(
                    user_id=user_id,
                    note=sentence.strip(),
                    memory_type="short_term",
                    entity=entity or "self",
                    title=title
                )
                captured_memories.append(memory)
            except Exception as e:
                print(f"Auto-memory capture error: {e}")
    
    return captured_memories


def _get_memory_from_id(memory_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single memory by ID for the modal."""
    rows = SqlMemoryStore.get_memories(user_id)
    for memory in rows:
        if str(memory.get('id', '')) == str(memory_id):
            return memory
    return None


def delete_memory_by_id(memory_id: str, user_id: str) -> bool:
    """Delete a memory by its ID."""
    # SQL query to delete by ID
    from .db import execute
    try:
        cursor = execute("DELETE FROM memories WHERE id = ? AND user_id = ?", (int(memory_id), user_id))
        return cursor.rowcount > 0
    except Exception as e:
        print(f"Delete memory error: {e}")
        return False
