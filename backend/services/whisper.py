import os


_whisper = None


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper


async def transcribe_file(tmp_path: str):
    """Transcribe audio using local faster-whisper (CPU, int8)."""
    try:
        model = _get_whisper()
        segments, _ = model.transcribe(tmp_path)
        transcript = " ".join(s.text.strip() for s in segments)
        return {"transcript": transcript.strip()}
    except Exception as e:
        return {"transcript": "", "error": str(e)}
    finally:
        os.unlink(tmp_path)
