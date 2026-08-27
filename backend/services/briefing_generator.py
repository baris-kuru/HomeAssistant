from __future__ import annotations

import datetime
import os
import urllib.parse

import certifi
import httpx

from .fireworks_service import chat_once
from .memory_store_sqlite import SqlMemoryStore
from .conversation_store import ConversationStore
from .user_store import resolve_user


def _today() -> str:
    return datetime.date.today().isoformat()


def _yesterday() -> str:
    return (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def _greeting(user_id: str) -> str:
    user = resolve_user(user_id)
    name = user.get("name", user_id.capitalize())
    return f"Good morning, {name}!"


async def _get_weather_context(user_id: str) -> str:
    """Get today's weather forecast for the user's location."""
    user = resolve_user(user_id)
    location = user.get("location", {})
    lat = location.get("lat", 50.7374)
    lon = location.get("lon", 7.0982)

    params = urllib.parse.urlencode(
        {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 1,
            "timezone": "auto",
        }
    )
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
    try:
        async with httpx.AsyncClient(timeout=12, verify=certifi.where()) as client:
            response = await client.get(f"https://api.open-meteo.com/v1/forecast?{params}")
            response.raise_for_status()
            data = response.json()
        daily = data.get("daily", {})
        if not daily.get("time"):
            return "No weather forecast available."
        code = daily["weather_code"][0]
        high = daily["temperature_2m_max"][0]
        low = daily["temperature_2m_min"][0]
        precip = daily.get("precipitation_probability_max", [0])[0]
        condition = wmo.get(code, "Unknown")
        rain_note = f" Rain chance: {precip}%." if precip > 20 else " No rain expected."
        return f"{condition}, {high}°C high / {low}°C low.{rain_note}"
    except Exception:
        return "Weather forecast unavailable."


async def _get_calendar_context(user_id: str) -> str:
    """Get today's calendar events."""
    username = os.environ.get("ICLOUD_USERNAME", "")
    password = os.environ.get("ICLOUD_APP_PASSWORD", "")
    if not username or not password:
        return ""

    try:
        import caldav

        client = caldav.DAVClient(
            url="https://caldav.icloud.com",
            username=username,
            password=password,
        )
        calendars = client.principal().calendars()
    except Exception:
        return ""

    today = datetime.date.today()
    start = datetime.datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=datetime.timezone.utc)
    end = start + datetime.timedelta(days=1)

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
                        if isinstance(dtstart, datetime.datetime):
                            time_str = dtstart.strftime("%H:%M")
                        elif isinstance(dtstart, datetime.date):
                            time_str = "All day"
                        else:
                            time_str = str(dtstart)
                        events.append((time_str, title))
                except Exception:
                    continue
        except Exception:
            continue

    if not events:
        return "No events scheduled today."

    return "\n".join(f"• {time_str} - {title}" for time_str, title in sorted(events))


async def _get_memory_delta(user_id: str) -> str:
    """Get memories added or updated since yesterday."""
    yesterday = _yesterday()
    memories = SqlMemoryStore.get_memories(user_id)

    delta = [m for m in memories if m.get("added_on", "") >= yesterday]

    if not delta:
        return ""

    lines = []
    for m in delta[:5]:
        entity_label = ""
        entity = m.get("entity")
        if entity and entity not in ("", "self"):
            entity_label = f" [{entity}]"
        title = m.get("title", "")
        content = m.get("content", "")
        lines.append(f"• {title}{entity_label} — {content}")

    return "\n".join(lines)


async def _get_recent_context(user_id: str) -> str:
    """Get last 3 conversations for context."""
    conv_store = ConversationStore()
    conversations = conv_store.get_recent_conversations(user_id, limit=3)

    if not conversations:
        return ""

    lines = []
    for conv in conversations:
        title = conv.get("title", "")
        if not title:
            continue
        domain = conv.get("domain", "")
        domain_label = f" ({domain})" if domain else ""
        lines.append(f"• {title}{domain_label}")

    return "\n".join(lines)


