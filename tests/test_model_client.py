# 本文件由 codex 辅助生成（外围模块）
import json
import io
import urllib.error
from uuid import uuid4

import pytest

from backend.app.contracts.game import initial_state
from backend.app.core.character_profile import DEFAULT_CHARACTER_PROFILE
from backend.app.core.model_client import ChatModelRequest, LiveModelClient, ModelRequest
from backend.app.core.errors import ModelProviderError


def test_live_client_defaults_to_deepseek_flash_and_normalizes_endpoint(monkeypatch):
    monkeypatch.delenv("WANDERER_MODEL_NAME", raising=False)
    monkeypatch.delenv("WANDERER_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("WANDERER_MODEL_ENDPOINT", raising=False)

    client = LiveModelClient()

    assert client.model_name == "deepseek-v4.1-flash"
    assert client.base_url == "https://api.deepseek.com"
    assert client.endpoint == "https://api.deepseek.com/chat/completions"


def test_live_client_accepts_provider_endpoint_with_chat_path(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test/v1/chat/completions")
    monkeypatch.setenv("WANDERER_MODEL_NAME", "another-model")
    monkeypatch.delenv("WANDERER_MODEL_ENDPOINT", raising=False)

    client = LiveModelClient()

    assert client.model_name == "another-model"
    assert client.endpoint == "https://example.test/v1/chat/completions"


def test_live_client_accepts_an_exact_endpoint_override(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_ENDPOINT", "https://example.test/v1/chat/completions")
    monkeypatch.setenv("WANDERER_MODEL_NAME", "another-model")

    client = LiveModelClient()

    assert client.endpoint == "https://example.test/v1/chat/completions"
    assert client.diagnostic_endpoint == "https://example.test/v1/chat/completions"


def test_live_client_normalizes_a_configured_v1_base_to_chat_completions(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_ENDPOINT", "http://localhost:1235/v1")
    monkeypatch.setenv("WANDERER_MODEL_NAME", "qwen/qwen3.5-9b")

    client = LiveModelClient()

    assert client.endpoint == "http://localhost:1235/v1/chat/completions"
    assert client.diagnostic_endpoint == "http://localhost:1235/v1/chat/completions"


def test_live_client_uses_text_response_format_for_openai_compatible_local_servers(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_NAME", "qwen/qwen3.5-9b")
    client = LiveModelClient()

    payload = client._payload(user="你好")

    assert payload["response_format"] == {"type": "text"}


def test_reply_stream_chunker_prefers_sentence_boundaries_and_flushes_long_text():
    from backend.app.core.model_client import chunk_reply_text

    assert chunk_reply_text("第一句。第二句！") == ["第一句。", "第二句！"]
    assert chunk_reply_text("第一段。\n\n第二段。") == ["第一段。", "第二段。"]
    assert chunk_reply_text("甲。" + " " * 60 + "乙。") == ["甲。", " 乙。"]
    long_text = "甲" * 60
    chunks = chunk_reply_text(long_text)
    assert "".join(chunks) == long_text
    assert all(1 <= len(chunk) <= 56 for chunk in chunks)


def test_chat_reply_layout_normalizer_handles_split_line_endings_and_preserves_word_spaces():
    from backend.app.core.model_client import ChatReplyLayoutNormalizer

    normalizer = ChatReplyLayoutNormalizer()
    assert normalizer.feed("第一段。\r") == "第一段。"
    assert normalizer.feed("\n  第二段。\u2028") == "第二段。"
    assert normalizer.feed("\u2029　第三段。") == "第三段。"

    words = ChatReplyLayoutNormalizer()
    assert words.feed("keep ") == "keep"
    assert words.feed("word spaces.") == " word spaces."

    latin_line_wrap = ChatReplyLayoutNormalizer()
    assert latin_line_wrap.feed("Use HTTP\r\n") == "Use HTTP"
    assert latin_line_wrap.feed("status 200.") == " status 200."

    whitespace = ChatReplyLayoutNormalizer()
    assert whitespace.feed("\u00a0\f\v") == ""


def test_live_client_stream_request_sends_stream_true_and_extracts_reply_deltas(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()
    captured = {}

    class Response:
        headers = {"content-type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            events = [
                {"choices": [{"delta": {"content": '{"reply":"第一句。'}}]},
                {"choices": [{"delta": {"content": '第二句！","emotion":"calm"'}}]},
                {"choices": [{"delta": {"content": ',"state_delta":{},"next_scene":null,"is_ending":false,"ending_id":null}'}}]},
            ]
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
            yield b"data: [DONE]\n\n"

    def capture(request, **kwargs):
        captured["request"] = request
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", capture)
    events = list(client.generate_chat_stream(
        request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message="你好")
    ))

    assert captured["payload"]["stream"] is True
    assert [event["type"] for event in events] == ["text", "text", "done"]
    assert "".join(event["delta"] for event in events if event["type"] == "text") == "第一句。第二句！"
    assert events[-1]["response"]["reply"] == "第一句。第二句！"


def test_live_client_stream_ignores_nested_reply_keys_and_uses_only_the_top_level_reply(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()
    content = json.dumps({
        "meta": {"reply": "错误草稿。"},
        "reply": "正确回复。",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }, ensure_ascii=False)

    class Response:
        headers = {"content-type": "text/event-stream"}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __iter__(self):
            yield f"data: {json.dumps({'choices': [{'delta': {'content': content}}]}, ensure_ascii=False)}\n\n".encode()
            yield b"data: [DONE]\n\n"

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())

    events = list(client.generate_chat_stream(
        request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message="你好")
    ))

    assert "".join(event["delta"] for event in events if event["type"] == "text") == "正确回复。"
    assert events[-1]["response"]["reply"] == "正确回复。"


def test_live_client_stream_rejects_duplicate_top_level_reply_keys(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    client = LiveModelClient()
    content = '{"reply":"第一份。","reply":"第二份。","emotion":"calm","state_delta":{},"next_scene":null,"is_ending":false,"ending_id":null}'

    class Response:
        headers = {"content-type": "text/event-stream"}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __iter__(self):
            yield f"data: {json.dumps({'choices': [{'delta': {'content': content}}]}, ensure_ascii=False)}\n\n".encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())

    with pytest.raises(ValueError, match="duplicate top-level reply"):
        list(client.generate_chat_stream(
            request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message="你好")
        ))


def test_live_client_stream_never_emits_text_beyond_the_chat_reply_limit(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    client = LiveModelClient()
    content = json.dumps({
        "reply": "甲" * 1001,
        "emotion": "calm",
        "state_delta": {},
        "next_scene": None,
        "is_ending": False,
        "ending_id": None,
    }, ensure_ascii=False)

    class Response:
        headers = {"content-type": "text/event-stream"}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __iter__(self):
            yield f"data: {json.dumps({'choices': [{'delta': {'content': content}}]}, ensure_ascii=False)}\n\n".encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    stream = iter(client.generate_chat_stream(
        request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message="你好")
    ))
    emitted = []

    with pytest.raises(ValueError, match="reply exceeds 1000 characters"):
        while True:
            emitted.append(next(stream))

    assert sum(len(event.get("delta", "")) for event in emitted) <= 1000


def test_live_client_uses_safe_cloudflare_request_id_for_provider_diagnostics(monkeypatch):
    import io
    import urllib.error

    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()

    def forbidden(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://example.test/chat/completions",
            403,
            "Forbidden",
            {"cf-ray": "a4c37957cfc3656e-AMS"},
            io.BytesIO(b"Access denied"),
        )

    monkeypatch.setattr("urllib.request.urlopen", forbidden)

    try:
        client._request_json({"model": "test"})
    except ModelProviderError as exc:
        assert exc.provider_request_id == "a4c37957cfc3656e-AMS"
    else:
        raise AssertionError("expected provider permission error")


def test_live_client_sends_a_provider_compatible_user_agent(monkeypatch):
    import json

    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"reply": "收到。"}).encode("utf-8")

    def capture(request, **kwargs):
        captured["request"] = request
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", capture)
    client._request_json({"model": "test"})

    assert captured["request"].get_header("User-agent") == "wanderer-game/0.2.0"


def test_live_client_parses_direct_json_object_response(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()
    client._request_json = lambda payload: {"reply": "收到。", "emotion": "calm", "state_delta": {}, "next_scene": None, "is_ending": False, "ending_id": None}

    result = client.generate_chat(
        request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message="你好")
    )

    assert result["reply"] == "收到。"


def test_live_client_parses_json_object_wrapped_in_openai_content(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": '{"reply":"收到。","emotion":"calm","state_delta":{},"next_scene":null,"is_ending":false,"ending_id":null}'}}]
            }).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())

    result = client.generate_chat(
        request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message="你好")
    )

    assert result["reply"] == "收到。"


