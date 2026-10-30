"""Exercise the upload package against local files that must stay private."""
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


def make_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    for name in ("README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml"):
        source = ROOT / name
        if source.exists():
            shutil.copyfile(source, project / name)
    for relative, content in {
        "backend/app/main.py": "app = None\n",
        "backend/app/__init__.py": "",
        "frontend/index.html": "<!doctype html><title>Game</title>",
        "frontend/app.js": "console.log('game');",
        "frontend/styles.css": "body { margin: 0; }",
        "scripts/package_release.py": None,
    }.items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            source = ROOT / relative
            if source.exists():
                shutil.copyfile(source, target)
        else:
            target.write_text(content, encoding="utf-8")
    return project


def run_packager(project, output):
    return subprocess.run(
        [sys.executable, str(project / "scripts/package_release.py"), "--output", str(output)],
        cwd=project,
        capture_output=True,
        text=True,
    )


def test_upload_package_includes_app_but_excludes_local_secrets_and_history(tmp_path):
    project = make_project(tmp_path)
    private_files = (
        ".env", ".env.production", "data/sessions.db", "data/sessions.db-wal",
        "backend/app/__pycache__/main.pyc", "backend/app/backup.db",
        "backend/app/.env", "frontend/.env", "frontend/debug.log",
        ".pytest-basetemp/api.db", ".git/config", "nonet.log",
    )
    for relative in private_files:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_TEST_VALUE", encoding="utf-8")
    # Even a source-looking file inside an interpreter cache must stay out.
    cached_source = project / "backend/app/__pycache__/cached.py"
    cached_source.write_text("PRIVATE_TEST_VALUE", encoding="utf-8")
    output = tmp_path / "upload.zip"

    result = run_packager(project, output)

    assert result.returncode == 0, result.stderr
    with ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {
            "wanderer-game/backend/app/main.py",
            "wanderer-game/frontend/index.html",
            "wanderer-game/frontend/app.js",
            "wanderer-game/frontend/styles.css",
            "wanderer-game/.env.example",
            "wanderer-game/Dockerfile",
            "wanderer-game/render.yaml",
            "wanderer-game/scripts/package_release.py",
        } <= names
        assert all("PRIVATE_TEST_VALUE" not in archive.read(name).decode("utf-8") for name in names)


def test_incomplete_project_fails_without_replacing_an_existing_archive(tmp_path):
    project = make_project(tmp_path)
    (project / "frontend/app.js").unlink()
    output = tmp_path / "upload.zip"
    output.write_bytes(b"existing archive")

    result = run_packager(project, output)

    assert result.returncode != 0
    assert "frontend/app.js" in result.stderr
    assert output.read_bytes() == b"existing archive"
