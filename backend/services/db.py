import sqlite3
from pathlib import Path
import threading

DB_PATH = Path(__file__).parent.parent.parent / "persona.db"
_local = threading.local()


def _cleanup_stale_wal():
    """Remove stale WAL/SHM files if no other process has the DB open."""
    db_dir = DB_PATH.parent
    shm_path = db_dir / "persona.db-shm"
    wal_path = db_dir / "persona.db-wal"

    # Only remove if both exist and WAL is empty (safe to delete)
    if shm_path.exists() and wal_path.exists():
        try:
            # Check if WAL is empty (0 bytes means safe to remove)
            if wal_path.stat().st_size == 0:
                shm_path.unlink(missing_ok=True)
                wal_path.unlink(missing_ok=True)
        except (OSError, PermissionError):
            pass  # Can't remove, will retry later


_cleanup_stale_wal()


def get_connection() -> sqlite3.Connection:
    """Get thread-local connection with WAL mode enabled."""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    """Execute a write query."""
    conn = get_connection()
    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor


def fetchone(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    """Execute a read query and return one row."""
    return get_connection().execute(sql, params).fetchone()


def fetchall(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Execute a read query and return all rows."""
    return get_connection().execute(sql, params).fetchall()


def init_schema():
    """Initialize database schema from schema.sql file."""
    import time
    import logging

    schema_path = Path(__file__).parent.parent.parent / "schema.sql"
    if not schema_path.exists():
        return

    schema_sql = schema_path.read_text()

    # Retry up to 3 times with exponential backoff
    for attempt in range(3):
        try:
            conn = get_connection()
            conn.executescript(schema_sql)
            conn.commit()
            return  # Success
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1s, 2s
                    continue
                else:
                    # Last attempt failed — log warning but don't crash
                    logging.warning(f"Database locked during schema init (attempt {attempt + 1}/3). This may resolve on next startup.")
                    return  # Don't crash, just skip
            else:
                raise  # Re-raise other errors


def run_migrations():
    """Run incremental migrations that can't be in static schema (e.g. ALTER TABLE)."""
    conn = get_connection()

    # Add briefing_sent table if not exists (belt-and-suspenders with schema.sql)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS briefing_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            briefing_date TEXT NOT NULL DEFAULT (date('now')),
            sent_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_briefing_sent_user_date
            ON briefing_sent(user_id, briefing_date)
    """)
    conn.commit()
