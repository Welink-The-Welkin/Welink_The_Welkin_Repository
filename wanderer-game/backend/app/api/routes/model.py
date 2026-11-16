"""Public provider metadata and one-shot model connection checks."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from backend.app.contracts.model import ModelConfig, ModelTestResult, ProviderPreset
from backend.app.core.errors import ModelProviderError, ModelTimeoutError
from backend.app.core.model_client import LiveModelClient
from backend.app.errors import AppError

router = APIRouter(prefix="/model")

# This catalogue contains display metadata only. Users provide their own Key.
_PROVIDERS = (
    ProviderPreset(
        id="deepseek",
        label="DeepSeek",
        endpoint="https://api.deepseek.com/v1",
        default_model=LiveModelClient.DEFAULT_MODEL_NAME,
    ),
)


@router.get("/providers")
def list_providers(request: Request):
    return {"data": [provider.model_dump() for provider in _PROVIDERS], "request_id": request.state.request_id}


def _read_model_config(payload: object) -> ModelConfig:
    try:
        return ModelConfig.from_payload(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise AppError("INVALID_REQUEST", "模型设置无效，请检查 HTTPS 地址、模型 ID 和 API Key。", 400) from exc


@router.post("/test")
async def test_model_connection(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        config = _read_model_config(payload)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AppError("INVALID_REQUEST", "模型设置无效，请检查 HTTPS 地址、模型 ID 和 API Key。", 400) from exc
    try:
        factory = getattr(request.app.state, "model_test_client_factory", LiveModelClient)
        client = factory(config)
        client.test_connection()
    except ModelTimeoutError as exc:
        raise AppError("MODEL_TIMEOUT", "模型服务响应超时。", 504) from exc
    except ModelProviderError as exc:
        if getattr(exc, "configuration_error", False) or exc.status_code in {400, 404}:
            if getattr(exc, "configuration_error", False):
                message = "模型接口地址无效或无法安全连接，请编辑模型设置。"
            else:
                message = f"模型服务拒绝了请求（HTTP {exc.status_code}）。请核对模型名称和服务商接口地址。"
            raise AppError("MODEL_CONFIGURATION_ERROR", message, 400) from exc
        details = {"provider_status": exc.status_code} if exc.status_code is not None else {}
        if exc.retry_after is not None:
            details["retry_after"] = exc.retry_after
        if exc.status_code is None:
            details["endpoint"] = config.diagnostic_endpoint
        raise AppError("MODEL_PROVIDER_ERROR", exc.user_message, 502, details=details or None) from exc
    except Exception as exc:
        raise AppError("MODEL_PROVIDER_ERROR", "模型服务暂时不可用，请检查模型设置后重试。", 502) from exc

    result = ModelTestResult(ok=True, model=config.model, endpoint=config.diagnostic_endpoint)
    return {"data": result.model_dump(), "request_id": request.state.request_id}
