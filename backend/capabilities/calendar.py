from __future__ import annotations

import datetime
import os
import re
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

from ..services.router import RouteDecision


_caldav_client = None
_WRITABLE_CALENDAR_NAME = os.environ.get("HA_ICLOUD_WRITE_CALENDAR_NAME", "Lobster").strip() or "Lobster"
_LOCAL_TZ = ZoneInfo(os.environ.get("HA_TIMEZONE", "Europe/Berlin"))


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


def _escape_ical(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


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
            f"SUMMARY:{_escape_ical(title)}\r\n"
            f"DTSTART;TZID=Europe/Berlin:{dt.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DTEND;TZID=Europe/Berlin:{dt_end.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DESCRIPTION:{_escape_ical(notes)}\r\n"
            f"UID:{uid}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        calendar.save_event(ical)
        return f"Event '{title}' added on {date} at {time} to {getattr(calendar, 'name', target_name)}."
    except Exception as exc:
        return f"Failed to add event: {exc}"


def _parse_calendar_write(text: str) -> dict[str, str] | None:
    """Extract the common one-shot event requests users actually type."""
    raw = re.sub(r"\s+", " ", text).strip()
    lowered = raw.lower()
    write_intent = re.search(r"\b(add|save|create|schedule|book|put|set up|make|new)\b", lowered)
    event_signal = re.search(r"\b(calendar|event|appointment|meeting|interview|meet)\b", lowered)
    if not write_intent or not event_signal:
        return None

    today = datetime.datetime.now(_LOCAL_TZ).date()
    date = today
    if re.search(r"\btomorrow\b", lowered):
        date = today + datetime.timedelta(days=1)
    elif re.search(r"\btoday\b", lowered):
        date = today
    else:
        iso_match = re.search(r"\b(20\d{2}-\d{1,2}-\d{1,2})\b", raw)
        dot_match = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](20\d{2}))?\b", raw)
        if iso_match:
            try:
                date = datetime.date.fromisoformat(iso_match.group(1))
            except ValueError:
                return None
        elif dot_match:
            day, month, year = dot_match.groups()
            date = datetime.date(int(year or today.year), int(month), int(day))

    time_match = re.search(r"\b(?:at|um)?\s*([01]?\d|2[0-3])(?::|\.)([0-5]\d)\b", lowered)
    if not time_match:
        time_match = re.search(r"\b(?:at|um)\s+([1-9]|1[0-2])\s*(am|pm)\b", lowered)
    if not time_match:
        return None
    if len(time_match.groups()) == 2 and time_match.group(2) in {"am", "pm"}:
        hour = int(time_match.group(1))
        if time_match.group(2) == "pm" and hour != 12:
            hour += 12
        if time_match.group(2) == "am" and hour == 12:
            hour = 0
        time = f"{hour:02d}:00"
    else:
        time = f"{int(time_match.group(1)):02d}:{int(time_match.group(2)):02d}"

    title = ""
    meet_match = re.search(
        r"\bmeet(?:ing)?(?:\s+(?:with|my friend|friend))?\s+(.+?)(?=\s+(?:in|at|on)\b|\s+(?:today|tomorrow)\b|\s+\d{1,2}[:.]|$)",
        raw,
        flags=re.I,
    )
    if meet_match:
        person = re.sub(r"^(?:with|my friend|friend)\s+", "", meet_match.group(1).strip(), flags=re.I)
        title = f"Meet {person}".strip()

    if not title:
        title_source = re.sub(
            r"^.*?\b(?:that|to)\b\s+",
            "",
            raw,
            count=1,
            flags=re.I,
        )
        title_source = re.sub(r"\b(?:at|um)\s+\d{1,2}(?::|\.)\d{2}\b.*$", "", title_source, flags=re.I).strip(" .")
        title = title_source[:80] or "Calendar event"

    location = ""
    location_match = re.search(
        r"\b(?:in|at)\s+(?:a\s+|an\s+|the\s+)?(.+?)(?=\s+(?:at|um)\s+\d{1,2}(?::|\.)\d{2}\b|\s+(?:today|tomorrow)\b|$)",
        raw,
        flags=re.I,
    )
    if location_match and not re.match(r"^\d", location_match.group(1).strip()):
        location = location_match.group(1).strip(" .")

    notes = f"Location: {location}" if location else ""
    return {"title": title, "date": date.isoformat(), "time": time, "notes": notes}


async def handle_calendar(
    messages: list[dict],
    user_id: str,
    location: dict | None,
    attachments: list[str],
    decision: RouteDecision,
) -> AsyncGenerator[str, None]:
    """Handle calendar read/write operations."""
    latest_text = messages[-1].get("content", "") if messages else ""
    lowered = latest_text.lower()

    if any(token in lowered for token in ["add", "save", "create", "schedule", "book", "put", "set up", "new"]):
        parsed = _parse_calendar_write(latest_text)
        if parsed:
            yield _add_event(**parsed)
        else:
            yield "I can add that. Please give me the title, date, and time, for example: \"Meet Hakan today at 18:00\"."
    else:
        # List events
        events = _list_events(7)
        yield events
