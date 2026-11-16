# 本文件由 codex 辅助生成（外围模块）
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    return {"data": {"status": "ok", "version": "0.2.0", "mode": request.app.state.mode}, "request_id": request.state.request_id}
