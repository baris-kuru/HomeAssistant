# Persona — Claude Instructions

## Run It
```bash
cd ~/Projects/HomeAssistant && source .venv/bin/activate && uvicorn backend.main:app --host 0.0.0.0 --port 8001 --ssl-keyfile key.pem --ssl-certfile cert.pem
```
- **Mac:** https://localhost:8001
- **iPhone (same WiFi):** https://192.168.178.134:8001
- Kill running instance: `kill $(lsof -ti:8001)`

## What This Is
**Persona: The assistant that remembers.** Cloud-first, single-codebase, proactive memory. FastAPI backend + vanilla JS frontend. Port **8001** with self-signed SSL.

The wedge is **"While You Slept"** — a morning briefing that synthesizes calendar, weather, memory changes, and wellbeing into one card. Not a chatbot. A companion.

## Architecture
| File | Role |
|------|------|
| `backend/main.py` | FastAPI: `/api/auth`, `/api/upload`, `/api/transcribe`, `/ws/chat`, serves frontend |
| `backend/agent.py` | Claude agent (claude-opus-4-6), all tools, memory system, user switching |
| `backend/devices.py` | Mock smart home device state (in-memory, resets on restart) |
| `frontend/index.html` | Login screen + chat UI |
| `frontend/app.js` | WS client, MediaRecorder voice (→ Whisper), login/switch flow, geolocation |
| `frontend/style.css` | Mobile-first styles |
| `memories/fabi.json` | Fabi's persistent memory (long_term, short_term, entities) |
| `memories/cani.json` | Cani's persistent memory |
| `uploads/` | Files uploaded via 📎 button |

## Users
- **Fabi**: PhD neurobiology researcher in Bonn, artist (gouache, Van Gogh, expressionism, miniatures, pastels), morning person, lots of plants. Tone: warm, intellectually curious, slightly playful.
- **Cani** (pronounced "Johnny"): AI engineer at BASF Berlin, built this assistant, night owl, remote worker who visits Fabi in Bonn. Tone: casual, direct, peer-to-peer, dry humour.
- Passwords in `.env`: `FABI_PASSWORD`, `CANI_PASSWORD`

## Cats
- **Nandi**: British Shorthair female, born April 2024, larger, timid but affectionate, loves being petted
- **Pixie**: British Shorthair female, born April 2024, more energetic and clever, follows Cani around
- Both prefer Fabi as she's lived with them longer

## Agent Tools
- `get_weather(days)` — Open-Meteo API, free, no key, uses live geolocation or defaults to Bonn
- `get_calendar_events(days)` — reads iCloud CalDAV
- `add_calendar_event(title, date, time, notes, calendar)` — adds to "Canni und Fabi" shared calendar by default
- `list_devices` / `control_device` — mock smart home devices from `devices.py`
- `recall_memory(entity?)` / `add_memory(note, memory_type, entity?)` / `forget_memory` — per-user JSON memory
- `consolidate_memories(summary, notes_to_remove, entity?)` — summarises short-term items older than 7 days into long-term
- `switch_user(username, password)` — switches active user mid-conversation
- `change_password(current, new)` — updates `.env` live
- `list_uploads` / `read_upload(filename)` — images via Claude vision, PDFs/DOCX via Docling OCR

## Telegram Bot
- Webhook endpoint: `POST /api/telegram/webhook` in `backend/routes.py`
- **28s execution timeout**: agent runs with `asyncio.wait_for(..., timeout=28)` to stay under Telegram's ~30s webhook limit
- **1 tool round max**: Telegram calls `stream_agent(..., max_tool_rounds=1)` to keep responses fast; web UI allows 2 rounds
- **4000 char cap**: responses are truncated at 4000 chars with `…` suffix to fit within Telegram's 4096 message limit
- **BackgroundTasks**: `send_message` is dispatched via FastAPI `BackgroundTasks` so the HTTP response returns immediately (Telegram retries webhook if it doesn't get a 200)
- On timeout: sends "I'm still working on that…" message instead of leaving the user hanging
- Bot token from `.env` as `TELEGRAM_BOT_TOKEN`; user mapping via `users.json` entries like `telegram:6503433160`

## Voice Input
- MediaRecorder API → POST `/api/transcribe` → faster-whisper `small` model (CPU, int8)
- Auto-stops after 2s of silence; tap ⏹ to stop early
- Works on iPhone Safari over local HTTPS (self-signed cert must be installed + trusted on device)

## iPhone Setup
1. Generate cert: `openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=192.168.178.134"`
2. AirDrop `cert.pem` to iPhone
3. Settings → General → VPN & Device Management → install cert
4. Settings → General → About → Certificate Trust Settings → toggle cert trusted
5. Make sure NordVPN is fully quit (not just disconnected)

## External Services
- **Weather**: Open-Meteo (no key needed)
- **Apple Calendar**: CalDAV via iCloud — set `ICLOUD_USERNAME` and `ICLOUD_APP_PASSWORD` (app-specific password from appleid.apple.com) in `.env`. Shared calendar is "Canni und Fabi".

## .env Keys
```
ANTHROPIC_API_KEY=
FABI_PASSWORD=
CANI_PASSWORD=
ICLOUD_USERNAME=
ICLOUD_APP_PASSWORD=
TELEGRAM_BOT_TOKEN=
FIREWORKS_API_KEY=
```

## Code Style
- Simple and direct, no over-engineering
- Vanilla JS/HTML/CSS — no frameworks, no bundlers
- No test files, no Docker, no CI
- Cloud-only — no local model infrastructure
- Model: claude-opus-4-6
- Docling and Whisper are lazy-loaded (first use only) to avoid startup memory issues
