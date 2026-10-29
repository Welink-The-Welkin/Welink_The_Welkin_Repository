"""Create a clean source archive for GitHub or a hosting provider.

The archive contains the application source and deployment documentation while
leaving local credentials, databases, caches, and logs on the developer's
machine.  It is deliberately conservative: required application files are
checked before an archive is written.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "wanderer-game"

REQUIRED_FILES = (
    "backend/app/main.py",
    "frontend/index.html",
    "frontend/app.js",
    "frontend/styles.css",
    "requirements.txt",
    ".env.example",
)

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".codeartsdoer",
    "__pycache__",
    ".pytest_cache",
    "data",
    "dist",
    "node_modules",
    ".idea",
    "superpowers",
}
EXCLUDED_PREFIXES = (
    ".pytest-basetemp",
    ".edge-",
    ".batch-tmp",
    ".final-tmp",
    ".red-tmp",
    ".verify-tmp",
    ".tmp",
    "tmp",
    "wanderer-integration-",
)
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".db", ".db-shm", ".db-wal", ".log")
EXCLUDED_NAMES = {
    ".browser-flow.html",
    "HANDOFF.md",
    "IMPLEMENTATION_PLAN.md",
    "codearts-handoff.md",
}


def _is_excluded(relative: Path, output: Path) -> bool:
    if (ROOT / relative).resolve() == output.resolve():
        return True
    for part in relative.parts:
        if part in EXCLUDED_DIRS or part.startswith(EXCLUDED_PREFIXES):
            return True
    name = relative.name
    if name in EXCLUDED_NAMES:
        return True
    if name == ".env" or name.startswith(".env."):
        return name != ".env.example"
    return name.endswith(EXCLUDED_SUFFIXES)


def _source_files(output: Path) -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not _is_excluded(path.relative_to(ROOT), output)
    )


def _validate() -> None:
    missing = [name for name in REQUIRED_FILES if not (ROOT / name).is_file()]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"无法打包：缺少必要文件：{joined}")


def build_archive(output: Path) -> int:
    _validate()
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = _source_files(output)
    if not files:
        raise SystemExit("无法打包：未找到项目文件")

    with NamedTemporaryFile(prefix=f"{output.stem}-", suffix=".tmp", dir=output.parent, delete=False) as temp:
        temporary_path = Path(temp.name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in files:
                relative = path.relative_to(ROOT).as_posix()
                archive.write(path, f"{ARCHIVE_ROOT}/{relative}")
        os.replace(temporary_path, output)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    print(f"已创建发布包：{output}")
    print(f"包含 {len(files)} 个文件；未包含 .env、数据库、缓存和日志。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="创建风起异途的干净发布压缩包")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist") / "wanderer-game-source.zip",
        help="输出 zip 路径（默认：dist/wanderer-game-source.zip）",
    )
    args = parser.parse_args()
    return build_archive(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
