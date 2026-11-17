"""关键词筛选测试。"""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from filter import match_keywords, KeywordHit  # noqa: E402


class TestMatchKeywords(unittest.TestCase):
    def setUp(self):
        self.kws = ["综测", "综合素质测评", "加分", "第二课堂"]

    def test_命中单个关键词(self):
        hit = match_keywords("关于开展志愿活动的通知（可加综测）", self.kws)
        self.assertTrue(hit.matched)
        self.assertIn("综测", hit.keywords)

    def test_未命中返回False(self):
        hit = match_keywords("关于校园网络维护的通知", self.kws)
        self.assertFalse(hit.matched)
        self.assertEqual(hit.keywords, [])

    def test_多个关键词全部记录(self):
        hit = match_keywords("第二课堂加分活动，综测直接加", self.kws)
        self.assertTrue(hit.matched)
        self.assertIn("综测", hit.keywords)
        self.assertIn("加分", hit.keywords)
        self.assertIn("第二课堂", hit.keywords)

    def test_关键词去重且保持原文出现顺序(self):
        hit = match_keywords("加分加分加分，综测你好，加分", self.kws)
        self.assertEqual(hit.keywords, ["加分", "综测"])

    def test_英文大小写不敏感(self):
        kw = ["volunteer"]
        hit = match_keywords("VOLUNTEER recruiting now", kw)
        self.assertTrue(hit.matched)

    def test_空标题安全(self):
        hit = match_keywords("", self.kws)
        self.assertFalse(hit.matched)

    def test_None标题安全(self):
        hit = match_keywords(None, self.kws)
        self.assertFalse(hit.matched)

    def test_空白关键词被忽略(self):
        hit = match_keywords("随便什么标题", ["", "   ", None])
        self.assertFalse(hit.matched)

    def test_三个字以上关键词也算命中(self):
        hit = match_keywords("综合素质测评办法修订", ["综合素质测评"])
        self.assertTrue(hit.matched)

    def test_KeywordHit带命中位置(self):
        """要能在弹窗里显示命中词，方便判断。"""
        hit = match_keywords("综测加分活动来了", self.kws)
        self.assertIsInstance(hit, KeywordHit)
        self.assertTrue(hit.has("综测"))
        self.assertFalse(hit.has("第二课堂"))


if __name__ == "__main__":
    unittest.main()
