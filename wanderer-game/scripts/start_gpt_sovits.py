"""Start the user's local GPT-SoVITS v2Pro server when voice is enabled."""

from __future__ import annotations

import json
import os
from pathlib import Path
import argparse
import subprocess
import sys
import tempfile
from time import monotonic, sleep
from urllib.parse import urlsplit

import httpx


# Direct script execution puts scripts/, rather than the project, on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.core.voice_config import (  # noqa: E402
    DEFAULT_VOICE_REFERENCE, VoiceDiagnostic, VoiceSettings, validate_api_url,
)


class VoiceSetupError(ValueError):
    """Carry an actionable diagnostic without exposing configured values."""

    def __init__(self, diagnostic: VoiceDiagnostic):
        self.diagnostic = diagnostic
        super().__init__(f"{diagnostic.code}: {diagnostic.message} {diagnostic.action}")


def _settings() -> VoiceSettings:
    try:
        return VoiceSettings.from_env()
    except ValueError:
        raise VoiceSetupError(VoiceDiagnostic(
            "TTS_API_INVALID", "语音 API 地址无效。", ("WANDERER_TTS_API_URL",),
            "api_url", "设置 WANDERER_TTS_API_URL 为有效的本机 loopback HTTP /tts 地址。",
        )) from None


def _require_settings(settings: VoiceSettings, checks: set[str]) -> None:
    for diagnostic in settings.diagnostics():
        if diagnostic.check in checks:
            raise VoiceSetupError(diagnostic)


def _api_unreachable() -> VoiceSetupError:
    return VoiceSetupError(VoiceDiagnostic(
        "TTS_API_UNREACHABLE", "GPT-SoVITS API 未能就绪。", ("WANDERER_TTS_API_URL",),
        "api_ready", "检查 WANDERER_TTS_API_URL 的端口、/openapi.json 的 POST /tts 接口及语音运行环境后重试。",
    ))


def _runtime_has_usable_cuda(root: Path) -> bool:
    """Return whether the bundled runtime can execute CUDA kernels on this GPU."""
    probe = (
        "import torch; "
        "available = torch.cuda.is_available(); "
        "device = torch.device('cuda') if available else None; "
        "left = torch.ones(1, device=device) if device else None; "
        "right = torch.ones(1, device=device) if device else None; "
        "result = left + right if device else None; "
        "result.item() if device else None; "
        "torch.cuda.synchronize() if device else None; "
        "print('1' if available else '0')"
    )
    try:
        result = subprocess.run(
            [str(root / "runtime" / "python.exe"), "-c", probe],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip().endswith("1")


def build_tts_config(root: Path, device: str = "cpu") -> dict:
    root = Path(root).expanduser().resolve()
    settings = _settings()
    if device not in {"cpu", "cuda"}:
        raise VoiceSetupError(VoiceDiagnostic(
            "TTS_DEVICE_INVALID", "语音计算设备无效。", ("WANDERER_TTS_DEVICE",),
            "device", "设置 WANDERER_TTS_DEVICE 为 auto、cpu 或 cuda。",
        ))

    return {
        "custom": {
            "device": device,
            "is_half": device == "cuda",
            "version": "v2Pro",
            "t2s_weights_path": str(settings.gpt_weights.resolve()),
            "vits_weights_path": str(settings.sovits_weights.resolve()),
            "bert_base_path": str(root / "GPT_SoVITS" / "pretrained_models" / "chinese-roberta-wwm-ext-large"),
            "cnhuhbert_base_path": str(root / "GPT_SoVITS" / "pretrained_models" / "chinese-hubert-base"),
        }
    }


def resolve_root() -> Path:
    settings = _settings()
    _require_settings(settings, {"enabled", "runtime", "weights"})
    return settings.root.resolve()


def tts_endpoint() -> tuple[str, int]:
    try:
        parsed = urlsplit(validate_api_url(_settings().api_url, mode="local"))
    except ValueError:
        raise VoiceSetupError(VoiceDiagnostic(
            "TTS_API_INVALID", "本机启动器需要 loopback HTTP API 地址。", ("WANDERER_TTS_API_URL",),
            "api_url", "设置 WANDERER_TTS_API_URL 为本机 loopback HTTP /tts 地址。",
        )) from None
    return parsed.hostname, parsed.port or 80


def voice_config(root: Path, device: str | None = None) -> dict:
    voice_settings = _settings()
    root = Path(root).expanduser().resolve()
    if voice_settings.root is None or root != voice_settings.root.resolve():
        raise VoiceSetupError(VoiceDiagnostic(
            "TTS_ROOT_MISSING", "启动目录与明确配置不一致。", ("GPT_SOVITS_ROOT",),
            "runtime", "设置 GPT_SOVITS_ROOT 为要使用的唯一安装目录。",
        ))
    _require_settings(voice_settings, {"enabled", "runtime", "weights", "reference_audio"})
    selected_device = device or os.getenv("WANDERER_TTS_DEVICE", "").strip().lower() or "auto"
    if selected_device == "auto":
        selected_device = "cuda" if _runtime_has_usable_cuda(root) else "cpu"
    settings = build_tts_config(root, selected_device)
    return {
        "root": root,
        "device": settings["custom"]["device"],
        "config": settings,
        "reference_audio": voice_settings.reference_audio.resolve(),
        "prompt_text": voice_settings.prompt_text,
    }


def tts_config_path() -> Path:
    app_data = Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir()))
    return app_data / "WandererGame" / "gpt-sovits-v2pro.json"


