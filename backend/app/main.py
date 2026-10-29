# 本文件由 codex 辅助生成（外围模块）
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import background, chat, health, sessions, voice
from backend.app.config import database_path, demo_mode
from backend.app.errors import AppError
from backend.app.services.session_service import SessionService
from backend.app.storage.database import create_database
from backend.app.storage.session_repository import SessionRepository

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def create_app(database_path_override=None, demo_mode_override: str | None = None) -> FastAPI:
    app = FastAPI(title="浮浪倾客：风起异途", version="0.2.0")
    mode = demo_mode_override or demo_mode()
    connection = create_database(database_path_override or database_path())
    app.state.mode = mode
    app.state.session_service = SessionService(SessionRepository(connection), mode)
    app.state.database = connection

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}, "request_id": request.state.request_id},
        )

    @app.get("/api/openapi.json")
    def custom_openapi():
        return app.openapi()

    app.include_router(health.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(voice.router, prefix="/api")
    app.include_router(background.router)

    if FRONTEND.exists():
        app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            candidate = (FRONTEND / path).resolve()
            if candidate.is_file() and FRONTEND.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(FRONTEND / "index.html")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
