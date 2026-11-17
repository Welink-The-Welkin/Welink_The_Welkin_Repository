"""`run.py --test` 自检提醒的内容约束。

背景（用户实际困惑，2026-11-17）：
自检弹窗里点「打开原文」会跳到微信公众平台首页。用户以为程序坏了，
实际是因为测试用的假文章 URL 被写成了 `https://mp.weixin.qq.com/`——
一个看起来像真文章、其实是网站首页的地址。

自检的目的是验证「弹窗能不能出来」「声音响不响」「按钮点得动」，
不是验证「链接能不能打开真文章」（假文章根本没有真链接）。
所以测试提醒必须让人一眼看出这是假的，避免误导。
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _self_test_source():
    """取出 run.py 里 self_test 函数的源码。"""
    path = os.path.join(ROOT, "run.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "self_test":
            return ast.get_source_segment(text, node)
    raise AssertionError("run.py 里找不到 self_test 函数")


class TestSelfTestArticle(unittest.TestCase):
    def test_标题标注了这是测试(self):
        src = _self_test_source()
        self.assertTrue(
            "测试" in src,
            "自检提醒的标题应包含「测试」字样，让人一眼知道是假的",
        )

    def test_不再使用微信公众平台首页当占位链接(self):
        """`https://mp.weixin.qq.com/` 是网站首页，不是某篇文章。

        它会让人误以为点了应该打开真文章，从而怀疑程序有问题。
        """
        src = _self_test_source()
        self.assertNotIn(
            'url="https://mp.weixin.qq.com/"',
            src,
            "不要用微信公众平台首页充当假文章链接，容易误导用户",
        )

    def test_占位链接明确指向示例域名(self):
        """若保留链接用于验证按钮可点，应指向 example.com 这类保留域名。"""
        src = _self_test_source()
        self.assertIn(
            "example.com",
            src,
            "自检链接应使用 example.com（RFC 2606 保留域名），一眼看出是示例",
        )

    def test_提示文案说明了链接是假的(self):
        """控制台输出里应提前告诉用户点了会跳到示例页。"""
        src = _self_test_source()
        self.assertTrue(
            "示例" in src or "假" in src or "占位" in src,
            "自检的控制台输出应说明「打开原文」按钮指向的是示例地址",
        )


if __name__ == "__main__":
    unittest.main()
