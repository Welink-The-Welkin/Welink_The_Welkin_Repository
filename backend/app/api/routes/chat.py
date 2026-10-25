# 本文件由 codex 辅助生成（外围模块）
import json
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from backend.app.contracts.game import ChatCreateRequest, ChatMessageRequest
from backend.app.errors import AppError

router = APIRouter()


def _service(request: Request):
    return request.app.state.session_service


@router.post("/chat/sessions", status_code=201)
def create_chat(request: Request, payload: ChatCreateRequest | None = None):
    player_name = payload.player_name if payload else "同行者"
    chat_id, mode = _service(request).create_chat(payload.mode if payload else None, player_name)
    return {"data": {"chat_session_id": str(chat_id), "mode": mode, "player_name": player_name, "title": "新对话", "messages": []}, "request_id": request.state.request_id}


@router.get("/chat/sessions/{chat_session_id}")
def get_chat(chat_session_id: UUID, request: Request):
    mode, messages, player_name, title = _service(request).get_chat(chat_session_id)
    return {"data": {"chat_session_id": str(chat_session_id), "mode": mode, "player_name": player_name, "title": title, "messages": messages}, "request_id": request.state.request_id}


@router.delete("/chat/sessions/{chat_session_id}")
def delete_chat(chat_session_id: UUID, request: Request):
    if not _service(request).delete_chat(chat_session_id):
        raise AppError("CHAT_SESSION_NOT_FOUND", "自由对话会话不存在或已过期", 404)
    return {"data": {"deleted": True}, "request_id": request.state.request_id}


@router.post("/chat/sessions/{chat_session_id}/messages")
async def send_chat_message(chat_session_id: UUID, request: Request):
    try:
        payload = ChatMessageRequest.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise AppError("INVALID_REQUEST", "请输入有效的对话内容", 400) from exc
    if "text/event-stream" in request.headers.get("accept", "").lower():
        stream_id = request.headers.get("x-chat-stream-id") or request.state.request_id

        def event_source():
            for event in _service(request).stream_chat_message(chat_session_id, payload.message, stream_id=stream_id):
                yield f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    response, messages = _service(request).chat_message(chat_session_id, payload.message)
    return {"data": {"response": response, "game_state": None, "messages": messages}, "request_id": request.state.request_id}

@router.post("/chat/sessions/{chat_session_id}/regenerate")
def regenerate_chat_message(chat_session_id: UUID, request: Request):
    response, messages = _service(request).regenerate_chat(chat_session_id)
    return {"data": {"response": response, "game_state": None, "messages": messages}, "request_id": request.state.request_id}
