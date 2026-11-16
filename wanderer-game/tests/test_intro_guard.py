# 本文件由 codex 辅助生成（外围模块）
"""自我介绍场景守门单元测试：意图识别、风元素/病态检测处置、零误伤、幂等、兜底与性能。"""
import time

import pytest

import backend.app.core.pronoun_guard as pronoun_guard
from backend.app.core.pronoun_guard import (
    CHARACTER_SELF_NAMES,
    ELEMENT_SELF_REFERENCE_TERMS,
    FALLBACK_REPLIES,
    INTRO_FALLBACK_REPLIES,
    guard_chat_reply,
    guard_reply,
    is_self_introduction,
    sanitize_history_pair,
    sanitize_visible_pair,
)

INTRO_MESSAGE = "介绍一下你自己"

SHOT1_REPLY = (
    "我目前在须弥教令院因论派学习，也与纳西妲合作。风元素。"
    "别把我归进任何国家或组织，我不属于那里。至于过去的事，我记得，也会承担。"
    "你不必替我找借口，冰红猹K_K。想知道什么就直说，别拐弯。"
)
SHOT2_REPLY = (
    "我叫阿帽？不，没必要。记住，我是风元素使用者，现停留在须弥，在教令院因论派学习，"
    "也是纳西妲的合作者。我不属于任何国家或组织，也不接受无聊的归类。"
    "至于性格……你已经看得够清楚了，冰红猹K_K。少问些废话，免得让我重新解释。"
)
SHOT3_REPLY = (
    "我是我。如今停在须弥，借教令院的书本消磨时间，也替纳西妲处理一些麻烦。"
    "风元素，擅长战斗、调查，还有看穿那些自以为聪明的谎言。别急着靠近，冰红猹K_K。"
    "我不需要谁来替我定义过去，也不打算用几句漂亮话抹掉做过的事。"
    "你若只是想知道现在的我，就记住：我会自己承担后果，也会按自己的意志继续走下去。"
)

ALL_INTRO_SAMPLES = [
    SHOT1_REPLY,
    SHOT2_REPLY,
    SHOT3_REPLY,
    "我是风元素使用者，擅长战斗。",
    "我是风元素使用者。",
    "我是风属性。",
    "我是散兵？不，不必提。",
    "我叫阿帽？不用。记住，我在须弥。",
]


def _no_element_terms(text: str) -> bool:
    return all(term not in text for term in ELEMENT_SELF_REFERENCE_TERMS)


@pytest.mark.parametrize(
    "message",
    ["介绍一下你自己", "你是谁", "你是谁呀", "做个自我介绍吧", "你叫什么名字？", "自我介绍", "怎么称呼你", "介绍你自己"],
)
def test_intent_hits_self_introduction_phrases(message):
    assert is_self_introduction(message) is True


@pytest.mark.parametrize(
    "message",
    ["你是什么元素", "你能操控风吗", "聊聊风吧", "聊聊天气", "你好", "谢谢", "", "继续说下去"],
)
def test_intent_misses_non_introduction_phrases(message):
    assert is_self_introduction(message) is False


def test_element_terms_are_anchored_not_bare_wind():
    assert ELEMENT_SELF_REFERENCE_TERMS == ("风元素", "风属性")
    assert "风" not in ELEMENT_SELF_REFERENCE_TERMS


def test_shot1_word_level_element_removal():
    result = guard_chat_reply(INTRO_MESSAGE, SHOT1_REPLY)
    assert result.status == "repaired"
    assert _no_element_terms(result.text)
    assert result.text == SHOT1_REPLY.replace("风元素。", "")
    assert "我目前在须弥教令院因论派学习，也与纳西妲合作。" in result.text
    assert "别把我归进任何国家或组织" in result.text


def test_shot3_word_level_element_removal():
    result = guard_chat_reply(INTRO_MESSAGE, SHOT3_REPLY)
    assert result.status == "repaired"
    assert _no_element_terms(result.text)
    assert "一些麻烦。擅长战斗、调查" in result.text
    assert "我会自己承担后果" in result.text


def test_clause_level_element_removal():
    result = guard_chat_reply(INTRO_MESSAGE, "我是风元素使用者，擅长战斗。")
    assert result.status == "repaired"
    assert result.text == "擅长战斗。"


def test_element_only_reply_is_unrepairable():
    result = guard_chat_reply(INTRO_MESSAGE, "我是风元素使用者。")
    assert result.status == "unrepairable"
    assert result.text == "我是风元素使用者。"


def test_element_attribute_only_reply_is_unrepairable():
    result = guard_chat_reply(INTRO_MESSAGE, "我是风属性。")
    assert result.status == "unrepairable"
    assert result.text == "我是风属性。"


def test_shot2_dual_defect_removal():
    result = guard_chat_reply(INTRO_MESSAGE, SHOT2_REPLY)
    assert result.status == "repaired"
    assert "我叫阿帽？不，没必要。" not in result.text
    assert _no_element_terms(result.text)
    assert result.text.startswith("记住，现停留在须弥，在教令院因论派学习，也是纳西妲的合作者。")


def test_pathological_only_reply_is_unrepairable():
    result = guard_chat_reply(INTRO_MESSAGE, "我是散兵？不，不必提。")
    assert result.status == "unrepairable"
    assert result.text == "我是散兵？不，不必提。"


