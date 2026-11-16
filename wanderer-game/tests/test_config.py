# 本文件由 codex 辅助生成（外围模块）
from backend.app import config


def test_load_env_file_sets_only_missing_environment_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WANDERER_MODEL_NAME=deepseek-v4.1-flash\n"
        "WANDERER_MODEL_BASE_URL=\"https://example.test\"\n"
        "# comment\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WANDERER_MODEL_NAME", raising=False)
    monkeypatch.setenv("WANDERER_MODEL_BASE_URL", "https://existing.test")

    config.load_env_file(env_file)

    assert config.os.environ["WANDERER_MODEL_NAME"] == "deepseek-v4.1-flash"
    assert config.os.environ["WANDERER_MODEL_BASE_URL"] == "https://existing.test"
