import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse

from .schemas import (
    ConsolidateRequest,
    LoginRequest,
    SearchRequest,
    SettingsUpdate,
    TTSRequest,
    VisionRequest,
)
from .services.agent_runner import stream_agent
from .services.audit import audit_log
from .services.auth_service import create_jwt_token, decode_jwt_token, get_current_user
from .services.heartbeat import heartbeat, briefing_scheduler
from .services.conversation_store import ConversationStore
from .services.router import route_request
from .services.scheduler import chat_scheduler
from .services.search import search_service
from .services.telegram_service import get_user_id_from_telegram, send_message
from .services.user_store import canonical_user_id, get_user, verify_password
from .services.whisper import transcribe_file
from .middleware.security import auth_rate_limiter, get_client_ip, sanitize_messages, ws_rate_limiter
from .middleware.request_context import get_request_id


def _strip_reasoning_chain(text: str) -> str:
    """Remove Qwen-style reasoning chains from agent output.

    Models like qwen3p6-plus sometimes emit a reasoning preamble such as:
        'Here's a thinking process:\\n1. Analyze...'
    This function extracts only the final answer portion.
    """
    indicators = [
        "Here's a thinking process:",
        "Here's a thinking process",
        "Here is a thinking process:",
        "Here is a thinking process",
        "Let me think through this",
        "1. **Analyze User Input:**",
        "<think>",
        "thinking process",
    ]
    for marker in indicators:
        idx = text.find(marker)
        if idx != -1:
            # Everything after the reasoning block is the real answer.
            # Look for the last occurrence of a clear answer-delimiter.
            remainder = text[idx:]
            for answer_marker in ["Final answer:", "Final Answer:", "**Final answer:**"]:
                am_idx = remainder.rfind(answer_marker)
                if am_idx != -1:
                    answer = remainder[am_idx + len(answer_marker):].strip()
                    if answer:
                        return answer
            # If no answer marker found, find the last substantial line after
            # the reasoning numbering stops (look for lines that don't start with
            # a number/bullet).
            lines = remainder.rsplit("\n\n", 1)
            if len(lines) > 1:
                candidate = lines[-1].strip()
                if candidate and not re.match(r"^\d+[\.\)]\s", candidate):
                    return candidate
            # Fallback: return text after the first marker, skip numbered lines
            after_marker = remainder[len(marker):]
            # Extract the last non-empty paragraph that doesn't look like reasoning
            paragraphs = after_marker.strip().split("\n\n")
            for p in reversed(paragraphs):
                p = p.strip()
                if p and not re.match(r"^\d+[\.\)]\s", p) and len(p) > 5:
                    return p
    return text


router = APIRouter()
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
logger = logging.getLogger(__name__)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency that rejects non-admin users with 403."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


@router.post("/api/auth/login")
async def login(request: Request, body: LoginRequest):
    """POST /api/auth/login — verify credentials and return a JWT.

    Rate-limited: 5 attempts per minute per username+IP.
    """
    username = canonical_user_id(body.username)
    limit_key = f"{username}:{get_client_ip(request)}"
    auth_rate_limiter.check("login", limit_key)

    password = body.password
    if not verify_password(username, password):
        return JSONResponse(status_code=401, content={"detail": "Invalid credentials"})
    user = get_user(username)
    role = user.get("role", "user") if user else "user"
    token_version = user.get("token_version", 1) if user else 1
    token = create_jwt_token(username, role, token_version=token_version, expires_delta=timedelta(hours=24))
    audit_log(username, "login", {"ip": get_client_ip(request)}, ip_address=get_client_ip(request))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": username,
            "name": user.get("name", username.capitalize()) if user else username.capitalize(),
            "role": role,
        },
    }


