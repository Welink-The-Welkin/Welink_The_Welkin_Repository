"""Webhook payload 自适应解析测试。

FeedWe 官方未公开 webhook 字段，因此解析器必须能容忍多种可能的结构。
这些用例覆盖了现实中常见的几种形状。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from article_parser import parse_payload, Article  # noqa: E402


class TestParseFlatObject(unittest.TestCase):
    def test_扁平单条(self):
        p = {
            "title": "综测加分通知",
            "url": "https://mp.weixin.qq.com/s/abc",
            "account": "上理大学生",
            "publish_time": "2026-11-17 10:00:00",
        }
        arts = parse_payload(p)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].title, "综测加分通知")
        self.assertEqual(arts[0].url, "https://mp.weixin.qq.com/s/abc")
        self.assertEqual(arts[0].account, "上理大学生")
        self.assertEqual(arts[0].published_at, "2026-11-17 10:00:00")

    def test_常见别名字段(self):
        p = {"Title": "T", "link": "https://mp.weixin.qq.com/s/x", "mp_name": "A", "pub_time": "P"}
        a = parse_payload(p)[0]
        self.assertEqual((a.title, a.url, a.account, a.published_at),
                         ("T", "https://mp.weixin.qq.com/s/x", "A", "P"))

    def test_嵌套data单条(self):
        p = {"event": "new_article",
             "data": {"title": "T", "link": "https://mp.weixin.qq.com/s/y", "author": "A"}}
        a = parse_payload(p)[0]
        self.assertEqual(a.title, "T")
        self.assertEqual(a.url, "https://mp.weixin.qq.com/s/y")
        self.assertEqual(a.account, "A")


class TestParseList(unittest.TestCase):
    def test_顶层数组(self):
        p = [
            {"title": "T1", "url": "https://mp.weixin.qq.com/s/1"},
            {"title": "T2", "url": "https://mp.weixin.qq.com/s/2"},
        ]
        arts = parse_payload(p)
        self.assertEqual([a.title for a in arts], ["T1", "T2"])

    def test_data里是数组(self):
        p = {"data": [
            {"title": "T1", "link": "https://mp.weixin.qq.com/s/1"},
            {"title": "T2", "link": "https://mp.weixin.qq.com/s/2"},
        ]}
        arts = parse_payload(p)
        self.assertEqual(len(arts), 2)

    def test_articles字段是数组(self):
        p = {"articles": [{"title": "T1", "url": "https://mp.weixin.qq.com/s/1"}]}
        self.assertEqual(len(parse_payload(p)), 1)


class TestParseDeepNesting(unittest.TestCase):
    def test_深层嵌套也能挖到文章(self):
        """结构未知时，递归找含 title+url 的对象。"""
        p = {"code": 0, "payload": {"msg": {"items": [
            {"title": "深", "url": "https://mp.weixin.qq.com/s/d"}]}}}
        arts = parse_payload(p)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].title, "深")

    def test_字段名完全不认识但能靠结构识别(self):
        p = {"data": {"headline": "奇怪字段名", "permalink": "https://mp.weixin.qq.com/s/zzz"}}
        arts = parse_payload(p)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].title, "奇怪字段名")


class TestParseEdgeCases(unittest.TestCase):
    def test_字符串输入按JSON解析(self):
        raw = '{"title":"来自字符串","url":"https://u"}'
        self.assertEqual(parse_payload(raw)[0].title, "来自字符串")

    def test_非法JSON不崩溃(self):
        self.assertEqual(parse_payload("{not json"), [])

    def test_空payload返回空列表(self):
        self.assertEqual(parse_payload({}), [])
        self.assertEqual(parse_payload(None), [])

    def test_文本型payload兜底抽取链接(self):
        """有些服务发纯文本，至少要把链接捞出来。"""
        txt = "新文章：综测加分通知 https://mp.weixin.qq.com/s/abc"
        arts = parse_payload(txt)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].url, "https://mp.weixin.qq.com/s/abc")

    def test_无URL的文章被丢弃(self):
        """没有链接就无法打开原文，不算有效文章。"""
        self.assertEqual(parse_payload({"title": "只有标题"}), [])

    def test_时间戳被转成可读时间(self):
        p = {"title": "T", "url": "https://u", "publish_time": 1700000000}
        a = parse_payload(p)[0]
        self.assertIn("-", a.published_at)

    def test_同一篇文章不重复返回(self):
        p = {"a": {"title": "T", "url": "https://u"}, "b": {"title": "T", "url": "https://u"}}
        self.assertEqual(len(parse_payload(p)), 1)


class TestFeedWeRealPayload(unittest.TestCase):
    """基于 FeedWe 真实 payload 的用例（2026-11-17 抓取的实际样本）。

    真实格式里公众号名和发布时间在**顶层**，文章在 articles 数组里：
        {"event":"NEW_ARTICLE","accountName":"上理大学生",
         "articles":[{"title":..., "url":..., "publishDate":...}]}
    早期实现只在文章对象内部找 account，导致"来源"栏永远为空。
    """

    REAL = {
        "version": "1",
        "event": "NEW_ARTICLE",
        "deliveryId": "76a1cc50-83c3-4486-8d75-4934fac6e212",
        "sentAt": "2026-11-17T09:38:09.827Z",
        "userId": "cmwkhi0vt006sqr09qc",
        "accountName": "上理大学生",
        "articles": [
            {
                "id": "article-1",
                "title": "关于开展志愿活动的通知（可加综测）",
                "url": "https://mp.weixin.qq.com/s/abc",
                "summary": "参加可获得综测加分",
                "publishDate": "2026-11-17T09:38:09.826Z",
                "coverImage": "",
            }
        ],
    }

    def test_从顶层取到公众号名(self):
        a = parse_payload(self.REAL)[0]
        self.assertEqual(a.account, "上理大学生")

    def test_取到publishDate时间(self):
        a = parse_payload(self.REAL)[0]
        self.assertNotEqual(a.published_at, "")

    def test_标题和链接正确(self):
        a = parse_payload(self.REAL)[0]
        self.assertEqual(a.title, "关于开展志愿活动的通知（可加综测）")
        self.assertEqual(a.url, "https://mp.weixin.qq.com/s/abc")

    def test_多篇文章都继承顶层公众号名(self):
        p = dict(self.REAL)
        p["articles"] = [
            {"title": "综测活动一", "url": "https://mp.weixin.qq.com/s/1"},
            {"title": "综测活动二", "url": "https://mp.weixin.qq.com/s/2"},
        ]
        arts = parse_payload(p)
        self.assertEqual(len(arts), 2)
        self.assertTrue(all(a.account == "上理大学生" for a in arts))

    def test_文章自带author时优先用自己的(self):
        p = json.loads(json.dumps(self.REAL))
        p["articles"][0]["author"] = "某学院"
        self.assertEqual(parse_payload(p)[0].account, "某学院")

    def test_sentAt可作为时间兜底(self):
        p = json.loads(json.dumps(self.REAL))
        del p["articles"][0]["publishDate"]
        a = parse_payload(p)[0]
        self.assertNotEqual(a.published_at, "", "应回落到顶层 sentAt")


if __name__ == "__main__":
    unittest.main()
