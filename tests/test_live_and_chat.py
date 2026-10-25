# 本文件由 codex 辅助生成（外围模块）
import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.core.errors import ModelProviderError, ModelTimeoutError
from backend.app.core.model_client import ChatReplyEventStream
from backend.app.core.pronoun_guard import ELEMENT_SELF_REFERENCE_TERMS, FALLBACK_REPLIES, INTRO_FALLBACK_REPLIES
from backend.app.main import create_app


def test_live_session_creation_returns_initial_state(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "live.db", demo_mode_override="live"))

    response = client.post("/api/sessions", json={"mode": "live"})

    assert response.status_code == 201
    data = response.json()["data"]
    assert UUID(data["session_id"])
    assert data["state"]["turn_count"] == 0
    assert data["mode"] == "offline"
    assert data["last_response"]["reply"]


def test_free_chat_stream_emits_text_before_done_and_persists_only_after_completion(tmp_path):
    app = create_app(database_path_override=tmp_path / "stream-chat.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    response_payload = {
        "reply": "第一句。第二句！",
        "title": "流式回复",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }
    app.state.session_service.chat_model_client.generate_chat_stream = lambda **kwargs: ChatReplyEventStream(iter([
        {"type": "text", "delta": "第一句。"},
        {"type": "text", "delta": "第二句！"},
        {"type": "done", "response": response_payload},
    ]))

    response = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={"message": "你好"},
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [event["type"] for event in events] == ["text", "text", "done"]
    assert events[-1]["response"]["reply"] == "第一句。第二句！"
    restored = client.get(f"/api/chat/sessions/{chat_id}").json()["data"]
    assert restored["messages"][-1]["reply"] == "第一句。第二句！"


def test_free_chat_stream_coalesces_token_deltas_into_sentence_chunks(tmp_path):
    app = create_app(database_path_override=tmp_path / "stream-chat-token-chunks.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    response_payload = {
        "reply": "第一句。第二句！",
        "title": "连续回复",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }
    app.state.session_service.chat_model_client.generate_chat_stream = lambda **kwargs: ChatReplyEventStream(iter([
        {"type": "text", "delta": "第一"},
        {"type": "text", "delta": "句"},
        {"type": "text", "delta": "。第二"},
        {"type": "text", "delta": "句"},
        {"type": "text", "delta": "！"},
        {"type": "done", "response": response_payload},
    ]))

    response = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={"message": "请连续回答"},
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [event["delta"] for event in events if event["type"] == "text"] == ["第一句。", "第二句！"]
    assert events[-1]["type"] == "done"


def test_free_chat_stream_repairs_a_later_delta_without_reporting_a_connection_error(tmp_path):
    app = create_app(database_path_override=tmp_path / "stream-chat-repair.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    response_payload = {
        "reply": "我听见了。浮浪倾客没空陪你说这些废话。",
        "title": "随口一问",
        "emotion": "irritated",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }
    app.state.session_service.chat_model_client.generate_chat_stream = lambda **kwargs: ChatReplyEventStream(iter([
        {"type": "text", "delta": "我听见了。"},
        {"type": "text", "delta": "浮浪倾客没空陪你说这些废话。"},
        {"type": "done", "response": response_payload},
    ]))

    response = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={"message": "你在忙什么？"},
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert all(event["type"] != "error" for event in events)
    assert "".join(event["delta"] for event in events if event["type"] == "text") == "我听见了。我没空陪你说这些废话。"
    assert events[-1]["type"] == "done"
    assert events[-1]["response"]["reply"] == "我听见了。我没空陪你说这些废话。"
    restored = client.get(f"/api/chat/sessions/{chat_id}").json()["data"]
    assert restored["messages"][-1]["reply"] == "我听见了。我没空陪你说这些废话。"


