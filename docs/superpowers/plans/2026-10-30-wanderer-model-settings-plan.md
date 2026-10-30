# 自由对话模型设置与共享传输层实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让自由对话在移动端可选择兼容模型、临时使用用户 API Key，并在 Key 保存/清除、模型错误、流式取消和响应校验上提供可操作且不泄露凭据的行为。

**Architecture:** 新增一个后端模型配置/供应商传输层，负责 HTTPS/私网校验、无重定向 HTTP、状态码分类、凭据脱敏和后端供应商 SSE 数据帧解析器。浏览器应用 SSE 保留其独立的一份前端解析器；两边都不为调用路径复制实现。自由对话每次请求携带临时 `ModelConfig`，由服务层即时创建 `LiveModelClient`，绝不写入会话存储；剧情旅途继续使用离线 `RoleplayEngine` 和 `AIResponse`。前端把模型设置存于内存，只有用户勾选后才写入命名空间 `localStorage`，并通过跨标签页事件清除。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、urllib、pytest、原生 JavaScript、浏览器 Fetch/ReadableStream/AbortController/StorageEvent。

**Spec:** `docs/superpowers/specs/2026-10-30-wanderer-model-voice-design.md`

**Execution order:** Complete this plan before `2026-10-30-wanderer-voice-deployment-plan.md`; both touch the shared frontend shell, so execute sequentially rather than in parallel. Finish `2026-10-30-wanderer-release-privacy-plan.md` after both feature plans.

## Global Constraints

- 模型 Key 只进入自由对话请求上下文，不进入剧情路由、游戏状态、聊天数据库或日志。
- 用户提供的模型 URL 必须为 HTTPS，拒绝回环/私网地址、URL 凭据和自动跟随重定向。
- 模型错误不得回退到自由对话 fixture；缺少配置时返回可识别错误并引导打开设置。
- 剧情旅途继续使用离线固定回放，不读取模型设置。
- 不在仓库创建真实 `.env`，不写入真实 API Key、模型、参考音频或本机绝对路径。

---

### Task 1: 建立共享模型配置与供应商传输契约

**Files:**
- Create: `backend/app/contracts/model.py`
- Create: `backend/app/core/model_transport.py`
- Modify: `backend/app/core/errors.py`
- Test: `tests/test_model_transport.py`

**Interfaces:**
- Produces `ModelConfig`, `FreeChatRequest`, `ProviderPreset`, `ModelTestResult`, `resolve_public_endpoint(url)`, `open_model_request(request)` 和 `iter_sse_data(response)`，后续模型客户端、测试路由和服务层只依赖这些接口。
- `ModelConfig.from_payload(payload: Mapping[str, object]) -> ModelConfig` 必须拒绝缺字段、不安全 URL、嵌入凭据和非法模型 ID；`api_key` 字段使用 `repr=False`，任何 `str(config)` 或异常都不得包含 Key。
- `FreeChatRequest` contains `message: str` and `model: ModelConfig`; it lives in the free-chat contract module, never in `contracts/game.py`.
- `iter_sse_data(response: Iterable[bytes | str]) -> Iterator[str]` 处理 `data:` 多行帧、CRLF/LF、空帧、`[DONE]` 和末尾无空行的帧。

- [ ] **Step 1: Write the failing tests**

```python
def test_model_config_rejects_http_private_and_embedded_credentials():
    for url in (
        "http://provider.example/v1",
        "https://127.0.0.1/v1",
        "https://192.168.1.10/v1",
        "https://user:pass@provider.example/v1",
    ):
        with pytest.raises(ValueError):
            ModelConfig.from_payload({"endpoint": url, "model": "demo", "api_key": "secret"})


def test_model_config_does_not_expose_key_in_repr_or_diagnostic_endpoint():
    config = ModelConfig.from_payload({
        "endpoint": "https://provider.example/v1",
        "model": "demo",
        "api_key": "secret-key",
    })
    assert "secret-key" not in repr(config)
    assert config.diagnostic_endpoint == "https://provider.example/v1/chat/completions"


def test_sse_parser_handles_multiline_data_and_done_marker():
    frames = list(iter_sse_data([
        b"data: {\"a\":\n",
        b"data: 1}\r\n\r\n",
        b"data: [DONE]\n\n",
    ]))
    assert frames == ['{"a":\n1}']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_model_transport.py -q`

