import json
import os
import re
import datetime
import urllib.request
import urllib.parse
from pathlib import Path
from typing import AsyncGenerator
import anthropic
from . import devices as dv

# ── Weather ──

WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Moderate showers", 82: "Heavy showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

DEFAULT_LAT, DEFAULT_LON = 50.7374, 7.0982  # Bonn

def _fetch_weather(lat: float, lon: float, days: int = 3) -> str:
    params = urllib.parse.urlencode({
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
        "forecast_days": min(max(days, 1), 7),
        "timezone": "auto",
    })
    import ssl, certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{params}", timeout=10, context=ctx) as r:
        data = json.loads(r.read())
    cur = data["current"]
    result = [
        f"Now: {WMO.get(cur['weather_code'], 'Unknown')}, "
        f"{cur['temperature_2m']}°C, "
        f"humidity {cur['relative_humidity_2m']}%, "
        f"wind {cur['wind_speed_10m']} km/h",
        "",
        "Forecast:",
    ]
    daily = data["daily"]
    for i, date in enumerate(daily["time"]):
        result.append(
            f"  {date}: {WMO.get(daily['weather_code'][i], '?')}, "
            f"{daily['temperature_2m_min'][i]}–{daily['temperature_2m_max'][i]}°C, "
            f"rain {daily['precipitation_sum'][i]}mm"
        )
    return "\n".join(result)

# ── Calendar ──

_caldav_client = None

def _get_caldav():
    global _caldav_client
    username = os.environ.get("ICLOUD_USERNAME", "")
    password = os.environ.get("ICLOUD_APP_PASSWORD", "")
    if not username or not password:
        return None, "Calendar not configured — add ICLOUD_USERNAME and ICLOUD_APP_PASSWORD to .env"
    try:
        if _caldav_client is None:
            import caldav
            _caldav_client = caldav.DAVClient(
                url="https://caldav.icloud.com",
                username=username,
                password=password,
            )
        return _caldav_client.principal().calendars(), None
    except Exception as e:
        _caldav_client = None
        return None, f"Calendar error: {e}"

SHARED_CALENDAR = "canni und fabi"

def _list_events(days: int = 7, user: str = "cani") -> str:
    cals, err = _get_caldav()
    if err:
        return err
    start = datetime.datetime.now(datetime.timezone.utc)
    end = start + datetime.timedelta(days=days)
    cals = [c for c in cals if SHARED_CALENDAR in str(getattr(c, "name", "")).lower()] or cals
    events = []
    for cal in cals:
        try:
            for ev in cal.date_search(start=start, end=end, expand=True):
                try:
                    ical = ev.icalendar_instance
                    for component in ical.walk():
                        if component.name != "VEVENT":
                            continue
                        title = str(component.get("SUMMARY", "Untitled"))
                        dtstart = component.get("DTSTART").dt
                        dt_str = dtstart.strftime("%Y-%m-%d %H:%M") if isinstance(dtstart, datetime.datetime) else str(dtstart)
                        events.append((dt_str, title))
                except Exception:
                    continue
        except Exception:
            pass
    if not events:
        return f"No events in the next {days} days."
    return "\n".join(f"- {d}: {t}" for d, t in sorted(events))

def _find_calendar(cals, name: str):
    name_lower = name.lower()
    for cal in cals:
        try:
            cal_name = str(cal.name).lower()
            if name_lower in cal_name or cal_name in name_lower:
                return cal
        except Exception:
            pass
    return cals[0]  # fallback to first

def _add_event(title: str, date: str, time: str = "09:00", notes: str = "", calendar: str = "") -> str:
    cals, err = _get_caldav()
    if err:
        return err
    try:
        cal = _find_calendar(cals, calendar) if calendar else cals[0]
        dt = datetime.datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        dt_end = dt + datetime.timedelta(hours=1)
        uid = f"{datetime.datetime.now().timestamp()}@homeassistant"
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            f"SUMMARY:{title}\r\n"
            f"DTSTART;TZID=Europe/Berlin:{dt.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DTEND;TZID=Europe/Berlin:{dt_end.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DESCRIPTION:{notes}\r\n"
            f"UID:{uid}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        cal.save_event(ical)
        cal_name = getattr(cal, 'name', calendar or 'default')
        return f"Event '{title}' added to '{cal_name}' on {date} at {time}."
    except Exception as e:
        return f"Failed to add event: {e}"
_converter = None

def _get_converter():
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import InputFormat
        opts = PdfPipelineOptions()
        opts.do_ocr = True
        opts.do_table_structure = True
        _converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    return _converter

client = anthropic.AsyncAnthropic()
MODEL = "claude-sonnet-4-6"

MEMORIES_DIR = Path(__file__).parent.parent / "memories"
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
ENV_PATH = Path(__file__).parent.parent / ".env"

