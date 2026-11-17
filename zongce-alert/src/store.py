"""已读文章存储（去重）。

用 SQLite，因为要保证「程序重启后不重复弹窗」。
链接归一化处理：微信文章链接常带 chksm/scene/chksm 等易变参数，
同一个 mid+idx+sn 就应视为同一篇。
"""
import hashlib
import os
import re
import sqlite3
import threading
import time
from typing import Optional
from urllib.parse import urlsplit, parse_qs

# 能唯一确定一篇文章的参数组合
_ID_KEYS = ("__biz", "mid", "idx", "sn")


def normalize_url(url: Optional[str]) -> str:
    """把链接归一化成稳定指纹来源。

    - 微信长链接：只保留 __biz/mid/idx/sn
    - 微信短链接 /s/xxx：保留路径
    - 其它链接：去掉 query 和 fragment
    """
    if not isinstance(url, str):
        return ""
    url = url.strip()
    if not url:
        return ""

    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    qs = parse_qs(parts.query)
    if all(k in qs for k in ("mid", "idx", "sn")) or "__biz" in qs:
        ident = "&".join(f"{k}={qs[k][0]}" for k in _ID_KEYS if k in qs)
        if ident:
            return f"{parts.netloc}{parts.path}?{ident}"

    # /s/<token> 短链，路径本身唯一
    if re.match(r"^/s/[A-Za-z0-9_-]+$", parts.path or ""):
        return f"{parts.netloc}{parts.path}"

    return f"{parts.netloc}{parts.path}"


def fingerprint(url: Optional[str], title: Optional[str]) -> str:
    """生成去重指纹。优先用链接，无链接退回标题。"""
    norm = normalize_url(url)
    if norm:
        basis = "url:" + norm
    else:
        basis = "title:" + (title or "").strip()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


class SeenStore:
    def __init__(self, db_path: str):
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        # ThreadingHTTPServer 每个请求一个线程，必须允许跨线程复用连接。
        # 并发写由下面的 _lock 串行化，保证事务安全。
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen (
                    fp        TEXT PRIMARY KEY,
                    title     TEXT,
                    url       TEXT,
                    seen_at   REAL NOT NULL
                )
                """
            )
            self._conn.commit()

    def mark_if_new(self, url: Optional[str], title: Optional[str]) -> bool:
        """首次出现返回 True 并记录；已存在返回 False。

        空链接且空标题视为无效数据，返回 False 且不记录。
        """
        if not (normalize_url(url) or (title or "").strip()):
            return False

        fp = fingerprint(url, title)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO seen (fp, title, url, seen_at) VALUES (?, ?, ?, ?)",
                    (fp, title or "", url or "", time.time()),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM seen").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
