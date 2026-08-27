import { chmodSync, copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, statSync, unlinkSync, writeFileSync } from "fs";
import { homedir } from "os";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

import { createDAVClient } from "tsdav";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function discoverDataDir() {
  const envDir = process.env.HA_DATA_DIR ? resolve(process.env.HA_DATA_DIR) : "";
  if (envDir && existsSync(join(envDir, "users.json"))) return envDir;

  const localDir = resolve(__dirname, "..");
  if (existsSync(join(localDir, "users.json")) && existsSync(join(localDir, "backend"))) return localDir;

  const configPath = join(homedir(), ".openclaw", "openclaw.json");
  if (existsSync(configPath)) {
    try {
      const config = JSON.parse(readFileSync(configPath, "utf8"));
      const sourcePath = config?.plugins?.installs?.["ha-assistant"]?.sourcePath;
      const sourceRoot = sourcePath ? resolve(sourcePath, "..") : "";
      if (sourceRoot && existsSync(join(sourceRoot, "users.json"))) return sourceRoot;
    } catch {}
  }

  return localDir;
}

export const DATA_DIR = discoverDataDir();
const ENV_PATH = join(DATA_DIR, ".env");
const OPENCLAW_CONFIG_PATH = join(homedir(), ".openclaw", "openclaw.json");
export const BACKEND_API_URL = process.env.HA_BACKEND_API_URL ?? "http://127.0.0.1:8001";
export const FIREWORKS_PROVIDER_ID = "fireworks";
export const FIREWORKS_QWEN_MODEL_ID = "accounts/fireworks/models/qwen3p6-plus";
export const FIREWORKS_QWEN_MODEL = `${FIREWORKS_PROVIDER_ID}/${FIREWORKS_QWEN_MODEL_ID}`;
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

export const LOCAL_CAL_MAX_EVENTS = 200;
const REVIEW_AFTER_DAYS = 7;
const WHISPER_URL = "http://127.0.0.1:8182/v1/audio/transcriptions";

function readEnvValue(key: string): string {
  if (!existsSync(ENV_PATH)) return "";
  try {
    return readFileSync(ENV_PATH, "utf8").match(new RegExp(`^${key}=(.*)$`, "m"))?.[1]?.trim() ?? "";
  } catch {
    return "";
  }
}

function readOpenClawConfig(): any {
  if (!existsSync(OPENCLAW_CONFIG_PATH)) return {};
  try {
    return JSON.parse(readFileSync(OPENCLAW_CONFIG_PATH, "utf8"));
  } catch {
    return {};
  }
}

function resolveTelegramBotToken(): string {
  const fromEnv = process.env.TELEGRAM_BOT_TOKEN?.trim();
  if (fromEnv) return fromEnv;

  const fromFile = readEnvValue("TELEGRAM_BOT_TOKEN");
  if (fromFile) return fromFile;

  const fromConfig = readOpenClawConfig()?.channels?.telegram?.botToken;
  return typeof fromConfig === "string" ? fromConfig.trim() : "";
}

function resolveFireworksApiKey(): string {
  const fromEnv = process.env.FIREWORKS_API_KEY?.trim();
  if (fromEnv) return fromEnv;

  return readEnvValue("FIREWORKS_API_KEY");
}

export const FIREWORKS_API_KEY = resolveFireworksApiKey();
export const TELEGRAM_BOT_TOKEN_EXPORT = resolveTelegramBotToken();
const TELEGRAM_BOT_TOKEN = TELEGRAM_BOT_TOKEN_EXPORT;

