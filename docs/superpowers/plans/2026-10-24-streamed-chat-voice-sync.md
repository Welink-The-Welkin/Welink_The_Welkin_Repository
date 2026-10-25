# 浮浪倾客流式文本与语音同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让自由对话以 SSE 分段缓存，在对应语音真实触发 `playing` 时同步释放文字，并通过有界预取消除句间额外合成停顿。

**Architecture:** LiveModelClient 读取 OpenAI 兼容 SSE，增量提取 JSON 的 `reply` 字段；SessionService 在保留最终契约校验、守门和入库的同时产出文本片段；聊天路由在客户端请求 SSE 时返回 `text` 与 `done` 事件，普通 JSON 请求继续兼容。前端将 SSE 消费与顺序播放解耦，用“当前段 + 下一段”的两段窗口预生成语音；每段文字只由匹配音频的真实 `playing` 事件释放。取消或删除时同时中止 fetch、清空预取队列并停止音频。

**Tech Stack:** FastAPI `StreamingResponse`, Python `urllib`, browser `ReadableStream`, existing GPT-SoVITS `/api/voice/stream`, pytest, Node test runner.

**Spec:** 用户确认的“后端 SSE 分段 + 前端文本先显示、对应语音排队播放、取消立即清理”方案。

## Global Constraints

- 保留现有普通 JSON 聊天接口与离线 DeterministicModelClient。
- 最终保存的回复必须经过现有 ChatResponse、人称守门和语言守门。
- 每段缓存文字只能由对应音频的真实 `playing` 事件释放；不得以 `canplay`、`play()` Promise 或定时器代替。
- 语音播放保持原文顺序，同时只允许“当前段 + 下一段”两段有界预取。
- 每次角色回复保持为一个连续自然段；模型换行在进入 SSE、语音队列和历史记录前移除，不得生成空白语音片段。
- 取消、删除、重生成不得让迟到的流事件恢复旧界面或继续播报。

---

### Task 1: Model stream parsing

**Files:**
- Modify: `backend/app/core/model_client.py`
- Test: `tests/test_model_client.py`

- [x] Add tests for OpenAI SSE `delta.content` parsing, incremental `reply` extraction, punctuation/length chunking, and stream request payload.
- [x] Run the focused tests and confirm they fail because no stream API exists.
- [x] Add `generate_chat_stream()` to deterministic and live clients plus a bounded reply chunker and SSE parser; keep `_request_json()` unchanged for JSON fallback.
- [x] Run focused model tests and confirm they pass.

### Task 2: Streaming service and route

**Files:**
- Modify: `backend/app/services/session_service.py`
- Modify: `backend/app/api/routes/chat.py`
- Test: `tests/test_live_and_chat.py`

- [x] Add a failing SSE route test asserting text events precede `done`, the final response is saved, and client disconnect does not save a partial message.
- [x] Implement a generator that accumulates streamed reply text, applies the existing final guards, saves only a completed response, and emits JSON SSE events.
- [x] Return `StreamingResponse` only for `Accept: text/event-stream`; preserve the existing JSON response otherwise.
- [x] Run focused backend tests and then the full Python suite.

### Task 3: Frontend stream and speech backpressure

**Files:**
- Modify: `frontend/app.js`
- Test: `tests/frontend_behavior.test.cjs`

- [x] Add failing browser-harness tests for SSE event ordering, bounded speech lookahead, `playing`-gated text release, long replies, and abort cleanup.
- [x] Implement SSE parsing, temporary streaming assistant state, a two-item preparation window, and ordered playback so each chunk is released by its audio's `playing` event while the next chunk synthesizes in advance.
- [x] Route stream failures to the existing JSON request fallback and retain current pause/delete/voice controls.
- [x] Run the focused Node tests and `node --check frontend/app.js`.

### Task 4: Integrated verification

- [x] Run all Python tests with an in-repository basetemp, all frontend tests, syntax checks, and `git diff --check`.
- [x] Inspect the final diff for accidental changes and document the restart requirement for old server processes.