Expected: FAIL because `backend.app.contracts.model` and `backend.app.core.model_transport` do not exist.

- [ ] **Step 3: Implement the minimal shared layer**

Implement `ModelConfig` with fields `endpoint: str`, `model: str`, `api_key: str = Field(repr=False)`, `timeout: float = 30.0`; normalize a base URL by appending `/chat/completions`, require HTTPS, and reject URL credentials, query and fragment. `resolve_public_endpoint(url)` resolves the host once per request and rejects every loopback, link-local, private or reserved result. `open_model_request(request)` must connect to one of those validated IPs while preserving the original hostname for the HTTP Host header and TLS SNI/certificate check; do not validate one DNS result then let the HTTP library resolve the host again. Reject redirects. Move the existing `_chat_sse_data` algorithm from `backend/app/core/model_client.py` into `iter_sse_data` and keep byte decoding and frame flushing in one place. Add `ModelProviderError` fields for `status_code`, `provider_code`, `provider_request_id`, and a sanitized `retry_after`, with a `public_message` mapper for 400/401/403/404/429/5xx. Define `FreeChatRequest` in this module so Key-bearing input never enters the story/game contracts.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_model_transport.py -q`

Expected: PASS with URL validation, Key redaction, and SSE framing covered.

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts/model.py backend/app/core/model_transport.py backend/app/core/errors.py tests/test_model_transport.py
git commit -m "feat: add shared model transport contracts"
```

### Task 2: Make `LiveModelClient` accept ephemeral configuration and share transport

**Files:**
- Modify: `backend/app/core/model_client.py`
- Modify: `tests/test_model_client.py`

**Interfaces:**
- `LiveModelClient(config: ModelConfig | None = None, *, timeout: float | None = None)` uses the supplied config for user-configured free chat. Existing environment-backed construction remains available only for internal/deployment compatibility and must never be selected for a browser request implicitly.
- `generate_chat` and `generate_chat_stream` use `iter_sse_data`, `ModelConfig.endpoint`, and a no-redirect opener. `diagnostic_endpoint` may be returned in safe error details; `api_key` may not.

- [ ] **Step 1: Add failing client tests**

Add tests that instantiate `LiveModelClient(ModelConfig(...))`, monkeypatch DNS resolution and the socket connector to prove a public IP is pinned while Host/SNI keep the original domain, assert the Authorization header is sent only to the requested HTTPS endpoint, assert a 401/403/400/404/429/5xx response maps to the corresponding public category, assert redirects are rejected, and assert streamed frames are parsed through `iter_sse_data` rather than a second provider parser.

- [ ] **Step 2: Run the focused tests**

Run: `python -m pytest tests/test_model_client.py -q`

Expected: FAIL on the new constructor and transport expectations.

- [ ] **Step 3: Implement the client integration**

Replace the environment-only fields in `LiveModelClient.__init__` with the injected `ModelConfig` when present. Keep the existing response normalizer and character prompt unchanged. Replace `_chat_sse_data(response)` with `iter_sse_data(response)`, route all requests through the shared no-redirect opener, and preserve safe provider request IDs only when they match the existing allow-list. Do not include response bodies or headers containing Key-like strings in exceptions or logs.

- [ ] **Step 4: Run the focused and regression tests**

Run: `python -m pytest tests/test_model_client.py tests/test_core_contracts.py -q`

Expected: PASS, including existing JSON normalization, reply length, and streaming cancellation tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/model_client.py tests/test_model_client.py
git commit -m "feat: inject ephemeral model configuration into client"
```

### Task 3: Add provider metadata/test endpoints and ephemeral chat request contracts

**Files:**
- Create: `backend/app/api/routes/model.py`
- Modify: `backend/app/api/routes/chat.py`
- Modify: `backend/app/main.py`
- Test: `tests/test_model_api.py`

**Interfaces:**
- `GET /api/model/providers` returns only preset IDs, labels, endpoint labels, and default model IDs; it never returns a Key or deployment secret.
- `POST /api/model/test` accepts `{endpoint, model, api_key}` and performs one bounded non-streaming request with `Cache-Control: no-store`; it returns `{ok, model, endpoint}` or the standard error envelope.
- `FreeChatRequest`, stream requests, and regenerate requests require a `model` object matching `ModelConfig` input. The object is validated per request and never persisted.

- [ ] **Step 1: Write failing API tests**

```python
def test_model_provider_metadata_has_no_secret_fields(client):
    response = client.get("/api/model/providers")
    assert response.status_code == 200
    assert all("api_key" not in item for item in response.json()["data"])


