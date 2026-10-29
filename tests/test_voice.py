import json
from io import BytesIO
import wave
import importlib.util
from pathlib import Path
import threading
import struct
import time
import sys
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.voice import stream_voice


def _load_launcher():
    path = Path(__file__).resolve().parents[1] / "scripts" / "start_gpt_sovits.py"
    spec = importlib.util.spec_from_file_location("wanderer_gpt_sovits_launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tts_config_uses_configured_checkpoint_and_cpu_compatible_v2pro():
    launcher = _load_launcher()
    root = Path("C:/path/to/GPT-SoVITS")

    config = launcher.build_tts_config(root, "cpu")

    assert config["custom"]["device"] == "cpu"
    assert config["custom"]["version"] == "v2Pro"
    assert config["custom"]["is_half"] is False
    assert config["custom"]["t2s_weights_path"] == str(root / "GPT_weights_v2Pro" / "model.ckpt")
    assert config["custom"]["vits_weights_path"] == str(root / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2Pro.pth")


def test_default_voice_reference_uses_a_configurable_placeholder_path(tmp_path, monkeypatch):
    launcher = _load_launcher()
    reference = tmp_path / "logs" / "wanderer" / "reference.wav"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(WAV_BYTES)
    monkeypatch.delenv("WANDERER_TTS_REFERENCE_AUDIO", raising=False)
    monkeypatch.delenv("WANDERER_TTS_PROMPT_TEXT", raising=False)

    settings = launcher.voice_config(tmp_path, "cpu")

    assert settings["reference_audio"] == reference.resolve()
    assert settings["prompt_text"] == ""


def test_gpt_sovits_root_uses_a_generic_home_directory_by_default(tmp_path, monkeypatch):
    launcher = _load_launcher()
    root = tmp_path / "GPT-SoVITS"
    for relative in (
        "api_v2.py",
        "runtime/python.exe",
        "GPT_weights_v2Pro/model.ckpt",
        "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.delenv("GPT_SOVITS_ROOT", raising=False)
    monkeypatch.setattr(launcher.Path, "home", lambda: tmp_path)

    assert launcher.resolve_root() == root.resolve()


def test_voice_config_auto_selects_a_usable_cuda_runtime(tmp_path, monkeypatch):
    launcher = _load_launcher()
    reference = tmp_path / "reference.wav"
    reference.write_bytes(WAV_BYTES)
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))
    monkeypatch.setattr(launcher, "_runtime_has_usable_cuda", lambda root: True, raising=False)

    settings = launcher.voice_config(tmp_path, "auto")

    assert settings["device"] == "cuda"
    assert settings["config"]["custom"]["is_half"] is True


def test_voice_config_auto_falls_back_to_cpu_without_usable_cuda(tmp_path, monkeypatch):
    launcher = _load_launcher()
    reference = tmp_path / "reference.wav"
    reference.write_bytes(WAV_BYTES)
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))
    monkeypatch.setattr(launcher, "_runtime_has_usable_cuda", lambda root: False, raising=False)

    settings = launcher.voice_config(tmp_path, "auto")

    assert settings["device"] == "cpu"
    assert settings["config"]["custom"]["is_half"] is False


def test_cuda_probe_falls_back_when_device_allocates_but_kernel_execution_is_unsupported(tmp_path, monkeypatch):
    launcher = _load_launcher()
    (tmp_path / "torch.py").write_text(
        """
class _Cuda:
    @staticmethod
    def is_available():
        return True

class _Tensor:
    def __add__(self, other):
        raise RuntimeError('no kernel image is available for execution')

cuda = _Cuda()

def device(name):
    return name

def empty(size, device=None):
    return _Tensor()

def ones(size, device=None):
    return _Tensor()
""",
        encoding="utf-8",
    )

    real_run = subprocess.run

    def run_probe(command, **kwargs):
        assert command[1] == "-c"
        return real_run(
            [sys.executable, "-c", command[2]],
            cwd=tmp_path,
            stdin=kwargs.get("stdin"),
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            text=kwargs.get("text"),
            timeout=kwargs.get("timeout"),
            check=kwargs.get("check", False),
        )

    monkeypatch.setattr(launcher.subprocess, "run", run_probe)

    assert launcher._runtime_has_usable_cuda(tmp_path) is False