export const localWhisperProvider = {
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

export const routingState: {
  pendingModel: string;
  routerPromise: Promise<{ model: string; reason: string }> | null;
  lane: string;
  activeDomain: string;
  allowedTools: string[];
  reason: string;
  fastIntent: { tool: string; action: string; args: Record<string, any> } | null;
} = {
  pendingModel: "",
  routerPromise: null,
  lane: "fast",
  activeDomain: "general",
  allowedTools: [],
  reason: "",
  fastIntent: null,
};

export function resolveAssistantModel(): string {
  return FIREWORKS_QWEN_MODEL;
}

export function resolveAssistantSelection(): { provider: string; modelId: string; modelRef: string } {
  return {
    provider: FIREWORKS_PROVIDER_ID,
    modelId: FIREWORKS_QWEN_MODEL_ID,
    modelRef: FIREWORKS_QWEN_MODEL,
  };
}

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function nowTime(): string {
  return new Date().toTimeString().slice(0, 5);
}

export function expiry(): string {
  const d = new Date();
  d.setDate(d.getDate() + REVIEW_AFTER_DAYS);
  return d.toISOString().slice(0, 10);
}

export function readJson<T>(path: string, fallback: T): T {
  if (!existsSync(path)) return fallback;
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return fallback;
  }
}

export function writeJson(path: string, data: unknown) {
  writeFileSync(path, JSON.stringify(data, null, 2));
}

export function ensureDir(dir: string) {
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
}

export function ok(text: string) {
  return { content: [{ type: "text" as const, text }] };
}

export async function telegramSend(chatId: string | number, text: string): Promise<void> {
  if (!TELEGRAM_BOT_TOKEN) return;
  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text }),
    });
  } catch {}
}

export function getTelegramChatId(userId: string): string | null {
  const canonical = canonicalUserId(userId);
  const users = loadUsers();
  for (const [key, val] of Object.entries(users)) {
    if (key.startsWith("telegram:") && String((val as any)?.id ?? "").toLowerCase() === canonical) {
      return key.replace("telegram:", "");
    }
  }
  return null;
}

export function verifyPassword(userId: string, password: string): boolean {
  const canonical = canonicalUserId(userId);
  const user = resolveUser(canonical);
  const keys = [
    `${canonical.toUpperCase()}_PASSWORD`,
    ...(Array.isArray(user.aliases) ? user.aliases.map((item: string) => `${String(item).toUpperCase()}_PASSWORD`) : []),
  ];
  for (const key of keys) {
    const fromEnv = process.env[key];
    const fromFile = existsSync(ENV_PATH)
      ? readFileSync(ENV_PATH, "utf8").match(new RegExp(`^${key}=(.*)$`, "m"))?.[1]
      : "";
    const expected = fromEnv || fromFile;
    if (expected && expected === password) return true;
  }
  return false;
}

export function updatePassword(userId: string, newPassword: string) {
  const canonical = canonicalUserId(userId);
  const user = resolveUser(canonical);
  const keys = [
    `${canonical.toUpperCase()}_PASSWORD`,
    ...(Array.isArray(user.aliases) ? user.aliases.map((item: string) => `${String(item).toUpperCase()}_PASSWORD`) : []),
  ];
  const current = existsSync(ENV_PATH) ? readFileSync(ENV_PATH, "utf8") : "";
  let next = current;
  for (const key of keys) {
    next = next.match(new RegExp(`^${key}=`, "m"))
      ? next.replace(new RegExp(`^${key}=.*$`, "m"), `${key}=${newPassword}`)
      : `${next.trim()}\n${key}=${newPassword}\n`.trimStart();
    process.env[key] = newPassword;
  }
  writeFileSync(ENV_PATH, next.endsWith("\n") ? next : `${next}\n`);
}

export async function callBackendSearch(payload: {
  query?: string;
  queries?: string[];
  max_results?: number;
  include_pages?: boolean;
  lane?: string;
}) {
  const res = await fetch(`${BACKEND_API_URL}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`Backend search error: ${res.status} ${await res.text()}`);
  }
  return await res.json() as {
    queries: string[];
    results: Array<{ title: string; url: string; snippet: string; domain: string; score: number }>;
    evidence: Array<{ title: string; url: string; text: string; domain: string }>;
    timings: { total_ms: number; lane: string };
  };
}

export async function callBackendPython(payload: {
  user: string;
  code: string;
  stdin?: string;
  timeout_seconds?: number;
}) {
  const res = await fetch(`${BACKEND_API_URL}/api/python/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`Backend python error: ${res.status} ${await res.text()}`);
  }
  return await res.json() as {
    stdout: string;
    stderr: string;
    returncode: number;
    timed_out: boolean;
    files_created: string[];
  };
}

