# MEETING SUMMARY — Product Direction Analysis

**Date:** April 17, 2026
**Participants:** Architect, Fullstack, Review, Test, Docs

---

## Agreement

All five participants converged on the following:

1. **Product thesis: "The assistant that remembers."** This is the single differentiator from ChatGPT/Claude. Persistent, structured memory that lives across calendar, health, shopping, journal, mood, habits, people, profiles, food, and notes domains. It already tracks life dimensions that generic assistants ignore.

2. **Wedge feature: "While You Slept" morning briefing.** A proactive digest synthesizing calendar, weather, household state, memories, and tasks. Transforms the product from reactive chat to indispensable companion — something Fabi and Baris will reach for before their first coffee.

3. **Three blocking security issues must be fixed first:**
   - Kill `/api/python/run` (unauthenticated arbitrary code execution)
   - Add session authentication to WebSocket (currently trusts client-provided user string)
   - Hash passwords (plaintext in `.env` is unacceptable)

4. **Memory store must migrate from JSON files to SQLite with WAL mode** before auto-memory capture ships, because concurrent writes corrupt JSON.

5. **Kill/de-prioritize:** mock devices, identity-as-agent-tools, DuckDGo scraping (replace with proper API), dark mode (cosmetic).

6. **The chat UI is hiding the product.** Needs: household context bar, visible memory indicators, conversation history sidebar.

## Disagreement

1. **Sequencing:** Architect wanted morning briefing first. Fullstack argued UX foundation (session persistence, conversation history) must come first. **Resolved:** UX is load-bearing for proactive features. Briefing is Week 3, not Week 1.

2. **Monitoring priority:** Test argued monitoring is #1. Review argued security blocks everything. **Resolved:** Security → core UX → features → monitoring.

3. **JSON memory store for 3 users:** Fullstack said "fine for now." Test/Architect showed auto-capture increases writes 10x with corruption risk. **Resolved:** SQLite migration before auto-capture.

4. **ha-assistant/ TypeScript codebase:** Review flagged that OpenClaw domains are a more mature product (health, shopping, wellbeing, imagine/image gen) but live in a separate parallel codebase. **Resolved:** Keep ha-assistant as the OpenClaw source of truth, focus backend/python on the web/Telegram delivery layer. Don't duplicate ha-assistant domains.

## Decision

**Product direction approved with the following phased execution plan:**

### Phase 1: Secure the Foundation (Week 1)
- Kill Python sandbox, add session auth, hash passwords, split `agent.py`, atomic memory writes

### Phase 2: Make the Agent Remember (Week 2)
- SQLite migration, auto-memory capture, conversation history, async CalDAV, household context bar

### Phase 3: The Proactive Wedge (Week 3)
- Scheduled agent execution, "While You Slept" morning briefing, instrumentation, semantic LLM router

### Phase 4: Polish & Scale (Weeks 4+)
- Voice-first ambient mode, reminders with push, email integration, monitoring dashboard, product rename

## Next Actions

**Recommended workflow command:** `/project`

This is a foundational architecture and product direction change touching every layer (security, memory, UI, agent loop). It should be executed as a coordinated project with clear phases, not as isolated feature tickets.

---

## What Would Make This Better Than ChatGPT/Claude

1. **Personal memory graph** across health, mood, people, habits, food — domains no generic assistant tracks.
2. **Proactive delivery** (morning briefing, reminders via Telegram) — the agent reaches out, you don't reach for it.
3. **Voice-first ambient mode** — orb UI with silence detection is closer to a real assistant than a chat box.
4. **Multi-user household awareness** — agent knows who you are, switches context, tracks relationships between household members.
5. **Local model fallback** — Ollama integration means the core experience survives internet outages.

## What the Chat UI Is Hiding

- No visible memory indicators
- No household context bar
- No conversation history
- No proactive push
- No ambient mode entry point from lock screen

The product should feel less like "another chat window" and more like "a companion that lives on your phone and already knows what's relevant today."

---

*Source: agent meeting with architect, fullstack, review, test, docs participants.*