def test_auto_tts_start_retries_with_cpu_when_cuda_server_exits(tmp_path, monkeypatch):
    launcher = _load_launcher()
    session_file = tmp_path / "voice-session.json"
    config_path = tmp_path / "gpt-sovits.json"
    reference = tmp_path / "reference.wav"
    reference.write_bytes(WAV_BYTES)
    devices = []
    readiness_checks = []

    def fake_voice_config(root, device=None):
        devices.append(device)
        selected = "cuda" if device in {None, "auto"} else device
        return {"root": root, "device": selected, "config": {"custom": {"device": selected}}, "reference_audio": reference, "prompt_text": ""}

    class FakeProcess:
        next_pid = 2000

        def __init__(self, exited):
            self.pid = FakeProcess.next_pid
            FakeProcess.next_pid += 1
            self.exited = exited

        def poll(self):
            return 1 if self.exited else None

    processes = iter([FakeProcess(True), FakeProcess(False)])
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_DEVICE", "auto")
    monkeypatch.setattr(launcher, "_load_game_env", lambda root: None)
    monkeypatch.setattr(launcher, "resolve_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "voice_config", fake_voice_config)
    monkeypatch.setattr(launcher, "tts_endpoint", lambda: ("127.0.0.1", 9880))
    monkeypatch.setattr(launcher, "tts_config_path", lambda: config_path)
    monkeypatch.setattr(launcher, "_is_ready", lambda host, port: readiness_checks.append(True) or len(readiness_checks) > 1)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: next(processes))
    monkeypatch.setattr(launcher, "sleep", lambda seconds: None)

    assert launcher.ensure_tts_server(session_file) is True
    assert devices == [None, "cpu"]


def test_shutdown_terminates_only_the_tts_process_owned_by_this_game_run(tmp_path, monkeypatch):
    launcher = _load_launcher()
    state_path = tmp_path / "voice-session.json"
    state_path.write_text(json.dumps({"owns_server": True, "pid": 45678}), encoding="utf-8")
    terminated = []
    monkeypatch.setattr(launcher, "_terminate_process", lambda pid: terminated.append(pid))

    launcher.stop_tts_server(state_path)

    assert terminated == [45678]
    assert not state_path.exists()


def test_shutdown_does_not_terminate_a_tts_server_reused_from_another_game_run(tmp_path, monkeypatch):
    launcher = _load_launcher()
    state_path = tmp_path / "voice-session.json"
    state_path.write_text(json.dumps({"owns_server": False, "pid": 45678}), encoding="utf-8")
    terminated = []
    monkeypatch.setattr(launcher, "_terminate_process", lambda pid: terminated.append(pid))

    launcher.stop_tts_server(state_path)

    assert terminated == []
    assert not state_path.exists()


def _wav_bytes(*samples: int) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(32000)
        audio.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return output.getvalue()


WAV_BYTES = _wav_bytes(1000, -1000, 500, -500)


class _TTSHandler(BaseHTTPRequestHandler):
    requests = []
    audio_bytes = WAV_BYTES
    api_paths = {"/tts": {"post": {"operationId": "tts"}}}

    def do_GET(self):  # noqa: N802 - stdlib handler API
        if self.path == "/openapi.json":
            payload = json.dumps({"paths": self.__class__.api_paths}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def do_POST(self):  # noqa: N802 - stdlib handler API
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.__class__.requests.append(payload)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(self.__class__.audio_bytes)))
        self.end_headers()
        self.wfile.write(self.__class__.audio_bytes)

    def log_message(self, *_args):
        return


def _tts_server():
    _TTSHandler.requests = []
    _TTSHandler.api_paths = {"/tts": {"post": {"operationId": "tts"}}}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TTSHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_voice_status_is_disabled_without_explicit_tts_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("WANDERER_TTS_ENABLED", raising=False)
    client = TestClient(create_app(database_path_override=tmp_path / "voice-status.db", demo_mode_override="offline"))

    response = client.get("/api/voice/status")

    assert response.status_code == 200
    assert response.json()["data"] == {"enabled": False, "configured": False}