export function formatSearchPayload(payload: {
  queries: string[];
  results: Array<{ title: string; url: string; snippet: string }>;
  timings?: { total_ms: number };
}) {
  if (!payload.results.length) return "No search results.";
  const lines = payload.results.slice(0, 5).map((item) => `- [${item.title}](${item.url}) — ${item.snippet}`);
  const timing = payload.timings?.total_ms ? `\n\nSearched in ${payload.timings.total_ms}ms.` : "";
  return lines.join("\n") + timing;
}

export function loadUsers(): Record<string, any> {
  return readJson<Record<string, any>>(USERS_FILE, {});
}

export function canonicalUserId(userId: string): string {
  const raw = String(userId || "").trim().toLowerCase();
  if (!raw) return "guest";
  const users = loadUsers();
  const direct = users[raw];
  if (direct?.id) return String(direct.id).toLowerCase();
  const telegram = users[`telegram:${raw}`];
  if (telegram?.id) return String(telegram.id).toLowerCase();
  for (const value of Object.values(users)) {
    const id = String(value?.id ?? "").toLowerCase();
    if (id === raw) return id;
    const aliases = Array.isArray(value?.aliases) ? value.aliases.map((item: any) => String(item).toLowerCase()) : [];
    if (aliases.includes(raw)) return id || raw;
    if (String(value?.name ?? "").toLowerCase() === raw) return id || raw;
  }
  if (raw.startsWith("telegram:")) return canonicalUserId(raw.slice("telegram:".length));
  return raw;
}

export function resolveUser(userId: string): any {
  const canonical = canonicalUserId(userId);
  const users = loadUsers();
  const direct = users[canonical];
  if (direct?.id) return direct;
  const byId = Object.values(users).find((u) => String(u?.id ?? "").toLowerCase() === canonical);
  if (byId) return byId;
  return { id: canonical, name: canonical, role: "user", aliases: [] };
}

function ensureJsonFile(path: string, empty: unknown) {
  if (!existsSync(path)) writeJson(path, empty);
}

export function ensureKnownUserScaffolds() {
  for (const userId of ["baris"]) {
    ensureJsonFile(join(PROFILES_DIR, `${userId}.json`), {});
    ensureJsonFile(join(NOTES_DIR, `${userId}.json`), []);
    ensureJsonFile(join(REMINDERS_DIR, `${userId}.json`), []);
    ensureJsonFile(join(SHOPPING_DIR, `${userId}.json`), []);
    ensureJsonFile(join(FOOD_DIR, `${userId}.json`), []);
    ensureJsonFile(join(HEALTH_DIR, `${userId}.json`), { weight: [], workouts: [], water: {} });
    ensureJsonFile(join(HABITS_DIR, `${userId}.json`), { habits: {}, logs: [] });
    ensureJsonFile(join(PEOPLE_DIR, `${userId}.json`), {});
    ensureJsonFile(join(MOOD_DIR, `${userId}.json`), []);
    ensureJsonFile(join(JOURNAL_DIR, `${userId}.json`), []);
    ensureJsonFile(join(LOCAL_CAL_DIR, `${userId}.json`), []);
  }
}

