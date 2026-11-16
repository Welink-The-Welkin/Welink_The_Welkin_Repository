# 本文件由 codex 辅助生成（外围模块）
"""角色对话引擎门面。

保留 `RoleplayEnginePlaceholder` 以满足既有守卫测试；
新增 `RoleplayEngineImpl` 编排「输入校验 → 模型 → 规范化 → 状态映射 → 场景推进 → 结局判定」。
"""
from typing import Protocol
from uuid import UUID

from backend.app.contracts.ai import CoreTurnResult
from backend.app.contracts.game import GameState, initial_state
from backend.app.core.character_profile import (
    DEFAULT_CHARACTER_PROFILE,
    CharacterProfile,
)
from backend.app.core.clock import Clock, SystemClock
from backend.app.core.ending_catalog import EndingCatalog
from backend.app.core.errors import (
    InconsistentTurnResultError,
    InvalidOptionError,
    InvalidTurnInputError,
    ModelProviderError,
    ModelTimeoutError,
    SessionFinishedError,
    TurnLimitExceededError,
)
from backend.app.core.model_client import (
    DeterministicModelClient,
    ModelClient,
    ModelRequest,
)
from backend.app.core.response_mapping import ResponseStateMapperImpl
from backend.app.core.state_machine import GameStateMachineImpl

_MAX_TURNS = 30


class RoleplayEngine(Protocol):
    def handle_turn(
        self,
        *,
        state: GameState,
        player_message: str | None,
        option_id: str | None,
    ) -> CoreTurnResult: ...

    def create_initial_state(self, *, session_id: str) -> GameState: ...


class CoreNotImplementedError(RuntimeError):
    """交给 CodeArts Agent 的核心模块尚未实现。"""


class RoleplayEnginePlaceholder:
    def handle_turn(self, *, state: GameState, player_message: str | None, option_id: str | None) -> CoreTurnResult:
        raise CoreNotImplementedError("roleplay engine is delegated to CodeArts Agent")

    def create_initial_state(self, *, session_id: str) -> GameState:
        raise CoreNotImplementedError("roleplay engine is delegated to CodeArts Agent")


class RoleplayEngineImpl:
    def __init__(
        self,
        *,
        model_client: ModelClient | None = None,
        mapper: ResponseStateMapperImpl | None = None,
        state_machine: GameStateMachineImpl | None = None,
        clock: Clock | None = None,
        catalog: EndingCatalog | None = None,
        character_profile: CharacterProfile | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._catalog = catalog or EndingCatalog()
        self._mapper = mapper or ResponseStateMapperImpl(clock=self._clock)
        self._state_machine = state_machine or GameStateMachineImpl(
            clock=self._clock, catalog=self._catalog
        )
        self._model_client = model_client or DeterministicModelClient()
        self._profile = character_profile or DEFAULT_CHARACTER_PROFILE

    def create_initial_state(self, *, session_id: str) -> GameState:
        try:
            parsed_session_id = UUID(session_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise InvalidTurnInputError(
                f"session_id must be a valid UUID string, got {session_id!r}"
            ) from exc
        return initial_state(session_id=parsed_session_id)

    def handle_turn(
        self,
        *,
        state: GameState,
        player_message: str | None,
        option_id: str | None,
    ) -> CoreTurnResult:
        has_message = player_message is not None and bool(player_message.strip())
        has_option = option_id is not None
        if has_message == has_option:
            raise InvalidTurnInputError(
                "provide exactly one non-empty player_message or option_id"
            )
        if state.is_finished:
            raise SessionFinishedError("session is already finished")
        if state.turn_count >= _MAX_TURNS:
            raise TurnLimitExceededError(
                f"turn limit reached: turn_count={state.turn_count} cannot exceed {_MAX_TURNS}"
            )

        request = ModelRequest(
            character_profile=self._profile,
            state_snapshot=state,
            player_message=player_message if has_message else None,
            option_id=option_id if has_option else None,
        )
        try:
            raw_response = self._model_client.generate(request=request)
        except (ModelTimeoutError, ModelProviderError, InvalidOptionError):
            raise
        except Exception as exc:
            raise ModelProviderError("model client failed to generate a response") from exc

        response = self._mapper.normalize_response(raw_response=raw_response)
        mapped_state = self._mapper.apply(state=state, response=response)
        advanced_state = self._state_machine.advance(
            state=state,
            turn_result=CoreTurnResult(response=response, state=mapped_state),
            player_input=option_id if has_option else player_message,
        )
        ending = self._state_machine.determine_ending(state=advanced_state)

        if response.is_ending != advanced_state.is_finished:
            raise InconsistentTurnResultError(
                "response ending flag contradicts the advanced state"
            )
        if response.is_ending:
            if (
                ending is None
                or advanced_state.ending_id is None
                or response.ending_id != advanced_state.ending_id
                or ending.ending_id != advanced_state.ending_id
            ):
                raise InconsistentTurnResultError(
                    "ending identifiers are inconsistent across response, state and ending"
                )
        else:
            if ending is not None or advanced_state.ending_id is not None:
                raise InconsistentTurnResultError(
                    "non-ending turn must not carry an ending or an ending id"
                )

        return CoreTurnResult(response=response, state=advanced_state, ending=ending)