def test_free_chat_stream_flattens_paragraph_breaks_before_emitting_and_persisting(tmp_path):
    app = create_app(database_path_override=tmp_path / "stream-chat-single-paragraph.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    response_payload = {
        "reply": "第一段。\n\n  第二段。",
        "title": "连续回复",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }
    app.state.session_service.chat_model_client.generate_chat_stream = lambda **kwargs: ChatReplyEventStream(iter([
        {"type": "text", "delta": "第一段。\n\n"},
        {"type": "text", "delta": "  第二段。"},
        {"type": "done", "response": response_payload},
    ]))

    response = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={"message": "请连续回答"},
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [event["delta"] for event in events if event["type"] == "text"] == ["第一段。", "第二段。"]
    assert events[-1]["response"]["reply"] == "第一段。第二段。"
    restored = client.get(f"/api/chat/sessions/{chat_id}").json()["data"]
    assert restored["messages"][-1]["reply"] == "第一段。第二段。"


def test_free_chat_stream_preserves_an_intentional_space_across_provider_deltas(tmp_path):
    app = create_app(database_path_override=tmp_path / "stream-chat-delta-space.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    response_payload = {
        "reply": "第一句。 第二句。",
        "title": "连续回复",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }
    app.state.session_service.chat_model_client.generate_chat_stream = lambda **kwargs: ChatReplyEventStream(iter([
        {"type": "text", "delta": "第一句。"},
        {"type": "text", "delta": " 第二句。"},
        {"type": "done", "response": response_payload},
    ]))

    response = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={"message": "请连续回答"},
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert all(event["type"] != "reset" for event in events)
    assert [event["delta"] for event in events if event["type"] == "text"] == ["第一句。", " 第二句。"]
    assert events[-1]["response"]["reply"] == "第一句。 第二句。"


@pytest.mark.parametrize("blank_reply", ["\n\n", "   ", "\u00a0", "\f", "\v"])
def test_free_chat_stream_replaces_replies_that_become_blank_after_layout_normalization(tmp_path, blank_reply):
    app = create_app(database_path_override=tmp_path / "stream-chat-blank-layout.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    response_payload = {
        "reply": blank_reply,
        "title": "空白回复",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }
    app.state.session_service.chat_model_client.generate_chat_stream = lambda **kwargs: ChatReplyEventStream(iter([
        {"type": "text", "delta": blank_reply},
        {"type": "done", "response": response_payload},
    ]))

    response = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={"message": "不要空白回答"},
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    text_deltas = [event["delta"] for event in events if event["type"] == "text"]
    assert text_deltas and all(delta.strip() for delta in text_deltas)
    assert events[-1]["response"]["reply"] in FALLBACK_REPLIES
    restored = client.get(f"/api/chat/sessions/{chat_id}").json()["data"]
    assert restored["messages"][-1]["reply"] in FALLBACK_REPLIES


def test_free_chat_read_flattens_paragraph_breaks_from_existing_sessions(tmp_path):
    app = create_app(database_path_override=tmp_path / "existing-chat-paragraphs.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.repository.save_chat_messages(
        UUID(chat_id),
        [{"message": "讲讲过去", "reply": "旧记录第一段。\n\n旧记录第二段。", "emotion": "calm"}],
        "旧时的对话",
    )

    restored = client.get(f"/api/chat/sessions/{chat_id}")

    assert restored.status_code == 200
    assert restored.json()["data"]["messages"][0]["reply"] == "旧记录第一段。旧记录第二段。"
    stored = app.state.session_service.repository.get_chat_details(UUID(chat_id))[1]
    assert stored[0]["reply"] == "旧记录第一段。\n\n旧记录第二段。"


