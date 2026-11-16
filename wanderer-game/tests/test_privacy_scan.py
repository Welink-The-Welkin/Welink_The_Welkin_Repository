"""Guard the public source tree against accidental private release content."""

from __future__ import annotations

import re
import hashlib
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parent
PUBLIC_DOCS = (ROOT / "README.md", ROOT / "docs" / "deployment-guide.md")


def _tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    names = result.stdout.decode().split("\0")
    return [REPOSITORY_ROOT / name for name in names if name]


def _tracked_text() -> list[tuple[Path, str]]:
    return [
        (path, path.read_bytes().decode("utf-8", errors="ignore"))
        for path in _tracked_paths()
        if path.is_file()
    ]


def _private_artifact_names() -> tuple[str, ...]:
    return (
        ".env",
        ".env.production",
        ".db",
        ".db-wal",
        ".db-shm",
        ".db-journal",
        ".sqlite",
        ".sqlite3",
        ".log",
        ".cache",
        ".wav",
        ".mp3",
        ".ckpt",
        ".pth",
        ".pt",
        ".safetensors",
        ".onnx",
        ".gguf",
        ".tflite",
        ".aac",
        ".opus",
        ".flac",
        ".ogg",
        ".m4a",
        ".bin",
        ".pyc",
        ".pyo",
    )


def _packager_private_artifact_names() -> tuple[str, ...]:
    # Keep this expected set independent from the scanner implementation.
    return (
        ".env",
        ".env.production",
        ".db",
        ".db-wal",
        ".db-shm",
        ".db-journal",
        ".sqlite",
        ".sqlite3",
        ".log",
        ".cache",
        ".wav",
        ".mp3",
        ".ckpt",
        ".pth",
        ".pt",
        ".safetensors",
        ".bin",
        ".onnx",
        ".gguf",
        ".tflite",
        ".flac",
        ".ogg",
        ".m4a",
        ".aac",
        ".opus",
        ".pyc",
        ".pyo",
    )


def _private_text_patterns() -> tuple[re.Pattern[str], ...]:
    # Keep fixture literals out of the source text that this scanner examines.
    token_prefixes = (
        "s" + "k-",
        "g" + "sk-",
        "x" + "ai-",
        "A" + "Iza",
        "gh" + "p_",
        "github" + "_pat_",
        "h" + "f_",
        "r" + "8_",
    )
    token_pattern = re.compile(
        r"(?:" + "|".join(map(re.escape, token_prefixes)) + r")[A-Za-z0-9_-]{20,}"
    )
    assignment_labels = (
        "api" + "[_-]?(?:key|token|secret)",
        "token",
        "secret",
    )
    assignment_pattern = re.compile(
        r"['\"]?(?:" + "|".join(assignment_labels) + r")['\"]?[ \t]*[:=][ \t]*['\"]?[A-Za-z0-9+/=_-]{24,}",
        flags=re.IGNORECASE,
    )
    bearer_word = "Bear" + "er"
    bearer_pattern = re.compile(r"\b" + bearer_word + r"\s+[A-Za-z0-9._~+/=-]{24,}", flags=re.IGNORECASE)
    private_word = "PRIVATE"
    key_word = "KEY"
    pem_pattern = re.compile(r"-----BEGIN(?: [A-Z0-9]+)* " + private_word + r" " + key_word + r"-----")
    return token_pattern, assignment_pattern, bearer_pattern, pem_pattern


def _assert_public_entries(entries: list[tuple[Path, str]]) -> None:
    private_names = _private_artifact_names()
    windows_profile = r"[A-Z]:\\" + "Users" + r"\\"
    unix_profile = "/" + "Users" + "/"
    home_profile = "/" + "home" + "/"
    deployment_private = "/" + "deployment" + "/" + "private" + "/"
    windows_deployment_private = r"[A-Z]:\\" + "deployment" + r"\\" + "private" + r"\\"
    profile_pattern = re.compile(
        "(?i)(?:" + "|".join(
            (windows_profile, unix_profile, home_profile, deployment_private, windows_deployment_private)
        ) + ")"
    )
    text_patterns = _private_text_patterns()

    for candidate, text in entries:
        relative = Path(candidate)
        assert not relative.is_absolute(), relative
        filename = relative.name.lower()
        if filename != ".env.example":
            assert not (
                filename == ".env"
                or filename.startswith(".env.")
                or relative.suffix.lower() in private_names
            ), relative
        assert not profile_pattern.search(text), relative
        for pattern in text_patterns:
            assert not pattern.search(text), relative


def test_public_docs_describe_explicit_voice_modes_and_remote_boundary():
    text = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_DOCS)

    assert "训练音色" in text
    assert "兼容音色" in text
    assert "无语音" in text
    assert "独立" in text
    assert "HTTPS" in text
    assert "开发者电脑" in text
    assert "WANDERER_TTS_API_URL" in text
    assert "WANDERER_TTS_REFERENCE_AUDIO" in text
    assert "WANDERER_TTS_GPT_WEIGHTS" in text
    assert "https://voice-service.invalid/tts" in text
    assert "浏览器会自动使用系统提供的中文语音" not in text
    assert "自动回退到浏览器的中文语音" not in text


