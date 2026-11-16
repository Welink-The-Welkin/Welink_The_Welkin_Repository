# 本文件由 codex 辅助生成（外围模块）
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.app.contracts.ai import AIResponse, CoreTurnResult, Emotion, EndingResult, NextScene
from backend.app.contracts.game import GameState, TurnRequest


def test_turn_request_rejects_empty_or_ambiguous_input():
    with pytest.raises(ValueError):
        TurnRequest()

    with pytest.raises(ValueError):
        TurnRequest(player_message=" ")

    with pytest.raises(ValueError):
        TurnRequest(player_message="hello", option_id="choice")


def test_turn_request_accepts_only_preset_options_without_free_text():
    accepted = TurnRequest(option_id="listen")

    assert accepted.option_id == "listen"
    assert not hasattr(accepted, "player_message")


def test_ai_response_rejects_missing_next_scene_for_non_ending():
    with pytest.raises(ValueError):
        AIResponse(
            reply="A line",
            emotion=Emotion.GUARDED,
            state_delta={"trust": 1},
            next_scene=None,
            is_ending=False,
            ending_id=None,
        )


def test_game_state_round_trip_preserves_contract_fields():
    now = datetime.now(timezone.utc)
    state = GameState(
        session_id=uuid4(),
        scene_id="scene_01",
        turn_count=0,
        trust=50,
        compassion=50,
        responsibility=50,
        history=[],
        is_finished=False,
        ending_id=None,
        created_at=now,
        updated_at=now,
    )

    restored = GameState.model_validate_json(state.model_dump_json())

    assert restored.session_id == state.session_id
    assert restored.trust == 50


def test_core_turn_result_carries_ending_metadata_without_computing_it():
    ending = EndingResult(ending_id="evidence_keeper", title="求证者", summary="先确认事实，再承担责任。")
    response = AIResponse(
        reply="风停了。",
        emotion=Emotion.QUIET,
        state_delta={},
        next_scene=None,
        is_ending=True,
        ending_id="evidence_keeper",
    )

    result = CoreTurnResult(response=response, state={"is_finished": True}, ending=ending)

    assert result.ending == ending
