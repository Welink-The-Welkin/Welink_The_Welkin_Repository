# 独立角色语音与本机诊断实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让本机启动在没有 `.env` 时按唯一、可解释的默认约定连接 GPT-SoVITS，并让公开 HTTPS 部署通过独立持续在线的 TTS 服务提供训练音色，不依赖开发者电脑。

**Architecture:** 把本机/远程语音配置解析和诊断码集中在 `voice_config` 模块；后端只接受部署环境配置的 TTS URL，浏览器只访问同源 `/api/voice/*`。本机启动器只检查一个明确默认根目录和参考音频，不扫描磁盘；远程模式要求 HTTPS。前端默认显示文字和语音状态，只有用户主动选择系统兼容语音时才调用 `speechSynthesis`。

**Tech Stack:** Python 3.11、FastAPI、httpx、GPT-SoVITS v2Pro、PowerShell、原生 JavaScript、pytest。

**Spec:** `docs/superpowers/specs/2026-10-30-wanderer-model-voice-design.md`

**Execution order:** Run after `2026-10-30-wanderer-model-settings-plan.md` because both plans change `frontend/app.js`, `frontend/styles.css`, and browser behavior tests.

## Global Constraints

- 默认安装根目录和默认参考音频只能各有一个 documented value；不得全盘搜索、猜测多版本路径或静默换音色。
- 本机失败必须返回 `code`、原因、变量名、检查项和下一步动作；不自动回退浏览器语音。
- 公共访问只使用部署方独立、持续在线的 HTTPS TTS 服务；访客不需安装 GPT-SoVITS、权重或参考音频。
- 浏览器不接收或传递任意 TTS URL；本地 HTTP 仅允许 loopback，远程必须 HTTPS。
- 不把训练权重、参考音频、`.env`、缓存或本机绝对路径提交到仓库。

---

### Task 1: 建立统一语音配置与诊断模型

**Files:**
- Create: `backend/app/core/voice_config.py`
- Modify: `backend/app/voice.py`
- Modify: `backend/app/api/routes/voice.py`
- Test: `tests/test_voice_config.py`

**Interfaces:**
- `VoiceSettings.from_env() -> VoiceSettings` 解析 `WANDERER_TTS_ENABLED`, `WANDERER_TTS_API_URL`, `GPT_SOVITS_ROOT`, `WANDERER_TTS_GPT_WEIGHTS`, `WANDERER_TTS_SOVITS_WEIGHTS`, `WANDERER_TTS_REFERENCE_AUDIO` 和提示文本。显式 `WANDERER_TTS_ENABLED=false` 关闭语音；未设置时 Windows 本机使用唯一文档默认值，非 Windows/无配置部署显示未配置诊断；远程部署显式开启并使用 HTTPS URL。
- `VoiceDiagnostic` 序列化为 `{code, message, variables, check, action}`；诊断不得包含绝对路径、Key 或模型权重内容。
- `voice_status() -> dict[str, object]` 返回 `enabled`, `configured`, `mode`, `diagnostics`, `compatibility_voice_available`，并保留现有客户端需要的布尔字段。

- [ ] **Step 1: Write failing tests**

```python
def test_missing_local_reference_reports_variable_and_action(monkeypatch):
    monkeypatch.setenv("WANDERER_TTS_ENABLED", "true")
    monkeypatch.delenv("WANDERER_TTS_REFERENCE_AUDIO", raising=False)
    status = voice_status()
    assert status["diagnostics"][0]["code"] == "TTS_REFERENCE_AUDIO_MISSING"
    assert "WANDERER_TTS_REFERENCE_AUDIO" in status["diagnostics"][0]["variables"]
    assert status["diagnostics"][0]["action"]


def test_remote_tts_requires_https(monkeypatch):
    monkeypatch.setenv("WANDERER_TTS_API_URL", "http://tts.example/tts")
    with pytest.raises(ValueError):
        VoiceSettings.from_env()
```

- [ ] **Step 2: Run focused tests**

Run: `python -m pytest tests/test_voice_config.py -q`

Expected: FAIL because the diagnostic model does not exist.

- [ ] **Step 3: Implement configuration and diagnostics**

Define one Windows default root `Path.home() / "Desktop" / "GPT-SoVITS-v2pro-20250604"` and one documented reference relative to that root, matching the current launcher constants. Check only the named files (`api_v2.py`, bundled runtime Python, configured GPT/SoVITS weights and reference audio); do not iterate over parent directories. For non-default paths require the exact variables named in the spec. Use `TTS_NOT_ENABLED`, `TTS_ROOT_MISSING`, `TTS_WEIGHTS_MISSING`, `TTS_REFERENCE_AUDIO_MISSING`, `TTS_API_UNREACHABLE`, and `TTS_API_INVALID` diagnostics with safe next actions. Explicit false disables local defaults. Separate local loopback URL validation from deployment-only remote HTTPS validation.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_voice_config.py -q`

Expected: PASS and no diagnostic response contains a private absolute path.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/voice_config.py backend/app/voice.py backend/app/api/routes/voice.py tests/test_voice_config.py
git commit -m "feat: add explicit voice configuration diagnostics"
```

### Task 2: Make local GPT-SoVITS startup deterministic and diagnosable

**Files:**
- Modify: `scripts/start_gpt_sovits.py`
- Modify: `start.ps1`
- Modify: `tests/test_startup.py`
- Modify: `tests/test_voice.py`

**Interfaces:**
- `resolve_root()` and `voice_config()` use the single documented default or explicit variables; they raise a diagnostic-bearing error rather than scanning alternatives.
- `ensure_tts_server()` returns `True` only when the requested GPT-SoVITS API is ready, and its CLI output names the variable to set when it fails.

