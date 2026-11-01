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
import os
import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.voice import stream_voice


def _placeholder_install(root):
    for relative in ("api_v2.py", "runtime/python.exe", "GPT_weights_v2Pro/流浪者-e15.ckpt", "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()


@pytest.fixture(autouse=True)
def isolated_voice_environment(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("WANDERER_TTS_") or name == "GPT_SOVITS_ROOT":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    monkeypatch.setenv("TMP", str(tmp_path / "temp"))
    monkeypatch.setenv("WANDERER_TTS_SESSION_FILE", str(tmp_path / "session.json"))
    _placeholder_install(tmp_path)
    monkeypatch.setenv("GPT_SOVITS_ROOT", str(tmp_path))
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")


def _load_launcher(*, load_project_env=False):
    path = Path(__file__).resolve().parents[1] / "scripts" / "start_gpt_sovits.py"
    spec = importlib.util.spec_from_file_location("wanderer_gpt_sovits_launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Launcher tests never load the real project's private environment file.
    if not load_project_env:
        module._load_game_env = lambda root: None
    return module


def test_tts_config_uses_existing_character_checkpoint_and_cpu_compatible_v2pro(tmp_path):
    launcher = _load_launcher()
    root = tmp_path

    config = launcher.build_tts_config(root, "cpu")

    assert config["custom"]["device"] == "cpu"
    assert config["custom"]["version"] == "v2Pro"
    assert config["custom"]["is_half"] is False
    assert config["custom"]["t2s_weights_path"] == str(root / "GPT_weights_v2Pro" / "流浪者-e15.ckpt")
    assert config["custom"]["vits_weights_path"] == str(root / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2Pro.pth")


def test_default_voice_reference_uses_a_known_training_cut_with_its_transcript(tmp_path, monkeypatch):
    launcher = _load_launcher()
    monkeypatch.delenv("GPT_SOVITS_ROOT")
    root = tmp_path / "Desktop" / "GPT-SoVITS-v2pro-20250604"
    _placeholder_install(root)
    reference = root / "logs" / "wanderer" / "5-wav32k" / "6.1流浪者全语音无音效无背景音乐（自用）.mp3_0000716160_0000856960.wav"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(WAV_BYTES)
    monkeypatch.delenv("WANDERER_TTS_REFERENCE_AUDIO", raising=False)
    monkeypatch.delenv("WANDERER_TTS_PROMPT_TEXT", raising=False)

    settings = launcher.voice_config(root, "cpu")

    assert settings["reference_audio"] == reference.resolve()
    assert settings["prompt_text"] == "可别让我失望.这世上没有纯粹的自由."


@pytest.mark.parametrize("missing, variable, code", [
    ("api_v2.py", "GPT_SOVITS_ROOT", "TTS_ROOT_MISSING"),
    ("GPT_weights_v2Pro/流浪者-e15.ckpt", "WANDERER_TTS_GPT_WEIGHTS", "TTS_WEIGHTS_MISSING"),
    ("reference.wav", "WANDERER_TTS_REFERENCE_AUDIO", "TTS_REFERENCE_AUDIO_MISSING"),
])
def test_launcher_missing_assets_print_actionable_value_free_diagnostics(tmp_path, monkeypatch, capsys, missing, variable, code):
    launcher = _load_launcher()
    reference = tmp_path / "reference.wav"
    reference.touch()
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))
    (tmp_path / missing).unlink()

    assert launcher.main([]) == 1

    output = capsys.readouterr().err
    assert variable in output
    assert code in output
    assert str(tmp_path) not in output
    assert "another directory" not in output


def test_custom_root_requires_explicit_reference_even_when_default_cut_exists(tmp_path, monkeypatch):
    launcher = _load_launcher()
    default_cut = tmp_path / launcher.DEFAULT_VOICE_REFERENCE
    default_cut.parent.mkdir(parents=True)
    default_cut.touch()
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")

    with pytest.raises(ValueError) as error:
        launcher.voice_config(tmp_path, "cpu")

    assert error.value.diagnostic.code == "TTS_REFERENCE_AUDIO_MISSING"


def test_launcher_uses_explicit_chinese_root_and_relative_weight_overrides(tmp_path, monkeypatch):
    launcher = _load_launcher()
    root = tmp_path / "语音 安装"
    _placeholder_install(root)
    for name in ("自定义.ckpt", "自定义.pth", "参考.wav"):
        (root / name).touch()
    (root / "GPT_weights_v2Pro/流浪者-e15.ckpt").unlink()
    monkeypatch.setenv("GPT_SOVITS_ROOT", str(root))
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_GPT_WEIGHTS", "自定义.ckpt")
    monkeypatch.setenv("WANDERER_TTS_SOVITS_WEIGHTS", "自定义.pth")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(root / "参考.wav"))

    assert launcher.resolve_root() == root.resolve()
    settings = launcher.voice_config(root, "cpu")
    assert settings["config"]["custom"]["t2s_weights_path"] == str(root / "自定义.ckpt")
    assert settings["reference_audio"] == root / "参考.wav"


def test_relative_install_root_writes_absolute_weight_paths(tmp_path, monkeypatch):
    launcher = _load_launcher()
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "relative-install"
    _placeholder_install(root)
    reference = root / "reference.wav"
    reference.touch()
    monkeypatch.setenv("GPT_SOVITS_ROOT", "relative-install")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))

    config = launcher.voice_config(root, "cpu")["config"]["custom"]

    assert config["t2s_weights_path"] == str(root / "GPT_weights_v2Pro" / "流浪者-e15.ckpt")
    assert config["vits_weights_path"] == str(root / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2Pro.pth")


def test_windows_defaults_reuse_ready_requested_local_api_without_spawning(tmp_path, monkeypatch):
    from backend.app.core import voice_config
    launcher = _load_launcher()
    monkeypatch.setattr(voice_config.platform, "system", lambda: "Windows")
    monkeypatch.delenv("GPT_SOVITS_ROOT")
    monkeypatch.delenv("WANDERER_TTS_ENABLED")
    root = tmp_path / "Desktop" / "GPT-SoVITS-v2pro-20250604"
    _placeholder_install(root)
    reference = root / launcher.DEFAULT_VOICE_REFERENCE
    reference.parent.mkdir(parents=True)
    reference.touch()
    server, thread = _tts_server()
    monkeypatch.setenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{server.server_port}/tts")
    monkeypatch.setenv("WANDERER_TTS_DEVICE", "cpu")
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: pytest.fail("ready API must be reused"))
    state_file = tmp_path / "session.json"
    try:
        assert launcher.ensure_tts_server(state_file) is True
        assert json.loads(state_file.read_text()) == {"owns_server": False, "pid": None, "port": server.server_port}
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.parametrize("url", ["http://127.0.0.1:bad/tts", "http://localhost:0/tts", "https://remote.example/tts", "http://user:secret@127.0.0.1/tts"])
def test_launcher_invalid_local_endpoint_names_variable_without_value(monkeypatch, capsys, url):
    launcher = _load_launcher()
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_API_URL", url)
    assert launcher.main([]) == 1
    output = capsys.readouterr().err
    assert "WANDERER_TTS_API_URL" in output
    assert "TTS_API_INVALID" in output
    assert url not in output
    assert "secret" not in output


