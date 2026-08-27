from __future__ import annotations

from .calendar import handle_calendar
from .devices import handle_devices
from .documents import handle_documents
from .general import handle_general
from .identity import handle_identity
from .memory import handle_memory
from .weather import handle_weather

# Map domain names to handler functions
CAPABILITY_HANDLERS: dict[str, callable] = {
    "calendar": handle_calendar,
    "devices": handle_devices,
    "documents": handle_documents,
    "general": handle_general,
    "identity": handle_identity,
    "memory": handle_memory,
    "weather": handle_weather,
}

__all__ = [
    "CAPABILITY_HANDLERS",
    "handle_calendar",
    "handle_devices",
    "handle_documents",
    "handle_general",
    "handle_identity",
    "handle_memory",
    "handle_weather",
]
