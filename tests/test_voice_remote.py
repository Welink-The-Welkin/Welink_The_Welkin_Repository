"""Remote deployment contracts; all upstream requests use an in-memory transport."""

from contextlib import contextmanager
import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import wave
import traceback
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect, Request

from backend.app import voice
from backend.app.core.voice_config import validate_api_url
from backend.app.main import create_app


REMOTE_URL = "https://voice-service.invalid/tts"
REFERENCE = "fixtures/reference.wav"
PROMPT = "deployment-only placeholder transcript"


def wav_bytes():
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(struct.pack("<hhhh", 1, -2, 3, -4))
    return output.getvalue()


WAV = wav_bytes()


@pytest.fixture(autouse=True)
def isolated_remote_environment(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.startswith("WANDERER_TTS_") or name == "GPT_SOVITS_ROOT":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_API_URL", REMOTE_URL)
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", REFERENCE)
    monkeypatch.setenv("WANDERER_TTS_PROMPT_TEXT", PROMPT)
    monkeypatch.setenv("WANDERER_TTS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        voice.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: pytest.fail("remote voice must not inspect a workstation profile")))


@pytest.fixture
def client():
    app = create_app(database_path_override=":memory:", demo_mode_override="offline")
    with TestClient(app) as browser:
        yield browser
    app.state.database.close()


@pytest.fixture
def upstream(monkeypatch):
    requests = []
    responses = []

    def handler(request):
        requests.append(request)
        if responses:
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        if request.method == "GET":
            return httpx.Response(200, json={"paths": {"/tts": {"post": {}}}})
        return httpx.Response(200, content=WAV, headers={"content-type": "audio/wav"})

    transport = httpx.MockTransport(handler)
    # Keep HTTP parsing, redirect handling and response semantics real; replace
    # only the network boundary. Top-level HTTPX functions do not follow by default.
    def request(method, url, **kwargs):
        with httpx.Client(
            transport=transport,
            follow_redirects=kwargs.pop("follow_redirects", False),
            trust_env=kwargs.pop("trust_env", True),
        ) as session:
            return session.request(method, url, **kwargs)

    @contextmanager
    def stream(method, url, **kwargs):
        with httpx.Client(
            transport=transport,
            follow_redirects=kwargs.pop("follow_redirects", False),
            trust_env=kwargs.pop("trust_env", True),
        ) as session:
            with session.stream(method, url, **kwargs) as response:
                yield response

    monkeypatch.setattr(voice.httpx, "get", lambda url, **kwargs: request("GET", url, **kwargs))
    monkeypatch.setattr(voice.httpx, "post", lambda url, **kwargs: request("POST", url, **kwargs))
    monkeypatch.setattr(voice.httpx, "stream", stream)
    return requests, responses


@pytest.mark.parametrize("route", ["synthesize", "stream"])
def test_remote_voice_proxies_wav_without_a_local_install(client, upstream, monkeypatch, route):
    requests, _ = upstream
    monkeypatch.setenv("GPT_SOVITS_ROOT", "/unavailable/developer/workstation")
    response = (
        client.post("/api/voice/synthesize", json={"text": "  远程语音。  "})
        if route == "synthesize" else client.get("/api/voice/stream", params={"text": "  远程语音。  "})
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == WAV
    assert len(requests) == 1
    assert str(requests[0].url) == REMOTE_URL
    payload = json.loads(requests[0].content)
    assert payload["text"] == "远程语音。"
    assert payload["ref_audio_path"] == REFERENCE
    assert payload["prompt_text"] == PROMPT
    assert payload["streaming_mode"] == (1 if route == "stream" else False)


@pytest.mark.parametrize("field", ["url", "api_url", "ref_audio_path", "reference_audio", "prompt_text", "credentials"])
@pytest.mark.parametrize("route", ["synthesize", "stream"])
def test_browser_can_supply_only_text(client, upstream, route, field):
    requests, _ = upstream
    payload = {"text": "hello", field: "browser-controlled"}
    response = (
        client.post("/api/voice/synthesize", json=payload)
        if route == "synthesize" else client.get("/api/voice/stream", params=payload)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert requests == []
    assert "browser-controlled" not in response.text


def test_remote_status_is_value_free_and_independent_of_workstation(client, upstream):
    requests, _ = upstream
    response = client.get("/api/voice/status")
    assert response.json()["data"] == {
        "enabled": True, "configured": True, "mode": "remote",
        "diagnostics": [], "compatibility_voice_available": True,
    }
    assert str(requests[0].url) == "https://voice-service.invalid/openapi.json"
    for private in (REMOTE_URL, REFERENCE, PROMPT):
        assert private not in response.text


def test_remote_ignores_local_weight_settings_and_preserves_upstream_path(client, upstream, monkeypatch):
    requests, _ = upstream
    def reject_profile_expansion(path):
        raise AssertionError("remote paths must not expand a web-host user profile")
    monkeypatch.setattr(Path, "expanduser", reject_profile_expansion)
    monkeypatch.setenv("GPT_SOVITS_ROOT", "~/unavailable-install")
    monkeypatch.setenv("WANDERER_TTS_GPT_WEIGHTS", "~/unavailable-checkpoint")
    monkeypatch.setenv("WANDERER_TTS_SOVITS_WEIGHTS", "~/unavailable-vocoder")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", "~/deployment-placeholder")
    response = client.post("/api/voice/synthesize", json={"text": "hello"})
    assert response.status_code == 200
    assert json.loads(requests[0].content)["ref_audio_path"] == "~/deployment-placeholder"


@pytest.mark.parametrize("route", ["synthesize", "stream"])
@pytest.mark.parametrize("kind", ["redirect", "upstream_error", "timeout", "wrong_type", "empty"])
def test_remote_failure_is_safe_and_never_follows_redirects(client, upstream, route, kind):
    requests, responses = upstream
    responses.append({
        "redirect": httpx.Response(307, headers={"location": "http://127.0.0.1/private-secret"}),
        "upstream_error": httpx.Response(500, text=f"{REFERENCE} {PROMPT}"),
        "timeout": httpx.ReadTimeout(f"{REMOTE_URL} private-secret"),
        "wrong_type": httpx.Response(200, text=REFERENCE, headers={"content-type": "text/plain"}),
        "empty": httpx.Response(200, content=b"", headers={"content-type": "audio/wav"}),
    }[kind])
    response = (
        client.post("/api/voice/synthesize", json={"text": "hello"})
        if route == "synthesize" else client.get("/api/voice/stream", params={"text": "hello"})
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VOICE_UNAVAILABLE"
    assert len(requests) == 1
    for private in (REMOTE_URL, REFERENCE, PROMPT, "private-secret", "127.0.0.1"):
        assert private not in response.text


def test_status_redirect_is_not_followed(client, upstream):
    requests, responses = upstream
    responses.append(httpx.Response(302, headers={"location": "http://127.0.0.1/private-secret"}))
    response = client.get("/api/voice/status")
    assert response.json()["data"]["enabled"] is False
    assert response.json()["data"]["diagnostics"][0]["code"] == "TTS_API_UNREACHABLE"
    assert len(requests) == 1
    assert "private-secret" not in response.text


@pytest.mark.parametrize("schema", [[], {"paths": []}, {"paths": {"/tts": {"get": {}}}}])
def test_remote_malformed_or_unrelated_readiness_schema_is_safe(client, upstream, schema):
    _, responses = upstream
    responses.append(httpx.Response(200, json=schema))
    response = client.get("/api/voice/status")
    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is False
    assert response.json()["data"]["diagnostics"][0]["code"] == "TTS_API_UNREACHABLE"


def test_synthesis_query_cannot_supply_upstream_settings(client, upstream):
    requests, _ = upstream
    response = client.post("/api/voice/synthesize?api_url=https://browser.invalid", json={"text": "hello"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert requests == []


@pytest.mark.parametrize("url", [
    "http://voice-service.invalid/tts", "https://127.0.0.1/tts", "https://localhost/tts",
    "https://[::1]/tts", "https://10.0.0.1/tts", "https://192.168.1.1/tts",
    "https://169.254.169.254/tts", "https://user:private-secret@voice-service.invalid/tts",
    "https://LOCALHOST./tts", "https://service.localhost/tts", "https://service.local/tts",
    "https://[fc00::1]/tts", "https://[::ffff:127.0.0.1]/tts", "https://2130706433/tts",
])
def test_remote_rejects_insecure_or_workstation_endpoints(client, upstream, monkeypatch, url):
    requests, _ = upstream
    monkeypatch.setenv("WANDERER_TTS_API_URL", url)
    status = client.get("/api/voice/status")
    assert status.json()["data"]["configured"] is False
    assert status.json()["data"]["diagnostics"][0]["code"] == "TTS_API_INVALID"
    response = client.post("/api/voice/synthesize", json={"text": "hello"})
    assert response.status_code == 503
    assert requests == []
    assert url not in status.text + response.text


def test_remote_validator_rejects_loopback_http_without_weakening_local_mode():
    with pytest.raises(ValueError):
        validate_api_url("http://127.0.0.1/tts", mode="remote")
    assert validate_api_url("http://127.0.0.1/tts", mode="local") == "http://127.0.0.1/tts"
    with pytest.raises(ValueError):
        validate_api_url(REMOTE_URL, mode="local")


def test_remote_dns_private_answer_is_rejected_even_with_mock_transport(client, upstream, monkeypatch):
    requests, _ = upstream
    monkeypatch.setattr(voice.socket, "getaddrinfo", lambda *args, **kwargs: [(0, 0, 0, "", ("127.0.0.1", 443))])
    response = client.post("/api/voice/synthesize", json={"text": "hello"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VOICE_UNAVAILABLE"
    assert requests == []


def test_endpoint_change_cannot_reuse_another_remote_voices_cache(client, upstream, monkeypatch):
    requests, _ = upstream
    assert client.post("/api/voice/synthesize", json={"text": "hello"}).status_code == 200
    monkeypatch.setenv("WANDERER_TTS_API_URL", "https://other-voice.invalid/tts")
    assert client.post("/api/voice/synthesize", json={"text": "hello"}).status_code == 200
    assert [str(request.url) for request in requests] == [REMOTE_URL, "https://other-voice.invalid/tts"]


class FragmentedAudio(httpx.SyncByteStream):
    def __init__(self, fragments):
        self.fragments = fragments
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for fragment in self.fragments:
            self.consumed += 1
            if isinstance(fragment, Exception):
                raise fragment
            yield fragment

    def close(self):
        self.closed = True


@pytest.mark.parametrize("body", [
    b'{"error":"upstream-private-body"}',
    b'RIFF' + b'upstream-private-body',
    WAV[:36],
    WAV[:8] + b'JSON' + WAV[12:44],
    WAV[:20] + b'\xff\xff' + WAV[22:44],
    WAV[:32] + b'\x00\x00' + WAV[34:44],
])
def test_stream_rejects_mislabeled_or_incomplete_wav_before_response(client, upstream, caplog, body):
    _, responses = upstream
    stream = FragmentedAudio([body[:3], body[3:]])
    responses.append(httpx.Response(200, stream=stream, headers={"content-type": "audio/wav"}))
    with TestClient(client.app, raise_server_exceptions=False) as browser:
        response = browser.get("/api/voice/stream", params={"text": "malformed"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VOICE_UNAVAILABLE"
    assert "upstream-private-body" not in response.text + caplog.text
    assert stream.closed
    assert not list(voice._cache_path("malformed").parent.glob("*.tmp"))


def test_stream_validates_cached_header_before_response(client, upstream):
    requests, _ = upstream
    cached = voice._cache_path("cached malformed")
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"upstream-private-body")
    response = client.get("/api/voice/stream", params={"text": "cached malformed"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VOICE_UNAVAILABLE"
    assert "upstream-private-body" not in response.text
    assert requests == []


@pytest.mark.parametrize("zero_header", [False, True])
def test_stream_waits_for_complete_header_then_yields_without_consuming_pcm(upstream, zero_header):
    _, responses = upstream
    header = bytearray(WAV[:44])
    if zero_header:
        struct.pack_into("<I", header, 4, 36)
        struct.pack_into("<I", header, 40, 0)
    stream = FragmentedAudio([bytes(header[:3]), bytes(header[3:29]), bytes(header[29:]), WAV[44:]])
    responses.append(httpx.Response(200, stream=stream, headers={"content-type": "audio/wav"}))
    producer = voice.stream_voice("header latency")
    try:
        first = next(producer)
        assert first == header
        assert stream.consumed == 3
        assert b"".join(producer) == WAV[44:]
        assert voice._cache_path("header latency").read_bytes() == bytes(header) + WAV[44:]
    finally:
        producer.close()
    assert stream.closed


@pytest.mark.parametrize("blank", ["", "  "])
def test_blank_cache_dir_uses_ignored_default_without_writing(monkeypatch, tmp_path, blank):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WANDERER_TTS_CACHE_DIR", blank)
    path = voice._cache_path("cache placeholder")
    assert path.parent == Path("data/voice-cache")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("host", [
    "0x7f.0.0.1", "0x0a.0.0.1", "0177.0.0.1", "127.1", "0x7f000001",
    "0x7f.1", "10.0x0.0.1", "0300.0250.1.1", "2130706433", "127.0.000.1",
])
def test_remote_rejects_legacy_numeric_ipv4_aliases_without_dns(host):
    with pytest.raises(ValueError):
        validate_api_url(f"https://{host}/tts", mode="remote")


def test_late_upstream_failure_has_no_private_exception_chain(upstream):
    _, responses = upstream
    stream = FragmentedAudio([WAV[:44], httpx.ReadError("upstream-private-body")])
    responses.append(httpx.Response(200, stream=stream, headers={"content-type": "audio/wav"}))
    producer = voice.stream_voice("late failure")
    assert next(producer) == WAV[:44]
    with pytest.raises(voice.VoiceUnavailableError) as error:
        next(producer)
    assert "upstream-private-body" not in "".join(traceback.format_exception(error.value))
    assert stream.closed


@pytest.mark.parametrize("abort", ["start_error", "body_error", "cancel", "disconnect"])
def test_response_abort_explicitly_closes_primed_upstream_and_staging(upstream, abort):
    from backend.app.api.routes import voice as route

    _, responses = upstream
    network_stream = FragmentedAudio([WAV[:44], WAV[44:]])
    responses.append(httpx.Response(200, stream=network_stream, headers={"content-type": "audio/wav"}))
    scope = {"type": "http", "method": "GET", "path": "/api/voice/stream", "headers": [],
             "query_string": b"text=abort", "asgi": {"spec_version": "2.0" if abort == "disconnect" else "2.4"}}
    response = route.stream(Request(scope), text="abort")
    cache = voice._cache_path("abort")
    assert network_stream.closed is False

    async def exercise():
        body_started = asyncio.Event()

        async def send(message):
            if abort == "start_error" and message["type"] == "http.response.start":
                raise OSError("controlled send abort")
            if message["type"] == "http.response.body":
                body_started.set()
                if abort == "body_error":
                    raise OSError("controlled send abort")
                await asyncio.Event().wait()

        async def receive():
            await body_started.wait()
            return {"type": "http.disconnect"}

        task = asyncio.create_task(response(scope, receive, send))
        if abort == "cancel":
            await body_started.wait()
            task.cancel()
        try:
            await task
        except (OSError, ClientDisconnect, asyncio.CancelledError):
            pass
        # Assert before asyncio.run shuts down/finalizes async generators.
        assert network_stream.closed
        assert cache not in voice._CACHE_LOCKS
        assert list(cache.parent.iterdir()) == []

    try:
        asyncio.run(exercise())
        # Keep response alive: success must not depend on garbage collection.
        assert response is not None
        assert network_stream.closed
        assert cache not in voice._CACHE_LOCKS
        assert not cache.exists()
        assert list(cache.parent.iterdir()) == []
    finally:
        # Test-owned cleanup allows expected RED assertions without leaking locks.
        close = getattr(response.body_iterator, "aclose", None)
        if close:
            asyncio.run(close())


def test_cancellation_during_worker_read_waits_then_closes_without_masking_cancel(upstream):
    from backend.app.api.routes import voice as route

    reading = threading.Event()
    release = threading.Event()
    read_finished = threading.Event()

    class BlockedAudio(httpx.SyncByteStream):
        closed = 0

        def __iter__(self):
            yield WAV[:44]
            reading.set()
            try:
                if not release.wait(timeout=3):
                    raise AssertionError("test read release timed out")
                yield WAV[44:]
            finally:
                read_finished.set()

        def close(self):
            self.closed += 1

    _, responses = upstream
    network_stream = BlockedAudio()
    responses.append(httpx.Response(200, stream=network_stream, headers={"content-type": "audio/wav"}))
    scope = {"type": "http", "method": "GET", "path": "/api/voice/stream", "headers": [],
             "query_string": b"text=blocked", "asgi": {"spec_version": "2.4"}}
    response = route.stream(Request(scope), text="blocked")
    cache = voice._cache_path("blocked")

    async def exercise():
        async def send(message):
            pass

        async def receive():
            await asyncio.Event().wait()

        task = asyncio.create_task(response(scope, receive, send))
        try:
            assert await asyncio.to_thread(reading.wait, 2)
            task.cancel()
            # Keep next(audio) in flight while the response enters cleanup.
            await asyncio.sleep(0.05)
            assert not task.done(), "cleanup must await the in-flight read"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
            # These run before asyncio.run finalizes generators; retain response.
            assert response is not None
            assert network_stream.closed == 1
            assert cache not in voice._CACHE_LOCKS
            assert not cache.exists()
            assert list(cache.parent.iterdir()) == []
        finally:
            release.set()
            try:
                await task
            except (asyncio.CancelledError, ValueError):
                pass
            await asyncio.to_thread(read_finished.wait, 2)
            # Explicit test cleanup keeps the expected RED from leaking state.
            response.audio.close()

    asyncio.run(exercise())
    assert network_stream.closed == 1
