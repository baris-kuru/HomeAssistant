from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any

from .user_store import canonical_user_id


ROOT_DIR = Path(__file__).resolve().parents[2]
MEMORIES_DIR = ROOT_DIR / "memories"
MEMORY_USERS_DIR = MEMORIES_DIR / "users"
ARCHIVE_DIR = ROOT_DIR / "archive" / "2026-04-15-memory-indexing" / "memories"
SCHEMA_VERSION = 2


def _today() -> str:
    return dt.date.today().isoformat()


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "user"


def _user_dir(user_id: str) -> Path:
    return MEMORY_USERS_DIR / _slug(user_id)


def _objects_dir(user_id: str) -> Path:
    return _user_dir(user_id) / "objects"


def _guide_path(user_id: str) -> Path:
    return _user_dir(user_id) / "guide.json"


def _legacy_path(user_id: str) -> Path:
    return MEMORIES_DIR / f"{user_id}.json"


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


def _short_title(note: str) -> str:
    compact = re.sub(r"\s+", " ", note).strip(" .")
    if not compact:
        return "Untitled memory"
    words = compact.split()
    title = " ".join(words[:6])
    if len(words) > 6:
        title += "..."
    return title[:80]


def _summary(note: str) -> str:
    compact = re.sub(r"\s+", " ", note).strip()
    return compact[:160]


def _default_guide(user_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "user_id": user_id,
        "title": f"Memory guide for {user_id}",
        "allowed_user_ids": [user_id],
        "next_memory_index": 1,
        "memory_ids": [],
        "active_memory_ids": [],
        "files_by_id": {},
        "indexes": {
            "by_entity": {},
            "by_type": {},
            "by_date": {},
        },
        "counts": {"total": 0, "active": 0, "deleted": 0},
        "updated_at": _now_iso(),
    }


def _memory_path(user_id: str, memory_id: str) -> Path:
    return _objects_dir(user_id) / f"{memory_id}.json"


def _object_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    return int(item.get("sequence_no", 0)), str(item.get("memory_id", ""))


def _active(item: dict[str, Any]) -> bool:
    if item.get("status") != "active":
        return False
    expires_on = item.get("expires_on")
    return not expires_on or expires_on >= _today()


def _load_objects(user_id: str) -> list[dict[str, Any]]:
    objects_dir = _objects_dir(user_id)
    if not objects_dir.exists():
        return []
    items = []
    for path in sorted(objects_dir.glob("*.json")):
        item = _read_json(path, None)
        if isinstance(item, dict):
            items.append(item)
    return sorted(items, key=_object_sort_key)


def rebuild_guide(user_id: str) -> dict[str, Any]:
    user_id = canonical_user_id(user_id)
    guide = _read_json(_guide_path(user_id), _default_guide(user_id))
    items = _load_objects(user_id)
    indexes = {"by_entity": {}, "by_type": {}, "by_date": {}}
    active_ids: list[str] = []
    files_by_id: dict[str, str] = {}
    max_index = 0
    deleted = 0

    for item in items:
        memory_id = str(item.get("memory_id", "")).strip()
        if not memory_id:
            continue
        sequence_no = int(item.get("sequence_no", 0))
        max_index = max(max_index, sequence_no)
        files_by_id[memory_id] = f"objects/{memory_id}.json"
        if item.get("status") == "deleted":
            deleted += 1
        if not _active(item):
            continue
        active_ids.append(memory_id)
        for key, value in (
            ("by_entity", str(item.get("entity", "self") or "self")),
            ("by_type", str(item.get("memory_type", "long_term"))),
            ("by_date", str(item.get("added_on", _today()))),
        ):
            indexes[key].setdefault(value, []).append(memory_id)

    next_index = max_index + 1 if max_index else 1
    guide.update(
        {
            "schema_version": SCHEMA_VERSION,
            "user_id": user_id,
            "title": f"Memory guide for {user_id}",
            "allowed_user_ids": guide.get("allowed_user_ids") or [user_id],
            "next_memory_index": next_index,
            "memory_ids": [item["memory_id"] for item in items if item.get("memory_id")],
            "active_memory_ids": active_ids,
            "files_by_id": files_by_id,
            "indexes": indexes,
            "counts": {
                "total": len(items),
                "active": len(active_ids),
                "deleted": deleted,
            },
            "updated_at": _now_iso(),
        }
    )
    _write_json(_guide_path(user_id), guide)
    return guide


