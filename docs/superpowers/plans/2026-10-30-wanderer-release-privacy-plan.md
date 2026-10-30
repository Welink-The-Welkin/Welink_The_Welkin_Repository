# 发布包隐私与可上传边界实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让源码发布包只包含 Git 已跟踪的项目内容，绝不因打包器递归扫描工作目录而带出 `.env`、数据库、缓存、日志、模型、参考音频或其他本机文件。

**Architecture:** 发布器以 `git ls-files -z` 作为唯一输入，而不是 `Path.rglob`；逐项做仓库根目录校验、输出路径排除和归档名规范化。验证测试在临时 Git 仓库中分别创建已跟踪源文件、未跟踪文件、忽略文件、数据库、模型和音频，证明只有已跟踪文件进入 ZIP。部署文档同时声明权重和参考音频由独立 TTS 主机管理。

**Tech Stack:** Python 3.11、`subprocess`、`zipfile`、pytest、Git CLI。

**Spec:** `docs/superpowers/specs/2026-10-30-wanderer-model-voice-design.md`

**Execution order:** Run after the model-settings and voice-deployment plans so the final package includes their committed, reviewed source and documentation.

## Global Constraints

- 发布器只打包 Git 已跟踪文件，不遍历运行时工作目录。
- 不创建或提交真实 `.env`、API Key、数据库、缓存、模型权重、参考音频或本机绝对路径。
- 发布失败不得覆盖已有输出归档。
- 所有测试数据使用临时目录和占位文本，不使用真实私密内容。

---

### Task 1: Replace recursive source discovery with Git-tracked discovery

**Files:**
- Modify: `scripts/package_release.py`
- Modify: `tests/test_release_package.py`

**Interfaces:**
- `_tracked_source_files(root: Path, output: Path) -> list[Path]` invokes `git -C root ls-files -z --cached` and returns only regular files inside `root`.
- `_validate_archive_candidates(paths: Sequence[Path]) -> None` fails closed on tracked `.env` except `.env.example`, database/cache/log files, model weights and audio assets; untracked and ignored files are never candidates.
- `build_archive(output: Path) -> int` preserves required-file validation, atomic replacement and existing archive safety.

- [ ] **Step 1: Write failing package tests**

Add a temporary Git repository fixture that creates a tracked app file, an untracked private marker, ignored `.env`, ignored database, untracked model checkpoint, untracked WAV, and a tracked source file under a normal app directory. Assert only tracked source files appear. Add a tracked `.env`, database, weight and audio case and assert packaging fails before replacing an existing archive. Add a test that `git` failure reports a clear error and does not replace an existing archive.

- [ ] **Step 2: Run focused tests**

Run: `python -m pytest tests/test_release_package.py -q`

Expected: FAIL because `_source_files` currently uses `ROOT.rglob("*")` and includes untracked files.

- [ ] **Step 3: Implement tracked-file enumeration**

Run `subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached"], check=True, stdout=PIPE)`; decode NUL-separated relative paths, reject absolute paths and `..` components, resolve each path under `ROOT`, skip the output archive itself, and require `path.is_file()`. Before writing, reject tracked private artifact names except `.env.example`; this protects against a secret accidentally added to Git. Keep the existing required-file check and atomic temporary archive. Do not invoke `git add`, `git commit`, or any command that mutates the repository.

- [ ] **Step 4: Run package tests**

Run: `python -m pytest tests/test_release_package.py -q`

Expected: PASS; archive contents contain tracked files only and existing archives survive validation failure.

- [ ] **Step 5: Commit**

```bash
git add scripts/package_release.py tests/test_release_package.py
git commit -m "fix: package only tracked repository files"
```

### Task 2: Update public documentation and release scans

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment-guide.md`
- Modify: `.env.example`
- Modify: `tests/test_release_package.py`
- Test: `tests/test_privacy_scan.py`

- [ ] **Step 1: Add failing documentation/privacy tests**

Assert documentation no longer promises automatic browser Chinese speech as the default trained voice, states that public voice comes from independent remote TTS, names the safe server-side variables without values, and does not contain a machine-specific user-profile path. Remove local training-candidate path examples and concrete reference-audio filenames from `.env.example`; leave only empty/configuration placeholders and documented variable names. Assert a repository scan rejects `.env`, `*.db`, `*.wav`, `*.ckpt`, `*.pth`, API-key patterns, and Windows user-profile paths in tracked files while allowing `.env.example` placeholders and test-only temporary paths. Express scanner patterns so their own source text does not match the patterns it checks.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_privacy_scan.py tests/test_release_package.py -q`

Expected: FAIL on the current README statement that browser speech is an automatic fallback and on any tracked-path/key match.

- [ ] **Step 3: Update docs without private values**

Replace the automatic fallback wording with explicit trained/compatibility/text modes. Document that public HTTPS visitors use the deployment server’s TTS endpoint and never need the developer’s computer, GPT-SoVITS installation, weights, or reference audio. Show only variable names and placeholder domains such as `https://tts.example.invalid/tts`; never include a real path or secret.

- [ ] **Step 4: Run privacy and release checks**

Run: `python -m pytest tests/test_privacy_scan.py tests/test_release_package.py -q; git diff --check`

Expected: PASS with no sensitive tracked content and no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/deployment-guide.md .env.example tests/test_privacy_scan.py tests/test_release_package.py
git commit -m "docs: document safe independent voice deployment"
```

### Task 3: Run cross-cutting release verification

**Files:**
- Modify only if a test exposes a regression: `tests/test_startup.py`, `tests/test_voice.py`, `tests/test_live_and_chat.py`

- [ ] **Step 1: Run Python, frontend and syntax checks**

Run: `python -m pytest -q; python -m compileall backend scripts; node --test tests/frontend_behavior.test.cjs; node --check frontend/app.js`

Expected: PASS with no failures. If a failure is found, update the owning task’s regression test and implementation; do not weaken the assertion.

- [ ] **Step 2: Build a release archive in a temporary output directory**

Run:

```powershell
$releaseTemp = Join-Path $env:TEMP ('wanderer-release-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $releaseTemp | Out-Null
python scripts/package_release.py --output (Join-Path $releaseTemp 'wanderer-game-source.zip')
```

Expected: the archive contains only tracked project files, excludes `data`, `.env`, caches, logs, model files and audio, and the command does not alter tracked files.

- [ ] **Step 3: Scan the archive and worktree**

Run a Python check over ZIP names and decoded text for `.env` (except `.env.example`), database/cache/log/model/audio suffixes, Windows user-profile path patterns, high-entropy API-key patterns, long authorization token patterns, and PEM headers; run `git status --short` afterward.

Expected: no prohibited match and only intentional source/doc changes remain.

- [ ] **Step 4: Commit the verification updates**

```bash
git add tests/test_startup.py tests/test_voice.py tests/test_live_and_chat.py
git commit -m "test: verify complete privacy-safe release flow"
```

## Self-Review Checklist

- The archive is based on Git’s tracked set, so ignored or untracked local data cannot leak through recursive scanning.
- Tests cover tracked/untracked/ignored files, required-file failures, archive atomicity and sensitive-pattern scans.
- Documentation describes independent TTS deployment without publishing any private path, key, weight or audio.
