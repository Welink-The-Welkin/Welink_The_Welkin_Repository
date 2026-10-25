# 本文件由 codex 辅助生成（外围模块）
"""人称守门单元测试：名号修复、历史称呼保护、代词模糊、幂等与性能。"""
import time

import pytest

from backend.app.core.pronoun_guard import (
    CHARACTER_SELF_NAMES,
    FALLBACK_REPLIES,
    guard_reply,
    sanitize_history_reply,
    sanitize_visible_reply,
)

SELF_REFERENCE_CASES = [
    ("浮浪倾客看不过去。", "我看不过去。"),
    ("流浪者会等风停。", "我会等风停。"),
    ("倾奇者从不为选择后悔。", "我从不为选择后悔。"),
    ("散兵只相信自己。", "我只相信自己。"),
    ("国崩早已看透这一切。", "我早已看透这一切。"),
    ("阿帽今天在教令院听课。", "我今天在教令院听课。"),
    ("斯卡拉姆齐今天在教令院听课。", "我今天在教令院听课。"),
    ("「流浪者」不会为这种事停下。", "我不会为这种事停下。"),
    ("“浮浪倾客”不接受怜悯。", "我不接受怜悯。"),
]

NAMING_PRESERVED_CASES = [
    "你可以叫我「浮浪倾客」。浮浪倾客这个名字，不过是个称呼。",
    "浮浪倾客这个名头是我自己捡来的。",
    "叫我流浪者也行，随你。",
    "「散兵」这个名字是别人硬安上的。",
    "「散兵」是我过去在愚人众使用的称呼。",
    "我过去在愚人众使用过「斯卡拉姆齐」这个称呼。",
]

INVALID_SELF_NAME_CASES = [
    "我曾经被称为国崩。",
    "我曾经名叫阿帽。",
    "我过去的名字是流浪者。",
]

def test_guard_repairs_the_persisted_malformed_historical_sentence():
    result = guard_reply("我是我过去在愚人众使用的称呼。")
    assert result.status == "repaired"
    assert result.text == "那是我过去在愚人众使用的称呼。"

OTHERS_PRESERVED_CASES = [
    "在别人口中，他是浮浪倾客。",
    "据说他叫散兵的时候，谁都不敢惹。",
]

MIXED_REPAIR_CASES = [
    ("杜林认定浮浪倾客是他的朋友。浮浪倾客会拦住他。", "杜林认定浮浪倾客是他的朋友。我会拦住他。"),
    ("纳西妲说，浮浪倾客其实心软。可浮浪倾客不会承认。", "纳西妲说，浮浪倾客其实心软。可我不会承认。"),
]

UNREPAIRABLE_CASES = [
    "他从不回头看，也不打算解释。",
    "她早已习惯一个人走。",
    "他只是不想再被丢下而已。",
]


@pytest.mark.parametrize("original,expected", SELF_REFERENCE_CASES)
def test_guard_repairs_each_self_name_variant(original, expected):
    result = guard_reply(original)
    assert result.status == "repaired"
    assert result.text == expected


def test_guard_covers_all_alias_names():
    joined = "、".join(CHARACTER_SELF_NAMES)
    assert joined == "浮浪倾客、流浪者、倾奇者、散兵、国崩、阿帽、斯卡拉姆齐"
    for name in CHARACTER_SELF_NAMES:
        result = guard_reply(f"{name}不会说第二遍。")
        assert result.status == "repaired"
        assert result.text == "我不会说第二遍。"


@pytest.mark.parametrize("reply", ["我是散兵。", "我叫阿帽。", "我的名字是斯卡拉姆齐。"])
def test_guard_rejects_alias_as_a_first_person_name(reply):
    result = guard_reply(reply)
    assert result.status == "unrepairable"
    assert result.text == reply


@pytest.mark.parametrize("reply", INVALID_SELF_NAME_CASES)
def test_guard_rejects_historical_alias_as_first_person_identity(reply):
    result = guard_reply(reply)
    assert result.status == "unrepairable"
    assert result.text == reply


@pytest.mark.parametrize("reply", NAMING_PRESERVED_CASES)
def test_guard_preserves_legal_naming_scenarios(reply):
    result = guard_reply(reply)
    assert result.status == "clean"
    assert result.text == reply


@pytest.mark.parametrize("reply", OTHERS_PRESERVED_CASES)
def test_guard_preserves_third_party_contexts(reply):
    result = guard_reply(reply)
    assert result.status == "clean"
    assert result.text == reply


@pytest.mark.parametrize("original,expected", MIXED_REPAIR_CASES)
def test_guard_repairs_only_unprotected_occurrences(original, expected):
    result = guard_reply(original)
    assert result.status == "repaired"
    assert result.text == expected


@pytest.mark.parametrize("reply", UNREPAIRABLE_CASES)
def test_guard_marks_ambiguous_pronoun_self_reference_unrepairable(reply):
    result = guard_reply(reply)
    assert result.status == "unrepairable"
    assert result.text == reply


def test_guard_is_idempotent():
    samples = [original for original, _ in SELF_REFERENCE_CASES]
    samples += NAMING_PRESERVED_CASES + OTHERS_PRESERVED_CASES
    samples += [original for original, _ in MIXED_REPAIR_CASES]
    samples += UNREPAIRABLE_CASES
    for sample in samples:
        first = guard_reply(sample)
        second = guard_reply(first.text)
        assert second.text == first.text
        if first.status == "repaired":
            assert second.status == "clean"
        else:
            assert second.status == first.status


def test_sanitize_history_reply_drops_unrepairable_entries():
    assert sanitize_history_reply("浮浪倾客不会说第二遍。") == "我不会说第二遍。"
    assert sanitize_history_reply("他从不回头看。") is None
    assert sanitize_history_reply(sanitize_history_reply("流浪者只能靠自己。")) == "我只能靠自己。"


def test_sanitize_visible_reply_keeps_original_when_unrepairable():
    assert sanitize_visible_reply("流浪者只能靠自己。") == "我只能靠自己。"
    assert sanitize_visible_reply("他早已把过去丢在身后。") == "他早已把过去丢在身后。"
    assert sanitize_visible_reply("我不会说第二遍。") == "我不会说第二遍。"


def test_guard_replies_are_clean_and_short():
    for reply in FALLBACK_REPLIES:
        assert guard_reply(reply).status == "clean"
        assert len(reply) <= 20
        assert reply.endswith(("。", "？", "！"))


def test_guard_single_reply_latency_within_budget():
    sample = "你可以叫我「浮浪倾客」。浮浪倾客看不过去。散兵不会解释。国崩早已看透。阿帽在听课。"
    start = time.perf_counter()
    for _ in range(10):
        guard_reply(sample)
    elapsed = (time.perf_counter() - start) / 10
    assert elapsed <= 0.05
