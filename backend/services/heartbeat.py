from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from pathlib import Path

from .briefing_generator import BriefingGenerator
from .telegram_service import send_message, send_voice, get_telegram_chat_id
from .user_store import load_users, resolve_user
from ..tts import synthesize
from .memory_store_sqlite import SqlMemoryStore
from .conversation_store import ConversationStore
from .db import get_connection

logger = logging.getLogger(__name__)

_last_briefing_date: dict[str, datetime.date] = {}


class BriefingScheduler:
    """Simple scheduler wrapper for briefing tracking."""

    @staticmethod
    def get_last_sent(user_id: str) -> datetime.date | None:
        return _last_briefing_date.get(user_id)

    @staticmethod
    def mark_sent(user_id: str) -> None:
        _last_briefing_date[user_id] = datetime.date.today()


briefing_scheduler = BriefingScheduler()


class Heartbeat:
    """Unified scheduler for Persona's autonomous agent loop."""

    BEATS = {
        "tick":          {"interval": 60,    "last_run": 0},
        "reminder":      {"interval": 86400,  "last_run": 0},   # MUTED: log-only, once/day
        "consolidation": {"interval": 900,    "last_run": 0},   # silent (no Telegram)
        "context":       {"interval": 3600,  "last_run": 0},
        "briefing":      {"interval": 86400, "last_run": 0},   # MUTED: mark handled only, user must request explicitly
        "maintenance":   {"interval": 86400, "last_run": 0},
        "calendar_reminder": {"interval": 86400, "last_run": 0},  # MUTED: log-only, once/day
        "memory_nudge":      {"interval": 86400, "last_run": 0},  # MUTED: log-only, once/day
        "device_alert":      {"interval": 86400, "last_run": 0},  # MUTED: log-only, once/day
        "router_eval":       {"interval": 86400, "last_run": 0},
    }

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        """Start the heartbeat loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started")

    async def stop(self):
        """Stop the heartbeat loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Heartbeat stopped")

    async def _run_loop(self):
        """Main loop: wake every 60s, check which beats are due, run them."""
        while self._running:
            try:
                now = datetime.datetime.now().timestamp()
                for beat_name, config in self.BEATS.items():
                    if now - config["last_run"] >= config["interval"]:
                        config["last_run"] = now
                        try:
                            handler_name = f"_beat_{beat_name}"
                            handler = getattr(self, handler_name, None)
                            if handler:
                                await handler()
                        except Exception as e:
                            logger.error(f"Heartbeat {beat_name} failed: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
            await asyncio.sleep(60)

    async def _beat_tick(self):
        """Health check: SQLite responsive, log pulse."""
        try:
            conn = get_connection()
            conn.execute("SELECT 1")
            logger.debug("Heartbeat tick: OK")
        except Exception as e:
            logger.error(f"Heartbeat tick: SQLite unresponsive: {e}")

    async def _beat_reminder(self):
        """Check reminders/*.json for due items, send via Telegram, mark done."""
        reminders_dir = Path(__file__).parent.parent.parent / "reminders"
        if not reminders_dir.exists():
            return

        for reminder_file in reminders_dir.glob("*.json"):
            user_id = reminder_file.stem  # e.g., "baris" from "baris.json"
            if user_id.startswith("telegram:"):
                continue

            try:
                data = json.loads(reminder_file.read_text())
                if not isinstance(data, list):
                    continue

                changed = False
                now = datetime.datetime.now()
                for reminder in data:
                    if reminder.get("done"):
                        continue

                    due_str = reminder.get("due", "")
                    if not self._is_due(due_str, now):
                        continue

                    # MUTED: Auto-messages disabled. User must ask explicitly.
                    # Telegram send suppressed — logging reminder instead.
                    # telegram_chat_id = get_telegram_chat_id(user_id)
                    # if not telegram_chat_id:
                    #     logger.debug(f"No Telegram chat ID for {user_id}, skipping reminder")
                    #     continue
                    # text = reminder.get("text", "")
                    # message = f"⏰ <b>Reminder</b>\n{text}"
                    # await send_message(telegram_chat_id, message)
                    text = reminder.get("text", "")
                    logger.info(f"[MUTED REMINDER] Would send to {user_id}: {text}")

                    reminder["done"] = True
                    changed = True
                    logger.info(f"Sent reminder to {user_id}: {text}")

                if changed:
                    reminder_file.write_text(json.dumps(data, indent=2))
            except Exception as e:
                logger.error(f"Reminder processing failed for {reminder_file}: {e}")

    def _is_due(self, due_str: str, now: datetime.datetime) -> bool:
        """Check if a reminder is due. Handles 'YYYY-MM-DD' and 'YYYY-MM-DD HH:MM' formats."""
        try:
            if len(due_str) == 10:
                # "YYYY-MM-DD" → due at end of that day
                target = datetime.datetime.strptime(f"{due_str}T23:59:59", "%Y-%m-%dT%H:%M:%S")
            else:
                # "YYYY-MM-DD HH:MM" → exact time
                target = datetime.datetime.strptime(due_str.replace(" ", "T") + ":00", "%Y-%m-%dT%H:%M:%S")
            return target <= now
        except (ValueError, AttributeError):
            return False

    async def _beat_consolidation(self):
        """Find short-term memories >7 days old, auto-consolidate if >3 for same entity."""
        users = load_users()
        for user_id in users:
            if user_id.startswith("telegram:"):
                continue

            due = SqlMemoryStore.get_short_term_due_for_review(user_id)
            if len(due) >= 3:
                # Group by entity
                by_entity: dict[str, list] = {}
                for item in due:
                    entity = item.get("entity") or "general"
                    by_entity.setdefault(entity, []).append(item)

                for entity, items in by_entity.items():
                    if len(items) >= 3:
                        # Create summary
                        notes = [i["content"] for i in items]
                        summary = f"Consolidated {len(items)} memories about {entity}: " + "; ".join(notes[:3])
                        notes_to_remove = [i["content"] for i in items]

                        SqlMemoryStore.consolidate_memories(
                            user_id=user_id,
                            summary=summary,
                            notes_to_remove=notes_to_remove,
                            entity=entity if entity != "general" else None,
                        )
                        logger.info(f"Auto-consolidated {len(items)} memories for {user_id} about {entity}")

    async def _beat_context(self):
        """Pre-fetch weather cache, check calendar for next 2hr events."""
        # For now, this is a no-op. Future: cache weather, prepare proactive nudges.
        logger.debug("Context beat: no-op for now")

    async def _beat_briefing(self):
        """Send morning briefings once per day, after the configured time."""
        now = datetime.datetime.now()
        today = now.date()
        users = load_users()

        for user_id, user_data in users.items():
            if user_id.startswith("telegram:"):
                continue
            if not isinstance(user_data, dict):
                continue

            briefing_time = user_data.get("briefing_time", "07:30")
            try:
                hour, minute = map(int, briefing_time.split(":"))
            except (ValueError, AttributeError):
                hour, minute = 7, 30

            # Check if we already sent a briefing to this user today
            if _last_briefing_date.get(user_id) == today:
                continue

            # Check if the configured time has passed today
            briefing_time_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now < briefing_time_today:
                continue  # Too early, wait until next tick

            # MUTED: Auto-messages disabled. User must request explicitly.
            # Only mark as "handled" so scheduling doesn't pile up; no Telegram is sent.
            if now.weekday() >= 5 and not user_data.get("briefing_on_weekends", False):
                _last_briefing_date[user_id] = today  # Mark as "handled" even if skipped
                logger.info(f"[MUTED BRIEFING] Available for {user_id} (skipped: weekend, user must request explicitly).")
                continue

            # Generate briefing text but DO NOT send via Telegram
            try:
                briefing = await BriefingGenerator.generate_briefing(user_id)
                if briefing:
                    _last_briefing_date[user_id] = today  # Mark as handled
                    logger.info(f"[MUTED BRIEFING] Available for {user_id}. User must request it explicitly.")
                else:
                    logger.warning(f"Briefing generator returned empty for {user_id}")
            except Exception as e:
                logger.error(f"Briefing generation (muted) failed for {user_id}: {e}")

    async def _beat_maintenance(self):
        """Prune expired memories, archive old conversations, VACUUM SQLite."""
        # Prune expired short-term memories (older than 30 days)
        cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
        conn = get_connection()
        cursor = conn.execute(
            "DELETE FROM memories WHERE memory_type = 'short_term' AND expires_on < ?",
            (cutoff,)
        )
        if cursor.rowcount > 0:
            logger.info(f"Pruned {cursor.rowcount} expired memories")
            conn.commit()

        # Archive conversations older than 90 days
        cutoff = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
        cursor = conn.execute(
            "UPDATE conversations SET is_active = 0 WHERE started_at < ? AND is_active = 1",
            (cutoff,)
        )
        if cursor.rowcount > 0:
            logger.info(f"Archived {cursor.rowcount} old conversations")
            conn.commit()

        # VACUUM SQLite (reclaim space)
        try:
            conn.execute("VACUUM")
            logger.debug("SQLite VACUUM complete")
        except Exception as e:
            logger.warning(f"SQLite VACUUM failed: {e}")

    async def _beat_calendar_reminder(self):
        """Check iCloud calendar for events starting in the next 2 hours and send Telegram reminders."""
        username = os.environ.get("ICLOUD_USERNAME", "")
        password = os.environ.get("ICLOUD_APP_PASSWORD", "")
        if not username or not password:
            return

        try:
            import caldav
            client = caldav.DAVClient(
                url="https://caldav.icloud.com",
                username=username,
                password=password,
            )
            calendars = client.principal().calendars()
        except Exception:
            return

        now = datetime.datetime.now()
        soon = now + datetime.timedelta(hours=2)
        reminded_today = self._get_reminded_today()

        for calendar in calendars:
            try:
                events = calendar.date_search(start=now, end=soon, expand=True)
                for event in events:
                    try:
                        ical = event.icalendar_instance
                        for component in ical.walk():
                            if component.name != "VEVENT":
                                continue

                            title = str(component.get("SUMMARY", "Untitled"))
                            dtstart = component.get("DTSTART")
                            if not dtstart:
                                continue

                            dtstart_val = dtstart.dt
                            if isinstance(dtstart_val, datetime.date) and not isinstance(dtstart_val, datetime.datetime):
                                # All-day event - skip for time-based reminders
                                continue

                            event_key = f"{title}_{dtstart_val.isoformat()}"
                            if event_key in reminded_today:
                                continue

                            minutes_until = (dtstart_val - now).total_seconds() / 60
                            # Remind 30 minutes before event start
                            if 15 <= minutes_until <= 30:
                                users = load_users()
                                for user_id in users:
                                    if user_id.startswith("telegram:"):
                                        continue
                                    # MUTED: Auto-messages disabled. User must ask explicitly.
                                    time_str = dtstart_val.strftime("%H:%M")
                                    reminded_today.add(event_key)
                                    logger.info(
                                        f"[MUTED CALENDAR REMINDER] Would send to {user_id}: "
                                        f"{title} at {time_str} (in {int(minutes_until)} minutes)"
                                    )

                                self._save_reminded_today(reminded_today)
                    except Exception as e:
                        logger.debug(f"Event processing error: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Calendar search error: {e}")
                continue

    def _get_reminded_today(self) -> set:
        """Get set of reminded event keys for today."""
        today = datetime.date.today().isoformat()
        if not hasattr(self, "_calendar_reminders"):
            self._calendar_reminders = {}
        return self._calendar_reminders.get(today, set())

    def _save_reminded_today(self, reminded: set):
        """Save reminded event keys for today."""
        today = datetime.date.today().isoformat()
        if not hasattr(self, "_calendar_reminders"):
            self._calendar_reminders = {}
        self._calendar_reminders[today] = reminded

    async def _beat_memory_nudge(self):
        """Nudge users about stale short-term memories (3+ items, oldest >3 days) that should be consolidated."""
        users = load_users()
        nudge_threshold_days = 3
        nudge_min_count = 3

        for user_id in users:
            if user_id.startswith("telegram:"):
                continue

            # Get short-term memories
            memories = SqlMemoryStore.get_memories(user_id, memory_type="short_term")
            if not memories:
                continue

            # Group by entity
            by_entity: dict[str, list] = {}
            for m in memories:
                entity = m.get("entity") or "general"
                by_entity.setdefault(entity, []).append(m)

            # Check for stale groups (3+ memories, oldest >3 days)
            now = datetime.date.today()
            nudge_key_prefix = f"memory_nudge_{user_id}"

            for entity, items in by_entity.items():
                if len(items) < nudge_min_count:
                    continue

                oldest_date = min(
                    datetime.date.fromisoformat(m["added_on"])
                    for m in items
                    if m.get("added_on")
                )
                days_old = (now - oldest_date).days

                if days_old >= nudge_threshold_days:
                    nudge_key = f"{nudge_key_prefix}_{entity}"
                    if self._already_reminded(nudge_key):
                        continue

                    # MUTED: Auto-messages disabled. User must ask explicitly.
                    self._mark_reminded(nudge_key)
                    logger.info(
                        f"[MUTED MEMORY NUDGE] Would send to {user_id} for {entity}: "
                        f"{len(items)} memories from {days_old} days ago"
                    )

    async def _beat_device_alert(self):
        """Check mock devices for unusual states and alert via Telegram."""
        try:
            from ..devices import list_devices
            devices = await list_devices()
        except ImportError:
            return

        alerted_devices = self._get_alerted_devices()

        for device in devices:
            device_id = device.get("id", "") or device.get("name", "")
            device_type = device.get("type", "")
            anomalies = []

            # Check lights that have been on for >12 hours
            if device_type == "light" and device.get("on"):
                last_changed = device.get("last_changed")
                if last_changed:
                    try:
                        on_since = datetime.datetime.fromisoformat(last_changed)
                        hours_on = (datetime.datetime.now() - on_since).total_seconds() / 3600
                        if hours_on > 12:
                            anomalies.append(f"has been on for {int(hours_on)} hours")
                    except (ValueError, TypeError):
                        pass

            # Check thermostat temperature
            if device_type == "thermostat":
                temp = device.get("current_temp", 21.0)
                if temp > 28:
                    anomalies.append(f"temperature too high: {temp}°C")
                elif temp < 15:
                    anomalies.append(f"temperature too low: {temp}°C")

            # Check cat feeder water level
            if device_type == "fountain":
                water_level = device.get("water_level", 100)
                if water_level < 30:
                    anomalies.append(f"water level low: {water_level}%")

            # Send alerts
            if anomalies:
                alert_key = device_id
                if alert_key in alerted_devices:
                    continue

                # MUTED: Auto-messages disabled. User must ask explicitly.
                alerted_devices.add(device_id)
                self._save_alerted_devices(alerted_devices)
                logger.info(f"[MUTED DEVICE ALERT] Would send to all users: {device_id} - {', '.join(anomalies)}")

    def _get_alerted_devices(self) -> set:
        """Get set of alerted device IDs."""
        if not hasattr(self, "_alerted_devices"):
            self._alerted_devices = set()
        return self._alerted_devices

    def _save_alerted_devices(self, alerted: set):
        """Save set of alerted device IDs."""
        if not hasattr(self, "_alerted_devices"):
            self._alerted_devices = set()
        self._alerted_devices = alerted

    def _already_reminded(self, key: str) -> bool:
        """Check if we already sent a notification for this key."""
        if not hasattr(self, "_notification_cache"):
            self._notification_cache = set()
        return key in self._notification_cache

    def _mark_reminded(self, key: str):
        """Mark a notification as sent."""
        if not hasattr(self, "_notification_cache"):
            self._notification_cache = set()
        self._notification_cache.add(key)

    async def _beat_router_eval(self):
        """Run the labeled router eval once a day and log accuracy per model.

        Compares the currently-active ROUTER_MODEL against ROUTER_SHADOW_MODEL
        when set. A warning fires if accuracy drops below 80% so regressions
        stand out in server.log.
        """
        if not os.environ.get("FIREWORKS_API_KEY", "").strip():
            return
        try:
            import json
            from pathlib import Path as _Path
            from .router import ROUTER_MODEL, ROUTER_SHADOW_MODEL
            from .router_eval import run_model

            eval_file = _Path(__file__).with_name("router_eval.json")
            if not eval_file.exists():
                return
            cases = json.loads(eval_file.read_text())
            total = len(cases)

            models = [ROUTER_MODEL] + ([ROUTER_SHADOW_MODEL] if ROUTER_SHADOW_MODEL else [])
            for model in models:
                lane_ok, domain_ok, misses = await run_model(model, cases)
                lane_pct = 100 * lane_ok / total if total else 0
                domain_pct = 100 * domain_ok / total if total else 0
                msg = (
                    f"router_eval model={model} lane={lane_ok}/{total} ({lane_pct:.0f}%) "
                    f"domain={domain_ok}/{total} ({domain_pct:.0f}%) misses={len(misses)}"
                )
                if lane_pct < 80 or domain_pct < 80:
                    logger.warning(msg)
                else:
                    logger.info(msg)
                for miss in misses[:10]:
                    logger.info(
                        "router_eval_miss model=%s got=%s/%s expected=%s/%s text=%r",
                        model,
                        miss.get("got_lane"), miss.get("got_domain"),
                        miss.get("lane"), miss.get("domain"),
                        miss.get("text"),
                    )
        except Exception as e:
            logger.warning(f"Router eval failed: {e}")

    async def send_briefing_now(self, user_id: str) -> bool:
        """Manually trigger a briefing for a user (for testing or on-demand)."""
        telegram_chat_id = get_telegram_chat_id(user_id)
        if not telegram_chat_id:
            return False

        try:
            briefing = await BriefingGenerator.generate_briefing(user_id)
            if briefing:
                return await send_message(telegram_chat_id, briefing)
        except Exception as e:
            logger.error(f"Briefing send_now failed for {user_id}: {e}")
        return False


# Global instance
heartbeat = Heartbeat()
