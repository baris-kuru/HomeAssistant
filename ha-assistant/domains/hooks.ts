import {
  FIREWORKS_QWEN_MODEL,
  loadMemoryGuide,
  resolveAssistantSelection,
  routingState,
  FIREWORKS_PROVIDER_ID,
  FIREWORKS_QWEN_MODEL_ID,
} from "../shared";

const DOMAIN_HINTS: Record<string, string[]> = {
  profile_memory: ["weather", "remember", "memory", "profile", "preference"],
  notes_reminders: ["note", "notes", "reminder", "todo"],
  shopping: ["shopping", "buy", "groceries", "grocery"],
  health: ["calorie", "meal", "food", "weight", "water", "workout", "habit"],
  wellbeing: ["mood", "journal", "dream", "person", "birthday", "relationship"],
  calendar: ["calendar", "meeting", "appointment", "schedule", "event"],
  gmail: ["gmail", "email", "emails", "inbox", "mail", "ticket", "flight", "train"],
  documents: ["upload", "attachment", "document", "pdf", "doc", "file"],
  python: ["python", "script", "code", "json output", "run this code"],
};

function detectRoute(prompt: string) {
  const text = prompt.trim().toLowerCase();
  let lane = "fast";
  if (text.startsWith("/think")) lane = "deep";
  else if (["latest", "today", "news", "current", "why", "compare", "research", "best"].some((item) => text.includes(item))) lane = "search";

  let activeDomain = "general";
  for (const [domain, hints] of Object.entries(DOMAIN_HINTS)) {
    if (hints.some((hint) => text.includes(hint))) {
      activeDomain = domain;
      break;
    }
  }

  const primaryTool = activeDomain === "general" ? [] : [`ha_${activeDomain}`];
  const allowedTools = [...primaryTool, "ha_search", "ha_identity"];
  return { lane, activeDomain, allowedTools, reason: `${lane}/${activeDomain}` };
}

