#!/usr/bin/env python3
"""One-time migration from JSON memory files to SQLite."""

import json
import sqlite3
import datetime
import shutil
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.services.db import get_connection, init_schema


def migrate():
    """Migrate JSON memory files to SQLite database."""
    
    print("=" * 60)
    print("Persona Memory Migration: JSON → SQLite")
    print("=" * 60)
    
    memories_dir = project_root / "memories" / "users"
    users_json_path = project_root / "users.json"
    
    if not memories_dir.exists():
        print(f"ERROR: Memories directory not found: {memories_dir}")
        return False
    
    # Initialize database schema
    print("\n[1/5] Initializing database schema...")
    try:
        init_schema()
        print("✓ Schema initialized successfully")
    except Exception as e:
        print(f"✗ Failed to initialize schema: {e}")
        return False
    
    conn = get_connection()
    
    # Load users from users.json
    print("\n[2/5] Loading users...")
    users_data = {}
    if users_json_path.exists():
        try:
            users_data = json.loads(users_json_path.read_text())
            print(f"✓ Loaded users.json ({len(users_data)} entries)")
        except Exception as e:
            print(f"⚠ Warning: Could not parse users.json: {e}")
    else:
        print("⚠ No users.json found, will create users from memory data")
    
    # Insert users into database
    user_count = 0
    for user_id, user_info in users_data.items():
        # Skip telegram mappings
        if user_id.startswith("telegram:"):
            continue
        
        try:
            display_name = user_info.get('name', user_id.capitalize())
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, display_name, source, is_active) VALUES (?, ?, ?, ?)",
                (user_id, display_name, 'users.json', 1)
            )
            user_count += 1
        except Exception as e:
            print(f"⚠ Warning: Could not insert user {user_id}: {e}")
    
    conn.commit()
    print(f"✓ Inserted {user_count} users into database")
    
    # Migrate memories
    print("\n[3/5] Migrating memories...")
    memory_count = 0
    error_count = 0
    
    for user_dir in memories_dir.iterdir():
        if not user_dir.is_dir():
            continue
        
        user_id = user_dir.name
        print(f"\n  Processing user: {user_id}")
        
        # Ensure user exists in database
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, display_name, source, is_active) VALUES (?, ?, ?, ?)",
            (user_id, user_id.capitalize(), 'memories', 1)
        )
        conn.commit()
        
        # Process objects directory
        objects_dir = user_dir / "objects"
        if objects_dir.exists():
            object_files = list(objects_dir.glob("*.json"))
            print(f"    Found {len(object_files)} memory objects")
            
            for obj_file in sorted(object_files):
                try:
                    with open(obj_file, 'r') as f:
                        obj_data = json.load(f)
                    
                    # Extract fields
                    content = obj_data.get('content', '')
                    memory_type = obj_data.get('memory_type', 'long_term')
                    entity = obj_data.get('entity', 'self')
                    title = obj_data.get('title', '')
                    added_on = obj_data.get('added_on', datetime.date.today().isoformat())
                    expires_on = obj_data.get('expires_on')
                    status = obj_data.get('status', 'active')
                    created_at = obj_data.get('created_at', datetime.datetime.now(datetime.timezone.utc).isoformat())
                    
                    if not content:
                        continue
                    
                    # Only migrate active memories
                    is_consolidated = 0 if status == 'active' else 1
                    
                    # Insert into memories table
                    conn.execute(
                        """INSERT INTO memories 
                           (user_id, memory_type, content, entity, title, added_on, expires_on, 
                            is_consolidated, metadata, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (user_id, memory_type, content, entity, title, added_on, expires_on,
                         is_consolidated, json.dumps(obj_data.get('source', {})), 
                         created_at, created_at)
                    )
                    memory_count += 1
                    
                except Exception as e:
                    error_count += 1
                    print(f"    ✗ Error migrating {obj_file.name}: {e}")
        
        conn.commit()
    
    print(f"\n✓ Migrated {memory_count} memories ({error_count} errors)")
    
    # Validate migration
    print("\n[4/5] Validating migration...")
    
    # Count users
    user_row = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()
    db_user_count = user_row['count'] if user_row else 0
    
    # Count memories
    mem_row = conn.execute("SELECT COUNT(*) as count FROM memories").fetchone()
    db_mem_count = mem_row['count'] if mem_row else 0
    
    # Count active memories
    active_row = conn.execute("SELECT COUNT(*) as count FROM memories WHERE is_consolidated = 0").fetchone()
    db_active_count = active_row['count'] if active_row else 0
    
    print(f"  Users in database: {db_user_count}")
    print(f"  Total memories: {db_mem_count}")
    print(f"  Active memories: {db_active_count}")
    
    # Sample verification
    print("\n  Sample memories:")
    sample_rows = conn.execute(
        "SELECT user_id, memory_type, content FROM memories LIMIT 5"
    ).fetchall()
    for row in sample_rows:
        content_preview = row['content'][:60] + "..." if len(row['content']) > 60 else row['content']
        print(f"    - [{row['user_id']}] {row['memory_type']}: {content_preview}")
    
    # Backup JSON files
    print("\n[5/5] Backing up JSON files...")
    backup_dir = project_root / "memories_backup"
    if not backup_dir.exists():
        try:
            shutil.copytree(project_root / "memories", backup_dir)
            print(f"✓ Backed up memories to {backup_dir}")
        except Exception as e:
            print(f"⚠ Warning: Could not backup memories: {e}")
            print("  JSON files preserved in original location")
    else:
        print("✓ Backup directory already exists, skipping")
    
    print("\n" + "=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print(f"\nDatabase: {project_root / 'persona.db'}")
    print(f"Users migrated: {db_user_count}")
    print(f"Memories migrated: {db_mem_count} ({db_active_count} active)")
    print(f"Errors: {error_count}")
    
    if error_count == 0:
        print("\n✓ All memories migrated successfully!")
        return True
    else:
        print(f"\n⚠ Migration completed with {error_count} errors")
        return error_count == 0


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
