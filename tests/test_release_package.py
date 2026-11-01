"""Exercise the upload package against local files that must stay private."""
from pathlib import Path
import shutil
import subprocess
import sys
import os
from zipfile import ZipFile
import pytest


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


def git_track(project, *paths):
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
    subprocess.run(["git", "add", *paths], cwd=project, check=True)


def run_packager(project, output):
    return subprocess.run(
        [sys.executable, str(project / "scripts/package_release.py"), "--output", str(output)],
        cwd=project,
        capture_output=True,
        text=True,
    )


def test_upload_package_includes_app_but_excludes_local_secrets_and_history(tmp_path):
    project = make_project(tmp_path)
    git_track(project, "README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml", "backend", "frontend", "scripts")
    private_files = (
        ".env", ".env.production", "data/sessions.db", "data/sessions.db-wal",
        "backend/app/__pycache__/main.pyc", "backend/app/backup.db",
        "backend/app/.env", "frontend/.env", "frontend/debug.log",
        ".pytest-basetemp/api.db", "nonet.log",
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
    git_track(project, "README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml", "backend", "frontend", "scripts")
    (project / "frontend/app.js").unlink()
    output = tmp_path / "upload.zip"
    output.write_bytes(b"existing archive")

    result = run_packager(project, output)

    assert result.returncode != 0
    assert "frontend/app.js" in result.stderr
    assert output.read_bytes() == b"existing archive"


def test_package_uses_only_tracked_files_and_ignores_private_untracked_files(tmp_path):
    project = make_project(tmp_path)
    git_track(project, "README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml", "backend", "frontend", "scripts")
    (project / ".gitignore").write_text(".env\ndata/\n", encoding="utf-8")
    for relative in (".env", "data/sessions.db", "models/checkpoint.pt", "audio/clip.wav", "untracked.txt"):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_TEST_VALUE", encoding="utf-8")
    output = tmp_path / "upload.zip"
    result = run_packager(project, output)
    assert result.returncode == 0, result.stderr
    with ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "wanderer-game/backend/app/main.py" in names
    assert not any(name.endswith(token) for name in names for token in ("/.env", "/sessions.db", "/checkpoint.pt", "/clip.wav", "/untracked.txt"))


@pytest.mark.parametrize("relative", [".env", "data/sessions.db", "models/checkpoint.pt", "audio/clip.wav"])
def test_tracked_private_artifact_fails_before_replacing_archive(tmp_path, relative):
    project = make_project(tmp_path)
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("PRIVATE_TEST_VALUE", encoding="utf-8")
    git_track(project, "README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml", "backend", "frontend", "scripts", relative)
    output = tmp_path / "upload.zip"
    output.write_bytes(b"existing archive")
    result = run_packager(project, output)
    assert result.returncode != 0
    assert output.read_bytes() == b"existing archive"


def test_git_failure_reports_clear_error_without_replacing_archive(tmp_path):
    project = make_project(tmp_path)
    (project / ".git").write_text("gitdir: missing-git-dir\n", encoding="utf-8")
    output = tmp_path / "upload.zip"
    output.write_bytes(b"existing archive")
    result = run_packager(project, output)
    assert result.returncode != 0
    assert "git" in result.stderr.lower()
    assert output.read_bytes() == b"existing archive"


def test_tracked_symlink_outside_root_fails_closed(tmp_path):
    project = make_project(tmp_path)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("PRIVATE_TEST_VALUE", encoding="utf-8")
    link = project / "backend" / "app" / "external.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlinks unavailable")
    git_track(project, "README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml", "backend", "frontend", "scripts")
    output = tmp_path / "upload.zip"
    output.write_bytes(b"existing archive")
    result = run_packager(project, output)
    assert result.returncode != 0
    assert "outside" in result.stderr.lower() or "root" in result.stderr.lower()
    assert output.read_bytes() == b"existing archive"


def test_repository_under_excluded_named_parent_is_packaged(tmp_path):
    project = tmp_path / "data" / "repo"
    project.parent.mkdir()
    project.mkdir()
    # Build the same minimal fixture at a path whose parent is named data.
    for name in ("README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml"):
        source = ROOT / name
        if source.exists():
            shutil.copyfile(source, project / name)
    for relative, content in {
        "backend/app/main.py": "app = None\n", "frontend/index.html": "<title>Game</title>",
        "frontend/app.js": "console.log('game');", "frontend/styles.css": "body {}",
        "scripts/package_release.py": None,
    }.items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            shutil.copyfile(ROOT / relative, target)
        else:
            target.write_text(content, encoding="utf-8")
    git_track(project, "README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml", "backend", "frontend", "scripts")
    output = tmp_path / "upload.zip"
    result = run_packager(project, output)
    assert result.returncode == 0, result.stderr


def test_untracked_required_file_does_not_satisfy_validation(tmp_path):
    project = make_project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
    subprocess.run(["git", "add", "README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml", "backend/app/main.py", "frontend/index.html", "frontend/styles.css", "scripts"], cwd=project, check=True)
    output = tmp_path / "upload.zip"
    output.write_bytes(b"existing archive")
    result = run_packager(project, output)
    assert result.returncode != 0
    assert "frontend/app.js" in result.stderr
    assert output.read_bytes() == b"existing archive"


def test_tracked_output_path_is_rejected_without_replacement(tmp_path):
    project = make_project(tmp_path)
    output = project / "release.zip"
    output.write_bytes(b"tracked source")
    git_track(project, "README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml", "backend", "frontend", "scripts", "release.zip")
    result = run_packager(project, output)
    assert result.returncode != 0
    assert output.read_bytes() == b"tracked source"


@pytest.mark.parametrize("relative", ["state.sqlite3", "state.db-journal", "artifact.cache", "model.onnx", "model.gguf", "model.tflite", "clip.aac", "clip.opus"])
def test_tracked_private_artifact_extensions_fail_closed(tmp_path, relative):
    project = make_project(tmp_path)
    target = project / relative
    target.write_text("PRIVATE_TEST_VALUE", encoding="utf-8")
    git_track(project, "README.md", "requirements.txt", ".env.example", "Dockerfile", "render.yaml", "backend", "frontend", "scripts", relative)
    output = tmp_path / "upload.zip"
    output.write_bytes(b"existing archive")
    result = run_packager(project, output)
    assert result.returncode != 0
    assert output.read_bytes() == b"existing archive"