def voice_session_path() -> Path:
    configured = os.getenv("WANDERER_TTS_SESSION_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    app_data = Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir()))
    return app_data / "WandererGame" / "voice-session.json"


def _is_ready(host: str, port: int) -> bool:
    try:
        authority = f"[{host}]" if ":" in host else host
        response = httpx.get(f"http://{authority}:{port}/openapi.json", timeout=1, follow_redirects=False, trust_env=False)
        if response.status_code != 200:
            return False
        schema = response.json()
        paths = schema.get("paths", {}) if isinstance(schema, dict) else {}
        operation = paths.get("/tts", {}) if isinstance(paths, dict) else {}
        return isinstance(operation, dict) and isinstance(operation.get("post"), dict)
    except (OSError, httpx.HTTPError, ValueError):
        return False


def _load_game_env(root: Path) -> None:
    env_file = root / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def ensure_tts_server(session_file: Path | None = None) -> bool:
    """Reuse the local GPT-SoVITS API or start the selected voice checkpoint."""
    game_root = Path(__file__).resolve().parents[1]
    _load_game_env(game_root)
    if not _settings().enabled:
        return False

    host, port = tts_endpoint()
    root = resolve_root()
    requested_device = os.getenv("WANDERER_TTS_DEVICE", "").strip().lower() or "auto"
    session_file = session_file or voice_session_path()
    _require_settings(_settings(), {"reference_audio"})
    if _is_ready(host, port):
        _write_session_state(session_file, owns_server=False, pid=None, port=port)
        return True
    settings = voice_config(root)
    try:
        startup_timeout = max(30, int(os.getenv("WANDERER_TTS_STARTUP_TIMEOUT", "").strip() or "240"))
    except ValueError:
        raise VoiceSetupError(VoiceDiagnostic(
            "TTS_STARTUP_TIMEOUT_INVALID", "语音启动等待时间无效。", ("WANDERER_TTS_STARTUP_TIMEOUT",),
            "startup_timeout", "设置 WANDERER_TTS_STARTUP_TIMEOUT 为整数秒数，默认 240 秒。",
        )) from None

    config_path = tts_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    stop_marker = _stop_marker_path(session_file)
    stop_marker.unlink(missing_ok=True)
    settings_to_try = [settings]
    if requested_device == "auto" and settings["device"] == "cuda":
        settings_to_try.append(voice_config(root, "cpu"))

    for attempt, candidate in enumerate(settings_to_try):
        temporary = config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(candidate["config"], ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(config_path)
        command = [
            str(candidate["root"] / "runtime" / "python.exe"),
            "-I",
            "api_v2.py",
            "-a",
            host,
            "-p",
            str(port),
            "-c",
            str(config_path),
        ]
        _write_session_state(session_file, owns_server=True, pid=None, port=port)
        try:
            process = subprocess.Popen(command, cwd=candidate["root"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creation_flags)
        except OSError:
            session_file.unlink(missing_ok=True)
            raise
        _write_session_state(session_file, owns_server=True, pid=process.pid, port=port)
        if stop_marker.is_file():
            _terminate_process(process.pid)
            session_file.unlink(missing_ok=True)
            stop_marker.unlink(missing_ok=True)
            return False
        deadline = monotonic() + startup_timeout
        while monotonic() < deadline:
            if stop_marker.is_file():
                _terminate_process(process.pid)
                session_file.unlink(missing_ok=True)
                stop_marker.unlink(missing_ok=True)
                return False
            if process.poll() is not None:
                session_file.unlink(missing_ok=True)
                if attempt + 1 < len(settings_to_try):
                    break
                raise _api_unreachable()
            if _is_ready(host, port):
                return True
            sleep(1)
        else:
            stop_tts_server(session_file)
            raise _api_unreachable()

    return False


def _write_session_state(path: Path, *, owns_server: bool, pid: int | None, port: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"owns_server": owns_server, "pid": pid, "port": port}), encoding="utf-8")
    temporary.replace(path)


def _stop_marker_path(session_file: Path) -> Path:
    return session_file.with_suffix(session_file.suffix + ".stop")


def _terminate_process(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass


def stop_tts_server(session_file: Path | None = None) -> None:
    session_file = session_file or voice_session_path()
    try:
        state = json.loads(session_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return

    pid = state.get("pid")
    if state.get("owns_server") is True and isinstance(pid, int) and pid > 0:
        _stop_marker_path(session_file).touch()
        _terminate_process(pid)
        session_file.unlink(missing_ok=True)
        _stop_marker_path(session_file).unlink(missing_ok=True)
    elif state.get("owns_server") is True:
        _stop_marker_path(session_file).touch()
    else:
        session_file.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start or stop the local GPT-SoVITS voice service")
    parser.add_argument("--stop", action="store_true", help="stop only the GPT-SoVITS process started for this game run")
    parser.add_argument("--state-file", type=Path, default=None, help="per-run TTS process ownership file")
    args = parser.parse_args(argv)
    if args.stop:
        if args.state_file is None:
            _load_game_env(Path(__file__).resolve().parents[1])
        stop_tts_server(args.state_file)
        return 0
    try:
        if ensure_tts_server(args.state_file):
            print("GPT-SoVITS 语音服务已就绪。")
            return 0
        diagnostics = _settings().diagnostics()
        diagnostic = diagnostics[0] if diagnostics else _api_unreachable().diagnostic
    except VoiceSetupError as exc:
        diagnostic = exc.diagnostic
    except (ValueError, OSError):
        # OS errors can contain private paths; never print raw exception values.
        diagnostic = _api_unreachable().diagnostic
    print(f"{diagnostic.code}: {diagnostic.message} [{', '.join(diagnostic.variables)}; {diagnostic.check}] {diagnostic.action} 游戏仍可使用文字对话。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
