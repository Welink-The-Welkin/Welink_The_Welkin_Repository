from fastapi.testclient import TestClient
import pytest

from backend.app.contracts.ai import ChatResponse
from backend.app.contracts.model import ModelConfig
from backend.app.core.errors import ModelProviderError
from backend.app.main import create_app


def _app(tmp_path):
    return create_app(database_path_override=tmp_path / "model-api.db", demo_mode_override="offline")


def _model_payload(key="do-not-echo"):
    return {
        "endpoint": "https://provider.example/v1",
        "model": "demo-model",
        "api_key": key,
    }


def test_model_provider_metadata_has_no_secret_fields(tmp_path):
    response = TestClient(_app(tmp_path)).get("/api/model/providers")

    assert response.status_code == 200
    assert response.json()["data"]
    assert all(set(item) == {"id", "label", "endpoint", "default_model"} for item in response.json()["data"])
    assert "api_key" not in response.text.lower()


def test_model_test_requires_https_and_never_echoes_key(tmp_path):
    response = TestClient(_app(tmp_path)).post(
        "/api/model/test",
        json={
            "endpoint": "http://127.0.0.1:9/v1",
            "model": "demo",
            "api_key": "do-not-echo",
        },
    )

    assert response.status_code == 400
    assert "do-not-echo" not in response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert response.json()["request_id"]
    assert response.headers["cache-control"] == "no-store"


def test_model_test_uses_one_non_stream_request_and_returns_safe_metadata(tmp_path):
    app = _app(tmp_path)
    captured = {"configs": [], "requests": []}

    class StubClient:
        def __init__(self, config):
            captured["configs"].append(config)

        def test_connection(self):
            captured["requests"].append("connection-probe")

    app.state.model_test_client_factory = StubClient
    response = TestClient(app).post("/api/model/test", json=_model_payload())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"] == {
        "ok": True,
        "model": "demo-model",
        "endpoint": "https://provider.example/v1/chat/completions",
    }
    assert len(captured["configs"]) == 1
    assert isinstance(captured["configs"][0], ModelConfig)
    assert len(captured["requests"]) == 1
    assert captured["requests"] == ["connection-probe"]
    assert "do-not-echo" not in response.text


def test_model_test_does_not_require_the_free_chat_json_contract(tmp_path):
    app = _app(tmp_path)
    captured = []

    class StubClient:
        def __init__(self, config):
            self.config = config

        def test_connection(self):
            captured.append(self.config.model)

    app.state.model_test_client_factory = StubClient
    response = TestClient(app).post("/api/model/test", json=_model_payload())

    assert response.status_code == 200
    assert captured == ["demo-model"]


def test_model_test_provider_failure_uses_safe_error_envelope(tmp_path):
    app = _app(tmp_path)

    class FailingClient:
        def __init__(self, config):
            self.config = config

        def test_connection(self):
            raise ModelProviderError(
                f"provider failure included {self.config.api_key}",
                status_code=401,
                user_message="provider rejected request",
            )

    app.state.model_test_client_factory = FailingClient
    response = TestClient(app).post("/api/model/test", json=_model_payload())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_PROVIDER_ERROR"
    assert response.json()["error"]["message"] == "provider rejected request"
    assert response.json()["request_id"]
    assert response.headers["cache-control"] == "no-store"
    assert "do-not-echo" not in response.text
    assert "provider failure" not in response.text


@pytest.mark.parametrize("status_code", [400, 404])
def test_model_test_configuration_status_uses_editable_settings_error(tmp_path, status_code):
    app = _app(tmp_path)

    class FailingClient:
        def __init__(self, config):
            self.config = config

        def test_connection(self):
            raise ModelProviderError(
                f"provider body included {self.config.api_key}",
                status_code=status_code,
                user_message="provider body must not be exposed",
            )

    app.state.model_test_client_factory = FailingClient
    response = TestClient(app).post("/api/model/test", json=_model_payload())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_CONFIGURATION_ERROR"
    assert response.json()["error"]["details"] is None
    assert "do-not-echo" not in response.text
    assert "provider body" not in response.text


