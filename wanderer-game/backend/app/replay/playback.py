# 本文件由 codex 辅助生成（外围模块）
"""外围离线回放容器；它只读取预录数据，不推导剧情或结局。"""
from dataclasses import dataclass
from backend.app.contracts.ai import AIResponse, EndingResult
from backend.app.contracts.game import GameState
from backend.app.replay.replays import REPLAYS


# 离线模式只选择预先记录的分支，不根据状态数值临时计算剧情。
_BRANCH_SOURCES = {
    "demo_guarded_path": {
        "ask_truth": "demo_direct_path",
        "accept_risk": "demo_direct_path",
    },
}


@dataclass(frozen=True)
class ReplayTurn:
    response: AIResponse
    state: GameState
    ending: EndingResult | None = None


class ReplayPlayback:
    def __init__(self, replay_id: str):
        if replay_id not in REPLAYS:
            raise KeyError(replay_id)
        records = REPLAYS[replay_id]
        self._opening_response = AIResponse.model_validate(records["opening_response"])
        self._initial_state = GameState.model_validate(records["initial_state"])
        self._replay_id = replay_id
        self._turns = [
            ReplayTurn(
                response=AIResponse.model_validate(item["response"]),
                state=GameState.model_validate(item["state"]),
                ending=EndingResult.model_validate(item["ending"]) if item.get("ending") else None,
            )
            for item in records["turns"]
        ]
        self._cursor = 0

    @staticmethod
    def available_ids() -> list[str]:
        return sorted(REPLAYS)

    @property
    def opening_response(self) -> AIResponse:
        return self._opening_response

    def initial_state(self) -> GameState:
        return self._initial_state.model_copy(deep=True)

    def ending_for(self, ending_id: str | None) -> EndingResult | None:
        if ending_id is None:
            return None
        for turn in self._turns:
            if turn.ending and turn.ending.ending_id == ending_id:
                return turn.ending
        return None

    def next_turn(self, option_id: str | None = None) -> ReplayTurn | None:
        source_id = _BRANCH_SOURCES.get(self._replay_id, {}).get(option_id, self._replay_id)
        source_records = REPLAYS[source_id]
        if self._cursor >= len(source_records["turns"]):
            return None
        item = source_records["turns"][self._cursor]
        turn = ReplayTurn(
            response=AIResponse.model_validate(item["response"]),
            state=GameState.model_validate(item["state"]),
            ending=EndingResult.model_validate(item["ending"]) if item.get("ending") else None,
        )
        self._cursor += 1
        return turn

    def skip(self, count: int) -> None:
        self._cursor = min(max(count, 0), len(self._turns))
