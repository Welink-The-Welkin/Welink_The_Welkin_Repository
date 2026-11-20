"""服务层集成测试：验证「payload → 该不该提醒」的完整决策链路。

这里把弹窗关掉（popup=False），只测决策逻辑，避免测试期间弹窗干扰。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from server import AlertService  # noqa: E402


def base_cfg(tmpdir, **over):
    cfg = {
        "port": 0,
        "token": "",
        "keywords": ["综测", "加分", "第二课堂"],
        "match_field": "title",
        "notify": {"popup": False, "sound": False},
        "email": {"enabled": False},
        "storage": {
            "db_path": os.path.join(tmpdir, "seen.db"),
            "raw_dir": os.path.join(tmpdir, "raw"),
            "save_raw_payload": False,
        },
    }
    cfg.update(over)
    return cfg


class TestAlertService(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.services = []

    def tearDown(self):
        for s in self.services:
            s.store.close()
        for root, dirs, files in os.walk(self.tmpdir, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
            for d in dirs:
                os.rmdir(os.path.join(root, d))
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def make(self, **over):
        s = AlertService(base_cfg(self.tmpdir, **over), self.tmpdir)
        self.services.append(s)
        return s

    def test_命中关键词会提醒(self):
        s = self.make()
        r = s.handle_payload({
            "title": "活动通知（可加综测）",
            "url": "https://mp.weixin.qq.com/s/a1",
        })
        self.assertEqual(r["notified"], 1)
        self.assertEqual(r["items"][0]["keywords"], ["综测"])

    def test_未命中不提醒(self):
        s = self.make()
        r = s.handle_payload({
            "title": "校园网维护通知",
            "url": "https://mp.weixin.qq.com/s/a2",
        })
        self.assertEqual(r["notified"], 0)
        self.assertEqual(r["skipped_keyword"], 1)

    def test_重复推送只提醒一次(self):
        payload = {"title": "加分活动", "url": "https://mp.weixin.qq.com/s/a3"}
        s = self.make()
        r1 = s.handle_payload(payload)
        r2 = s.handle_payload(payload)
        self.assertEqual(r1["notified"], 1)
        self.assertEqual(r2["notified"], 0)
        self.assertEqual(r2["skipped_duplicate"], 1)

    def test_同一次推送里多篇命中都会提醒(self):
        s = self.make()
        r = s.handle_payload({"data": [
            {"title": "综测活动一", "url": "https://mp.weixin.qq.com/s/m1"},
            {"title": "综测活动二", "url": "https://mp.weixin.qq.com/s/m2"},
            {"title": "无关通知", "url": "https://mp.weixin.qq.com/s/m3"},
        ]})
        self.assertEqual(r["parsed"], 3)
        self.assertEqual(r["notified"], 2)

    def test_标题加摘要模式下摘要命中会提醒(self):
        s = self.make(match_field="title_and_summary")
        r = s.handle_payload({
            "title": "关于活动的通知",
            "summary": "参加可获得综测加分",
            "url": "https://mp.weixin.qq.com/s/s1",
        })
        self.assertEqual(r["notified"], 1)
        self.assertEqual(r["items"][0]["keywords"], ["综测", "加分"])

    def test_只看标题模式下摘要命中不算(self):
        s = self.make(match_field="title")
        r = s.handle_payload({
            "title": "关于活动的通知",
            "summary": "参加可获得综测加分",
            "url": "https://mp.weixin.qq.com/s/s2",
        })
        self.assertEqual(r["notified"], 0)

    def test_缺失或空摘要不产生关键词命中(self):
        s = self.make(match_field="title_and_summary", keywords=["综测", "None"])
        summaries = ({}, {"summary": None}, {"summary": ""}, {"summary": " \t"})
        for index, fields in enumerate(summaries):
            with self.subTest(summary=fields):
                r = s.handle_payload({"articles": [
                    {"title": "关于活动的通知", "url": f"https://example.com/skip/{index}", **fields},
                    {"title": "综测活动通知", "url": f"https://example.com/notify/{index}", **fields},
                ]})
                self.assertEqual(r["parsed"], 2)
                self.assertEqual(r["skipped_keyword"], 1)
                self.assertEqual(r["items"], [{"title": "综测活动通知", "keywords": ["综测"]}])

    def test_摘要模式不匹配独立的正文字段(self):
        s = self.make(match_field="title_and_summary")
        r = s.handle_payload({
            "title": "关于活动的通知",
            "summary": "",
            "content": "参加可获得综测加分",
            "url": "https://example.com/body-only",
        })
        self.assertEqual(r["notified"], 0)
        self.assertEqual(r["skipped_keyword"], 1)

    def test_无关payload返回no_articles(self):
        s = self.make()
        r = s.handle_payload({"hello": "world"})
        self.assertEqual(r["reason"], "no_articles")

    def test_已提醒记录持久化用于统计(self):
        s = self.make()
        s.handle_payload({"title": "综测A", "url": "https://mp.weixin.qq.com/s/p1"})
        s.handle_payload({"title": "综测B", "url": "https://mp.weixin.qq.com/s/p2"})
        self.assertEqual(s.store.count(), 2)

    def test_未命中的不占用去重库(self):
        s = self.make()
        s.handle_payload({"title": "无关", "url": "https://mp.weixin.qq.com/s/q1"})
        self.assertEqual(s.store.count(), 0)


if __name__ == "__main__":
    unittest.main()