def test_model_test_rate_limit_exposes_safe_retry_after(tmp_path):
    app = _app(tmp_path)

    class FailingClient:
        def __init__(self, config):
            self.config = config

        def test_connection(self):
            raise ModelProviderError(
                "provider body included do-not-echo",
                status_code=429,
                retry_after="19",
                user_message="safe rate limit",
            )

    app.state.model_test_client_factory = FailingClient
    response = TestClient(app).post("/api/model/test", json=_model_payload())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_PROVIDER_ERROR"
    assert response.json()["error"]["details"] == {"provider_status": 429, "retry_after": 19.0}
    assert "do-not-echo" not in response.text
    assert "provider body" not in response.text


def test_model_test_unexpected_failure_uses_safe_error_envelope(tmp_path):
    app = _app(tmp_path)

    class FailingClient:
        def __init__(self, config):
            self.config = config

        def test_connection(self):
            raise RuntimeError(f"internal failure included {self.config.api_key}")

    app.state.model_test_client_factory = FailingClient
    response = TestClient(app).post("/api/model/test", json=_model_payload())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_PROVIDER_ERROR"
    assert response.json()["request_id"]
    assert response.headers["cache-control"] == "no-store"
    assert "do-not-echo" not in response.text
    assert "internal failure" not in response.text


def test_sync_free_chat_passes_model_config_to_service_without_persisting_key(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    chat_id = client.post("/api/chat/sessions", json={"mode": "offline"}).json()["data"]["chat_session_id"]
    captured = {}

    class StubClient:
        def generate_chat(self, *, request):
            return {"reply": "收到。"}

    app.state.session_service._chat_client_for_config = lambda config: StubClient()
    original_chat_message = app.state.session_service.chat_message

    def chat_message(session_id, message, *, model_config):
        captured.update(session_id=session_id, message=message, model_config=model_config)
        return original_chat_message(session_id, message, model_config=model_config)

    app.state.session_service.chat_message = chat_message
    response = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={"message": "你好", "model": _model_payload()},
    )

    assert response.status_code == 200
    assert captured["message"] == "你好"
    assert isinstance(captured["model_config"], ModelConfig)
    assert captured["model_config"].api_key == "do-not-echo"
    assert "do-not-echo" not in response.text
    assert "do-not-echo" not in str(app.state.session_service.repository.get_chat_details(captured["session_id"]))


def test_stream_free_chat_passes_same_model_config_to_service(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    chat_id = client.post("/api/chat/sessions", json={"mode": "live"}).json()["data"]["chat_session_id"]
    captured = {}

    def stream_chat_message(session_id, message, *, stream_id=None, model_config):
        captured.update(session_id=session_id, message=message, stream_id=stream_id, model_config=model_config)
        return iter([{"type": "done", "response": {"reply": "收到。"}}])

    app.state.session_service.stream_chat_message = stream_chat_message
    response = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={"message": "你好", "model": _model_payload()},
        headers={"accept": "text/event-stream", "x-chat-stream-id": "test-stream"},
    )

    assert response.status_code == 200
    assert captured["stream_id"] == "test-stream"
    assert isinstance(captured["model_config"], ModelConfig)
    assert captured["model_config"].api_key == "do-not-echo"
    assert "do-not-echo" not in response.text


def test_regenerate_chat_requires_and_passes_model_config(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    chat_id = client.post("/api/chat/sessions", json={"mode": "live"}).json()["data"]["chat_session_id"]
    captured = {}

    def regenerate_chat(session_id, *, model_config):
        captured.update(session_id=session_id, model_config=model_config)
        return ChatResponse(reply="再答一次。", emotion="calm"), []

    app.state.session_service.regenerate_chat = regenerate_chat
    response = client.post(
        f"/api/chat/sessions/{chat_id}/regenerate",
        json={"model": _model_payload()},
    )

    assert response.status_code == 200
    assert isinstance(captured["model_config"], ModelConfig)
    assert captured["model_config"].api_key == "do-not-echo"
    assert "do-not-echo" not in response.text


def test_free_chat_rejects_missing_model_with_explicit_configuration_error(tmp_path):
    client = TestClient(_app(tmp_path))
    chat_id = client.post("/api/chat/sessions", json={"mode": "live"}).json()["data"]["chat_session_id"]

    response = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"message": "你好"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
    assert response.json()["request_id"]
