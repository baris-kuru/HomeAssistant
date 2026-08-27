"""Local Whisper transcription service.

Exposes an OpenAI-compatible endpoint at POST /v1/audio/transcriptions used by
the Telegram bot (ha-assistant) for voice-note transcription. Runs faster-whisper
locally on CPU (int8). Model is configurable via the WHISPER_MODEL env var.
"""
import os
import tempfile

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")

app = FastAPI()
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    language: str | None = Form(None),
    prompt: str | None = Form(None),
):
    suffix = os.path.splitext(file.filename or "audio.ogg")[1] or ".ogg"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        segments, _ = _get_model().transcribe(
            tmp_path,
            language=language or None,
            initial_prompt=prompt or None,
            beam_size=5,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"text": text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("WHISPER_PORT", "8182")))
