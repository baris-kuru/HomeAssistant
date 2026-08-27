from .db import execute, fetchone, fetchall
import json
import datetime
import uuid


class ConversationStore:
    """SQLite-backed conversation persistence."""
    
    @staticmethod
    def create_conversation(user_id: str, title: str = None, 
                           lane: str = None, domain: str = None,
                           decision: dict = None) -> int:
        """Create a new conversation. Returns conversation_id."""
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        decision_json = json.dumps(decision) if decision else None
        
        cursor = execute(
            """INSERT INTO conversations (user_id, title, lane, domain, decision, started_at, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (user_id, title, lane, domain, decision_json, now, now, now)
        )
        
        return cursor.lastrowid
    
    @staticmethod
    def add_message(conversation_id: int, role: str, content: str,
                    tool_calls: list = None, tool_results: list = None) -> int:
        """Add a message to a conversation. Returns message_id."""
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        tool_results_json = json.dumps(tool_results) if tool_results else None
        
        cursor = execute(
            """INSERT INTO messages (conversation_id, role, content, timestamp, tool_calls, tool_results, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conversation_id, role, content, now, tool_calls_json, tool_results_json, now)
        )
        
        return cursor.lastrowid
    
    @staticmethod
    def get_conversation(conversation_id: int) -> dict | None:
        """Get a conversation by ID."""
        row = fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        if row:
            data = dict(row)
            if data.get('decision'):
                try:
                    data['decision'] = json.loads(data['decision'])
                except (json.JSONDecodeError, TypeError):
                    data['decision'] = None
            return data
        return None
    
    @staticmethod
    def get_recent_conversations(user_id: str, limit: int = 20) -> list[dict]:
        """Get N most recent conversations for a user."""
        rows = fetchall(
            """SELECT * FROM conversations 
               WHERE user_id = ? 
               ORDER BY started_at DESC 
               LIMIT ?""",
            (user_id, limit)
        )
        
        conversations = []
        for row in rows:
            data = dict(row)
            if data.get('decision'):
                try:
                    data['decision'] = json.loads(data['decision'])
                except (json.JSONDecodeError, TypeError):
                    data['decision'] = None
            conversations.append(data)
        
        return conversations
    
    @staticmethod
    def get_messages(conversation_id: int) -> list[dict]:
        """Get all messages for a conversation, ordered by timestamp."""
        rows = fetchall(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
            (conversation_id,)
        )
        
        messages = []
        for row in rows:
            data = dict(row)
            if data.get('tool_calls'):
                try:
                    data['tool_calls'] = json.loads(data['tool_calls'])
                except (json.JSONDecodeError, TypeError):
                    data['tool_calls'] = None
            if data.get('tool_results'):
                try:
                    data['tool_results'] = json.loads(data['tool_results'])
                except (json.JSONDecodeError, TypeError):
                    data['tool_results'] = None
            messages.append(data)
        
        return messages
    
    @staticmethod
    def close_conversation(conversation_id: int) -> bool:
        """Mark a conversation as inactive and set end time."""
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        cursor = execute(
            "UPDATE conversations SET is_active = 0, ended_at = ?, updated_at = ? WHERE id = ?",
            (now, now, conversation_id)
        )
        return cursor.rowcount > 0
