-- Persona Database Schema (Phase 1B)
-- SQLite with WAL mode for concurrent read safety

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

-- Memories table (single table with memory_type discriminator)
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'long_term',
    content TEXT NOT NULL,
    entity TEXT,
    domain TEXT,
    confidence REAL,
    source TEXT,
    source_id TEXT,
    title TEXT,
    added_on TEXT NOT NULL DEFAULT (date('now')),
    expires_on TEXT,
    is_consolidated INTEGER NOT NULL DEFAULT 0,
    consolidated_into INTEGER,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (consolidated_into) REFERENCES memories(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_memory_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_entity ON memories(entity);
CREATE INDEX IF NOT EXISTS idx_memories_expires_on ON memories(expires_on);
CREATE INDEX IF NOT EXISTS idx_memories_is_consolidated ON memories(is_consolidated);
CREATE INDEX IF NOT EXISTS idx_memories_consolidated_into ON memories(consolidated_into);
CREATE INDEX IF NOT EXISTS idx_memories_added_on ON memories(added_on);

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    title TEXT,
    lane TEXT,
    domain TEXT,
    decision TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_is_active ON conversations(is_active);
CREATE INDEX IF NOT EXISTS idx_conversations_started_at ON conversations(started_at);

-- Messages table
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    tool_calls TEXT,
    tool_results TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);

-- Trigger to update message_count on message insert
CREATE TRIGGER IF NOT EXISTS trg_message_insert
AFTER INSERT ON messages
BEGIN
    UPDATE conversations
    SET message_count = message_count + 1,
        updated_at = datetime('now')
    WHERE id = NEW.conversation_id;
END;

-- Trigger to update message_count on message delete
CREATE TRIGGER IF NOT EXISTS trg_message_delete
AFTER DELETE ON messages
BEGIN
    UPDATE conversations
    SET message_count = MAX(0, message_count - 1),
        updated_at = datetime('now')
    WHERE id = OLD.conversation_id;
END;

-- Briefing tracking table
CREATE TABLE IF NOT EXISTS briefing_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    briefing_date TEXT NOT NULL DEFAULT (date('now')),
    sent_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_briefing_sent_user_date ON briefing_sent(user_id, briefing_date);

-- Trigger to update users.updated_at
CREATE TRIGGER IF NOT EXISTS trg_user_update
AFTER UPDATE ON users
BEGIN
    UPDATE users
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;