@router.post("/api/auth/refresh")
async def refresh(request: Request, authorization: str = Header(None)):
    """POST /api/auth/refresh — return a new JWT with extended expiry.

    Rate-limited: 10 refreshes per minute per IP.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Missing or invalid Authorization header"})
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_jwt_token(token)
    except Exception:
        return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})
    user_id = claims.get("user_id")
    limit_key = f"{user_id}:{get_client_ip(request)}"
    auth_rate_limiter.check("refresh", limit_key)
    role = claims.get("role", "user")
    token_version = claims.get("token_version", 1)
    new_token = create_jwt_token(user_id, role, token_version=token_version, expires_delta=timedelta(hours=24))
    audit_log(user_id, "token_refresh", {"ip": get_client_ip(request)}, ip_address=get_client_ip(request))
    return {
        "access_token": new_token,
        "token_type": "bearer",
    }


@router.get("/api/health")
async def health_check():
    """Simple health check. Returns 200 if the app is up."""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/api/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    _user: dict = Depends(get_current_user),  # require auth
):
    ext = {
        "audio/webm": ".webm",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
    }.get(file.content_type, ".webm")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    return await transcribe_file(tmp_path)


def _safe_upload_name(raw: str | None) -> str:
    """Strip directory components and disallowed chars so uploads can't escape UPLOADS_DIR."""
    base = os.path.basename(raw or "upload.bin").strip() or "upload.bin"
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned.lstrip(".") or "upload.bin"


@router.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    _user: dict = Depends(get_current_user),  # require auth
):
    name = _safe_upload_name(file.filename)
    dest = UPLOADS_DIR / name
    async with aiofiles.open(dest, "wb") as f:
        await f.write(await file.read())
    return {"name": name}


@router.post("/api/search")
async def search(
    body: SearchRequest,
    _user: dict = Depends(get_current_user),  # require auth
):
    payload = await search_service.search(
        query=body.query,
        queries=body.queries,
        max_results=body.max_results,
        include_pages=body.include_pages,
        lane=body.lane,
    )
    return JSONResponse(payload)




