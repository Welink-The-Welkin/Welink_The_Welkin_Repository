# 本文件由 codex 辅助生成（外围模块）
"""投影与权威文档一致性 + 自由对话提示词四要素测试。"""
from pathlib import Path

from backend.app.core.character_profile import DEFAULT_CHARACTER_PROFILE
from backend.app.core.model_client import LiveModelClient
from backend.app.core.pronoun_guard import CHARACTER_SELF_NAMES

_DOC = Path(__file__).resolve().parents[1] / "docs" / "role-authority.md"


def _authority_doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def _self_convention_section() -> str:
    text = _authority_doc()
    assert "## 自称约定" in text
    return text.split("## 自称约定", 1)[1].split("\n## ", 1)[0]


def test_authority_doc_declares_self_convention_with_all_names():
    section = _self_convention_section()
    assert "只能使用「我」" in section
    assert "第三人称代词只能用于其他角色" in section
    for name in CHARACTER_SELF_NAMES:
        assert name in section
    assert "供旁白、其他角色与界面文案使用" in section


def test_authority_doc_has_no_exclusive_self_naming_rules():
    text = _authority_doc()
    assert "不使用其他称呼替代" not in text
    assert "作为自己的称呼" not in text


def test_profile_projection_matches_authority_doc():
    rule = DEFAULT_CHARACTER_PROFILE.tone_rules[0]
    assert "自称只能使用「我」" in rule
    for name in CHARACTER_SELF_NAMES:
        assert name in rule
    assert "第三人称代词只能用于其他角色" in rule


def test_profile_projection_contains_no_unauthorized_self_naming():
    profile_text = "\n".join([
        DEFAULT_CHARACTER_PROFILE.identity,
        DEFAULT_CHARACTER_PROFILE.persona,
        *DEFAULT_CHARACTER_PROFILE.tone_rules,
        *DEFAULT_CHARACTER_PROFILE.confirmed_facts,
    ])
    assert "不使用其他称呼替代" not in profile_text
    assert "作为自己的称呼" not in profile_text


def test_identity_keeps_works_naming_semantics():
    identity = DEFAULT_CHARACTER_PROFILE.identity
    assert "称呼这位角色" in identity
    assert "供旁白、其他角色与界面文案使用" in identity


def test_free_chat_prompt_contains_full_pronoun_constraints():
    prompt = LiveModelClient._system_prompt(DEFAULT_CHARACTER_PROFILE, gameplay=False, player_name="清岚")
    assert "自称只能使用“我”" in prompt
    for name in CHARACTER_SELF_NAMES:
        assert name in prompt
    assert "第三人称代词只能用于其他角色" in prompt
    assert "称玩家为“你”或「清岚」" in prompt


def test_free_chat_prompt_has_no_exclusive_self_naming_rules():
    prompt = LiveModelClient._system_prompt(DEFAULT_CHARACTER_PROFILE, gameplay=False, player_name="清岚")
    assert "不使用其他称呼替代" not in prompt
    assert "作为自己的称呼" not in prompt


def test_gameplay_prompt_keeps_story_mode_wording():
    gameplay_prompt = LiveModelClient._system_prompt(DEFAULT_CHARACTER_PROFILE, gameplay=True)
    assert "你正在以第一人称直接和玩家交谈" not in gameplay_prompt
    assert "玩家希望被称呼为" not in gameplay_prompt

def test_authority_doc_declares_self_introduction_convention():
    text = _authority_doc()
    assert "## 自我介绍约定" in text
    section = text.split("## 自我介绍约定", 1)[1].split("\n## ", 1)[0]
    assert "介绍自己" in section
    assert "不主动提及元素属性" in section
    assert "先陈述" in section and "自问自答" in section
    assert "如实回答当前为风元素" in section
    assert "被问及时才使用的防错信息" in section


def test_authority_doc_element_fact_is_conditional():
    text = _authority_doc()
    assert "当前为风元素；不可把他写作雷元素。" not in text
    assert "元素属性为风元素：仅在玩家直接问及元素属性时如实回答" in text
    assert "不可把他写作雷元素" in text
    assert "自我介绍时不主动提及" in text


