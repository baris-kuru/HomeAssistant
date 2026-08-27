# Summary

Replaced the old flat `memories/<user>.json` blobs with a per-user memory object store under `memories/users/<user>/`.

# Current State

- Each user now has a `guide.json` plus one JSON file per memory object in `objects/`.
- Memory IDs are stable and sequential per user, e.g. `cani-000001`.
- Each memory object stores owner, allowed users, title, summary, content, entity, type, created date, and status.
- Legacy memory blobs were migrated automatically and copied into `archive/2026-04-15-memory-indexing/memories/`.
- The Python backend and the OpenClaw TypeScript plugin both now use the indexed memory model.
- Memory recall now returns object-aware lines with IDs and titles.
- A structured memory guide is available to the assistant via `get_memory_guide`.

# Important Decisions

- Keep isolation simple and explicit: each user only reads and writes their own memory folder, and each object stores `allowed_user_ids` with the owner only.
- Use soft deletion (`status: deleted`) instead of hard-deleting object files so guides and audits stay coherent.
- Rebuild `guide.json` from object files after each write rather than maintaining fragile incremental indexes.
- Keep the external tool verbs mostly stable (`add_memory`, `recall_memory`, `forget_memory`, `consolidate_memories`) so small-model behavior does not regress.

# Verification

- `python3 -m compileall backend`
- `node --check frontend/app.js`
- `npx -y tsx -e "import('./ha-assistant/domains/profile-memory.ts').then(() => console.log('profile-memory-import-ok'))"`
- Python memory store smoke test: add, recall, forget, guide rebuild
- TypeScript memory store smoke test: add, recall, forget, guide rebuild

# Next Steps

- Improve title generation so imported memories get cleaner short titles than the first few words.
- Add a small admin/debug view in the frontend for `guide.json` and per-user memory objects.
- Consider using memory IDs in future planner prompts when editing or deleting memories to reduce ambiguity.
