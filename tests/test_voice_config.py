"""Configuration contracts; all file probes stay inside test fixtures."""

import json
from pathlib import Path

import pytest
import httpx

from backend.app import voice


@pytest.fixture(autouse=True)
def isolated_voice_env(monkeypatch, tmp_path):
    for name in (
        "WANDERER_TTS_ENABLED", "WANDERER_TTS_API_URL", "GPT_SOVITS_ROOT",
        "WANDERER_TTS_GPT_WEIGHTS", "WANDERER_TTS_SOVITS_WEIGHTS",
        "WANDERER_TTS_REFERENCE_AUDIO", "WANDERER_TTS_PROMPT_TEXT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))


def settings_module():
    from backend.app.core import voice_config
    return voice_config


def local_install(tmp_path, monkeypatch):
    root = tmp_path / "install"
    for relative in (
        "api_v2.py", "runtime/python.exe", "GPT_weights_v2Pro/流浪者-e15.ckpt",
        "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth", "reference.wav",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    monkeypatch.setenv("GPT_SOVITS_ROOT", str(root))
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", str(root / "reference.wav"))
    return root


def test_missing_local_reference_reports_variable_and_action(monkeypatch):
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    status = voice.voice_status()
    diagnostic = status["diagnostics"][0]
    assert diagnostic["code"] == "TTS_REFERENCE_AUDIO_MISSING"
    assert "WANDERER_TTS_REFERENCE_AUDIO" in diagnostic["variables"]
    assert diagnostic["check"] and diagnostic["action"]
    assert set(diagnostic) == {"code", "message", "variables", "check", "action"}


@pytest.mark.parametrize("url", [
    "http://tts.example/tts", "https://user:secret@tts.example/tts",
    "https://tts.example/tts?key=secret", "https://tts.example/tts#secret",
    "http://127.0.0.1:bad/tts", "https://tts.example/other",
    "file:///private/tts", "https:///tts",
])
def test_invalid_endpoint_is_rejected_without_echoing_values(monkeypatch, url):
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_API_URL", url)
    with pytest.raises(ValueError) as error:
        settings_module().VoiceSettings.from_env()
    assert url not in str(error.value)
    status = voice.voice_status()
    assert status["diagnostics"][0]["code"] == "TTS_API_INVALID"
    assert "secret" not in json.dumps(status)


def test_explicit_false_disables_windows_defaults(monkeypatch):
    module = settings_module()
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "false")
    status = voice.voice_status()
    assert status["enabled"] is False
    assert status["configured"] is False
    assert status["diagnostics"][0]["code"] == "TTS_NOT_ENABLED"


def test_non_windows_without_configuration_does_not_use_local_defaults(monkeypatch):
    module = settings_module()
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    settings = module.VoiceSettings.from_env()
    assert settings.enabled is False
    assert settings.root is None
    assert voice.voice_status()["diagnostics"][0]["code"] == "TTS_NOT_ENABLED"


def test_windows_defaults_match_documented_reference_and_prompt(monkeypatch, tmp_path):
    module = settings_module()
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    settings = module.VoiceSettings.from_env()
    assert settings.enabled is True
    assert settings.root == tmp_path / "Desktop/GPT-SoVITS-v2pro-20250604"
    assert settings.reference_audio == settings.root / "logs/wanderer/5-wav32k/6.1流浪者全语音无音效无背景音乐（自用）.mp3_0000716160_0000856960.wav"
    assert settings.prompt_text == "可别让我失望.这世上没有纯粹的自由."


def test_ready_local_status_and_payload_use_shared_settings(monkeypatch, tmp_path):
    root = local_install(tmp_path, monkeypatch)
    monkeypatch.setattr(voice, "_api_ready", lambda url: True)
    status = voice.voice_status()
    assert status == {
        "enabled": True, "configured": True, "mode": "local",
        "diagnostics": [], "compatibility_voice_available": True,
    }
    assert voice._tts_payload("你好")["ref_audio_path"] == str(root / "reference.wav")


@pytest.mark.parametrize("relative,code,variable", [
    ("api_v2.py", "TTS_ROOT_MISSING", "GPT_SOVITS_ROOT"),
    ("runtime/python.exe", "TTS_ROOT_MISSING", "GPT_SOVITS_ROOT"),
    ("GPT_weights_v2Pro/流浪者-e15.ckpt", "TTS_WEIGHTS_MISSING", "WANDERER_TTS_GPT_WEIGHTS"),
    ("GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth", "TTS_WEIGHTS_MISSING", "WANDERER_TTS_SOVITS_WEIGHTS"),
    ("reference.wav", "TTS_REFERENCE_AUDIO_MISSING", "WANDERER_TTS_REFERENCE_AUDIO"),
])
def test_missing_named_file_has_safe_actionable_diagnostic(monkeypatch, tmp_path, relative, code, variable):
    root = local_install(tmp_path, monkeypatch)
    (root / relative).unlink()
    status = voice.voice_status()
    diagnostic = next(item for item in status["diagnostics"] if item["code"] == code)
    assert variable in diagnostic["variables"]
    assert diagnostic["action"]
    assert status["configured"] is False
    assert str(tmp_path) not in json.dumps(status)


def test_unreachable_service_is_distinct_from_missing_configuration(monkeypatch, tmp_path):
    local_install(tmp_path, monkeypatch)
    monkeypatch.setattr(voice, "_api_ready", lambda url: False)
    status = voice.voice_status()
    assert status["configured"] is True
    assert status["enabled"] is False
    assert status["diagnostics"][0]["code"] == "TTS_API_UNREACHABLE"


def test_explicit_weight_overrides_and_relative_reference_resolve_under_root(monkeypatch, tmp_path):
    root = local_install(tmp_path, monkeypatch)
    monkeypatch.setenv("WANDERER_TTS_GPT_WEIGHTS", "custom.ckpt")
    monkeypatch.setenv("WANDERER_TTS_SOVITS_WEIGHTS", "custom.pth")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", "reference.wav")
    settings = settings_module().VoiceSettings.from_env()
    assert settings.gpt_weights == root / "custom.ckpt"
    assert settings.sovits_weights == root / "custom.pth"
    assert settings.reference_audio == root / "reference.wav"


def test_remote_https_requires_explicit_enable_and_no_local_assets(monkeypatch):
    monkeypatch.setenv("WANDERER_TTS_API_URL", "https://tts.example/tts")
    monkeypatch.setenv("WANDERER_TTS_REFERENCE_AUDIO", "deployment-reference")
    monkeypatch.setenv("WANDERER_TTS_PROMPT_TEXT", "deployment-prompt")
    assert settings_module().VoiceSettings.from_env().enabled is False
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setattr(voice, "_api_ready", lambda url: True)
    status = voice.voice_status()
    assert status["mode"] == "remote"
    assert status["configured"] is True
    assert status["enabled"] is True
    assert status["diagnostics"] == []


def test_remote_mode_requires_reference_audio_and_prompt_configuration(monkeypatch):
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_API_URL", "https://tts.example/tts")
    monkeypatch.delenv("WANDERER_TTS_REFERENCE_AUDIO", raising=False)
    monkeypatch.delenv("WANDERER_TTS_PROMPT_TEXT", raising=False)
    status = voice.voice_status()
    codes = {item["code"] for item in status["diagnostics"]}
    assert {"TTS_REFERENCE_AUDIO_MISSING", "TTS_PROMPT_TEXT_MISSING"} <= codes
    assert status["configured"] is False
    assert all("tts.example" not in str(item) for item in status["diagnostics"])


def test_cache_fingerprint_uses_resolved_weight_settings(monkeypatch, tmp_path):
    root = local_install(tmp_path, monkeypatch)
    default_path = voice._cache_path("同一个音色")
    monkeypatch.setenv("WANDERER_TTS_GPT_WEIGHTS", str(root / "GPT_weights_v2Pro/流浪者-e15.ckpt"))
    monkeypatch.setenv("WANDERER_TTS_SOVITS_WEIGHTS", str(root / "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth"))
    assert voice._cache_path("同一个音色") == default_path


@pytest.mark.parametrize("error_type", [PermissionError, OSError])
@pytest.mark.parametrize("relative,code,variable", [
    ("reference.wav", "TTS_REFERENCE_AUDIO_MISSING", "WANDERER_TTS_REFERENCE_AUDIO"),
    ("api_v2.py", "TTS_ROOT_MISSING", "GPT_SOVITS_ROOT"),
    ("runtime/python.exe", "TTS_ROOT_MISSING", "GPT_SOVITS_ROOT"),
    ("GPT_weights_v2Pro/流浪者-e15.ckpt", "TTS_WEIGHTS_MISSING", "WANDERER_TTS_GPT_WEIGHTS"),
    ("GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth", "TTS_WEIGHTS_MISSING", "WANDERER_TTS_SOVITS_WEIGHTS"),
])
def test_inaccessible_named_file_returns_safe_diagnostic(monkeypatch, tmp_path, error_type, relative, code, variable):
    root = local_install(tmp_path, monkeypatch)
    inaccessible = root / relative
    real_is_file = Path.is_file

    def probe(path):
        if path == inaccessible:
            raise error_type(f"private filesystem details: {inaccessible}")
        return real_is_file(path)

    monkeypatch.setattr(Path, "is_file", probe)
    status = voice.voice_status()
    diagnostic = next(item for item in status["diagnostics"] if item["code"] == code)
    assert variable in diagnostic["variables"]
    assert diagnostic["message"] and diagnostic["check"] and diagnostic["action"]
    assert status["enabled"] is False
    assert status["configured"] is False
    assert "private filesystem details" not in json.dumps(status)
    assert str(tmp_path) not in json.dumps(status)


def test_httpx_incompatible_host_is_rejected_by_settings(monkeypatch):
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_API_URL", "https://[v1.foo]/tts")
    with pytest.raises(ValueError):
        settings_module().VoiceSettings.from_env()


def test_httpx_incompatible_host_returns_safe_configuration_diagnostic(monkeypatch):
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.setenv("WANDERER_TTS_API_URL", "https://[v1.foo]/tts")

    def parse_without_network(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(200, json={"paths": {"/tts": {}}}, request=request)

    monkeypatch.setattr(voice.httpx, "get", parse_without_network)
    status = voice.voice_status()
    assert status["enabled"] is False
    assert status["configured"] is False
    diagnostic = status["diagnostics"][0]
    assert diagnostic["code"] == "TTS_API_INVALID"
    assert diagnostic["variables"] == ["WANDERER_TTS_API_URL"]
    assert diagnostic["message"] and diagnostic["check"] and diagnostic["action"]
    assert "v1.foo" not in json.dumps(status)
