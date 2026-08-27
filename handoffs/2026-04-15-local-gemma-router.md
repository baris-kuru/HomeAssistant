# Local Gemma Router And Broker Runtime

## Summary
- Replaced the old Anthropic-first backend loop with a local Ollama Gemma planner/executor flow.
- Added deterministic routing, lane-aware queueing, and a backend-owned parallel web search service.
- Converted the OpenClaw plugin surface from many narrow tools to broker-style domain tools.

## Current State
- Working:
  local search endpoint, lane-aware scheduler, live websocket assistant path, broker tool registration, upload-aware routing.
- Partially working:
  search synthesis is functional but still generic on wording with the small Gemma model.
- Not implemented yet:
  Google Calendar OAuth access, real Tuya control integration, polished end-user onboarding for third-party connectors.

## Important Decisions
- Backend default model is local Ollama via `OLLAMA_BASE_URL` and `OLLAMA_MODEL`.
- Planner uses structured JSON when possible, but falls back to deterministic heuristics for common household actions.
- Single primary domain bundle is enforced in the backend; the plugin mirrors this with broker tools plus shared `ha_search` and `ha_identity`.

## Verification
- `python3 -m compileall backend`
- `node --check frontend/app.js`
- `python3 - <<'PY' ... route_request(...) ... PY`
- `python3 - <<'PY' ... search_service.search(...) ... PY`
- Live `/api/search` request against a running uvicorn server on `127.0.0.1:8010`
- Live websocket chat turn:
  `Remember that I prefer tea in the evening and then tell me what you saved.`
  Result: `add_memory` was called and the assistant answered correctly.
- Live websocket search turn:
  `What is the latest Berlin weather news today?`
  Result: `search_web` was called and the assistant answered with retrieval-backed text.

## Next Steps
- Add Google Calendar OAuth flow for private Google calendars; API key alone is not enough.
- Improve retrieval answer synthesis so search lane answers include stronger citations and less generic phrasing.
- Add connector onboarding for smart-home systems like Tuya using local/open-source methods rather than password-based guidance.
