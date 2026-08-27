#!/usr/bin/env python3
"""
Reset passwords for all HomeAssistant users.

Run this when you've forgotten passwords — it interactively prompts for new
passwords and writes bcrypt hashes directly into users.json.

Usage:
    cd ~/Projects/HomeAssistant
    source .venv/bin/activate
    python reset_passwords.py
"""

import getpass
import sys
from pathlib import Path

# Add the project root to the path so we can import backend modules
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.user_store import set_password, load_users


def validate_password(password: str) -> str | None:
    """Return error message if password is too weak, else None."""
    if len(password) < 6:
        return "Password must be at least 6 characters."
    if password.lower() in ("password", "123456", "qwerty"):
        return "Don't use common passwords."
    return None


def reset_user(user_id: str, display_name: str) -> bool:
    """Prompt for a new password for one user. Returns True if changed."""
    print(f"\n{'─' * 40}")
    print(f"  User: {display_name} ({user_id})")
    print(f"{'─' * 40}")

    # Check current state
    users = load_users()
    user = users.get(user_id)
    has_hash = user and "password_hash" in user if user else False
    if has_hash:
        print("  Current: hashed password exists")
    else:
        print("  Current: no password set")

    while True:
        pw1 = getpass.getpass("  New password: ")
        if not pw1:
            print("  Skipped — keeping current password.")
            return False

        error = validate_password(pw1)
        if error:
            print(f"  ⚠ {error}")
            continue

        pw2 = getpass.getpass("  Confirm:      ")
        if pw1 != pw2:
            print("  ⚠ Passwords don't match. Try again.")
            continue

        break

    set_password(user_id, pw1)
    print(f"  ✅ Password updated for {display_name}")
    return True


def main():
    print("\n" + "=" * 50)
    print("   HomeAssistant Password Reset Tool")
    print("=" * 50)
    print("\nThis will update bcrypt hashes in users.json.")
    print("All old sessions will be invalidated (token_version bumped).\n")

    users_to_reset = [
        ("baris", "Baris (admin)"),
        ("fabi", "Fabi"),
        ("ahmet", "Ahmet"),
    ]

    changed = []
    for uid, name in users_to_reset:
        if reset_user(uid, name):
            changed.append(name)

    print("\n" + "=" * 50)
    if changed:
        print(f"✅ Updated: {', '.join(changed)}")
        print("\nYou can now log in with the new passwords.")
    else:
        print("No passwords were changed.")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
