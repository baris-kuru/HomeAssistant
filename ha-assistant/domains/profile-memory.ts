import {
  addMemoryObject,
  consolidateMemoryObjects,
  fetchWeather,
  formatMemoryObjects,
  forgetMemoryObject,
  loadMemoryGuide,
  loadProfile,
  listMemoryObjects,
  ok,
  resolveUser,
  saveProfile,
} from "../shared";

export function registerProfileMemoryDomain(api: any) {
  api.registerTool({
    name: "ha_profile_memory",
    label: "Profile Memory",
    description: "Broker for profile, weather, and memory actions. Actions: get_weather, set_preference, get_profile, recall_memory, get_memory_guide, add_memory, forget_memory, consolidate_memories.",
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

      if (action === "get_weather") {
        let lat = args.lat ?? 50.7374;
        let lon = args.lon ?? 7.0982;
        if (args.user_id) {
          const profile = loadProfile(args.user_id);
          if (profile.home_location) {
            lat = profile.home_location.lat;
            lon = profile.home_location.lon;
          } else {
            const user = resolveUser(args.user_id);
            if (user?.location) {
              lat = user.location.lat;
              lon = user.location.lon;
            }
          }
        }
        return ok(await fetchWeather(lat, lon, args.days ?? 3));
      }

      if (action === "set_preference") {
        if (!args.user_id || !args.key) return ok("set_preference requires user_id and key.");
        const profile = loadProfile(args.user_id);
        profile[args.key] = args.value;
        saveProfile(args.user_id, profile);
        return ok(`Preference saved: ${args.key} = ${JSON.stringify(args.value)}`);
      }

      if (action === "get_profile") {
        if (!args.user_id) return ok("get_profile requires user_id.");
        const profile = loadProfile(args.user_id);
        if (!Object.keys(profile).length) return ok("No profile saved yet.");
        return ok(Object.entries(profile).map(([key, value]) => `${key}: ${JSON.stringify(value)}`).join("\n"));
      }

      if (action === "recall_memory") {
        if (!args.user_id) return ok("recall_memory requires user_id.");
        if (args.entity) {
          const entity = String(args.entity).toLowerCase();
          const items = listMemoryObjects(args.user_id, entity);
          if (!items.length) return ok(`No memories about ${entity}.`);
          return ok(items.map((item) => `- [${item.memory_id}] ${item.title} — ${item.content}`).join("\n"));
        }
        return ok(formatMemoryObjects(args.user_id));
      }

      if (action === "get_memory_guide") {
        if (!args.user_id) return ok("get_memory_guide requires user_id.");
        return ok(JSON.stringify(loadMemoryGuide(args.user_id), null, 2));
      }

      if (action === "add_memory") {
        if (!args.user_id || !args.note || !args.memory_type) return ok("add_memory requires user_id, note, and memory_type.");
        const item = addMemoryObject(args.user_id, String(args.note), args.memory_type, args.entity?.toLowerCase(), args.title);
        return ok(`Saved [${item.memory_id}] ${item.title} on ${item.added_on}.`);
      }

      if (action === "forget_memory") {
        if (!args.user_id || !args.note) return ok("forget_memory requires user_id and note.");
        const item = forgetMemoryObject(args.user_id, String(args.note), args.entity?.toLowerCase());
        if (!item) return ok(`No active memory found for ${args.note}.`);
        return ok(`Forgotten [${item.memory_id}] ${item.title}.`);
      }

      if (action === "consolidate_memories") {
        if (!args.user_id || !args.summary || !Array.isArray(args.notes_to_remove)) return ok("consolidate_memories requires user_id, summary, and notes_to_remove.");
        const removed = consolidateMemoryObjects(args.user_id, String(args.summary), args.notes_to_remove, args.entity?.toLowerCase());
        return ok(`Consolidated ${removed} short-term memories into a new indexed memory.`);
      }

      return ok(`Unknown ha_profile_memory action: ${action}`);
    },
  } as any);
}
