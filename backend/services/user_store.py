from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .auth_service import hash_password, verify_password as bcrypt_verify


ROOT_DIR = Path(__file__).resolve().parents[2]
USERS_FILE = ROOT_DIR / "users.json"
ENV_PATH = ROOT_DIR / ".env"
ARCHIVE_DIR = ROOT_DIR / "archive" / "2026-04-15-baris-identity"

DEFAULT_USERS: dict[str, dict[str, Any]] = {
    "baris": {
        "id": "baris",
        "name": "Baris",
        "role": "admin",
        "aliases": ["cani"],
        "timezone": "Europe/Berlin",
        "location": {"lat": 50.7374, "lon": 7.0982},
    },
    "telegram:6503433160": {"id": "baris"},
}

USER_JSON_DEFAULTS: list[tuple[str, Any]] = [
    ("profiles", {}),
    ("notes", []),
    ("reminders", []),
    ("shopping", []),
    ("food", []),
    ("health", {"weight": [], "workouts": [], "water": {}}),
    ("habits", {"habits": {}, "logs": []}),
    ("people", {}),
    ("mood", []),
    ("journal", []),
    ("calendars", []),
]


def _read_json(path: Path, fallback: Any):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text())
    except Exception:
        return fallback


def _write_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_users() -> dict[str, dict[str, Any]]:
    return _read_json(USERS_FILE, {})


def save_users(data: dict[str, dict[str, Any]]):
    _write_json(USERS_FILE, data)


def seed_default_users() -> dict[str, dict[str, Any]]:
    current = load_users()
    merged = {**DEFAULT_USERS, **current}
    for user_id, defaults in DEFAULT_USERS.items():
        merged[user_id] = {**defaults, **merged.get(user_id, {})}
    # Ensure all non-telegram users have token_version initialized
    for uid, udata in merged.items():
        if isinstance(udata, dict) and "id" in udata and not uid.startswith("telegram:"):
            if "token_version" not in udata:
                udata["token_version"] = 1
    save_users(merged)
    return merged


def canonical_user_id(raw_user_id: str | None) -> str:
    text = str(raw_user_id or "").strip()
    if not text:
        return "guest"
    lowered = text.lower()
    users = load_users()
    direct = users.get(lowered)
    if isinstance(direct, dict) and direct.get("id"):
        return str(direct["id"]).lower()

    telegram = users.get(f"telegram:{lowered}")
    if isinstance(telegram, dict) and telegram.get("id"):
        return str(telegram["id"]).lower()

    for value in users.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("id", "")).lower() == lowered:
            return lowered
        aliases = [str(item).lower() for item in value.get("aliases", [])]
        if lowered in aliases:
            return str(value.get("id", lowered)).lower()
        if str(value.get("name", "")).lower() == lowered:
            return str(value.get("id", lowered)).lower()

    if lowered.startswith("telegram:"):
        return canonical_user_id(lowered.split(":", 1)[1])
    return lowered


def resolve_user(raw_user_id: str | None) -> dict[str, Any]:
    users = seed_default_users()
    canonical = canonical_user_id(raw_user_id)
    user = users.get(canonical)
    if isinstance(user, dict) and user.get("id"):
        return user
    for value in users.values():
        if isinstance(value, dict) and str(value.get("id", "")).lower() == canonical:
            return value
    return {"id": canonical, "name": canonical.capitalize(), "role": "user", "aliases": []}


def _env_value(key: str) -> str:
    if key in os.environ and os.environ[key]:
        return os.environ[key]
    if ENV_PATH.exists():
        match = re.search(rf"^{re.escape(key)}=(.*)$", ENV_PATH.read_text(), flags=re.MULTILINE)
        if match:
            return match.group(1).strip()
    return ""


def password_keys(raw_user_id: str | None) -> list[str]:
    canonical = canonical_user_id(raw_user_id)
    users = seed_default_users()
    aliases: list[str] = []
    user = resolve_user(canonical)
    aliases.extend(str(item).lower() for item in user.get("aliases", []))
    keys = [f"{canonical.upper()}_PASSWORD", *(f"{alias.upper()}_PASSWORD" for alias in aliases)]
    deduped: list[str] = []
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def get_user(user_id: str) -> dict | None:
    """Return the user dict for a given canonical user_id, or None."""
    users = load_users()
    canonical = canonical_user_id(user_id)
    return users.get(canonical)


def verify_password(raw_user_id: str | None, password: str) -> bool:
    """Verify against bcrypt hash in users.json first, fallback to .env plaintext."""
    if not password:
        return False
    canonical = canonical_user_id(raw_user_id)
    user = get_user(canonical)
    # Check bcrypt hash in users.json
    if user and "password_hash" in user:
        return bcrypt_verify(password, user["password_hash"])
    # Fallback: check plaintext .env entries (migration path)
    for key in password_keys(raw_user_id):
        expected = _env_value(key)
        if expected and expected == password:
            return True
    return False


