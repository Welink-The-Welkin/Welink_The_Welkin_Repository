# 本文件由 codex 辅助生成（外围模块）
import os
from pathlib import Path


def load_env_file(path: str | Path | None = None) -> None:
    """Load simple KEY=VALUE settings without overwriting explicit environment values."""
    env_path = Path(path or os.getenv("WANDERER_ENV_FILE", ".env"))
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


load_env_file()


def demo_mode() -> str:
    value = os.getenv("WANDERER_DEMO_MODE", "offline").strip().lower()
    return value if value in {"offline", "live"} else "offline"


def database_path() -> Path:
    return Path(os.getenv("WANDERER_DATABASE_PATH", "data/sessions.db"))
