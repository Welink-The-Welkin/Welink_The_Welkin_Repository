# 本文件由 codex 辅助生成（外围模块）
import json
import sqlite3
from uuid import uuid4

from backend.app.contracts.ai import EndingResult
from backend.app.contracts.game import initial_state
from backend.app.storage.database import create_database
from backend.app.storage.session_repository import SessionRepository


def test_repository_saves_and_loads_a_session_snapshot(tmp_path):
    repository = SessionRepository(create_database(tmp_path / "sessions.db"))
    state = initial_state(uuid4())

    repository.save(state, last_response=None)
    restored = repository.get(state.session_id)

    assert restored is not None
    assert restored is not None
    restored_state, response, mode, replay_id, ending = restored
    assert restored_state.session_id == state.session_id
    assert restored_state.scene_id == "scene_01"
    assert response is None
    assert mode == "offline"
    assert replay_id == "demo_guarded_path"
    assert ending is None


def test_repository_deletes_a_session_snapshot(tmp_path):
    repository = SessionRepository(create_database(tmp_path / "sessions.db"))
    state = initial_state(uuid4())
    repository.save(state, last_response=None)

    assert repository.delete(state.session_id) is True
    assert repository.get(state.session_id) is None


def test_repository_persists_ending_metadata(tmp_path):
    repository = SessionRepository(create_database(tmp_path / "sessions.db"))
    state = initial_state(uuid4())
    ending = EndingResult(
        ending_id="evidence_keeper",
        title="求证者",
        summary="你选择先确认事实，再承担随之而来的责任。",
    )

    repository.save(state, last_response=None, ending=ending)

    restored = repository.get(state.session_id)
    assert restored is not None
    assert restored[4] == ending


def test_database_migrates_older_chat_rows_without_losing_messages(tmp_path):
    path = tmp_path / "older-chat-schema.db"
    chat_id = uuid4()
    old_connection = sqlite3.connect(path)
    old_connection.execute(
        "CREATE TABLE chat_sessions (chat_session_id TEXT PRIMARY KEY, mode TEXT NOT NULL, messages_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL)"
    )
    old_connection.execute(
        "INSERT INTO chat_sessions(chat_session_id, mode, messages_json, updated_at) VALUES (?, ?, ?, ?)",
        (str(chat_id), "offline", json.dumps([{"message": "旧消息", "reply": "旧回复"}], ensure_ascii=False), "2026-10-16"),
    )
    old_connection.commit()
    old_connection.close()

    migrated_connection = create_database(path)
    try:
        restored = SessionRepository(migrated_connection).get_chat(chat_id)
    finally:
        migrated_connection.close()

    assert restored == ("offline", [{"message": "旧消息", "reply": "旧回复"}], "同行者")