@pytest.mark.parametrize("paths", [{"/tts": {}}, {"/health": {"get": {}}}, []])
def test_launcher_rejects_unrelated_or_malformed_openapi(paths):
    launcher = _load_launcher()
    server, thread = _tts_server()
    _TTSHandler.api_paths = paths
    try:
        assert launcher._is_ready("127.0.0.1", server.server_port) is False
    finally:
        server.shutdown()
        thread.join(timeout=2)
        _TTSHandler.api_paths = {"/tts": {"post": {"operationId": "tts"}}}


def test_launcher_does_not_accept_redirect_to_another_api():
    launcher = _load_launcher()
    destination, destination_thread = _tts_server()
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/openapi.json")
            self.end_headers()
        def log_message(self, *_args):
            pass
    source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    try:
        assert launcher._is_ready("127.0.0.1", source.server_port) is False
    finally:
        source.shutdown()
        source_thread.join(timeout=2)
        destination.shutdown()
        destination_thread.join(timeout=2)


def test_voice_config_rejects_root_other_than_the_configured_root(tmp_path, monkeypatch):
    launcher = _load_launcher()
    reference = tmp_path / "reference.wav"
    reference.touch()
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))
    with pytest.raises(ValueError) as error:
        launcher.voice_config(tmp_path / "another-install", "cpu")
    assert error.value.diagnostic.code == "TTS_ROOT_MISSING"


def test_launcher_explicit_false_skips_all_runtime_checks(monkeypatch, capsys):
    launcher = _load_launcher()
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "false")
    monkeypatch.setattr(launcher, "resolve_root", lambda: pytest.fail("disabled voice must not probe runtime"))
    assert launcher.main([]) == 1
    assert "WANDERER_TTS_ENABLED" in capsys.readouterr().err


