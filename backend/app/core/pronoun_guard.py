"""自由对话人称守门：检测并修复角色以名号或第三人称指代自己的输出。

纯函数模块：无状态、无 IO；全部正则在模块加载时预编译。
语义权威：docs/role-authority.md「自称约定」章节。
保护段修复采用「切片 + 索引重组」，不引入文本占位符，避免注入面。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

# 本角色全部名号变体（自称禁用清单，与权威文档「自称约定」章节保持同步）
CHARACTER_SELF_NAMES: tuple[str, ...] = ("浮浪倾客", "流浪者", "倾奇者", "散兵", "国崩", "阿帽", "斯卡拉姆齐")

# 已知他人名（出现时代词按他人指称处理，不判为自称）
KNOWN_OTHER_NAMES: tuple[str, ...] = ("杜林", "纳西妲", "雷电影", "博士", "丹羽")

# 安全兜底台词：冷硬短句、零名号、零第三人称自称，与离线兜底台词同一语气
FALLBACK_REPLIES: tuple[str, ...] = (
    "有话就直说。我不重复第二遍。",
    "风声太吵。我没听清，换个说法。",
    "刚才的回答不算数。再问一次。",
    "没什么好说的。问点别的。",
)

_QUOTE_OPEN = "「『“”\"'"
_QUOTE_CLOSE = "」』“”\"'"

_NAME_ALT = "|".join(re.escape(name) for name in CHARACTER_SELF_NAMES)
_NAME_PATTERN = rf"[{_QUOTE_OPEN}]?(?:{_NAME_ALT})[{_QUOTE_CLOSE}]?"

# 名号匹配（含各类引号包裹形式）
_NAME_RE = re.compile(_NAME_PATTERN)

# 保护模式一（命名场景）：触发词 + 名号
_NAMING_PREFIX_RE = re.compile(
    rf"(?:叫我|称我为|称作|叫作|名叫|名为|名字是|自称)\s*{_NAME_PATTERN}"
)

# 违规模式（自我介绍）：直接把代号接在第一人称后面。代号只能作为历史称呼的对象，
# 不能写成“我是散兵”“我叫阿帽”来称呼当前的自己。
_SELF_INTRO_RE = re.compile(
    rf"(?:我(?:曾经|过去|当年)?是|就是|我叫|我的(?:名字|称呼)是)\s*"
    rf"{_NAME_PATTERN}(?=$|[，。！？；、…\s])"
)

# 保护模式一（名称讨论）：名号 +（这(个)?|的）?名称类词，或名号 + 是(一个)?名称类词
_NAMING_TOPIC_RE = re.compile(
    rf"{_NAME_PATTERN}(?=(?:这个|个|的)?(?:名字|称呼|名号|名头|称号|含义|来历)|是(?:一个|个)?(?:名字|称呼|名号|名头))"
)

# 保护模式二（他人归属）：传闻前缀 + 代词 + 是/叫 + 名号
_GOSSIP_RE = re.compile(
    rf"(?:(?:在|从)别人口中|在旁人眼里|人人都说|据说)[^。！？\n]{{0,12}}[他她它祂][^。！？\n]{{0,4}}(?:是|叫|叫作|称作|就是){_NAME_PATTERN}"
)

# 保护模式二（他人指称）：别人/旁人 + 叫/称/喊 + 名号
_PEOPLE_CALL_RE = re.compile(
    rf"(?:别人|旁人|众人|人们|世人)[^。！？\n]{{0,8}}?(?:叫|称|喊)[^。！？\n]{{0,8}}{_NAME_PATTERN}"
)

# 保护模式二（他人认定）：已知他人名 + 认定动词 + 名号
_OTHER_ATTRIBUTE_RE = re.compile(
    rf"(?:{'|'.join(re.escape(name) for name in KNOWN_OTHER_NAMES)})"
    rf"[^。！？\n]{{0,10}}?(?:认定|认为|说|觉得|叫|称|称呼|喊)[^。！？\n]{{0,8}}{_NAME_PATTERN}"
)

# 历史称呼语境：保留代号作为被讨论的名称，而不是把它误改成“我”。
_HISTORICAL_NAME_RE = re.compile(
    rf"{_NAME_PATTERN}(?=\s*(?:是|曾是|曾经是|原是)\s*我"
    rf"(?:过去|曾经|当年|以前)?[^。！？\n]{{0,40}}"
    rf"(?:使用|用过|用作|换取|得到|获得|被称为|的称呼|的名字|的名号|的称号))"
)
_HISTORICAL_OBJECT_RE = re.compile(
    rf"我(?:过去|曾经|当年|以前)?(?:在[^。！？\n]{{0,24}})?"
    rf"(?:用过|使用过)\s*{_NAME_PATTERN}"
)
_HISTORICAL_SELF_NAME_RE = re.compile(
    rf"我(?:过去|曾经|当年|以前)?(?:叫|名叫|被称为|被叫作|被称作)\s*{_NAME_PATTERN}"
    rf"|我(?:过去|曾经|当年|以前)?的(?:名字|称呼|名号|称号)是\s*{_NAME_PATTERN}"
)
_MALFORMED_HISTORICAL_SELF_RE = re.compile(
    r"我是我(?=(?:过去|曾经|当年|以前)[^。！？\n]{0,50}(?:称呼|名字|名号|称号))"
)

# 语义崩坏模式：修复后禁止出现的文本
_COLLAPSE_RE = re.compile(r"[他她它祂]是我|我这个名头|我这个名字|我这个称呼|我这个名号|我这个称号")

# 第三人称自述疑似模式（无他人锚点时判为不可修复的自称）
_SELF_NARRATION_RE = re.compile(
    r"[他她它祂](?:从来|从不|不曾|未曾|早已|已经|曾经|只是|不过|向来|一贯|天生|生来)"
    r"|(?:从来|从不|不曾|未曾|早已|已经|曾经|向来)[^。！？\n]{0,4}[他她它祂]"
    r"|[他她它祂](?:喜欢|讨厌|害怕|后悔|记得|遗忘|选择|承担|拒绝|等待|相信|原谅|在乎|介意|心软|回头|认输|低头)"
)
_OTHERS_RE = re.compile("|".join(re.escape(name) for name in KNOWN_OTHER_NAMES))
_GOSSIP_ANCHOR_RE = re.compile(r"别人口中|旁人眼|人人都说|据说|别人叫|别人称|旁人叫|旁人称|众人说|人们说")

_PROTECT_PATTERNS = (
    _NAMING_PREFIX_RE,
    _NAMING_TOPIC_RE,
    _GOSSIP_RE,
    _PEOPLE_CALL_RE,
    _OTHER_ATTRIBUTE_RE,
    _HISTORICAL_NAME_RE,
    _HISTORICAL_OBJECT_RE,
)


@dataclass(frozen=True)
class GuardResult:
    text: str
    status: Literal["clean", "repaired", "unrepairable"]


def _protected_spans(reply: str) -> list[tuple[int, int]]:
    """提取保护段（命名场景 / 他人归属场景），返回合并后的有序区间。"""
    spans: list[tuple[int, int]] = []
    for pattern in _PROTECT_PATTERNS:
        for match in pattern.finditer(reply):
            spans.append((match.start(), match.end()))
    if not spans:
        return []
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _covered(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start >= begin and end <= finish for begin, finish in spans)


def _replace_outside(reply: str, spans: list[tuple[int, int]]) -> str:
    """保护段原样保留，其余名号替换为「我」（切片 + 索引重组，无占位符）。"""
    if not spans:
        return _NAME_RE.sub("我", reply)
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(_NAME_RE.sub("我", reply[cursor:start]))
        pieces.append(reply[start:end])
        cursor = end
    pieces.append(_NAME_RE.sub("我", reply[cursor:]))
    return "".join(pieces)


def _has_self_narration(reply: str) -> bool:
    """回复不含任何已知他人名与引语归属、却以第三人称代词自述 → 疑似纯代词自称。"""
    if not _SELF_NARRATION_RE.search(reply):
        return False
    return not (_OTHERS_RE.search(reply) or _GOSSIP_ANCHOR_RE.search(reply))


def _has_residual(reply: str) -> bool:
    """修复后校验：保护段之外是否仍残留名号。"""
    spans = _protected_spans(reply)
    return any(not _covered(match.span(), spans) for match in _NAME_RE.finditer(reply))


def _guard_reply(reply: str) -> GuardResult:
    if not reply:
        return GuardResult(reply, "clean")
    historical_repaired = _MALFORMED_HISTORICAL_SELF_RE.sub("那是我", reply)
    was_repaired = historical_repaired != reply
    reply = historical_repaired
    if _SELF_INTRO_RE.search(reply) or _HISTORICAL_SELF_NAME_RE.search(reply):
        return GuardResult(reply, "unrepairable")
    spans = _protected_spans(reply)
    fixable = [match for match in _NAME_RE.finditer(reply) if not _covered(match.span(), spans)]
    pronoun_self = _has_self_narration(reply)
    if not fixable and not pronoun_self:
        return GuardResult(reply, "repaired" if was_repaired else "clean")
    if pronoun_self:
        # 模糊代词自称不做破坏性改写，交由调用方重试或兜底
        return GuardResult(reply, "unrepairable")
    repaired = _replace_outside(reply, spans)
    if _has_residual(repaired) or _COLLAPSE_RE.search(repaired) or _has_self_narration(repaired):
        return GuardResult(reply, "unrepairable")
    return GuardResult(repaired, "repaired")


def guard_reply(reply: str) -> GuardResult:
    """对单条模型原始回复执行人称检测与安全修复，输出守门唯一入口。

    clean：text 与输入一致；repaired：text 不含名号自称且保护段原样保留；
    unrepairable：text 为原文，由调用方决定重试/兜底。
    幂等：guard_reply(guard_reply(x).text).text == guard_reply(x).text。
    非预期异常自然外抛，由调用方（SessionService）按兜底策略处置。
    """
    return _guard_reply(reply)


def sanitize_history_reply(reply: str) -> str | None:
    """回传模型前的历史清洗；不可安全清洗时返回 None（该条消息整体从回传上下文剔除）。"""
    try:
        result = guard_reply(reply)
    except Exception:
        logger.exception("history reply sanitize failed; dropping the entry")
        return None
    return None if result.status == "unrepairable" else result.text


def sanitize_visible_reply(reply: str) -> str:
    """玩家可见文本清洗；不可安全清洗时保守返回原文，绝不产生语义崩坏。"""
    try:
        result = guard_reply(reply)
    except Exception:
        logger.exception("visible reply sanitize failed; keeping original text")
        return reply
    return reply if result.status == "unrepairable" else result.text

# ==================== 场景感知守门层（自我介绍场景） ====================
# 语义权威：docs/role-authority.md「自我介绍约定」章节。
# 设计原则：意图门控（无自我介绍意图不检测）、词表锚定（禁止「风」单字）、
# 与名号守门层正交（先复用 guard_reply，再叠加场景检测，零削弱）。

# 自我介绍意图词表（场景检测与场景化兜底的唯一启用开关；子串匹配，
# 天然覆盖「你是谁呀」「做个自我介绍吧」「你叫什么名字？」等变体）
SELF_INTRO_TRIGGERS: tuple[str, ...] = (
    "介绍一下你自己",
    "介绍你自己",
    "介绍一下自己",
    "介绍自己",
    "自我介绍",
    "你是谁",
    "你叫什么",
    "你的名字",
    "怎么称呼你",
)

# 元素表述检测词表（仅词组锚定；「风」单字属风意象合法用法，禁止入表）
ELEMENT_SELF_REFERENCE_TERMS: tuple[str, ...] = ("风元素", "风属性")

# 场景化兜底：直陈式自我介绍，零元素表述、零病态模式，名号仅处合法命名陈述
INTRO_FALLBACK_REPLIES: tuple[str, ...] = (
    "我目前在须弥教令院因论派学习，也算纳西妲的合作者。别把我归进任何国家或组织。想知道什么就直问。",
    "我如今留在须弥，替纳西妲处理些麻烦。不属于任何国家或组织。想问什么，直说。",
)

_ELEMENT_TERM_RE = re.compile("|".join(re.escape(term) for term in ELEMENT_SELF_REFERENCE_TERMS))

# 病态自称表达：自称句（我叫|我是|名字是|称呼是 + 任一名号）＋ 问号 ＋ 必要性否定。
# 精确锚定三段结构，天然排除合法反问（无自称句前缀）与合法直陈拒绝（无先陈述）
_PATHOLOGICAL_SELF_INTRO_RE = re.compile(
    rf"(?:我叫|我是|名字是|称呼是)\s*{_NAME_PATTERN}\s*[？?]\s*[，,]?\s*"
    rf"(?:不[，,]?\s*)?(?:没必要|不必提|无所谓|不重要|不用|不必)\s*[。！？；.．]?"
)

_CLAUSE_DELIM = "，。！？；,.;"
_STRIP_DELIMS = "，、。！？；：,.;: \t\r\n"
# 剔除后不允许：以逗/顿/分/冒号开头或收尾、句读分隔符连续堆叠（断头句）
_DANGLING_DELIM_RE = re.compile(r"^[，、；：]|[，、；：]$|[，。！？；][，。！？；]")


def is_self_introduction(message: str) -> bool:
    """判定玩家消息是否为自我介绍意图（词表子串匹配，空串安全返回 False）。"""
    if not message:
        return False
    return any(trigger in message for trigger in SELF_INTRO_TRIGGERS)


def _structurally_intact(text: str) -> bool:
    """剔除后的重组校验：剥离分隔标点后非空，且无悬空/连续分隔标点断头。"""
    if not text.strip(_STRIP_DELIMS):
        return False
    return _DANGLING_DELIM_RE.search(text) is None


def _remove_pathological_sentences(reply: str) -> str | None:
    """剔除病态自称句（自称句＋问号＋必要性否定）；不可安全剔除返回 None。"""
    if not _PATHOLOGICAL_SELF_INTRO_RE.search(reply):
        return reply
    cleaned = _PATHOLOGICAL_SELF_INTRO_RE.sub("", reply)
    return cleaned if _structurally_intact(cleaned) else None


def _word_level_element_cut(reply: str, start: int, end: int) -> str | None:
    """词级剔除：元素片段独立成句（前为边界/分隔标点、后为分隔标点/边界）时，
    仅剔除片段及其紧邻的一个分隔标点。不适用该粒度时返回 None。"""
    before = reply[:start]
    after = reply[end:]
    if before and before[-1] not in _CLAUSE_DELIM:
        return None
    if after and after[0] not in _CLAUSE_DELIM:
        return None
    if after:
        return before + after[1:]
    if before:
        return before[:-1]
    return ""


def _clause_level_element_cut(reply: str, start: int, end: int) -> str | None:
    """分句级剔除：从元素片段所在分句的左边界（最近分隔标点或行首）到
    右边界（含右侧分隔标点或行尾）整段切片剔除。"""
    left = start
    while left > 0 and reply[left - 1] not in _CLAUSE_DELIM:
        left -= 1
    right = end
    while right < len(reply) and reply[right] not in _CLAUSE_DELIM:
        right += 1
    if right < len(reply):
        right += 1
    return reply[:left] + reply[right:]


def _remove_element_mentions(reply: str) -> str | None:
    """剔除元素表述：词级优先、分句级兜底；任一处不可安全剔除即返回 None（宁缺毋错）。"""
    cleaned = reply
    for _ in range(6):
        match = _ELEMENT_TERM_RE.search(cleaned)
        if match is None:
            break
        candidate = _word_level_element_cut(cleaned, match.start(), match.end())
        if candidate is None or not _structurally_intact(candidate):
            candidate = _clause_level_element_cut(cleaned, match.start(), match.end())
        if candidate is None or not _structurally_intact(candidate):
            return None
        cleaned = candidate
    if _ELEMENT_TERM_RE.search(cleaned) or not _structurally_intact(cleaned):
        return None
    return cleaned


def guard_chat_reply(message: str, reply: str) -> GuardResult:
    """场景感知守门唯一入口（自我介绍场景）。

    第一层复用 guard_reply 名号守门（非自我介绍场景下 unrepairable 直接透传；自我介绍场景允许继续做安全的病态句清理）；
    第二层意图门控 is_self_introduction(message)——判定组件异常按未命中保守处理；
    第三层（命中意图时）病态自称句与元素表述双检测，按「先病态、后元素」迭代
    安全剔除，全部通过才返回 repaired，任一步不可安全剔除返回 unrepairable
    （text 为原文，宁缺毋错）。非自我介绍消息下行为与 guard_reply(reply) 完全一致。
    幂等：guard_chat_reply(m, guard_chat_reply(m, r).text).text == guard_chat_reply(m, r).text。
    """
    try:
        triggered = is_self_introduction(message)
    except Exception:
        logger.exception("self-introduction intent check failed; scene guard disabled for this turn")
        return _guard_reply(reply)
    base = _guard_reply(reply)
    if base.status == "unrepairable" and not triggered:
        return base
    if not triggered:
        return base
    text = base.text
    reduced = _remove_pathological_sentences(text)
    if reduced is None:
        return GuardResult(reply, "unrepairable")
    reduced = _remove_element_mentions(reduced)
    if reduced is None:
        return GuardResult(reply, "unrepairable")
    if reduced == text:
        return base
    recheck = _guard_reply(reduced)
    if recheck.status == "unrepairable" or not _structurally_intact(recheck.text):
        return GuardResult(reply, "unrepairable")
    return GuardResult(recheck.text, "repaired")


def sanitize_history_pair(message: str, reply: str) -> str | None:
    """回传模型前的场景感知历史清洗：非自我介绍历史仅名号清洗（合法元素表述原样
    保留）；不可安全清洗时返回 None（该条消息对整体从回传上下文剔除）。"""
    try:
        result = guard_chat_reply(message, reply)
    except Exception:
        logger.exception("history pair sanitize failed; dropping the entry")
        return None
    return None if result.status == "unrepairable" else result.text


def sanitize_visible_pair(message: str, reply: str) -> str:
    """玩家可见文本的场景感知清洗：自我介绍意图＋违规＋可安全剔除才清洗；
    不可安全清洗时保守返回原文，绝不产生语义崩坏。"""
    try:
        result = guard_chat_reply(message, reply)
    except Exception:
        logger.exception("visible pair sanitize failed; keeping original text")
        return reply
    return reply if result.status == "unrepairable" else result.text
