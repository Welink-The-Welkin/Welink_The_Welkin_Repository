# 本文件由 codex 辅助生成（外围模块）
from fastapi.testclient import TestClient

from backend.app.core.errors import ModelProviderError
from backend.app.errors import AppError
from backend.app.main import create_app


def test_health_endpoint_returns_service_status(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "api.db", demo_mode_override="offline"))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"
    assert response.json()["data"]["version"] == "0.2.0"


def test_offline_session_can_play_a_fixed_replay(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "api.db", demo_mode_override="offline"))

    created = client.post("/api/sessions")
    assert created.status_code == 201
    session_id = created.json()["data"]["session_id"]

    turn = client.post(
        f"/api/sessions/{session_id}/turn",
        json={"option_id": "listen"},
    )

    assert turn.status_code == 200
    assert turn.json()["data"]["response"]["reply"]
    assert turn.json()["data"]["state"]["turn_count"] == 1


def test_story_session_keeps_the_players_chosen_name(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "named-story.db", demo_mode_override="offline"))

    created = client.post("/api/sessions", json={"player_name": "清岚"})
    assert created.status_code == 201
    session_id = created.json()["data"]["session_id"]
    assert created.json()["data"]["state"]["player_name"] == "清岚"

    turn = client.post(f"/api/sessions/{session_id}/turn", json={"option_id": "listen"})

    assert turn.status_code == 200
    assert turn.json()["data"]["state"]["player_name"] == "清岚"


def test_story_session_rejects_blank_player_name(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "blank-name.db", demo_mode_override="offline"))

    response = client.post("/api/sessions", json={"player_name": "   "})

    assert response.status_code == 422
    assert any(error["loc"][-1] == "player_name" and error["type"] == "value_error" for error in response.json()["detail"])


def test_live_mode_creates_a_real_core_session(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "api.db", demo_mode_override="live"))

    created = client.post("/api/sessions")

    assert created.status_code == 201
    assert created.json()["data"]["mode"] == "offline"
    assert created.json()["data"]["last_response"]["reply"]
    assert created.json()["data"]["state"]["turn_count"] == 0


def test_two_offline_replay_ids_reach_distinct_recorded_endings(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "api.db", demo_mode_override="offline"))
    endings = []

    for replay_id in ("demo_guarded_path", "demo_direct_path"):
        created = client.post("/api/sessions", json={"replay_id": replay_id})
        assert created.status_code == 201
        session_id = created.json()["data"]["session_id"]
        options = (
            ["listen", "inspect_records", "follow_wind", "return_evidence", "tell_truth", "stay", "protect_others", "accept_burden"]
            if replay_id == "demo_guarded_path"
            else ["ask_truth", "confront_handler", "protect_witness", "accept_risk", "hide_truth", "leave", "protect_self", "accept_burden"]
        )
        for option_id in options:
            turn = client.post(f"/api/sessions/{session_id}/turn", json={"option_id": option_id})
            assert turn.status_code == 200
        endings.append(turn.json()["data"]["state"]["ending_id"])

    assert endings == ["evidence_keeper", "burden_bearer"]


def test_offline_story_choice_changes_reply_and_final_ending(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "branching.db", demo_mode_override="offline"))

    guarded = client.post("/api/sessions", json={"replay_id": "demo_guarded_path"}).json()["data"]["session_id"]
    direct = client.post("/api/sessions", json={"replay_id": "demo_guarded_path"}).json()["data"]["session_id"]

    guarded_first = client.post(f"/api/sessions/{guarded}/turn", json={"option_id": "listen"})
    direct_first = client.post(f"/api/sessions/{direct}/turn", json={"option_id": "ask_truth"})
    assert guarded_first.json()["data"]["response"]["reply"] != direct_first.json()["data"]["response"]["reply"]

    for option_id in ("inspect_records", "follow_wind", "return_evidence", "tell_truth", "stay", "protect_others", "accept_burden"):
        guarded_result = client.post(f"/api/sessions/{guarded}/turn", json={"option_id": option_id})
    for option_id in ("confront_handler", "protect_witness", "accept_risk", "hide_truth", "leave", "protect_self", "walk_away"):
        direct_result = client.post(f"/api/sessions/{direct}/turn", json={"option_id": option_id})

    assert guarded_result.json()["data"]["ending"]["ending_id"] != direct_result.json()["data"]["ending"]["ending_id"]


def test_finished_session_exposes_ending_title_and_summary(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "api.db", demo_mode_override="offline"))

    created = client.post("/api/sessions", json={"replay_id": "demo_guarded_path"})
    session_id = created.json()["data"]["session_id"]
    for option_id in ("listen", "inspect_records", "follow_wind", "return_evidence", "tell_truth", "stay", "protect_others", "accept_burden"):
        response = client.post(f"/api/sessions/{session_id}/turn", json={"option_id": option_id})
        assert response.status_code == 200

    finished = client.get(f"/api/sessions/{session_id}")

    assert finished.json()["data"]["ending"] == {
        "ending_id": "evidence_keeper",
        "title": "见证者",
        "summary": "你选择记住全部真相，与被改写过的记忆对峙，让事实本身替你说话。",
    }


def test_model_timeout_error_uses_public_error_envelope(tmp_path):
    app = create_app(database_path_override=tmp_path / "api.db", demo_mode_override="offline")
    app.state.session_service.create = lambda *args, **kwargs: (_ for _ in ()).throw(
        AppError("MODEL_TIMEOUT", "模型服务响应超时", 504)
    )

    response = TestClient(app).post("/api/sessions")

    assert response.status_code == 504
    assert response.json()["error"] == {
        "code": "MODEL_TIMEOUT",
        "message": "模型服务响应超时",
        "details": None,
    }
    assert response.json()["request_id"]


