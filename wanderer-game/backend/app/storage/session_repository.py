# 本文件由 codex 辅助生成（外围模块）
import sqlite3
import json
from datetime import datetime, timezone
from uuid import UUID

from backend.app.contracts.ai import AIResponse, EndingResult
from backend.app.contracts.game import GameState


class SessionRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def save(
        self,
        state: GameState,
        last_response: AIResponse | None,
        mode: str = "offline",
        replay_id: str = "demo_guarded_path",
        ending: EndingResult | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO sessions(session_id, state_json, last_response_json, ending_json, mode, replay_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                state_json=excluded.state_json,
                last_response_json=excluded.last_response_json,
                ending_json=excluded.ending_json,
                mode=excluded.mode,
                replay_id=excluded.replay_id,
                updated_at=excluded.updated_at
            """,
            (
                str(state.session_id),
                state.model_dump_json(),
                last_response.model_dump_json() if last_response else None,
                ending.model_dump_json() if ending else None,
                mode,
                replay_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()

    def get(self, session_id: UUID) -> tuple[GameState, AIResponse | None, str, str, EndingResult | None] | None:
        row = self.connection.execute(
            "SELECT state_json, last_response_json, mode, replay_id, ending_json FROM sessions WHERE session_id = ?",
            (str(session_id),),
        ).fetchone()
        if row is None:
            return None
        state = GameState.model_validate_json(row["state_json"])
        last_response = (
            AIResponse.model_validate_json(row["last_response_json"])
            if row["last_response_json"]
            else None
        )
        ending = EndingResult.model_validate_json(row["ending_json"]) if row["ending_json"] else None
        return state, last_response, row["mode"], row["replay_id"], ending

    def delete(self, session_id: UUID) -> bool:
        cursor = self.connection.execute("DELETE FROM sessions WHERE session_id = ?", (str(session_id),))
        self.connection.commit()
        return cursor.rowcount == 1

    def create_chat(self, chat_session_id: UUID, mode: str, player_name: str = "同行者") -> None:
        self.connection.execute(
            "INSERT INTO chat_sessions(chat_session_id, mode, player_name, title, messages_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(chat_session_id), mode, player_name, "新对话", "[]", datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def get_chat(self, chat_session_id: UUID) -> tuple[str, list[dict[str, str]], str] | None:
        details = self.get_chat_details(chat_session_id)
        if details is None:
            return None
        mode, messages, player_name, _title = details
        return mode, messages, player_name

    def get_chat_details(self, chat_session_id: UUID) -> tuple[str, list[dict[str, str]], str, str] | None:
        row = self.connection.execute(
            "SELECT mode, messages_json, player_name, title FROM chat_sessions WHERE chat_session_id = ?",
            (str(chat_session_id),),
        ).fetchone()
        if row is None:
            return None
        return row["mode"], json.loads(row["messages_json"]), row["player_name"], row["title"]

    def save_chat_messages(self, chat_session_id: UUID, messages: list[dict[str, str]], title: str | None = None) -> None:
        if title is None:
            self.connection.execute(
                "UPDATE chat_sessions SET messages_json = ?, updated_at = ? WHERE chat_session_id = ?",
                (json.dumps(messages, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), str(chat_session_id)),
            )
        else:
            self.connection.execute(
                "UPDATE chat_sessions SET messages_json = ?, title = ?, updated_at = ? WHERE chat_session_id = ?",
                (json.dumps(messages, ensure_ascii=False), title, datetime.now(timezone.utc).isoformat(), str(chat_session_id)),
            )
        self.connection.commit()

    def delete_chat(self, chat_session_id: UUID) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM chat_sessions WHERE chat_session_id = ?",
            (str(chat_session_id),),
        )
        self.connection.commit()
        return cursor.rowcount == 1
