"""Tuya smart device integration via local network (tinytuya)."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Device cache
_device_cache: list[dict[str, Any]] = []
_device_objects: dict[str, Any] = {}
_last_scan: float = 0
_CACHE_TTL = 60  # seconds


def _scan_devices() -> list[dict[str, Any]]:
    """Discover Tuya devices on the local network."""
    global _device_cache, _device_objects, _last_scan

    now = time.time()
    if now - _last_scan < _CACHE_TTL and _device_cache:
        return _device_cache

    try:
        import tinytuya

        logger.info("Scanning for Tuya devices...")
        devices = tinytuya.deviceScan()

        result = []
        for dev_id, dev_info in devices.items():
            device_type = dev_info.get("type", "unknown")
            ip = dev_info.get("ip", "")
            version = dev_info.get("version", 3.3)

            try:
                if device_type == "BulbDevice":
                    tuya_device = tinytuya.BulbDevice(dev_id, ip, key="")
                    tuya_device.set_version(version)
                    state = tuya_device.status()

                    result.append(
                        {
                            "id": dev_id,
                            "name": state.get("dps", {}).get("1", "Unknown Bulb"),
                            "type": "light",
                            "state": "on" if state.get("dps", {}).get("1") else "off",
                            "brightness": state.get("dps", {}).get("2", 0),
                            "color_temp": state.get("dps", {}).get("3"),
                            "ip": ip,
                        }
                    )
                    _device_objects[dev_id] = tuya_device

                elif device_type in ("OutletDevice", "SwitchDevice"):
                    tuya_device = tinytuya.OutletDevice(dev_id, ip, key="")
                    tuya_device.set_version(version)
                    state = tuya_device.status()

                    result.append(
                        {
                            "id": dev_id,
                            "name": state.get("dps", {}).get("1", "Unknown Plug"),
                            "type": "switch",
                            "state": "on" if state.get("dps", {}).get("1") else "off",
                            "ip": ip,
                        }
                    )
                    _device_objects[dev_id] = tuya_device
                else:
                    result.append(
                        {
                            "id": dev_id,
                            "name": f"Unknown Tuya Device ({dev_id})",
                            "type": "unknown",
                            "state": "unknown",
                            "ip": ip,
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to get status for device {dev_id}: {e}")
                continue

        _device_cache = result
        _last_scan = now
        logger.info(f"Found {len(result)} Tuya devices")
        return result

    except ImportError:
        logger.error("tinytuya not installed. Run: pip install tinytuya")
        return []
    except Exception as e:
        logger.error(f"Failed to scan Tuya devices: {e}")
        return _device_cache or []


async def list_devices() -> list[dict[str, Any]]:
    """List all Tuya devices."""
    return _scan_devices()


async def control_device(
    device_id: str, action: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Control a Tuya device."""
    params = params or {}

    import tinytuya

    devices = _scan_devices()
    device_obj = _device_objects.get(device_id)

    if not device_obj:
        for dev in devices:
            if dev["id"] == device_id:
                device_obj = _device_objects.get(dev["id"])
                break

    if not device_obj:
        return {"success": False, "error": f"Device {device_id} not found"}

    try:
        if action == "on":
            device_obj.turn_on()
            return {"success": True, "device_id": device_id, "action": "on"}

        elif action == "off":
            device_obj.turn_off()
            return {"success": True, "device_id": device_id, "action": "off"}

        elif action == "set_brightness" and "brightness" in params:
            if isinstance(device_obj, tinytuya.BulbDevice):
                device_obj.set_brightness(params["brightness"])
                return {
                    "success": True,
                    "device_id": device_id,
                    "action": "set_brightness",
                }
            return {
                "success": False,
                "error": "Brightness control only available for bulbs",
            }

        elif action == "set_color_temp" and "color_temp" in params:
            if isinstance(device_obj, tinytuya.BulbDevice):
                device_obj.set_colourtemp(params["color_temp"])
                return {
                    "success": True,
                    "device_id": device_id,
                    "action": "set_color_temp",
                }
            return {
                "success": False,
                "error": "Color temp control only available for bulbs",
            }

        elif action == "set_color" and "color" in params:
            if isinstance(device_obj, tinytuya.BulbDevice):
                device_obj.set_colour(params["color"])
                return {"success": True, "device_id": device_id, "action": "set_color"}
            return {
                "success": False,
                "error": "Color control only available for bulbs",
            }

        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        logger.error(f"Failed to control device {device_id}: {e}")
        return {"success": False, "error": str(e)}


async def get_device_info(device_id: str) -> dict[str, Any] | None:
    """Get detailed info about a specific device."""
    devices = await list_devices()
    for device in devices:
        if device["id"] == device_id:
            return device
    return None