def test_model_provider_error_uses_public_error_envelope(tmp_path):
    app = create_app(database_path_override=tmp_path / "api.db", demo_mode_override="offline")
    app.state.session_service.create = lambda *args, **kwargs: (_ for _ in ()).throw(
        AppError("MODEL_PROVIDER_ERROR", "模型服务暂时不可用", 502)
    )

    response = TestClient(app).post("/api/sessions")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_PROVIDER_ERROR"


def test_free_chat_without_model_config_returns_explicit_configuration_error(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "chat-no-model-config.db", demo_mode_override="offline"))
    chat_id = client.post("/api/chat/sessions", json={"mode": "offline"}).json()["data"]["chat_session_id"]

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "请回答"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
    assert "api_key" not in response.text.lower()
    assert client.get(f"/api/chat/sessions/{chat_id}").json()["data"]["messages"] == []


def test_free_chat_regenerate_without_model_config_returns_explicit_configuration_error(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "chat-regen-no-model-config.db", demo_mode_override="offline"))
    chat_id = client.post("/api/chat/sessions", json={"mode": "offline"}).json()["data"]["chat_session_id"]

    response = client.post(f"/api/chat/sessions/{chat_id}/regenerate", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
    assert "api_key" not in response.text.lower()


def test_live_chat_provider_error_never_echoes_submitted_key_or_persists_fixture_reply(tmp_path, monkeypatch):
    app = create_app(database_path_override=tmp_path / "chat-provider-key.db", demo_mode_override="offline")
    client = TestClient(app)
    chat_id = client.post("/api/chat/sessions", json={"mode": "offline"}).json()["data"]["chat_session_id"]
    submitted_key = "must-not-appear-in-error-body"

    class FailingClient:
        def __init__(self, config):
            self.config = config
            self.model_name = config.model
            self.diagnostic_endpoint = config.diagnostic_endpoint

        def generate_chat(self, *, request):
            raise ModelProviderError(
                f"private provider response: {submitted_key}",
                status_code=403,
                user_message=f"provider rejected {submitted_key}",
                provider_code=submitted_key,
                provider_request_id=submitted_key,
            )

    monkeypatch.setattr("backend.app.services.session_service.LiveModelClient", FailingClient)
    response = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={
            "message": "请回答",
            "model": {
                "endpoint": "https://provider.example/v1",
                "model": "request-model",
                "api_key": submitted_key,
            },
        },
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_PROVIDER_ERROR"
    assert submitted_key not in response.text
    assert client.get(f"/api/chat/sessions/{chat_id}").json()["data"]["messages"] == []


def test_story_turn_stays_deterministic_and_does_not_construct_chat_model(tmp_path, monkeypatch):
    app = create_app(database_path_override=tmp_path / "story-without-model-config.db", demo_mode_override="offline")
    client = TestClient(app)

    def unexpected_live_client(*_args, **_kwargs):
        raise AssertionError("story turn must not construct a free-chat model client")

    monkeypatch.setattr("backend.app.services.session_service.LiveModelClient", unexpected_live_client)
    session_id = client.post("/api/sessions", json={"mode": "live"}).json()["data"]["session_id"]

    first = client.post(f"/api/sessions/{session_id}/turn", json={"option_id": "listen"})

    assert first.status_code == 200
    assert first.json()["data"]["state"]["turn_count"] == 1
    assert first.json()["data"]["response"]["reply"]


def _play_story(client, options):
    created = client.post("/api/sessions", json={"replay_id": "demo_guarded_path"})
    assert created.status_code == 201
    session_id = created.json()["data"]["session_id"]
    states = []
    for option_id in options:
        turn = client.post(f"/api/sessions/{session_id}/turn", json={"option_id": option_id})
        assert turn.status_code == 200, turn.text
        states.append(turn.json()["data"])
    return states


def test_offline_story_is_long_stateful_and_has_four_endings(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "long-story.db", demo_mode_override="offline"))
    paths = [
        ["listen", "inspect_records", "follow_wind", "return_evidence", "tell_truth", "stay", "protect_others", "accept_burden"],
        ["listen", "question_witness", "protect_witness", "accept_risk", "tell_truth", "stay", "protect_others", "accept_burden"],
        ["ask_truth", "inspect_records", "follow_wind", "return_evidence", "hide_truth", "leave", "protect_self", "walk_away"],
        ["ask_truth", "confront_handler", "protect_witness", "accept_risk", "hide_truth", "leave", "protect_self", "walk_away"],
    ]

    endings = []
    for options in paths:
        states = _play_story(client, options)
        final = states[-1]
        assert len(states) == 8
        assert final["state"]["is_finished"] is True
        assert final["state"]["turn_count"] == 8
        assert final["ending"]["ending_id"]
        assert len({(item["state"]["trust"], item["state"]["compassion"], item["state"]["responsibility"]) for item in states}) >= 4
        endings.append(final["ending"]["ending_id"])

    assert len(set(endings)) == 4


def test_story_history_keeps_choice_text_instead_of_internal_option_id(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "history-label.db", demo_mode_override="offline"))
    created = client.post("/api/sessions")
    session_id = created.json()["data"]["session_id"]

    response = client.post(f"/api/sessions/{session_id}/turn", json={"option_id": "listen"})

    assert response.status_code == 200
    history_item = response.json()["data"]["state"]["history"][0]
    assert history_item["player_input"] == "先听听他的判断"
    assert "listen" not in history_item["player_input"]

def test_story_turn_rejects_player_authored_free_text(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "no-free-text.db", demo_mode_override="offline"))
    session_id = client.post("/api/sessions").json()["data"]["session_id"]

    response = client.post(f"/api/sessions/{session_id}/turn", json={"player_message": "让我自己说一句"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