def test_launcher_loads_only_named_project_env_and_preserves_explicit_values(tmp_path, monkeypatch):
    launcher = _load_launcher(load_project_env=True)
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / ".env").write_text("WANDERER_TTS_PROMPT_TEXT=parent must be ignored\n", encoding="utf-8")
    (project / ".env").write_text("WANDERER_TTS_DEVICE=cpu\nWANDERER_TTS_PROMPT_TEXT=项目提示\n", encoding="utf-8")
    monkeypatch.setenv("WANDERER_TTS_DEVICE", "cuda")
    monkeypatch.setenv("WANDERER_TTS_PROMPT_TEXT", "placeholder")
    monkeypatch.delenv("WANDERER_TTS_PROMPT_TEXT", raising=False)
    launcher._load_game_env(project)
    assert os.environ["WANDERER_TTS_DEVICE"] == "cuda"
    assert os.environ["WANDERER_TTS_PROMPT_TEXT"] == "项目提示"
    monkeypatch.delenv("WANDERER_TTS_PROMPT_TEXT")
    (project / ".env").unlink()
    launcher._load_game_env(project)
    assert "WANDERER_TTS_PROMPT_TEXT" not in os.environ


def test_stop_cli_uses_project_env_ownership_file(tmp_path, monkeypatch):
    launcher = _load_launcher(load_project_env=True)
    project = tmp_path / "project"
    project.mkdir()
    state_file = project / "session.json"
    state_file.write_text('{"owns_server": false, "pid": null, "port": 9880}', encoding="utf-8")
    (project / ".env").write_text(f'WANDERER_TTS_SESSION_FILE="{state_file}"\n', encoding="utf-8")
    monkeypatch.setattr(launcher, "__file__", str(project / "scripts/start_gpt_sovits.py"))
    monkeypatch.setenv("WANDERER_TTS_SESSION_FILE", "placeholder")
    monkeypatch.delenv("WANDERER_TTS_SESSION_FILE")
    monkeypatch.setattr(launcher, "_terminate_process", lambda pid: pytest.fail("reused API must stay alive"))
    assert launcher.main(["--stop"]) == 0
    assert not state_file.exists()


def test_voice_config_invalid_device_has_variable_diagnostic(tmp_path, monkeypatch):
    launcher = _load_launcher()
    reference = tmp_path / "reference.wav"
    reference.touch()
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))
    with pytest.raises(ValueError) as error:
        launcher.voice_config(tmp_path, "invalid")
    assert error.value.diagnostic.variables == ("WANDERER_TTS_DEVICE",)


def test_launcher_invalid_timeout_is_diagnosed_before_spawning(tmp_path, monkeypatch, capsys):
    launcher = _load_launcher()
    reference = tmp_path / "reference.wav"
    reference.touch()
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))
    monkeypatch.setenv("WANDERER_TTS_DEVICE", "cpu")
    monkeypatch.setenv("WANDERER_TTS_STARTUP_TIMEOUT", "invalid")
    monkeypatch.setattr(launcher, "_is_ready", lambda *a: False)
    monkeypatch.setattr(launcher, "tts_config_path", lambda: tmp_path / "tts.json")
    class ExitedProcess:
        pid = 12345
        def poll(self):
            return 1
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: ExitedProcess())
    state_file = tmp_path / "session.json"
    assert launcher.main(["--state-file", str(state_file)]) == 1
    assert "WANDERER_TTS_STARTUP_TIMEOUT" in capsys.readouterr().err
    assert not state_file.exists()


@pytest.mark.parametrize("timeout", ["", "  "])
def test_launcher_blank_startup_timeout_uses_documented_default(tmp_path, monkeypatch, timeout):
    launcher = _load_launcher()
    reference = tmp_path / "reference.wav"
    reference.touch()
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))
    monkeypatch.setenv("WANDERER_TTS_DEVICE", "cpu")
    monkeypatch.setenv("WANDERER_TTS_STARTUP_TIMEOUT", timeout)
    monkeypatch.setattr(launcher, "_is_ready", lambda *args: False)
    monkeypatch.setattr(launcher, "tts_config_path", lambda: tmp_path / "tts.json")
    times = iter([0, 239, 240])
    monkeypatch.setattr(launcher, "monotonic", lambda: next(times))
    sleeps = []
    monkeypatch.setattr(launcher, "sleep", sleeps.append)
    class RunningProcess:
        pid = 12345
        def poll(self):
            return None
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: RunningProcess())
    stopped = []
    monkeypatch.setattr(launcher, "stop_tts_server", stopped.append)
    state = tmp_path / "session.json"
    with pytest.raises(launcher.VoiceSetupError) as error:
        launcher.ensure_tts_server(state)
    assert error.value.diagnostic.code == "TTS_API_UNREACHABLE"
    assert sleeps == [1]
    assert stopped == [state]


