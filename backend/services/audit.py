from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from .db import execute, fetchall

logger = logging.getLogger(__name__)


def init_audit_table():
    """Create the audit_log table if it doesn't exist."""
    execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_user_time
        ON audit_log(user_id, timestamp)
    """)


def audit_log(user_id: str, action: str, details: dict[str, Any] | None = None, ip_address: str = ""):
    """Write an audit entry. Never raises — failures are logged but swallowed."""
    try:
        details_json = json.dumps(details, default=str, ensure_ascii=False) if details else None
        execute(
            "INSERT INTO audit_log (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
            (user_id, action, details_json, ip_address),
        )
    except Exception as exc:
        logger.warning(f"Audit logging failed for {action}: {exc}")
