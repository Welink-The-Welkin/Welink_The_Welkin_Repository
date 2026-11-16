# 本文件由 codex 辅助生成（外围模块）
import sqlite3
from pathlib import Path


def create_database(path: str | Path) -> sqlite3.Connection:
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            last_response_json TEXT,
            ending_json TEXT,
            mode TEXT NOT NULL DEFAULT 'offline',
            replay_id TEXT NOT NULL DEFAULT 'demo_guarded_path',
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            chat_session_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            player_name TEXT NOT NULL DEFAULT '同行者',
            title TEXT NOT NULL DEFAULT '新对话',
            messages_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        )
        """
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
    if "ending_json" not in columns:
        connection.execute("ALTER TABLE sessions ADD COLUMN ending_json TEXT")
    chat_columns = {row["name"] for row in connection.execute("PRAGMA table_info(chat_sessions)")}
    if "player_name" not in chat_columns:
        connection.execute("ALTER TABLE chat_sessions ADD COLUMN player_name TEXT NOT NULL DEFAULT '同行者'")
    if "title" not in chat_columns:
        connection.execute("ALTER TABLE chat_sessions ADD COLUMN title TEXT NOT NULL DEFAULT '新对话'")
    connection.commit()
    return connection
