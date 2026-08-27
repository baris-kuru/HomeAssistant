# Persona Pivot — Phase 0 Complete (2026-04-17)

## What Was Done

### Deleted
- `whisper-service/` (standalone service)
- `.venv-llama-build/` (llama.cpp build environment)
- `runtime/` (llama-slots, llama-swap, bin, models)
- `scripts/` (6 files: model switch, Ollama setup, OpenClaw sync)
- `start-llama-swap.sh`
- `warm-models.js`
- `config/llama-swap.yaml`
- `backend/services/ollama.py`
- `docling-service.py`
- `backend/services/python_runner.py`

### Removed from code
- `/api/python/run` endpoint (RCE) from `backend/routes.py`
- `run_python_script` import from `backend/routes.py`
- `PYTHON_TOOL` definition + handler from `backend/agent.py`
- `PYTHON_HINTS` from `backend/services/router.py`
- Python heuristic block from `_heuristic_plan` in `backend/agent.py`
- `run_python` from fast-lane early exit set

### Renamed/Rebranded
- "Home Assistant" → "Persona" in `frontend/index.html` (title, header, login)
- Calendar UID `@homeassistant` → `@persona` in `backend/agent.py`
- `run.sh` echo message updated
- `CLAUDE.md` title and description updated

### Cleaned
- `.gitignore` — removed dead entries (runtime dirs, agent venv)
- `.env.example` — removed all `OLLAMA_*`/`LOCAL_MODEL_*` vars, added `FIREWORKS_API_KEY`

### Smoke test result
- ✅ Import OK (`from backend.main import app` succeeds)

## Product Thesis (Updated)
**Persona: The assistant that remembers.**
Cloud-first, single-codebase, proactive memory. The wedge is "While You Slept" — a morning briefing that synthesizes calendar, weather, memory changes, and wellbeing into one card. Not a chatbot. A companion.

## Phased Roadmap

### Phase 1: Persona Core (current frontier)
- SQLite migration (`persona.db`, `user_id` on every table, WAL mode)
- LLM-based router replaces keyword matching
- Capability module structure: `backend/capabilities/{memory,calendar,weather,knowledge,wellbeing,health,shopping}`
- Conversation persistence in SQLite
- bcrypt passwords → JWT session auth
- Memory sparkles + timeline strip on frontend

### Phase 2: The Wedge
- Morning briefing MVP: scheduled Telegram digest from calendar + weather + memory changes
- Proactive UI: briefing as default view, not chat
- Auto-memory capture during conversations
- Frontend: FAB input, warm palette, journal-not-terminal feel

### Phase 3: Multi-User Household
- Household model, shared memories, cross-user briefing
- Telegram per-user auth
- Avatar becomes household ring

## What to Defer
- Docling document processing
- Multi-user (Phase 3)
- Real smart home devices
- Email integration
- Monitoring/instrumentation dashboard
- Voice orb/ambient mode
- Shopping, health, wellbeing capabilities

## First Implementation Slice
Kill RCE → bcrypt → JWT → SQLite → LLM router → memory capability → Telegram briefing

This is the smallest vertical slice that proves Persona's thesis.

## Open Questions
1. Which model tier on Fireworks for the router vs. answer vs. briefing? (Cost optimization TBD)
2. How to handle the `persona.db` migration script — manual run or auto-on-startup?
