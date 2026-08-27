from .db import execute, fetchone, fetchall
import json
import datetime


class SqlMemoryStore:
    """SQLite-backed memory store replacing JSON files."""
    
    @staticmethod
    def add_memory(user_id: str, note: str, memory_type: str = "long_term", 
                   entity: str = None, title: str = None, expires_on: str = None) -> dict:
        """Add a memory entry. Returns the inserted row as dict."""
        if not title:
            words = note.strip().split()
            title = " ".join(words[:6])
            if len(words) > 6:
                title += "..."
            title = title[:80]
        
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        added_on = datetime.date.today().isoformat()
        
        cursor = execute(
            """INSERT INTO memories (user_id, memory_type, content, entity, title, added_on, expires_on, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, memory_type, note.strip(), entity, title, added_on, expires_on, 
             json.dumps({"source": "chat"}), now, now)
        )
        
        memory_id = cursor.lastrowid
        
        return {
            "memory_id": str(memory_id),
            "user_id": user_id,
            "memory_type": memory_type,
            "content": note.strip(),
            "entity": entity or "self",
            "title": title,
            "added_on": added_on,
            "expires_on": expires_on,
        }
    
    @staticmethod
    def get_memories(user_id: str, entity: str = None, memory_type: str = None) -> list[dict]:
        """Get memories for a user, optionally filtered."""
        sql = "SELECT * FROM memories WHERE user_id = ? AND is_consolidated = 0"
        params = [user_id]
        
        if entity:
            sql += " AND (entity = ? OR entity IS NULL)"
            params.append(entity)
        
        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)
        
        # Filter out expired memories
        today = datetime.date.today().isoformat()
        sql += " AND (expires_on IS NULL OR expires_on >= ?)"
        params.append(today)
        
        sql += " ORDER BY added_on DESC, id DESC"
        
        rows = fetchall(sql, tuple(params))
        return [dict(row) for row in rows]
    
    @staticmethod
    def get_short_term_due_for_review(user_id: str) -> list[dict]:
        """Get short-term memories due for consolidation."""
        review_date = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        
        rows = fetchall(
            """SELECT * FROM memories 
               WHERE user_id = ? 
                 AND memory_type = 'short_term' 
                 AND is_consolidated = 0
                 AND (expires_on IS NULL OR expires_on >= ?)
                 AND added_on <= ?
               ORDER BY added_on ASC""",
            (user_id, datetime.date.today().isoformat(), review_date)
        )
        return [dict(row) for row in rows]
    
    @staticmethod
    def forget_memory(user_id: str, *, note: str, entity: str = None) -> dict | None:
        """Delete a memory by content. Returns the deleted item or None."""
        target_note = note.strip()
        target_entity = (entity or "").strip().lower()
        
        # Find the memory
        sql = "SELECT * FROM memories WHERE user_id = ? AND is_consolidated = 0 AND content = ?"
        params = [user_id, target_note]
        
        if target_entity:
            sql += " AND (entity = ? OR entity IS NULL)"
            params.append(target_entity)
        
        # Filter out expired memories
        today = datetime.date.today().isoformat()
        sql += " AND (expires_on IS NULL OR expires_on >= ?)"
        params.append(today)
        
        sql += " ORDER BY id DESC LIMIT 1"
        
        row = fetchone(sql, tuple(params))
        
        if not row:
            return None
        
        # Delete the memory
        cursor = execute("DELETE FROM memories WHERE id = ?", (row["id"],))
        
        if cursor.rowcount > 0:
            return dict(row)
        return None
    
    @staticmethod
    def consolidate_memories(user_id: str, *, summary: str, notes_to_remove: list[str], entity: str = None) -> int:
        """Create long-term memory from short-term ones, remove originals."""
        # Mark short-term memories as consolidated
        removed = 0
        for note in notes_to_remove:
            row = fetchone(
                "SELECT id FROM memories WHERE user_id = ? AND content = ? AND memory_type = 'short_term' AND is_consolidated = 0",
                (user_id, note.strip())
            )
            if row:
                execute(
                    "UPDATE memories SET is_consolidated = 1, updated_at = datetime('now') WHERE id = ?",
                    (row["id"],)
                )
                removed += 1
        
        # Create new long-term memory
        SqlMemoryStore.add_memory(
            user_id=user_id,
            note=summary,
            memory_type="long_term",
            entity=entity
        )
        
        return removed
    
    @staticmethod
    def format_memories(user_id: str, entity: str = None) -> str:
        """Format memories as text for the agent system prompt."""
        memories = SqlMemoryStore.get_memories(user_id, entity=entity)
        
        if not memories:
            label = f" about {entity}" if entity else ""
            return f"No memories{label}."
        
        lines = []
        for item in memories:
            expires = f" (expires {item['expires_on']})" if item.get('expires_on') else ""
            entity_label = "" if item.get('entity') in {"", "self", None} else f" [{item['entity']}]"
            title = item.get('title', '')
            content = item['content']
            memory_id = item['id']
            lines.append(f"- [{memory_id}] {title}{entity_label} — {content}{expires}")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_memory_guide(user_id: str) -> str:
        """Format memory guide JSON for the agent."""
        memories = SqlMemoryStore.get_memories(user_id)
        
        # Build indexes
        by_entity = {}
        by_type = {}
        by_date = {}
        memory_ids = []
        
        for m in memories:
            mid = str(m['id'])
            memory_ids.append(mid)
            
            entity = m.get('entity') or 'self'
            by_entity.setdefault(entity, []).append(mid)
            
            mtype = m.get('memory_type', 'long_term')
            by_type.setdefault(mtype, []).append(mid)
            
            added = m.get('added_on', datetime.date.today().isoformat())
            by_date.setdefault(added, []).append(mid)
        
        guide = {
            "schema_version": 1,
            "user_id": user_id,
            "title": f"Memory guide for {user_id}",
            "allowed_user_ids": [user_id],
            "memory_ids": memory_ids,
            "active_memory_ids": memory_ids,
            "indexes": {
                "by_entity": by_entity,
                "by_type": by_type,
                "by_date": by_date,
            },
            "counts": {
                "total": len(memory_ids),
                "active": len(memory_ids),
                "deleted": 0,
            },
            "updated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        }
        
        return json.dumps(guide, indent=2, ensure_ascii=False)


# Create alias for backward compatibility
add_memory = SqlMemoryStore.add_memory
consolidate_memories = SqlMemoryStore.consolidate_memories
forget_memory = SqlMemoryStore.forget_memory
format_memories = SqlMemoryStore.format_memories
format_memory_guide = SqlMemoryStore.format_memory_guide
