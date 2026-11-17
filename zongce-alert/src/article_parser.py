"""Webhook payload 自适应解析，使用唯一模块名以兼容 Python 3.8。

背景：FeedWe 的 webhook 字段格式没有公开文档。硬编码字段名是脆弱设计——
对方一改字段，程序就会静默失效（看起来在跑，其实永远不提醒）。

策略（按顺序）：
1. 先按已知别名表取字段（快、准）
2. 别名表失败时，递归遍历整棵 JSON 树，凡是"像一篇文章"的对象都收上来
3. 纯文本 payload 兜底用正则抽链接

工效优于聪明：宁可偶尔多认，也不要漏。
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from datetime import datetime

# 字段别名，按优先级排列
_TITLE_KEYS = ("title", "Title", "headline", "name", "subject", "article_title")
_URL_KEYS = (
    "url", "Url", "URL", "link", "Link", "permalink", "href",
    "article_url", "content_url", "short_url",
)
_ACCOUNT_KEYS = (
    "account", "mp_name", "author", "source", "nickname",
    "account_name", "feed_name", "official_account",
    "accountName",  # FeedWe 实际使用
)
_TIME_KEYS = (
    "publish_time", "pub_time", "published_at", "publishTime",
    "pubDate", "date", "datetime", "create_time", "timestamp",
    "publish_date",
    "publishDate",  # FeedWe 实际使用
    "sentAt",       # FeedWe 顶层发送时间，作兜底
)
_SUMMARY_KEYS = ("summary", "digest", "desc", "description", "abstract")

# 纯文本里抽链接
_URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s\"'<>）)】\]]+")


@dataclass
class Article:
    title: str = ""
    url: str = ""
    account: str = ""
    published_at: str = ""
    summary: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "account": self.account,
            "published_at": self.published_at,
            "summary": self.summary,
        }


def _first_str(obj: Dict[str, Any], keys: Iterable[str]) -> str:
    for k in keys:
        if k not in obj:
            continue
        v = obj[k]
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _coerce_time(value: Any) -> str:
    """把各种时间表示统一成可读字符串。"""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # 毫秒
            ts /= 1000.0
        if ts > 946684800:  # 2000-01-01 之后才当时间戳
            try:
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (OSError, ValueError, OverflowError):
                return ""
        return ""
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit() and len(s) >= 10:
            return _coerce_time(int(s))
        return s
    return ""


def _looks_like_article(obj: Dict[str, Any]) -> bool:
    """判定一个 dict 是否像一篇文章：必须有可打开的链接。"""
    url = _first_str(obj, _URL_KEYS)
    if not url.startswith("http"):
        return False
    # 必须有标题，否则没意义
    return bool(_first_str(obj, _TITLE_KEYS))


@dataclass
class _Ctx:
    """父级上下文。

    FeedWe 把公众号名放在顶层 accountName，文章在 articles 数组里，
    文章自身不带账号信息。所以需要把父级的账号/时间往下传。
    """

    account: str = ""
    published: str = ""


def _build_article(obj: Dict[str, Any], ctx: Optional[_Ctx] = None) -> Optional[Article]:
    url = _first_str(obj, _URL_KEYS)
    title = _first_str(obj, _TITLE_KEYS)
    if not url.startswith("http"):
        return None
    if not title:
        return None

    published = ""
    for k in _TIME_KEYS:
        if k in obj:
            published = _coerce_time(obj[k])
            if published:
                break
    if not published and ctx is not None:
        published = ctx.published

    # 文章自带 author 优先；否则继承顶层公众号名
    account = _first_str(obj, _ACCOUNT_KEYS)
    if not account and ctx is not None:
        account = ctx.account

    return Article(
        title=title,
        url=url,
        account=account,
        published_at=published,
        summary=_first_str(obj, _SUMMARY_KEYS),
        raw=obj,
    )


def _ctx_of(obj: Dict[str, Any], parent: Optional[_Ctx] = None) -> _Ctx:
    """从当前节点提取可向子节点传递的上下文。"""
    account = _first_str(obj, _ACCOUNT_KEYS)
    published = ""
    for k in ("sentAt", "publish_time", "pub_time", "publishDate"):
        if k in obj:
            published = _coerce_time(obj[k])
            if published:
                break
    return _Ctx(
        account=account or (parent.account if parent else ""),
        published=published or (parent.published if parent else ""),
    )


def _walk(node: Any, out: List[Article], depth: int = 0,
          ctx: Optional[_Ctx] = None) -> None:
    """递归找出所有像文章的节点，并把父级上下文传下去。"""
    if depth > 12:  # 防止异常深的 payload 拖死程序
        return

    if isinstance(node, dict):
        art = _build_article(node, ctx)
        if art is not None:
            out.append(art)
            # 文章内部不再继续挖，避免把 summary 里的链接当另一篇
            return
        child_ctx = _ctx_of(node, ctx)
        for v in node.values():
            _walk(v, out, depth + 1, child_ctx)

    elif isinstance(node, list):
        for item in node:
            _walk(item, out, depth + 1, ctx)


def _dedupe(articles: List[Article]) -> List[Article]:
    seen = set()
    result = []
    for a in articles:
        key = (a.url.strip(), a.title.strip())
        if key in seen:
            continue
        seen.add(key)
        result.append(a)
    return result


def parse_payload(payload: Any) -> List[Article]:
    """把任意 webhook payload 解析成文章列表。

    永远不抛异常——解析失败返回空列表，由调用方记录日志。
    """
    if payload is None:
        return []

    # 字符串先尝试 JSON，失败则按纯文本处理
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8", "replace")
        except Exception:
            return []

    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return _from_plain_text(text)
        return parse_payload(parsed)

    if not isinstance(payload, (dict, list)):
        return []

    # 1) 已知别名精确取（只对顶层和常见容器做，速度快）
    quick = _try_known_shapes(payload)
    if quick:
        return _dedupe(quick)

    # 2) 递归兜底
    found: List[Article] = []
    _walk(payload, found)
    return _dedupe(found)


def _try_known_shapes(payload: Any) -> List[Article]:
    """处理最常见的几种已知结构。"""
    if isinstance(payload, list):
        arts = [a for a in (_build_article(o) for o in payload if isinstance(o, dict)) if a]
        return arts

    if isinstance(payload, dict):
        # 顶层直接就是一篇
        art = _build_article(payload)
        if art is not None:
            return [art]

        # 顶层容器里的公众号名/时间，需要传给文章
        ctx = _ctx_of(payload)

        # 常见的容器字段
        for key in ("data", "articles", "items", "list", "results", "payload", "content"):
            if key not in payload:
                continue
            node = payload[key]
            if isinstance(node, list):
                arts = [
                    a
                    for a in (_build_article(o, ctx) for o in node if isinstance(o, dict))
                    if a
                ]
                if arts:
                    return arts
            elif isinstance(node, dict):
                art = _build_article(node, ctx)
                if art is not None:
                    return [art]

    return []


def _from_plain_text(text: str) -> List[Article]:
    """纯文本 payload：至少把微信文章链接捞出来。"""
    urls = _URL_RE.findall(text)
    if not urls:
        return []

    # 尝试用链接前面的文字当标题
    articles = []
    for url in urls:
        idx = text.find(url)
        prefix = text[:idx].strip().splitlines()
        title = prefix[-1].strip(" ：:-\t") if prefix else ""
        articles.append(Article(title=title or "（未识别标题）", url=url))
    return _dedupe(articles)