def _create_memory_object(
    *,
    user_id: str,
    sequence_no: int,
    note: str,
    memory_type: str,
    entity: str | None,
    added_on: str | None = None,
    expires_on: str | None = None,
    title: str | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory_id = f"{_slug(user_id)}-{sequence_no:06d}"
    timestamp = _now_iso()
    entity_name = (entity or "self").strip().lower() or "self"
    added_date = added_on or _today()
    return {
        "schema_version": SCHEMA_VERSION,
        "memory_id": memory_id,
        "sequence_no": sequence_no,
        "user_id": user_id,
        "owner_user_id": user_id,
        "allowed_user_ids": [user_id],
        "title": (title or _short_title(note)).strip()[:80],
        "summary": _summary(note),
        "content": note.strip(),
        "memory_type": memory_type,
        "entity": entity_name,
        "status": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "added_on": added_date,
        "expires_on": expires_on,
        "source": source or {"kind": "chat", "saved_by_user_id": user_id},
    }


def _archive_legacy_file(user_id: str):
    legacy = _legacy_path(user_id)
    if not legacy.exists():
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE_DIR / legacy.name
    if not target.exists():
        shutil.copy2(legacy, target)
    legacy.unlink()


def _migrate_legacy_items(user_id: str, data: Any, legacy_mtime: str):
    if isinstance(data, list):
        data = {"long_term": data, "short_term": [], "entities": {}}
    if not isinstance(data, dict):
        data = {"long_term": [], "short_term": [], "entities": {}}

    seq = 1
    for note in data.get("long_term", []):
        item = _create_memory_object(
            user_id=user_id,
            sequence_no=seq,
            note=str(note),
            memory_type="long_term",
            entity="self",
            added_on=legacy_mtime,
        )
        _write_json(_memory_path(user_id, item["memory_id"]), item)
        seq += 1

    for note in data.get("short_term", []):
        if isinstance(note, dict):
            content = str(note.get("note", "")).strip()
            added_on = str(note.get("added", legacy_mtime))
            expires_on = note.get("expires")
        else:
            content = str(note).strip()
            added_on = legacy_mtime
            expires_on = None
        if not content:
            continue
        item = _create_memory_object(
            user_id=user_id,
            sequence_no=seq,
            note=content,
            memory_type="short_term",
            entity="self",
            added_on=added_on,
            expires_on=expires_on,
        )
        _write_json(_memory_path(user_id, item["memory_id"]), item)
        seq += 1

    for entity, entity_data in (data.get("entities") or {}).items():
        entity_name = str(entity).strip().lower() or "self"
        if not isinstance(entity_data, dict):
            continue
        for note in entity_data.get("long_term", []):
            item = _create_memory_object(
                user_id=user_id,
                sequence_no=seq,
                note=str(note),
                memory_type="long_term",
                entity=entity_name,
                added_on=legacy_mtime,
            )
            _write_json(_memory_path(user_id, item["memory_id"]), item)
            seq += 1
        for note in entity_data.get("short_term", []):
            if isinstance(note, dict):
                content = str(note.get("note", "")).strip()
                added_on = str(note.get("added", legacy_mtime))
                expires_on = note.get("expires")
            else:
                content = str(note).strip()
                added_on = legacy_mtime
                expires_on = None
            if not content:
                continue
            item = _create_memory_object(
                user_id=user_id,
                sequence_no=seq,
                note=content,
                memory_type="short_term",
                entity=entity_name,
                added_on=added_on,
                expires_on=expires_on,
            )
            _write_json(_memory_path(user_id, item["memory_id"]), item)
            seq += 1


def ensure_user_store(user_id: str) -> dict[str, Any]:
    user_id = canonical_user_id(user_id)
    guide_path = _guide_path(user_id)
    if guide_path.exists():
        return rebuild_guide(user_id)

    _objects_dir(user_id).mkdir(parents=True, exist_ok=True)
    legacy_path = _legacy_path(user_id)
    if legacy_path.exists():
        legacy_data = _read_json(legacy_path, {})
        legacy_mtime = dt.datetime.fromtimestamp(legacy_path.stat().st_mtime, tz=dt.timezone.utc).date().isoformat()
        _migrate_legacy_items(user_id, legacy_data, legacy_mtime)
        _archive_legacy_file(user_id)
    guide = rebuild_guide(user_id)
    if not guide_path.exists():
        _write_json(guide_path, guide)
    return guide


def list_active_memories(user_id: str, entity: str | None = None) -> list[dict[str, Any]]:
    user_id = canonical_user_id(user_id)
    ensure_user_store(user_id)
    target = (entity or "").strip().lower()
    items = []
    for item in _load_objects(user_id):
        if not _active(item):
            continue
        if target and str(item.get("entity", "self")).lower() != target:
            continue
        items.append(item)
    return items


def format_memory_guide(user_id: str) -> str:
    user_id = canonical_user_id(user_id)
    guide = ensure_user_store(user_id)
    return json.dumps(guide, indent=2, ensure_ascii=False)


def format_memories(user_id: str, entity: str | None = None) -> str:
    user_id = canonical_user_id(user_id)
    items = list_active_memories(user_id, entity=entity)
    if not items:
        label = f" about {entity}" if entity else ""
        return f"No memories{label}."
    lines = []
    for item in items:
        expires = f" (expires {item['expires_on']})" if item.get("expires_on") else ""
        entity_label = "" if item.get("entity") in {"", "self", None} else f" [{item['entity']}]"
        lines.append(f"- [{item['memory_id']}] {item['title']}{entity_label} — {item['content']}{expires}")
    return "\n".join(lines)


def add_memory(
    user_id: str,
    note: str,
    *,
    memory_type: str = "long_term",
    entity: str | None = None,
    title: str | None = None,
    expires_on: str | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_id = canonical_user_id(user_id)
    guide = ensure_user_store(user_id)
    sequence_no = int(guide.get("next_memory_index", 1))
    item = _create_memory_object(
        user_id=user_id,
        sequence_no=sequence_no,
        note=note,
        memory_type=memory_type,
        entity=entity,
        expires_on=expires_on,
        title=title,
        source=source,
    )
    _write_json(_memory_path(user_id, item["memory_id"]), item)
    rebuild_guide(user_id)
    return item


def _save_object(user_id: str, item: dict[str, Any]):
    user_id = canonical_user_id(user_id)
    item["updated_at"] = _now_iso()
    _write_json(_memory_path(user_id, item["memory_id"]), item)


def forget_memory(user_id: str, *, note: str, entity: str | None = None) -> dict[str, Any] | None:
    user_id = canonical_user_id(user_id)
    target_note = note.strip()
    target_entity = (entity or "").strip().lower()
    for item in reversed(_load_objects(user_id)):
        if not _active(item):
            continue
        if target_entity and str(item.get("entity", "self")).lower() != target_entity:
            continue
        if item.get("content") != target_note:
            continue
        item["status"] = "deleted"
        _save_object(user_id, item)
        rebuild_guide(user_id)
        return item
    return None


def consolidate_memories(user_id: str, *, summary: str, notes_to_remove: list[str], entity: str | None = None) -> int:
    user_id = canonical_user_id(user_id)
    target_entity = (entity or "").strip().lower()
    targets = {item.strip() for item in notes_to_remove if item.strip()}
    removed = 0
    for item in _load_objects(user_id):
        if not _active(item):
            continue
        if item.get("memory_type") != "short_term":
            continue
        if target_entity and str(item.get("entity", "self")).lower() != target_entity:
            continue
        if str(item.get("content", "")).strip() not in targets:
            continue
        item["status"] = "deleted"
        _save_object(user_id, item)
        removed += 1

    add_memory(user_id, summary, memory_type="long_term", entity=entity)
    rebuild_guide(user_id)
    return removed


def migrate_all_legacy_memories():
    MEMORY_USERS_DIR.mkdir(parents=True, exist_ok=True)
    for legacy_path in MEMORIES_DIR.glob("*.json"):
        ensure_user_store(legacy_path.stem)


def merge_user_memories(source_user_id: str, target_user_id: str) -> int:
    source_raw = str(source_user_id).strip().lower()
    target_user = canonical_user_id(target_user_id)
    source_dir = MEMORY_USERS_DIR / _slug(source_raw)
    if not source_dir.exists() or source_raw == target_user:
        return 0

    target_guide = ensure_user_store(target_user)
    next_index = int(target_guide.get("next_memory_index", 1))
    migrated = 0

    for item in _load_objects(source_raw):
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        migrated_item = _create_memory_object(
            user_id=target_user,
            sequence_no=next_index,
            note=content,
            memory_type=str(item.get("memory_type", "long_term")),
            entity=str(item.get("entity", "self")),
            added_on=str(item.get("added_on", _today())),
            expires_on=item.get("expires_on"),
            title=str(item.get("title", "")) or None,
            source={
                "kind": "migration",
                "saved_by_user_id": target_user,
                "migrated_from_user_id": source_raw,
                "source_memory_id": item.get("memory_id"),
            },
        )
        migrated_item["status"] = str(item.get("status", "active"))
        _write_json(_memory_path(target_user, migrated_item["memory_id"]), migrated_item)
        next_index += 1
        migrated += 1

    archive_dir = ROOT_DIR / "archive" / "2026-04-15-baris-identity" / "memories-users"
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, archive_dir / source_dir.name, dirs_exist_ok=True)
    shutil.rmtree(source_dir)
    rebuild_guide(target_user)
    return migrated
