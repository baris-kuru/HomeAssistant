import { readFileSync, writeFileSync, existsSync, mkdirSync, chmodSync, readdirSync } from "fs";
import { join } from "path";
import { createDAVClient } from "tsdav";

// ── Local Whisper provider ────────────────────────────────────────────────────

const WHISPER_URL = "http://127.0.0.1:8182/v1/audio/transcriptions";

const localWhisperProvider = {
  id: "local-whisper",
  capabilities: ["audio" as const],
  defaultModels: { audio: "whisper-1" },
  autoPriority: { audio: 1 },
  transcribeAudio: async (req: any): Promise<{ text: string; model: string }> => {
    const form = new FormData();
    const blob = new Blob([req.buffer], { type: req.mime ?? "audio/ogg" });
    form.append("file", blob, req.fileName ?? "voice.ogg");
    form.append("model", req.model ?? "whisper-1");
    if (req.language) form.append("language", req.language);
    if (req.prompt) form.append("prompt", req.prompt);
    const res = await fetch(WHISPER_URL, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Whisper service error: ${res.status} ${await res.text()}`);
    const data = await res.json() as { text: string };
    return { text: data.text, model: "whisper-small" };
  },
};

// ── Data directories ──────────────────────────────────────────────────────────

const DATA_DIR = "/Users/bariskuru/Projects/HomeAssistant";
const USERS_FILE = join(DATA_DIR, "users.json");
const MEMORIES_DIR = join(DATA_DIR, "memories");
const NOTES_DIR = join(DATA_DIR, "notes");
const REMINDERS_DIR = join(DATA_DIR, "reminders");
const CREDS_DIR = join(DATA_DIR, "credentials");
const LOCAL_CAL_DIR = join(DATA_DIR, "calendars");
const SHOPPING_DIR = join(DATA_DIR, "shopping");
const FOOD_DIR = join(DATA_DIR, "food");
const PROFILES_DIR = join(DATA_DIR, "profiles");
const HEALTH_DIR = join(DATA_DIR, "health");
const HABITS_DIR = join(DATA_DIR, "habits");
const PEOPLE_DIR = join(DATA_DIR, "people");
const MOOD_DIR = join(DATA_DIR, "mood");
const JOURNAL_DIR = join(DATA_DIR, "journal");

const LOCAL_CAL_MAX_EVENTS = 200;
const REVIEW_AFTER_DAYS = 7;

// ── Fast/Slow thinking (System 1 / System 2) ─────────────────────────────────

const TELEGRAM_BOT_TOKEN = "8776088138:AAG08J3jD9RDIvx4rKnDuFobWLlUyz4B3FA";

async function callOllamaChat(
  model: string,
  messages: Array<{ role: string; content: string }>,
  timeoutMs = 20000,
  maxTokens = 100,
): Promise<string> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch("http://127.0.0.1:11434/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages,
        stream: false,
        options: { num_predict: maxTokens, temperature: 0.3 },
      }),
      signal: controller.signal,
    });
    if (!res.ok) return "";
    const data = (await res.json()) as any;
    return data.message?.content?.trim() ?? "";
  } catch {
    return "";
  } finally {
    clearTimeout(timer);
  }
}

async function telegramSend(chatId: string | number, text: string): Promise<void> {
  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text }),
    });
  } catch {}
}

// Per-turn routing state (single-user, safe as module globals)
let _pendingModel = "";
let _routerPromise: Promise<{ model: string; reason: string }> | null = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function today(): string { return new Date().toISOString().slice(0, 10); }

function nowTime(): string { return new Date().toTimeString().slice(0, 5); }

function expiry(): string {
  const d = new Date(); d.setDate(d.getDate() + REVIEW_AFTER_DAYS);
  return d.toISOString().slice(0, 10);
}

function readJson<T>(path: string, fallback: T): T {
  if (!existsSync(path)) return fallback;
  try { return JSON.parse(readFileSync(path, "utf8")); } catch { return fallback; }
}

function writeJson(path: string, data: unknown) {
  writeFileSync(path, JSON.stringify(data, null, 2));
}

function ensureDir(dir: string) {
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
}

function ok(text: string) {
  return { content: [{ type: "text" as const, text }] };
}

// ── User identity ─────────────────────────────────────────────────────────────

function resolveUser(userId: string): any {
  const users = readJson<Record<string, any>>(USERS_FILE, {});
  const byId = Object.values(users).find((u) => u.id === userId);
  if (byId) return byId;
  return users[`telegram:${userId}`] ?? users[userId] ?? { id: userId, name: userId, role: "user" };
}

// ── User profile / preferences ────────────────────────────────────────────────

interface UserProfile {
  calorie_goal?: number;
  water_goal_ml?: number;
  dietary_restrictions?: string[];
  preferred_language?: string;
  home_location?: { lat: number; lon: number; label?: string };
  work_location?: { lat: number; lon: number; label?: string };
  wake_time?: string;
  sleep_time?: string;
  timezone?: string;
  [key: string]: any;
}

function loadProfile(userId: string): UserProfile {
  ensureDir(PROFILES_DIR);
  return readJson<UserProfile>(join(PROFILES_DIR, `${userId}.json`), {});
}

function saveProfile(userId: string, profile: UserProfile) {
  ensureDir(PROFILES_DIR);
  writeJson(join(PROFILES_DIR, `${userId}.json`), profile);
}

// ── Memory ────────────────────────────────────────────────────────────────────

interface Memory {
  long_term: string[];
  short_term: { note: string; added: string; expires: string }[];
  entities: Record<string, { long_term: string[]; short_term: { note: string; added: string; expires: string }[] }>;
}

function loadMemory(userId: string): Memory {
  ensureDir(MEMORIES_DIR);
  const data = readJson<any>(join(MEMORIES_DIR, `${userId}.json`), null);
  if (!data) return { long_term: [], short_term: [], entities: {} };
  if (Array.isArray(data)) return { long_term: data, short_term: [], entities: {} };
  return { long_term: [], short_term: [], entities: {}, ...data };
}

function saveMemory(userId: string, mem: Memory) {
  ensureDir(MEMORIES_DIR);
  writeJson(join(MEMORIES_DIR, `${userId}.json`), mem);
}

function formatMemory(mem: Memory): string {
  const parts: string[] = [];
  if (mem.long_term.length) parts.push("Long-term:\n" + mem.long_term.map((n) => `- ${n}`).join("\n"));
  const activeST = mem.short_term.filter((i) => i.expires >= today());
  if (activeST.length) parts.push("Short-term:\n" + activeST.map((i) => `- ${i.note} (added ${i.added})`).join("\n"));
  for (const [name, edata] of Object.entries(mem.entities ?? {})) {
    const lines = [
      ...edata.long_term.map((n) => `  - ${n}`),
      ...edata.short_term.filter((i) => i.expires >= today()).map((i) => `  - ${i.note}`),
    ];
    if (lines.length) parts.push(`${name}:\n${lines.join("\n")}`);
  }
  return parts.join("\n\n") || "No memories yet.";
}

// ── Weather ───────────────────────────────────────────────────────────────────

const WMO: Record<number, string> = {
  0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
  45: "Fog", 51: "Light drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
  71: "Slight snow", 73: "Moderate snow", 80: "Showers", 95: "Thunderstorm",
};

async function fetchWeather(lat: number, lon: number, days = 3): Promise<string> {
  const params = new URLSearchParams({
    latitude: lat.toFixed(4), longitude: lon.toFixed(4),
    current: "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
    daily: "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
    forecast_days: String(Math.min(Math.max(days, 1), 7)),
    timezone: "auto",
  });
  const res = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`);
  if (!res.ok) throw new Error(`Weather API error: ${res.status}`);
  const data = await res.json() as any;
  const cur = data.current;
  return [
    `Now: ${WMO[cur.weather_code] ?? "Unknown"}, ${cur.temperature_2m}°C, humidity ${cur.relative_humidity_2m}%, wind ${cur.wind_speed_10m} km/h`,
    "", "Forecast:",
    ...data.daily.time.map((date: string, i: number) =>
      `  ${date}: ${WMO[data.daily.weather_code[i]] ?? "?"}, ${data.daily.temperature_2m_min[i]}–${data.daily.temperature_2m_max[i]}°C, rain ${data.daily.precipitation_sum[i]}mm`
    ),
  ].join("\n");
}

// ── Calendar: iCloud ──────────────────────────────────────────────────────────

interface CalendarCreds { username: string; password: string; }

function loadCreds(userId: string): CalendarCreds | null {
  ensureDir(CREDS_DIR);
  const path = join(CREDS_DIR, `${userId}.json`);
  return existsSync(path) ? readJson<CalendarCreds>(path, null as any) : null;
}

function saveCreds(userId: string, creds: CalendarCreds) {
  ensureDir(CREDS_DIR);
  const path = join(CREDS_DIR, `${userId}.json`);
  writeJson(path, creds);
  chmodSync(path, 0o600);
}

async function getICloudClient(creds: CalendarCreds) {
  return createDAVClient({
    serverUrl: "https://caldav.icloud.com",
    credentials: { username: creds.username, password: creds.password },
    authMethod: "Basic",
    defaultAccountType: "caldav",
  });
}

function parseEventFromIcal(icalData: string): { summary: string; dtstart: string; location?: string } | null {
  try {
    const summary = icalData.match(/SUMMARY[^:]*:([^\r\n]+)/)?.[1]?.trim() ?? "Untitled";
    const dtstart = icalData.match(/DTSTART[^:]*:([^\r\n]+)/)?.[1]?.trim() ?? "";
    const location = icalData.match(/LOCATION[^:]*:([^\r\n]+)/)?.[1]?.trim();
    const dt = dtstart.replace(/(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/, "$1-$2-$3 $4:$5");
    return { summary, dtstart: dt, location };
  } catch { return null; }
}

// ── Calendar: local ───────────────────────────────────────────────────────────

interface LocalEvent {
  id: string; title: string; date: string; time: string;
  duration_minutes: number; notes?: string; location?: string; created: string;
}

function loadLocalCal(userId: string): LocalEvent[] {
  ensureDir(LOCAL_CAL_DIR);
  return readJson<LocalEvent[]>(join(LOCAL_CAL_DIR, `${userId}.json`), []);
}

function saveLocalCal(userId: string, events: LocalEvent[]) {
  ensureDir(LOCAL_CAL_DIR);
  writeJson(join(LOCAL_CAL_DIR, `${userId}.json`), events);
}

// ── Shopping list ─────────────────────────────────────────────────────────────

interface ShoppingItem { id: string; item: string; qty?: string; added: string; done: boolean; }

function loadShopping(userId: string): ShoppingItem[] {
  ensureDir(SHOPPING_DIR);
  return readJson<ShoppingItem[]>(join(SHOPPING_DIR, `${userId}.json`), []);
}

function saveShopping(userId: string, items: ShoppingItem[]) {
  ensureDir(SHOPPING_DIR);
  writeJson(join(SHOPPING_DIR, `${userId}.json`), items);
}

// ── Food diary ────────────────────────────────────────────────────────────────

interface FoodEntry {
  id: string; meal: string; calories: number; meal_type?: string;
  date: string; time: string; notes?: string;
}

function loadFood(userId: string): FoodEntry[] {
  ensureDir(FOOD_DIR);
  return readJson<FoodEntry[]>(join(FOOD_DIR, `${userId}.json`), []);
}

function saveFood(userId: string, entries: FoodEntry[]) {
  ensureDir(FOOD_DIR);
  writeJson(join(FOOD_DIR, `${userId}.json`), entries);
}

// ── Health ────────────────────────────────────────────────────────────────────

interface HealthData {
  weight: { date: string; weight_kg: number; notes?: string }[];
  workouts: { id: string; date: string; time: string; type: string; duration_minutes: number; calories_burned?: number; notes?: string }[];
  water: Record<string, number>; // date → ml total
}

function loadHealth(userId: string): HealthData {
  ensureDir(HEALTH_DIR);
  return readJson<HealthData>(join(HEALTH_DIR, `${userId}.json`), { weight: [], workouts: [], water: {} });
}

function saveHealth(userId: string, data: HealthData) {
  ensureDir(HEALTH_DIR);
  writeJson(join(HEALTH_DIR, `${userId}.json`), data);
}

// ── Habits ────────────────────────────────────────────────────────────────────

interface HabitData {
  habits: Record<string, { description?: string; frequency: string; created: string }>;
  logs: { habit: string; date: string; notes?: string }[];
}

function loadHabits(userId: string): HabitData {
  ensureDir(HABITS_DIR);
  return readJson<HabitData>(join(HABITS_DIR, `${userId}.json`), { habits: {}, logs: [] });
}

function saveHabits(userId: string, data: HabitData) {
  ensureDir(HABITS_DIR);
  writeJson(join(HABITS_DIR, `${userId}.json`), data);
}

function calcStreak(logs: { habit: string; date: string }[], habitName: string): number {
  const dates = new Set(logs.filter((l) => l.habit === habitName).map((l) => l.date));
  let streak = 0;
  const d = new Date();
  // if not logged today yet, start checking from yesterday
  if (!dates.has(today())) d.setDate(d.getDate() - 1);
  while (true) {
    if (!dates.has(d.toISOString().slice(0, 10))) break;
    streak++;
    d.setDate(d.getDate() - 1);
  }
  return streak;
}

// ── People profiles ───────────────────────────────────────────────────────────

interface Person {
  name: string; relationship?: string; birthday?: string;
  notes: string[]; created: string; updated: string;
}

function loadPeople(userId: string): Record<string, Person> {
  ensureDir(PEOPLE_DIR);
  return readJson<Record<string, Person>>(join(PEOPLE_DIR, `${userId}.json`), {});
}

function savePeople(userId: string, data: Record<string, Person>) {
  ensureDir(PEOPLE_DIR);
  writeJson(join(PEOPLE_DIR, `${userId}.json`), data);
}

// ── Mood ──────────────────────────────────────────────────────────────────────

interface MoodEntry { id: string; date: string; time: string; score: number; notes?: string; factors?: string[]; }

function loadMood(userId: string): MoodEntry[] {
  ensureDir(MOOD_DIR);
  return readJson<MoodEntry[]>(join(MOOD_DIR, `${userId}.json`), []);
}

function saveMood(userId: string, entries: MoodEntry[]) {
  ensureDir(MOOD_DIR);
  writeJson(join(MOOD_DIR, `${userId}.json`), entries);
}

// ── Journal & Dreams ──────────────────────────────────────────────────────────

interface JournalEntry {
  id: string; date: string; time: string;
  type: "journal" | "dream";
  raw?: string;         // full transcript
  summary: string;      // concise AI-written summary
  themes?: string[];
  emotions?: string[];
  symbols?: string[];   // dreams only
  tags?: string[];
}

function loadJournal(userId: string): JournalEntry[] {
  ensureDir(JOURNAL_DIR);
  return readJson<JournalEntry[]>(join(JOURNAL_DIR, `${userId}.json`), []);
}

function saveJournal(userId: string, entries: JournalEntry[]) {
  ensureDir(JOURNAL_DIR);
  writeJson(join(JOURNAL_DIR, `${userId}.json`), entries);
}

// ── Plugin ────────────────────────────────────────────────────────────────────

const haAssistantPlugin = {
  id: "ha-assistant",
  name: "Home Assistant",
  description: "Personal assistant: memory, health, habits, journal, dreams, people, calendar, shopping, food diary",

  register(api: any) {

    // ── LOCAL WHISPER PROVIDER ──
    api.registerMediaUnderstandingProvider(localWhisperProvider);

    // ── WEATHER ──
    api.registerTool({
      name: "ha_get_weather",
      label: "Get Weather",
      description: "Get current weather and forecast. Uses saved home location if available.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          lat: { type: "number" },
          lon: { type: "number" },
          days: { type: "integer", description: "1–7, default 3" },
        },
        required: [],
      },
      execute: async (_id: string, params: any) => {
        let lat = params.lat ?? 50.7374, lon = params.lon ?? 7.0982;
        if (params.user_id) {
          const profile = loadProfile(params.user_id);
          if (profile.home_location) { lat = profile.home_location.lat; lon = profile.home_location.lon; }
          else {
            const user = resolveUser(params.user_id);
            if (user?.location) { lat = user.location.lat; lon = user.location.lon; }
          }
        }
        return ok(await fetchWeather(lat, lon, params.days ?? 3));
      },
    } as any);

    // ── USER PROFILE: SET PREFERENCE ──
    api.registerTool({
      name: "ha_set_preference",
      label: "Set User Preference",
      description: "Save a personal preference or setting for the user. Keys include: calorie_goal (number), water_goal_ml (number), dietary_restrictions (array of strings), preferred_language (e.g. 'tr', 'de', 'en'), wake_time (HH:MM), sleep_time (HH:MM), timezone (e.g. Europe/Berlin), home_location ({lat,lon,label}), work_location ({lat,lon,label}).",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          key: { type: "string" },
          value: { description: "The preference value" },
        },
        required: ["user_id", "key", "value"],
      },
      execute: async (_id: string, params: any) => {
        const profile = loadProfile(params.user_id);
        profile[params.key] = params.value;
        saveProfile(params.user_id, profile);
        return ok(`Preference saved: ${params.key} = ${JSON.stringify(params.value)}`);
      },
    } as any);

    // ── USER PROFILE: GET ──
    api.registerTool({
      name: "ha_get_profile",
      label: "Get User Profile",
      description: "Retrieve the full profile and preferences for a user.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const profile = loadProfile(params.user_id);
        if (!Object.keys(profile).length) return ok("No profile saved yet.");
        return ok(Object.entries(profile).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join("\n"));
      },
    } as any);

    // ── MEMORY: RECALL ──
    api.registerTool({
      name: "ha_recall_memory",
      label: "Recall Memory",
      description: "Read memories for a user. Optionally filter by entity.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, entity: { type: "string" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const mem = loadMemory(params.user_id);
        if (params.entity) {
          const e = params.entity.toLowerCase();
          const edata = mem.entities?.[e];
          if (!edata) return ok(`No memories about ${e}.`);
          const lines = [
            ...edata.long_term.map((n) => `- ${n}`),
            ...edata.short_term.filter((i) => i.expires >= today()).map((i) => `- ${i.note}`),
          ];
          return ok(lines.join("\n") || `No memories about ${e}.`);
        }
        return ok(formatMemory(mem));
      },
    } as any);

    // ── MEMORY: ADD ──
    api.registerTool({
      name: "ha_add_memory",
      label: "Add Memory",
      description: "Save a memory. long_term = lasting fact. short_term = temporary (expires 7 days). Use entity to attach to a person or object.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          note: { type: "string" },
          memory_type: { type: "string", enum: ["long_term", "short_term"] },
          entity: { type: "string" },
        },
        required: ["user_id", "note", "memory_type"],
      },
      execute: async (_id: string, params: any) => {
        const mem = loadMemory(params.user_id);
        const { note, memory_type, entity } = params;
        const e = entity?.toLowerCase();
        if (e) {
          if (!mem.entities[e]) mem.entities[e] = { long_term: [], short_term: [] };
          if (memory_type === "short_term") mem.entities[e].short_term.push({ note, added: today(), expires: expiry() });
          else mem.entities[e].long_term.push(note);
        } else {
          if (memory_type === "short_term") mem.short_term.push({ note, added: today(), expires: expiry() });
          else mem.long_term.push(note);
        }
        saveMemory(params.user_id, mem);
        return ok(`Saved (${memory_type}${e ? ` about ${e}` : ""}): ${note}`);
      },
    } as any);

    // ── MEMORY: FORGET ──
    api.registerTool({
      name: "ha_forget_memory",
      label: "Forget Memory",
      description: "Remove a specific memory by its exact text.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, note: { type: "string" }, entity: { type: "string" } },
        required: ["user_id", "note"],
      },
      execute: async (_id: string, params: any) => {
        const mem = loadMemory(params.user_id);
        const e = params.entity?.toLowerCase();
        if (e && mem.entities[e]) {
          mem.entities[e].long_term = mem.entities[e].long_term.filter((n) => n !== params.note);
          mem.entities[e].short_term = mem.entities[e].short_term.filter((i) => i.note !== params.note);
        } else {
          mem.long_term = mem.long_term.filter((n) => n !== params.note);
          mem.short_term = mem.short_term.filter((i) => i.note !== params.note);
        }
        saveMemory(params.user_id, mem);
        return ok(`Forgotten: ${params.note}`);
      },
    } as any);

    // ── NOTES: ADD ──
    api.registerTool({
      name: "ha_add_note",
      label: "Add Note",
      description: "Save a quick note for a user.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          text: { type: "string" },
          tags: { type: "array", items: { type: "string" } },
        },
        required: ["user_id", "text"],
      },
      execute: async (_id: string, params: any) => {
        ensureDir(NOTES_DIR);
        const path = join(NOTES_DIR, `${params.user_id}.json`);
        const notes = readJson<any[]>(path, []);
        notes.push({ id: Date.now().toString(36), text: params.text, tags: params.tags ?? [], created: today() });
        writeJson(path, notes);
        return ok(`Note saved: "${params.text}"`);
      },
    } as any);

    // ── NOTES: LIST ──
    api.registerTool({
      name: "ha_list_notes",
      label: "List Notes",
      description: "List saved notes for a user. Optionally filter by tag.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, tag: { type: "string" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        ensureDir(NOTES_DIR);
        const notes = readJson<any[]>(join(NOTES_DIR, `${params.user_id}.json`), []);
        const filtered = params.tag ? notes.filter((n) => n.tags?.includes(params.tag)) : notes;
        if (!filtered.length) return ok("No notes.");
        return ok(filtered.map((n) => `[${n.id}] [${n.created}] ${n.text}${n.tags?.length ? ` (${n.tags.join(", ")})` : ""}`).join("\n"));
      },
    } as any);

    // ── NOTES: DELETE ──
    api.registerTool({
      name: "ha_delete_note",
      label: "Delete Note",
      description: "Delete a note by ID or partial text match.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          id: { type: "string" },
          text: { type: "string" },
        },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        ensureDir(NOTES_DIR);
        const path = join(NOTES_DIR, `${params.user_id}.json`);
        const notes = readJson<any[]>(path, []);
        const before = notes.length;
        const remaining = notes.filter((n) => {
          if (params.id) return n.id !== params.id;
          if (params.text) return !n.text.toLowerCase().includes(params.text.toLowerCase());
          return true;
        });
        if (remaining.length === before) return ok("No matching note found.");
        writeJson(path, remaining);
        return ok(`Deleted ${before - remaining.length} note(s).`);
      },
    } as any);

    // ── REMINDERS: SET ──
    api.registerTool({
      name: "ha_set_reminder",
      label: "Set Reminder",
      description: "Set a reminder for a user.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          text: { type: "string" },
          due: { type: "string", description: "YYYY-MM-DD or YYYY-MM-DD HH:MM" },
        },
        required: ["user_id", "text", "due"],
      },
      execute: async (_id: string, params: any) => {
        ensureDir(REMINDERS_DIR);
        const path = join(REMINDERS_DIR, `${params.user_id}.json`);
        const reminders = readJson<any[]>(path, []);
        reminders.push({ id: Date.now().toString(36), text: params.text, due: params.due, done: false, created: today() });
        writeJson(path, reminders);
        return ok(`Reminder set for ${params.due}: "${params.text}"`);
      },
    } as any);

    // ── REMINDERS: LIST ──
    api.registerTool({
      name: "ha_list_reminders",
      label: "List Reminders",
      description: "List upcoming reminders for a user.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, include_done: { type: "boolean" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        ensureDir(REMINDERS_DIR);
        const reminders = readJson<any[]>(join(REMINDERS_DIR, `${params.user_id}.json`), []);
        const filtered = params.include_done ? reminders : reminders.filter((r) => !r.done);
        if (!filtered.length) return ok("No reminders.");
        return ok(filtered.sort((a, b) => a.due.localeCompare(b.due)).map((r) => `${r.done ? "✓" : "○"} [${r.id}] [${r.due}] ${r.text}`).join("\n"));
      },
    } as any);

    // ── REMINDERS: DELETE ──
    api.registerTool({
      name: "ha_delete_reminder",
      label: "Delete Reminder",
      description: "Delete or mark a reminder as done.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          id: { type: "string" },
          text: { type: "string" },
          mark_done: { type: "boolean" },
        },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        ensureDir(REMINDERS_DIR);
        const path = join(REMINDERS_DIR, `${params.user_id}.json`);
        const reminders = readJson<any[]>(path, []);
        let changed = 0;
        const updated = reminders.map((r) => {
          const match = (params.id && r.id === params.id) || (params.text && r.text.toLowerCase().includes(params.text.toLowerCase()));
          if (!match) return r;
          changed++;
          return params.mark_done ? { ...r, done: true } : null;
        }).filter(Boolean);
        if (!changed) return ok("No matching reminder found.");
        writeJson(path, updated);
        return ok(params.mark_done ? `Marked ${changed} reminder(s) as done.` : `Deleted ${changed} reminder(s).`);
      },
    } as any);

    // ── SHOPPING LIST: ADD ──
    api.registerTool({
      name: "ha_add_shopping_item",
      label: "Add Shopping Item",
      description: "Add one or more items to the shopping list.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          item: { type: "string" },
          qty: { type: "string" },
          items: { type: "array", items: { type: "object", properties: { item: { type: "string" }, qty: { type: "string" } } } },
        },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const list = loadShopping(params.user_id);
        const toAdd: { item: string; qty?: string }[] = params.items ?? (params.item ? [{ item: params.item, qty: params.qty }] : []);
        if (!toAdd.length) return ok("No items provided.");
        for (const entry of toAdd) {
          list.push({ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 5), item: entry.item, qty: entry.qty, added: today(), done: false });
        }
        saveShopping(params.user_id, list);
        return ok(`Added: ${toAdd.map((e) => e.qty ? `${e.qty} ${e.item}` : e.item).join(", ")}`);
      },
    } as any);

    // ── SHOPPING LIST: VIEW ──
    api.registerTool({
      name: "ha_list_shopping_items",
      label: "View Shopping List",
      description: "Show the current shopping list.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, show_done: { type: "boolean" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const list = loadShopping(params.user_id);
        const filtered = params.show_done ? list : list.filter((i) => !i.done);
        if (!filtered.length) return ok("Shopping list is empty.");
        return ok(filtered.map((i) => `${i.done ? "✓" : "○"} ${i.qty ? `${i.qty} ` : ""}${i.item}`).join("\n"));
      },
    } as any);

    // ── SHOPPING LIST: REMOVE ──
    api.registerTool({
      name: "ha_remove_shopping_item",
      label: "Remove Shopping Item",
      description: "Mark an item as bought or remove it from the list.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          item: { type: "string" },
          delete: { type: "boolean" },
        },
        required: ["user_id", "item"],
      },
      execute: async (_id: string, params: any) => {
        const list = loadShopping(params.user_id);
        const nameLower = params.item.toLowerCase();
        let changed = 0;
        const updated = list.map((i) => {
          if (!i.item.toLowerCase().includes(nameLower)) return i;
          changed++;
          return params.delete ? null : { ...i, done: true };
        }).filter(Boolean) as ShoppingItem[];
        if (!changed) return ok(`"${params.item}" not found on the list.`);
        saveShopping(params.user_id, updated);
        return ok(params.delete ? `Removed "${params.item}".` : `Marked "${params.item}" as bought.`);
      },
    } as any);

    // ── SHOPPING LIST: CLEAR ──
    api.registerTool({
      name: "ha_clear_shopping_list",
      label: "Clear Shopping List",
      description: "Clear bought items or the entire shopping list.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, all: { type: "boolean" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const list = loadShopping(params.user_id);
        const updated = params.all ? [] : list.filter((i) => !i.done);
        saveShopping(params.user_id, updated);
        return ok(`Cleared ${list.length - updated.length} item(s).`);
      },
    } as any);

    // ── FOOD DIARY: LOG MEAL ──
    api.registerTool({
      name: "ha_log_meal",
      label: "Log Meal",
      description: "Log a meal with calorie count. When the user sends a food photo, estimate calories visually before calling this. For meal_type: breakfast, lunch, dinner, or snack.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          meal: { type: "string" },
          calories: { type: "integer" },
          meal_type: { type: "string", enum: ["breakfast", "lunch", "dinner", "snack"] },
          notes: { type: "string" },
        },
        required: ["user_id", "meal", "calories"],
      },
      execute: async (_id: string, params: any) => {
        const entries = loadFood(params.user_id);
        const now = new Date();
        const hour = now.getHours();
        const meal_type = params.meal_type ?? (hour < 11 ? "breakfast" : hour < 15 ? "lunch" : hour < 19 ? "dinner" : "snack");
        entries.push({ id: Date.now().toString(36), meal: params.meal, calories: params.calories, meal_type, date: today(), time: now.toTimeString().slice(0, 5), notes: params.notes });
        saveFood(params.user_id, entries);
        const todayTotal = entries.filter((e) => e.date === today()).reduce((s, e) => s + e.calories, 0);
        const profile = loadProfile(params.user_id);
        const goal = profile.calorie_goal;
        let msg = `Logged ${meal_type}: ${params.meal} — ${params.calories} kcal. Today's total: ${todayTotal} kcal.`;
        if (goal) {
          const pct = Math.round((todayTotal / goal) * 100);
          msg += ` (${pct}% of ${goal} kcal goal)`;
          if (todayTotal >= goal) msg += " ⚠️ Daily goal reached.";
          else if (todayTotal >= goal * 0.8) msg += " — approaching your daily limit.";
        }
        return ok(msg);
      },
    } as any);

    // ── FOOD DIARY: VIEW ──
    api.registerTool({
      name: "ha_get_food_diary",
      label: "Get Food Diary",
      description: "Show the food diary for a date (default today) or last N days with calorie totals.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          date: { type: "string", description: "YYYY-MM-DD" },
          days: { type: "integer" },
        },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const entries = loadFood(params.user_id);
        if (!entries.length) return ok("No food diary entries yet.");
        if (params.days) {
          const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - params.days);
          const recent = entries.filter((e) => e.date >= cutoff.toISOString().slice(0, 10));
          if (!recent.length) return ok(`No entries in the last ${params.days} days.`);
          const byDate: Record<string, FoodEntry[]> = {};
          for (const e of recent) { (byDate[e.date] ??= []).push(e); }
          const lines: string[] = [];
          for (const [date, dayEntries] of Object.entries(byDate).sort()) {
            const total = dayEntries.reduce((s, e) => s + e.calories, 0);
            lines.push(`\n${date} — ${total} kcal`);
            for (const e of dayEntries) lines.push(`  ${e.time} [${e.meal_type}] ${e.meal}: ${e.calories} kcal`);
          }
          return ok(lines.join("\n").trim());
        }
        const date = params.date ?? today();
        const dayEntries = entries.filter((e) => e.date === date);
        if (!dayEntries.length) return ok(`No entries for ${date}.`);
        const total = dayEntries.reduce((s, e) => s + e.calories, 0);
        const profile = loadProfile(params.user_id);
        const goal = profile.calorie_goal ? ` / ${profile.calorie_goal} kcal goal` : "";
        const lines = [`${date} — ${total} kcal${goal}`, ""];
        for (const e of dayEntries) lines.push(`${e.time} [${e.meal_type}] ${e.meal}: ${e.calories} kcal${e.notes ? ` (${e.notes})` : ""}`);
        return ok(lines.join("\n"));
      },
    } as any);

    // ── FOOD DIARY: DELETE ──
    api.registerTool({
      name: "ha_delete_food_entry",
      label: "Delete Food Entry",
      description: "Remove a food diary entry by ID or meal name match.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          id: { type: "string" },
          meal: { type: "string" },
          date: { type: "string" },
        },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const entries = loadFood(params.user_id);
        const before = entries.length;
        const remaining = entries.filter((e) => {
          if (params.id) return e.id !== params.id;
          if (params.meal) return !(e.meal.toLowerCase().includes(params.meal.toLowerCase()) && (!params.date || e.date === params.date));
          return true;
        });
        if (remaining.length === before) return ok("No matching entry found.");
        saveFood(params.user_id, remaining);
        return ok(`Deleted ${before - remaining.length} food entry/entries.`);
      },
    } as any);

    // ── HEALTH: LOG WEIGHT ──
    api.registerTool({
      name: "ha_log_weight",
      label: "Log Weight",
      description: "Record the user's weight.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          weight_kg: { type: "number" },
          notes: { type: "string" },
        },
        required: ["user_id", "weight_kg"],
      },
      execute: async (_id: string, params: any) => {
        const health = loadHealth(params.user_id);
        health.weight.push({ date: today(), weight_kg: params.weight_kg, notes: params.notes });
        saveHealth(params.user_id, health);
        const recent = health.weight.slice(-7);
        let trend = "";
        if (recent.length >= 2) {
          const diff = recent[recent.length - 1].weight_kg - recent[0].weight_kg;
          trend = diff > 0 ? ` (+${diff.toFixed(1)} kg over last ${recent.length} entries)` : diff < 0 ? ` (${diff.toFixed(1)} kg over last ${recent.length} entries)` : "";
        }
        return ok(`Logged: ${params.weight_kg} kg${trend}`);
      },
    } as any);

    // ── HEALTH: WEIGHT HISTORY ──
    api.registerTool({
      name: "ha_get_weight_history",
      label: "Get Weight History",
      description: "Show weight log with trend.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, days: { type: "integer", description: "Default 30" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const health = loadHealth(params.user_id);
        const days = params.days ?? 30;
        const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - days);
        const entries = health.weight.filter((e) => e.date >= cutoff.toISOString().slice(0, 10));
        if (!entries.length) return ok("No weight entries.");
        const lines = entries.map((e) => `${e.date}: ${e.weight_kg} kg${e.notes ? ` — ${e.notes}` : ""}`);
        if (entries.length >= 2) {
          const diff = entries[entries.length - 1].weight_kg - entries[0].weight_kg;
          lines.push(`\nTrend: ${diff > 0 ? "+" : ""}${diff.toFixed(1)} kg over this period`);
        }
        return ok(lines.join("\n"));
      },
    } as any);

    // ── HEALTH: LOG WORKOUT ──
    api.registerTool({
      name: "ha_log_workout",
      label: "Log Workout",
      description: "Record a workout session.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          type: { type: "string", description: "e.g. gym, run, swim, yoga, cycling" },
          duration_minutes: { type: "integer" },
          calories_burned: { type: "integer" },
          notes: { type: "string" },
        },
        required: ["user_id", "type", "duration_minutes"],
      },
      execute: async (_id: string, params: any) => {
        const health = loadHealth(params.user_id);
        health.workouts.push({ id: Date.now().toString(36), date: today(), time: nowTime(), type: params.type, duration_minutes: params.duration_minutes, calories_burned: params.calories_burned, notes: params.notes });
        saveHealth(params.user_id, health);
        let msg = `Logged: ${params.type} for ${params.duration_minutes} min`;
        if (params.calories_burned) msg += `, ${params.calories_burned} kcal burned`;
        return ok(msg);
      },
    } as any);

    // ── HEALTH: WORKOUT HISTORY ──
    api.registerTool({
      name: "ha_get_workout_history",
      label: "Get Workout History",
      description: "Show recent workout sessions.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, days: { type: "integer", description: "Default 14" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const health = loadHealth(params.user_id);
        const days = params.days ?? 14;
        const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - days);
        const entries = health.workouts.filter((e) => e.date >= cutoff.toISOString().slice(0, 10));
        if (!entries.length) return ok("No workouts recorded.");
        const totalMin = entries.reduce((s, e) => s + e.duration_minutes, 0);
        const lines = entries.map((e) => `${e.date} ${e.time}: ${e.type} ${e.duration_minutes}min${e.calories_burned ? ` / ${e.calories_burned} kcal` : ""}${e.notes ? ` — ${e.notes}` : ""}`);
        lines.push(`\nTotal: ${entries.length} sessions, ${totalMin} min`);
        return ok(lines.join("\n"));
      },
    } as any);

    // ── HEALTH: LOG WATER ──
    api.registerTool({
      name: "ha_log_water",
      label: "Log Water Intake",
      description: "Add water intake for today in ml. A glass is ~250ml.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, amount_ml: { type: "integer" } },
        required: ["user_id", "amount_ml"],
      },
      execute: async (_id: string, params: any) => {
        const health = loadHealth(params.user_id);
        health.water[today()] = (health.water[today()] ?? 0) + params.amount_ml;
        saveHealth(params.user_id, health);
        const total = health.water[today()];
        const profile = loadProfile(params.user_id);
        const goal = profile.water_goal_ml ?? 2500;
        const pct = Math.round((total / goal) * 100);
        return ok(`Water logged: +${params.amount_ml}ml → ${total}ml today (${pct}% of ${goal}ml goal)`);
      },
    } as any);

    // ── HABITS: DEFINE ──
    api.registerTool({
      name: "ha_define_habit",
      label: "Define Habit",
      description: "Create a new habit to track. frequency: daily or weekly.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          name: { type: "string", description: "Short habit name, e.g. 'gym', 'meditation', 'reading'" },
          description: { type: "string" },
          frequency: { type: "string", enum: ["daily", "weekly"], description: "Default daily" },
        },
        required: ["user_id", "name"],
      },
      execute: async (_id: string, params: any) => {
        const data = loadHabits(params.user_id);
        const key = params.name.toLowerCase();
        data.habits[key] = { description: params.description, frequency: params.frequency ?? "daily", created: today() };
        saveHabits(params.user_id, data);
        return ok(`Habit "${params.name}" created. Log it daily with ha_log_habit.`);
      },
    } as any);

    // ── HABITS: LOG ──
    api.registerTool({
      name: "ha_log_habit",
      label: "Log Habit",
      description: "Check off a habit for today.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          habit: { type: "string", description: "Habit name" },
          notes: { type: "string" },
        },
        required: ["user_id", "habit"],
      },
      execute: async (_id: string, params: any) => {
        const data = loadHabits(params.user_id);
        const key = params.habit.toLowerCase();
        if (!data.habits[key]) return ok(`Habit "${params.habit}" not found. Create it first with ha_define_habit.`);
        const alreadyToday = data.logs.some((l) => l.habit === key && l.date === today());
        if (alreadyToday) return ok(`"${params.habit}" already logged today.`);
        data.logs.push({ habit: key, date: today(), notes: params.notes });
        saveHabits(params.user_id, data);
        const streak = calcStreak(data.logs, key);
        return ok(`✓ ${params.habit} logged. Current streak: ${streak} day${streak !== 1 ? "s" : ""}.`);
      },
    } as any);

    // ── HABITS: STATS ──
    api.registerTool({
      name: "ha_get_habit_stats",
      label: "Get Habit Stats",
      description: "Show streak and history for all habits or a specific one.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          habit: { type: "string", description: "Specific habit name, or omit for all" },
          days: { type: "integer", description: "Days of history, default 30" },
        },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const data = loadHabits(params.user_id);
        if (!Object.keys(data.habits).length) return ok("No habits defined yet.");
        const days = params.days ?? 30;
        const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - days);
        const cutoffStr = cutoff.toISOString().slice(0, 10);
        const habits = params.habit ? [params.habit.toLowerCase()] : Object.keys(data.habits);
        const lines: string[] = [];
        for (const key of habits) {
          const def = data.habits[key];
          if (!def) { lines.push(`"${key}" not found.`); continue; }
          const streak = calcStreak(data.logs, key);
          const recent = data.logs.filter((l) => l.habit === key && l.date >= cutoffStr);
          const allLogs = data.logs.filter((l) => l.habit === key);
          const best = (() => {
            let max = 0, cur = 0;
            const dates = new Set(allLogs.map((l) => l.date));
            const sorted = [...dates].sort();
            for (let i = 0; i < sorted.length; i++) {
              const prev = new Date(sorted[i]); prev.setDate(prev.getDate() - 1);
              cur = (i > 0 && sorted[i - 1] === prev.toISOString().slice(0, 10)) ? cur + 1 : 1;
              if (cur > max) max = cur;
            }
            return max;
          })();
          lines.push(`${key}: streak ${streak}d | best ${best}d | ${recent.length}/${days} days logged`);
        }
        return ok(lines.join("\n"));
      },
    } as any);

    // ── PEOPLE: SAVE / UPDATE ──
    api.registerTool({
      name: "ha_save_person",
      label: "Save Person Profile",
      description: "Save or update a profile for someone in the user's life (family, friends, colleagues). Add notes like birthday, allergies, preferences, relationship.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          name: { type: "string" },
          relationship: { type: "string", description: "e.g. son, partner, friend, colleague" },
          birthday: { type: "string", description: "YYYY-MM-DD" },
          note: { type: "string", description: "A fact to add to this person's profile" },
        },
        required: ["user_id", "name"],
      },
      execute: async (_id: string, params: any) => {
        const people = loadPeople(params.user_id);
        const key = params.name.toLowerCase();
        const existing = people[key] ?? { name: params.name, notes: [], created: today(), updated: today() };
        if (params.relationship) existing.relationship = params.relationship;
        if (params.birthday) existing.birthday = params.birthday;
        if (params.note) existing.notes.push(params.note);
        existing.updated = today();
        people[key] = existing;
        savePeople(params.user_id, people);
        return ok(`Saved profile for ${params.name}.`);
      },
    } as any);

    // ── PEOPLE: GET ──
    api.registerTool({
      name: "ha_get_person",
      label: "Get Person Profile",
      description: "Recall everything saved about a person.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, name: { type: "string" } },
        required: ["user_id", "name"],
      },
      execute: async (_id: string, params: any) => {
        const people = loadPeople(params.user_id);
        const p = people[params.name.toLowerCase()];
        if (!p) return ok(`No profile for "${params.name}".`);
        const lines = [`${p.name}`];
        if (p.relationship) lines.push(`Relationship: ${p.relationship}`);
        if (p.birthday) {
          const bday = new Date(p.birthday);
          const thisYear = new Date(new Date().getFullYear(), bday.getMonth(), bday.getDate());
          const daysUntil = Math.round((thisYear.getTime() - Date.now()) / 86400000);
          const age = new Date().getFullYear() - bday.getFullYear();
          lines.push(`Birthday: ${p.birthday} (${age} years old${daysUntil >= 0 && daysUntil <= 30 ? `, in ${daysUntil} days!` : ""})`);
        }
        if (p.notes.length) lines.push("Notes:\n" + p.notes.map((n: string) => `  - ${n}`).join("\n"));
        return ok(lines.join("\n"));
      },
    } as any);

    // ── PEOPLE: LIST ──
    api.registerTool({
      name: "ha_list_people",
      label: "List People",
      description: "List all saved people profiles, with upcoming birthdays highlighted.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const people = loadPeople(params.user_id);
        if (!Object.keys(people).length) return ok("No people profiles saved.");
        const lines = Object.values(people).map((p: any) => {
          let line = `${p.name}${p.relationship ? ` (${p.relationship})` : ""}`;
          if (p.birthday) {
            const bday = new Date(p.birthday);
            const thisYear = new Date(new Date().getFullYear(), bday.getMonth(), bday.getDate());
            const daysUntil = Math.round((thisYear.getTime() - Date.now()) / 86400000);
            if (daysUntil >= 0 && daysUntil <= 30) line += ` 🎂 birthday in ${daysUntil} days!`;
          }
          return line;
        });
        return ok(lines.join("\n"));
      },
    } as any);

    // ── MOOD: LOG ──
    api.registerTool({
      name: "ha_log_mood",
      label: "Log Mood",
      description: "Log the user's current mood on a 1–5 scale. 1=very bad, 3=neutral, 5=great. Optionally note contributing factors.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          score: { type: "integer", description: "1–5" },
          notes: { type: "string" },
          factors: { type: "array", items: { type: "string" }, description: "e.g. ['sleep', 'work stress', 'exercise']" },
        },
        required: ["user_id", "score"],
      },
      execute: async (_id: string, params: any) => {
        const entries = loadMood(params.user_id);
        entries.push({ id: Date.now().toString(36), date: today(), time: nowTime(), score: params.score, notes: params.notes, factors: params.factors });
        saveMood(params.user_id, entries);
        const label = ["", "very low", "low", "neutral", "good", "great"][params.score] ?? "";
        return ok(`Mood logged: ${params.score}/5 (${label})`);
      },
    } as any);

    // ── MOOD: HISTORY ──
    api.registerTool({
      name: "ha_get_mood_history",
      label: "Get Mood History",
      description: "Show mood log and weekly average.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, days: { type: "integer", description: "Default 14" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const entries = loadMood(params.user_id);
        const days = params.days ?? 14;
        const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - days);
        const recent = entries.filter((e) => e.date >= cutoff.toISOString().slice(0, 10));
        if (!recent.length) return ok("No mood entries.");
        const avg = (recent.reduce((s, e) => s + e.score, 0) / recent.length).toFixed(1);
        const bar = ["", "▁", "▃", "▅", "▇", "█"];
        const lines = recent.map((e) => `${e.date} ${e.time}: ${bar[e.score]} ${e.score}/5${e.notes ? ` — ${e.notes}` : ""}${e.factors?.length ? ` [${e.factors.join(", ")}]` : ""}`);
        lines.push(`\nAverage: ${avg}/5 over ${recent.length} entries`);
        return ok(lines.join("\n"));
      },
    } as any);

    // ── JOURNAL: SAVE ENTRY ──
    api.registerTool({
      name: "ha_save_journal_entry",
      label: "Save Journal Entry",
      description: "Save a journal entry from a voice memo or typed text. When the user sends a voice message that sounds like journaling or reflection, transcribe it, then: extract key themes, emotions, and important events, write a concise 2-3 sentence summary, and call this tool. The raw transcript should also be stored.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          summary: { type: "string", description: "Concise 2-3 sentence summary of the entry" },
          raw: { type: "string", description: "Full transcript or original text" },
          themes: { type: "array", items: { type: "string" }, description: "Key topics, e.g. ['work', 'relationships', 'health']" },
          emotions: { type: "array", items: { type: "string" }, description: "Emotions present, e.g. ['anxious', 'hopeful', 'grateful']" },
          tags: { type: "array", items: { type: "string" } },
        },
        required: ["user_id", "summary"],
      },
      execute: async (_id: string, params: any) => {
        const entries = loadJournal(params.user_id);
        entries.push({ id: Date.now().toString(36), date: today(), time: nowTime(), type: "journal", raw: params.raw, summary: params.summary, themes: params.themes, emotions: params.emotions, tags: params.tags });
        saveJournal(params.user_id, entries);
        return ok(`Journal entry saved for ${today()}.`);
      },
    } as any);

    // ── JOURNAL: SAVE DREAM ──
    api.registerTool({
      name: "ha_save_dream",
      label: "Save Dream",
      description: "Save a dream recording. When the user sends a voice memo about a dream, transcribe it, then analyze: identify the main narrative arc, symbols (people, objects, places), emotions felt during the dream, and possible themes. Write a concise summary and call this tool. Dreams are best recorded immediately after waking.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          summary: { type: "string", description: "Concise narrative summary of the dream" },
          raw: { type: "string", description: "Full transcript" },
          themes: { type: "array", items: { type: "string" }, description: "Recurring or significant themes" },
          emotions: { type: "array", items: { type: "string" }, description: "Emotions felt in or about the dream" },
          symbols: { type: "array", items: { type: "string" }, description: "Notable symbols, e.g. ['water', 'childhood home', 'unknown figure']" },
        },
        required: ["user_id", "summary"],
      },
      execute: async (_id: string, params: any) => {
        const entries = loadJournal(params.user_id);
        entries.push({ id: Date.now().toString(36), date: today(), time: nowTime(), type: "dream", raw: params.raw, summary: params.summary, themes: params.themes, emotions: params.emotions, symbols: params.symbols });
        saveJournal(params.user_id, entries);
        return ok(`Dream saved for ${today()}.${params.symbols?.length ? ` Symbols: ${params.symbols.join(", ")}.` : ""}`);
      },
    } as any);

    // ── JOURNAL: LIST ──
    api.registerTool({
      name: "ha_get_journal",
      label: "Get Journal",
      description: "Retrieve journal entries or dreams.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          type: { type: "string", enum: ["journal", "dream", "all"], description: "Default all" },
          days: { type: "integer", description: "Default 7" },
          full: { type: "boolean", description: "Include full transcripts, default false" },
        },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const entries = loadJournal(params.user_id);
        const days = params.days ?? 7;
        const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - days);
        const filtered = entries
          .filter((e) => e.date >= cutoff.toISOString().slice(0, 10))
          .filter((e) => !params.type || params.type === "all" || e.type === params.type);
        if (!filtered.length) return ok(`No ${params.type ?? "entries"} in the last ${days} days.`);
        const lines = filtered.map((e) => {
          const header = `[${e.date}] [${e.type}] ${e.summary}`;
          const meta: string[] = [];
          if (e.themes?.length) meta.push(`themes: ${e.themes.join(", ")}`);
          if (e.emotions?.length) meta.push(`emotions: ${e.emotions.join(", ")}`);
          if (e.symbols?.length) meta.push(`symbols: ${e.symbols.join(", ")}`);
          const full = params.full && e.raw ? `\n  Transcript: ${e.raw}` : "";
          return header + (meta.length ? `\n  ${meta.join(" | ")}` : "") + full;
        });
        return ok(lines.join("\n\n"));
      },
    } as any);

    // ── CALENDAR: CONNECT iCLOUD ──
    api.registerTool({
      name: "ha_connect_calendar",
      label: "Connect iCloud Calendar",
      description: "Save a user's iCloud credentials for calendar access.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          username: { type: "string" },
          password: { type: "string" },
        },
        required: ["user_id", "username", "password"],
      },
      execute: async (_id: string, params: any) => {
        try {
          const client = await getICloudClient({ username: params.username, password: params.password });
          await client.fetchCalendars();
          saveCreds(params.user_id, { username: params.username, password: params.password });
          return ok(`iCloud calendar connected. Ready to use.`);
        } catch (e: any) {
          return ok(`Connection failed: ${e.message}.`);
        }
      },
    } as any);

    // ── CALENDAR: GET EVENTS ──
    api.registerTool({
      name: "ha_get_calendar_events",
      label: "Get Calendar Events",
      description: "List upcoming events from iCloud or local calendar.",
      parameters: {
        type: "object",
        properties: { user_id: { type: "string" }, days: { type: "integer", description: "Default 7" } },
        required: ["user_id"],
      },
      execute: async (_id: string, params: any) => {
        const creds = loadCreds(params.user_id);
        const days = params.days ?? 7;
        if (creds) {
          try {
            const client = await getICloudClient(creds);
            const calendars = await client.fetchCalendars();
            const start = new Date();
            const end = new Date(); end.setDate(end.getDate() + days);
            const events: string[] = [];
            for (const cal of calendars) {
              const objects = await client.fetchCalendarObjects({ calendar: cal, timeRange: { start: start.toISOString(), end: end.toISOString() } });
              for (const obj of objects) {
                const ev = parseEventFromIcal((obj.calendarData || (obj as any).data) as string);
                if (ev) events.push(`- ${ev.dtstart}: ${ev.summary}${ev.location ? ` @ ${ev.location}` : ""}`);
              }
            }
            if (!events.length) return ok(`No events in the next ${days} days.`);
            return ok(events.sort().join("\n"));
          } catch (e: any) {
            return ok(`iCloud error: ${e.message}`);
          }
        }
        const events = loadLocalCal(params.user_id);
        const cutoff = new Date(); cutoff.setDate(cutoff.getDate() + days);
        const upcoming = events.filter((e) => new Date(`${e.date}T${e.time ?? "00:00"}`) >= new Date() && new Date(`${e.date}T${e.time ?? "00:00"}`) <= cutoff);
        if (!upcoming.length) return ok(`No events in the next ${days} days.`);
        return ok(upcoming.sort((a, b) => `${a.date}${a.time}`.localeCompare(`${b.date}${b.time}`)).map((e) => `- ${e.date} ${e.time}: ${e.title}${e.location ? ` @ ${e.location}` : ""}`).join("\n"));
      },
    } as any);

    // ── CALENDAR: ADD EVENT ──
    api.registerTool({
      name: "ha_add_calendar_event",
      label: "Add Calendar Event",
      description: "Add an event to the calendar.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          title: { type: "string" },
          date: { type: "string" },
          time: { type: "string" },
          duration_minutes: { type: "integer" },
          notes: { type: "string" },
          location: { type: "string" },
        },
        required: ["user_id", "title", "date"],
      },
      execute: async (_id: string, params: any) => {
        const creds = loadCreds(params.user_id);
        const time = params.time ?? "09:00";
        if (creds) {
          try {
            const client = await getICloudClient(creds);
            const calendars = await client.fetchCalendars();
            if (!calendars.length) return ok("No calendars found.");
            const start = new Date(`${params.date}T${time}:00`);
            const end = new Date(start); end.setMinutes(end.getMinutes() + (params.duration_minutes ?? 60));
            const fmt = (d: Date) => d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
            const uid = `${Date.now()}-${Math.random().toString(36).slice(2)}@ha`;
            const ical = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ha-assistant//EN", "BEGIN:VEVENT",
              `SUMMARY:${params.title}`, `DTSTART:${fmt(start)}`, `DTEND:${fmt(end)}`, `UID:${uid}`,
              params.notes ? `DESCRIPTION:${params.notes}` : "", params.location ? `LOCATION:${params.location}` : "",
              "END:VEVENT", "END:VCALENDAR"].filter(Boolean).join("\r\n");
            await client.createCalendarObject({ calendar: calendars[0], filename: `${uid}.ics`, iCalString: ical });
            return ok(`Added "${params.title}" on ${params.date} at ${time}.`);
          } catch (e: any) { return ok(`iCloud error: ${e.message}`); }
        }
        const events = loadLocalCal(params.user_id);
        if (events.length >= LOCAL_CAL_MAX_EVENTS) return ok("Local calendar full.");
        events.push({ id: Date.now().toString(36), title: params.title, date: params.date, time, duration_minutes: params.duration_minutes ?? 60, notes: params.notes, location: params.location, created: today() });
        saveLocalCal(params.user_id, events);
        return ok(`Added "${params.title}" on ${params.date} at ${time} to local calendar.`);
      },
    } as any);

    // ── CALENDAR: DELETE EVENT ──
    api.registerTool({
      name: "ha_delete_calendar_event",
      label: "Delete Calendar Event",
      description: "Delete a calendar event by title and optional date.",
      parameters: {
        type: "object",
        properties: {
          user_id: { type: "string" },
          title: { type: "string" },
          date: { type: "string" },
        },
        required: ["user_id", "title"],
      },
      execute: async (_id: string, params: any) => {
        const creds = loadCreds(params.user_id);
        if (creds) {
          try {
            const client = await getICloudClient(creds);
            const calendars = await client.fetchCalendars();
            const titleLower = params.title.toLowerCase();
            for (const cal of calendars) {
              const objects = await client.fetchCalendarObjects({ calendar: cal });
              for (const obj of objects) {
                const icalData = (obj.calendarData || (obj as any).data) as string;
                if (!icalData) continue;
                const summary = icalData.match(/SUMMARY:(.*)/)?.[1]?.trim().toLowerCase() ?? "";
                if (!summary.includes(titleLower)) continue;
                if (params.date) {
                  const dtstart = icalData.match(/DTSTART[^:]*:(.*)/)?.[1]?.trim() ?? "";
                  if (!dtstart.startsWith(params.date.replace(/-/g, ""))) continue;
                }
                await client.deleteCalendarObject({ calendarObject: obj });
                return ok(`Deleted "${params.title}" from calendar.`);
              }
            }
            return ok(`No event matching "${params.title}" found.`);
          } catch (e: any) { return ok(`iCloud error: ${e.message}`); }
        }
        const events = loadLocalCal(params.user_id);
        const idx = events.findIndex((e) => e.title.toLowerCase().includes(params.title.toLowerCase()) && (!params.date || e.date === params.date));
        if (idx === -1) return ok(`No event matching "${params.title}" found.`);
        const removed = events.splice(idx, 1)[0];
        saveLocalCal(params.user_id, events);
        return ok(`Deleted "${removed.title}" from local calendar.`);
      },
    } as any);

    // ── DOCUMENT READER (Docling) ──
    api.registerTool({
      name: "ha_read_document",
      label: "Read Document",
      description: "Convert a document file (PDF, Word, Excel, PowerPoint, HTML) to readable text using Docling. Call this whenever the user sends a file attachment — use the file path or URL from the message context. Supports .pdf .docx .xlsx .pptx .html .csv",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Local file path to the document" },
          url: { type: "string", description: "URL to download the document from" },
          filename: { type: "string", description: "Original filename (helps Docling pick the right parser)" },
        },
        required: [],
      },
      execute: async (_id: string, params: any) => {
        const DOCLING_URL = "http://127.0.0.1:8183/convert";
        const { createReadStream } = await import("fs");
        const { basename } = await import("path");
        const { FormData: NodeFormData, File: NodeFile } = await import("formdata-node");

        let buffer: Buffer;
        let filename: string = params.filename ?? "document";

        if (params.path) {
          if (!existsSync(params.path)) return ok(`File not found: ${params.path}`);
          buffer = readFileSync(params.path);
          filename = params.filename ?? basename(params.path);
        } else if (params.url) {
          const res = await fetch(params.url);
          if (!res.ok) return ok(`Failed to download: ${res.status} ${res.statusText}`);
          buffer = Buffer.from(await res.arrayBuffer());
          filename = params.filename ?? (params.url.split("/").pop() ?? "document");
        } else {
          return ok("Provide either a file path or URL.");
        }

        try {
          const form = new NodeFormData();
          form.set("file", new NodeFile([buffer], filename));
          const res = await fetch(DOCLING_URL, { method: "POST", body: form as any });
          if (!res.ok) {
            const err = await res.text();
            return ok(`Docling error: ${res.status} — ${err}`);
          }
          const data = await res.json() as { markdown: string; chars: number };
          if (!data.markdown?.trim()) return ok("Document converted but appears to be empty.");
          return ok(`**${filename}** (${data.chars} chars)\n\n${data.markdown}`);
        } catch (e: any) {
          if (e.cause?.code === "ECONNREFUSED") return ok("Docling service is not running. Start it with: launchctl load ~/Library/LaunchAgents/com.homeassistant.docling.plist");
          return ok(`Conversion failed: ${e.message}`);
        }
      },
    } as any);

    // ── BEFORE AGENT START: document awareness + /think stripping ──
    api.registerHook("before_agent_start", async (event: any) => {
      const prompt: string = event.prompt ?? "";
      const lower = prompt.toLowerCase();
      const parts: string[] = [];

      if (/\.(pdf|docx?|xlsx?|pptx?|csv|html?)(\b|$)/i.test(prompt) ||
          lower.includes("mediapath") || lower.includes("attachment")) {
        parts.push(
          "The user has sent a file attachment. Use ha_read_document with the file path or URL from the message to read its contents before responding.",
        );
      }

      if (prompt.trim().toLowerCase().startsWith("/think")) {
        parts.push(
          "The user has requested deep analysis. Before answering, run 2–3 parallel ollama_web_search calls if the topic benefits from current information, then give a thorough, well-reasoned response.",
        );
      }

      if (parts.length === 0) return;
      return { prependContext: parts.join("\n\n") };
    });

    // ── PARALLEL e2b PIPELINE: instant ack + async router ──
    api.registerHook("message_received", async (event: any) => {
      const prompt: string = event.prompt ?? event.message?.text ?? "";
      const trimmed = prompt.trim();
      const chatId: string | number =
        event.channel?.chatId ?? event.chatId ?? event.userId ?? "6503433160";

      if (trimmed.split(/\s+/).length < 2) return;

      // /think command → just ack, router not needed
      if (trimmed.toLowerCase().startsWith("/think")) {
        _pendingModel = "e2b";
        _routerPromise = Promise.resolve({ model: "e2b", reason: "explicit /think" });
        telegramSend(chatId, "On it, thinking carefully... 🧠");
        return;
      }

      // ── Fire both e2b calls in parallel ──

      // Call A: Router → instant JSON classification (e2b only now, kept for future routing)
      _routerPromise = Promise.resolve({ model: "e2b", reason: "single model mode" });
      _pendingModel = "e2b";

      // Call B: Instant ack → sent to Telegram immediately, fire-and-forget
      callOllamaChat(
        "gemma4:e2b",
        [
          {
            role: "system",
            content:
              "You are a friendly home assistant on Telegram. The user just sent you a message. " +
              "Send ONE short, warm, human-like acknowledgment — you got it, more is coming. " +
              "Examples: 'On it, give me a sec ⏳', 'Got it — working on that!', 'Sure, one moment!'. " +
              "Casual, max 1 sentence, no markdown. Never repeat the user's words back.",
          },
          { role: "user", content: trimmed },
        ],
        8000,
        25,
      ).then((ack) => {
        if (ack) telegramSend(chatId, ack);
      });
    });

    // ── MODEL SELECTION: always e2b ──
    api.registerHook("before_model_resolve", async (event: any) => {
      _routerPromise = null;
      return { modelOverride: "gemma4:e2b" };
    });
  },
};

export default haAssistantPlugin;
