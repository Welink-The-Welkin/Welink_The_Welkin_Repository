"""正式收件与通知任务：一次投递一次事务，不在数据库事务内发送通知。"""
import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from article_parser import Article


_MAX_FAILURES = 3


def _article_id(article):
    url = article.url.strip()
    identity = ["url", url] if url else ["title", article.account.strip(), article.title.strip()]
    try:
        parts = urlsplit(url)
    except ValueError:
        parts = None
    if (parts and parts.scheme in ("http", "https") and
            parts.netloc.lower() == "mp.weixin.qq.com"):
        if re.fullmatch(r"/s/[A-Za-z0-9_-]+", parts.path):
            identity = ["wechat-short", parts.path]
        elif parts.path == "/s":
            params = parse_qs(parts.query)
            # __biz 单独只标识公众号；不完整链接宁可保留原 query，也不合并错文。
            if "mid" in params and ("__biz" in params or "sn" in params) and (
                    "idx" in params or "sn" in params):
                identity = ["wechat-long", [(k, params[k]) for k in ("__biz", "mid", "idx", "sn") if k in params]]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()


def _display_time(timestamp):
    return "" if timestamp is None else datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


class InboxStore:
    def __init__(self, path, *, now=time.time):
        """now 为可选的 Unix 秒时钟；构造不会自动恢复已领取任务。"""
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now
        with self._db() as db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
                    account TEXT NOT NULL, published_at TEXT NOT NULL, received_at REAL NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0, notice_key TEXT
                );
                CREATE INDEX IF NOT EXISTS articles_notice ON articles(notice_key);
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, notice_key TEXT NOT NULL, channel TEXT NOT NULL,
                    keywords TEXT NOT NULL, failures INTEGER NOT NULL DEFAULT 0,
                    ready_at REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id)
                );
                CREATE TABLE IF NOT EXISTS diagnostics (
                    id INTEGER PRIMARY KEY, last_received REAL, last_parse_error REAL
                );
                INSERT OR IGNORE INTO diagnostics(id) VALUES (1);
                COMMIT;
            """)

    @contextmanager
    def _db(self, write=False):
        with closing(sqlite3.connect(self.path, timeout=15, isolation_level=None)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db

    def ingest(self, entries, channels, batch_all=True):
        channels = tuple(channels)
        new = duplicates = 0
        hits, batches = [], {}
        with self._db(write=True) as db:
            now = self._now()
            db.execute("UPDATE diagnostics SET last_received=? WHERE id=1", (now,))
            for article, keywords, legacy_seen in entries:
                key = _article_id(article)
                account = article.account.strip() or "未知公众号"
                # 每篇文章最多属于一条通知；批次以本投递该公众号的首篇新文章为键。
                group = None if legacy_seen else key if keywords else batches.get(account, key) if batch_all else None
                inserted = db.execute("""
                    INSERT INTO articles(id,title,url,account,published_at,received_at,notice_key)
                    VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING
                """, (key, article.title, article.url, account, article.published_at, now, group))
                if not inserted.rowcount:
                    duplicates += 1
                    continue
                new += 1
                if group is None:
                    continue
                if keywords:
                    hits.append(article)
                else:
                    batches[account] = group
                if group == key:
                    db.executemany("INSERT INTO jobs(notice_key,channel,keywords) VALUES (?,?,?)",
                                   ((group, ch, json.dumps(keywords, ensure_ascii=False)) for ch in channels))
        return {"new": new, "duplicates": duplicates, "hits": hits, "batches": len(batches)}

    def unread(self):
        with self._db() as db:
            rows = db.execute("""SELECT id,title,url,account,published_at,received_at FROM articles
                                 WHERE is_read=0 ORDER BY received_at DESC, rowid""")
            return [dict(row, received_at=_display_time(row["received_at"])) for row in rows]

    def mark_read(self, id):
        with self._db() as db:
            db.execute("UPDATE articles SET is_read=1 WHERE id=?", (id,))

    def note_parse_error(self):
        with self._db(write=True) as db:
            now = self._now()
            db.execute("UPDATE diagnostics SET last_received=?, last_parse_error=? WHERE id=1", (now, now))

    def status(self):
        with self._db() as db:
            row = db.execute("""
                SELECT last_received, last_parse_error, (SELECT count(*) FROM articles WHERE is_read=0) AS unread,
                    (SELECT count(*) FROM jobs WHERE failures < ?) AS pending,
                    (SELECT count(*) FROM jobs WHERE failures >= ?) AS failed FROM diagnostics WHERE id=1
            """, (_MAX_FAILURES, _MAX_FAILURES)).fetchone()
            return dict(row, last_received=_display_time(row["last_received"]),
                        last_parse_error=_display_time(row["last_parse_error"]))

    def take_jobs(self, limit=30):
        """每次领取生成唯一的回执编号，迟到的旧回执不能结束新一轮尝试。"""
        with self._db(write=True) as db:
            rows = db.execute("""SELECT j.* FROM jobs j LEFT JOIN claims c ON c.job_id=j.id
                WHERE c.id IS NULL AND j.failures < ? AND j.ready_at <= ?
                ORDER BY CASE WHEN j.keywords='[]' THEN 1 ELSE 0 END, j.id LIMIT ?""",
                (_MAX_FAILURES, self._now(), max(0, int(limit)))).fetchall()
            jobs = []
            for row in rows:
                claim = db.execute("INSERT INTO claims(job_id) VALUES (?)", (row["id"],)).lastrowid
                arts = [Article(**dict(a)) for a in db.execute("""SELECT title,url,account,published_at
                    FROM articles WHERE notice_key=? ORDER BY rowid""", (row["notice_key"],))]
                keywords = json.loads(row["keywords"])
                jobs.append({"id": claim, "channel": row["channel"], "kind": "hit" if keywords else "batch",
                             "articles": arts, "keywords": keywords})
            return jobs

    def finish_job(self, claim_id, ok):
        with self._db(write=True) as db:
            row = db.execute("SELECT job_id,failures FROM claims JOIN jobs ON claims.job_id=jobs.id WHERE claims.id=?",
                             (claim_id,)).fetchone()
            if row is None:
                return
            db.execute("DELETE FROM claims WHERE id=?", (claim_id,))
            if ok:
                db.execute("DELETE FROM jobs WHERE id=?", (row["job_id"],))
            else:
                failures = row["failures"] + 1
                db.execute("UPDATE jobs SET failures=?,ready_at=? WHERE id=?",
                           (failures, self._now() + 15 * failures, row["job_id"]))

    def recover(self):
        """仅在服务取得监听端口后调用；不让中断消耗明确失败的次数。"""
        with self._db(write=True) as db:
            db.execute("DELETE FROM claims")

    def close(self):
        """每次事务已独立关闭连接；供窗口统一清理。"""