def test_launcher_exited_process_prints_api_variable(tmp_path, monkeypatch, capsys):
    launcher = _load_launcher()
    reference = tmp_path / "reference.wav"
    reference.touch()
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_DEVICE", "cpu")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))
    monkeypatch.setattr(launcher, "tts_config_path", lambda: tmp_path / "tts.json")
    monkeypatch.setattr(launcher, "_is_ready", lambda *a: False)
    class ExitedProcess:
        pid = 12345
        def poll(self):
            return 1
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: ExitedProcess())
    assert launcher.main(["--state-file", str(tmp_path / "session.json")]) == 1
    output = capsys.readouterr().err
    assert "TTS_API_UNREACHABLE" in output
    assert "WANDERER_TTS_API_URL" in output
    assert str(tmp_path) not in output


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

    class FakeProcess:
        next_pid = 2000

        def __init__(self, exited):
            self.pid = FakeProcess.next_pid
            FakeProcess.next_pid += 1
            self.exited = exited

        def poll(self):
            return 1 if self.exited else None

    processes = iter([FakeProcess(True), FakeProcess(False)])
    def spawn(command, **kwargs):
        devices.append(json.loads(config_path.read_text(encoding="utf-8"))["custom"]["device"])
        assert kwargs["cwd"] == tmp_path
        return next(processes)

    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_DEVICE", "auto")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference))
    monkeypatch.setattr(launcher, "_load_game_env", lambda root: None)
    monkeypatch.setattr(launcher, "resolve_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime_has_usable_cuda", lambda root: True)
    monkeypatch.setattr(launcher, "tts_endpoint", lambda: ("127.0.0.1", 9880))
    monkeypatch.setattr(launcher, "tts_config_path", lambda: config_path)
    monkeypatch.setattr(launcher, "_is_ready", lambda host, port: readiness_checks.append(True) or len(readiness_checks) > 1)
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher, "sleep", lambda seconds: None)

    assert launcher.ensure_tts_server(session_file) is True
    assert devices == ["cuda", "cpu"]


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
    from backend.app.core import voice_config

    monkeypatch.setattr(voice_config.platform, "system", lambda: "Linux")
    monkeypatch.delenv("WANDERER_TTS_ENABLED", raising=False)
    client = TestClient(create_app(database_path_override=tmp_path / "voice-status.db", demo_mode_override="offline"))

    response = client.get("/api/voice/status")

    assert response.status_code == 200
    status = response.json()["data"]
    assert status["enabled"] is False
    assert status["configured"] is False
    assert status["mode"] == "local"
    assert status["diagnostics"][0]["code"] == "TTS_NOT_ENABLED"
    assert status["compatibility_voice_available"] is True


def test_voice_status_enables_only_after_the_local_tts_api_is_ready(tmp_path, monkeypatch):
    server, thread = _tts_server()
    reference_audio = tmp_path / "reference.wav"
    reference_audio.write_bytes(WAV_BYTES)
    for relative in ("api_v2.py", "runtime/python.exe", "GPT_weights_v2Pro/流浪者-e15.ckpt", "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    monkeypatch.setenv("GPT_SOVITS_ROOT", str(tmp_path))
    try:
        monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
        monkeypatch.setenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{server.server_port}/tts")
        monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference_audio))
        client = TestClient(create_app(database_path_override=tmp_path / "voice-ready.db", demo_mode_override="offline"))

        response = client.get("/api/voice/status")

        assert response.status_code == 200
        assert response.json()["data"] == {
            "enabled": True, "configured": True, "mode": "local",
            "diagnostics": [], "compatibility_voice_available": True,
        }
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_voice_status_rejects_an_unrelated_local_openapi_server(tmp_path, monkeypatch):
    server, thread = _tts_server()
    _TTSHandler.api_paths = {"/health": {"get": {"operationId": "health"}}}
    reference_audio = tmp_path / "reference.wav"
    reference_audio.write_bytes(WAV_BYTES)
    for relative in ("api_v2.py", "runtime/python.exe", "GPT_weights_v2Pro/流浪者-e15.ckpt", "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    monkeypatch.setenv("GPT_SOVITS_ROOT", str(tmp_path))
    try:
        monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
        monkeypatch.setenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{server.server_port}/tts")
        monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(reference_audio))
        client = TestClient(create_app(database_path_override=tmp_path / "voice-unrelated.db", demo_mode_override="offline"))

        response = client.get("/api/voice/status")

        status = response.json()["data"]
        assert status["enabled"] is False
        assert status["configured"] is True
        assert status["mode"] == "local"
        assert status["diagnostics"][0]["code"] == "TTS_API_UNREACHABLE"
        assert status["compatibility_voice_available"] is True
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
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(tmp_path / "reference.wav"))
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
        monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(tmp_path / "reference.wav"))
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
