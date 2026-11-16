"""核心模块错误分类。

按「输入非法 / 响应非法 / 结局不一致 / 模型故障」四类细分，
供门面在不同阶段抛出，拒绝时携带可审计原因。
"""
from __future__ import annotations

import math
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone


class CoreError(RuntimeError):
    """所有核心错误的基类。"""


class InvalidTurnInputError(CoreError):
    """玩家输入非法（恰好一项约束、非法会话标识）。"""


class SessionFinishedError(CoreError):
    """会话已结束，拒绝继续推进回合。"""


class TurnLimitExceededError(CoreError):
    """回合数已达上限，拒绝继续推进。"""


class InvalidOptionError(CoreError):
    """选项无法解析或不属于当前可选集合。"""


class InvalidAIResponseError(CoreError, ValueError):
    """模型原始响应或规范化后的响应非法。"""


class InconsistentTurnResultError(CoreError):
    """终局状态、响应标志与结局标识相互矛盾。"""


class ModelTimeoutError(CoreError):
    """模型调用超时。"""


class ModelProviderError(CoreError):
    """模型供应商不可用或返回错误。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        user_message: str | None = None,
        provider_code: str | None = None,
        provider_request_id: str | None = None,
        retry_after: str | float | int | None = None,
        configuration_error: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.public_message = user_message or self._public_message_for_status(status_code)
        self.user_message = self.public_message
        self.provider_code = provider_code
        self.provider_request_id = provider_request_id
        self.retry_after = self._parse_retry_after(retry_after)
        self.configuration_error = bool(configuration_error)

    @staticmethod
    def _public_message_for_status(status_code: int | None) -> str:
        if status_code in {401, 403}:
            return f"模型服务拒绝了请求（HTTP {status_code}）。请检查 API Key、账户权限和服务商设置。"
        if status_code in {400, 404}:
            return f"模型服务无法识别请求（HTTP {status_code}）。请检查模型 ID 和接口地址。"
        if status_code == 429:
            return "模型服务当前限流或账户额度不足（HTTP 429）。请稍后重试，或检查服务商账户额度。"
        if status_code is not None and 500 <= status_code <= 599:
            return f"模型服务暂时发生故障（HTTP {status_code}）。请稍后重试。"
        return "模型服务暂时不可用，请检查实时接口配置后重试。"

    @staticmethod
    def _parse_retry_after(value: str | float | int | None) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            if not isinstance(value, str):
                return None
            try:
                target = parsedate_to_datetime(value)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                seconds = (target - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        if not math.isfinite(seconds) or seconds < 0 or seconds > 86400:
            return None
        return seconds
