"""回归测试：测试模式必须能反复触发弹窗。

根因（2026-11-17 实测）：
FeedWe 的测试消息标题固定 "Test article title"、URL 固定指向 feedwe.top，
所以第二次点「发送测试消息」会被去重逻辑判定为"已提醒过"而跳过，
用户看到的现象是"点了没反应"，误以为通路没打通。

测试模式的目的就是反复验证通路，因此必须绕过去重。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from server import AlertService  # noqa: E402

# FeedWe 真实测试消息（2026-11-17 抓取）
FEEDWE_TEST_PAYLOAD = {
    "version": "1",
    "event": "NEW_ARTICLE",
    "accountName": "FeedWe System Test",
    "articles": [
        {
            "id": "article-demo",
            "title": "Test article title",
            "url": "https://feedwe.top/",
            "summary": "This is a sample article payload sent by FeedWe.",
            "publishDate": "2026-11-17T09:38:09.826Z",
        }
    ],
}


def cfg_for(tmpdir):
    return {
        "port": 0,
        "token": "",
        "keywords": ["综测", "加分"],
        "match_field": "title",
        "notify": {"popup": False, "sound": False},
        "email": {"enabled": False},
        "storage": {
            "db_path": os.path.join(tmpdir, "seen.db"),
            "raw_dir": os.path.join(tmpdir, "raw"),
            "save_raw_payload": False,
        },
    }


class TestTestModeRepeatable(unittest.TestCase):
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

    def make(self):
        s = AlertService(cfg_for(self.tmpdir), self.tmpdir)
        self.services.append(s)
        return s

    def test_第一次测试模式会提醒(self):
        s = self.make()
        r = s.handle_payload(FEEDWE_TEST_PAYLOAD, ignore_keywords=True)
        self.assertEqual(r["notified"], 1)

    def test_重复点发送测试消息仍然提醒(self):
        """核心回归用例：这是用户实际遇到的 bug。"""
        s = self.make()
        for i in range(3):
            r = s.handle_payload(FEEDWE_TEST_PAYLOAD, ignore_keywords=True)
            self.assertEqual(
                r["notified"], 1,
                f"第 {i + 1} 次测试消息应仍然弹窗，实际 notified={r['notified']}",
            )

    def test_测试模式不污染正式去重库(self):
        """测试用假文章不能占掉正式去重记录。"""
        s = self.make()
        s.handle_payload(FEEDWE_TEST_PAYLOAD, ignore_keywords=True)
        self.assertEqual(s.store.count(), 0, "测试模式不应写入去重库")

    def test_测试后正式模式仍能正常去重(self):
        s = self.make()
        s.handle_payload(FEEDWE_TEST_PAYLOAD, ignore_keywords=True)
        # 正式模式下这条不含关键词，应被关键词拦掉（与去重无关）
        r = s.handle_payload(FEEDWE_TEST_PAYLOAD, ignore_keywords=False)
        self.assertEqual(r["notified"], 0)
        self.assertEqual(r["skipped_keyword"], 1)

    def test_正式模式重复推送仍只提醒一次(self):
        """正式模式的去重行为不能被改坏。"""
        s = self.make()
        p = {"title": "综测加分活动", "url": "https://mp.weixin.qq.com/s/real"}
        self.assertEqual(s.handle_payload(p)["notified"], 1)
        self.assertEqual(s.handle_payload(p)["notified"], 0)


if __name__ == "__main__":
    unittest.main()