def set_password(user_id: str, raw_password: str):
    """Set or update a password for a given user_id. Increments token_version to revoke old tokens."""
    canonical = canonical_user_id(user_id)
    users = load_users()
    if canonical not in users or not isinstance(users[canonical], dict):
        raise ValueError(f"User '{canonical}' not found in users.json")
    hashed = hash_password(raw_password)
    users[canonical]["password_hash"] = hashed
    # Increment token_version to invalidate all existing tokens
    current_version = users[canonical].get("token_version", 0)
    users[canonical]["token_version"] = current_version + 1
    save_users(users)


def update_password(raw_user_id: str | None, new_password: str):
    """Update password by storing bcrypt hash in users.json."""
    canonical = canonical_user_id(raw_user_id)
    hashed = hash_password(new_password)
    
    # Store hash in users.json
    users = load_users()
    if canonical in users and isinstance(users[canonical], dict):
        users[canonical]["password_hash"] = hashed
        # Increment token_version to invalidate all existing tokens for this user
        current_version = users[canonical].get("token_version", 0)
        users[canonical]["token_version"] = current_version + 1
    save_users(users)
    
    # Remove any old plaintext entries from .env (cleanup)
    keys = password_keys(canonical)
    if ENV_PATH.exists():
        text = ENV_PATH.read_text()
        for key in keys:
            text = re.sub(rf"^{re.escape(key)}=.*$", "", text, flags=re.MULTILINE)
        ENV_PATH.write_text(text.strip() + "\n")


def merge_json_file(source: Path, target: Path, empty: Any):
    if not source.exists():
        return
    source_data = _read_json(source, empty)
    target_data = _read_json(target, empty)

    if isinstance(empty, list):
        merged = list(target_data or [])
        seen = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in merged}
        for item in source_data or []:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    elif isinstance(empty, dict):
        merged = {**(target_data or {}), **(source_data or {})}
    else:
        merged = target_data if target_data else source_data

    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, merged)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archived = ARCHIVE_DIR / source.parent.name
    archived.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, archived / source.name)
    source.unlink()


def initialize_user_files(raw_user_id: str | None):
    user_id = canonical_user_id(raw_user_id)
    for directory, empty in USER_JSON_DEFAULTS:
        path = ROOT_DIR / directory / f"{user_id}.json"
        if path.exists():
            continue
        _write_json(path, empty)


def migrate_plaintext_passwords():
    """Hash plaintext passwords from .env into users.json and remove them from .env."""
    users = load_users()
    if not users:
        return
    # Map: username_lower -> password
    pwd_map = {}
    env_text = ENV_PATH.read_text() if ENV_PATH.exists() else ""

    for user_id, user_data in list(users.items()):
        # Skip telegram mappings
        if user_id.startswith("telegram:"):
            continue
        if not isinstance(user_data, dict):
            continue
        # Skip users that already have a password_hash
        if "password_hash" in user_data:
            continue

        # Check .env for PASSWORD entries
        username = user_id
        aliases = user_data.get("aliases", [])
        candidates = [username] + aliases

        for candidate in candidates:
            env_key = f"{candidate.upper()}_PASSWORD"
            match = re.search(rf"^{re.escape(env_key)}=(.*)$", env_text, flags=re.MULTILINE)
            if match:
                plaintext = match.group(1).strip()
                if plaintext:
                    pwd_map[candidate] = plaintext
                    break

        if not pwd_map.get(username):
            # Try direct env key based on user_id
            env_key = f"{username.upper()}_PASSWORD"
            match = re.search(rf"^{re.escape(env_key)}=(.*)$", env_text, flags=re.MULTILINE)
            if match:
                plaintext = match.group(1).strip()
                if plaintext:
                    pwd_map[username] = plaintext

        # Also handle known user mappings (cani -> baris)
        if username == "baris" and "baris" not in pwd_map:
            for key in ("CANI_PASSWORD",):
                match = re.search(rf"^{re.escape(key)}=(.*)$", env_text, flags=re.MULTILINE)
                if match and match.group(1).strip():
                    pwd_map[username] = match.group(1).strip()
                    break

    # Hash and store
    modified = False
    for username, plaintext in pwd_map.items():
        if username in users and not users[username].get("password_hash"):
            users[username]["password_hash"] = hash_password(plaintext)
            print(f"  Hashed password for '{username}'")
            modified = True

    if modified:
        save_users(users)
        print("  Password hashes written to users.json")

    # Remove plaintext password lines from .env
    if env_text:
        pattern = re.compile(r"^([A-Z]+_PASSWORD)=.*$", flags=re.MULTILINE)
        new_text = pattern.sub("", env_text)
        # Clean up blank lines
        new_text = re.sub(r"\n{2,}", "\n", new_text)
        if new_text != env_text:
            ENV_PATH.write_text(new_text.strip() + "\n")
            print("  Removed plaintext passwords from .env")