def test_free_chat_title_repair_does_not_rewrite_existing_reply_layout(tmp_path):
    app = create_app(database_path_override=tmp_path / "existing-chat-title-repair.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    original_reply = "旧记录第一段。\n\n旧记录第二段。"
    app.state.session_service.repository.save_chat_messages(
        UUID(chat_id),
        [{"message": "讲讲过去", "reply": original_reply, "emotion": "calm"}],
        "新对话",
    )

    restored = client.get(f"/api/chat/sessions/{chat_id}")

    assert restored.status_code == 200
    assert restored.json()["data"]["messages"][0]["reply"] == "旧记录第一段。旧记录第二段。"
    stored = app.state.session_service.repository.get_chat_details(UUID(chat_id))
    assert stored[1][0]["reply"] == original_reply
    assert stored[3] != "新对话"


def test_free_chat_append_does_not_rewrite_existing_reply_layout(tmp_path):
    app = create_app(database_path_override=tmp_path / "existing-chat-append.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    original_reply = "旧记录第一段。\n\n旧记录第二段。"
    app.state.session_service.repository.save_chat_messages(
        UUID(chat_id),
        [{"message": "讲讲过去", "reply": original_reply, "emotion": "calm"}],
        "旧时的对话",
    )
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: {
        "reply": "现在没什么可补充的。",
        "title": "旧时的对话",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "还有呢？"})

    assert response.status_code == 200
    assert response.json()["data"]["messages"][0]["reply"] == "旧记录第一段。旧记录第二段。"
    stored = app.state.session_service.repository.get_chat_details(UUID(chat_id))[1]
    assert stored[0]["reply"] == original_reply
    assert stored[-1]["reply"] == "现在没什么可补充的。"


def test_free_chat_stream_does_not_persist_when_client_stops_before_done(tmp_path):
    app = create_app(database_path_override=tmp_path / "stream-chat-partial.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    response_payload = {
        "reply": "完整回复。",
        "title": "流式回复",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }
    cancelled = []
    app.state.session_service.chat_model_client.generate_chat_stream = lambda **kwargs: ChatReplyEventStream(iter([
        {"type": "text", "delta": "未完成。"},
        {"type": "done", "response": response_payload},
    ]), cancel=lambda: cancelled.append(True))

    events = app.state.session_service.stream_chat_message(UUID(chat_id), "你好", stream_id="partial-stream")
    assert next(events)["type"] == "text"
    events.close()
    assert app.state.session_service.repository.get_chat_details(UUID(chat_id))[1] == []
    assert cancelled == [True]




def test_story_creation_forces_offline_even_when_live_mode_is_requested(tmp_path, monkeypatch):
    monkeypatch.delenv("WANDERER_MODEL_API_KEY", raising=False)
    client = TestClient(create_app(database_path_override=tmp_path / "selected-live.db", demo_mode_override="live"))
    created = client.post("/api/sessions", json={"mode": "live"})

    assert created.status_code == 201
    assert created.json()["data"]["mode"] == "offline"
    assert created.json()["data"]["last_response"]["reply"]

    session_id = created.json()["data"]["session_id"]
    turn = client.post(f"/api/sessions/{session_id}/turn", json={"option_id": "listen"})
    assert turn.status_code == 200
    assert client.get(f"/api/sessions/{session_id}").json()["data"]["mode"] == "offline"


def test_legacy_live_story_is_migrated_to_offline_replay_on_next_turn(tmp_path, monkeypatch):
    app = create_app(database_path_override=tmp_path / "legacy-live-story.db", demo_mode_override="offline")
    client = TestClient(app)
    created = client.post("/api/sessions", json={"mode": "offline"})
    session_id = created.json()["data"]["session_id"]
    session_service = app.state.session_service
    state, last_response, _, replay_id, ending = session_service.get(UUID(session_id))
    session_service.repository.save(state, last_response, "live", replay_id, ending)
    offline_engine = session_service._engine_for_mode("offline")

    def require_offline(mode):
        assert mode == "offline"
        return offline_engine

    monkeypatch.setattr(session_service, "_engine_for_mode", require_offline)
    response = client.post(f"/api/sessions/{session_id}/turn", json={"option_id": "listen"})

    assert response.status_code == 200
    assert response.json()["data"]["response"]["reply"]
    assert client.get(f"/api/sessions/{session_id}").json()["data"]["mode"] == "offline"


def test_live_free_chat_includes_safe_provider_diagnostics_on_forbidden(tmp_path, monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://user:secret@provider.example/v1?token=query-secret")
    monkeypatch.setenv("WANDERER_MODEL_NAME", "story-model")
    monkeypatch.delenv("WANDERER_MODEL_ENDPOINT", raising=False)
    app = create_app(database_path_override=tmp_path / "chat-live-forbidden.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    provider_error = ModelProviderError("forbidden", status_code=403, user_message="服务商拒绝了请求")
    provider_error.provider_code = "ip_blocked"
    provider_error.provider_request_id = "req-safe-123"
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: (_ for _ in ()).throw(provider_error)

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你好"})

    assert response.status_code == 502
    details = response.json()["error"]["details"]
    assert details["provider_status"] == 403
    assert details["provider_code"] == "ip_blocked"
    assert details["provider_request_id"] == "req-safe-123"
    assert details["model"] == "story-model"
    assert details["endpoint"] == "https://provider.example/v1/chat/completions"
    assert "secret" not in response.text
    assert "query-secret" not in response.text


def test_live_free_chat_accepts_reply_only_provider_payload(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-live-reply-only.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: {"reply": "我听见了。"}

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你好"})

    assert response.status_code == 200
    data = response.json()["data"]["response"]
    assert data["reply"] == "我听见了。"
    assert data["emotion"] == "calm"
    assert data["state_delta"] == {}
    assert data["next_scene"] is None
    assert data["is_ending"] is False
    assert data["ending_id"] is None


def test_offline_free_chat_returns_structured_response_without_game_state(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "chat.db", demo_mode_override="offline"))

    created = client.post("/api/chat/sessions")
    assert created.status_code == 201
    chat_id = created.json()["data"]["chat_session_id"]
    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你在做什么？"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["response"]["reply"]
    assert data["response"]["emotion"]
    assert data["response"]["state_delta"] == {}
    assert data["response"]["next_scene"] is None
    assert data["response"]["is_ending"] is False
    assert data["game_state"] is None


def test_offline_free_chat_changes_reply_for_different_messages(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "chat-variety.db", demo_mode_override="offline"))
    created = client.post("/api/chat/sessions")
    chat_id = created.json()["data"]["chat_session_id"]

    first = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你在做什么？"})
    second = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "我想知道踏鞴砂的真相。"})

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["response"]["reply"] != second.json()["data"]["response"]["reply"]


