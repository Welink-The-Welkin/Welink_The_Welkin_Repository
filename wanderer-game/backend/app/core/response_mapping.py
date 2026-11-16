# 本文件由 codex 辅助生成（外围模块）
"""响应规范化与状态映射。

保留 `ResponseStateMapperPlaceholder` 以满足既有守卫测试；
新增 `ResponseStateMapperImpl` 承载核心行为。
"""
from typing import Mapping, Protocol

from pydantic import ValidationError

from backend.app.contracts.ai import AIResponse
from backend.app.contracts.game import GameState
from backend.app.core.clock import Clock, SystemClock
from backend.app.core.errors import InvalidAIResponseError

_ALLOWED_DELTA_KEYS = {"trust", "compassion", "responsibility"}
_ALLOWED_RESPONSE_KEYS = {"reply", "emotion", "state_delta", "next_scene", "is_ending", "ending_id"}
_REQUIRED_RESPONSE_KEYS = ("reply", "emotion", "next_scene", "is_ending")


class ResponseStateMapper(Protocol):
    def normalize_response(self, *, raw_response: Mapping[str, object]) -> AIResponse: ...

    def apply(self, *, state: GameState, response: AIResponse) -> GameState: ...


class ResponseStateMapperPlaceholder:
    def normalize_response(self, *, raw_response: Mapping[str, object]) -> AIResponse:
        raise RuntimeError("response normalization is delegated to CodeArts Agent")

    def apply(self, *, state: GameState, response: AIResponse) -> GameState:
        raise RuntimeError("response-to-state mapping is delegated to CodeArts Agent")


def _clamp_delta(value: int) -> int:
    return max(-10, min(10, value))


def _clamp_metric(value: int) -> int:
    return max(0, min(100, value))


class ResponseStateMapperImpl:
    """把模型原始响应规范化为受校验的 AIResponse，并把状态变化应用到 GameState。"""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()

    def normalize_response(self, *, raw_response: Mapping[str, object]) -> AIResponse:
        if not isinstance(raw_response, Mapping):
            raise InvalidAIResponseError("raw_response must be a mapping of response fields")

        for key in _REQUIRED_RESPONSE_KEYS:
            if key not in raw_response:
                raise InvalidAIResponseError(f"raw_response is missing required field: {key}")

        unknown_keys = [key for key in raw_response if key not in _ALLOWED_RESPONSE_KEYS]
        if unknown_keys:
            raise InvalidAIResponseError(
                f"raw_response contains unsupported field(s): {sorted(unknown_keys)}"
            )

        raw_delta = raw_response.get("state_delta", {})
        if raw_delta is None:
            raw_delta = {}
        if not isinstance(raw_delta, Mapping):
            raise InvalidAIResponseError("state_delta must be a mapping of integer deltas")

        bounded_delta: dict[str, int] = {}
        for key, value in raw_delta.items():
            if key not in _ALLOWED_DELTA_KEYS:
                raise InvalidAIResponseError(f"state_delta contains an unsupported field: {key}")
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidAIResponseError(
                    f"state_delta field {key} must be an integer, got {type(value).__name__}"
                )
            bounded_delta[key] = _clamp_delta(value)

        payload = dict(raw_response)
        payload["state_delta"] = bounded_delta
        try:
            return AIResponse(**payload)
        except ValidationError as exc:
            raise InvalidAIResponseError(f"raw_response failed contract validation: {exc}") from exc

    def apply(self, *, state: GameState, response: AIResponse) -> GameState:
        updates: dict[str, int] = {}
        for key, delta in response.state_delta.items():
            if key not in _ALLOWED_DELTA_KEYS:
                continue
            updates[key] = _clamp_metric(getattr(state, key) + delta)
        updates["updated_at"] = self._clock.now()
        return state.model_copy(update=updates)