export interface UserProfile {
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

export function loadProfile(userId: string): UserProfile {
  userId = canonicalUserId(userId);
  ensureDir(PROFILES_DIR);
  return readJson<UserProfile>(join(PROFILES_DIR, `${userId}.json`), {});
}

export function saveProfile(userId: string, profile: UserProfile) {
  userId = canonicalUserId(userId);
  ensureDir(PROFILES_DIR);
  writeJson(join(PROFILES_DIR, `${userId}.json`), profile);
}

const MEMORY_USERS_DIR = join(MEMORIES_DIR, "users");
const MEMORY_ARCHIVE_DIR = join(DATA_DIR, "archive", "2026-04-15-memory-indexing", "memories");
const MEMORY_SCHEMA_VERSION = 2;

export interface MemoryObject {
  schema_version: number;
  memory_id: string;
  sequence_no: number;
  user_id: string;
  owner_user_id: string;
  allowed_user_ids: string[];
  title: string;
  summary: string;
  content: string;
  memory_type: "long_term" | "short_term";
  entity: string;
  status: "active" | "deleted";
  created_at: string;
  updated_at: string;
  added_on: string;
  expires_on: string | null;
  source: Record<string, any>;
}

export interface MemoryGuide {
  schema_version: number;
  user_id: string;
  title: string;
  allowed_user_ids: string[];
  next_memory_index: number;
  memory_ids: string[];
  active_memory_ids: string[];
  files_by_id: Record<string, string>;
  indexes: {
    by_entity: Record<string, string[]>;
    by_type: Record<string, string[]>;
    by_date: Record<string, string[]>;
  };
  counts: {
    total: number;
    active: number;
    deleted: number;
  };
  updated_at: string;
}

function nowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function slugUserId(userId: string): string {
  return userId.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "user";
}

function userMemoryDir(userId: string): string {
  return join(MEMORY_USERS_DIR, slugUserId(userId));
}

function memoryObjectsDir(userId: string): string {
  return join(userMemoryDir(userId), "objects");
}

function memoryGuidePath(userId: string): string {
  return join(userMemoryDir(userId), "guide.json");
}

function legacyMemoryPath(userId: string): string {
  return join(MEMORIES_DIR, `${userId}.json`);
}

function defaultMemoryGuide(userId: string): MemoryGuide {
  return {
    schema_version: MEMORY_SCHEMA_VERSION,
    user_id: userId,
    title: `Memory guide for ${userId}`,
    allowed_user_ids: [userId],
    next_memory_index: 1,
    memory_ids: [],
    active_memory_ids: [],
    files_by_id: {},
    indexes: {
      by_entity: {},
      by_type: {},
      by_date: {},
    },
    counts: {
      total: 0,
      active: 0,
      deleted: 0,
    },
    updated_at: nowIso(),
  };
}

function shortMemoryTitle(note: string): string {
  const compact = note.replace(/\s+/g, " ").trim().replace(/[. ]+$/, "");
  if (!compact) return "Untitled memory";
  const words = compact.split(" ");
  const base = words.slice(0, 6).join(" ");
  return `${base}${words.length > 6 ? "..." : ""}`.slice(0, 80);
}

function memorySummary(note: string): string {
  return note.replace(/\s+/g, " ").trim().slice(0, 160);
}

function isActiveMemory(item: MemoryObject): boolean {
  if (item.status !== "active") return false;
  return !item.expires_on || item.expires_on >= today();
}

function loadMemoryObjectsRaw(userId: string): MemoryObject[] {
  const dir = memoryObjectsDir(userId);
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => readJson<MemoryObject | null>(join(dir, name), null))
    .filter((item): item is MemoryObject => !!item)
    .sort((a, b) => a.sequence_no - b.sequence_no);
}

function writeMemoryObject(userId: string, item: MemoryObject) {
  ensureDir(memoryObjectsDir(userId));
  writeJson(join(memoryObjectsDir(userId), `${item.memory_id}.json`), item);
}

function rebuildMemoryGuide(userId: string): MemoryGuide {
  const current = readJson<MemoryGuide>(memoryGuidePath(userId), defaultMemoryGuide(userId));
  const items = loadMemoryObjectsRaw(userId);
  const guide = defaultMemoryGuide(userId);
  guide.allowed_user_ids = current.allowed_user_ids?.length ? current.allowed_user_ids : [userId];
  let maxIndex = 0;
  for (const item of items) {
    guide.memory_ids.push(item.memory_id);
    guide.files_by_id[item.memory_id] = `objects/${item.memory_id}.json`;
    maxIndex = Math.max(maxIndex, item.sequence_no ?? 0);
    if (item.status === "deleted") guide.counts.deleted += 1;
    if (!isActiveMemory(item)) continue;
    guide.active_memory_ids.push(item.memory_id);
    const entity = item.entity || "self";
    const kind = item.memory_type || "long_term";
    const day = item.added_on || today();
    guide.indexes.by_entity[entity] ??= [];
    guide.indexes.by_type[kind] ??= [];
    guide.indexes.by_date[day] ??= [];
    guide.indexes.by_entity[entity].push(item.memory_id);
    guide.indexes.by_type[kind].push(item.memory_id);
    guide.indexes.by_date[day].push(item.memory_id);
  }
  guide.counts.total = items.length;
  guide.counts.active = guide.active_memory_ids.length;
  guide.next_memory_index = maxIndex ? maxIndex + 1 : 1;
  guide.updated_at = nowIso();
  writeJson(memoryGuidePath(userId), guide);
  return guide;
}

