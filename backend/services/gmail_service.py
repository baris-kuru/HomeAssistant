from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from shutil import copy2
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DATA_DIR = Path(__file__).resolve().parents[2]
GOOGLE_CREDS_DIR = DATA_DIR / "credentials" / "google"
CLIENT_SECRET_PATH = GOOGLE_CREDS_DIR / "gmail-client-secret.json"
TOKEN_PATH = GOOGLE_CREDS_DIR / "gmail-token.json"


def _ensure_google_dir() -> None:
    GOOGLE_CREDS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(GOOGLE_CREDS_DIR, 0o700)


def import_client_secret(source_path: str | Path) -> dict[str, Any]:
    source = Path(source_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"OAuth client file not found: {source}")

    _ensure_google_dir()
    copy2(source, CLIENT_SECRET_PATH)
    os.chmod(CLIENT_SECRET_PATH, 0o600)
    return get_status()


def _load_token() -> Credentials | None:
    if not TOKEN_PATH.exists():
        return None
    return Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)


def _save_token(creds: Credentials) -> None:
    _ensure_google_dir()
    TOKEN_PATH.write_text(creds.to_json())
    os.chmod(TOKEN_PATH, 0o600)


def get_status() -> dict[str, Any]:
    _ensure_google_dir()
    creds = None
    token_error = None
    try:
        creds = _load_token()
    except Exception as exc:
        token_error = str(exc)

    return {
        "client_secret_present": CLIENT_SECRET_PATH.exists(),
        "token_present": TOKEN_PATH.exists(),
        "authorized": bool(creds and (creds.valid or creds.refresh_token)),
        "token_valid": bool(creds and creds.valid),
        "token_expired": bool(creds and creds.expired),
        "scopes": SCOPES,
        "client_secret_path": str(CLIENT_SECRET_PATH),
        "token_path": str(TOKEN_PATH),
        "token_error": token_error,
    }


def authorize() -> dict[str, Any]:
    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            f"Gmail OAuth desktop client file is missing at {CLIENT_SECRET_PATH}"
        )

    _ensure_google_dir()
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    _save_token(creds)
    return get_status()


def _get_credentials() -> Credentials:
    if not CLIENT_SECRET_PATH.exists():
        raise RuntimeError(
            f"Gmail client credentials are missing at {CLIENT_SECRET_PATH}. Import the desktop OAuth JSON first."
        )

    creds = _load_token()
    if not creds:
        raise RuntimeError(
            f"Gmail is not authorized yet. Run the local authorize flow to create {TOKEN_PATH}."
        )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds)

    if not creds.valid:
        raise RuntimeError("Gmail token is invalid. Re-run authorization.")

    return creds


def _gmail_service():
    creds = _get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    return value.strip()


def _header_map(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers", []) or []
    result: dict[str, str] = {}
    for item in headers:
        name = str(item.get("name", "")).lower().strip()
        if not name:
            continue
        result[name] = _decode_header(item.get("value"))
    return result


def _extract_plain_text(payload: dict[str, Any]) -> str:
    body = payload.get("body", {}) or {}
    data = body.get("data")
    if data:
        try:
            return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
        except Exception:
            return ""

    for part in payload.get("parts", []) or []:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            return _extract_plain_text(part)
    for part in payload.get("parts", []) or []:
        if part.get("mimeType", "").startswith("multipart/"):
            text = _extract_plain_text(part)
            if text:
                return text
    return ""


def _to_iso_date(header_date: str, fallback_ms: str | None) -> str:
    if header_date:
        try:
            return parsedate_to_datetime(header_date).astimezone(timezone.utc).isoformat()
        except Exception:
            pass
    if fallback_ms:
        try:
            return datetime.fromtimestamp(int(fallback_ms) / 1000, tz=timezone.utc).isoformat()
        except Exception:
            pass
    return ""


def list_recent_messages(max_results: int = 10, query: str = "in:inbox newer_than:14d") -> dict[str, Any]:
    service = _gmail_service()
    response = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max(1, min(max_results, 25)), q=query)
        .execute()
    )
    messages = response.get("messages", []) or []
    items: list[dict[str, Any]] = []

    for item in messages:
        full = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="full")
            .execute()
        )
        payload = full.get("payload", {}) or {}
        headers = _header_map(payload)
        body_text = _extract_plain_text(payload)
        snippet = (body_text or full.get("snippet") or "").strip().replace("\n", " ")
        if len(snippet) > 300:
            snippet = snippet[:297] + "..."
        items.append(
            {
                "id": full.get("id"),
                "thread_id": full.get("threadId"),
                "from": headers.get("from", ""),
                "subject": headers.get("subject", "(No subject)"),
                "date": _to_iso_date(headers.get("date", ""), full.get("internalDate")),
                "labels": full.get("labelIds", []),
                "snippet": snippet,
            }
        )

    return {
        "query": query,
        "count": len(items),
        "messages": items,
    }