def test_voice_status_enables_only_after_the_local_tts_api_is_ready(tmp_path, monkeypatch):
    server, thread = _tts_server()
    reference_audio = tmp_path / "reference.wav"
    reference_audio.write_bytes(WAV_BYTES)
    try:
        monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
        monkeypatch.setenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{server.server_port}/tts")
        monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference_audio))
        client = TestClient(create_app(database_path_override=tmp_path / "voice-ready.db", demo_mode_override="offline"))

        response = client.get("/api/voice/status")

        assert response.status_code == 200
        assert response.json()["data"] == {"enabled": True, "configured": True}
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_voice_status_rejects_an_unrelated_local_openapi_server(tmp_path, monkeypatch):
    server, thread = _tts_server()
    _TTSHandler.api_paths = {"/health": {"get": {"operationId": "health"}}}
    reference_audio = tmp_path / "reference.wav"
    reference_audio.write_bytes(WAV_BYTES)
    try:
        monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
        monkeypatch.setenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{server.server_port}/tts")
        monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference_audio))
        client = TestClient(create_app(database_path_override=tmp_path / "voice-unrelated.db", demo_mode_override="offline"))

        response = client.get("/api/voice/status")

        assert response.json()["data"] == {"enabled": False, "configured": True}
    finally:
        _TTSHandler.api_paths = {"/tts": {"post": {"operationId": "tts"}}}
        server.shutdown()
        thread.join(timeout=2)


def test_voice_synthesis_proxies_audio_and_reuses_cached_text(tmp_path, monkeypatch):
    server, thread = _tts_server()
    reference_audio = tmp_path / "reference.wav"
    reference_audio.write_bytes(WAV_BYTES)
    try:
        monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
        monkeypatch.setenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{server.server_port}/tts")
        monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference_audio))
        monkeypatch.setenv("WANDERER_TTS_PROMPT_TEXT", "可别让我失望。")
        monkeypatch.setenv("WANDERER_TTS_CACHE_DIR", str(tmp_path / "voice-cache"))
        client = TestClient(create_app(database_path_override=tmp_path / "voice.db", demo_mode_override="offline"))

        first = client.post("/api/voice/synthesize", json={"text": "风从身侧掠过。"})
        second = client.post("/api/voice/synthesize", json={"text": "风从身侧掠过。"})

        assert first.status_code == 200
        assert first.headers["content-type"] == "audio/wav"
        assert first.content == WAV_BYTES
        assert second.content == WAV_BYTES
        assert len(_TTSHandler.requests) == 1
        assert _TTSHandler.requests[0]["text"] == "风从身侧掠过。"
        assert _TTSHandler.requests[0]["prompt_lang"] == "zh"
        assert _TTSHandler.requests[0]["ref_audio_path"] == str(reference_audio)
        assert _TTSHandler.requests[0]["top_k"] == 5
        assert _TTSHandler.requests[0]["top_p"] == 0.8
        assert _TTSHandler.requests[0]["temperature"] == 0.7
        assert _TTSHandler.requests[0]["speed_factor"] == 0.9
        assert _TTSHandler.requests[0]["seed"] == 1234
        assert _TTSHandler.requests[0]["parallel_infer"] is False
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_voice_cache_key_changes_when_articulation_settings_change(tmp_path, monkeypatch):
    from backend.app.voice import _cache_path

    monkeypatch.setenv("WANDERER_TTS_CACHE_DIR", str(tmp_path / "voice-cache"))
    monkeypatch.setenv("WANDERER_TTS_SPEED_FACTOR", "0.9")
    first_path = _cache_path("请把这句话说清楚。")
    monkeypatch.setenv("WANDERER_TTS_SPEED_FACTOR", "0.85")

    second_path = _cache_path("请把这句话说清楚。")

    assert first_path != second_path


