"""结局文案目录，作为 ending_id -> (title, summary) 的唯一出处。"""
from __future__ import annotations


class EndingCatalog:
    def __init__(self, endings: dict[str, tuple[str, str]] | None = None) -> None:
        self._endings = dict(endings) if endings is not None else {
            "burden_bearer": (
                "负重者",
                "你没有抹去往事，也没有要求谁的宽恕，只是独自背起自己造成的一切，继续往前走。",
            ),
            "evidence_keeper": (
                "见证者",
                "你选择记住全部真相，与被改写过的记忆对峙，让事实本身替你说话。",
            ),
            "merciful_wanderer": (
                "留风之人",
                "你先护住了会受伤的人，再决定何时离开。风没有替你洗清过去，却带走了一点不必要的伤害。",
            ),
            "solitary_wanderer": (
                "独行者",
                "你选择保全自己并继续前行。没有人替你宣判，也没有人替你承担，这条路只能由你走完。",
            ),
        }

    def get(self, ending_id: str) -> tuple[str, str] | None:
        return self._endings.get(ending_id)
