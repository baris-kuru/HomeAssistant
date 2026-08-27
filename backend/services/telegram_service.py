import os
import logging
import httpx
import certifi

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def _get_token() -> str | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token
    # Try reading from .env file
    from pathlib import Path
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        import re
        match = re.search(r"^TELEGRAM_BOT_TOKEN=(.+)$", env_path.read_text(), re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


async def send_message(chat_id: str | int, text: str) -> bool:
    """Send a text message to a Telegram chat."""
    # QUIET_MODE: suppress all outbound Telegram messages
    if os.environ.get("HA_QUIET_MODE", "").strip() == "1":
        logger.info(f"QUIET: message suppressed (chat_id={chat_id}, text={text[:60]}...)")
        return True

    token = _get_token()
    if not token:
        return False
    
    url = f"{TELEGRAM_API_BASE}{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    
    try:
        async with httpx.AsyncClient(timeout=30, verify=certifi.where()) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return True
    except Exception:
        # Try without markdown on failure (maybe bad formatting)
        try:
            payload["parse_mode"] = None
            async with httpx.AsyncClient(timeout=30, verify=certifi.where()) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return True
        except Exception:
            return False


async def send_photo(chat_id: str | int, photo_url: str, caption: str | None = None) -> bool:
    """Send a photo to a Telegram chat by URL."""
    token = _get_token()
    if not token:
        return False
    
    url = f"{TELEGRAM_API_BASE}{token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "Markdown"
    
    try:
        async with httpx.AsyncClient(timeout=30, verify=certifi.where()) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return True
    except Exception:
        return False


def get_telegram_chat_id(user_id: str) -> str | None:
    """Look up Telegram chat ID for a user."""
    from .user_store import load_users
    
    canonical = user_id.lower().strip()
    users = load_users()
    
    # Look for telegram:XXX entries that map to this user
    for key, val in users.items():
        if key.startswith("telegram:"):
            if isinstance(val, dict) and val.get("id", "").lower() == canonical:
                return key.replace("telegram:", "")
    return None


def get_user_id_from_telegram(chat_id: str | int) -> str | None:
    """Look up user ID from Telegram chat ID."""
    from .user_store import load_users
    
    chat_id_str = str(chat_id)
    users = load_users()
    
    # Look for telegram:CHAT_ID entry
    telegram_entry = users.get(f"telegram:{chat_id_str}")
    if isinstance(telegram_entry, dict) and telegram_entry.get("id"):
        return telegram_entry["id"]
    
    return None


async def send_photo_bytes(chat_id: str | int, image_bytes: bytes, caption: str | None = None) -> bool:
    """Send an in-memory image (PNG/JPEG) to a Telegram chat via multipart upload."""
    token = _get_token()
    if not token:
        return False

    url = f"{TELEGRAM_API_BASE}{token}/sendPhoto"
    try:
        import io
        async with httpx.AsyncClient(timeout=60, verify=certifi.where()) as client:
            files = {"photo": ("image.png", io.BytesIO(image_bytes), "image/png")}
            data: dict[str, str] = {"chat_id": str(chat_id)}
            if caption:
                data["caption"] = caption[:1024]  # Telegram caption cap
            response = await client.post(url, data=data, files=files)
            response.raise_for_status()
            return True
    except Exception as e:
        logger.warning(f"send_photo_bytes failed: {e}")
        return False


async def send_voice(chat_id: str | int, wav_bytes: bytes) -> bool:
    """Send a voice note (WAV) to a Telegram chat."""
    token = _get_token()
    if not token:
        return False

    url = f"{TELEGRAM_API_BASE}{token}/sendVoice"

    try:
        import io
        async with httpx.AsyncClient(timeout=60, verify=certifi.where()) as client:
            files = {"voice": ("briefing.wav", io.BytesIO(wav_bytes), "audio/wav")}
            response = await client.post(url, files=files)
            response.raise_for_status()
            return True
    except Exception as e:
        logger.warning(f"send_voice failed: {e}")
        return False