def test_free_chat_generates_and_persists_a_thematic_title(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "chat-title.db", demo_mode_override="offline"))
    created = client.post("/api/chat/sessions", json={"player_name": "清岚"})
    chat_id = created.json()["data"]["chat_session_id"]

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "我想知道教令院的规矩。"})

    assert response.status_code == 200
    title = response.json()["data"]["response"]["title"]
    assert title == "关于教令院的求问"
    assert title != "我想知道教令院的规矩。"
    client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "说说风吧。"})
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["title"] == title


def test_free_chat_history_survives_read_and_does_not_create_game_session(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "chat-history.db", demo_mode_override="offline"))
    created = client.post("/api/chat/sessions")
    chat_id = created.json()["data"]["chat_session_id"]
    client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "别绕弯子。"})

    read = client.get(f"/api/chat/sessions/{chat_id}")

    assert read.status_code == 200
    assert len(read.json()["data"]["messages"]) == 1


def test_live_free_chat_maps_model_timeout(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-live.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: (_ for _ in ()).throw(
        ModelTimeoutError("timed out")
    )

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "回答我。"})

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "MODEL_TIMEOUT"


def test_live_free_chat_explains_rejected_credentials_without_exposing_provider_body(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-live-auth.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    provider_error = ModelProviderError("upstream rejected credentials")
    provider_error.status_code = 401
    provider_error.user_message = "模型服务拒绝了 API 密钥（HTTP 401）。请检查密钥是否有效、是否属于当前服务商，然后重启游戏。"
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: (_ for _ in ()).throw(provider_error)

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你好"})

    assert response.status_code == 502
    assert response.json()["error"]["message"] == "模型服务拒绝了 API 密钥（HTTP 401）。请检查密钥是否有效、是否属于当前服务商，然后重启游戏。"
    assert "upstream rejected credentials" not in response.text


def test_chat_session_can_be_deleted_from_history(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "chat-delete.db", demo_mode_override="offline"))
    created = client.post("/api/chat/sessions")
    chat_id = created.json()["data"]["chat_session_id"]

    deleted = client.delete(f"/api/chat/sessions/{chat_id}")

    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True
    assert client.get(f"/api/chat/sessions/{chat_id}").status_code == 404