REVIEW_AFTER_DAYS = 7


def _today() -> str:
    return datetime.date.today().isoformat()


def _load_memory(user: str) -> dict:
    path = MEMORIES_DIR / f"{user.lower()}.json"
    if not path.exists():
        return {"long_term": [], "short_term": [], "entities": {}}
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return {"long_term": data, "short_term": [], "entities": {}}
    return data


def _save_memory(user: str, data: dict):
    path = MEMORIES_DIR / f"{user.lower()}.json"
    path.write_text(json.dumps(data, indent=2))


def _expiry() -> str:
    return (datetime.date.today() + datetime.timedelta(days=REVIEW_AFTER_DAYS)).isoformat()


def _active_short_term(items: list) -> list:
    today = datetime.date.today()
    return [i for i in items if datetime.date.fromisoformat(i.get("expires", "9999-12-31")) >= today]


def _is_due(item: dict) -> bool:
    added = item.get("added", _today())
    age = (datetime.date.today() - datetime.date.fromisoformat(added)).days
    return age >= REVIEW_AFTER_DAYS


def _format_memory(mem: dict) -> str:
    parts = []
    lt = mem.get("long_term", [])
    if lt:
        parts.append("Long-term:\n" + "\n".join(f"- {n}" for n in lt))

    st = mem.get("short_term", [])
    if st:
        lines = []
        for i in st:
            prefix = "[due for review] " if _is_due(i) else ""
            lines.append(f"- {prefix}{i['note']} (added {i['added']})")
        parts.append("Short-term:\n" + "\n".join(lines))

    for name, edata in mem.get("entities", {}).items():
        elt = edata.get("long_term", [])
        est = edata.get("short_term", [])
        if elt or est:
            lines = [f"  - {n}" for n in elt]
            for i in est:
                prefix = "[due for review] " if _is_due(i) else ""
                lines.append(f"  - {prefix}{i['note']} (added {i['added']})")
            parts.append(f"{name.capitalize()}:\n" + "\n".join(lines))

    return "\n\n".join(parts) if parts else "No memories yet."


def _update_env_password(user: str, new_password: str):
    key = f"{user.upper()}_PASSWORD"
    text = ENV_PATH.read_text()
    text = re.sub(rf"^{key}=.*$", f"{key}={new_password}", text, flags=re.MULTILINE)
    ENV_PATH.write_text(text)
    os.environ[key] = new_password


PERSONAS = {
    "fabi": """Fabi is a PhD researcher in neurobiology, studying the molecular triggers of autism. She's creative and artistic — she paints with gouache, loves drawing, is drawn to Van Gogh and expressionism, miniature objects/rooms, and pastel colors. She's a morning person (up at 7am, coffee first), nurtures a lot of plants, and has a thoughtful, curious nature.

Tone for Fabi: warm, intellectually curious, gently playful. You can make light references to science, art, or her plants. Don't be overly chirpy. She appreciates nuance and a bit of depth. Keep responses concise but not cold.""",

    "cani": """Cani (pronounced like "Johnny") is an AI engineer at BASF in Berlin, building AI applications. He partially lives in Berlin (shared apartment) and visits Fabi in Bonn regularly. He's a night owl, prefers cooler temps and dim lights. He built this home assistant himself and likes to tinker with it.

Tone for Cani: casual, direct, peer-to-peer. He's technical so you can be straightforward and skip the hand-holding. A dry sense of humour is welcome. Don't be overly warm — he's more of a "just give me the info" type.""",
}

def _system(user: str, location: dict = None) -> str:
    loc_str = f"lat {location['lat']:.4f}, lon {location['lon']:.4f}" if location else "Bonn, Germany (default)"
    if user == "guest":
        return (
            f"You are a home assistant for Fabi and Cani's household in Bonn. Today is {_today()}. "
            f"User location: {loc_str}. "
            "You don't know who you're talking to yet — greet them and ask. "
            "Use the switch_user tool to log in a known user."
        )
    mem = _load_memory(user)
    persona = PERSONAS.get(user, "")
    return f"""You are a home assistant for Fabi and Cani's household in Bonn. Today is {_today()}.

Current user: {user.capitalize()}

--- About {user.capitalize()} ---
{persona}

--- Location ---
{loc_str}

--- Household ---
Fabi and Cani are a couple. Fabi lives in Bonn, Cani splits between Berlin and Bonn.
Two cats: Nandi and Pixie — British Shorthair twin sisters, born April 2024.
Nandi is larger and timid but very affectionate once comfortable. Pixie is more energetic and clever.
Both cats are closer to Fabi as she's lived with them longer.

--- Memory for {user.capitalize()} ---
{_format_memory(mem)}

--- Guidelines ---
- Match the tone described above for this user.
- Reference the cats, household, and personal details naturally when relevant.
- Proactively use add_memory for anything worth remembering.
  memory_type="short_term" for recent/temporary things, "long_term" for lasting facts.
  Use entity= to attach to a cat, person, or object (e.g. entity="nandi", entity="fabi").
- When you see short-term memories marked [due for review], call consolidate_memories.
- To switch users, use the switch_user tool."""