async def _get_device_context(user_id: str) -> str:
    """Get notable device states (lights on, temp anomalies, etc.)."""
    from ..devices import list_devices

    devices = await list_devices()
    alerts = []

    for device in devices:
        dtype = device.get("type", "")
        dname = device.get("name", "")

        if dtype == "light" and device.get("on"):
            brightness = device.get("brightness", 100)
            dim_note = f" (dim, {brightness}%)" if brightness < 50 else ""
            alerts.append(f"💡 {dname} is on{dim_note}")
        elif dtype == "thermostat":
            temp = device.get("current_temp", 20)
            if temp > 26 or temp < 16:
                alerts.append(f"🌡️ {dname}: {temp}°C (out of range)")
        elif dtype == "feeder":
            food_level = device.get("food_level", 100)
            if food_level < 20:
                alerts.append(f"🍽️ Cat feeder low ({food_level}%)")
        elif dtype == "fountain":
            water_level = device.get("water_level", 100)
            if water_level < 30:
                alerts.append(f"💧 Cat fountain low ({water_level}%)")
        elif dtype == "vacuum":
            battery = device.get("battery", 100)
            if battery < 30:
                alerts.append(f"🤖 Vacuum needs charging ({battery}%)")

    if not alerts:
        return ""

    return "\n".join(alerts)


async def _get_mood_context(user_id: str) -> str:
    """Get recent mood entries to inform tone."""
    import json
    from pathlib import Path

    mood_file = Path(__file__).parent.parent / "mood" / f"{user_id}.json"
    if not mood_file.exists():
        return ""

    try:
        moods = json.loads(mood_file.read_text())
        if not moods:
            return ""

        # Get last 3 days of mood
        recent = moods[-3:]
        avg_mood = sum(m.get("score", 5) for m in recent) / len(recent)

        if avg_mood < 4:
            return "🧠 Recent mood has been low — keep tone gentle and supportive"
        elif avg_mood > 7:
            return "🧠 Recent mood has been high — tone can be energetic and playful"
        else:
            return "🧠 Mood has been neutral — keep tone warm and balanced"
    except Exception:
        return ""


async def _get_habit_context(user_id: str) -> str:
    """Get habit progress for the week."""
    import json
    from pathlib import Path

    habits_file = Path(__file__).parent.parent / "habits" / f"{user_id}.json"
    if not habits_file.exists():
        return ""

    try:
        data = json.loads(habits_file.read_text())
        habits = data.get("habits", {})
        logs = data.get("logs", [])

        if not habits or not logs:
            return ""

        # Get this week's logs
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())

        week_logs = [log for log in logs if datetime.fromisoformat(log["date"]).date() >= week_start]

        if not week_logs:
            return ""

        # Summarize
        habit_counts = {}
        for log in week_logs:
            habit_name = log.get("habit", "unknown")
            habit_counts[habit_name] = habit_counts.get(habit_name, 0) + 1

        summaries = []
        for habit_name, count in habit_counts.items():
            if count >= 5:
                summaries.append(f"✅ {habit_name}: {count}/7 days (great streak!)")
            elif count >= 3:
                summaries.append(f"📊 {habit_name}: {count}/7 days (on track)")
            else:
                summaries.append(f"⚠️ {habit_name}: {count}/7 days (needs attention)")

        return "\n".join(summaries)
    except Exception:
        return ""


async def _get_conversation_themes(user_id: str) -> str:
    """Get themes from recent conversations."""
    conv_store = ConversationStore()
    conversations = conv_store.get_recent_conversations(user_id, limit=5)

    if not conversations:
        return ""

    # Extract domains/topics
    domains = [conv.get("domain", "") for conv in conversations if conv.get("domain")]

    if not domains:
        return ""

    # Count frequency
    from collections import Counter
    domain_counts = Counter(domains)

    top_topics = domain_counts.most_common(3)
    topics_str = ", ".join(f"{topic} ({count}x)" for topic, count in top_topics)

    return f"🗣️ Recent conversation themes: {topics_str}"


def _clean_briefing(text: str) -> str:
    """Strip qwen reasoning. Return "" if the output is leaked reasoning so the
    caller falls back to the deterministic template briefing."""
    import re
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    head = text.lower()[:160]
    reasoning_markers = (
        "thinking process", "let me", "deconstruct", "analyze user input",
        "**analyze", "here's a", "here is a", "draft generation", "mental refinement",
    )
    if any(marker in head for marker in reasoning_markers):
        return ""
    return text.strip()


