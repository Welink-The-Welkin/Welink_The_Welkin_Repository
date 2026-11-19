"""本地集成：使用临时库、假弹窗，不访问 FeedWe 或邮箱。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from config import DEFAULT_CONFIG
from server import AlertService


def article(n, title="普通通知"):
    return {"title": title, "url": "https://mp.weixin.qq.com/s/" + str(n)}


def delivery(account, *items):
    return {"event": "NEW_ARTICLE", "accountName": account, "articles": list(items)}


class ServiceInboxTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = tmp.name
        self.s = self.start()

    def start(self, **overrides):
        cfg = {"keywords": ["综测"], "notify": {"popup": False}, "email": {},
               "storage": {"save_raw_payload": False}, "batch_all_accounts": True}
        cfg.update(overrides)
        srv = AlertService(cfg, self.path)
        self.addCleanup(srv.store.close)
        srv.notifier = Mock()
        srv.notifier.notify.side_effect = lambda t, m, url, on_result=None: on_result and on_result(True)
        srv.notifier.notify_batch.side_effect = lambda a, arts, on_result=None: on_result and on_result(True)
        return srv

    def test_default_and_shipped_config_cover_every_account(self):
        self.assertIs(DEFAULT_CONFIG.get("batch_all_accounts"), True)
        self.assertIs(json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["batch_all_accounts"], True)

    def test_mixed_delivery_and_future_account(self):
        result = self.s.handle_payload(delivery("新订阅号", article(1, "综测活动"), article(2), article(3)))
        self.assertEqual((result["notified"], result["batch_notifications"], result["inbox_new"]), (1, 1, 3))
        self.s.pump_once()
        self.assertEqual(self.s.notifier.notify.call_count, 1)
        call = self.s.notifier.notify_batch.call_args
        self.assertEqual((call.args[0], len(call.args[1])), ("新订阅号", 2))
        self.assertEqual(len(self.s.inbox.unread()), 3)

    def test_duplicate_after_restart_without_read_or_second_batch(self):
        p = delivery("新号", article(1), article(2))
        self.s.handle_payload(p)  # 在发送前退出
        nxt = self.start()
        nxt.inbox.recover()
        self.assertEqual(nxt.handle_payload(p)["inbox_new"], 0)
        nxt.pump_once()
        self.assertEqual(nxt.notifier.notify_batch.call_count, 1)
        self.assertEqual(len(nxt.inbox.unread()), 2)
        nxt.handle_payload(p)
        nxt.pump_once()
        self.assertEqual(nxt.notifier.notify_batch.call_count, 1)

    def test_legacy_seen_not_resent_but_new_unread_persisted(self):
        a = article("old", "综测旧通知")
        self.s.store.mark_if_new(a["url"], a["title"])
        r = self.s.handle_payload(a)
        self.s.pump_once()
        self.assertEqual(r["notified"], 0)
        self.assertEqual(len(self.s.inbox.unread()), 1)
        self.s.notifier.notify.assert_not_called()

    def test_fallback_still_alerts_when_inbox_write_fails(self):
        with patch.object(self.s.inbox, "ingest", side_effect=OSError("storage unavailable")):
            r = self.s.handle_payload(delivery("新号", article(1, "综测"), article(2)))
        self.assertFalse(r["ok"])
        self.assertTrue(r["degraded"])
        self.s.notifier.notify.assert_called_once()
        self.s.notifier.notify_batch.assert_called_once()
        self.assertIn("异常", self.s.inbox_status_text())

    def test_testing_does_not_change_formal_receipt(self):
        self.s.handle_payload(delivery("FeedWe System Test", article(1)))
        self.s.handle_payload(delivery("普通号", article(2)), ignore_keywords=True)
        self.assertFalse(self.s.inbox.status()["last_received"])
        self.assertFalse(self.s.inbox.unread())

    def test_group_by_subscription_not_article_author(self):
        a, b = article(1), article(2)
        a["author"], b["author"] = "作者甲", "作者乙"
        r = self.s.handle_payload(delivery("订阅号", a, b))
        self.assertEqual(r["batch_notifications"], 1)
        self.s.pump_once()
        self.assertEqual(self.s.notifier.notify_batch.call_args.args[0], "订阅号")

    def test_nested_article_in_feedwe_batch_is_not_silently_omitted(self):
        self.s.handle_payload(delivery("号", article(1), {"data": article(2)}))
        self.assertEqual(len(self.s.inbox.unread()), 2)
        self.assertFalse(self.s.inbox.status()["last_parse_error"])

    def test_shared_non_wechat_path_keeps_both_keyword_articles(self):
        a, b = article(1, "综测报名（一）"), article(2, "综测报名（二）")
        a["url"], b["url"] = "https://example.test/article?id=1", "https://example.test/article?id=2"
        self.s.handle_payload(a)
        self.assertEqual(self.s.handle_payload(b)["notified"], 1)

    def test_partial_or_empty_real_delivery_visible(self):
        self.s.handle_payload(delivery("号", article(1), {"title": "缺链接"}))
        self.assertTrue(self.s.inbox.status()["last_parse_error"])
        self.assertEqual(len(self.s.inbox.unread()), 1)
        self.s.handle_payload(delivery("号", {"unrecognized": 1}))
        self.assertIn("解析异常", self.s.inbox_status_text())

    def test_legacy_record_from_one_query_does_not_swallow_other_query(self):
        a, b = article(1, "综测报名（一）"), article(2, "综测报名（二）")
        a["url"], b["url"] = "https://example.test/article?id=1", "https://example.test/article?id=2"
        self.s.store.mark_if_new(a["url"], a["title"])
        self.assertEqual(self.s.handle_payload(b)["notified"], 1)

    def test_receipt_write_error_retried_without_second_physical_notice(self):
        p = delivery("号", article(1))
        self.s.handle_payload(p)
        complete = self.s.inbox.finish_job
        with patch.object(self.s.inbox, "finish_job", side_effect=OSError("brief fault")):
            self.s.pump_once()
        with patch.object(self.s.inbox, "finish_job", wraps=complete) as retry:
            self.s.pump_once()
            self.assertTrue(retry.called)
        self.assertEqual(self.s.inbox.status()["pending"], 0)
        self.assertEqual(self.s.notifier.notify_batch.call_count, 1)
        self.assertEqual(len(self.s.inbox.unread()), 1)

    def test_partial_wechat_identifiers_must_not_collide_with_legacy(self):
        root = "https://mp.weixin.qq.com/s?mid="
        self.s.store.mark_if_new(root + "10&idx=1", "综测 A")
        result = self.s.handle_payload({"title": "综测 B", "url": root + "11&idx=1"})
        self.assertEqual(result["notified"], 1)

    def test_damaged_legacy_store_does_not_block_persistent_queue(self):
        self.s.handle_payload(delivery("新号", article(1)))
        self.s.store.close()
        (Path(self.path) / "data" / "seen.db").write_bytes(b"not a database")
        nxt = self.start()
        nxt.pump_once()
        self.assertEqual(nxt.notifier.notify_batch.call_count, 1)
        self.assertEqual(len(nxt.inbox.unread()), 1)
        self.assertIn("旧版", nxt.inbox_status_text())

    def test_degraded_redelivery_does_not_repeat_or_lose_backfill(self):
        hist = article(0, "综测旧文")
        self.s.store.mark_if_new(hist["url"], hist["title"])
        p = delivery("号", hist, article(1, "综测"), article(2))
        with patch.object(self.s.inbox, "ingest", side_effect=OSError()):
            for _ in range(2):
                self.assertFalse(self.s.handle_payload(p)["ok"])
        self.assertEqual(self.s.notifier.notify.call_count, 1)
        self.assertEqual(self.s.notifier.notify_batch.call_count, 1)
        self.assertEqual(self.s.handle_payload(p)["inbox_new"], 3)

    def test_batch_switch_does_not_disable_inbox_or_immediate_alert(self):
        svc = self.start(batch_all_accounts=False)
        svc.handle_payload(delivery("号", article(1), article(2, "综测")))
        svc.pump_once()
        self.assertEqual(len(svc.inbox.unread()), 2)
        svc.notifier.notify.assert_called_once()
        svc.notifier.notify_batch.assert_not_called()