function createMemoryObject(
  userId: string,
  sequenceNo: number,
  note: string,
  memoryType: "long_term" | "short_term",
  entity?: string,
  title?: string,
  addedOn?: string,
  expiresOn?: string | null,
): MemoryObject {
  const memoryId = `${slugUserId(userId)}-${String(sequenceNo).padStart(6, "0")}`;
  const timestamp = nowIso();
  return {
    schema_version: MEMORY_SCHEMA_VERSION,
    memory_id: memoryId,
    sequence_no: sequenceNo,
    user_id: userId,
    owner_user_id: userId,
    allowed_user_ids: [userId],
    title: (title?.trim() || shortMemoryTitle(note)).slice(0, 80),
    summary: memorySummary(note),
    content: note.trim(),
    memory_type: memoryType,
    entity: entity?.trim().toLowerCase() || "self",
    status: "active",
    created_at: timestamp,
    updated_at: timestamp,
    added_on: addedOn || today(),
    expires_on: expiresOn ?? null,
    source: { kind: "chat", saved_by_user_id: userId },
  };
}

function migrateLegacyMemoryFile(userId: string) {
  const legacyPath = legacyMemoryPath(userId);
  if (!existsSync(legacyPath)) return;
  ensureDir(memoryObjectsDir(userId));
  ensureDir(MEMORY_ARCHIVE_DIR);
  const legacy = readJson<any>(legacyPath, {});
  const fallbackDate = statSync(legacyPath).mtime.toISOString().slice(0, 10);
  const normalized = Array.isArray(legacy) ? { long_term: legacy, short_term: [], entities: {} } : (legacy ?? {});
  let sequenceNo = 1;

  const pushItem = (note: string, memoryType: "long_term" | "short_term", entity?: string, addedOn?: string, expiresOn?: string | null) => {
    const trimmed = String(note || "").trim();
    if (!trimmed) return;
    writeMemoryObject(userId, createMemoryObject(userId, sequenceNo, trimmed, memoryType, entity, undefined, addedOn, expiresOn));
    sequenceNo += 1;
  };

  for (const note of normalized.long_term ?? []) pushItem(String(note), "long_term", "self", fallbackDate, null);
  for (const item of normalized.short_term ?? []) {
    if (typeof item === "string") pushItem(item, "short_term", "self", fallbackDate, null);
    else pushItem(String(item?.note ?? ""), "short_term", "self", String(item?.added ?? fallbackDate), item?.expires ?? null);
  }
  for (const [entity, bucket] of Object.entries<any>(normalized.entities ?? {})) {
    for (const note of bucket?.long_term ?? []) pushItem(String(note), "long_term", entity, fallbackDate, null);
    for (const item of bucket?.short_term ?? []) {
      if (typeof item === "string") pushItem(item, "short_term", entity, fallbackDate, null);
      else pushItem(String(item?.note ?? ""), "short_term", entity, String(item?.added ?? fallbackDate), item?.expires ?? null);
    }
  }

  const archivePath = join(MEMORY_ARCHIVE_DIR, `${userId}.json`);
  if (!existsSync(archivePath)) copyFileSync(legacyPath, archivePath);
  unlinkSync(legacyPath);
}