def test_chat_session_persists_the_players_chosen_name(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "named-chat.db", demo_mode_override="offline"))

    created = client.post("/api/chat/sessions", json={"player_name": "清岚"})
    chat_id = created.json()["data"]["chat_session_id"]

    restored = client.get(f"/api/chat/sessions/{chat_id}")

    assert created.json()["data"]["player_name"] == "清岚"
    assert restored.json()["data"]["player_name"] == "清岚"

def test_free_chat_regenerate_replaces_the_last_reply_in_place(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-regenerate.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]

    replies = iter([
        {"reply": "第一次回应。", "title": "关于你的近况", "emotion": "calm", "state_delta": {}, "next_scene": None, "is_ending": False, "ending_id": None},
        {"reply": "重新想过之后的回应。", "title": "关于你的近况", "emotion": "guarded", "state_delta": {}, "next_scene": None, "is_ending": False, "ending_id": None},
    ])
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: next(replies)

    first = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你在想什么？"})
    assert first.status_code == 200
    assert first.json()["data"]["messages"][0]["reply"] == "第一次回应。"

    regenerated = client.post(f"/api/chat/sessions/{chat_id}/regenerate")

    assert regenerated.status_code == 200
    messages = regenerated.json()["data"]["messages"]
    assert len(messages) == 1
    assert messages[0]["reply"] == "重新想过之后的回应。"
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["messages"][0]["reply"] == "重新想过之后的回应。"


def test_free_chat_normalizes_third_person_self_reference_before_saving(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-pronouns.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live", "player_name": "清岚"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: {
        "reply": "杜林认定浮浪倾客是他的朋友。「浮浪倾客」会拦住他。",
        "title": "关于杜林的关系",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你和杜林是什么关系？"})

    assert response.status_code == 200
    expected = "杜林认定浮浪倾客是他的朋友。我会拦住他。"
    assert response.json()["data"]["response"]["reply"] == expected
    assert response.json()["data"]["messages"][0]["reply"] == expected
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["messages"][0]["reply"] == expected


def test_free_chat_pronoun_normalization_preserves_the_character_name_when_discussing_it(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-name-reference.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    reply = "你可以叫我「浮浪倾客」。浮浪倾客这个名字，不过是个称呼。"
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: {
        "reply": reply,
        "title": "关于称呼",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "我该怎么称呼你？"})

    assert response.status_code == 200
    assert response.json()["data"]["response"]["reply"] == reply


def test_free_chat_regenerate_without_history_is_rejected(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "chat-regen-empty.db", demo_mode_override="offline"))
    created = client.post("/api/chat/sessions")
    chat_id = created.json()["data"]["chat_session_id"]

    response = client.post(f"/api/chat/sessions/{chat_id}/regenerate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CHAT_NOTHING_TO_REGENERATE"

def test_free_chat_falls_back_after_three_unrepairable_replies(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-guard-fallback.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    calls = []

    def unrepairable(**kwargs):
        calls.append(kwargs)
        return {
            "reply": "他从不回头，也不会为谁停下。",
            "title": "关于他的传闻",
            "emotion": "calm",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        }

    app.state.session_service.chat_model_client.generate_chat = unrepairable

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你会回头吗？"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(calls) == 3
    assert data["response"]["reply"] in FALLBACK_REPLIES
    assert data["response"]["emotion"] in ("guarded", "reluctant")
    assert data["response"]["state_delta"] == {}
    assert data["messages"][-1]["reply"] == data["response"]["reply"]
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["messages"][-1]["reply"] in FALLBACK_REPLIES


@pytest.mark.parametrize("blank_reply", ["\n\n", "   ", "\u00a0", "\f", "\v"])
def test_free_chat_retries_then_falls_back_when_layout_normalization_removes_the_reply(tmp_path, blank_reply):
    app = create_app(database_path_override=tmp_path / "chat-blank-layout-fallback.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    calls = []

    def blank_response(**kwargs):
        calls.append(kwargs)
        return {
            "reply": blank_reply,
            "title": "空白回复",
            "emotion": "calm",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        }

    app.state.session_service.chat_model_client.generate_chat = blank_response

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "不要空白回答"})

    assert response.status_code == 200
    assert len(calls) == 3
    assert response.json()["data"]["response"]["reply"] in FALLBACK_REPLIES
    restored = client.get(f"/api/chat/sessions/{chat_id}").json()["data"]
    assert restored["messages"][-1]["reply"] in FALLBACK_REPLIES


def test_free_chat_retries_and_adopts_the_first_repairable_reply(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-guard-retry.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    replies = iter([
        {
            "reply": "他早已把过去丢在身后。",
            "title": "关于过去",
            "emotion": "calm",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        },
        {
            "reply": "过去的事我记着，但不打算讲给你听。",
            "title": "关于过去",
            "emotion": "guarded",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        },
    ])
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: next(replies)

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "讲讲你的过去。"})

    assert response.status_code == 200
    assert response.json()["data"]["response"]["reply"] == "过去的事我记着，但不打算讲给你听。"
    assert response.json()["data"]["messages"][-1]["reply"] == "过去的事我记着，但不打算讲给你听。"


