#!/usr/bin/env python3
"""
Migration script: Phase 1A — Security & Auth Foundation

1. Reads FABI_PASSWORD, CANI_PASSWORD from .env
2. Hashes each with bcrypt
3. Updates users.json to add password_hash field to each user
4. Removes FABI_PASSWORD, CANI_PASSWORD (and AHMET_PASSWORD) lines from .env
5. Adds JWT_SECRET_KEY=<random_64_char_hex> to .env if not present
"""
import json
import os
import re
import sys
from pathlib import Path

# Ensure the backend package is importable
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.auth_service import hash_password

ENV_PATH = PROJECT_ROOT / ".env"
USERS_PATH = PROJECT_ROOT / "users.json"


def read_env():
    if not ENV_PATH.exists():
        return {}
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            env[key.strip()] = val.strip()
    return env


def main():
    print("=" * 50)
    print("Phase 1A Auth Migration")
    print("=" * 50)

    # Step 1: Read env
    env = read_env()
    password_map = {}
    env_keys_to_remove = ["FABI_PASSWORD", "CANI_PASSWORD"]
    
    # Check for AHMET_PASSWORD too
    if "AHMET_PASSWORD" in env:
        env_keys_to_remove.append("AHMET_PASSWORD")

    for key in env_keys_to_remove:
        value = env.get(key)
        if value:
            username = key.replace("_PASSWORD", "").lower()
            # Map CANI -> baris (per users.json alias)
            if username == "cani":
                username = "baris"
            if username in ("fabi", "baris", "ahmet"):
                password_map[username] = value
                print(f"  Found {key} (mapped to '{username}')")

    if not password_map:
        print("  No plaintext passwords found to migrate. Already done?")
    else:
        # Step 2: Hash and update users.json
        users = json.loads(USERS_PATH.read_text()) if USERS_PATH.exists() else {}
        for uid, pwd in password_map.items():
            if uid in users and isinstance(users[uid], dict):
                if "password_hash" not in users[uid]:
                    users[uid]["password_hash"] = hash_password(pwd)
                    print(f"  Stored bcrypt hash for '{uid}'")
                else:
                    print(f"  Skipping '{uid}' — already has password_hash")
        
        USERS_PATH.write_text(json.dumps(users, indent=2, ensure_ascii=False))
        print("  Updated users.json")

    # Step 3: Remove plaintext passwords from .env
    if ENV_PATH.exists():
        text = ENV_PATH.read_text()
        removed = []
        for key in env_keys_to_remove:
            if re.search(rf"^{re.escape(key)}=.*$", text, flags=re.MULTILINE):
                text = re.sub(rf"^{re.escape(key)}=.*$", "", text, flags=re.MULTILINE)
                removed.append(key)
        if removed:
            # Clean up double blank lines
            text = re.sub(r"\n{3,}", "\n\n", text)
            ENV_PATH.write_text(text.strip() + "\n")
            print(f"  Removed {', '.join(removed)} from .env")
        else:
            print("  No plaintext passwords to remove from .env")

    # Step 4: Generate JWT_SECRET_KEY if missing
    current_env = read_env()
    if "JWT_SECRET_KEY" not in current_env:
        secret = os.urandom(32).hex()
        with open(ENV_PATH, "a") as f:
            f.write(f"\nJWT_SECRET_KEY={secret}\n")
        print(f"  Generated JWT_SECRET_KEY in .env")
    else:
        print("  JWT_SECRET_KEY already present")

    print("=" * 50)
    print("Migration complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
