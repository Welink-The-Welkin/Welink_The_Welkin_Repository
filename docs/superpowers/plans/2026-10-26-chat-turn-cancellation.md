# Free-chat Turn Cancellation Implementation Plan

> **For agentic workers:** Use this plan task by task with verification checkpoints. Keep unrelated dirty work intact.

**Goal:** Make pause cancel the exact active server generation, discard its reply, and permit edited resubmission in the same chat session.

**Architecture:** A session-scoped HTTP cancellation request addresses the current SSE ID. The service cancellation control marks the turn cancelled and closes the active provider response without cross-thread generator closure. The service prevents fallback and commits only while holding the control's commit/cancel lock; the browser aborts SSE/audio immediately and gates a subsequent submit until cancellation settles.

**Tech Stack:** FastAPI, Python threading and urllib, browser Fetch/SSE/AbortController, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-10-26-chat-turn-cancellation-design.md`

## Global Constraints

- A cancellation ID must be bound to its chat-session ID and cannot affect another chat.
- Cancelled turns must not trigger JSON fallback generation or save a message/title.
- The browser must stop local stream/audio, restore editable text, and gate a resubmission until the cancellation request settles.
- Paused-state copy must exactly equal “「浮浪倾客」的话戛然而止，略表腻烦的眼神随清风飘来，示意你接上这场被打断的对话。”
- A turn already committed before cancellation is received remains completed; cancelling it does not remove history.

---

### Task 1: Service cancellation regression

**Files:**
- Modify: `backend/app/core/model_client.py`
- Modify: `backend/app/services/session_service.py`
- Test: `tests/test_live_and_chat.py`

**Interfaces:** `_ChatStreamControl` binds one `ChatReplyEventStream`, supports idempotent cancellation, and protects the final persistence boundary with a lock. `ChatReplyEventStream.cancel()` signals its provider callback without closing the iterator from a different executing thread; its owner closes the iterator in `finally`.

- [ ] Write `test_cancelled_provider_stream_does_not_fallback_or_persist`: fake `generate_chat_stream` yields one text event, waits on a `threading.Event`, then raises; fake `generate_chat` records calls. Run service iteration in a worker thread, wait until the provider is blocked, call `cancel_chat_stream("turn-old", chat_id=chat_id)`, and assert the worker ends, fallback calls stay empty, and repository messages/title are unchanged.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q tests/test_live_and_chat.py::test_cancelled_provider_stream_does_not_fallback_or_persist --basetemp .pytest-basetemp-cancel-red`; confirm the failure is the unwanted fallback or history write, not fixture setup.
- [ ] Add a control-bound active-stream slot and cancellation/commit lock. Register the stream before iteration; cancellation sets the event and invokes only its provider callback; the service owner closes it.
- [ ] After stream exceptions, check cancellation before `_generate_chat`; check again before final publish and inside the commit lock immediately before append/save.
- [ ] Run the new test and `tests/test_live_and_chat.py::test_free_chat_stream_does_not_persist_when_client_stops_before_done`.

### Task 2: Session-bound cancel API

**Files:**
- Modify: `backend/app/api/routes/chat.py`
- Test: `tests/test_live_and_chat.py`

**Interface:** `POST /api/chat/sessions/{chat_session_id}/cancel` takes `X-Chat-Stream-ID` in `<chat_session_id>-<positive request sequence>` form and returns `{"data":{"cancelled":true|false}}`.

- [ ] Write an API regression that registers `<session-one>-1` and `<session-two>-1` against two distinct UUID chat sessions, cancels session one's ID through the HTTP route, and asserts session two cannot cancel it. Also assert malformed and other-session IDs return `cancelled: false`, and an early valid ID reserves its turn.
- [ ] Run the test and confirm the missing route is the failure.
- [ ] Validate the header is non-empty and no longer than 128 characters; return the standard invalid-request envelope otherwise. Call `cancel_chat_stream` with both stream ID and route session UUID. When the service sees a positive sequence ID for that session before registration, store a bounded pre-cancellation control reused by the later stream.
- [ ] Run route, service-cancel, and existing streamed-message tests.

### Task 3: Browser pause and same-session resend

**Files:**
- Modify: `frontend/app.js`
- Test: `tests/frontend_behavior.test.cjs`

**Interfaces:** pending turn state stores `{message, streamId, ...}`; `pauseChat()` immediately aborts SSE/audio then retains a promise for the keepalive server-cancel request; `submitChat()` waits for that promise before issuing a new unique stream ID.

- [ ] Extend the browser harness to return an existing restored chat transcript, capture `/cancel` calls and headers, and defer cancellation acknowledgement.
- [ ] Write a test that pauses a later turn in the restored chat, edits the restored draft, attempts resubmission before acknowledgement, then resolves cancellation and verifies a new stream ID is sent and the prior turn's abandoned reply never appears in rendered or persisted messages.
- [ ] Write a separate test that pauses before receiving text and verifies the exact interrupted-dialogue copy, restored draft, no old reply, and aborted audio/SSE.
- [ ] Run each new test and confirm it catches current missing cancel call, stale-reply race, and incorrect paused copy.
- [ ] Add the separate `fetch` cancellation request with `keepalive: true`, preserve the response draft and cancellation promise across the old request's `finally`, and gate later submissions until the promise settles. Do not let old request handlers mutate a new pending turn.
- [ ] Replace paused copy with the exact sentence in the spec.
- [ ] Run `node tests/frontend_behavior.test.cjs` and `node --check frontend/app.js`.

### Task 4: Full verification

- [ ] Run `.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-basetemp-chat-cancel-verify`, `node tests/frontend_behavior.test.cjs`, `.venv\Scripts\python.exe -m compileall -q backend tests scripts`, `node --check frontend/app.js`, and `git diff --check`.
- [ ] Inspect `git diff -- backend/app/core/model_client.py backend/app/services/session_service.py backend/app/api/routes/chat.py frontend/app.js tests/test_live_and_chat.py tests/frontend_behavior.test.cjs`; do not stage or overwrite pre-existing work.
