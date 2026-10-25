from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.app.errors import AppError
from backend.app.voice import VoiceUnavailableError, stream_voice, synthesize_voice, voice_status


class VoiceSynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value


router = APIRouter()


@router.get("/voice/status")
def get_voice_status(request: Request):
    return {"data": voice_status(), "request_id": request.state.request_id}


@router.post("/voice/synthesize")
async def synthesize(request: Request):
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
def stream(text: str = Query(min_length=1, max_length=1000)):
    text = text.strip()
    if not text:
        raise AppError("INVALID_REQUEST", "请输入有效的语音文本", 400)
    try:
        audio = stream_voice(text)
    except VoiceUnavailableError as exc:
        raise AppError("VOICE_UNAVAILABLE", "语音服务暂不可用，文字对话仍可继续", 503) from exc
    return StreamingResponse(audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=31536000"})
