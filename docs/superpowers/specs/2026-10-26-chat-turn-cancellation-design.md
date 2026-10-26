# Free-chat Turn Cancellation Design

## Goal

When the player pauses a pending free-chat turn, stop its provider generation, discard it, and prevent it from appearing in the session history. The player can edit the restored input and send another turn in the same chat. The paused state must use the exact copy: “「浮浪倾客」的话戛然而止，略表腻烦的眼神随清风飘来，示意你接上这场被打断的对话。”

## Current Evidence

- `frontend/app.js` gives each turn an ID in the SSE request header and aborts the browser fetch from `pauseChat()`.
- `SessionService` keeps controls in an in-memory registry and has a `cancel_chat_stream()` method, but the chat API has no endpoint that calls it.
- Provider-stream failures can currently fall back to ordinary non-stream generation. Unless cancellation is observed before that fallback and before persistence, a visually paused turn can continue and be saved.
- Existing tests cover pausing one new turn, but not pausing a later turn in a restored session and editing/resending it.

## Design

- Add a cancellation endpoint keyed by chat session and exact stream ID. Stream IDs use `<chat_session_id>-<positive request sequence>`. It may only cancel or reserve a matching turn in that session; if cancellation arrives before the SSE request registers, retain a bounded tombstone so the later stream cannot start.
- Bind the active provider response to the service cancellation control. On cancellation, close the response/request rather than closing a Python iterator from a different thread while it is executing; the owner thread closes the iterator in its `finally` block.
- Recheck the cancellation flag after provider read errors and before JSON fallback, final event publishing, and database persistence. Serialize cancellation versus commit so a cancel that wins the control lock prevents the turn write. A turn already committed before the cancellation request is received is treated as completed, not removed from history.
- On pause, the frontend immediately stops the local SSE reader and speech queue, restores the user's editable draft, and sends a separate keepalive cancellation request for that stream ID. A resubmission from this paused state waits until the cancellation request settles. Every new turn gets a fresh ID; stale request handlers cannot modify the new turn's UI state.
- Keep the interrupted turn temporary and absent from persisted history; the follow-up request sends only committed history. Do not render any abandoned assistant output in paused markup.
- Replace the old paused label with the exact sentence above.

## Interfaces

- `POST /api/chat/sessions/{chat_session_id}/cancel` with `X-Chat-Stream-ID` returns `{"data":{"cancelled":bool}}`.
- `SessionService.cancel_chat_stream(stream_id, chat_id=...)` remains the service boundary and validates session ownership.
- Frontend pending state retains the stream ID alongside the message and draft snapshot.

## Error Handling

- A malformed, completed, or other-session ID does not change chat history. A valid session-scoped ID may return `cancelled: true` before stream registration because it reserves that turn against later generation.
- If the cancel HTTP call fails, local display/audio still stop; keep resubmission gated until the attempt settles and show a recoverable error rather than pretending the server confirmed cancellation.
- Preserve ordinary non-stream chat behavior and existing error envelopes.

## Verification

- Backend: block a provider stream, cancel it through the route, and assert no fallback, title update, or history write occurs; verify another session's stream is unaffected.
- Frontend: cover the first turn and a later turn in a restored session, checking exact stream IDs, abort/audio cleanup, draft editing, same-session resend, and absence of abandoned text/history.
- Run full Python and frontend suites, compile/syntax checks, and `git diff --check`.