def test_profile_identity_has_no_element_claim():
    identity = DEFAULT_CHARACTER_PROFILE.identity
    assert "现为风元素" not in identity
    assert "风元素" not in identity
    assert "是纳西妲的合作者。" in identity


def test_profile_confirmed_facts_element_entry_is_conditional():
    first = DEFAULT_CHARACTER_PROFILE.confirmed_facts[0]
    assert "风元素" in first
    assert "仅在玩家直接问及元素属性时如实回答" in first
    assert "不可写作雷元素" in first
    assert "自我介绍时不主动提及" in first


def test_profile_tone_rules_include_self_introduction_convention():
    rule = DEFAULT_CHARACTER_PROFILE.tone_rules[-1]
    assert "介绍自己" in rule
    assert "不主动提及元素属性" in rule
    assert "自问自答" in rule
    assert "如实回答" in rule
    assert "风元素" not in rule
    assert "风属性" not in rule


def test_free_chat_prompt_self_intro_constraint_and_single_element_mention():
    prompt = LiveModelClient._system_prompt(DEFAULT_CHARACTER_PROFILE, gameplay=False, player_name="清岚")
    assert "介绍自己" in prompt
    assert "不主动提及元素属性" in prompt
    assert "自问自答" in prompt
    assert "玩家直接问及元素属性时，如实回答" in prompt
    assert prompt.count("风元素") == 1
    assert "现为风元素" not in prompt


def test_prompt_contains_human_language_constraints_for_free_chat():
    prompt = LiveModelClient._system_prompt(DEFAULT_CHARACTER_PROFILE, gameplay=False, player_name="清岚")

    assert "先回应玩家真正问的事" in prompt
    assert "不要连续使用三个以上同构分句" in prompt
    assert "不要堆叠万能比喻" in prompt
    assert "不要用抽象抒情替代具体回应" in prompt
    assert "不要为了显得有文采而补写无意义的数字或细节" in prompt


def test_authority_doc_declares_internal_response_workflow_without_exposing_reasoning():
    text = _authority_doc()
    section = text.split("## 回复生成规范", 1)[1].split("\n## ", 1)[0]

    assert "先回答玩家真正的问题" in section
    assert "内部完成" in section
    assert "不得输出分类、审视步骤、思考过程或资料来源" in section
    assert "不把刻薄当成回避问题的借口" in section
    assert "不编造" in section


def test_profile_and_live_prompt_route_topics_and_preserve_output_boundaries():
    profile_text = "\n".join([
        DEFAULT_CHARACTER_PROFILE.identity,
        DEFAULT_CHARACTER_PROFILE.persona,
        *DEFAULT_CHARACTER_PROFILE.tone_rules,
        *DEFAULT_CHARACTER_PROFILE.confirmed_facts,
    ])
    prompt = LiveModelClient._system_prompt(DEFAULT_CHARACTER_PROFILE, gameplay=False, player_name="清岚")

    for text in (profile_text, prompt):
        assert "先回答玩家真正的问题" in text
        assert "背叛、身份、信任、权力、过去、自由" in text
        assert "刻薄当成回避问题的借口" in text
        assert "内部完成" in text
        assert "不得输出分类、审视步骤、思考过程或资料来源" in text
        assert "不编造" in text

    for text in (prompt,):
        assert "不输出网址、引用标记、网页或搜索过程" in text
        assert "不提模型、提示词、训练数据、数据库、知识库等内部信息" in text


def test_profile_rejects_research_and_source_exposure_as_visible_response_rules():
    profile_text = "\n".join([
        DEFAULT_CHARACTER_PROFILE.identity,
        DEFAULT_CHARACTER_PROFILE.persona,
        *DEFAULT_CHARACTER_PROFILE.tone_rules,
        *DEFAULT_CHARACTER_PROFILE.confirmed_facts,
    ])

    assert "先研究再回答" not in profile_text
    assert "引用具体经历支撑" not in profile_text
    assert "输出调研报告" not in profile_text