async def _synthesize_briefing(
    user_id: str,
    weather: str,
    calendar: str,
    memory_delta: str,
    recent_context: str,
    device_context: str = "",
    mood_context: str = "",
    habit_context: str = "",
    conversation_themes: str = "",
) -> str:
    """Use LLM to synthesize all context into a warm, personalized briefing."""
    user = resolve_user(user_id)
    safe_id = str(user_id or user.get("id") or "there")
    name = user.get("name") or safe_id.capitalize()
    persona_map = {
        "baris": "direct, technical, dry humour, concise",
    }
    tone = persona_map.get(safe_id.lower(), "friendly and concise")

    # Build context sections dynamically
    sections = []

    if weather:
        sections.append(f"**Today's Weather**\n{weather}")

    if calendar:
        sections.append(f"**Today's Calendar**\n{calendar}")
    elif calendar == "":
        sections.append("**Today's Calendar**\nNo events scheduled.")

    if memory_delta:
        sections.append(f"**What's On Your Mind**\n{memory_delta}")

    if device_context:
        sections.append(f"**Home Status**\n{device_context}")

    if habit_context:
        sections.append(f"**Habit Progress**\n{habit_context}")

    if conversation_themes:
        sections.append(f"**Recent Conversations**\n{conversation_themes}")

    context_text = "\n\n".join(sections) if sections else "No specific context available."

    # Build mood guidance line
    mood_line = f"\n{mood_context}" if mood_context else ""

    prompt = f"""You are writing a morning briefing for {name}. Keep it warm, concise, and actionable.

Tone: {tone}{mood_line}

Context available:
{context_text}

Write a morning briefing in markdown format. It must:
1. Start with a greeting like "☀️ Good morning, {name}!"
2. Synthesize the context into a coherent narrative (not just a list)
3. Highlight what matters most today
4. End with a brief encouragement or gentle reminder
5. Stay under 4000 characters total
6. Be specific — mention names, times, projects
7. Use markdown formatting (bold headers, bullet points)
8. If mood context suggests low mood, be extra supportive; if high, be energetic

Return ONLY the briefing text. No preamble, no JSON, no explanation.
"""

    try:
        result = await chat_once(
            [{"role": "user", "content": prompt}],
            max_tokens=2500,
            temperature=0.3,
        )
        cleaned = _clean_briefing(result)
        if cleaned:
            return cleaned
        raise ValueError("empty briefing after cleaning")
    except Exception:
        # Fallback: construct a plain-text briefing
        greeting = f"☀️ {_greeting(user_id)}"
        parts = [greeting, ""]

        if weather:
            parts.append(f"🌤️ **Today's Weather**\n{weather}\n")
        if calendar and calendar != "":
            parts.append(f"📅 **Today's Calendar**\n{calendar}\n")
        if memory_delta:
            parts.append(f"🧠 **What's On Your Mind**\n{memory_delta}\n")
        if device_context:
            parts.append(f"🏠 **Home Status**\n{device_context}\n")

        parts.append("\nHave a wonderful day!")
        return "\n".join(parts)


class BriefingGenerator:
    """Generates 'While You Slept' morning briefings."""

    @staticmethod
    async def generate_briefing(user_id: str) -> str:
        """
        Generate a personalized morning briefing for the given user.

        The briefing includes:
        1. Weather forecast for today
        2. Calendar events for today
        3. Memory delta (what changed since yesterday)
        4. Recent conversation context
        5. Device state anomalies (home context)
        6. Mood-aware tone guidance
        7. Habit progress for the week
        8. Top conversation themes

        Returns: Formatted markdown text for Telegram
        """
        weather = await _get_weather_context(user_id)
        calendar = await _get_calendar_context(user_id)
        memory_delta = await _get_memory_delta(user_id)
        recent_context = await _get_recent_context(user_id)

        # New context sources
        device_context = await _get_device_context(user_id)
        mood_context = await _get_mood_context(user_id)
        habit_context = await _get_habit_context(user_id)
        conversation_themes = await _get_conversation_themes(user_id)

        return await _synthesize_briefing(
            user_id=user_id,
            weather=weather,
            calendar=calendar,
            memory_delta=memory_delta,
            recent_context=recent_context,
            device_context=device_context,
            mood_context=mood_context,
            habit_context=habit_context,
            conversation_themes=conversation_themes,
        )
