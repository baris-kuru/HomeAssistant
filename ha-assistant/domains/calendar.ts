import { getICloudClient, loadCreds, loadLocalCal, LOCAL_CAL_MAX_EVENTS, ok, parseEventFromIcal, saveCreds, saveLocalCal, today } from "../shared";

const DEFAULT_WRITABLE_CALENDAR = process.env.HA_ICLOUD_WRITE_CALENDAR_NAME?.trim() || "Lobster";

function calendarDisplayName(calendar: any): string {
  return String(
    calendar?.displayName ??
    calendar?.props?.displayname ??
    calendar?.name ??
    "Unnamed calendar",
  ).trim();
}

function findCalendarByName(calendars: any[], desiredName: string) {
  const needle = desiredName.trim().toLowerCase();
  return calendars.find((calendar) => calendarDisplayName(calendar).toLowerCase() === needle)
    ?? calendars.find((calendar) => calendarDisplayName(calendar).toLowerCase().includes(needle));
}

export function registerCalendarDomain(api: any) {
  api.registerTool({
    name: "ha_calendar",
    label: "Calendar",
    description: "Broker for calendar actions. Actions: connect, get_events, add_event, delete_event.",
    parameters: {
      type: "object",
      properties: {
        action: { type: "string" },
        args: { type: "object" },
      },
      required: ["action"],
    },
    execute: async (_id: string, params: any) => {
      const action = params.action;
      const args = params.args ?? {};

      if (action === "connect") {
        if (!args.user_id || !args.username || !args.password) return ok("connect requires user_id, username, and password.");
        try {
          const client = await getICloudClient({ username: args.username, password: args.password });
          await client.fetchCalendars();
          saveCreds(args.user_id, { username: args.username, password: args.password });
          return ok("iCloud calendar connected. Ready to use.");
        } catch (e: any) {
          return ok(`Connection failed: ${e.message}.`);
        }
      }

      if (action === "get_events") {
        if (!args.user_id) return ok("get_events requires user_id.");
        const creds = loadCreds(args.user_id);
        const days = args.days ?? 7;
        if (creds) {
          try {
            const client = await getICloudClient(creds);
            const calendars = await client.fetchCalendars();
            const start = new Date();
            const end = new Date();
            end.setDate(end.getDate() + days);
            const events: string[] = [];
            for (const calendar of calendars) {
              const calendarName = calendarDisplayName(calendar);
              const objects = await client.fetchCalendarObjects({ calendar, timeRange: { start: start.toISOString(), end: end.toISOString() } });
              for (const obj of objects) {
                const event = parseEventFromIcal((obj.calendarData || (obj as any).data) as string);
                if (event) events.push(`- [${calendarName}] ${event.dtstart}: ${event.summary}${event.location ? ` @ ${event.location}` : ""}`);
              }
            }
            if (!events.length) return ok(`No events in the next ${days} days.`);
            return ok(events.sort().join("\n"));
          } catch (e: any) {
            return ok(`iCloud error: ${e.message}`);
          }
        }
        const events = loadLocalCal(args.user_id);
        const cutoff = new Date();
        cutoff.setDate(cutoff.getDate() + days);
        const upcoming = events.filter((event) => new Date(`${event.date}T${event.time ?? "00:00"}`) >= new Date() && new Date(`${event.date}T${event.time ?? "00:00"}`) <= cutoff);
        if (!upcoming.length) return ok(`No events in the next ${days} days.`);
        return ok(upcoming.sort((a, b) => `${a.date}${a.time}`.localeCompare(`${b.date}${b.time}`)).map((event) => `- ${event.date} ${event.time}: ${event.title}${event.location ? ` @ ${event.location}` : ""}`).join("\n"));
      }

      if (action === "add_event") {
        if (!args.user_id || !args.title || !args.date) return ok("add_event requires user_id, title, and date.");
        const creds = loadCreds(args.user_id);
        const time = args.time ?? "09:00";
        if (creds) {
          try {
            const client = await getICloudClient(creds);
            const calendars = await client.fetchCalendars();
            if (!calendars.length) return ok("No calendars found.");
            const writableCalendar = findCalendarByName(calendars, DEFAULT_WRITABLE_CALENDAR);
            if (!writableCalendar) {
              return ok(
                `Write calendar "${DEFAULT_WRITABLE_CALENDAR}" not found. Available calendars: ${calendars.map(calendarDisplayName).join(", ")}`,
              );
            }
            const start = new Date(`${args.date}T${time}:00`);
            const end = new Date(start);
            end.setMinutes(end.getMinutes() + (args.duration_minutes ?? 60));
            const fmt = (date: Date) => date.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
            const uid = `${Date.now()}-${Math.random().toString(36).slice(2)}@ha`;
            const ical = [
              "BEGIN:VCALENDAR",
              "VERSION:2.0",
              "PRODID:-//ha-assistant//EN",
              "BEGIN:VEVENT",
              `SUMMARY:${args.title}`,
              `DTSTART:${fmt(start)}`,
              `DTEND:${fmt(end)}`,
              `UID:${uid}`,
              args.notes ? `DESCRIPTION:${args.notes}` : "",
              args.location ? `LOCATION:${args.location}` : "",
              "END:VEVENT",
              "END:VCALENDAR",
            ].filter(Boolean).join("\r\n");
            await client.createCalendarObject({ calendar: writableCalendar, filename: `${uid}.ics`, iCalString: ical });
            return ok(`Added "${args.title}" on ${args.date} at ${time} to ${calendarDisplayName(writableCalendar)}.`);
          } catch (e: any) {
            return ok(`iCloud error: ${e.message}`);
          }
        }
        const events = loadLocalCal(args.user_id);
        if (events.length >= LOCAL_CAL_MAX_EVENTS) return ok("Local calendar full.");
        events.push({ id: Date.now().toString(36), title: args.title, date: args.date, time, duration_minutes: args.duration_minutes ?? 60, notes: args.notes, location: args.location, created: today() });
        saveLocalCal(args.user_id, events);
        return ok(`Added "${args.title}" on ${args.date} at ${time} to local calendar.`);
      }

      if (action === "delete_event") {
        if (!args.user_id || !args.title) return ok("delete_event requires user_id and title.");
        const creds = loadCreds(args.user_id);
        if (creds) {
          try {
            const client = await getICloudClient(creds);
            const calendars = await client.fetchCalendars();
            const writableCalendar = findCalendarByName(calendars, DEFAULT_WRITABLE_CALENDAR);
            if (!writableCalendar) {
              return ok(
                `Delete is limited to "${DEFAULT_WRITABLE_CALENDAR}", but that calendar was not found. Available calendars: ${calendars.map(calendarDisplayName).join(", ")}`,
              );
            }
            const titleLower = String(args.title).toLowerCase();
            const objects = await client.fetchCalendarObjects({ calendar: writableCalendar });
            for (const obj of objects) {
              const icalData = (obj.calendarData || (obj as any).data) as string;
              if (!icalData) continue;
              const summary = icalData.match(/SUMMARY:(.*)/)?.[1]?.trim().toLowerCase() ?? "";
              if (!summary.includes(titleLower)) continue;
              if (args.date) {
                const dtstart = icalData.match(/DTSTART[^:]*:(.*)/)?.[1]?.trim() ?? "";
                if (!dtstart.startsWith(String(args.date).replace(/-/g, ""))) continue;
              }
              await client.deleteCalendarObject({ calendarObject: obj });
              return ok(`Deleted "${args.title}" from ${calendarDisplayName(writableCalendar)}.`);
            }
            return ok(`No event matching "${args.title}" found in ${calendarDisplayName(writableCalendar)}.`);
          } catch (e: any) {
            return ok(`iCloud error: ${e.message}`);
          }
        }
        const events = loadLocalCal(args.user_id);
        const index = events.findIndex((event) => event.title.toLowerCase().includes(String(args.title).toLowerCase()) && (!args.date || event.date === args.date));
        if (index === -1) return ok(`No event matching "${args.title}" found.`);
        const removed = events.splice(index, 1)[0];
        saveLocalCal(args.user_id, events);
        return ok(`Deleted "${removed.title}" from local calendar.`);
      }

      return ok(`Unknown ha_calendar action: ${action}`);
    },
  } as any);
}