def test_live_client_maps_provider_emotion_alias_to_supported_contract_value(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": '{"reply":"你好。","emotion":"friendly","state_delta":{},"next_scene":null,"is_ending":false,"ending_id":null}'}}]
            }).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())

    result = client.generate_chat(
        request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message="你好")
    )

    assert result["emotion"] == "calm"


def test_live_client_rejects_success_payload_without_openai_choices(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test/v1")
    client = LiveModelClient()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"message":"upstream returned an unsupported shape"}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())

    try:
        client._request_json({"model": "test"})
    except ModelProviderError as exc:
        assert "格式不兼容" in exc.user_message
        assert "unsupported shape" not in str(exc)
    else:
        raise AssertionError("expected malformed provider payload error")


def test_live_gameplay_payload_contains_recent_history(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()
    captured = {}
    client._request_json = lambda payload: captured.setdefault("payload", payload) or {
        "reply": "继续。",
        "emotion": "calm",
        "state_delta": {},
        "next_scene": {"scene_id": "scene_02", "options": [{"id": "wait", "text": "等候"}]},
        "is_ending": False,
        "ending_id": None,
    }
    state = initial_state(session_id=uuid4()).model_copy(update={
        "history": [{"scene_id": "scene_01", "player_input": "我来查证", "response_summary": "那就查。"}]
    })

    client.generate(request=ModelRequest(
        character_profile=DEFAULT_CHARACTER_PROFILE,
        state_snapshot=state,
        player_message="我还要继续。",
        option_id=None,
    ))

    messages = captured["payload"]["messages"]
    assert any(item["content"] == "那就查。" for item in messages)
    assert messages[-1]["content"] == "我还要继续。"
    prompt = messages[0]["content"]
    assert "信任 50" in prompt
    assert "共情 50" in prompt
    assert "承担 50" in prompt
    assert "始终使用中文" in prompt


def test_live_client_classifies_http_401_without_exposing_response_body(monkeypatch):
    from backend.app.core.errors import ModelProviderError

    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key-that-must-not-be-returned")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()
    provider_body = b'{"error":{"message":"private provider diagnostic"}}'

    def unauthorized(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test/chat/completions", 401, "Unauthorized", {}, io.BytesIO(provider_body))

    monkeypatch.setattr("urllib.request.urlopen", unauthorized)

    try:
        client._request_json({"model": "test"})
    except ModelProviderError as exc:
        message = getattr(exc, "user_message", "")
        assert getattr(exc, "status_code", None) == 401
        assert "HTTP 401" in message
        assert "API 密钥" in message
        assert "private provider diagnostic" not in message
        assert "test-key-that-must-not-be-returned" not in message
    else:
        raise AssertionError("expected provider authorization error")


def test_live_client_classifies_http_403_as_access_permission_not_bad_key(monkeypatch):
    from backend.app.core.errors import ModelProviderError

    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()
    provider_body = b'{"error":{"type":"permission_denied","message":"private diagnostic"}}'

    def forbidden(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test/chat/completions", 403, "Forbidden", {}, io.BytesIO(provider_body))

    monkeypatch.setattr("urllib.request.urlopen", forbidden)

    try:
        client._request_json({"model": "test"})
    except ModelProviderError as exc:
        message = exc.user_message
        assert "权限" in message
        assert "HTTP 403" in message
        assert "不一定表示密钥错误" in message
        assert "API 密钥" not in message
        assert "private diagnostic" not in message
    else:
        raise AssertionError("expected provider permission error")


def test_live_client_preserves_only_safe_diagnostics_from_http_403(monkeypatch):
    from backend.app.core.errors import ModelProviderError

    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "do-not-leak-this-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://provider.example/v1")
    client = LiveModelClient()
    provider_body = json.dumps({"error": {"code": "ip_blocked", "message": "do-not-leak-this-key"}}).encode()

    def forbidden(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://provider.example/v1/chat/completions",
            403,
            "Forbidden",
            {"x-request-id": "req-safe-456"},
            io.BytesIO(provider_body),
        )

    monkeypatch.setattr("urllib.request.urlopen", forbidden)

    try:
        client._request_json({"model": "test"})
    except ModelProviderError as exc:
        assert exc.status_code == 403
        assert exc.provider_code == "ip_blocked"
        assert exc.provider_request_id == "req-safe-456"
        assert "do-not-leak-this-key" not in str(exc)
        assert "do-not-leak-this-key" not in exc.user_message
    else:
        raise AssertionError("expected provider permission error")


def test_live_free_chat_prompt_uses_the_players_chosen_name(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()
    captured = {}
    client._request_json = lambda payload: captured.setdefault("payload", payload) or {}

    client.generate_chat(request=ChatModelRequest(
        character_profile=DEFAULT_CHARACTER_PROFILE,
        message="你在说谁？",
        player_name="清岚",
    ))

    prompt = captured["payload"]["messages"][0]["content"]
    assert "玩家希望被称呼为「清岚」" in prompt
    assert "自称只能使用“我”" in prompt
    assert "称玩家为“你”或「清岚」" in prompt
    assert "第三人称代词只能用于其他角色" in prompt
    assert "不得以浮浪倾客、流浪者、倾奇者、散兵、国崩、阿帽、斯卡拉姆齐中的任何一个名号指代自己" in prompt
    assert "不要写“我是散兵”或“我叫阿帽”" in prompt

def test_live_free_chat_prompt_has_no_exclusive_self_naming_rules(monkeypatch):
    monkeypatch.setenv("WANDERER_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://example.test")
    client = LiveModelClient()
    captured = {}
    client._request_json = lambda payload: captured.setdefault("payload", payload) or {}

    client.generate_chat(request=ChatModelRequest(
        character_profile=DEFAULT_CHARACTER_PROFILE,
        message="你在说谁？",
        player_name="清岚",
    ))

    prompt = captured["payload"]["messages"][0]["content"]
    assert "不使用其他称呼替代" not in prompt
    assert "作为自己的称呼" not in prompt


def test_offline_replies_and_fallbacks_have_no_self_name_references():
    from backend.app.core.model_client import (
        DeterministicModelClient,
        _FALLBACK,
        _FIXTURES,
        _OPENINGS,
        _STORY_FIXTURES,
    )
    from backend.app.core.pronoun_guard import FALLBACK_REPLIES, guard_reply

    fixtures = [*_FIXTURES.values(), *_STORY_FIXTURES.values(), *_OPENINGS.values(), _FALLBACK]
    for fixture in fixtures:
        result = guard_reply(fixture["reply"])
        assert result.status == "clean"
        assert result.text == fixture["reply"]

    client = DeterministicModelClient()
    probes = ["谢谢", "很难过", "踏鞴砂的真相", "今天风怎么样", "你好", "在吗", "随便", "继续"]
    for message in probes:
        payload = client.generate_chat(
            request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message=message)
        )
        result = guard_reply(payload["reply"])
        assert result.status == "clean"
        assert result.text == payload["reply"]

    remainders = {sum(ord(char) for char in message) % 4 for message in ("你好", "在吗", "随便", "继续")}
    assert remainders == {0, 1, 2, 3}

    for reply in FALLBACK_REPLIES:
        assert guard_reply(reply).status == "clean"
        assert len(reply) <= 20

def test_offline_replies_stay_clean_in_intro_intent_context():
    from backend.app.core.model_client import (
        DeterministicModelClient,
        _FALLBACK,
        _FIXTURES,
        _OPENINGS,
        _STORY_FIXTURES,
    )
    from backend.app.core.pronoun_guard import guard_chat_reply

    intro_message = "介绍一下你自己"
    fixtures = [*_FIXTURES.values(), *_STORY_FIXTURES.values(), *_OPENINGS.values(), _FALLBACK]
    for fixture in fixtures:
        result = guard_chat_reply(intro_message, fixture["reply"])
        assert result.status == "clean"
        assert result.text == fixture["reply"]

    client = DeterministicModelClient()
    probes = ["谢谢", "很难过", "踏鞴砂的真相", "今天风怎么样", "你好", "在吗", "随便", "继续"]
    for message in probes:
        payload = client.generate_chat(
            request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message=message)
        )
        result = guard_chat_reply(intro_message, payload["reply"])
        assert result.status == "clean"
        assert result.text == payload["reply"]

    state = initial_state(session_id=uuid4()).model_copy(update={"scene_id": "scene_08"})
    for option_id in ("accept_burden", "walk_away"):
        payload = client.generate(
            request=ModelRequest(
                character_profile=DEFAULT_CHARACTER_PROFILE,
                state_snapshot=state,
                player_message=None,
                option_id=option_id,
            )
        )
        result = guard_chat_reply(intro_message, payload["reply"])
        assert result.status == "clean"
        assert result.text == payload["reply"]


def test_fallback_pools_pass_scene_guard_with_no_element_or_pathological_mentions():
    import backend.app.core.pronoun_guard as pronoun_guard
    from backend.app.core.pronoun_guard import (
        ELEMENT_SELF_REFERENCE_TERMS,
        FALLBACK_REPLIES,
        INTRO_FALLBACK_REPLIES,
        guard_chat_reply,
        guard_reply,
    )

    intro_message = "介绍一下你自己"
    for reply in (*FALLBACK_REPLIES, *INTRO_FALLBACK_REPLIES):
        assert all(term not in reply for term in ELEMENT_SELF_REFERENCE_TERMS)
        assert pronoun_guard._PATHOLOGICAL_SELF_INTRO_RE.search(reply) is None
        assert guard_reply(reply).status == "clean"
        result = guard_chat_reply(intro_message, reply)
        assert result.status == "clean"
        assert result.text == reply


def test_offline_script_lines_are_frozen_verbatim():
    from backend.app.core.model_client import (
        DeterministicModelClient,
        _FALLBACK,
        _FIXTURES,
        _OPENINGS,
    )

    frozen_fixture_replies = {
        ("scene_01", "ask_truth"): "你倒是直接。真相不会因为问得急就变得干净，先看看谁有意把记录撕掉了。",
        ("scene_01", "accept_task"): "行。既然你自己撞上来，就别指望我给你留退路。",
        ("scene_01", "listen"): "先听清楚再开口，至少还算知道分寸。委托人的话有遗漏，沿着风里残留的气息查下去。",
        ("scene_02", "inspect_records"): "纸上的字迹被人改过。记下每一处不合常理的地方，别让所谓的证据替你思考。",
        ("scene_02", "question_witness"): "他不是不想说，是害怕说错一句就要付出代价。别把追问变成另一种逼迫。",
        ("scene_truth", "inspect_records"): "你找到了缺口。有人把自己的责任藏进了别人的叙述里，现在轮到我们把它翻出来。",
        ("scene_truth", "confront_handler"): "质问当然痛快，可对方会把你的愤怒当成遮掩。先让他把自己说过的话说完。",
        ("scene_03", "follow_wind"): "风把你带到旧址边缘。那里留下的不是答案，是一群人不愿再提的代价。",
        ("scene_03", "protect_witness"): "你替别人挡了一步，事情就不会因此变简单。但至少今晚，不会再有人因为知道真相而被推下悬崖。",
        ("scene_witness", "follow_wind"): "你没有逼他继续说。顺着他指向的方向走，风会把剩下的线索送回来。",
        ("scene_witness", "protect_witness"): "把人护在身后并不能抹掉过去，却能让他有机会亲口说完。这个选择比你想的更重。",
        ("scene_truth_evidence", "follow_wind"): "你抓住了被抹掉的痕迹。别急着庆祝，真相越完整，必须承担的东西就越多。",
        ("scene_truth_evidence", "protect_witness"): "你先护住了知情者，证据可以晚一点，人的安全不能。别把这当成宽恕。",
        ("scene_confront", "follow_wind"): "你把怒火压回去，终于看见对方话里的裂缝。能控制自己，才有资格追问别人。",
        ("scene_confront", "protect_witness"): "你把知情者带离争执。承担风险的人应该是做决定的人，不该是最先开口的人。",
        ("scene_04", "return_evidence"): "证据摆在面前，谁也不能再假装没看见。现在的问题是，你准备让谁来承担后果。",
        ("scene_04", "accept_risk"): "你选择先站到风口。勇气不是把后果说得好听，而是知道会痛仍然不把它推给别人。",
        ("scene_05", "tell_truth"): "说出口的真相不会自动修复任何人，但至少从这一刻起，没人能再借沉默逃走。",
        ("scene_05", "hide_truth"): "你留了一手。也许能换来片刻安稳，也许只是把更难看的部分推迟到以后。",
        ("scene_06", "stay"): "留下来很麻烦，却也意味着你不会把残局丢给下一个路过的人。别误会，我只是看不惯半途而废。",
        ("scene_06", "leave"): "离开也算一种选择。只是你要记住，转身不会让已经发生的事消失。",
        ("scene_07", "protect_others"): "你把别人挡在身后。这个动作没有让你变得无罪，却让风里多了一点不至于崩塌的东西。",
        ("scene_07", "protect_self"): "你先护住了自己。活下来并不可耻，只是之后别再假装代价从未存在。",
    }
    assert {key: fixture["reply"] for key, fixture in _FIXTURES.items()} == frozen_fixture_replies

    frozen_opening_replies = {
        "demo_guarded_path": "你若只是来问路，就不必绕这么大的弯子。说吧，究竟想从我这里得到什么？",
        "demo_direct_path": "你看起来已经决定了。也好，至少省去一番无意义的劝告。只是别把鲁莽误认为勇气。",
    }
    assert {key: fixture["reply"] for key, fixture in _OPENINGS.items()} == frozen_opening_replies
    assert _FALLBACK["reply"] == "有什么想说的就说，别指望我先替你表态。"

    client = DeterministicModelClient()

    def chat_reply(message):
        return client.generate_chat(
            request=ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message=message)
        )["reply"]

    assert chat_reply("谢谢") == "少说这些。做好你该做的事就够了。"
    assert chat_reply("很难过") == "把情绪收好。没人会因为你难受就替你承担后果。"
    assert chat_reply("踏鞴砂的真相") == "那段过去不会因为你问起，就变得更容易接受。想知道什么，直说。"
    assert chat_reply("今天风怎么样") == "风向没变。变的是你终于肯抬头看路了。"
    assert chat_reply("你好") == "这种问题也值得你专程来问？再想清楚些。"
    assert chat_reply("在吗") == "呵，至少这次你没有重复同一句废话。"
    assert chat_reply("随便") == "我听见了。别急着把答案推给别人。"
    assert chat_reply("继续") == "有话直说。拐弯抹角只会浪费时间。"

    state = initial_state(session_id=uuid4()).model_copy(update={"scene_id": "scene_08"})
    accept = client.generate(request=ModelRequest(
        character_profile=DEFAULT_CHARACTER_PROFILE,
        state_snapshot=state,
        player_message=None,
        option_id="accept_burden",
    ))
    assert accept["reply"] == "你没有抹去往事，也没有要求谁的宽恕。既然选择背起来，就别在半路松手。"
    assert accept["ending_id"] == "burden_bearer"
    walk_away = client.generate(request=ModelRequest(
        character_profile=DEFAULT_CHARACTER_PROFILE,
        state_snapshot=state,
        player_message=None,
        option_id="walk_away",
    ))
    assert walk_away["reply"] == "风会把你的脚印吹散，却不会替你改写走过的路。至少这一次，选择是你自己的。"
    assert walk_away["ending_id"] == "solitary_wanderer"