export function ensureUserMemoryStore(userId: string): MemoryGuide {
  userId = canonicalUserId(userId);
  ensureDir(MEMORIES_DIR);
  ensureDir(MEMORY_USERS_DIR);
  if (!existsSync(memoryGuidePath(userId)) && existsSync(legacyMemoryPath(userId))) {
    migrateLegacyMemoryFile(userId);
  }
  ensureDir(memoryObjectsDir(userId));
  if (!existsSync(memoryGuidePath(userId))) writeJson(memoryGuidePath(userId), defaultMemoryGuide(userId));
  return rebuildMemoryGuide(userId);
}

export function loadMemoryGuide(userId: string): MemoryGuide {
  return ensureUserMemoryStore(userId);
}

export function listMemoryObjects(userId: string, entity?: string): MemoryObject[] {
  userId = canonicalUserId(userId);
  ensureUserMemoryStore(userId);
  const target = entity?.trim().toLowerCase();
  return loadMemoryObjectsRaw(userId).filter((item) => isActiveMemory(item) && (!target || item.entity === target));
}

export function addMemoryObject(userId: string, note: string, memoryType: "long_term" | "short_term", entity?: string, title?: string): MemoryObject {
  userId = canonicalUserId(userId);
  const guide = ensureUserMemoryStore(userId);
  const expiresOn = memoryType === "short_term" ? expiry() : null;
  const item = createMemoryObject(userId, guide.next_memory_index, note, memoryType, entity, title, today(), expiresOn);
  writeMemoryObject(userId, item);
  rebuildMemoryGuide(userId);
  return item;
}

export function forgetMemoryObject(userId: string, note: string, entity?: string): MemoryObject | null {
  userId = canonicalUserId(userId);
  ensureUserMemoryStore(userId);
  const targetEntity = entity?.trim().toLowerCase();
  const items = loadMemoryObjectsRaw(userId).sort((a, b) => b.sequence_no - a.sequence_no);
  for (const item of items) {
    if (!isActiveMemory(item)) continue;
    if (targetEntity && item.entity !== targetEntity) continue;
    if (item.content !== note.trim()) continue;
    item.status = "deleted";
    item.updated_at = nowIso();
    writeMemoryObject(userId, item);
    rebuildMemoryGuide(userId);
    return item;
  }
  return null;
}

export function consolidateMemoryObjects(userId: string, summary: string, notesToRemove: string[], entity?: string): number {
  userId = canonicalUserId(userId);
  ensureUserMemoryStore(userId);
  const targets = new Set(notesToRemove.map((item) => item.trim()).filter(Boolean));
  const targetEntity = entity?.trim().toLowerCase();
  let removed = 0;
  for (const item of loadMemoryObjectsRaw(userId)) {
    if (!isActiveMemory(item)) continue;
    if (item.memory_type !== "short_term") continue;
    if (targetEntity && item.entity !== targetEntity) continue;
    if (!targets.has(item.content.trim())) continue;
    item.status = "deleted";
    item.updated_at = nowIso();
    writeMemoryObject(userId, item);
    removed += 1;
  }
  addMemoryObject(userId, summary, "long_term", entity);
  rebuildMemoryGuide(userId);
  return removed;
}

export function formatMemoryObjects(userId: string, entity?: string): string {
  userId = canonicalUserId(userId);
  const items = listMemoryObjects(userId, entity);
  if (!items.length) return entity ? `No memories about ${entity}.` : "No memories yet.";
  return items
    .map((item) => {
      const entityLabel = item.entity && item.entity !== "self" ? ` [${item.entity}]` : "";
      const expires = item.expires_on ? ` (expires ${item.expires_on})` : "";
      return `- [${item.memory_id}] ${item.title}${entityLabel} — ${item.content}${expires}`;
    })
    .join("\n");
}

const WMO: Record<number, string> = {
  0: "Clear sky",
  1: "Mainly clear",
  2: "Partly cloudy",
  3: "Overcast",
  45: "Fog",
  51: "Light drizzle",
  61: "Slight rain",
  63: "Moderate rain",
  65: "Heavy rain",
  71: "Slight snow",
  73: "Moderate snow",
  80: "Showers",
  95: "Thunderstorm",
};

