"""Small GPT-SoVITS client used by the game's optional voice layer."""

from __future__ import annotations

import hashlib
import json
import os
import ipaddress
import socket
import struct
from pathlib import Path
from urllib.parse import urlsplit
import wave
from io import BytesIO
from collections.abc import Iterator
from threading import Lock
from contextlib import contextmanager
from uuid import uuid4

import httpx

from backend.app.core.voice_config import VoiceDiagnostic, VoiceSettings, validate_api_url


class VoiceUnavailableError(RuntimeError):
    """The configured TTS service cannot produce audio for this request."""


_CACHE_LOCKS: dict[Path, tuple[Lock, int]] = {}
_CACHE_LOCKS_GUARD = Lock()


@contextmanager
def _cache_lock(cache_path: Path) -> Iterator[None]:
    """Serialize identical text requests while allowing different texts to overlap."""
    with _CACHE_LOCKS_GUARD:
        lock, users = _CACHE_LOCKS.get(cache_path, (Lock(), 0))
        _CACHE_LOCKS[cache_path] = (lock, users + 1)
    try:
        with lock:
            yield
    finally:
        with _CACHE_LOCKS_GUARD:
            current_lock, users = _CACHE_LOCKS[cache_path]
            if users == 1:
                _CACHE_LOCKS.pop(cache_path, None)
            else:
                _CACHE_LOCKS[cache_path] = (current_lock, users - 1)


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def voice_enabled() -> bool:
    try:
        return VoiceSettings.from_env().enabled
    except ValueError as exc:
        raise VoiceUnavailableError("voice endpoint configuration is invalid") from exc


def _validate_api_url(value: str) -> str:
    try:
        return validate_api_url(value, mode="local")
    except ValueError as exc:
        raise VoiceUnavailableError("the local GPT-SoVITS endpoint is invalid") from exc


def _api_ready(api_url: str) -> bool:
    parsed = urlsplit(api_url)
    try:
        _guard_remote_endpoint(api_url)
        response = httpx.get(
            f"{parsed.scheme}://{parsed.netloc}/openapi.json",
            timeout=1,
            follow_redirects=False,
            trust_env=False,
        )
        if response.status_code != 200:
            return False
        schema = response.json()
        paths = schema.get("paths") if isinstance(schema, dict) else None
        endpoint = paths.get("/tts") if isinstance(paths, dict) else None
        return isinstance(endpoint, dict) and isinstance(endpoint.get("post"), dict)
    except (httpx.HTTPError, ValueError, VoiceUnavailableError):
        return False


def _guard_remote_endpoint(api_url: str) -> None:
    """Reject DNS answers that can reach local infrastructure before remote I/O."""
    settings = VoiceSettings.from_env()
    if settings.mode != "remote":
        return
    parsed = urlsplit(api_url)
    if not parsed.hostname:
        raise VoiceUnavailableError("the remote TTS service is unavailable")
    try:
        records = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise VoiceUnavailableError("the remote TTS service is unavailable") from None
    addresses = {str(record[4][0]).split("%", 1)[0] for record in records if record and record[4]}
    if not addresses:
        raise VoiceUnavailableError("the remote TTS service is unavailable")
    try:
        if any(not ipaddress.ip_address(value).is_global for value in addresses):
            raise VoiceUnavailableError("the remote TTS service is unavailable")
    except ValueError:
        raise VoiceUnavailableError("the remote TTS service is unavailable") from None


def voice_status() -> dict[str, object]:
    try:
        settings = VoiceSettings.from_env()
    except ValueError:
        diagnostic = VoiceDiagnostic("TTS_API_INVALID", "语音服务地址无效。", ("WANDERER_TTS_API_URL",), "api_url", "本机使用 loopback HTTP 地址；远程部署使用不含凭据的 HTTPS /tts 地址。")
        return {"enabled": False, "configured": False, "mode": "unconfigured", "diagnostics": [diagnostic.to_dict()], "compatibility_voice_available": True}
    diagnostics = settings.diagnostics()
    configured = settings.enabled and not diagnostics
    ready = configured and _api_ready(settings.api_url)
    if configured and not ready:
        diagnostics.append(VoiceDiagnostic("TTS_API_UNREACHABLE", "语音服务尚未就绪。", ("WANDERER_TTS_API_URL",), "api_readiness", "启动对应语音服务并检查 WANDERER_TTS_API_URL。"))
    return {
        "enabled": ready, "configured": configured, "mode": settings.mode,
        "diagnostics": [item.to_dict() for item in diagnostics],
        "compatibility_voice_available": True,
    }


