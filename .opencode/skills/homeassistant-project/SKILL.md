---
name: homeassistant-project
description: Project-specific guidance for the HomeAssistant repo, including architecture, runtime, and working conventions
compatibility: opencode
---

## What I do

- Explain the repo layout and the main backend/frontend entry points
- Remind the agent how to run the app locally
- Reinforce project conventions like simple code, no frameworks, and minimal surface-area changes

## Key facts

- Backend: `backend/main.py`
- Agent logic: `backend/agent.py`
- Devices: `backend/devices.py`
- Frontend: `frontend/index.html`, `frontend/app.js`, `frontend/style.css`
- Local run command:

```bash
cd ~/Projects/HomeAssistant && source .venv/bin/activate && uvicorn backend.main:app --host 0.0.0.0 --port 8001 --ssl-keyfile key.pem --ssl-certfile cert.pem
```

## When to use me

Use this when a task touches multiple parts of the repo or when the agent needs project-specific context before changing code.
