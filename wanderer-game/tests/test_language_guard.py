from backend.app.core.language_guard import guard_language


def test_guard_language_rejects_mechanical_repeated_clause_openings():
    result = guard_language("记住江水的颜色，记住风吹乱头发时的痒，记住逃课后世界仍在转。")

    assert result.status == "unrepairable"


def test_guard_language_rejects_dense_generic_metaphors_only_when_they_stack():
    result = guard_language("你的沉默像雾，像潮水，像一把落在夜里的刀。")

    assert result.status == "unrepairable"


def test_guard_language_keeps_specific_dialogue_and_a_single_figurative_line():
    reply = "别站在门口。进来，把你查到的东西给我。"

    result = guard_language(reply)

    assert result.status == "clean"
    assert result.text == reply


def test_guard_language_does_not_treat_one_metaphor_as_ai_flavor():
    reply = "这句话轻得像纸，落地却够你疼一阵。"

    result = guard_language(reply)

    assert result.status == "clean"
    assert result.text == reply
