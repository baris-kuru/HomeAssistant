# Llama.cpp Switch

## Summary
- Switched the project and live OpenClaw config away from Ollama defaults to a llama.cpp/OpenAI-compatible local endpoint.
- Installed and launched `llama-swap` with a local web UI on `http://127.0.0.1:8091/ui`.
- Added repo scripts/config to manage the llama.cpp stack and to keep the OpenClaw/runtime config reproducible.

## Current State
- Working:
  - `llama-swap` is installed at `/Users/bariskuru/Projects/HomeAssistant/runtime/bin/llama-swap`.
  - launchd service `ai.homeassistant.llama-swap` is loaded and `GET /health` returns `OK`.
  - project `.env` and `~/.openclaw/openclaw.json` now point to `llama-cpp/gemma-4-e4b-q4km`.
  - backend and plugin code now support a generic local model API, not just Ollama.
- Partially working:
  - first model warm is still pending because the GGUF is downloading into the Hugging Face cache.
  - until that finishes, `POST /v1/chat/completions` through `llama-swap` will not succeed yet.
  - the OpenClaw gateway itself has not been restarted onto the new provider yet; cutover should happen after the first download completes.
- Deliberate choice:
  - local path is now text-first with `--no-mmproj` for speed and lower memory pressure.

## Important Decisions
- Default target is `ggml-org/gemma-4-E4B-it-GGUF:Q4_K_M`, not E2B, because:
  - `ggml-org/gemma-4-E2B-it-GGUF` currently exposes `Q8_0`/`bf16` only.
  - E4B provides `Q4_K_M`, which is a better fit for RAM and latency.
- `llama-server` is configured with:
  - `--ctx-size 32768`
  - `--parallel 2`
  - `--cache-type-k q8_0`
  - `--cache-type-v q4_0`
  - `--cache-prompt`
  - `--cache-reuse 256`
  - `--slot-save-path /Users/bariskuru/Projects/HomeAssistant/runtime/llama-slots/gemma-4-e4b-q4km`
- OpenClaw `contextTokens` was reduced from `262144` to `32768`.

## Verification
- `python3 -m compileall backend`
- `npx -y tsx -e "import('./ha-assistant/shared.ts')..."`
- `npx -y tsx -e "import('./ha-assistant/index.ts')..."`
- `python3 scripts/switch_local_model_to_llama_cpp.py`
- `launchctl list | rg ai.homeassistant.llama-swap`
- `curl http://127.0.0.1:8091/health`
- `curl -H 'Authorization: Bearer local-model' http://127.0.0.1:8091/v1/models`
- Direct llama.cpp warm-up confirmed the model cache is downloading under:
  - `/Users/bariskuru/.cache/huggingface/hub/models--ggml-org--gemma-4-E4B-it-GGUF`

## Next Steps
- Let the first GGUF download finish, then re-test:
  - `curl -H 'Authorization: Bearer local-model' http://127.0.0.1:8091/v1/chat/completions ...`
  - `openclaw agent --agent main ...`
- Once the local endpoint answers, restart the OpenClaw gateway and exercise one fresh Telegram turn.
- If prompt latency is still too high after the provider switch, cut OpenClaw workspace prompt weight next.