function detectFastIntent(prompt: string, userId: string) {
  const text = prompt.trim();
  const lowered = text.toLowerCase();

  const memoryNote = text.match(/(?:remember that|remember|note that)\s+(.+?)(?:[.?!]|$)/i)?.[1]?.trim();
  if (memoryNote) {
    return { tool: "ha_profile_memory", action: "add_memory", args: { user_id: userId, note: memoryNote, memory_type: "long_term" } };
  }
  if (/(what did you save|what do you remember|recall memory|tell me what you saved)/i.test(text)) {
    return { tool: "ha_profile_memory", action: "recall_memory", args: { user_id: userId } };
  }
  if (/(forget memory|forget that|remove memory)/i.test(text)) {
    const note = text.replace(/.*?(forget memory|forget that|remove memory)\s*/i, "").trim().replace(/[.?!]+$/, "");
    if (note) return { tool: "ha_profile_memory", action: "forget_memory", args: { user_id: userId, note } };
  }

  if (/(show notes|list notes|what notes)/i.test(lowered)) {
    return { tool: "ha_notes_reminders", action: "list_notes", args: { user_id: userId } };
  }
  if (/(show reminders|list reminders|what reminders)/i.test(lowered)) {
    return { tool: "ha_notes_reminders", action: "list_reminders", args: { user_id: userId } };
  }
  const noteMatch = text.match(/(?:add note|note)\s+(.+?)(?:[.?!]|$)/i);
  if (noteMatch?.[1] && !/memory/.test(lowered)) {
    return { tool: "ha_notes_reminders", action: "add_note", args: { user_id: userId, text: noteMatch[1].trim() } };
  }

  const parsedCalendarWrite = parseCalendarWrite(text);
  if (parsedCalendarWrite) {
    return { tool: "ha_calendar", action: "add_event", args: { user_id: userId, ...parsedCalendarWrite } };
  }

  const calendarWriteIntent = /\b(add|save|create|schedule|book|put|set up|new)\b/i.test(text) && /\b(calendar|event|appointment|meeting|interview|meet)\b/i.test(text);
  if (!calendarWriteIntent && /(what(?:'s| is) (?:on )?my calendar|my schedule|my events|my agenda|upcoming events)/i.test(text)) {
    return { tool: "ha_calendar", action: "get_events", args: { user_id: userId, days: 7 } };
  }

  if (/(what(?:'s| is) in my inbox|check my email|check my emails|summari[sz]e my emails|summari[sz]e my inbox|recent emails|recent email|important emails)/i.test(text)) {
    return { tool: "ha_gmail", action: "recent", args: { max_results: 10, query: "in:inbox newer_than:14d" } };
  }

  if (/(change password)/i.test(lowered)) {
    return { tool: "ha_identity", action: "change_password", args: { user_id: userId } };
  }

  const pythonMatch = text.match(/```python\s*([\s\S]*?)```/i);
  if (pythonMatch?.[1]) {
    return { tool: "ha_python", action: "run", args: { user_id: userId, code: pythonMatch[1].trim() } };
  }

  return null;
}

function parseCalendarWrite(prompt: string) {
  const text = prompt.replace(/\s+/g, " ").trim();
  const lowered = text.toLowerCase();
  const writeIntent = /\b(add|save|create|schedule|book|put|set up|make|new)\b/i.test(text);
  const eventSignal = /\b(calendar|event|appointment|meeting|interview|meet)\b/i.test(text);
  if (!writeIntent || !eventSignal) return null;

  const today = new Date();
  let date = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  if (/\btomorrow\b/i.test(text)) {
    date.setDate(date.getDate() + 1);
  } else {
    const iso = text.match(/\b(20\d{2}-\d{1,2}-\d{1,2})\b/);
    const dotted = text.match(/\b(\d{1,2})[./](\d{1,2})(?:[./](20\d{2}))?\b/);
    if (iso?.[1]) {
      const [year, month, day] = iso[1].split("-").map(Number);
      date = new Date(year, month - 1, day);
    } else if (dotted) {
      const day = Number(dotted[1]);
      const month = Number(dotted[2]);
      const year = Number(dotted[3] ?? today.getFullYear());
      date = new Date(year, month - 1, day);
    }
  }

  const time24 = lowered.match(/\b(?:at|um)?\s*([01]?\d|2[0-3])(?::|\.)([0-5]\d)\b/);
  const time12 = lowered.match(/\b(?:at|um)\s+([1-9]|1[0-2])\s*(am|pm)\b/);
  let time = "";
  if (time24) {
    time = `${Number(time24[1]).toString().padStart(2, "0")}:${time24[2]}`;
  } else if (time12) {
    let hour = Number(time12[1]);
    if (time12[2] === "pm" && hour !== 12) hour += 12;
    if (time12[2] === "am" && hour === 12) hour = 0;
    time = `${hour.toString().padStart(2, "0")}:00`;
  } else {
    return null;
  }

  let title = "";
  const meet = text.match(/\bmeet(?:ing)?(?:\s+(?:with|my friend|friend))?\s+(.+?)(?=\s+(?:in|at|on)\b|\s+(?:today|tomorrow)\b|\s+\d{1,2}[:.]|$)/i);
  if (meet?.[1]) {
    const person = meet[1].replace(/^(?:with|my friend|friend)\s+/i, "").trim();
    title = `Meet ${person}`.trim();
  }
  if (!title) {
    title = text
      .replace(/^.*?\b(?:that|to)\b\s+/i, "")
      .replace(/\b(?:at|um)\s+\d{1,2}(?::|\.)\d{2}\b.*$/i, "")
      .replace(/[ .]+$/g, "")
      .slice(0, 80) || "Calendar event";
  }

  const locationMatch = text.match(/\b(?:in|at)\s+(?:a\s+|an\s+|the\s+)?(.+?)(?=\s+(?:at|um)\s+\d{1,2}(?::|\.)\d{2}\b|\s+(?:today|tomorrow)\b|$)/i);
  const location = locationMatch?.[1] && !/^\d/.test(locationMatch[1].trim()) ? locationMatch[1].trim().replace(/[ .]+$/g, "") : "";
  const dateString = [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");

  return {
    title,
    date: dateString,
    time,
    duration_minutes: 60,
    ...(location ? { location, notes: `Location: ${location}` } : {}),
  };
}

function extractPromptText(event: any): string {
  return String(event?.content ?? event?.body ?? event?.prompt ?? "").trim();
}

function matchesSlashCommand(prompt: string, command: string): boolean {
  const escaped = command.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`(^|\\s)${escaped}(\\s|$)`, "i");
  return pattern.test(prompt);
}

function chatUserId(event: any, ctx: any): string {
  const fromContext = String(ctx?.senderId ?? event?.metadata?.senderId ?? "").trim();
  if (fromContext) return fromContext;
  const prompt = extractPromptText(event);
  const senderId = prompt.match(/"sender_id"\s*:\s*"([^"]+)"/)?.[1]?.trim();
  if (senderId) return senderId;
  return "baris";
}

export function registerHooks(api: any) {
  api.on("before_dispatch", async (event: any, ctx: any) => {
    const prompt = extractPromptText(event);
    const activeSelection = resolveAssistantSelection();

    if (matchesSlashCommand(prompt, "/unc") || matchesSlashCommand(prompt, "/remote")) {
      return {
        handled: true,
        text: `Local model switching is disabled. This assistant always uses ${FIREWORKS_QWEN_MODEL}.`,
      };
    }

    if (matchesSlashCommand(prompt, "/model") || matchesSlashCommand(prompt, "/status")) {
      return {
        handled: true,
        text: `Current mode: remote. Active model: ${activeSelection.modelRef}.`,
      };
    }
  }, { name: "ha-assistant-before-dispatch", description: "Intercept Telegram slash commands before model dispatch." });

  api.on("before_agent_start", async (event: any, ctx: any) => {
    const prompt: string = event.prompt ?? "";
    const route = detectRoute(prompt);
    const userId = chatUserId(event, ctx);
    const fastIntent = detectFastIntent(prompt, userId);
    routingState.lane = route.lane;
    routingState.activeDomain = route.activeDomain;
    routingState.allowedTools = route.allowedTools;
    routingState.reason = route.reason;
    routingState.fastIntent = fastIntent;
    routingState.pendingModel = FIREWORKS_QWEN_MODEL;

    const lines: string[] = [];

    const calendarWrite = route.activeDomain === "calendar" && /\b(add|save|create|schedule|book|put|set up|new)\b/i.test(prompt);

    if (fastIntent) {
      lines.push(`Call ${fastIntent.tool} ${JSON.stringify({ action: fastIntent.action, args: fastIntent.args })} then reply in one sentence.`);
    } else if (calendarWrite) {
      const todayStr = new Date().toLocaleDateString("en-CA");
      lines.push(`Today is ${todayStr}. The user wants to add a calendar event. Call ha_calendar {action:"add_event",args:{user_id:"${userId}",title:"<short title>",date:"<YYYY-MM-DD>",time:"<HH:MM 24h>",duration_minutes:60}} — resolve "today"/"tomorrow" relative to ${todayStr}. After it succeeds, confirm in one sentence. You CAN write to the calendar; never claim you lack access.`);
    } else if (route.lane === "search") {
      lines.push("Use ha_search before answering.");
    }

    if (route.activeDomain === "documents" || /\.(pdf|docx?|xlsx?|pptx?|csv|html?)(\b|$)/i.test(prompt)) {
      lines.push("File detected — call ha_documents {action:read_document} first.");
    }

    try {
      const guide = loadMemoryGuide(userId);
      if ((guide.counts?.active ?? 0) < 15) {
        lines.push(`At the end of your reply, ask one short natural question to learn more about ${userId}. If they share something new, save it with ha_profile_memory {action:"add_memory",args:{user_id:"${userId}",note:"...",memory_type:"long_term"}}.`);
      }
    } catch {}

    if (lines.length === 0) return;
    return { prependContext: lines.join("\n") };
  }, { name: "ha-assistant-before-agent-start", description: "Inject lightweight tool-routing guidance into the agent prompt." });

  api.on("before_model_resolve", async (_event: any) => {
    const target = resolveAssistantSelection();
    routingState.routerPromise = null;
    return {
      providerOverride: target.provider,
      modelOverride: target.modelId,
    };
  }, { name: "ha-assistant-before-model-resolve", description: "Select the live remote or local llama.cpp model for the current session." });
}
