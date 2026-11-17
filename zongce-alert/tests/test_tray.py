"""托盘模块的可测逻辑。

GUI 本身（pystray 图标）靠手动验证，但"状态文案""菜单项"这类逻辑必须可测。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tray import build_status_text, build_menu_labels, make_icon_image  # noqa: E402


class TestStatusText(unittest.TestCase):
    def test_正常时显示运行中(self):
        text = build_status_text(port=8765, seen=12, email_enabled=True)
        self.assertIn("运行中", text)
        self.assertIn("8765", text)
        self.assertIn("12", text)

    def test_邮件未启用时明确说明(self):
        text = build_status_text(port=8765, seen=0, email_enabled=False)
        self.assertIn("邮件", text)
        self.assertIn("未", text)

    def test_邮件启用时显示已开启(self):
        text = build_status_text(port=8765, seen=3, email_enabled=True)
        self.assertIn("已", text)

    def test_多行便于托盘提示阅读(self):
        text = build_status_text(port=8765, seen=1, email_enabled=False)
        self.assertGreaterEqual(len(text.splitlines()), 2)


class TestMenuLabels(unittest.TestCase):
    def test_菜单包含必需项(self):
        labels = build_menu_labels(port=8765)
        joined = " ".join(labels)
        self.assertIn("状态", joined)
        self.assertIn("退出", joined)

    def test_菜单包含打开日志(self):
        labels = build_menu_labels(port=8765)
        self.assertIn("日志", " ".join(labels))

    def test_菜单包含打开回调地址文件(self):
        """用户经常需要复制回调地址去 FeedWe。"""
        labels = build_menu_labels(port=8765)
        self.assertIn("回调", " ".join(labels))


class TestIconImage(unittest.TestCase):
    def test_能生成图标图像(self):
        img = make_icon_image(64)
        self.assertEqual(img.size, (64, 64))
        self.assertEqual(img.mode, "RGBA")

    def test_图标不透明区域存在(self):
        """纯透明图标在托盘里看不见，必须有不透明像素。"""
        img = make_icon_image(64)
        alpha = img.getchannel("A")
        self.assertGreater(max(alpha.getdata()), 0)


if __name__ == "__main__":
    unittest.main()
