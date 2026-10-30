"""Small GPT-SoVITS client used by the game's optional voice layer."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import wave
from io import BytesIO
from collections.abc import Iterator
from threading import Lock
from contextlib import contextmanager
from uuid import uuid4

import httpx


class VoiceUnavailableError(RuntimeError):
    """The local TTS service cannot produce audio for this request."""


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
    return _as_bool(os.getenv("WANDERER_TTS_ENABLED"))


def _validate_api_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise VoiceUnavailableError("the local GPT-SoVITS endpoint must use localhost")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise VoiceUnavailableError("the local GPT-SoVITS endpoint is invalid")
    if parsed.path not in {"", "/", "/tts"}:
        raise VoiceUnavailableError("the local GPT-SoVITS endpoint is invalid")
    return f"http://{parsed.netloc}/tts"


def _api_ready(api_url: str) -> bool:
    parsed = urlsplit(api_url)
    try:
        response = httpx.get(f"{parsed.scheme}://{parsed.netloc}/openapi.json", timeout=1)
        return response.status_code == 200 and "/tts" in response.json().get("paths", {})
    except (httpx.HTTPError, ValueError):
        return False


def voice_status() -> dict[str, bool]:
    configured = voice_enabled()
    if not configured:
        return {"enabled": False, "configured": False}
    try:
        ready = _api_ready(_validate_api_url(_api_url()))
    except VoiceUnavailableError:
        ready = False
    return {"enabled": ready, "configured": True}


def _api_url() -> str:
    value = os.getenv("WANDERER_TTS_API_URL", "http://127.0.0.1:9880/tts").strip()
    return _validate_api_url(value)


def _reference_audio() -> str:
    return os.getenv("WANDERER_TTS_REFERENCE_AUDIO", "").strip()


def _prompt_text() -> str:
    return os.getenv("WANDERER_TTS_PROMPT_TEXT", "").strip()


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
    cache_dir = Path(os.getenv("WANDERER_TTS_CACHE_DIR", "data/voice-cache"))
    root = os.getenv("GPT_SOVITS_ROOT", "")
    fingerprint = hashlib.sha256(
        "\0".join((
            "v2",
            text,
            _reference_audio(),
            _prompt_text(),
            os.getenv("WANDERER_TTS_GPT_WEIGHTS", "") or f"{root}/GPT_weights_v2Pro/流浪者-e15.ckpt",
            os.getenv("WANDERER_TTS_SOVITS_WEIGHTS", "") or f"{root}/GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth",
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
    reference_audio = _reference_audio()
    if not reference_audio or not Path(reference_audio).is_file():
        raise VoiceUnavailableError("voice reference audio is not configured")

    cache_path = _cache_path(text)
    with _cache_lock(cache_path):
        if cache_path.is_file():
            return cache_path.read_bytes()

        payload = _tts_payload(text)
        try:
            response = httpx.post(_api_url(), json=payload, timeout=_timeout())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError("the local TTS service did not respond") from exc

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
    reference_audio = _reference_audio()
    if not reference_audio or not Path(reference_audio).is_file():
        raise VoiceUnavailableError("voice reference audio is not configured")

    cache_path = _cache_path(text)
    if cache_path.is_file():
        return iter((cache_path.read_bytes(),))

    def generate() -> Iterator[bytes]:
        # Each producer gets its own staging file.  The in-process cache lock
        # deduplicates requests in this worker; a unique path also keeps
        # separate workers from truncating or deleting one another's stream.
        temporary = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.stream.tmp")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _cache_lock(cache_path):
                if cache_path.is_file():
                    yield cache_path.read_bytes()
                    return
                with httpx.stream("POST", _api_url(), json=_tts_payload(text, streaming_mode=1), timeout=_timeout()) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type != "audio/wav":
                        raise VoiceUnavailableError("the local TTS service returned an unexpected audio format")
                    with temporary.open("wb") as output:
                        for chunk in response.iter_bytes():
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
        except httpx.HTTPError as exc:
            temporary.unlink(missing_ok=True)
            raise VoiceUnavailableError("the local TTS service did not respond") from exc
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    return generate()
