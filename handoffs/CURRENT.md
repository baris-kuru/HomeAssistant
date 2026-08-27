# Current Handoff

Active handoff: [2026-04-26-openclaw-fireworks-runtime.md](/Users/bariskuru/Projects/HomeAssistant/handoffs/2026-04-26-openclaw-fireworks-runtime.md)

## Summary
- OpenClaw is currently running on Fireworks `qwen3p6-plus`, and the live gateway is healthy on `127.0.0.1:18789`.
- The prior April 15 local-llama handoff is stale relative to the current machine state.
- Retired `llama-swap` artifacts now live in `archive/2026-04-24-single-user-cleanup/`.

## Immediate Next Steps
- Run one fresh Telegram smoke test on the current Fireworks-backed OpenClaw runtime.
- Investigate `stale-socket` Telegram restarts first if messaging feels flaky.
- Only revive the older local `llama.cpp` path if that is a deliberate product decision.