@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    # Accept token via query parameter (?token=xxx) or Authorization header.
    # NOTE: Query param is used because the WebSocket API in browsers does not
    # support custom headers. The token will be masked in logs (first 8 chars only).
    # Tokens should be short-lived (24h default).
    # TODO: Migrate to a ticket-based approach (exchange JWT for a short-lived session
    # ticket via HTTP, then use ticket in WS query param) for production hardening.
    query_token = ws.query_params.get("token")
    auth_header = ws.headers.get("authorization")

    jwt_token = None
    if query_token:
        jwt_token = query_token
        # Log masked token for debugging (first 8 chars only to avoid full token in logs)
        masked = jwt_token[:8] + "..." if jwt_token else "none"
        logger.info(f"WebSocket auth attempt with token: {masked}")
    elif auth_header and auth_header.startswith("Bearer "):
        jwt_token = auth_header.split(" ", 1)[1].strip()

    if not jwt_token:
        await ws.close(code=4003, reason="Missing authentication token")
        return

    try:
        claims = decode_jwt_token(jwt_token)
    except Exception:
        await ws.close(code=4003, reason="Invalid or expired token")
        return

    user_id = claims.get("user_id")
    if not user_id:
        await ws.close(code=4003, reason="Invalid token claims")
        return

    await ws.accept()
    conversation_id = None
    conv_store = ConversationStore()

    try:
        while True:
            data = await ws.receive_json()

            # Rate limit per user (30 messages / 60s)
            try:
                ws_rate_limiter.check(user_id)
            except HTTPException:
                await ws.send_json({"type": "text", "content": "You're sending messages too fast. Please slow down."})
                await ws.send_json({"type": "done"})
                continue

            # Sanitize and bound messages before routing/LLM
            raw_messages = data.get("messages", [])
            messages = sanitize_messages(raw_messages)
            location = data.get("location")
            attachments = [a for a in (data.get("attachments", []) or []) if isinstance(a, str)][:5]

            decision = await route_request(messages, attachments=attachments)

            # Create conversation on first message
            if conversation_id is None and messages:
                # Get the first user message as title
                first_user_msg = next((m for m in messages if m.get("role") == "user"), None)
                title = first_user_msg.get("content", "")[:100] if first_user_msg else None

                conversation_id = conv_store.create_conversation(
                    user_id=user_id,
                    title=title,
                    lane=decision.lane,
                    domain=decision.domain,
                    decision={
                        "lane": decision.lane,
                        "domain": decision.domain,
                        "reason": decision.reason,
                        "confidence": decision.confidence,
                    }
                )

                # Store all previous messages in the conversation
                for msg in messages[:-1]:  # Exclude the current message (last one)
                    conv_store.add_message(
                        conversation_id=conversation_id,
                        role=msg.get("role", "user"),
                        content=str(msg.get("content", "")),
                    )

            snapshot = await chat_scheduler.snapshot(user_id, decision.lane)
            if snapshot["queued"] or snapshot["active_total"] >= snapshot["max_concurrent"]:
                await ws.send_json(
                    {
                        "type": "status",
                        "content": (
                            f"Queued behind {snapshot['ahead']} request(s). "
                            f"Running {snapshot['active_total']}/{snapshot['max_concurrent']} active jobs."
                        ),
                    }
                )

            # Store the current user message
            if conversation_id and messages:
                current_msg = messages[-1]
                conv_store.add_message(
                    conversation_id=conversation_id,
                    role=current_msg.get("role", "user"),
                    content=str(current_msg.get("content", "")),
                )

            try:
                async with chat_scheduler.slot(user_id, decision.lane):
                    response_content = []
                    async for chunk in stream_agent(messages, user_id, location, attachments=attachments, decision=decision):
                        await ws.send_json(chunk)
                        # Collect text chunks for storing assistant response
                        if chunk.get("type") == "text":
                            response_content.append(chunk.get("content", ""))

                    # Store assistant response
                    if conversation_id and response_content:
                        conv_store.add_message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content="".join(response_content),
                        )
                        
                        # Auto-capture memories from conversation
                        try:
                            from .services.memory_capture import capture_memories_auto
                            captured = capture_memories_auto(
                                user_id=user_id,
                                conversation_history=messages,
                                assistant_response="".join(response_content)
                            )
                            if captured:
                                logger.info(f"Auto-captured {len(captured)} memories for {user_id}")
                        except Exception as e:
                            logger.error(f"Auto-memory capture failed: {e}")
            except Exception as e:
                await ws.send_json({"type": "text", "content": f"\n\n**Error:** {e}"})
            await ws.send_json({"type": "done"})
    except WebSocketDisconnect:
        pass
    finally:
        # Close conversation on disconnect
        if conversation_id:
            conv_store.close_conversation(conversation_id)


