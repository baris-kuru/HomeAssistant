"""Home Assistant integration via REST API."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import certifi

logger = logging.getLogger(__name__)

# Config from environment
HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}


async def get_states() -> list[dict[str, Any]]:
    """Get all entity states from Home Assistant."""
    if not HA_TOKEN:
        logger.warning("HA_TOKEN not set, returning empty states")
        return []
    
    try:
        async with httpx.AsyncClient(timeout=10, verify=certifi.where()) as client:
            response = await client.get(f"{HA_URL}/api/states", headers=HEADERS)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to get HA states: {e}")
        return []


async def get_entity_state(entity_id: str) -> dict[str, Any] | None:
    """Get state of a specific entity."""
    if not HA_TOKEN:
        return None
    
    try:
        async with httpx.AsyncClient(timeout=10, verify=certifi.where()) as client:
            response = await client.get(
                f"{HA_URL}/api/states/{entity_id}",
                headers=HEADERS
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to get HA entity {entity_id}: {e}")
        return None


async def call_service(domain: str, service: str, data: dict[str, Any]) -> bool:
    """Call a Home Assistant service."""
    if not HA_TOKEN:
        logger.warning("HA_TOKEN not set, skipping service call")
        return False
    
    try:
        async with httpx.AsyncClient(timeout=10, verify=certifi.where()) as client:
            response = await client.post(
                f"{HA_URL}/api/services/{domain}/{service}",
                headers=HEADERS,
                json=data
            )
            response.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"Failed to call HA service {domain}.{service}: {e}")
        return False


async def turn_on(entity_id: str) -> bool:
    """Turn on a light/switch."""
    return await call_service("homeassistant", "turn_on", {"entity_id": entity_id})


async def turn_off(entity_id: str) -> bool:
    """Turn off a light/switch."""
    return await call_service("homeassistant", "turn_off", {"entity_id": entity_id})


async def set_temperature(entity_id: str, temperature: float) -> bool:
    """Set thermostat temperature."""
    return await call_service("climate", "set_temperature", {
        "entity_id": entity_id,
        "temperature": temperature
    })


async def set_brightness(entity_id: str, brightness: int) -> bool:
    """Set light brightness (0-255)."""
    return await call_service("light", "turn_on", {
        "entity_id": entity_id,
        "brightness": brightness
    })


async def get_energy_stats() -> dict[str, Any]:
    """Get energy consumption stats from Home Assistant energy dashboard."""
    states = await get_states()
    energy_entities = [s for s in states if s["entity_id"].startswith("sensor.") and "energy" in s["entity_id"]]
    
    stats = {}
    for entity in energy_entities:
        stats[entity["entity_id"]] = {
            "state": entity["state"],
            "unit": entity.get("attributes", {}).get("unit_of_measurement", ""),
            "friendly_name": entity.get("attributes", {}).get("friendly_name", entity["entity_id"])
        }
    
    return stats