def test_model_test_requires_https_and_never_echoes_key(client):
    response = client.post("/api/model/test", json={
        "endpoint": "http://127.0.0.1:9/v1",
        "model": "demo",
        "api_key": "do-not-echo",
    })
    assert response.status_code == 400
    assert "do-not-echo" not in response.text
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_model_api.py -q`

Expected: FAIL because the router and request model do not exist.

- [ ] **Step 3: Implement routes and request parsing**

Add a router under `/api/model`, register it in `backend/app/main.py`, define a fixed in-source preset list with no credentials, and use `ModelConfig.from_payload` for custom values. The test endpoint must call the injected `LiveModelClient.generate_chat` with a minimal `ChatModelRequest`, return only safe metadata, and use `no-store` response headers. Parse free-chat JSON into `FreeChatRequest`; do not add model fields to `ChatMessageRequest` in `contracts/game.py`. Parse regenerate input into `ModelConfig`. Pass the same request-scoped configuration to sync, SSE and regenerate service calls.

- [ ] **Step 4: Run API tests**

Run: `python -m pytest tests/test_model_api.py tests/test_api.py -q`

Expected: PASS with request IDs and standard error envelopes intact.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/model.py backend/app/contracts/model.py backend/app/api/routes/chat.py backend/app/main.py tests/test_model_api.py
git commit -m "feat: expose safe model provider settings endpoints"
```

### Task 4: Remove free-chat fixture fallback and thread configuration through `SessionService`

**Files:**
- Modify: `backend/app/services/session_service.py`
- Modify: `backend/app/api/routes/chat.py`
- Modify: `tests/test_live_and_chat.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- `SessionService.chat_message(chat_id, message, model_config)` and `stream_chat_message(chat_id, message, stream_id, model_config)` create a fresh `LiveModelClient(model_config)` for each request.
- `SessionService.regenerate_chat(chat_id, model_config)` uses the same ephemeral config and never reads a Key from `SessionRepository`.
- Missing config raises `AppError("MODEL_NOT_CONFIGURED", ...)`; provider failures preserve their category; exhausted guard validation raises `INVALID_AI_RESPONSE` instead of `_fallback_chat_response`.

- [ ] **Step 1: Add failing service/API tests**

Cover missing model configuration, 401/403, 400/404, timeout/5xx, 429, malformed model output, synchronous chat, SSE chat, regenerate, and cancellation. Assert the response body never contains the submitted Key and that a failed live turn does not append a fixture reply to the database. Add a story test proving `/api/sessions/{id}/turn` remains deterministic and receives no model object.

- [ ] **Step 2: Run the new tests to verify failure**

Run: `python -m pytest tests/test_live_and_chat.py tests/test_api.py -q`

Expected: FAIL because the service still selects a cached mode client and converts errors to fixture replies.

- [ ] **Step 3: Implement request-scoped clients and explicit error mapping**

Add `_chat_client_for_config(model_config)` that returns `LiveModelClient(model_config)` and is not stored in `_chat_clients`. Thread the config through sync, streaming, and regenerate code. Replace every live-chat exception or exhausted response-guard fallback with the correct `AppError` code and safe details; no free-chat mode may surface fixture text after model failure. Public free-chat requests without config must stop before generation. Ensure stream events emit `{type: "error", code, message, details}` and never `{type: "done"}` for failures. Leave deterministic story replay and its domain contracts untouched.

- [ ] **Step 4: Run the service regression suite**

Run: `python -m pytest tests/test_live_and_chat.py tests/test_api.py tests/test_model_client.py -q`

Expected: PASS with no fixture response on provider failure and unchanged offline story behavior.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/session_service.py backend/app/api/routes/chat.py tests/test_live_and_chat.py tests/test_api.py
git commit -m "fix: require ephemeral live model for free chat"
```

### Task 5: Build mobile model settings, persistence and complete Key clearing

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `tests/frontend_behavior.test.cjs`
- Modify: `tests/test_frontend.py`

