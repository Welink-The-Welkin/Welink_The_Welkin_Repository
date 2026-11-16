# 本文件由 codex 辅助生成（外围模块）
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import ValidationError

from backend.app.contracts.game import CreateSessionRequest, TurnRequest
from backend.app.errors import AppError

router = APIRouter()


def _service(request: Request):
    return request.app.state.session_service


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(request: Request, payload: CreateSessionRequest | None = None):
    state, last_response, mode, replay_id, ending = _service(request).create(
        payload.mode if payload else None,
        payload.replay_id if payload else None,
        payload.player_name if payload else "同行者",
    )
    return {"data": {"session_id": str(state.session_id), "state": state, "last_response": last_response, "mode": mode, "replay_id": replay_id, "ending": ending}, "request_id": request.state.request_id}


@router.get("/sessions/{session_id}")
def get_session(session_id: UUID, request: Request):
    state, last_response, mode, replay_id, ending = _service(request).get(session_id)
    return {"data": {"session_id": str(session_id), "state": state, "last_response": last_response, "mode": mode, "replay_id": replay_id, "ending": ending}, "request_id": request.state.request_id}


@router.post("/sessions/{session_id}/turn")
async def submit_turn(session_id: UUID, request: Request):
    try:
        payload = TurnRequest.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise AppError("INVALID_REQUEST", "请选择一个有效选项", 400) from exc
    # 剧情旅途只接受预设选项，玩家自定义文本不再被受理。
    state, response, ending = _service(request).turn(session_id, None, payload.option_id)
    return {"data": {"response": response, "state": state, "ending": ending}, "request_id": request.state.request_id}


@router.post("/sessions/{session_id}/restart", status_code=status.HTTP_201_CREATED)
def restart_session(session_id: UUID, request: Request):
    state, last_response, mode, replay_id, ending = _service(request).restart(session_id)
    return {"data": {"session_id": str(state.session_id), "state": state, "last_response": last_response, "mode": mode, "replay_id": replay_id, "ending": ending}, "request_id": request.state.request_id}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: UUID, request: Request):
    if not _service(request).delete(session_id):
        raise AppError("SESSION_NOT_FOUND", "会话不存在或已过期", 404)
    return {"data": {"deleted": True}, "request_id": request.state.request_id}
