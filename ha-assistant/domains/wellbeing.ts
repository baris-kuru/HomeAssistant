import { loadJournal, loadMood, loadPeople, nowTime, ok, saveJournal, saveMood, savePeople, today } from "../shared";

export function registerWellbeingDomain(api: any) {
  api.registerTool({
    name: "ha_wellbeing",
    label: "Wellbeing",
    description: "Broker for people, mood, journal, and dream actions. Actions: save_person, get_person, list_people, log_mood, get_mood_history, save_journal_entry, save_dream, get_journal.",
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
      if (!args.user_id) return ok("ha_wellbeing actions require user_id.");

      if (action === "save_person") {
        if (!args.name) return ok("save_person requires name.");
        const people = loadPeople(args.user_id);
        const key = String(args.name).toLowerCase();
        const existing = people[key] ?? { name: args.name, notes: [], created: today(), updated: today() };
        if (args.relationship) existing.relationship = args.relationship;
        if (args.birthday) existing.birthday = args.birthday;
        if (args.note) existing.notes.push(args.note);
        existing.updated = today();
        people[key] = existing;
        savePeople(args.user_id, people);
        return ok(`Saved profile for ${args.name}.`);
      }

      if (action === "get_person") {
        if (!args.name) return ok("get_person requires name.");
        const person = loadPeople(args.user_id)[String(args.name).toLowerCase()];
        if (!person) return ok(`No profile for "${args.name}".`);
        const lines = [`${person.name}`];
        if (person.relationship) lines.push(`Relationship: ${person.relationship}`);
        if (person.birthday) lines.push(`Birthday: ${person.birthday}`);
        if (person.notes.length) lines.push("Notes:\n" + person.notes.map((note: string) => `  - ${note}`).join("\n"));
        return ok(lines.join("\n"));
      }

      if (action === "list_people") {
        const people = loadPeople(args.user_id);
        if (!Object.keys(people).length) return ok("No people profiles saved.");
        return ok(Object.values(people).map((person: any) => `${person.name}${person.relationship ? ` (${person.relationship})` : ""}`).join("\n"));
      }

      if (action === "log_mood") {
        if (args.score == null) return ok("log_mood requires score.");
        const entries = loadMood(args.user_id);
        entries.push({ id: Date.now().toString(36), date: today(), time: nowTime(), score: args.score, notes: args.notes, factors: args.factors });
        saveMood(args.user_id, entries);
        return ok(`Mood logged: ${args.score}/5`);
      }

      if (action === "get_mood_history") {
        const entries = loadMood(args.user_id);
        const days = args.days ?? 14;
        const cutoff = new Date();
        cutoff.setDate(cutoff.getDate() - days);
        const recent = entries.filter((entry) => entry.date >= cutoff.toISOString().slice(0, 10));
        if (!recent.length) return ok("No mood entries.");
        const avg = (recent.reduce((sum, entry) => sum + entry.score, 0) / recent.length).toFixed(1);
        const lines = recent.map((entry) => `${entry.date} ${entry.time}: ${entry.score}/5${entry.notes ? ` — ${entry.notes}` : ""}`);
        lines.push(`\nAverage: ${avg}/5 over ${recent.length} entries`);
        return ok(lines.join("\n"));
      }

      if (action === "save_journal_entry") {
        if (!args.summary) return ok("save_journal_entry requires summary.");
        const entries = loadJournal(args.user_id);
        entries.push({ id: Date.now().toString(36), date: today(), time: nowTime(), type: "journal", raw: args.raw, summary: args.summary, themes: args.themes, emotions: args.emotions, tags: args.tags });
        saveJournal(args.user_id, entries);
        return ok(`Journal entry saved for ${today()}.`);
      }

      if (action === "save_dream") {
        if (!args.summary) return ok("save_dream requires summary.");
        const entries = loadJournal(args.user_id);
        entries.push({ id: Date.now().toString(36), date: today(), time: nowTime(), type: "dream", raw: args.raw, summary: args.summary, themes: args.themes, emotions: args.emotions, symbols: args.symbols });
        saveJournal(args.user_id, entries);
        return ok(`Dream saved for ${today()}.`);
      }

      if (action === "get_journal") {
        const entries = loadJournal(args.user_id);
        const days = args.days ?? 7;
        const cutoff = new Date();
        cutoff.setDate(cutoff.getDate() - days);
        const filtered = entries
          .filter((entry) => entry.date >= cutoff.toISOString().slice(0, 10))
          .filter((entry) => !args.type || args.type === "all" || entry.type === args.type);
        if (!filtered.length) return ok(`No ${args.type ?? "entries"} in the last ${days} days.`);
        const lines = filtered.map((entry) => `[${entry.date}] [${entry.type}] ${entry.summary}`);
        return ok(lines.join("\n\n"));
      }

      return ok(`Unknown ha_wellbeing action: ${action}`);
    },
  } as any);
}
