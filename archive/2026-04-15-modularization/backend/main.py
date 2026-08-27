import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import aiofiles

from .agent import run_agent

app = FastAPI()
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

_whisper = None

def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper


@app.post("/api/auth")
async def auth(body: dict):
    user = body.get("user", "").lower()
    password = body.get("password", "")
    expected = os.environ.get(f"{user.upper()}_PASSWORD", "")
    ok = bool(expected) and password == expected
    return JSONResponse({"ok": ok})


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    ext = {
        "audio/webm": ".webm", "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",   "audio/wav": ".wav",
    }.get(file.content_type, ".webm")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        model = _get_whisper()
        segments, _ = model.transcribe(tmp_path)
        transcript = " ".join(s.text.strip() for s in segments)
        return {"transcript": transcript.strip()}
    except Exception as e:
        return {"transcript": "", "error": str(e)}
    finally:
        os.unlink(tmp_path)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    dest = UPLOADS_DIR / file.filename
    async with aiofiles.open(dest, "wb") as f:
        await f.write(await file.read())
    return {"name": file.filename}


@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data = await ws.receive_json()
            messages = data.get("messages", [])
            user = data.get("user", "guest")
            location = data.get("location")
            try:
                async for chunk in run_agent(messages, user, location):
                    await ws.send_json(chunk)
            except Exception as e:
                await ws.send_json({"type": "text", "content": f"\n\n**Error:** {e}"})
            await ws.send_json({"type": "done"})
    except WebSocketDisconnect:
        pass


frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
