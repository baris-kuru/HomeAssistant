import { noteFile, ok, readJson, reminderFile, writeJson, today } from "../shared";

export function registerNotesRemindersDomain(api: any) {
  api.registerTool({
    name: "ha_notes_reminders",
    label: "Notes Reminders",
    description: "Broker for note and reminder actions. Actions: add_note, list_notes, delete_note, set_reminder, list_reminders, delete_reminder.",
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

      if (action === "add_note") {
        if (!args.user_id || !args.text) return ok("add_note requires user_id and text.");
        const path = noteFile(args.user_id);
        const notes = readJson<any[]>(path, []);
        notes.push({ id: Date.now().toString(36), text: args.text, tags: args.tags ?? [], created: today() });
        writeJson(path, notes);
        return ok(`Note saved: "${args.text}"`);
      }

      if (action === "list_notes") {
        if (!args.user_id) return ok("list_notes requires user_id.");
        const notes = readJson<any[]>(noteFile(args.user_id), []);
        const filtered = args.tag ? notes.filter((note) => note.tags?.includes(args.tag)) : notes;
        if (!filtered.length) return ok("No notes.");
        return ok(filtered.map((note) => `[${note.id}] [${note.created}] ${note.text}${note.tags?.length ? ` (${note.tags.join(", ")})` : ""}`).join("\n"));
      }

      if (action === "delete_note") {
        if (!args.user_id) return ok("delete_note requires user_id.");
        const path = noteFile(args.user_id);
        const notes = readJson<any[]>(path, []);
        const before = notes.length;
        const remaining = notes.filter((note) => {
          if (args.id) return note.id !== args.id;
          if (args.text) return !note.text.toLowerCase().includes(String(args.text).toLowerCase());
          return true;
        });
        if (remaining.length === before) return ok("No matching note found.");
        writeJson(path, remaining);
        return ok(`Deleted ${before - remaining.length} note(s).`);
      }

      if (action === "set_reminder") {
        if (!args.user_id || !args.text || !args.due) return ok("set_reminder requires user_id, text, and due.");
        const path = reminderFile(args.user_id);
        const reminders = readJson<any[]>(path, []);
        reminders.push({ id: Date.now().toString(36), text: args.text, due: args.due, done: false, created: today() });
        writeJson(path, reminders);
        return ok(`Reminder set for ${args.due}: "${args.text}"`);
      }

      if (action === "list_reminders") {
        if (!args.user_id) return ok("list_reminders requires user_id.");
        const reminders = readJson<any[]>(reminderFile(args.user_id), []);
        const filtered = args.include_done ? reminders : reminders.filter((item) => !item.done);
        if (!filtered.length) return ok("No reminders.");
        return ok(filtered.sort((a, b) => a.due.localeCompare(b.due)).map((item) => `${item.done ? "✓" : "○"} [${item.id}] [${item.due}] ${item.text}`).join("\n"));
      }

      if (action === "delete_reminder") {
        if (!args.user_id) return ok("delete_reminder requires user_id.");
        const path = reminderFile(args.user_id);
        const reminders = readJson<any[]>(path, []);
        let changed = 0;
        const updated = reminders.map((item) => {
          const match = (args.id && item.id === args.id) || (args.text && item.text.toLowerCase().includes(String(args.text).toLowerCase()));
          if (!match) return item;
          changed++;
          return args.mark_done ? { ...item, done: true } : null;
        }).filter(Boolean);
        if (!changed) return ok("No matching reminder found.");
        writeJson(path, updated);
        return ok(args.mark_done ? `Marked ${changed} reminder(s) as done.` : `Deleted ${changed} reminder(s).`);
      }

      return ok(`Unknown ha_notes_reminders action: ${action}`);
    },
  } as any);
}
