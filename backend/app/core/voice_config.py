"""Shared, explicit voice settings and public, value-free diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from ipaddress import ip_address
import os
from pathlib import Path
import platform
import re
from urllib.parse import urlsplit

import httpx


DEFAULT_API_URL = "http://127.0.0.1:9880/tts"
DEFAULT_VOICE_REFERENCE = Path("logs/wanderer/5-wav32k/6.1流浪者全语音无音效无背景音乐（自用）.mp3_0000716160_0000856960.wav")
DEFAULT_VOICE_PROMPT = "可别让我失望.这世上没有纯粹的自由."
DEFAULT_GPT_WEIGHTS = Path("GPT_weights_v2Pro/流浪者-e15.ckpt")
DEFAULT_SOVITS_WEIGHTS = Path("GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth")


@dataclass(frozen=True)
class VoiceDiagnostic:
    code: str
    message: str
    variables: tuple[str, ...]
    check: str
    action: str

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["variables"] = list(self.variables)
        return result


def validate_api_url(value: str, *, mode: str) -> str:
    """Validate deployment HTTPS separately from the local loopback endpoint."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = httpx.URL(value).host.rstrip(".").lower()
        remote_host = bool(host) and host != "localhost" and not host.endswith((".localhost", ".local"))
        try:
            remote_host = ip_address(host).is_global
        except ValueError:
            # Legacy resolver forms can mix hexadecimal, octal and shortened
            # decimal components. Only canonical IP literals reach is_global.
            numeric_alias = all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", part) for part in host.split("."))
            remote_host = remote_host and "." in host and not numeric_alias
        valid_transport = (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            if mode == "local" else mode == "remote" and parsed.scheme == "https" and remote_host
        )
        if (
            not valid_transport or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/", "/tts"}
            or port == 0
        ):
            raise ValueError
        # Match the parser used by the HTTP transport before making requests.
        httpx.URL(value)
    except (ValueError, httpx.InvalidURL):
        raise ValueError("Configure a loopback HTTP or deployment HTTPS TTS endpoint") from None
    return f"{parsed.scheme}://{parsed.netloc}/tts"


def _is_accessible_file(path: Path | None) -> bool:
    """Treat expected filesystem failures as configuration failures, without details."""
    try:
        return path is not None and path.is_file()
    except OSError:
        return False