def _api_url() -> str:
    try:
        return VoiceSettings.from_env().api_url
    except ValueError as exc:
        raise VoiceUnavailableError("voice endpoint configuration is invalid") from exc


def _reference_audio() -> str:
    settings = VoiceSettings.from_env()
    if settings.mode == "remote":
        if not os.getenv("WANDERER_TTS_REFERENCE_AUDIO", "").strip() or not settings.prompt_text:
            raise VoiceUnavailableError("remote voice settings are incomplete")
        # This path belongs to the independently deployed TTS host. Preserve
        # its syntax and never probe it on the web host's filesystem.
        return os.getenv("WANDERER_TTS_REFERENCE_AUDIO", "").strip()
    path = settings.reference_audio
    return str(path) if path is not None else ""


def _prompt_text() -> str:
    return VoiceSettings.from_env().prompt_text


def _timeout() -> float:
    try:
        return max(1.0, float(os.getenv("WANDERER_TTS_TIMEOUT", "120")))
    except ValueError:
        return 120.0


def _float_setting(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def _int_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def _tts_parameters() -> dict[str, object]:
    return {
        "top_k": _int_setting("WANDERER_TTS_TOP_K", 5, 1, 100),
        "top_p": _float_setting("WANDERER_TTS_TOP_P", 0.8, 0.0, 1.0),
        "temperature": _float_setting("WANDERER_TTS_TEMPERATURE", 0.7, 0.0, 1.0),
        "speed_factor": _float_setting("WANDERER_TTS_SPEED_FACTOR", 0.9, 0.6, 1.65),
        "seed": _int_setting("WANDERER_TTS_SEED", 1234, -1, 2**32 - 1),
        "parallel_infer": _as_bool(os.getenv("WANDERER_TTS_PARALLEL_INFER", "false")),
    }


def _cache_path(text: str) -> Path:
    cache_dir = Path(os.getenv("WANDERER_TTS_CACHE_DIR", "").strip() or "data/voice-cache")
    settings = VoiceSettings.from_env()
    fingerprint = hashlib.sha256(
        "\0".join((
            "v3",
            settings.mode,
            settings.api_url,
            text,
            _reference_audio(),
            settings.prompt_text,
            str(settings.gpt_weights) if settings.gpt_weights else "",
            str(settings.sovits_weights) if settings.sovits_weights else "",
            json.dumps(_tts_parameters(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )).encode("utf-8")
    ).hexdigest()
    return cache_dir / f"{fingerprint}.wav"


def _tts_payload(text: str, *, streaming_mode: int | bool = False) -> dict[str, object]:
    return {
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": _reference_audio(),
        "prompt_lang": "zh",
        "prompt_text": _prompt_text(),
        "text_split_method": "cut5",
        "batch_size": 1,
        "media_type": "wav",
        "streaming_mode": streaming_mode,
        "repetition_penalty": 1.35,
        **_tts_parameters(),
    }


def _wav_chunks(chunks: Iterator[bytes]) -> Iterator[bytes]:
    """Validate GPT-SoVITS' standard PCM header before exposing any bytes.

    Buffer only the 44-byte header, including across arbitrary HTTP fragments.
    Zero-length mode-1 WAV headers are valid; PCM can follow immediately.
    Reject metadata/extended headers rather than forwarding untrusted content.
    """
    header = bytearray()
    for chunk in chunks:
        needed = 44 - len(header)
        header.extend(chunk[:needed])
        if len(header) < 44:
            continue
        riff, size, kind, fmt, fmt_size, encoding, channels, rate, byte_rate, align, bits, data, data_size = struct.unpack(
            "<4sI4s4sIHHIIHH4sI", header
        )
        if (
            (riff, kind, fmt, data) != (b"RIFF", b"WAVE", b"fmt ", b"data")
            or fmt_size != 16 or encoding != 1 or channels not in {1, 2}
            or bits not in {8, 16, 24, 32} or not 1 <= rate <= 384000
            or align != channels * (bits // 8) or byte_rate != rate * align
            or data_size % align or size != 36 + data_size
        ):
            raise VoiceUnavailableError("the TTS service returned invalid audio")
        yield bytes(header) + chunk[needed:]
        yield from chunks
        return
    raise VoiceUnavailableError("the TTS service returned incomplete audio")


def _validate_wav(audio: bytes) -> None:
    try:
        with wave.open(BytesIO(audio), "rb") as sample:
            if sample.getcomptype() != "NONE":
                raise VoiceUnavailableError("the local TTS service returned invalid audio")
            frame_count = sample.getnframes()
            frames = sample.readframes(frame_count)
            sample_width = sample.getsampwidth()
            if sample_width not in {1, 2, 3, 4}:
                raise VoiceUnavailableError("the local TTS service returned unsupported audio")
            # GPT-SoVITS' streaming WAV response sends a zero-length RIFF
            # header first and appends raw PCM fragments afterwards. The wave
            # module quite correctly reports zero frames from that header, so
            # inspect the bytes after the standard 44-byte header before
            # rejecting an otherwise valid completed stream.
            if frame_count <= 0 and len(audio) > 44 and audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
                frames = audio[44:]
            if not frames:
                raise VoiceUnavailableError("the local TTS service returned empty audio")
            midpoint = 128 if sample_width == 1 else 0
            if not any(value != midpoint for value in frames):
                raise VoiceUnavailableError("the local TTS service returned silent audio")
    except (wave.Error, EOFError) as exc:
        raise VoiceUnavailableError("the local TTS service returned invalid audio") from exc


def synthesize_voice(text: str) -> bytes:
    """Synthesize one Chinese line and cache it by text and voice settings."""
    if not voice_enabled():
        raise VoiceUnavailableError("voice is disabled")
    settings = VoiceSettings.from_env()
    reference_audio = _reference_audio()
    if settings.mode == "remote":
        _guard_remote_endpoint(settings.api_url)
    if settings.mode == "local" and (not reference_audio or not Path(reference_audio).is_file()):
        raise VoiceUnavailableError("voice reference audio is not configured")

    cache_path = _cache_path(text)
    with _cache_lock(cache_path):
        if cache_path.is_file():
            return cache_path.read_bytes()

        payload = _tts_payload(text)
        try:
            response = httpx.post(
                _api_url(),
                json=payload,
                timeout=_timeout(),
                follow_redirects=False,
                trust_env=False,
            )
            response.raise_for_status()
        except (httpx.HTTPError, VoiceUnavailableError):
            raise VoiceUnavailableError("the TTS service did not respond") from None

        audio = response.content
        if not audio:
            raise VoiceUnavailableError("the local TTS service returned empty audio")
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "audio/wav":
            raise VoiceUnavailableError("the local TTS service returned an unexpected audio format")
        _validate_wav(audio)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(audio)
        temporary.replace(cache_path)
        return audio


def stream_voice(text: str) -> Iterator[bytes]:
    """Stream the first quality-preserving GPT-SoVITS fragment immediately.

    GPT-SoVITS mode 1 keeps the normal non-streaming synthesis quality for each
    text fragment while yielding completed fragments as they become available.
    The temporary file is promoted to the normal cache only after the complete
    WAV stream has been validated.
    """
    if not voice_enabled():
        raise VoiceUnavailableError("voice is disabled")
    settings = VoiceSettings.from_env()
    reference_audio = _reference_audio()
    if settings.mode == "remote":
        _guard_remote_endpoint(settings.api_url)
    if settings.mode == "local" and (not reference_audio or not Path(reference_audio).is_file()):
        raise VoiceUnavailableError("voice reference audio is not configured")

    cache_path = _cache_path(text)
    if cache_path.is_file():
        return _wav_chunks(iter((cache_path.read_bytes(),)))

    def generate() -> Iterator[bytes]:
        # Each producer gets its own staging file.  The in-process cache lock
        # deduplicates requests in this worker; a unique path also keeps
        # separate workers from truncating or deleting one another's stream.
        temporary = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.stream.tmp")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _cache_lock(cache_path):
                if cache_path.is_file():
                    yield from _wav_chunks(iter((cache_path.read_bytes(),)))
                    return
                with httpx.stream(
                    "POST",
                    _api_url(),
                    json=_tts_payload(text, streaming_mode=1),
                    timeout=_timeout(),
                    follow_redirects=False,
                    trust_env=False,
                ) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type != "audio/wav":
                        raise VoiceUnavailableError("the local TTS service returned an unexpected audio format")
                    with temporary.open("wb") as output:
                        for chunk in _wav_chunks(response.iter_bytes()):
                            if chunk:
                                output.write(chunk)
                                yield chunk
                audio = temporary.read_bytes()
                if not audio:
                    raise VoiceUnavailableError("the local TTS service returned empty audio")
                _validate_wav(audio)
                temporary.replace(cache_path)
        except VoiceUnavailableError:
            temporary.unlink(missing_ok=True)
            raise
        except httpx.HTTPError:
            temporary.unlink(missing_ok=True)
            raise VoiceUnavailableError("the TTS service did not respond") from None
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    return generate()
