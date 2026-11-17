"""关键词匹配。

设计要点：
- 大小写不敏感（英文关键词常见）
- 返回命中的全部关键词，按其在文本中首次出现的位置排序，方便弹窗展示
- 对 None / 空串 / 非字符串输入保持安全
"""
from dataclasses import dataclass, field
from typing import Iterable, List, Optional


@dataclass
class KeywordHit:
    """一次匹配的结果。"""

    matched: bool = False
    keywords: List[str] = field(default_factory=list)

    def has(self, kw: str) -> bool:
        return kw in self.keywords


def _normalize_keywords(keywords: Iterable) -> List[str]:
    out = []
    for kw in keywords or []:
        if not isinstance(kw, str):
            continue
        kw = kw.strip()
        if kw:
            out.append(kw)
    return out


def match_keywords(text: Optional[str], keywords: Iterable) -> KeywordHit:
    """返回 text 中命中的关键词。

    只要命中任意一个，matched 即为 True。
    """
    if not isinstance(text, str) or not text:
        return KeywordHit()

    lowered = text.lower()
    found = []  # (首次出现位置, 关键词)

    for kw in _normalize_keywords(keywords):
        pos = lowered.find(kw.lower())
        if pos >= 0:
            found.append((pos, kw))

    if not found:
        return KeywordHit()

    found.sort(key=lambda pair: pair[0])
    return KeywordHit(matched=True, keywords=[kw for _, kw in found])