def test_voice_stream_proxies_fragmented_audio_and_requests_quality_preserving_fragment_mode(tmp_path, monkeypatch):
    server, thread = _tts_server()
    reference_audio = tmp_path / "reference.wav"
    reference_audio.write_bytes(WAV_BYTES)
    try:
        monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
        monkeypatch.setenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{server.server_port}/tts")
        monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference_audio))
        monkeypatch.setenv("WANDERER_TTS_CACHE_DIR", str(tmp_path / "voice-cache"))
        client = TestClient(create_app(database_path_override=tmp_path / "voice-stream.db", demo_mode_override="offline"))

        response = client.get("/api/voice/stream", params={"text": "先播放第一段，再继续后面的回复。"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.content == WAV_BYTES
        assert len(_TTSHandler.requests) == 1
        assert _TTSHandler.requests[0]["streaming_mode"] == 1
        assert _TTSHandler.requests[0]["parallel_infer"] is False
        assert _TTSHandler.requests[0]["speed_factor"] == 0.9
        assert _TTSHandler.requests[0]["top_k"] == 5
        assert _TTSHandler.requests[0]["top_p"] == 0.8
        assert _TTSHandler.requests[0]["temperature"] == 0.7
        assert _TTSHandler.requests[0]["seed"] == 1234
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_different_streamed_voice_texts_can_generate_in_parallel(tmp_path, monkeypatch):
    reference_audio = tmp_path / "reference.wav"
    reference_audio.write_bytes(WAV_BYTES)
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference_audio))
    monkeypatch.setenv("WANDERER_TTS_CACHE_DIR", str(tmp_path / "voice-cache"))
    active = 0
    max_active = 0
    state_lock = threading.Lock()

    class FakeResponse:
        headers = {"content-type": "audio/wav"}

        def __enter__(self):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            return self

        def __exit__(self, *_args):
            nonlocal active
            with state_lock:
                active -= 1
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            time.sleep(0.05)
            yield WAV_BYTES

    monkeypatch.setattr("backend.app.voice.httpx.stream", lambda *args, **kwargs: FakeResponse())

    def generate(text):
        return b"".join(stream_voice(text))

    first = threading.Thread(target=generate, args=("第一段。",))
    second = threading.Thread(target=generate, args=("第二段。",))
    first.start()
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert max_active == 2


def test_voice_stream_accepts_gpt_sovits_zero_length_header_with_appended_pcm(tmp_path, monkeypatch):
    server, thread = _tts_server()
    reference_audio = tmp_path / "reference.wav"
    reference_audio.write_bytes(WAV_BYTES)
    original_audio = _TTSHandler.audio_bytes
    # GPT-SoVITS writes a zero-frame WAV header for the first stream chunk,
    # then appends raw PCM fragments. The completed response must still be
    # accepted and promoted to the cache.
    _TTSHandler.audio_bytes = _wav_bytes() + WAV_BYTES[44:]
    try:
        monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
        monkeypatch.setenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{server.server_port}/tts")
        monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference_audio))
        cache_dir = tmp_path / "voice-cache"
        monkeypatch.setenv("WANDERER_TTS_CACHE_DIR", str(cache_dir))
        client = TestClient(create_app(database_path_override=tmp_path / "voice-stream-header.db", demo_mode_override="offline"))

        response = client.get("/api/voice/stream", params={"text": "流式响应的后半段。"})

        assert response.status_code == 200
        assert response.content == _TTSHandler.audio_bytes
        assert list(cache_dir.glob("*.wav"))
    finally:
        _TTSHandler.audio_bytes = original_audio
        server.shutdown()
        thread.join(timeout=2)


def test_voice_provider_failure_returns_safe_public_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_API_URL", "http://127.0.0.1:1/tts")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", "C:/voice/reference.wav")
    monkeypatch.setenv("WANDERER_TTS_CACHE_DIR", str(tmp_path / "voice-cache"))
    client = TestClient(create_app(database_path_override=tmp_path / "voice-error.db", demo_mode_override="offline"))

    response = client.post("/api/voice/synthesize", json={"text": "听见了吗？"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VOICE_UNAVAILABLE"
    assert "127.0.0.1:1" not in response.text


def test_voice_synthesis_rejects_a_silent_audio_provider_response(tmp_path, monkeypatch):
    server, thread = _tts_server()
    silent_audio = _wav_bytes(0, 0, 0, 0)
    _TTSHandler.audio_bytes = silent_audio
    try:
        monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
        monkeypatch.setenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{server.server_port}/tts")
        monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", "C:/voice/reference.wav")
        monkeypatch.setenv("WANDERER_TTS_CACHE_DIR", str(tmp_path / "voice-cache"))
        client = TestClient(create_app(database_path_override=tmp_path / "voice-silent.db", demo_mode_override="offline"))

        response = client.post("/api/voice/synthesize", json={"text": "静音不能被播放。"})

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "VOICE_UNAVAILABLE"
        assert "127.0.0.1" not in response.text
    finally:
        _TTSHandler.audio_bytes = WAV_BYTES
        server.shutdown()
        thread.join(timeout=2)
