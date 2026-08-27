import json

_state = {
    "living_room_light":  {"name": "Living Room Light",    "type": "light",      "on": True,  "brightness": 75},
    "kitchen_light":      {"name": "Kitchen Light",         "type": "light",      "on": False, "brightness": 100},
    "fabi_bedroom_light": {"name": "Fabi's Bedroom Light",  "type": "light",      "on": False, "brightness": 50},
    "cani_bedroom_light": {"name": "Cani's Bedroom Light",  "type": "light",      "on": True,  "brightness": 30},
    "bathroom_light":     {"name": "Bathroom Light",        "type": "light",      "on": False, "brightness": 100},
    "thermostat":         {"name": "Thermostat",            "type": "thermostat", "current_temp": 21.2, "target_temp": 22.0, "mode": "heating"},
    "front_door":         {"name": "Front Door",            "type": "lock",       "locked": True},
    "robot_vacuum":       {"name": "Robot Vacuum",          "type": "vacuum",     "status": "docked", "battery": 92, "last_clean": "today 10:15"},
    "tv":                 {"name": "TV",                    "type": "tv",         "on": False, "app": "Netflix"},
    "cat_feeder":         {"name": "Cat Feeder",            "type": "feeder",     "last_fed": "13:00", "next_feed": "19:00", "food_level": 68},
    "cat_fountain":       {"name": "Cat Water Fountain",    "type": "fountain",   "on": True,  "water_level": 55},
}


def _find(name: str):
    key = name.lower().replace(" ", "_")
    if key in _state:
        return key
    for k in _state:
        if name.lower() in k or k in name.lower():
            return k
    return None


def list_devices() -> list:
    return list(_state.values())


def control_device(name: str, action: str, value=None) -> str:
    key = _find(name)
    if not key:
        return f"Device '{name}' not found."
    d = _state[key]
    action = action.lower()
    if action == "on":
        d["on"] = True
    elif action == "off":
        d["on"] = False
    elif action == "brightness" and value is not None:
        d["brightness"] = int(value)
    elif action in ("set_temp", "temperature") and value is not None:
        d["target_temp"] = float(value)
    elif action == "lock":
        d["locked"] = True
    elif action == "unlock":
        d["locked"] = False
    elif action == "start":
        d["status"] = "cleaning"
    elif action == "stop":
        d["status"] = "docked"
    else:
        return f"Unknown action '{action}' for {d['name']}."
    return f"{d['name']}: {action}" + (f" → {value}" if value else "")
