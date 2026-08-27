from __future__ import annotations

from dataclasses import dataclass
import datetime
import json
import os
from pathlib import Path
import re
from typing import Any, AsyncGenerator, Awaitable, Callable
import urllib.parse

import certifi
import httpx

from . import devices as dv
from .services.memory_store_sqlite import (
    add_memory as store_add_memory,
    consolidate_memories as store_consolidate_memories,
    forget_memory as store_forget_memory,
    format_memories,
    format_memory_guide,
)
from .services.fireworks_service import chat_once, chat_stream
from .services.fireworks_image import generate_flux_image
from .services.router import RouteDecision, route_request
from .services.search import search_service
from .services.telegram_service import get_telegram_chat_id, send_photo_bytes
from .services.user_store import canonical_user_id, resolve_user, update_password, verify_password


DEFAULT_LAT, DEFAULT_LON = 50.7374, 7.0982
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
ENV_PATH = Path(__file__).parent.parent / ".env"
REVIEW_AFTER_DAYS = 7
ROUTER_DEBUG = os.getenv("ROUTER_DEBUG", "").lower() in {"1", "true", "yes"}


PERSONAS = {
    "baris": """Baris is an AI engineer at BASF in Berlin. Tone: direct, technical, lightly dry, concise, peer-to-peer.""",
}


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any], str, dict | None, list[str]], Awaitable["ToolOutcome"]]


@dataclass(slots=True)
class ToolOutcome:
    content: str
    user: str
    search_payload: dict[str, Any] | None = None


def _today() -> str:
    return datetime.date.today().isoformat()


def _update_env_password(user: str, new_password: str):
    update_password(user, new_password)


async def _fetch_weather(lat: float, lon: float, days: int = 3) -> str:
    params = urllib.parse.urlencode(
        {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
            "forecast_days": min(max(days, 1), 7),
            "timezone": "auto",
        }
    )
    async with httpx.AsyncClient(timeout=12, verify=certifi.where()) as client:
        response = await client.get(f"https://api.open-meteo.com/v1/forecast?{params}")
        response.raise_for_status()
        data = response.json()
    wmo = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Icy fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        80: "Slight showers",
        81: "Moderate showers",
        82: "Heavy showers",
        95: "Thunderstorm",
    }
    cur = data["current"]
    result = [
        f"Now: {wmo.get(cur['weather_code'], 'Unknown')}, {cur['temperature_2m']}°C, humidity {cur['relative_humidity_2m']}%, wind {cur['wind_speed_10m']} km/h",
        "",
        "Forecast:",
    ]
    for i, date in enumerate(data["daily"]["time"]):
        result.append(
            f"  {date}: {wmo.get(data['daily']['weather_code'][i], '?')}, "
            f"{data['daily']['temperature_2m_min'][i]}–{data['daily']['temperature_2m_max'][i]}°C, "
            f"rain {data['daily']['precipitation_sum'][i]}mm"
        )
    return "\n".join(result)


_caldav_client = None
_WRITABLE_CALENDAR_NAME = os.environ.get("HA_ICLOUD_WRITE_CALENDAR_NAME", "Lobster").strip() or "Lobster"


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
    except Exception as exc:
        _caldav_client = None
        return None, f"Calendar error: {exc}"


def _list_events(days: int = 7) -> str:
    calendars, error = _get_caldav()
    if error:
        return error
    start = datetime.datetime.now(datetime.timezone.utc)
    end = start + datetime.timedelta(days=days)
    events = []
    for calendar in calendars:
        try:
            for event in calendar.date_search(start=start, end=end, expand=True):
                try:
                    ical = event.icalendar_instance
                    for component in ical.walk():
                        if component.name != "VEVENT":
                            continue
                        title = str(component.get("SUMMARY", "Untitled"))
                        dtstart = component.get("DTSTART").dt
                        dt_str = dtstart.strftime("%Y-%m-%d %H:%M") if isinstance(dtstart, datetime.datetime) else str(dtstart)
                        calendar_name = str(getattr(calendar, "name", "") or "Unnamed calendar")
                        events.append((dt_str, title, calendar_name))
                except Exception:
                    continue
        except Exception:
            continue
    if not events:
        return f"No events in the next {days} days."
    return "\n".join(f"- [{calendar_name}] {date}: {title}" for date, title, calendar_name in sorted(events))