- [ ] **Step 1: Add failing launcher tests**

Test missing root, missing reference audio, non-standard root, non-standard API port, Chinese absolute paths, and a ready local `/openapi.json`. Assert the launcher output names `GPT_SOVITS_ROOT`, `WANDERER_TTS_GPT_WEIGHTS`, `WANDERER_TTS_REFERENCE_AUDIO`, or `WANDERER_TTS_API_URL` as appropriate and never says it will try another directory.

- [ ] **Step 2: Run launcher tests**

Run: `python -m pytest tests/test_startup.py tests/test_voice.py -q`

Expected: FAIL on explicit diagnostics and default-enabled behavior.

- [ ] **Step 3: Implement launcher changes**

Load only the project `.env` if present, then apply the documented default settings. Keep process ownership files under the existing per-run temp location, but do not write model paths to game logs or API responses. Preserve CUDA probe and CPU fallback as device selection, not path discovery. Make `start.ps1` wait for the launcher result, print its actionable diagnostic, and continue starting the web app with text-only status when TTS assets are unavailable. Keep the batch wrapper paused on failure so users can read the variable guidance.

- [ ] **Step 4: Run tests and syntax checks**

Run: `python -m pytest tests/test_startup.py tests/test_voice.py -q; python -m compileall backend scripts`

Expected: PASS, with no hidden fallback to browser speech at the launcher level.

- [ ] **Step 5: Commit**

```bash
git add scripts/start_gpt_sovits.py start.ps1 start.bat tests/test_startup.py tests/test_voice.py
git commit -m "fix: diagnose local GPT-SoVITS setup explicitly"
```

### Task 3: Add independent remote TTS deployment path

**Files:**
- Modify: `backend/app/voice.py`
- Modify: `backend/app/api/routes/voice.py`
- Modify: `render.yaml`
- Modify: `Dockerfile`
- Modify: `docs/deployment-guide.md`
- Modify: `.env.example`
- Test: `tests/test_voice_remote.py`

**Interfaces:**
- Remote deployment reads only server-side `WANDERER_TTS_API_URL` and the server-side reference/prompt configuration. Browser requests contain text only.
- `/api/voice/status` never exposes remote credentials or private deployment paths; `/api/voice/stream` proxies WAV from the configured remote endpoint.

- [ ] **Step 1: Write failing remote tests**

Use a local mock only in tests to assert a configured HTTPS URL is proxied, the client request never includes a browser-supplied URL, the app remains usable when the developer workstation is unavailable, and loopback/HTTP remote configuration is rejected. Assert audio content type and safe `VOICE_UNAVAILABLE` errors.

- [ ] **Step 2: Run remote tests**

Run: `python -m pytest tests/test_voice_remote.py -q`

Expected: FAIL because current voice validation only permits local HTTP.

- [ ] **Step 3: Implement deployment mode**

Allow a server-selected `remote` mode with HTTPS-only URL validation and no automatic redirects. Keep local mode loopback-only. Move all TTS payload construction to use deployment-side reference audio and prompt text. Add Render/Docker environment placeholders without values, and document the independent host/reverse proxy requirement. Never add the trained checkpoint or reference WAV to the repository.

- [ ] **Step 4: Run remote and existing voice tests**

Run: `python -m pytest tests/test_voice_remote.py tests/test_voice.py -q`

Expected: PASS with local and remote modes isolated.

- [ ] **Step 5: Commit**

```bash
git add backend/app/voice.py backend/app/api/routes/voice.py render.yaml Dockerfile docs/deployment-guide.md .env.example tests/test_voice_remote.py
git commit -m "feat: proxy independent remote character voice"
```

### Task 4: Remove implicit browser speech and expose explicit compatibility voice

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Modify: `tests/frontend_behavior.test.cjs`

**Interfaces:**
- `appState.voiceMode` is `trained`, `compatibility`, or `text`; it defaults to `text` when the server reports unavailable voice.
- `playVoice` never calls `playBrowserVoice` unless `voiceMode === "compatibility"`.

- [ ] **Step 1: Change failing browser expectations**

Replace existing tests that expect automatic Chinese browser speech with tests asserting no `speechSynthesis.speak` call and visible text when TTS is unavailable. Add a test for the explicit “使用系统兼容音色” action and a visible compatibility label.

- [ ] **Step 2: Run focused frontend tests**

Run: `node --test tests/frontend_behavior.test.cjs`

Expected: FAIL until the automatic fallback is removed.

- [ ] **Step 3: Implement explicit voice mode**

Render the server diagnostic and a user action when voice is unavailable. Keep the existing audio queue for trained WAV playback. Gate all `playBrowserVoice` calls on the explicit compatibility setting, stop compatibility speech when leaving a route, and preserve text replies if either audio path fails.

- [ ] **Step 4: Run frontend checks**

Run: `node --test tests/frontend_behavior.test.cjs; node --check frontend/app.js`

Expected: PASS with no silent language/voice substitution.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js frontend/styles.css tests/frontend_behavior.test.cjs
git commit -m "fix: require explicit compatibility voice fallback"
```

## Self-Review Checklist

- Local startup has one default path and actionable variable diagnostics; no recursive discovery remains.
- Remote TTS is server-side and independent of the developer computer.
- Browser speech is opt-in and visibly labeled; text remains available on TTS failure.
- Tests cover local diagnostics, remote proxying, WAV validation, launcher behavior, and frontend fallback behavior.