def test_public_docs_have_no_real_remote_endpoint():
    text = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_DOCS)
    urls = re.findall(r"https?://[^\s)`>\"']+", text)
    allowed_hosts = {
        "127.0.0.1",
        "localhost",
        "github.com",
        "gitcode.com",
        "gallery.developer.huaweicloud.com",
    }
    for url in urls:
        host = urlparse(url).hostname
        assert host in allowed_hosts or (host and host.endswith(".invalid")), url


def test_public_readme_links_approved_release_destinations():
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "https://gitcode.com/IanElseWhere/Welink_The_Welkin_Repository" in text
    assert "https://gallery.developer.huaweicloud.com/gallery/007342752f000000" in text


def test_env_example_contains_names_only_for_private_voice_inputs():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in (
        "WANDERER_TTS_API_URL",
        "WANDERER_TTS_API_TOKEN",
        "WANDERER_TTS_REFERENCE_AUDIO",
        "WANDERER_TTS_PROMPT_TEXT",
        "WANDERER_TTS_GPT_WEIGHTS",
        "WANDERER_TTS_SOVITS_WEIGHTS",
    ):
        assert re.search(rf"^{re.escape(name)}=$", text, flags=re.MULTILINE)
    assert not re.search(r"(?i)[^\s#=]+\.(?:wav|mp3|ckpt|pth)\b", text)


def test_tracked_tree_has_no_private_artifact_paths_or_machine_profiles():
    _assert_public_entries([(path.relative_to(REPOSITORY_ROOT), text) for path, text in _tracked_text()])


def test_tracked_tree_has_no_private_voice_asset_identifiers():
    fingerprints = (
        (12, "19762d3d04a6dd58a047c8379fbe24e1059a82125d4245bc91b129b8a53a0ba5"),
        (12, "73b6ab573b6633ffd9aa02e81e63659bc11b99ed353c3a15fca04f886785b892"),
        (51, "535516243101cdda8c353de3d1d58870cfe3a8d46b24c1951a7e414e9f454b33"),
        (18, "b30b774ab81ab3ed6de991e75497ac1b7ee8977835c241a66f3cb1d6fe8e5636"),
    )
    for _, text in _tracked_text():
        tokens = re.split(r"[\s/\\'\"`=,:;()\[\]{}]+", text)
        for length, fingerprint in fingerprints:
            candidates = (value for value in tokens if len(value) == length)
            assert all(hashlib.sha256(value.encode("utf-8")).hexdigest() != fingerprint for value in candidates)


@pytest.mark.parametrize("filename", _packager_private_artifact_names())
def test_scanner_rejects_every_private_artifact_suffix(filename):
    candidate = (
        Path("fixtures") / filename
        if filename.startswith(".env")
        else Path("fixtures") / ("sample" + filename)
    )
    with pytest.raises(AssertionError):
        _assert_public_entries([(candidate, "safe")])


def test_scanner_rejects_private_profile_and_deployment_paths():
    private_fragments = (
        "C:" + "\\" + "Users" + "\\" + "Example" + "\\" + "secret.txt",
        "C:" + "\\" + "deployment" + "\\" + "private" + "\\" + "reference.dat",
        "/" + "Users" + "/Example/secret.txt",
        "/" + "home" + "/example/secret.txt",
        "/" + "deployment" + "/" + "private" + "/reference.dat",
    )
    for private_path in private_fragments:
        with pytest.raises(AssertionError):
            _assert_public_entries([(Path("docs/fixture.txt"), private_path)])


def _secret_fixtures() -> tuple[str, ...]:
    long_value = "x" * 28
    return (
        "s" + "k-" + long_value,
        "g" + "sk-" + long_value,
        "x" + "ai-" + long_value,
        "A" + "Iza" + long_value,
        "gh" + "p_" + long_value,
        "github" + "_pat_" + long_value,
        "h" + "f_" + long_value,
        "r" + "8_" + long_value,
        "api" + "_key=" + long_value,
        "api" + "_token=" + long_value,
        "API" + "_KEY=" + long_value,
        "TOKEN=" + long_value,
        "SECRET=" + long_value,
        "api" + "Key=" + long_value,
        "Api" + "-Key: " + long_value,
        '"' + "API" + "_KEY" + '": "' + long_value + '"',
        '"' + "TOKEN" + '": "' + long_value + '"',
        "token: " + long_value,
        "secret=" + long_value,
        "Bear" + "er " + long_value,
        "-----BEGIN " + "PRIVATE" + " KEY-----",
        "-----BEGIN RSA " + "PRIVATE" + " KEY-----",
    )


@pytest.mark.parametrize("secret", _secret_fixtures())
def test_scanner_rejects_modern_keys_tokens_and_private_key_headers(secret):
    with pytest.raises(AssertionError):
        _assert_public_entries([(Path("docs/fixture.txt"), secret)])


def test_scanner_bearer_detection_is_case_insensitive():
    with pytest.raises(AssertionError):
        _assert_public_entries([(Path("docs/fixture.txt"), "bearer " + "x" * 28)])


def test_scanner_allows_safe_placeholders_and_public_docs():
    entries = [
        (Path(".env.example"), "WANDERER_MODEL_API_KEY=\nGPT_SOVITS_ROOT=\nWANDERER_TTS_REFERENCE_AUDIO=\n"),
        (Path("README.md"), "https://voice-service.invalid/tts and a relative fixtures/reference.wav"),
    ]
    _assert_public_entries(entries)
