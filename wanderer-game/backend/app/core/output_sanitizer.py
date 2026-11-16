"""Remove visible source citations and refuse replies that expose internal traces."""

from __future__ import annotations

import re


_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*[^)]*\)")
_AUTOLINK_RE = re.compile(r"(?i)<https?://[^>]+>")
_URL_RE = re.compile(r"(?i)(?:https?://|www\.)[^\s<>\[\](){}\"'，。！？；：]+")
_DOMAIN_RE = re.compile(
    r"(?i)(?<![\w@])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}"
    r"(?:/[^\s<>\[\](){}\"'，。！？；：]*)?"
)
_BRACKET_CITATION_RE = re.compile(
    r"(?i)(?:\[\s*(?:\d{1,3}|\^\d+|source|citation|ref(?:erence)?|来源|出处|资料)\s*\]"
    r"|【\s*(?:\d{1,3}|[^】]{0,80}(?:来源|出处|引自|引用|参考资料|资料来源)[^】]{0,80})\s*】"
    r"|〔\s*(?:\d{1,3}|[^〕]{0,80}(?:来源|出处|引自|引用|参考资料|资料来源)[^〕]{0,80})\s*〕)"
)
_HTML_SOURCE_BLOCK_RE = re.compile(
    r"(?is)<(?:source|citation|reference|metadata|meta)\b[^>]*>.*?</(?:source|citation|reference|metadata|meta)\s*>"
)
_TRACE_RE = re.compile(
    r"(?i)(?:"
    r"(?:据|根据).{0,24}(?:搜索|检索|查询|网站|网页|报道|资料|数据库|知识库|训练数据|训练语料|公告|文章|链接)"
    r"|(?:据|根据|参考|引用|引自).{0,30}(?:维基|百科|官方|研究|报告|资料|报道|网页|网站|论文|数据库|链接|文献)"
    r"|(?:官方|权威|公开|网络|媒体|资料|数据显示|研究|报告|文献).{0,12}(?:显示|指出|表明|记载|称|认为|报道)"
    r"|(?:搜索|检索|查询)(?:结果|到|自|后)"
    r"|(?:来源|出处|资料来源|参考资料|参考文献|数据来源)\s*[:：]"
    r"|\b(?:according\s+to|as\s+(?:reported|cited|referenced)\s+by|source|sources|citation|citations|references?)\s*[:：#\[]"
    r"|(?:我的|本机|系统|内部|模型|底层)?(?:训练数据|训练语料|知识库|数据库|系统提示|开发者指令|提示词|隐藏指令|底层数据|内部上下文)"
    r"|(?:我(?:搜索|检索|查询|联网|浏览)(?:到|了|过|后|的)?)"
    r"|(?:详情|出处|依据|来源|参见|详见).{0,20}(?:公告|官方|网页|链接|网站|报道|资料|文章)"
    r"|\b(?:training\s+data(?:set)?|system\s+prompt|developer\s+prompt|hidden\s+instructions?|knowledge\s+base|internal\s+context|model\s+metadata|retrieval\s+results?|search\s+results?)\b"
    r"|\b(?:as\s+an\s+(?:AI|artificial\s+intelligence)|language\s+model)\b"
    r"|\b(?:I|we)\s+(?:searched|searched\s+the\s+web|looked\s+up|retrieved|queried)\b"
    r"|\b(?:BV[0-9A-Za-z]{10,}|av[0-9]{5,})\b"
    r"|(?:原始|底层|内部)(?:载荷|响应|数据|字段|内容|元数据)"
    r"|\b(?:model(?:_name)?|endpoint|base_url|api_key|response_format|finish_reason|prompt_tokens|completion_tokens|token_usage|choices|messages|role|content|reply|title|emotion|state_delta|next_scene|is_ending|ending_id)\s*[:=]"
    r"|[\"'](?:source|citation|reference|url|metadata|role|content|model|endpoint|choices|usage|reply|title|emotion|state_delta|next_scene|is_ending|ending_id)\s*[\"']\s*:"
    r")"
)
_TRACKING_RE = re.compile(r"(?i)\butm_[a-z0-9_-]+\s*=\s*[^\s，。！？；：]+")
_EMPTY_MARKUP_RE = re.compile(r"(?:\(\s*\)|（\s*）|\[\s*\]|【\s*】|〔\s*〕|<>)+")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([，。！？；：,.!?;:])")


def sanitize_character_reply(value: object) -> str | None:
    """Strip visible citation artifacts; return ``None`` for source/internal traces.

    The caller should retry or use its safe character fallback when a reply is
    refused. This is deliberately applied to complete replies, before they are
    shown, persisted, included in model history, or sent to speech synthesis.
    """
    if not isinstance(value, str):
        return None

    text = _HTML_SOURCE_BLOCK_RE.sub("", value)
    text = _MARKDOWN_LINK_RE.sub("", text)
    text = _AUTOLINK_RE.sub("", text)
    text = _URL_RE.sub("", text)
    text = _DOMAIN_RE.sub("", text)
    text = _BRACKET_CITATION_RE.sub("", text)
    text = _TRACKING_RE.sub("", text)
    if _TRACE_RE.search(text):
        return None

    previous = None
    while previous != text:
        previous = text
        text = _EMPTY_MARKUP_RE.sub("", text)
    text = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text or None
