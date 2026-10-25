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
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


DEFAULT_PORT = 9880
DEFAULT_VOICE_REFERENCE = Path("logs/wanderer/5-wav32k/6.1流浪者全语音无音效无背景音乐（自用）.mp3_0000716160_0000856960.wav")
DEFAULT_VOICE_PROMPT = "可别让我失望.这世上没有纯粹的自由."


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
    if device not in {"cpu", "cuda"}:
        raise ValueError("GPT-SoVITS device must be cpu or cuda")

    return {
        "custom": {
            "device": device,
            "is_half": device == "cuda",
            "version": "v2Pro",
            "t2s_weights_path": os.getenv("WANDERER_TTS_GPT_WEIGHTS", "").strip() or str(root / "GPT_weights_v2Pro" / "流浪者-e15.ckpt"),
            "vits_weights_path": os.getenv("WANDERER_TTS_SOVITS_WEIGHTS", "").strip() or str(root / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2Pro.pth"),
            "bert_base_path": str(root / "GPT_SoVITS" / "pretrained_models" / "chinese-roberta-wwm-ext-large"),
            "cnhuhbert_base_path": str(root / "GPT_SoVITS" / "pretrained_models" / "chinese-hubert-base"),
        }
    }


def resolve_root() -> Path:
    configured = os.getenv("GPT_SOVITS_ROOT", "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / "Desktop" / "GPT-SoVITS-v2pro-20250604"
    root = root.resolve()
    required = (
        root / "api_v2.py",
        root / "runtime" / "python.exe",
        root / "GPT_weights_v2Pro" / "流浪者-e15.ckpt",
        root / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2Pro.pth",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("GPT-SoVITS files not found: " + ", ".join(missing))
    return root


def tts_endpoint() -> tuple[str, int]:
    parsed = urlsplit(os.getenv("WANDERER_TTS_API_URL", f"http://127.0.0.1:{DEFAULT_PORT}/tts"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/", "/tts"}:
        raise ValueError("The GPT-SoVITS API must use the local HTTP server on 127.0.0.1")
    return parsed.hostname, parsed.port or DEFAULT_PORT


def voice_config(root: Path, device: str | None = None) -> dict:
    selected_device = device or os.getenv("WANDERER_TTS_DEVICE", "").strip().lower() or "auto"
    if selected_device == "auto":
        selected_device = "cuda" if _runtime_has_usable_cuda(root) else "cpu"
    settings = build_tts_config(root, selected_device)
    reference = Path(os.getenv("WANDERER_TTS_REFERENCE_AUDIO", "").strip() or root / DEFAULT_VOICE_REFERENCE)
    if not reference.is_absolute():
        reference = root / reference
    if not reference.is_file():
        raise FileNotFoundError(f"GPT-SoVITS voice reference audio not found: {reference}")
    return {
        "root": root,
        "device": settings["custom"]["device"],
        "config": settings,
        "reference_audio": reference.resolve(),
        "prompt_text": os.getenv("WANDERER_TTS_PROMPT_TEXT", DEFAULT_VOICE_PROMPT).strip(),
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
        with urlopen(f"http://{host}:{port}/openapi.json", timeout=1) as response:
            if response.status != 200:
                return False
            schema = json.loads(response.read())
            return "/tts" in schema.get("paths", {})
    except (OSError, URLError, ValueError):
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
    if _as_bool(os.getenv("WANDERER_TTS_ENABLED")) is False:
        return False

    host, port = tts_endpoint()
    root = resolve_root()
    requested_device = os.getenv("WANDERER_TTS_DEVICE", "").strip().lower() or "auto"
    settings = voice_config(root)
    session_file = session_file or voice_session_path()
    if not settings["reference_audio"].is_file():
        return False
    if _is_ready(host, port):
        _write_session_state(session_file, owns_server=False, pid=None, port=port)
        return True

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
            "127.0.0.1",
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
        deadline = monotonic() + max(30, int(os.getenv("WANDERER_TTS_STARTUP_TIMEOUT", "240")))
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
                return False
            if _is_ready(host, port):
                return True
            sleep(1)
        else:
            stop_tts_server(session_file)
            return False

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


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start or stop the local GPT-SoVITS voice service")
    parser.add_argument("--stop", action="store_true", help="stop only the GPT-SoVITS process started for this game run")
    parser.add_argument("--state-file", type=Path, default=None, help="per-run TTS process ownership file")
    args = parser.parse_args(argv)
    _load_game_env(Path(__file__).resolve().parents[1])
    if args.stop:
        stop_tts_server(args.state_file)
        return 0
    try:
        if ensure_tts_server(args.state_file):
            print("GPT-SoVITS 语音服务已就绪。")
        else:
            print("语音服务未启动；游戏仍可使用文字对话。", file=sys.stderr)
            return 1
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"GPT-SoVITS 语音服务启动失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
