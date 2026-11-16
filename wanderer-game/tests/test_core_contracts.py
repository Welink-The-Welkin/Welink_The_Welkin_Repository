# 本文件由 codex 辅助生成（外围模块）
from uuid import uuid4

import pytest

from backend.app.contracts.ai import AIResponse, Choice, CoreTurnResult, Emotion, EndingResult, NextScene
from backend.app.contracts.game import GameState, initial_state
from backend.app.core.response_mapping import ResponseStateMapperImpl, ResponseStateMapperPlaceholder
from backend.app.core.roleplay_engine import CoreNotImplementedError, RoleplayEngineImpl, RoleplayEnginePlaceholder
from backend.app.core.state_machine import GameStateMachineImpl, StateMachinePlaceholder


def make_response(**overrides) -> AIResponse:
    values = {
        "reply": "少说些空话。",
        "emotion": Emotion.GUARDED,
        "state_delta": {"trust": 10, "compassion": -10, "responsibility": 1},
        "next_scene": NextScene(
            scene_id="scene_02",
            options=[Choice(id="ask", text="追问真相")],
        ),
        "is_ending": False,
        "ending_id": None,
    }
    values.update(overrides)
    return AIResponse(**values)


def make_state(**overrides) -> GameState:
    values = initial_state(session_id=uuid4()).model_dump()
    values.update(overrides)
    return GameState.model_validate(values)


def make_raw_response(state_delta: dict[str, object]) -> dict[str, object]:
    return {
        "reply": "少说些空话。",
        "emotion": "guarded",
        "state_delta": state_delta,
        "next_scene": {
            "scene_id": "scene_02",
            "options": [{"id": "ask", "text": "追问真相"}],
        },
        "is_ending": False,
        "ending_id": None,
    }


def test_roleplay_engine_methods_remain_explicit_placeholders():
    engine = RoleplayEnginePlaceholder()

    with pytest.raises(CoreNotImplementedError, match="delegated to CodeArts Agent"):
        engine.create_initial_state(session_id=str(uuid4()))
    with pytest.raises(CoreNotImplementedError, match="delegated to CodeArts Agent"):
        engine.handle_turn(state=make_state(), player_message="你好", option_id=None)


def test_state_machine_methods_remain_explicit_placeholders():
    state_machine = StateMachinePlaceholder()

    with pytest.raises(RuntimeError, match="state machine is delegated"):
        state_machine.advance(state=make_state(), turn_result=CoreTurnResult(response=make_response(), state=make_state()))
    with pytest.raises(RuntimeError, match="ending logic is delegated"):
        state_machine.determine_ending(state=make_state())


def test_response_mapper_methods_remain_explicit_placeholders():
    mapper = ResponseStateMapperPlaceholder()

    with pytest.raises(RuntimeError, match="response normalization is delegated"):
        mapper.normalize_response(raw_response=make_raw_response({"trust": 1}))
    with pytest.raises(RuntimeError, match="response-to-state mapping is delegated"):
        mapper.apply(state=make_state(), response=make_response())


def test_normalized_ai_response_rejects_delta_outside_contract_range():
    with pytest.raises(ValueError, match="between -10 and 10"):
        make_response(state_delta={"trust": 11})


def test_normalized_ai_response_rejects_duplicate_options():
    with pytest.raises(ValueError, match="unique"):
        make_response(
            next_scene=NextScene(
                scene_id="scene_02",
                options=[Choice(id="same", text="甲"), Choice(id="same", text="乙")],
            )
        )


def test_game_state_contract_rejects_metrics_outside_zero_to_one_hundred():
    with pytest.raises(ValueError):
        make_state(trust=101)


def test_response_normalizer_clamps_raw_integer_delta_before_model_validation():
    response = ResponseStateMapperImpl().normalize_response(
        raw_response=make_raw_response({"trust": 999, "compassion": -999})
    )

    assert response.state_delta == {"trust": 10, "compassion": -10}


@pytest.mark.parametrize(
    "delta",
    [
        {"trust": 1.5},
        {"trust": "2"},
        {"trust": True},
        {"unknown_metric": 2},
    ],
)
def test_response_normalizer_rejects_invalid_raw_delta_values(delta):
    with pytest.raises((TypeError, ValueError)):
        ResponseStateMapperImpl().normalize_response(raw_response=make_raw_response(delta))


def test_response_mapper_clamps_state_metrics_after_applying_delta():
    state = make_state(trust=98, compassion=1, responsibility=50)

    updated = ResponseStateMapperImpl().apply(state=state, response=make_response())

    assert (updated.trust, updated.compassion, updated.responsibility) == (100, 0, 51)
    assert updated.session_id == state.session_id


def test_roleplay_engine_creates_initial_state_for_requested_session():
    session_id = uuid4()

    state = RoleplayEngineImpl().create_initial_state(session_id=str(session_id))

    assert isinstance(state, GameState)
    assert state.session_id == session_id
    assert (state.trust, state.compassion, state.responsibility) == (50, 50, 50)
    assert state.turn_count == 0
    assert not state.is_finished
    assert state.ending_id is None


def test_roleplay_engine_returns_valid_response_and_state():
    state = make_state()

    result = RoleplayEngineImpl().handle_turn(
        state=state,
        player_message="我想先听听你的判断。",
        option_id=None,
    )

    assert isinstance(result, CoreTurnResult)
    assert isinstance(result.response, AIResponse)
    assert isinstance(result.state, GameState)
    assert result.response.reply
    assert result.response.emotion in Emotion
    assert set(result.response.state_delta) <= {"trust", "compassion", "responsibility"}


def test_roleplay_engine_allows_different_choices_to_reach_distinct_outcomes():
    engine = RoleplayEngineImpl()
    state = make_state()

    guarded = engine.handle_turn(state=state, player_message=None, option_id="ask_truth")
    direct = engine.handle_turn(state=state, player_message=None, option_id="accept_task")

    assert (
        guarded.response.next_scene.scene_id != direct.response.next_scene.scene_id
        or guarded.response.ending_id != direct.response.ending_id
    )


def test_state_machine_advances_scene_and_turn_once():
    state = make_state(turn_count=2)
    mapped_state = state.model_copy(update={"scene_id": "scene_02"})
    result = CoreTurnResult(response=make_response(), state=mapped_state)

    advanced = GameStateMachineImpl().advance(state=state, turn_result=result)

    assert isinstance(advanced, GameState)
    assert advanced.session_id == state.session_id
    assert advanced.scene_id == "scene_02"
    assert advanced.turn_count == 3
    assert 0 <= advanced.trust <= 100
    assert 0 <= advanced.compassion <= 100
    assert 0 <= advanced.responsibility <= 100


def test_state_machine_returns_no_ending_for_unfinished_state():
    assert GameStateMachineImpl().determine_ending(state=make_state()) is None


def test_state_machine_returns_ending_details_for_finished_state():
    state = make_state(is_finished=True, ending_id="burden_bearer")

    ending = GameStateMachineImpl().determine_ending(state=state)

    assert isinstance(ending, EndingResult)
    assert ending.ending_id == state.ending_id
    assert ending.title
    assert ending.summary
