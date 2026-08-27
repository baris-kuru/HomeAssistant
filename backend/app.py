from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router
from .middleware.request_context import RequestContextMiddleware
from .services.audit import init_audit_table
from .services.db import init_schema, run_migrations
from .services.memory_store import ensure_user_store, merge_user_memories
from .services.heartbeat import heartbeat
from .services.user_store import initialize_user_files, merge_json_file, seed_default_users


def _bootstrap_data():
    # Initialize SQLite database schema
    init_schema()
    run_migrations()
    init_audit_table()
    
    seed_default_users()
    for user_id in ("baris",):
        initialize_user_files(user_id)
        ensure_user_store(user_id)

    for source_user_id in ("cani", "6503433160"):
        merge_user_memories(source_user_id, "baris")
        merge_json_file(Path(__file__).parent.parent / "credentials" / f"{source_user_id}.json", Path(__file__).parent.parent / "credentials" / "baris.json", {})
        merge_json_file(Path(__file__).parent.parent / "people" / f"{source_user_id}.json", Path(__file__).parent.parent / "people" / "baris.json", {})
        merge_json_file(Path(__file__).parent.parent / "reminders" / f"{source_user_id}.json", Path(__file__).parent.parent / "reminders" / "baris.json", [])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start heartbeat on startup
    await heartbeat.start()
    yield
    # Stop heartbeat on shutdown
    await heartbeat.stop()


def create_app() -> FastAPI:
    _bootstrap_data()
    app = FastAPI(lifespan=lifespan)

    # Security middleware — CORS with exact origin only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://localhost:8001",
            "https://127.0.0.1:8001",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # Request ID tracking for debugging
    app.add_middleware(RequestContextMiddleware)

    app.include_router(router)

    if os.getenv("HA_ENABLE_WEB_UI", "").strip().lower() in {"1", "true", "yes"}:
        frontend_dir = Path(__file__).parent.parent / "frontend"
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    return app