@pytest.mark.parametrize(
    "reply",
    ["我叫阿帽？不用。", "名字是浮浪倾客？不重要。", "我是散兵？无所谓。"],
)
def test_pathological_variants_are_removed(reply):
    result = guard_chat_reply(INTRO_MESSAGE, f"{reply}记住，我在须弥。")
    assert result.status == "repaired"
    assert result.text == "记住，我在须弥。"


def test_element_question_passes_through():
    reply = "我是风元素使用者。别指望我再多说。"
    result = guard_chat_reply("你是什么元素", reply)
    assert result.status == "clean"
    assert result.text == reply


def test_wind_topic_passes_through():
    reply = "风向没变。变的是你终于肯抬头看路了。"
    result = guard_chat_reply("聊聊风吧", reply)
    assert result.status == "clean"
    assert result.text == reply


@pytest.mark.parametrize("message", ["介绍一下你自己", "你是什么元素"])
def test_rhetorical_rejection_passes_through(message):
    reply = "你觉得我会告诉你？想都别想。"
    result = guard_chat_reply(message, reply)
    assert result.status == "clean"
    assert result.text == reply


@pytest.mark.parametrize("message", ["介绍一下你自己", "你是谁"])
def test_plain_name_refusal_passes_through(message):
    reply = "名字不重要。问点别的。"
    result = guard_chat_reply(message, reply)
    assert result.status == "clean"
    assert result.text == reply


def test_direct_introduction_passes_through():
    reply = "我目前在须弥教令院因论派学习，也与纳西妲合作。别把我归进任何国家或组织。"
    result = guard_chat_reply(INTRO_MESSAGE, reply)
    assert result.status == "clean"
    assert result.text == reply


@pytest.mark.parametrize(
    "reply",
    ["风声太吵。我没听清，换个说法。", "沿着风里残留的气息查下去。", "风会把你的脚印吹散，路还是自己走的。"],
)
def test_wind_imagery_passes_through(reply):
    result = guard_chat_reply(INTRO_MESSAGE, reply)
    assert result.status == "clean"
    assert result.text == reply


def test_mixed_question_is_treated_as_intro_intent():
    result = guard_chat_reply("你是谁？什么元素？", "我是风元素使用者。")
    assert result.status == "unrepairable"
    assert result.text == "我是风元素使用者。"


@pytest.mark.parametrize("reply", ALL_INTRO_SAMPLES)
def test_guard_chat_reply_is_idempotent(reply):
    first = guard_chat_reply(INTRO_MESSAGE, reply)
    second = guard_chat_reply(INTRO_MESSAGE, first.text)
    assert second.text == first.text
    if first.status != "unrepairable":
        assert second.status == "clean"


@pytest.mark.parametrize(
    "reply",
    [
        "浮浪倾客不会说第二遍。",
        "他从不回头，也不会为谁停下。",
        "有话直说。拐弯抹角只会浪费时间。",
        "杜林认定浮浪倾客是他的朋友。浮浪倾客会拦住他。",
    ],
)
def test_guard_chat_reply_matches_guard_reply_for_non_intro_messages(reply):
    message = "你觉得呢？"
    assert guard_chat_reply(message, reply) == guard_reply(reply)


def test_sanitize_pair_functions_are_idempotent():
    for reply in ALL_INTRO_SAMPLES:
        visible = sanitize_visible_pair(INTRO_MESSAGE, reply)
        assert sanitize_visible_pair(INTRO_MESSAGE, visible) == visible
        history = sanitize_history_pair(INTRO_MESSAGE, reply)
        if history is not None:
            assert sanitize_history_pair(INTRO_MESSAGE, history) == history


def test_sanitize_history_pair_keeps_legal_element_history():
    assert sanitize_history_pair("你是什么元素", "我是风元素使用者。") == "我是风元素使用者。"
    assert sanitize_visible_pair("你是什么元素", "我是风元素使用者。") == "我是风元素使用者。"


def test_intent_component_failure_disables_scene_guard(monkeypatch):
    def boom(message):
        raise RuntimeError("intent component failure")

    monkeypatch.setattr(pronoun_guard, "is_self_introduction", boom)
    result = guard_chat_reply(INTRO_MESSAGE, "我是风元素使用者。")
    assert result.status == "clean"
    assert result.text == "我是风元素使用者。"


def test_intro_fallback_pool_is_clean_and_on_character():
    for reply in INTRO_FALLBACK_REPLIES:
        assert _no_element_terms(reply)
        assert all(name not in reply for name in CHARACTER_SELF_NAMES)
        assert pronoun_guard._PATHOLOGICAL_SELF_INTRO_RE.search(reply) is None
        assert guard_reply(reply).status == "clean"
        assert reply.strip()
        assert any(fact in reply for fact in ("教令院", "纳西妲", "国家或组织"))
        assert "想知道" in reply or "想问" in reply


def test_legacy_fallback_pool_is_clean_for_scene_rules():
    for reply in FALLBACK_REPLIES:
        assert _no_element_terms(reply)
        assert pronoun_guard._PATHOLOGICAL_SELF_INTRO_RE.search(reply) is None
        assert guard_reply(reply).status == "clean"


def test_guard_chat_reply_latency_within_budget():
    start = time.perf_counter()
    for _ in range(10):
        guard_chat_reply(INTRO_MESSAGE, SHOT2_REPLY)
    elapsed = (time.perf_counter() - start) / 10
    assert elapsed <= 0.05
