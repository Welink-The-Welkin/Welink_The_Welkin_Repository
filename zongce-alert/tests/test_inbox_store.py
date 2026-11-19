"""收件与派送只使用临时库、人工时钟和构造的文章，不启动任何通知渠道。"""
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from article_parser import Article
from inbox_store import InboxStore


def article(token, account="甲号"):
    return Article(title="标题" + token, url="https://mp.weixin.qq.com/s/" + token,
                   account=account, published_at="2025-01-02", raw={"额外字段": token})


class TestInboxStore(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "data" / "inbox.db"
        self.t = 1700000000
        self.store = self.open_store()

    def open_store(self):
        return InboxStore(self.path, now=lambda: self.t)

    def test_mixed_delivery_batches_only_new_nonhits_per_account(self):
        h1, h2, historical = article("h1"), article("h2"), article("old")
        a, b = article("a"), article("b", " 甲号 ")
        c, d, e = article("c", ""), article("d", "  "), article("e", "乙号")
        entries = [(h1, ["甲", "乙"], False), (a, [], False), (historical, ["甲"], True),
                   (b, [], False), (h2, ["乙"], False), (c, [], False), (d, [], False),
                   (e, [], False), (a, [], False)]
        self.assertEqual(self.store.ingest(entries, ["popup", "email"]),
                         {"new": 8, "duplicates": 1, "hits": [h1, h2], "batches": 3})
        reopened = self.open_store()
        self.assertEqual(reopened.ingest(entries, ["popup", "email"]),
                         {"new": 0, "duplicates": 9, "hits": [], "batches": 0})
        jobs = reopened.take_jobs()
        self.assertEqual(len(jobs), 10)
        for channel in ("popup", "email"):
            actual = []
            for j in jobs:
                if j["channel"] == channel:
                    self.assertIsInstance(j["id"], int)
                    self.assertTrue(all(isinstance(x, Article) and not x.raw for x in j["articles"]))
                    actual.append((j["kind"], [x.url for x in j["articles"]], j["keywords"]))
            self.assertCountEqual(actual, [("hit", [h1.url], ["甲", "乙"]),
                                          ("hit", [h2.url], ["乙"]), ("batch", [a.url, b.url], []),
                                          ("batch", [c.url, d.url], []), ("batch", [e.url], [])])
        self.assertEqual(len(reopened.unread()), 8)
        self.assertEqual(reopened.take_jobs(), [])

    def test_no_channels_and_keyword_only_mode(self):
        a, b, h = article("a"), article("b", "乙号"), article("h")
        self.assertEqual(self.store.ingest([(a, [], False), (b, [], False), (h, ["词"], False)], []),
                         {"new": 3, "duplicates": 0, "hits": [h], "batches": 2})
        self.assertEqual(self.store.take_jobs(), [])
        k = article("k")
        r = self.store.ingest([(article("c"), [], False), (k, ["词"], False)], ["email"], batch_all=False)
        self.assertEqual(r, {"new": 2, "duplicates": 0, "hits": [k], "batches": 0})
        j, = self.store.take_jobs()
        self.assertEqual((j["channel"], j["kind"], j["articles"][0].title), ("email", "hit", k.title))
        self.assertEqual(self.store.status()["unread"], 5)

    def test_real_wechat_identities_but_not_generic_query_or_incomplete_ids(self):
        root = "https://mp.weixin.qq.com/s"
        generic = "https://example.test/s"
        urls = [root + "?__biz=A&mid=1&idx=1&sn=x&scene=1",
                root + "?sn=x&scene=2&mid=1&idx=1&__biz=A#rd",
                root + "?__biz=A&mid=1&idx=2&sn=y", root + "?__biz=B&mid=1&idx=1&sn=z",
                root + "/t-1_2?scene=1", root + "/t-1_2?scene=2#rd", root + "/t-1_3",
                root + "?__biz=A&id=a", root + "?__biz=A&id=b",
                generic + "/abc?item=1", generic + "/abc?item=2",
                generic + "?mid=1&idx=1&sn=x&item=1", generic + "?mid=1&idx=1&sn=x&item=2"]
        entries = [(Article(title="相同标题", url=url), [], False) for url in urls]
        entries.append((Article(title="改过的标题", url=urls[0]), [], False))
        r = self.store.ingest(entries, [])
        self.assertEqual((r["new"], r["duplicates"]), (11, 3))
        self.assertEqual(self.open_store().ingest(entries, ["email"])["duplicates"], 14)
        self.assertEqual(self.store.take_jobs(), [])

    def test_reading_does_not_cancel_jobs_and_success_does_not_mark_read(self):
        a, b = article("a"), article("b")
        self.store.ingest([(a, [], False), (b, [], False)], ["popup"])
        rows = {r["url"]: r for r in self.store.unread()}
        key = rows[a.url]["id"]
        self.assertIsInstance(key, str)
        self.assertEqual(rows[a.url]["title"], a.title)
        self.assertEqual(rows[a.url]["account"], a.account)
        self.assertTrue(rows[a.url]["received_at"])
        self.assertEqual({r["id"] for r in self.open_store().unread()}, {key, rows[b.url]["id"]})
        self.store.mark_read(key)
        self.store.mark_read(key)
        reopened = self.open_store()
        j, = reopened.take_jobs()
        self.assertEqual([x.url for x in j["articles"]], [a.url, b.url])
        self.assertEqual(j["articles"][0].published_at, a.published_at)
        self.assertEqual(reopened.status()["pending"], 1)
        reopened.finish_job(j["id"], True)
        self.assertEqual([r["url"] for r in self.store.unread()], [b.url])
        self.assertEqual(self.store.status()["pending"], 0)
        self.assertEqual(self.store.ingest([(a, [], False)], ["popup"])["duplicates"], 1)
        self.assertEqual(self.store.status()["unread"], 1)

    def test_retry_is_delayed_channel_local_and_terminal_after_three_failures(self):
        self.store.ingest([(article("h"), ["词"], False)], ["popup", "email"])
        by_channel = {j["channel"]: j for j in self.store.take_jobs()}
        self.store.finish_job(by_channel["popup"]["id"], True)
        first = by_channel["email"]["id"]
        self.store.finish_job(first, False)
        for number in (2, 3):
            reopened = self.open_store()
            self.assertEqual(reopened.take_jobs(), [])
            self.assertEqual((reopened.status()["pending"], reopened.status()["failed"]), (1, 0))
            self.t += 3600
            retry, = reopened.take_jobs()
            self.assertEqual(retry["channel"], "email")
            self.assertNotEqual(retry["id"], first)
            reopened.finish_job(first, True)
            reopened.finish_job(retry["id"], False)
        self.t += 86400
        reopened = self.open_store()
        reopened.recover()
        self.assertEqual(reopened.take_jobs(), [])
        self.assertEqual((reopened.status()["pending"], reopened.status()["failed"]), (0, 1))
        self.assertEqual(reopened.status()["unread"], 1)

    def test_only_explicit_recovery_releases_claim_and_fences_old_callback(self):
        self.store.ingest([(article("h"), ["词"], False)], ["email"])
        for _ in range(2):
            j, = self.store.take_jobs()
            self.store.finish_job(j["id"], False)
            self.t += 3600
        interrupted, = self.store.take_jobs()
        reopened = self.open_store()
        self.assertEqual(reopened.take_jobs(), [])
        reopened.recover()
        recovered, = reopened.take_jobs()
        self.assertNotEqual(interrupted["id"], recovered["id"])
        self.store.finish_job(interrupted["id"], True)
        self.store.finish_job(interrupted["id"], False)
        self.assertEqual((reopened.status()["pending"], reopened.status()["failed"]), (1, 0))
        reopened.finish_job(recovered["id"], True)
        self.assertEqual((reopened.status()["pending"], reopened.status()["failed"]), (0, 0))

    def test_delivery_diagnostics_include_repeats_and_parse_errors_after_restart(self):
        self.assertEqual(self.store.status(), {"unread": 0, "pending": 0, "failed": 0,
                                              "last_received": "", "last_parse_error": ""})
        a = article("a")
        self.store.ingest([(a, [], False)], [])
        first = self.store.status()["last_received"]
        self.assertIsNotNone(datetime.fromisoformat(first))
        self.t += 65
        self.store.ingest([(a, [], False)], [])
        repeated = self.store.status()["last_received"]
        self.assertNotEqual(first, repeated)
        self.t += 65
        self.store.note_parse_error()
        state = self.open_store().status()
        self.assertNotEqual(repeated, state["last_received"])
        self.assertTrue(state["last_parse_error"])
        self.t += 65
        self.store.ingest([(article("b"), [], False)], [])
        self.assertEqual(self.store.status()["last_parse_error"], state["last_parse_error"])

    def test_ingest_rolls_back_articles_jobs_and_diagnostics_together(self):
        def aborted():
            yield article("h"), ["词"], False
            raise RuntimeError("构造的中断")

        before = self.store.status()
        with self.assertRaises(RuntimeError):
            self.store.ingest(aborted(), ["email"])
        self.assertEqual(self.open_store().status(), before)
        self.assertEqual(self.store.take_jobs(), [])
        self.assertEqual(self.store.ingest([(article("h"), ["词"], False)], ["email"])["new"], 1)

    def test_simultaneous_writers_and_limited_claimers_do_not_duplicate(self):
        entries = [(article(str(i)), ["词"], False) for i in range(12)]
        gate = threading.Barrier(6)

        def ingest(_):
            store = self.open_store()
            gate.wait(timeout=10)
            return store.ingest(entries, ["email", "popup"])

        def claim(_):
            store = self.open_store()
            gate.wait(timeout=10)
            return store.take_jobs(limit=4)

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(ingest, range(6)))
            claims = list(pool.map(claim, range(6)))
        self.assertEqual(sum(r["new"] for r in results), 12)
        self.assertEqual(sum(r["duplicates"] for r in results), 60)
        self.assertEqual([len(group) for group in claims], [4] * 6)
        jobs = [j for group in claims for j in group]
        self.assertEqual(len({j["id"] for j in jobs}), 24)
        self.assertEqual(len({(j["channel"], j["articles"][0].url) for j in jobs}), 24)
        self.assertEqual(self.store.take_jobs(), [])


if __name__ == "__main__":
    unittest.main()