@router.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, bg: BackgroundTasks):
    """Receive Telegram webhook updates."""
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    received = request.headers.get("x-telegram-bot-api-secret-token", "")
    if expected and received != expected:
        logger.warning("Invalid webhook secret attempt")
        return JSONResponse(status_code=403, content={"detail": "Invalid webhook secret"})

    body = await request.json()
    message = body.get("message", {})
    if not message:
        return JSONResponse({"ok": True})
    
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    
    if not chat_id or not text:
        return JSONResponse({"ok": True})
    
    # Get user ID from Telegram chat ID
    user_id = get_user_id_from_telegram(chat_id)
    if not user_id:
        bg.add_task(send_message, chat_id, "Sorry, I don't recognize you. Please ask the admin to link your Telegram account.")
        return JSONResponse({"ok": True})
    
    # Build message history
    messages = [{"role": "user", "content": text}]
    
    # Route and run agent
    decision = await route_request(messages)
    
    # Collect response chunks with a timeout (Telegram webhooks wait ~30s max)
    response_text = []
    timed_out = False
    timeout_seconds = 28  # Stay under Telegram's ~30s timeout with a safety margin

    async def _collect_response():
        nonlocal response_text
        async with chat_scheduler.slot(user_id, decision.lane):
            async for chunk in stream_agent(messages, user_id, None, attachments=[], decision=decision, max_tool_rounds=1):
                if chunk.get("type") == "text":
                    response_text.append(chunk.get("content", ""))

    try:
        await asyncio.wait_for(_collect_response(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        timed_out = True
    except Exception:
        bg.add_task(send_message, chat_id, "Sorry, something went wrong. Please try again.")
        return JSONResponse({"ok": True})

    # Send response back to Telegram
    full_response = "".join(response_text).strip()
    # Strip out any reasoning chains the model may have emitted
    full_response = _strip_reasoning_chain(full_response)
    # Handle partial response on timeout - add ellipsis if text seems cut off
    if timed_out and full_response and not any(full_response.rstrip().endswith(c) for c in ".!?"):
        full_response = full_response.rstrip() + "…"
    
    # Truncate to avoid exceeding Telegram's 4096 character limit
    if len(full_response) > 4000:
        full_response = full_response[:4000] + "…"
    
    if full_response:
        bg.add_task(send_message, chat_id, full_response)
    elif timed_out:
        bg.add_task(send_message, chat_id, "I'm still working on that — it's taking a bit longer than usual. Try asking again in a moment.")
    else:
        bg.add_task(send_message, chat_id, "I'm not sure how to help with that.")

    return JSONResponse({"ok": True})


@router.post("/api/briefing/send")
async def trigger_briefing(_user: dict = Depends(get_current_user)):
    """Manually trigger a briefing (for testing or on-demand)."""
    user_id = _user.get("user_id") or _user.get("id")
    success = await heartbeat.send_briefing_now(user_id)
    return {"sent": success}


@router.get("/api/briefing/latest")
async def get_briefing_latest(_user: dict = Depends(get_current_user)):
    """Get the latest briefing for a user (generates on-demand if needed)."""
    from .services.briefing_generator import BriefingGenerator
    user_id = _user.get("user_id") or _user.get("id")
    briefing = await BriefingGenerator.generate_briefing(user_id)
    return {"briefing": briefing, "generated_at": datetime.now().isoformat()}


@router.get("/api/context")
async def get_context(_user: dict = Depends(get_current_user)):
    """Get context summary for the current user (memories, events, weather)."""
    from .services.memory_store_sqlite import SqlMemoryStore
    user_id = _user.get("id")

    # Count new memories (added today)
    today = datetime.now().date().isoformat()
    memories = SqlMemoryStore.get_memories(user_id)
    new_memories = sum(1 for m in memories if m.get("added_on") == today)
    
    # Count today's calendar events
    try:
        import caldav
        import os
        username = os.environ.get("ICLOUD_USERNAME", "")
        password = os.environ.get("ICLOUD_APP_PASSWORD", "")
        event_count = 0
        if username and password:
            client = caldav.DAVClient(url="https://caldav.icloud.com", username=username, password=password)
            calendars = client.principal().calendars()
            now = datetime.now()
            start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            for calendar in calendars:
                events = calendar.date_search(start=start, end=end, expand=True)
                event_count += len(list(events))
    except Exception:
        event_count = 0
    
    # Get weather
    try:
        import urllib.parse
        import httpx
        import certifi
        from .services.user_store import resolve_user
        user = resolve_user(user_id)
        location = user.get("location", {})
        lat = location.get("lat", 50.7374)
        lon = location.get("lon", 7.0982)
        params = urllib.parse.urlencode({
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "daily": "temperature_2m_max,temperature_2m_min",
            "forecast_days": 1,
            "timezone": "auto",
        })
        async with httpx.AsyncClient(timeout=10, verify=certifi.where()) as client:
            response = await client.get(f"https://api.open-meteo.com/v1/forecast?{params}")
            data = response.json()
        daily = data.get("daily", {})
        high = daily.get("temperature_2m_max", [None])[0]
        weather_str = f"{high}°C" if high else ""
    except Exception:
        weather_str = ""
    
    return {
        "new_memories": new_memories,
        "today_events": event_count,
        "weather": weather_str,
    }


@router.get("/api/briefing/status")
async def briefing_status(_user: dict = Depends(get_current_user)):
    """Get briefing status for the authenticated user (last sent, next scheduled)."""
    user_id = _user.get("id")
    last_sent_date = briefing_scheduler.get_last_sent(user_id)
    return {
        "user_id": user_id,
        "last_sent": last_sent_date.isoformat() if last_sent_date else None,
        "next_scheduled": "07:30",
    }


@router.get("/api/memories")
async def get_recent_memories(limit: int = 20, _user: dict = Depends(get_current_user)):
    """Get recent memories for timeline display."""
    from .services.memory_store_sqlite import SqlMemoryStore
    user_id = _user.get("id")

    memories = SqlMemoryStore.get_memories(user_id)
    # Limit to N most recent
    memories = memories[:limit]

    return {
        "memories": memories,
        "count": len(memories)
    }


@router.delete("/api/memories/{memory_id}")
async def delete_memory(request: Request, memory_id: int, _user: dict = Depends(get_current_user)):
    """Delete a memory by ID. Always uses the authenticated user's ID."""
    from .services.memory_capture import delete_memory_by_id

    uid = _user.get("id")
    if not uid:
        return JSONResponse(status_code=400, content={"detail": "user_id required"})

    success = delete_memory_by_id(memory_id, uid)
    if success:
        audit_log(uid, "memory_delete", {"memory_id": memory_id}, ip_address=get_client_ip(request))
        return {"deleted": True}
    return JSONResponse(status_code=404, content={"detail": "Memory not found"})


@router.post("/api/tts/synthesize")
async def tts_synthesize(body: TTSRequest, _user: dict = Depends(get_current_user)):
    """Synthesize text to speech using MMS TTS."""
    from .tts import synthesize

    wav_bytes = synthesize(body.text, language=body.language)
    if not wav_bytes:
        return JSONResponse(status_code=500, content={"detail": "TTS synthesis failed"})
    
    # Return WAV bytes with proper content type
    from fastapi.responses import Response
    return Response(content=wav_bytes, media_type="audio/wav")


@router.get("/api/conversations")
async def list_conversations(limit: int = 20, _user: dict = Depends(get_current_user)):
    """List recent conversations for the authenticated user."""
    user_id = _user.get("id")
    conv_store = ConversationStore()
    conversations = conv_store.get_recent_conversations(user_id, limit=limit)
    return {"conversations": conversations}


@router.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str, _user: dict = Depends(get_current_user)):
    """Get all messages for a specific conversation.

    Verifies the conversation belongs to the authenticated user.
    """
    from .services.db import get_connection
    conn = get_connection()
    # Verify ownership via JOIN with conversations table
    messages = conn.execute(
        "SELECT m.role, m.content, m.timestamp FROM messages m "
        "JOIN conversations c ON m.conversation_id = c.id "
        "WHERE m.conversation_id = ? AND c.user_id = ? "
        "ORDER BY m.timestamp ASC",
        (conversation_id, _user.get("id")),
    ).fetchall()
    return {"messages": [{"role": m["role"], "content": m["content"], "timestamp": m["timestamp"]} for m in messages]}


@router.get("/api/memories/consolidate")
async def get_consolidation_candidates(_user: dict = Depends(get_current_user)):
    """Get groups of short-term memories that are good candidates for consolidation."""
    from .services.memory_store_sqlite import SqlMemoryStore
    import datetime

    user_id = _user.get("id")
    memories = SqlMemoryStore.get_memories(user_id, memory_type="short_term")
    
    # Group by entity
    by_entity: dict[str, list] = {}
    for m in memories:
        entity = m.get("entity") or "general"
        by_entity.setdefault(entity, []).append(m)
    
    # Filter groups with 3+ memories
    candidates = []
    for entity, items in by_entity.items():
        if len(items) >= 3:
            # Calculate age
            oldest_date = min(datetime.date.fromisoformat(m["added_on"]) for m in items)
            days_old = (datetime.date.today() - oldest_date).days
            
            candidates.append({
                "entity": entity,
                "count": len(items),
                "days_old": days_old,
                "memories": [
                    {"id": m["id"], "title": m["title"], "content": m["content"], "added_on": m["added_on"]}
                    for m in items
                ]
            })
    
    # Sort by count (most memories first)
    candidates.sort(key=lambda x: x["count"], reverse=True)
    
    return {"candidates": candidates}


@router.post("/api/memories/consolidate")
async def consolidate_memories_endpoint(request: Request, body: ConsolidateRequest, _user: dict = Depends(get_current_user)):
    """Consolidate a group of short-term memories into a single long-term memory."""
    from .services.memory_store_sqlite import SqlMemoryStore
    from .services.db import get_connection

    user_id = _user.get("id")
    notes_to_remove = []
    conn = get_connection()
    for mid in body.memory_ids:
        row = conn.execute(
            "SELECT content FROM memories WHERE id = ? AND user_id = ?", (mid, user_id)
        ).fetchone()
        if row:
            notes_to_remove.append(row["content"])

    SqlMemoryStore.consolidate_memories(
        user_id=user_id,
        summary=body.summary,
        notes_to_remove=notes_to_remove,
        entity=body.entity if body.entity != "general" else None,
    )

    audit_log(user_id, "memory_consolidate", {"count": len(body.memory_ids), "entity": body.entity}, ip_address=get_client_ip(request))
    return {"consolidated": True, "count": len(body.memory_ids)}


@router.get("/api/settings")
async def get_settings(_user: dict = Depends(get_current_user)):
    """Get user settings."""
    from .services.user_store import resolve_user
    user_id = _user.get("id")
    user = resolve_user(user_id)
    
    return {
        "language": user.get("language", "tr"),
        "briefing_time": user.get("briefing_time", "07:30"),
        "briefing_on_weekends": user.get("briefing_on_weekends", False),
        "timezone": user.get("timezone", "Europe/Berlin"),
        "notifications_enabled": user.get("notifications_enabled", True),
    }


@router.post("/api/settings")
async def update_settings(request: Request, body: SettingsUpdate, _user: dict = Depends(get_current_user)):
    """Update user settings."""
    from .services.user_store import load_users, save_users
    user_id = _user.get("id")

    users = load_users()
    if user_id not in users or not isinstance(users[user_id], dict):
        return JSONResponse(status_code=404, content={"detail": "User not found"})

    # exclude_unset so we only touch fields the client actually sent
    changed_fields = list(body.model_dump(exclude_unset=True).keys())
    for field, value in body.model_dump(exclude_unset=True).items():
        users[user_id][field] = value

    save_users(users)
    audit_log(user_id, "settings_update", {"fields": changed_fields}, ip_address=get_client_ip(request))
    return {"updated": True}


@router.post("/api/vision/describe")
async def describe_image(body: VisionRequest, _user: dict = Depends(get_current_user)):
    """Analyze an image and return a description using Fireworks vision (Kimi K2.5)."""
    header, encoded = body.image.split(",", 1)
    media_type = header.split(":")[1].split(";")[0] if ":" in header else "image/jpeg"
    
    try:
        from .services.fireworks_service import _headers, FIREWORKS_BASE_URL
        import httpx
        import certifi
        
        payload = {
            "model": "accounts/fireworks/models/qwen3p6-plus",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a vision assistant integrated into a home companion. Describe the scene briefly but accurately. Focus on: what objects are visible, who is in the image, what the setting appears to be, and any notable actions or emotions. Keep the description concise (under 150 words) and conversational."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
                        {"type": "text", "text": "What do you see in this image?"}
                    ]
                }
            ],
            "max_tokens": 300,
            "temperature": 0.3,
        }
        
        async with httpx.AsyncClient(timeout=30, verify=certifi.where()) as client:
            response = await client.post(
                f"{FIREWORKS_BASE_URL}/chat/completions",
                headers=_headers(),
                json=payload,
            )
            response.raise_for_status()
        
        data = response.json()
        description = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not description:
            return JSONResponse(status_code=500, content={"detail": "No description generated"})
        return {"description": description}
        
    except Exception as e:
        logger.error(f"Vision analysis failed: {e}")
        return JSONResponse(status_code=500, content={"detail": "Vision analysis failed"})
