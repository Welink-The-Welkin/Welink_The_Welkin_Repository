from itertools import chain
from threading import Lock

import anyio
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.app.errors import AppError
from backend.app.voice import VoiceUnavailableError, stream_voice, synthesize_voice, voice_status


class VoiceSynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value


router = APIRouter()


class _OwnedAudio:
    """Serialize producer advancement and closure across response workers."""

    def __init__(self, producer):
        self.producer = producer
        self.lock = Lock()
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        with self.lock:
            if self.closed:
                raise StopIteration
            return next(self.producer)

    def close(self):
        # Raw task cancellation can abandon a worker that is still in next().
        # Wait for that worker before closing a generator it may be executing.
        with self.lock:
            if not self.closed:
                self.closed = True
                close = getattr(self.producer, "close", None)
                if close:
                    close()


class VoiceStreamingResponse(StreamingResponse):
    """Own a primed producer until ASGI sending completes or aborts."""

    def __init__(self, audio, first):
        self.audio = _OwnedAudio(audio)
        super().__init__(chain((first,), self.audio), media_type="audio/wav", headers={"Cache-Control": "private, max-age=31536000"})

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        except BaseExceptionGroup as group:
            # AnyIO 4 wraps a single transport/send failure raised inside
            # Starlette's response task group. Preserve the original
            # exception contract for callers while retaining multi-error
            # groups for diagnosis.
            if len(group.exceptions) == 1:
                raise group.exceptions[0] from None
            raise
        finally:
            close = getattr(self.audio, "close", None)
            if close:
                # The sync producer owns the HTTP response, staging file and
                # cache lock. Close even when cancellation interrupts sending.
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(close)


@router.get("/voice/status")
def get_voice_status(request: Request, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return {"data": voice_status(), "request_id": request.state.request_id}


@router.post("/voice/synthesize")
async def synthesize(request: Request):
    if request.query_params:
        raise AppError("INVALID_REQUEST", "请输入有效的语音文本", 400)
    try:
        payload = VoiceSynthesisRequest.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise AppError("INVALID_REQUEST", "请输入有效的语音文本", 400) from exc

    try:
        audio = synthesize_voice(payload.text)
    except VoiceUnavailableError as exc:
        raise AppError("VOICE_UNAVAILABLE", "语音服务暂不可用，文字对话仍可继续", 503) from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=31536000"})


@router.get("/voice/stream")
def stream(request: Request, text: str = Query(min_length=1, max_length=1000)):
    if set(request.query_params) != {"text"} or len(request.query_params.getlist("text")) != 1:
        raise AppError("INVALID_REQUEST", "请输入有效的语音文本", 400)
    text = text.strip()
    if not text:
        raise AppError("INVALID_REQUEST", "请输入有效的语音文本", 400)
    try:
        audio = stream_voice(text)
        # The producer validates a complete WAV header before its first yield.
        first = next(audio)
    except (VoiceUnavailableError, StopIteration) as exc:
        raise AppError("VOICE_UNAVAILABLE", "语音服务暂不可用，文字对话仍可继续", 503) from exc
    return VoiceStreamingResponse(audio, first)
