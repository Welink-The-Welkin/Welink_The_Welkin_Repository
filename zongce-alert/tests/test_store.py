"""去重存储测试。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from store import SeenStore  # noqa: E402


class TestSeenStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = os.path.join(self.tmpdir, "seen.db")
        self.store = SeenStore(self.db)

    def tearDown(self):
        self.store.close()
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_首次见到返回True(self):
        self.assertTrue(self.store.mark_if_new("https://mp.weixin.qq.com/s/abc", "标题一"))

    def test_重复链接返回False(self):
        self.store.mark_if_new("https://mp.weixin.qq.com/s/abc", "标题一")
        self.assertFalse(self.store.mark_if_new("https://mp.weixin.qq.com/s/abc", "标题一"))

    def test_同标题不同链接视为不同文章(self):
        self.store.mark_if_new("https://mp.weixin.qq.com/s/abc", "标题")
        self.assertTrue(self.store.mark_if_new("https://mp.weixin.qq.com/s/xyz", "标题"))

    def test_重启后仍然去重(self):
        """核心需求：程序重启不能重复弹窗。"""
        self.store.mark_if_new("https://mp.weixin.qq.com/s/abc", "标题一")
        self.store.close()
        store2 = SeenStore(self.db)
        try:
            self.assertFalse(store2.mark_if_new("https://mp.weixin.qq.com/s/abc", "标题一"))
        finally:
            store2.close()

    def test_无链接时用标题指纹去重(self):
        self.assertTrue(self.store.mark_if_new("", "只有标题没有链接"))
        self.assertFalse(self.store.mark_if_new("", "只有标题没有链接"))

    def test_链接带不同查询参数视为同一篇(self):
        """微信链接常带 chksm/scene 等变化参数，需归一化。"""
        self.store.mark_if_new("https://mp.weixin.qq.com/s?__biz=A&mid=1&idx=1&sn=x&chksm=yy", "t")
        self.assertFalse(
            self.store.mark_if_new("https://mp.weixin.qq.com/s?__biz=A&mid=1&idx=1&sn=x&chksm=zz", "t")
        )

    def test_记录数量(self):
        self.store.mark_if_new("a1", "t1")
        self.store.mark_if_new("a2", "t2")
        self.assertEqual(self.store.count(), 2)

    def test_空链接空标题不记录(self):
        self.assertFalse(self.store.mark_if_new("", ""))

    def test_可以在不同线程中写入(self):
        """回归测试：ThreadingHTTPServer 每请求一个线程，
        跨线程写 SQLite 曾导致线上 500 错误。"""
        import threading

        errors = []

        def worker(i):
            try:
                self.store.mark_if_new(f"https://mp.weixin.qq.com/s/t{i}", f"标题{i}")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(self.store.count(), 8)


if __name__ == "__main__":
    unittest.main()