def test_free_chat_retries_when_reply_has_mechanical_language(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-language-guard.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    replies = iter([
        {
            "reply": "记住江水的颜色，记住风吹乱头发时的痒，记住逃课后世界仍在转。",
            "title": "关于过去",
            "emotion": "quiet",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        },
        {
            "reply": "别站在门口。进来，把你查到的东西给我。",
            "title": "关于过去",
            "emotion": "guarded",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        },
    ])
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: next(replies)

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "我查到了一些东西。"})

    assert response.status_code == 200
    assert response.json()["data"]["response"]["reply"] == "别站在门口。进来，把你查到的东西给我。"


def test_free_chat_sanitizes_dirty_history_before_sending_and_on_read(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-dirty-history.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    captured = {}

    def echo_history(**kwargs):
        captured["history"] = kwargs["request"].history
        return {
            "reply": "风没停，我也没走。",
            "title": "关于风",
            "emotion": "quiet",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        }

    app.state.session_service.chat_model_client.generate_chat = echo_history

    dirty_messages = [
        {"message": "你会等风停吗？", "reply": "浮浪倾客不会说第二遍。", "emotion": "guarded"},
        {"message": "那你能依靠谁？", "reply": "流浪者只能靠自己。", "emotion": "calm"},
    ]
    app.state.session_service.repository.save_chat_messages(UUID(chat_id), dirty_messages, "旧时的对话")

    sent = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "那现在呢？"})

    assert sent.status_code == 200
    assert captured["history"] == (
        ("你会等风停吗？", "我不会说第二遍。"),
        ("那你能依靠谁？", "我只能靠自己。"),
    )
    read = client.get(f"/api/chat/sessions/{chat_id}")
    assert read.status_code == 200
    first_read = read.json()["data"]
    messages = first_read["messages"]
    assert messages[0]["message"] == "你会等风停吗？"
    assert messages[0]["reply"] == "我不会说第二遍。"
    assert messages[0]["emotion"] == "guarded"
    assert messages[1]["reply"] == "我只能靠自己。"
    assert first_read["title"] == "旧时的对话"
    for _ in range(2):
        again = client.get(f"/api/chat/sessions/{chat_id}")
        assert again.json()["data"] == first_read