export async function fetchWeather(lat: number, lon: number, days = 3): Promise<string> {
  const params = new URLSearchParams({
    latitude: lat.toFixed(4),
    longitude: lon.toFixed(4),
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
    "",
    "Forecast:",
    ...data.daily.time.map((date: string, i: number) =>
      `  ${date}: ${WMO[data.daily.weather_code[i]] ?? "?"}, ${data.daily.temperature_2m_min[i]}–${data.daily.temperature_2m_max[i]}°C, rain ${data.daily.precipitation_sum[i]}mm`,
    ),
  ].join("\n");
}

export interface CalendarCreds {
  username: string;
  password: string;
}

export function loadCreds(userId: string): CalendarCreds | null {
  userId = canonicalUserId(userId);
  ensureDir(CREDS_DIR);
  const path = join(CREDS_DIR, `${userId}.json`);
  return existsSync(path) ? readJson<CalendarCreds>(path, null as any) : null;
}

export function saveCreds(userId: string, creds: CalendarCreds) {
  userId = canonicalUserId(userId);
  ensureDir(CREDS_DIR);
  const path = join(CREDS_DIR, `${userId}.json`);
  writeJson(path, creds);
  chmodSync(path, 0o600);
}

export async function getICloudClient(creds: CalendarCreds) {
  return createDAVClient({
    serverUrl: "https://caldav.icloud.com",
    credentials: { username: creds.username, password: creds.password },
    authMethod: "Basic",
    defaultAccountType: "caldav",
  });
}

export function parseEventFromIcal(icalData: string): { summary: string; dtstart: string; location?: string } | null {
  try {
    const summary = icalData.match(/SUMMARY[^:]*:([^\r\n]+)/)?.[1]?.trim() ?? "Untitled";
    const dtstart = icalData.match(/DTSTART[^:]*:([^\r\n]+)/)?.[1]?.trim() ?? "";
    const location = icalData.match(/LOCATION[^:]*:([^\r\n]+)/)?.[1]?.trim();
    const dt = dtstart.replace(/(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/, "$1-$2-$3 $4:$5");
    return { summary, dtstart: dt, location };
  } catch {
    return null;
  }
}

export interface LocalEvent {
  id: string;
  title: string;
  date: string;
  time: string;
  duration_minutes: number;
  notes?: string;
  location?: string;
  created: string;
}

export function loadLocalCal(userId: string): LocalEvent[] {
  userId = canonicalUserId(userId);
  ensureDir(LOCAL_CAL_DIR);
  return readJson<LocalEvent[]>(join(LOCAL_CAL_DIR, `${userId}.json`), []);
}

export function saveLocalCal(userId: string, events: LocalEvent[]) {
  userId = canonicalUserId(userId);
  ensureDir(LOCAL_CAL_DIR);
  writeJson(join(LOCAL_CAL_DIR, `${userId}.json`), events);
}

export interface ShoppingItem {
  id: string;
  item: string;
  qty?: string;
  added: string;
  done: boolean;
}

export function loadShopping(userId: string): ShoppingItem[] {
  userId = canonicalUserId(userId);
  ensureDir(SHOPPING_DIR);
  return readJson<ShoppingItem[]>(join(SHOPPING_DIR, `${userId}.json`), []);
}

export function saveShopping(userId: string, items: ShoppingItem[]) {
  userId = canonicalUserId(userId);
  ensureDir(SHOPPING_DIR);
  writeJson(join(SHOPPING_DIR, `${userId}.json`), items);
}

export interface FoodEntry {
  id: string;
  meal: string;
  calories: number;
  meal_type?: string;
  date: string;
  time: string;
  notes?: string;
}

export function loadFood(userId: string): FoodEntry[] {
  userId = canonicalUserId(userId);
  ensureDir(FOOD_DIR);
  return readJson<FoodEntry[]>(join(FOOD_DIR, `${userId}.json`), []);
}

export function saveFood(userId: string, entries: FoodEntry[]) {
  userId = canonicalUserId(userId);
  ensureDir(FOOD_DIR);
  writeJson(join(FOOD_DIR, `${userId}.json`), entries);
}

export interface HealthData {
  weight: { date: string; weight_kg: number; notes?: string }[];
  workouts: { id: string; date: string; time: string; type: string; duration_minutes: number; calories_burned?: number; notes?: string }[];
  water: Record<string, number>;
}

export function loadHealth(userId: string): HealthData {
  userId = canonicalUserId(userId);
  ensureDir(HEALTH_DIR);
  return readJson<HealthData>(join(HEALTH_DIR, `${userId}.json`), { weight: [], workouts: [], water: {} });
}

export function saveHealth(userId: string, data: HealthData) {
  userId = canonicalUserId(userId);
  ensureDir(HEALTH_DIR);
  writeJson(join(HEALTH_DIR, `${userId}.json`), data);
}

export interface HabitData {
  habits: Record<string, { description?: string; frequency: string; created: string }>;
  logs: { habit: string; date: string; notes?: string }[];
}

export function loadHabits(userId: string): HabitData {
  userId = canonicalUserId(userId);
  ensureDir(HABITS_DIR);
  return readJson<HabitData>(join(HABITS_DIR, `${userId}.json`), { habits: {}, logs: [] });
}

export function saveHabits(userId: string, data: HabitData) {
  userId = canonicalUserId(userId);
  ensureDir(HABITS_DIR);
  writeJson(join(HABITS_DIR, `${userId}.json`), data);
}

export function calcStreak(logs: { habit: string; date: string }[], habitName: string): number {
  const dates = new Set(logs.filter((entry) => entry.habit === habitName).map((entry) => entry.date));
  let streak = 0;
  const d = new Date();
  if (!dates.has(today())) d.setDate(d.getDate() - 1);
  while (true) {
    if (!dates.has(d.toISOString().slice(0, 10))) break;
    streak++;
    d.setDate(d.getDate() - 1);
  }
  return streak;
}

export interface Person {
  name: string;
  relationship?: string;
  birthday?: string;
  notes: string[];
  created: string;
  updated: string;
}

export function loadPeople(userId: string): Record<string, Person> {
  userId = canonicalUserId(userId);
  ensureDir(PEOPLE_DIR);
  return readJson<Record<string, Person>>(join(PEOPLE_DIR, `${userId}.json`), {});
}

export function savePeople(userId: string, data: Record<string, Person>) {
  userId = canonicalUserId(userId);
  ensureDir(PEOPLE_DIR);
  writeJson(join(PEOPLE_DIR, `${userId}.json`), data);
}

export interface MoodEntry {
  id: string;
  date: string;
  time: string;
  score: number;
  notes?: string;
  factors?: string[];
}

export function loadMood(userId: string): MoodEntry[] {
  userId = canonicalUserId(userId);
  ensureDir(MOOD_DIR);
  return readJson<MoodEntry[]>(join(MOOD_DIR, `${userId}.json`), []);
}

export function saveMood(userId: string, entries: MoodEntry[]) {
  userId = canonicalUserId(userId);
  ensureDir(MOOD_DIR);
  writeJson(join(MOOD_DIR, `${userId}.json`), entries);
}

export interface JournalEntry {
  id: string;
  date: string;
  time: string;
  type: "journal" | "dream";
  raw?: string;
  summary: string;
  themes?: string[];
  emotions?: string[];
  symbols?: string[];
  tags?: string[];
}

export function loadJournal(userId: string): JournalEntry[] {
  userId = canonicalUserId(userId);
  ensureDir(JOURNAL_DIR);
  return readJson<JournalEntry[]>(join(JOURNAL_DIR, `${userId}.json`), []);
}

export function saveJournal(userId: string, entries: JournalEntry[]) {
  userId = canonicalUserId(userId);
  ensureDir(JOURNAL_DIR);
  writeJson(join(JOURNAL_DIR, `${userId}.json`), entries);
}

export function noteFile(userId: string) {
  userId = canonicalUserId(userId);
  ensureDir(NOTES_DIR);
  return join(NOTES_DIR, `${userId}.json`);
}

export function reminderFile(userId: string) {
  userId = canonicalUserId(userId);
  ensureDir(REMINDERS_DIR);
  return join(REMINDERS_DIR, `${userId}.json`);
}