def _find_calendar(calendars, desired_name: str):
    lowered = desired_name.lower()
    for item in calendars:
        if lowered == str(getattr(item, "name", "")).lower():
            return item
    for item in calendars:
        if lowered in str(getattr(item, "name", "")).lower():
            return item
    return None


def _add_event(title: str, date: str, time: str = "09:00", notes: str = "", calendar_name: str = "") -> str:
    calendars, error = _get_caldav()
    if error:
        return error
    try:
        target_name = _WRITABLE_CALENDAR_NAME
        calendar = _find_calendar(calendars, target_name)
        if calendar is None:
            available = ", ".join(str(getattr(item, "name", "") or "Unnamed calendar") for item in calendars)
            return f'Write calendar "{target_name}" not found. Available calendars: {available}'
        dt = datetime.datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        dt_end = dt + datetime.timedelta(hours=1)
        uid = f"{datetime.datetime.now().timestamp()}@persona"
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            f"SUMMARY:{title}\r\n"
            f"DTSTART;TZID=Europe/Berlin:{dt.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DTEND;TZID=Europe/Berlin:{dt_end.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DESCRIPTION:{notes}\r\n"
            f"UID:{uid}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        calendar.save_event(ical)
        return f"Event '{title}' added on {date} at {time} to {getattr(calendar, 'name', target_name)}."
    except Exception as exc:
        return f"Failed to add event: {exc}"


_converter = None


def _get_converter():
    global _converter
    if _converter is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = True
        options.do_table_structure = True
        _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    return _converter


def _format_tool_result_for_prompt(tool_name: str, content: str) -> str:
    return f"{tool_name} result:\n{content[:3000]}"


