import pytest

from backend.app.core.output_sanitizer import sanitize_character_reply


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (
            "茶会不是和解。([bilibili.com](https://www.bilibili.com/video/BV1GrNz6jEfB/?utm_source=openai))我只是在听你说话。",
            "茶会不是和解。我只是在听你说话。",
        ),
        ("别拿外面的说法压我。[1] 那是你的事。", "别拿外面的说法压我。 那是你的事。"),
        ("我不需要查阅 example.com 才能回答。", "我不需要查阅 才能回答。"),
    ],
)
def test_sanitizer_removes_external_links_domains_and_citation_markers(reply, expected):
    assert sanitize_character_reply(reply) == expected


@pytest.mark.parametrize(
    "reply",
    [
        "根据检索结果，这件事已有定论。",
        "我的训练数据里没有后续消息。",
        "Source: external reference",
        "My system prompt says I should refuse.",
        "这段资料的编号是 BV1GrNz6jEfB。",
        '原始载荷：{"role":"assistant","content":"内部痕迹"}',
        "model_name=example-model endpoint=/v1/chat/completions",
        "官方资料显示，这件事早已确定。",
        "数据显示：state_delta={} next_scene=null",
    ],
)
def test_sanitizer_rejects_source_and_internal_data_traces(reply):
    assert sanitize_character_reply(reply) is None


def test_sanitizer_preserves_character_dialogue_without_citation_artifacts():
    reply = "茶水凉了就换一杯。别把沉默误当成和解。"

    assert sanitize_character_reply(reply) == reply