def test_free_chat_end_to_end_repairs_wrong_self_reference(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-e2e-guard.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: {
        "reply": "「流浪者」没空陪你说这些废话。想问什么就直说。",
        "title": "关于你的来意",
        "emotion": "irritated",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "陪我说说话。"})

    assert response.status_code == 200
    expected = "我没空陪你说这些废话。想问什么就直说。"
    assert response.json()["data"]["response"]["reply"] == expected
    assert response.json()["data"]["messages"][-1]["reply"] == expected
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["messages"][-1]["reply"] == expected


def test_free_chat_keeps_historical_alias_as_a_name_not_first_person(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-historical-alias.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    historical_reply = "「散兵」是我过去在愚人众使用的称呼。"
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: {
        "reply": historical_reply,
        "title": "关于过去身份",
        "emotion": "guarded",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "关于你和散兵"})

    assert response.status_code == 200
    assert response.json()["data"]["response"]["reply"] == historical_reply
    assert "我是我" not in response.text
    assert response.json()["data"]["messages"][-1]["reply"] == historical_reply


def test_free_chat_regenerate_also_passes_through_pronoun_guard(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-regen-guard.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: {
        "reply": "知道了。说重点。",
        "title": "关于你的问题",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }
    first = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "听我说件事。"})
    assert first.status_code == 200

    app.state.session_service.chat_model_client.generate_chat = lambda **kwargs: {
        "reply": "散兵说过的话不会收回。",
        "title": "关于你的问题",
        "emotion": "guarded",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }

    regenerated = client.post(f"/api/chat/sessions/{chat_id}/regenerate")

    assert regenerated.status_code == 200
    messages = regenerated.json()["data"]["messages"]
    assert len(messages) == 1
    assert messages[0]["reply"] == "我说过的话不会收回。"

def _intro_reply_mock(reply_text):
    def generate(**kwargs):
        return {
            "reply": reply_text,
            "title": "关于自我介绍",
            "emotion": "calm",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        }

    return generate


def test_intro_scene_shot1_end_to_end_repairs_standalone_element_sentence(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-intro-shot1.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.chat_model_client.generate_chat = _intro_reply_mock(
        "目前在须弥教令院因论派学习，也与纳西妲合作。风元素。别把我归进任何国家或组织。"
    )

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "介绍一下你自己"})

    assert response.status_code == 200
    expected = "目前在须弥教令院因论派学习，也与纳西妲合作。别把我归进任何国家或组织。"
    data = response.json()["data"]
    assert data["response"]["reply"] == expected
    assert all(term not in data["response"]["reply"] for term in ELEMENT_SELF_REFERENCE_TERMS)
    assert data["messages"][-1]["reply"] == expected
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["messages"][-1]["reply"] == expected


def test_intro_scene_shot2_end_to_end_removes_pathological_and_element_clauses(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-intro-shot2.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.chat_model_client.generate_chat = _intro_reply_mock(
        "我叫阿帽？不，没必要。记住，我是风元素使用者，现停留在须弥，替纳西妲处理一些麻烦。"
    )

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "介绍一下你自己"})

    assert response.status_code == 200
    expected = "记住，现停留在须弥，替纳西妲处理一些麻烦。"
    data = response.json()["data"]
    assert data["response"]["reply"] == expected
    assert all(term not in data["response"]["reply"] for term in ELEMENT_SELF_REFERENCE_TERMS)
    assert "不，没必要" not in data["response"]["reply"]
    assert data["messages"][-1]["reply"] == expected
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["messages"][-1]["reply"] == expected


def test_intro_scene_shot3_end_to_end_repairs_element_clause_prefix(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-intro-shot3.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.chat_model_client.generate_chat = _intro_reply_mock(
        "我如今留在须弥，替纳西妲处理一些麻烦。风元素，擅长战斗。别把我归进任何组织。"
    )

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "介绍一下你自己"})

    assert response.status_code == 200
    expected = "我如今留在须弥，替纳西妲处理一些麻烦。擅长战斗。别把我归进任何组织。"
    data = response.json()["data"]
    assert data["response"]["reply"] == expected
    assert all(term not in data["response"]["reply"] for term in ELEMENT_SELF_REFERENCE_TERMS)
    assert data["messages"][-1]["reply"] == expected
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["messages"][-1]["reply"] == expected


