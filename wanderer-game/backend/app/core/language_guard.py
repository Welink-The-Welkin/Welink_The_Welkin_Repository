"""自由对话的轻量语言质量守门。

这里只拦截高置信度的机械痕迹，不把单个比喻、排比或破折号当成问题。
无法安全改写的回复交给调用方重试，避免守门器擅自改变事实或语气。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LanguageGuardResult:
    text: str
    status: Literal["clean", "unrepairable"]


_CLAUSE_SPLIT_RE = re.compile(r"[，、；。！？!?……]+")
_LEADING_WORD_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}")
_METAPHOR_RE = re.compile(r"像|如同|仿佛|犹如")


def _has_mechanical_listing(reply: str) -> bool:
    clauses = [part.strip() for part in _CLAUSE_SPLIT_RE.split(reply) if part.strip()]
    if len(clauses) < 3:
        return False
    openings: dict[str, list[int]] = {}
    for clause in clauses:
        match = _LEADING_WORD_RE.match(clause)
        if match is None:
            continue
        opening = match.group(0)
        # AI 常把同一个两字动词重复套在等长分句前；保留更长前缀
        # 只会漏掉「记住江水／记住风／记住逃课」这类典型结构。
        for prefix_length in (2, 3, 4):
            if len(opening) >= prefix_length:
                openings.setdefault(opening[:prefix_length], []).append(len(clause))
    for lengths in openings.values():
        if len(lengths) >= 3 and max(lengths) - min(lengths) <= 8:
            return True
    return False


def _has_stacked_generic_metaphors(reply: str) -> bool:
    return len(_METAPHOR_RE.findall(reply)) >= 3


def guard_language(reply: str) -> LanguageGuardResult:
    """检测高置信度的机械罗列与比喻堆叠；不做破坏性自动改写。"""
    if not reply:
        return LanguageGuardResult(reply, "clean")
    if _has_mechanical_listing(reply) or _has_stacked_generic_metaphors(reply):
        return LanguageGuardResult(reply, "unrepairable")
    return LanguageGuardResult(reply, "clean")
