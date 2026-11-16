# 本文件由 codex 辅助生成（外围模块）
from backend.app.replay.playback import ReplayPlayback


def test_playback_returns_static_turns_in_order_without_deciding_game_rules():
    playback = ReplayPlayback("demo_guarded_path")

    first = playback.next_turn()
    second = playback.next_turn()

    assert first is not None
    assert second is not None
    assert first.response.reply != second.response.reply
    assert first.state.turn_count == 1
    assert second.state.turn_count == 2


def test_unknown_replay_is_rejected():
    try:
        ReplayPlayback("missing")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown replay should not be accepted")