def test_intro_scene_falls_back_to_intro_pool_after_unrepairable_replies(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-intro-fallback.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    calls = []

    def unrepairable(**kwargs):
        calls.append(kwargs)
        return {
            "reply": "我是风元素使用者。",
            "title": "关于自我介绍",
            "emotion": "calm",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        }

    app.state.session_service.chat_model_client.generate_chat = unrepairable

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "介绍一下你自己"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(calls) == 3
    assert data["response"]["reply"] in INTRO_FALLBACK_REPLIES
    assert data["response"]["reply"] not in FALLBACK_REPLIES
    assert data["response"]["emotion"] in ("guarded", "reluctant")
    assert data["response"]["state_delta"] == {}
    assert data["messages"][-1]["reply"] == data["response"]["reply"]
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["messages"][-1]["reply"] in INTRO_FALLBACK_REPLIES


def test_element_question_keeps_element_answer_live(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-element-live.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    app.state.session_service.chat_model_client.generate_chat = _intro_reply_mock("我是风元素使用者。")

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你是什么元素"})

    assert response.status_code == 200
    assert response.json()["data"]["response"]["reply"] == "我是风元素使用者。"
    assert response.json()["data"]["messages"][-1]["reply"] == "我是风元素使用者。"
    restored = client.get(f"/api/chat/sessions/{chat_id}")
    assert restored.json()["data"]["messages"][-1]["reply"] == "我是风元素使用者。"


def test_intro_history_scene_sanitization_and_zero_false_positive(tmp_path):
    app = create_app(database_path_override=tmp_path / "chat-intro-history.db", demo_mode_override="live")
    client = TestClient(app)
    created = client.post("/api/chat/sessions", json={"mode": "live"})
    chat_id = created.json()["data"]["chat_session_id"]
    captured = {}

    def echo_history(**kwargs):
        captured["history"] = kwargs["request"].history
        return {
            "reply": "问吧。",
            "title": "关于你的问题",
            "emotion": "calm",
            "state_delta": {},
            "next_scene": None,
            "is_ending": False,
            "ending_id": None,
        }

    app.state.session_service.chat_model_client.generate_chat = echo_history

    dirty_messages = [
        {"message": "介绍一下你自己", "reply": "目前在须弥教令院因论派学习，也与纳西妲合作。风元素。别把我归进任何国家或组织。", "emotion": "calm"},
        {"message": "介绍一下你自己", "reply": "风元素。", "emotion": "guarded"},
        {"message": "介绍一下你自己", "reply": "我叫阿帽？不，没必要。", "emotion": "calm"},
        {"message": "你是什么元素", "reply": "我是风元素使用者。", "emotion": "calm"},
    ]
    app.state.session_service.repository.save_chat_messages(UUID(chat_id), dirty_messages, "旧时的对话")

    sent = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "那现在呢？"})

    assert sent.status_code == 200
    assert sent.json()["data"]["response"]["reply"] == "问吧。"
    assert captured["history"] == (
        ("介绍一下你自己", "目前在须弥教令院因论派学习，也与纳西妲合作。别把我归进任何国家或组织。"),
        ("你是什么元素", "我是风元素使用者。"),
    )
    read = client.get(f"/api/chat/sessions/{chat_id}")
    assert read.status_code == 200
    first_read = read.json()["data"]
    messages = first_read["messages"]
    assert first_read["title"] == "旧时的对话"
    assert messages[0]["reply"] == "目前在须弥教令院因论派学习，也与纳西妲合作。别把我归进任何国家或组织。"
    assert messages[1]["reply"] == "风元素。"
    assert messages[2]["reply"] == "我叫阿帽？不，没必要。"
    assert messages[3]["reply"] == "我是风元素使用者。"
    for _ in range(2):
        again = client.get(f"/api/chat/sessions/{chat_id}")
        assert again.json()["data"] == first_read