**Interfaces:**
- `appState.modelSettings` is memory-only unless `modelSettingsRemembered === true`.
- `loadModelSettings()`, `saveModelSettings()`, `clearModelSettings()`, `broadcastModelClear()`, and `renderModelSettings()` are the only UI paths that touch model settings.
- `ApiError` has `{code, message, details, requestId}` and `showActionableError(error, retry)` maps backend codes to visible actions.

- [ ] **Step 1: Add failing browser tests**

Extend `makeBrowser` to model `localStorage`, `sessionStorage`, `StorageEvent`, `BroadcastChannel`, fetch abort signals, and a model test response. Add tests for preset selection, custom endpoint/model/Key, `autocomplete="off"`/password input, unselected refresh loss, selected refresh restoration, clear from one tab clearing another tab, aborting model test/chat/retry requests, and actionable buttons for each error category. Assert `speechSynthesis` is not called when voice is unavailable during these chat tests.

- [ ] **Step 2: Run frontend tests to verify failure**

Run: `node --test tests/frontend_behavior.test.cjs`

Expected: FAIL because no model settings route, state, or actionable error controls exist.

- [ ] **Step 3: Implement settings state and route**

Add a `#/settings/model` route reachable from free chat. Fetch `/api/model/providers` with `{cache: "no-store"}`; selecting a preset fills endpoint/model but never Key. Keep Key in a local variable/state object, write only a namespaced JSON record to `localStorage` when the checkbox is checked, and remove that record plus any legacy session-storage key on clear. Register `window.storage` and `BroadcastChannel` listeners so every same-origin tab clears fields, pending model test/chat/regenerate/retry requests and stops any current voice work. Use `autocomplete="off"` on the form and `autocomplete="new-password"`/`type="password"` for the Key field.

- [ ] **Step 4: Thread model settings and actionable errors through chat UI**

Include a sanitized model object in `requestChatReply` and regenerate bodies. Add “测试连接”, “打开模型设置”, “检查 Key/权限”, “编辑模型设置”, “重试” and rate-limit wait actions based on `ApiError.code`. Preserve the chat draft on errors. Do not render the Key, endpoint query, or provider response body in error HTML. Keep `parseSseFrame`/`readSseEvents` as the sole frontend SSE implementation used by free chat.

- [ ] **Step 5: Run browser and syntax tests**

Run: `node --test tests/frontend_behavior.test.cjs; node --check frontend/app.js`

Expected: PASS with model settings, cross-tab clearing, error actions, and no automatic browser speech.

- [ ] **Step 6: Commit**

```bash
git add frontend/app.js frontend/index.html frontend/styles.css tests/frontend_behavior.test.cjs tests/test_frontend.py
git commit -m "feat: add mobile model settings and actionable chat errors"
```

### Task 6: Verify shared-layer and isolation invariants

**Files:**
- Modify: `tests/test_live_and_chat.py`
- Modify: `tests/test_model_client.py`
- Modify: `tests/frontend_behavior.test.cjs`

- [ ] **Step 1: Add invariant assertions**

Assert that `GameState`, `AIResponse`, `RoleplayEngineImpl`, and replay persistence never receive a model config; assert that free-chat `ChatResponse` never contains `next_scene`, `ending_id`, or `state_delta`; assert the backend provider boundary has exactly one `iter_sse_data` implementation and the browser application boundary has exactly one `readSseEvents` implementation. Story replay remains JSON/offline and must not add an SSE parser.

- [ ] **Step 2: Run the complete model/chat verification**

Run: `python -m pytest tests/test_model_transport.py tests/test_model_api.py tests/test_model_client.py tests/test_live_and_chat.py tests/test_api.py -q; node --test tests/frontend_behavior.test.cjs; node --check frontend/app.js`

Expected: PASS with both product paths isolated and shared transport behavior covered.

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_and_chat.py tests/test_model_client.py tests/frontend_behavior.test.cjs
git commit -m "test: enforce model transport and domain isolation"
```

## Self-Review Checklist

- The plan covers provider metadata, user-selected model config, all chat paths, Key lifecycle, error-to-action UI, no fixture fallback, one parser per SSE protocol boundary, and story isolation.
- No step relies on a real API Key, real provider, or local model file.
- Every request path names its exact config and error contract; no task depends on a database field for Key storage.