@dataclass(frozen=True)
class VoiceSettings:
    enabled: bool
    mode: str
    api_url: str
    root: Path | None
    gpt_weights: Path | None
    sovits_weights: Path | None
    reference_audio: Path | None
    prompt_text: str

    @classmethod
    def from_env(cls) -> VoiceSettings:
        api_url = os.getenv("WANDERER_TTS_API_URL", DEFAULT_API_URL).strip()
        # A non-loopback deployment is never inferred from the operating system.
        try:
            parsed = urlsplit(api_url)
            mode = "local" if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"} else "remote"
        except ValueError:
            raise ValueError("Invalid TTS endpoint configuration") from None
        api_url = validate_api_url(api_url, mode=mode)
        flag = os.getenv("WANDERER_TTS_ENABLED")
        enabled = (
            flag.strip().lower() in {"1", "true", "yes", "on"}
            if flag is not None else mode == "local" and platform.system() == "Windows"
        )
        root_value = os.getenv("GPT_SOVITS_ROOT", "").strip()
        root = None
        if mode == "local" and enabled:
            if root_value:
                root = Path(root_value).expanduser()
            elif platform.system() == "Windows":
                root = Path.home() / "Desktop" / "GPT-SoVITS-v2pro-20250604"

        def configured_path(name: str, default: Path | None) -> Path | None:
            value = os.getenv(name, "").strip()
            path = Path(value) if value else default
            if path is not None and mode == "local":
                path = path.expanduser()
            if path is not None and root is not None and not path.is_absolute():
                path = root / path
            return path

        return cls(
            enabled=enabled, mode=mode, api_url=api_url, root=root,
            gpt_weights=configured_path("WANDERER_TTS_GPT_WEIGHTS", DEFAULT_GPT_WEIGHTS if root else None) if mode == "local" else None,
            sovits_weights=configured_path("WANDERER_TTS_SOVITS_WEIGHTS", DEFAULT_SOVITS_WEIGHTS if root else None) if mode == "local" else None,
            # Custom roots require an explicit reference; never search for alternatives.
            reference_audio=configured_path("WANDERER_TTS_REFERENCE_AUDIO", DEFAULT_VOICE_REFERENCE if root and not root_value else None),
            prompt_text=os.getenv("WANDERER_TTS_PROMPT_TEXT", DEFAULT_VOICE_PROMPT if mode == "local" else "").strip(),
        )

    def diagnostics(self) -> list[VoiceDiagnostic]:
        if not self.enabled:
            return [VoiceDiagnostic("TTS_NOT_ENABLED", "语音未启用。", ("WANDERER_TTS_ENABLED",), "enabled", "设置 WANDERER_TTS_ENABLED=true 后检查语音配置。")]
        if self.mode == "remote":
            diagnostics = []
            if not os.getenv("WANDERER_TTS_API_TOKEN", "").strip():
                diagnostics.append(VoiceDiagnostic(
                    "TTS_API_TOKEN_MISSING", "远程语音服务令牌未配置。",
                    ("WANDERER_TTS_API_TOKEN",), "remote_credentials",
                    "在网站部署平台的私有环境变量中设置 WANDERER_TTS_API_TOKEN；不要放入前端或代码仓库。",
                ))
            if not os.getenv("WANDERER_TTS_REFERENCE_AUDIO", "").strip():
                diagnostics.append(VoiceDiagnostic(
                    "TTS_REFERENCE_AUDIO_MISSING", "远程语音参考音频未配置。",
                    ("WANDERER_TTS_REFERENCE_AUDIO",), "remote_reference_audio",
                    "在独立语音服务上配置参考音频，并通过 WANDERER_TTS_REFERENCE_AUDIO 提供服务端识别值。",
                ))
            if not self.prompt_text:
                diagnostics.append(VoiceDiagnostic(
                    "TTS_PROMPT_TEXT_MISSING", "远程语音提示文本未配置。",
                    ("WANDERER_TTS_PROMPT_TEXT",), "remote_prompt_text",
                    "在独立语音服务上配置提示文本，并设置 WANDERER_TTS_PROMPT_TEXT。",
                ))
            return diagnostics
        diagnostics = []
        if not _is_accessible_file(self.reference_audio):
            diagnostics.append(VoiceDiagnostic("TTS_REFERENCE_AUDIO_MISSING", "参考音频未配置、不存在或无法访问。", ("WANDERER_TTS_REFERENCE_AUDIO",), "reference_audio", "设置 WANDERER_TTS_REFERENCE_AUDIO 为有效的参考音频文件，并检查访问权限。"))
        if self.root is None or not all(_is_accessible_file(self.root / name) for name in ("api_v2.py", "runtime/python.exe")):
            diagnostics.append(VoiceDiagnostic("TTS_ROOT_MISSING", "本机语音运行环境不完整或无法访问。", ("GPT_SOVITS_ROOT",), "runtime", "设置 GPT_SOVITS_ROOT，确认包含 api_v2.py 和 bundled runtime，并检查访问权限。"))
        missing_weights = tuple(
            variable for variable, path in (
                ("WANDERER_TTS_GPT_WEIGHTS", self.gpt_weights),
                ("WANDERER_TTS_SOVITS_WEIGHTS", self.sovits_weights),
            ) if not _is_accessible_file(path)
        )
        if missing_weights:
            diagnostics.append(VoiceDiagnostic("TTS_WEIGHTS_MISSING", "语音权重未配置、不存在或无法访问。", missing_weights, "weights", "通过列出的环境变量指定有效权重文件，并检查访问权限。"))
        return diagnostics
