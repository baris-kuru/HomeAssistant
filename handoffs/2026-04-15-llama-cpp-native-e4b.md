# Llama.cpp Native E4B

## Summary
- Rebuilt `llama.cpp` as native Apple Silicon and switched `llama-swap` to the `arm64` binary.
- Replaced broken `--hf-repo` model loading with stable local GGUF symlinks under `runtime/models/`.
- Exercised a real `gemma-4-e4b-q4km` completion through both direct `llama-server` and the managed `llama-swap` endpoint.

## Current State
- Working:
  - `config/llama-swap.yaml` now points at `/Users/bariskuru/llama.cpp/build-arm64/bin/llama-server`.
  - `scripts/prepare_llama_cpp_models.py` can download and link `e4b` and `26b` GGUF files into `runtime/models/`.
  - `runtime/models/gemma-4-e4b-q4km.gguf` is linked and usable.
  - `http://127.0.0.1:8091/v1/chat/completions` responds successfully for `gemma-4-e4b-q4km`.
- Partially working:
  - `gemma-4-26b-a4b-q4km` is configured but still downloading; the Hugging Face cache currently contains an `.incomplete` blob around 14 GB and growing.
  - OpenClaw has not yet been re-exercised after this native llama.cpp fix.

## Important Decisions
- The earlier slow/broken path was caused by two concrete issues:
  - `llama-server` had been built as `x86_64` via Anaconda `cmake`.
  - `--hf-repo` failed because this local `llama.cpp` build has HTTPS disabled.
- The working `E4B` profile now uses:
  - `ctx-size 16384`
  - `parallel 1`
  - prompt cache enabled
  - no quantized KV cache flags
- Quantized KV cache was removed because on this M1 Max path it required Flash Attention and caused context init failure.
- The larger model remains `26B A4B`, not `26B E4B`.
- A Hugging Face token was used transiently to speed up the `26B A4B` download, but it was not written into repo config files.

## Verification
- `file /Users/bariskuru/llama.cpp/build-arm64/bin/llama-server`
- direct run on port `10052` reached `server is listening`
- direct completion returned `ok`
- `launchctl kickstart -k gui/$(id -u)/ai.homeassistant.llama-swap`
- `curl http://127.0.0.1:8091/health`
- `curl -H 'Authorization: Bearer local-model' http://127.0.0.1:8091/v1/chat/completions ...`
- managed completion returned `ok`

## Next Steps
- Let `gemma-4-26B-A4B-it-Q4_K_M.gguf` finish downloading, then run:
  - `python3 scripts/prepare_llama_cpp_models.py 26b`
  - one direct completion
  - one `llama-swap` completion
- Restart the OpenClaw gateway and verify one fresh Telegram turn now that `E4B` is healthy.
- Next performance pass should trim OpenClaw prompt/context weight, since the provider layer is no longer the main blocker.
