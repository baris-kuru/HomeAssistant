# OpenClaw Local-Only Telegram Fix

## Summary
- Switched the live OpenClaw Telegram path back to a real local-only `ollama/gemma4:e2b` execution path.
- Cleared stale OpenClaw session state and stale tool allowlists that were keeping Claude and removed tools in the live path.
- Exercised the live assistant through `openclaw agent` and confirmed local model replies plus a persisted memory write.

## Current State
- Working:
  - `~/.openclaw/openclaw.json` now uses `primary=ollama/gemma4:e2b` with no fallbacks.
  - The live OpenClaw session store no longer pins `anthropic/claude-sonnet-4-5`.
  - Fresh gateway runs report `provider=ollama` and `model=gemma4:e2b`.
  - The live prompt tool allowlist now uses broker tools: `ha_profile_memory`, `ha_notes_reminders`, `ha_shopping`, `ha_health`, `ha_wellbeing`, `ha_calendar`, `ha_documents`, `ha_identity`, `ha_python`, `ha_search`.
  - A live memory turn saved `baris-000030` with content `I prefer tea in the evening`.
- Partially working:
  - Simple local turns still take about 43-50 seconds on Gemma because OpenClaw is still sending about 18k prompt tokens per turn.
  - The OpenClaw fast-intent layer works functionally, but it is not yet a true pre-model short-circuit.
- Not implemented yet:
  - Apple Calendar / Google OAuth connector flow.
  - Tuya/local smart-home onboarding skills.
  - A real pre-agent deterministic executor for Telegram CRUD tasks.

## Important Decisions
- Repo remains the source of truth for `/Users/bariskuru/Projects/HomeAssistant/ha-assistant`, but some critical runtime fixes live in OpenClaw state outside the repo:
  - `/Users/bariskuru/.openclaw/openclaw.json`
  - `/Users/bariskuru/.openclaw/agents/main/sessions/sessions.json`
- Archived the stale main session under:
  - `/Users/bariskuru/.openclaw/agents/main/sessions/archive/2026-04-15T18-31-11-telegram-main-reset`
- Kept Anthropic installed in OpenClaw, but removed active fallbacks for this path instead of uninstalling the provider globally.

## Verification
- `ollama ps`
- `~/.npm-global/bin/openclaw gateway status`
- `~/.npm-global/bin/openclaw health`
- `~/.npm-global/bin/openclaw sessions --json`
- `~/.npm-global/bin/openclaw agent --agent main --thinking off --message "Which model are you using right now? Reply with provider/model only." --json --timeout 90`
  - Returned `ollama/gemma4:e2b`
  - `fallbackUsed: false`
  - `durationMs: 43455`
- `~/.npm-global/bin/openclaw agent --agent main --thinking off --message "Remember that I prefer tea in the evening." --json --timeout 90`
  - Returned a successful confirmation
  - `fallbackUsed: false`
  - `durationMs: 49825`
- `rg -n "prefer tea in the evening|tea in the evening" /Users/bariskuru/Projects/HomeAssistant/memories`
  - Confirmed persistence in `memories/users/baris/objects/baris-000030.json`

## Next Steps
- Cut OpenClaw prompt weight:
  - shrink workspace docs injected into the main session
  - reduce skill prompt load
  - prune built-in tool surface if possible
- Implement a true deterministic Telegram fast lane before model invocation for memory/notes/reminders/calendar/profile/password tasks.
- Add connector flows as user-facing skills:
  - Apple Calendar / iCloud
  - Google Calendar OAuth
  - Tuya capability check with realistic local-control guidance