def _json_block(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    for candidate in [cleaned, *re.findall(r"\{.*\}", cleaned, flags=re.S)]:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def _persona_text(user: str) -> str:
    return PERSONAS.get(canonical_user_id(user), "Tone: friendly, concise, practical.")


def _system_context(user: str, location: dict | None = None) -> str:
    user = canonical_user_id(user)
    loc_str = f"lat {location['lat']:.4f}, lon {location['lon']:.4f}" if location else "Bonn, Germany (default)"
    if user == "guest":
        return (
            f"You are a home assistant for Fabi and Baris's household in Bonn. Today is {_today()}.\n"
            f"User location: {loc_str}.\n"
            "The current person is not identified yet. Be brief and ask who they are if needed."
        )
    return (
        f"Today is {_today()}.\n"
        f"Current user: {user.capitalize()}.\n"
        f"Location: {loc_str}.\n"
        f"Persona: {_persona_text(user)}\n"
        "Household: Fabi and Baris are a couple in Bonn/Berlin with two cats, Nandi and Pixie.\n"
        f"Memory:\n{format_memories(user)}"
    )


def _tool_catalog(tool_specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tool_specs
    ]


def _recent_history(messages: list[dict]) -> list[dict]:
    trimmed = messages[-8:]
    return [{"role": item.get("role", "user"), "content": str(item.get("content", ""))} for item in trimmed]


def _latest_user_text(messages: list[dict]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user":
            return str(item.get("content", "")).strip()
    return ""


def _answer_chunks(text: str) -> list[str]:
    if len(text) <= 220:
        return [text]
    chunks = re.split(r"(?<=[.!?])\s+", text)
    output: list[str] = []
    current = ""
    for chunk in chunks:
        if len(current) + len(chunk) + 1 <= 220:
            current = f"{current} {chunk}".strip()
            continue
        if current:
            output.append(current)
        current = chunk
    if current:
        output.append(current)
    return output or [text]


async def _tool_get_weather(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    lat = (location or {}).get("lat", DEFAULT_LAT)
    lon = (location or {}).get("lon", DEFAULT_LON)
    return ToolOutcome(await _fetch_weather(lat, lon, args.get("days", 3)), user)


async def _tool_get_calendar_events(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    return ToolOutcome(_list_events(args.get("days", 7)), user)


async def _tool_add_calendar_event(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    result = _add_event(args["title"], args["date"], args.get("time", "09:00"), args.get("notes", ""), args.get("calendar", ""))
    return ToolOutcome(result, user)


async def _tool_list_devices(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    devices = await dv.list_devices()
    return ToolOutcome(json.dumps(devices, indent=2), user)


async def _tool_control_device(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    device_id = args["device"]
    action = args["action"]
    value = args.get("value")
    
    # Map legacy value parameter to params dict
    params = {}
    if value is not None:
        if action in ("set_temperature", "temperature"):
            params = {"temperature": float(value)}
        elif action == "brightness":
            params = {"brightness": int(value)}
    
    result = await dv.control_device(device_id, action, params)
    return ToolOutcome(json.dumps(result, indent=2), user)


async def _tool_recall_memory(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    entity = args.get("entity", "").lower().strip() or None
    return ToolOutcome(format_memories(user, entity=entity), user)


async def _tool_get_memory_guide(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    return ToolOutcome(format_memory_guide(user), user)


async def _tool_add_memory(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    memory_type = args.get("memory_type", "long_term")
    entity = args.get("entity", "").lower().strip() or None
    note = args["note"].strip()
    expires_on = None
    if memory_type == "short_term":
        expires_on = (datetime.date.today() + datetime.timedelta(days=REVIEW_AFTER_DAYS)).isoformat()
    item = store_add_memory(
        user,
        note,
        memory_type=memory_type,
        entity=entity,
        title=args.get("title"),
        expires_on=expires_on,
    )
    scope = f" about {item['entity']}" if item.get("entity") not in {"", None, "self"} else ""
    return ToolOutcome(
        f"Saved [{item['memory_id']}] {item['title']} on {item['added_on']} ({memory_type}{scope}).",
        user,
    )


async def _tool_consolidate_memories(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    entity = args.get("entity", "").lower().strip() or None
    removed = store_consolidate_memories(user, summary=args["summary"], notes_to_remove=args["notes_to_remove"], entity=entity)
    return ToolOutcome(f"Consolidated {removed} short-term items into a new indexed memory.", user)


async def _tool_forget_memory(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    note = args["note"].strip()
    entity = args.get("entity", "").lower().strip() or None
    item = store_forget_memory(user, note=note, entity=entity)
    if not item:
        return ToolOutcome(f"No active memory found for: {note}", user)
    return ToolOutcome(f"Forgotten [{item['memory_id']}] {item['title']}.", user)


async def _tool_switch_user(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    target = canonical_user_id(args["username"])
    resolved = resolve_user(target)
    if resolved.get("id") != target:
        return ToolOutcome(f"Unknown user '{target}'.", user)
    if not verify_password(target, args["password"]):
        return ToolOutcome("Wrong password or password not set.", user)
    return ToolOutcome(f"Switched to {resolved.get('name', target.capitalize())}.", target)


async def _tool_change_password(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    if not verify_password(user, args["current_password"]):
        return ToolOutcome("Current password is wrong.", user)
    _update_env_password(user, args["new_password"])
    return ToolOutcome("Password changed.", user)


async def _tool_list_uploads(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    files = [item.name for item in UPLOADS_DIR.iterdir() if item.is_file()]
    return ToolOutcome(json.dumps(files) if files else "No uploads yet.", user)


def _safe_upload_name(raw: str | None) -> str:
    """Strip directory traversal and disallowed chars."""
    import os, re
    base = os.path.basename(raw or "").strip() or "upload.bin"
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned.lstrip(".") or "upload.bin"


async def _tool_read_upload(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    filename = args.get("filename") or (attachments[-1] if attachments else None)
    if not filename:
        return ToolOutcome("No upload specified.", user)
    # SECURITY: sanitize to prevent path traversal (e.g. ../../../.env)
    safe_name = _safe_upload_name(filename)
    path = UPLOADS_DIR / safe_name
    if not path.exists():
        return ToolOutcome(f"'{safe_name}' not found.", user)
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return ToolOutcome(f"Uploaded image available: {path.name}. This backend is text-first, so ask for a summary request or document upload when possible.", user)
    if suffix in {".pdf", ".docx", ".doc"}:
        result = _get_converter().convert(str(path))
        return ToolOutcome(result.document.export_to_markdown()[:8000], user)
    return ToolOutcome(path.read_text(errors="replace")[:8000], user)


async def _tool_generate_image(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    prompt = str(args.get("prompt", "")).strip()
    if not prompt:
        return ToolOutcome("No prompt provided for image generation.", user)
    quality = str(args.get("quality", "kontext")).strip().lower()
    if quality not in {"schnell", "dev", "kontext"}:
        quality = "kontext"
    try:
        image_bytes = await generate_flux_image(prompt, quality=quality)
    except Exception as exc:
        return ToolOutcome(f"Image generation failed: {exc}", user)

    filename = f"imagine_{int(datetime.datetime.now().timestamp())}.png"
    path = UPLOADS_DIR / filename
    try:
        path.write_bytes(image_bytes)
    except Exception:
        pass

    chat_id = get_telegram_chat_id(user)
    sent = False
    if chat_id:
        sent = await send_photo_bytes(chat_id, image_bytes, caption=prompt[:1024])

    if sent:
        return ToolOutcome(f"Generated image with FLUX {quality} and sent to Telegram.", user)
    return ToolOutcome(
        f"Generated image with FLUX {quality} (saved as {filename}, no Telegram chat linked).",
        user,
    )


async def _tool_search_web(args: dict, user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    query = args.get("query", "").strip()
    if not query:
        return ToolOutcome("No search query provided.", user)
    payload = await search_service.search(
        query=query,
        max_results=args.get("max_results"),
        include_pages=True,
        lane=args.get("lane", "search"),
    )
    lines = []
    for item in payload["results"][:5]:
        lines.append(f"- [{item['title']}]({item['url']}) — {item['snippet']}")
    summary = "\n".join(lines) if lines else "No results found."
    return ToolOutcome(summary, user, search_payload=payload)


WEATHER_TOOL = ToolSpec(
    name="get_weather",
    description="Get the current weather and short forecast for the current location.",
    input_schema={"type": "object", "properties": {"days": {"type": "integer"}}, "required": []},
    handler=_tool_get_weather,
)
CALENDAR_TOOLS = [
    ToolSpec(
        name="get_calendar_events",
        description="List upcoming calendar events.",
        input_schema={"type": "object", "properties": {"days": {"type": "integer"}}, "required": []},
        handler=_tool_get_calendar_events,
    ),
    ToolSpec(
        name="add_calendar_event",
        description="Add a calendar event.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "date": {"type": "string"},
                "time": {"type": "string"},
                "notes": {"type": "string"},
                "calendar": {"type": "string"},
            },
            "required": ["title", "date"],
        },
        handler=_tool_add_calendar_event,
    ),
]
DEVICE_TOOLS = [
    ToolSpec("list_devices", "List all smart home devices and their status.", {"type": "object", "properties": {}, "required": []}, _tool_list_devices),
    ToolSpec(
        "control_device",
        "Control a smart home device.",
        {
            "type": "object",
            "properties": {
                "device": {"type": "string"},
                "action": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["device", "action"],
        },
        _tool_control_device,
    ),
]
MEMORY_TOOLS = [
    ToolSpec("recall_memory", "Read saved memories.", {"type": "object", "properties": {"entity": {"type": "string"}}, "required": []}, _tool_recall_memory),
    ToolSpec("get_memory_guide", "Read the structured memory guide JSON for the current user.", {"type": "object", "properties": {}, "required": []}, _tool_get_memory_guide),
    ToolSpec(
        "add_memory",
        "Save a long-term or short-term memory.",
        {
            "type": "object",
            "properties": {
                "note": {"type": "string"},
                "memory_type": {"type": "string"},
                "entity": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["note", "memory_type"],
        },
        _tool_add_memory,
    ),
    ToolSpec(
        "consolidate_memories",
        "Summarize short-term memories into a long-term note.",
        {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "notes_to_remove": {"type": "array", "items": {"type": "string"}},
                "entity": {"type": "string"},
            },
            "required": ["summary", "notes_to_remove"],
        },
        _tool_consolidate_memories,
    ),
    ToolSpec(
        "forget_memory",
        "Remove a specific memory.",
        {"type": "object", "properties": {"note": {"type": "string"}, "entity": {"type": "string"}}, "required": ["note"]},
        _tool_forget_memory,
    ),
]
IDENTITY_TOOLS = [
    ToolSpec(
        "switch_user",
        "Switch to a different known user.",
        {"type": "object", "properties": {"username": {"type": "string"}, "password": {"type": "string"}}, "required": ["username", "password"]},
        _tool_switch_user,
    ),
    ToolSpec(
        "change_password",
        "Change the current user's password.",
        {"type": "object", "properties": {"current_password": {"type": "string"}, "new_password": {"type": "string"}}, "required": ["current_password", "new_password"]},
        _tool_change_password,
    ),
]
DOCUMENT_TOOLS = [
    ToolSpec("list_uploads", "List uploaded files.", {"type": "object", "properties": {}, "required": []}, _tool_list_uploads),
    ToolSpec(
        "read_upload",
        "Read an uploaded file or document.",
        {"type": "object", "properties": {"filename": {"type": "string"}}, "required": []},
        _tool_read_upload,
    ),
]
SEARCH_TOOL = ToolSpec(
    name="search_web",
    description="Search the web and return compact evidence with links.",
    input_schema={"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
    handler=_tool_search_web,
)
IMAGE_TOOL = ToolSpec(
    name="generate_image",
    description=(
        "Generate an image from a text prompt using Fireworks FLUX and deliver it to the user's "
        "Telegram chat. Use when the user asks to draw, paint, imagine, picture, or generate an image. "
        "Quality: 'schnell' (fast/cheap), 'dev' (balanced), 'kontext' (best, default)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Detailed description of the image"},
            "quality": {"type": "string", "enum": ["schnell", "dev", "kontext"]},
        },
        "required": ["prompt"],
    },
    handler=_tool_generate_image,
)

DOMAIN_TOOL_BUNDLES: dict[str, list[ToolSpec]] = {
    "identity": [],
    "memory": MEMORY_TOOLS,
    "calendar": CALENDAR_TOOLS,
    "devices": DEVICE_TOOLS,
    "documents": DOCUMENT_TOOLS,
    "general": [WEATHER_TOOL, IMAGE_TOOL],
}


def _allowed_tools(decision: RouteDecision, attachments: list[str]) -> list[ToolSpec]:
    tools: list[ToolSpec] = []
    tools.extend(DOMAIN_TOOL_BUNDLES.get(decision.domain, DOMAIN_TOOL_BUNDLES["general"]))
    tools.extend(IDENTITY_TOOLS)
    tools.append(SEARCH_TOOL)
    if attachments and decision.domain != "documents":
        tools.extend(DOCUMENT_TOOLS)
    seen = set()
    deduped = []
    for tool in tools:
        if tool.name in seen:
            continue
        seen.add(tool.name)
        deduped.append(tool)
    return deduped


def _format_search_context(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "No web evidence gathered yet."
    evidence = payload.get("evidence") or []
    if not evidence:
        return "No web evidence gathered yet."
    lines = []
    for item in evidence[:5]:
        lines.append(f"- {item['title']} ({item['url']})\n  {item['text'][:500]}")
    return "\n".join(lines)


def _planner_system(
    *,
    user: str,
    location: dict | None,
    decision: RouteDecision,
    tool_specs: list[ToolSpec],
    search_payload: dict[str, Any] | None,
    tool_journal: list[str],
    attachments: list[str],
) -> str:
    tool_names = ", ".join(tool.name for tool in tool_specs)
    tool_history = "\n\n".join(tool_journal) if tool_journal else "No tool results yet."
    attachment_text = ", ".join(attachments) if attachments else "No pending attachments."
    return f"""You are a compact planner for a home assistant powered by Kimi 2.5.

Return JSON only. No prose outside JSON.

Route:
- lane: {decision.lane}
- domain: {decision.domain}
- reason: {decision.reason}
- confidence: {decision.confidence}

Current context:
{_system_context(user, location)}

Pending attachments: {attachment_text}

Allowed tools:
{json.dumps(_tool_catalog(tool_specs), indent=2)}

Allowed tool names: {tool_names}

Web evidence:
{_format_search_context(search_payload)}

Previous tool results:
{tool_history}

Rules:
- Use at most one tool per response.
- Prefer a direct answer when the user can be answered safely from the route context and evidence.
- If the route domain is {decision.domain}, stay inside that primary domain unless using shared utilities like search_web or identity tools.
- If you need a tool, return:
  {{"type":"tool","tool":"tool_name","args":{{...}}}}
- If you can answer directly, return:
  {{"type":"answer","answer":"short but complete answer in the right user tone"}}
- Never invent tool names.
- When search evidence already answers the question, answer directly instead of searching again.
"""


async def _plan_action(
    *,
    messages: list[dict],
    user: str,
    location: dict | None,
    decision: RouteDecision,
    tool_specs: list[ToolSpec],
    search_payload: dict[str, Any] | None,
    tool_journal: list[str],
    attachments: list[str],
) -> dict[str, Any] | None:
    heuristic = _heuristic_plan(
        latest=_latest_user_text(messages),
        decision=decision,
        tool_specs=tool_specs,
        search_payload=search_payload,
        tool_journal=tool_journal,
        attachments=attachments,
    )
    if heuristic is not None:
        return heuristic

    raw = await chat_once(
        _recent_history(messages),
        system=_planner_system(
            user=user,
            location=location,
            decision=decision,
            tool_specs=tool_specs,
            search_payload=search_payload,
            tool_journal=tool_journal,
            attachments=attachments,
        ),
        max_tokens=260,
        temperature=0.1,
        response_format="json",
    )
    parsed = _json_block(raw)
    if parsed is not None:
        return parsed
    return _heuristic_plan(
        latest=_latest_user_text(messages),
        decision=decision,
        tool_specs=tool_specs,
        search_payload=search_payload,
        tool_journal=tool_journal,
        attachments=attachments,
    )


def _extract_memory_note(text: str) -> str:
    note = re.sub(r"^.*?(remember that|remember|note that)\s*", "", text, flags=re.I).strip()
    note = re.split(r"\b(and then|and tell me|then tell me|please tell me)\b", note, maxsplit=1, flags=re.I)[0].strip(" .")
    return note or text.strip()


def _heuristic_plan(
    *,
    latest: str,
    decision: RouteDecision,
    tool_specs: list[ToolSpec],
    search_payload: dict[str, Any] | None,
    tool_journal: list[str],
    attachments: list[str],
) -> dict[str, Any] | None:
    text = latest.lower().strip()
    allowed = {tool.name for tool in tool_specs}

    if tool_journal:
        return {"type": "answer", "answer": "Use the tool results to answer the user clearly."}

    if decision.domain == "documents" and attachments and "read_upload" in allowed:
        return {"type": "tool", "tool": "read_upload", "args": {"filename": attachments[-1]}}

    if decision.use_search and search_payload:
        return {"type": "answer", "answer": "Answer using the gathered search evidence with concise citations."}

    if decision.use_search and "search_web" in allowed:
        query = latest.replace("/think", "").strip()
        return {"type": "tool", "tool": "search_web", "args": {"query": query, "lane": decision.lane}}

    if decision.domain == "memory":
        if any(token in text for token in ["memory guide", "memory index", "guide json", "memory objects"]) and "get_memory_guide" in allowed:
            return {"type": "tool", "tool": "get_memory_guide", "args": {}}
        if any(token in text for token in ["remember", "note that", "save this"]) and "add_memory" in allowed:
            return {
                "type": "tool",
                "tool": "add_memory",
                "args": {"note": _extract_memory_note(latest), "memory_type": "long_term"},
            }
        if any(token in text for token in ["what did you save", "what do you remember", "recall", "tell me what you saved"]) and "recall_memory" in allowed:
            return {"type": "tool", "tool": "recall_memory", "args": {}}

    if decision.domain == "calendar":
        if any(token in text for token in ["what's on", "events", "calendar", "schedule"]) and "get_calendar_events" in allowed:
            return {"type": "tool", "tool": "get_calendar_events", "args": {"days": 7}}

    if decision.domain == "devices":
        if "turn on" in text and "control_device" in allowed:
            return {"type": "tool", "tool": "control_device", "args": {"device": latest.replace("turn on", "").strip(), "action": "on"}}
        if "turn off" in text and "control_device" in allowed:
            return {"type": "tool", "tool": "control_device", "args": {"device": latest.replace("turn off", "").strip(), "action": "off"}}
        if "list_devices" in allowed:
            return {"type": "tool", "tool": "list_devices", "args": {}}

    if "weather" in text and "get_weather" in allowed:
        return {"type": "tool", "tool": "get_weather", "args": {"days": 3}}

    if "generate_image" in allowed and any(
        token in text for token in ("draw ", "paint ", "imagine ", "picture of", "image of", "generate image", "generate an image", "make an image")
    ):
        # Strip command prefix; the LLM planner would also work here, but a
        # direct heuristic keeps latency low for the common phrasing.
        stripped = re.sub(r"^\s*(please\s+)?(draw|paint|imagine|generate|make)\s+(me\s+)?(an?\s+)?(image|picture)?\s*(of\s+)?", "", latest, flags=re.I).strip()
        return {"type": "tool", "tool": "generate_image", "args": {"prompt": stripped or latest, "quality": "kontext"}}

    return {"type": "answer", "answer": "Answer directly and keep it concise."}


def _answer_system(user: str, location: dict | None, decision: RouteDecision, search_payload: dict[str, Any] | None, tool_journal: list[str]) -> str:
    citations = "When web evidence is present, cite sources inline using markdown links." if search_payload else "No citations needed unless clearly useful."
    tool_history = "\n\n".join(tool_journal) if tool_journal else "No tools were used."
    return f"""{_system_context(user, location)}

Route lane: {decision.lane}
Route domain: {decision.domain}
{citations}

Web evidence:
{_format_search_context(search_payload)}

Tool results:
{tool_history}

Write the final user-facing answer only.
"""


async def _stream_final_answer(messages: list[dict], user: str, location: dict | None, decision: RouteDecision, search_payload: dict[str, Any] | None, tool_journal: list[str]) -> AsyncGenerator[str, None]:
    async for chunk in chat_stream(
        _recent_history(messages),
        system=_answer_system(user, location, decision, search_payload, tool_journal),
        max_tokens=420,
        temperature=0.35,
    ):
        yield chunk


async def _execute_tool(tool: ToolSpec, args: dict[str, Any], user: str, location: dict | None, attachments: list[str]) -> ToolOutcome:
    try:
        return await tool.handler(args, user, location, attachments)
    except Exception as exc:
        return ToolOutcome(f"Error: {exc}", user)


async def run_agent(
    messages: list,
    user: str,
    location: dict | None = None,
    attachments: list[str] | None = None,
    decision: RouteDecision | None = None,
    max_tool_rounds: int | None = None,
) -> AsyncGenerator[dict, None]:
    user = canonical_user_id(user)
    attachments = [item for item in (attachments or []) if item]
    if decision is None:
        decision = await route_request(messages, attachments=attachments)
    tool_specs = _allowed_tools(decision, attachments)
    tool_map = {tool.name: tool for tool in tool_specs}
    current_user = user
    tool_journal: list[str] = []
    search_payload: dict[str, Any] | None = None

    yield {"type": "thinking"}
    if ROUTER_DEBUG:
        yield {"type": "status", "content": f"route: {decision.lane}/{decision.domain} ({decision.reason})"}

    if decision.use_search and decision.queries:
        yield {"type": "tool_call", "name": "search_web"}
        search_payload = await search_service.search(
            queries=decision.queries,
            include_pages=True,
            lane=decision.lane,
        )
        tool_journal.append(_format_tool_result_for_prompt("search_web", _format_search_context(search_payload)))

    if max_tool_rounds is not None:
        max_rounds = max_tool_rounds
    elif decision.lane == "deep":
        max_rounds = 2
    else:
        max_rounds = 1
    tool_rounds = 0

    while True:
        plan = await _plan_action(
            messages=messages,
            user=current_user,
            location=location,
            decision=decision,
            tool_specs=tool_specs,
            search_payload=search_payload,
            tool_journal=tool_journal,
            attachments=attachments,
        )

        if not plan:
            fallback = "I ran into a planning hiccup, so I’m giving you the best direct answer I can."
            for chunk in _answer_chunks(fallback):
                yield {"type": "text", "content": chunk}
            return

        if plan.get("type") == "answer":
            answer = str(plan.get("answer", "")).strip() or "I’m not fully sure, but that’s the best answer I can give right now."
            if tool_journal:
                async for chunk in _stream_final_answer(messages, current_user, location, decision, search_payload, tool_journal):
                    yield {"type": "text", "content": chunk}
            else:
                for chunk in _answer_chunks(answer):
                    yield {"type": "text", "content": chunk}
            return

        if plan.get("type") != "tool" or tool_rounds >= max_rounds:
            async for chunk in _stream_final_answer(messages, current_user, location, decision, search_payload, tool_journal):
                yield {"type": "text", "content": chunk}
            return

        tool_name = str(plan.get("tool", "")).strip()
        args = plan.get("args") if isinstance(plan.get("args"), dict) else {}
        tool = tool_map.get(tool_name)
        if not tool:
            async for chunk in _stream_final_answer(messages, current_user, location, decision, search_payload, tool_journal):
                yield {"type": "text", "content": chunk}
            return

        yield {"type": "tool_call", "name": tool_name}
        outcome = await _execute_tool(tool, args, current_user, location, attachments)
        if tool_name == "switch_user" and outcome.user != current_user and outcome.content.startswith("Switched to"):
            current_user = outcome.user
            yield {"type": "user_switched", "user": current_user}
        else:
            current_user = outcome.user
        if outcome.search_payload:
            search_payload = outcome.search_payload
        tool_journal.append(_format_tool_result_for_prompt(tool_name, outcome.content))
        tool_rounds += 1

        if decision.lane == "fast" and tool_name in {
            "add_memory",
            "recall_memory",
            "get_memory_guide",
            "forget_memory",
            "consolidate_memories",
            "get_calendar_events",
            "add_calendar_event",
            "switch_user",
            "change_password",
        }:
            for chunk in _answer_chunks(outcome.content):
                yield {"type": "text", "content": chunk}
            return