TOOLS = [
    {
        "name": "get_weather",
        "description": "Get current weather and forecast for the user's location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Forecast days (1–7), default 3"},
            },
            "required": [],
        },
    },
    {
        "name": "get_calendar_events",
        "description": "List upcoming Apple Calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "How many days ahead to look, default 7"},
            },
            "required": [],
        },
    },
    {
        "name": "add_calendar_event",
        "description": "Add an event to Apple Calendar. Defaults to the shared 'Canni und Fabi' calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "HH:MM, default 09:00"},
                "notes": {"type": "string"},
                "calendar": {"type": "string", "description": "Calendar name, e.g. 'Fabi' or 'Canni'. Defaults to current user's calendar."},
            },
            "required": ["title", "date"],
        },
    },
    {
        "name": "list_devices",
        "description": "List all smart home devices and their current status.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "control_device",
        "description": "Control a smart home device (lights, thermostat, vacuum, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "device": {"type": "string"},
                "action": {"type": "string", "description": "on / off / brightness / temperature / lock / unlock / start / stop"},
                "value": {"type": "string", "description": "Optional value"},
            },
            "required": ["device", "action"],
        },
    },
    {
        "name": "recall_memory",
        "description": "Read memories for the current user. Optionally filter by entity (e.g. 'nandi', 'pixie').",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Optional: cat, person, or object name"},
            },
            "required": [],
        },
    },
    {
        "name": "add_memory",
        "description": "Save a memory for the current user. long_term = lasting fact. short_term = temporary observation (expires in 7 days). Use entity to attach to a specific cat, person, or object.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string"},
                "memory_type": {"type": "string", "enum": ["long_term", "short_term"]},
                "entity": {"type": "string", "description": "Optional: e.g. 'nandi', 'pixie', 'fabi'"},
            },
            "required": ["note", "memory_type"],
        },
    },
    {
        "name": "consolidate_memories",
        "description": "Summarize short-term memories marked [due for review] into a long-term note, then remove them. Call this when you see short-term items due for review — write a concise summary of what's worth keeping.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Concise long-term note summarising the reviewed short-term items"},
                "notes_to_remove": {"type": "array", "items": {"type": "string"}, "description": "Exact note texts to remove from short-term"},
                "entity": {"type": "string", "description": "Optional: entity these memories belong to"},
            },
            "required": ["summary", "notes_to_remove"],
        },
    },
    {
        "name": "forget_memory",
        "description": "Remove a specific memory note by its exact text, optionally from an entity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string"},
                "entity": {"type": "string"},
            },
            "required": ["note"],
        },
    },
    {
        "name": "switch_user",
        "description": "Switch the active user after verifying their password.",
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "fabi or cani"},
                "password": {"type": "string"},
            },
            "required": ["username", "password"],
        },
    },
    {
        "name": "change_password",
        "description": "Change the current user's password after verifying the existing one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_password": {"type": "string"},
                "new_password": {"type": "string"},
            },
            "required": ["current_password", "new_password"],
        },
    },
    {
        "name": "list_uploads",
        "description": "List uploaded files.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_upload",
        "description": "Read an uploaded file (PDF, DOCX, image, or text).",
        "input_schema": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
]


