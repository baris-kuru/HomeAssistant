from __future__ import annotations

from typing import AsyncGenerator

from .. import devices as dv
from ..services.router import RouteDecision


async def handle_devices(
    messages: list[dict],
    user_id: str,
    location: dict | None,
    attachments: list[str],
    decision: RouteDecision,
) -> AsyncGenerator[str, None]:
    """Handle smart home device operations."""
    import json

    latest_text = messages[-1].get("content", "").lower() if messages else ""

    if "list" in latest_text or "what" in latest_text or "show" in latest_text:
        # List devices
        devices = await dv.list_devices()
        yield json.dumps(devices, indent=2)
    elif "turn on" in latest_text or "turn off" in latest_text or "set" in latest_text:
        # Control device - for now return a message
        yield "Device control is available. Please specify: device name, action (on/off/set), and optional value."
    else:
        # Default: list devices
        devices = await dv.list_devices()
        yield json.dumps(devices, indent=2)
