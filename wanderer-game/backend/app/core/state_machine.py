# 本文件由 codex 辅助生成（外围模块）
"""场景推进与结局判定。

保留 `StateMachinePlaceholder` 以满足既有守卫测试；
新增 `GameStateMachineImpl` 作为场景、回合与结局的唯一裁决者。
"""
from typing import Protocol

from backend.app.contracts.ai import CoreTurnResult, EndingResult
from backend.app.contracts.game import GameState, HistoryItem
from backend.app.core.clock import Clock, SystemClock
from backend.app.core.ending_catalog import EndingCatalog
from backend.app.core.errors import (
    InconsistentTurnResultError,
    InvalidAIResponseError,
    TurnLimitExceededError,
)

_MAX_TURNS = 30
_MAX_HISTORY = 30


class GameStateMachine(Protocol):
    def advance(self, *, state: GameState, turn_result: CoreTurnResult, player_input: str | None = None) -> GameState: ...

    def determine_ending(self, *, state: GameState) -> EndingResult | None: ...


class StateMachinePlaceholder:
    def advance(self, *, state: GameState, turn_result: CoreTurnResult) -> GameState:
        raise RuntimeError("state machine is delegated to CodeArts Agent")

    def determine_ending(self, *, state: GameState) -> EndingResult | None:
        raise RuntimeError("ending logic is delegated to CodeArts Agent")


class GameStateMachineImpl:
    def __init__(self, *, clock: Clock | None = None, catalog: EndingCatalog | None = None) -> None:
        self._clock = clock or SystemClock()
        self._catalog = catalog or EndingCatalog()

    def advance(
        self,
        *,
        state: GameState,
        turn_result: CoreTurnResult,
        player_input: str | None = None,
    ) -> GameState:
        if state.turn_count >= _MAX_TURNS:
            raise TurnLimitExceededError(
                f"turn limit reached: turn_count={state.turn_count} cannot exceed {_MAX_TURNS}"
            )

        response = turn_result.response
        updates: dict[str, object] = {"turn_count": state.turn_count + 1}

        if response.is_ending:
            updates["is_finished"] = True
            updates["ending_id"] = response.ending_id
        else:
            if response.next_scene is None:
                raise InconsistentTurnResultError("non-ending response requires a next scene")
            updates["scene_id"] = response.next_scene.scene_id

        summary = turn_result.state
        if isinstance(summary, GameState):
            updates["trust"] = summary.trust
            updates["compassion"] = summary.compassion
            updates["responsibility"] = summary.responsibility

        history_item = HistoryItem(
            scene_id=state.scene_id,
            player_input=(player_input or "")[:1000],
            response_summary=response.reply[:2000],
        )
        updates["history"] = (list(state.history) + [history_item])[-_MAX_HISTORY:]
        updates["updated_at"] = self._clock.now()

        return state.model_copy(update=updates)

    def determine_ending(self, *, state: GameState) -> EndingResult | None:
        if not state.is_finished:
            return None
        ending_id = state.ending_id
        if not ending_id:
            raise InvalidAIResponseError("finished state requires a non-empty ending_id")
        entry = self._catalog.get(ending_id)
        if entry is None:
            raise InvalidAIResponseError(f"unknown ending_id: {ending_id}")
        title, summary = entry
        return EndingResult(ending_id=ending_id, title=title, summary=summary)