def _run_tool(name: str, args: dict, user: str, location: dict = None) -> tuple[str | list, str]:
    try:
        if name == "get_weather":
            lat = (location or {}).get("lat", DEFAULT_LAT)
            lon = (location or {}).get("lon", DEFAULT_LON)
            return _fetch_weather(lat, lon, args.get("days", 3)), user

        elif name == "get_calendar_events":
            return _list_events(args.get("days", 7), user), user

        elif name == "add_calendar_event":
            calendar = args.get("calendar", "Canni und Fabi")
            return _add_event(args["title"], args["date"], args.get("time", "09:00"), args.get("notes", ""), calendar), user

        elif name == "list_devices":
            return json.dumps(dv.list_devices(), indent=2), user

        elif name == "control_device":
            return dv.control_device(args["device"], args["action"], args.get("value")), user

        elif name == "recall_memory":
            mem = _load_memory(user)
            entity = args.get("entity", "").lower().strip()
            if entity:
                edata = mem.get("entities", {}).get(entity, {})
                lt = edata.get("long_term", [])
                st = _active_short_term(edata.get("short_term", []))
                if not lt and not st:
                    return f"No memories about {entity}.", user
                parts = []
                if lt:
                    parts.append("Long-term:\n" + "\n".join(f"- {n}" for n in lt))
                if st:
                    parts.append("Recent:\n" + "\n".join(f"- {i['note']}" for i in st))
                return "\n".join(parts), user
            return _format_memory(mem), user

        elif name == "add_memory":
            mem = _load_memory(user)
            memory_type = args.get("memory_type", "long_term")
            entity = args.get("entity", "").lower().strip()
            note = args["note"]

            if entity:
                if entity not in mem["entities"]:
                    mem["entities"][entity] = {"long_term": [], "short_term": []}
                if memory_type == "short_term":
                    mem["entities"][entity]["short_term"].append({"note": note, "added": _today(), "expires": _expiry()})
                else:
                    mem["entities"][entity]["long_term"].append(note)
            else:
                if memory_type == "short_term":
                    mem["short_term"].append({"note": note, "added": _today(), "expires": _expiry()})
                else:
                    mem["long_term"].append(note)

            _save_memory(user, mem)
            scope = f" about {entity}" if entity else ""
            return f"Saved ({memory_type}{scope}): {note}", user

        elif name == "consolidate_memories":
            mem = _load_memory(user)
            entity = args.get("entity", "").lower().strip()
            to_remove = set(args["notes_to_remove"])

            if entity:
                edata = mem.get("entities", {}).get(entity, {})
                edata["short_term"] = [i for i in edata.get("short_term", []) if i["note"] not in to_remove]
                edata["long_term"].append(args["summary"])
            else:
                mem["short_term"] = [i for i in mem["short_term"] if i["note"] not in to_remove]
                mem["long_term"].append(args["summary"])

            _save_memory(user, mem)
            return f"Consolidated {len(to_remove)} short-term items into long-term: {args['summary']}", user

        elif name == "forget_memory":
            mem = _load_memory(user)
            note = args["note"]
            entity = args.get("entity", "").lower().strip()

            if entity:
                edata = mem.get("entities", {}).get(entity, {})
                edata["long_term"] = [n for n in edata.get("long_term", []) if n != note]
                edata["short_term"] = [i for i in edata.get("short_term", []) if i["note"] != note]
            else:
                mem["long_term"] = [n for n in mem["long_term"] if n != note]
                mem["short_term"] = [i for i in mem["short_term"] if i["note"] != note]

            _save_memory(user, mem)
            return f"Forgotten: {note}", user

        elif name == "switch_user":
            target = args["username"].lower()
            expected = os.environ.get(f"{target.upper()}_PASSWORD", "")
            if not expected:
                return f"Unknown user '{target}'.", user
            if args["password"] != expected:
                return "Wrong password.", user
            return f"Switched to {target.capitalize()}.", target

        elif name == "change_password":
            expected = os.environ.get(f"{user.upper()}_PASSWORD", "")
            if args["current_password"] != expected:
                return "Current password is wrong.", user
            _update_env_password(user, args["new_password"])
            return "Password changed.", user

        elif name == "list_uploads":
            files = [f.name for f in UPLOADS_DIR.iterdir() if f.is_file()]
            return (json.dumps(files) if files else "No uploads yet."), user

        elif name == "read_upload":
            path = UPLOADS_DIR / args["filename"]
            if not path.exists():
                return f"'{args['filename']}' not found.", user
            if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                import base64, io
                from PIL import Image as PILImage
                img = PILImage.open(path)
                img.thumbnail((800, 800))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=70)
                data = base64.standard_b64encode(buf.getvalue()).decode()
                return [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                    {"type": "text", "text": f"Uploaded image: {path.name}"},
                ], user
            if path.suffix.lower() in {".pdf", ".docx", ".doc"}:
                result = _get_converter().convert(str(path))
                return result.document.export_to_markdown()[:8000], user
            return path.read_text(errors="replace")[:8000], user

        return f"Unknown tool: {name}", user
    except Exception as e:
        return f"Error: {e}", user


async def run_agent(messages: list, user: str, location: dict = None) -> AsyncGenerator[dict, None]:
    history = list(messages)
    current_user = user

    while True:
        yield {"type": "thinking"}

        async with client.messages.stream(
            model=MODEL,
            max_tokens=4096,
            system=_system(current_user, location),
            tools=TOOLS,
            messages=history,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                    yield {"type": "text", "content": event.delta.text}
            final = await stream.get_final_message()

        history.append({"role": "assistant", "content": final.content})

        if final.stop_reason != "tool_use":
            break

        tool_results = []
        for block in final.content:
            if block.type == "tool_use":
                yield {"type": "tool_call", "name": block.name}
                result, current_user = _run_tool(block.name, block.input, current_user, location)
                if block.name == "switch_user" and "Switched to" in result:
                    yield {"type": "user_switched", "user": current_user}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        history.append({"role": "user", "content": tool_results})
