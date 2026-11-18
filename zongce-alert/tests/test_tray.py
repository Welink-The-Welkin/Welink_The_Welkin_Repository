"""托盘模块的可测逻辑。

GUI 本身（pystray 图标）靠手动验证，但"状态文案""菜单项"这类逻辑必须可测。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tray import build_status_text, build_menu_labels, make_icon_image  # noqa: E402
from tray import describe_restart_steps, read_callback_host  # noqa: E402
import tray as tray_mod  # noqa: E402


class _FakeMenu:
    """吃掉 pystray.Menu 的构造，只保留菜单项的 label 和 action。"""

    SEPARATOR = "<sep>"

    def __init__(self, *items):
        self.items = items


class _FakeMenuItem:
    def __init__(self, label, action, default=False):
        self.label = label
        self.action = action
        self.default = default


class _FakeTray:
    """伪造 pystray 模块：不建真图标，只让 _build_menu 能跑完。"""

    Menu = _FakeMenu
    MenuItem = _FakeMenuItem

    class Icon:  # noqa: D401 - 占位
        def __init__(self, *a, **kw):
            pass

        def notify(self, *a, **kw):
            raise AssertionError("通知气泡不该再被用作状态展示")


def _built_menu(base_dir, status_text="状态占位"):
    """返回 {label: action} 的菜单映射，供直接调用菜单回调。"""
    icon = tray_mod.TrayIcon(
        port=8765,
        status_provider=lambda: status_text,
        on_quit=lambda: None,
        base_dir=base_dir,
    )
    menu = icon._build_menu(_FakeTray)
    plain = _FakeTray.MenuItem
    pairs = {}
    for it in menu.items:
        if it == _FakeMenu.SEPARATOR:
            continue
        assert isinstance(it, plain), it
        pairs[it.label] = it.action
    return pairs, icon


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

    def test_文案清单与真实菜单逐字一致(self):
        """回归：清单里写过「重启提示」，真实菜单却是「重启后要做什么？」。"""
        with tempfile.TemporaryDirectory() as base:
            pairs, _ = _built_menu(base)
        self.assertEqual(list(pairs.keys()), build_menu_labels(port=8765))


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


def _write_callback(base_dir, url):
    data = os.path.join(base_dir, "data")
    os.makedirs(data, exist_ok=True)
    with open(os.path.join(data, "callback-url.txt"), "w", encoding="utf-8") as f:
        f.write(url)


class TestMenuActuallyResponds(unittest.TestCase):
    """回归：两个菜单元只调用通知气泡，通知被系统设置吞掉 = 点了没反应。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        self.menu, self.icon = _built_menu(self.base)
        _write_callback(self.base, "https://laptop-x.tail1234.ts.net/hook?token=abcdefghij")

    def tearDown(self):
        self._tmp.cleanup()

    def test_查看状态会真的弹出可见对话框(self):
        with mock.patch.object(tray_mod, "_show_message_box") as box, \
                mock.patch.object(tray_mod.threading, "Thread") as th:
            th.return_value.start.return_value = None
            self.menu["查看状态"](None, None)
            target = th.call_args.kwargs.get("target")
            self.assertIsNotNone(target, "必须在新线程里弹窗，不能阻塞托盘")
            target()
        box.assert_called_once()
        title, body = box.call_args.args[0], box.call_args.args[1]
        self.assertIn("状态", title)
        self.assertIn("状态占位", body)

    def test_重启提示会真的弹出可见对话框(self):
        with mock.patch.object(tray_mod, "_show_message_box") as box, \
                mock.patch.object(tray_mod.threading, "Thread") as th:
            th.return_value.start.return_value = None
            self.menu["重启后要做什么？"](None, None)
            th.call_args.kwargs["target"]()
        box.assert_called_once()
        self.assertIn("重启", box.call_args.args[0])

    def test_弹窗用原生Unicode接口而非通知气泡(self):
        calls = {}

        class _FakeUser32:
            def MessageBoxW(self, hwnd, text, caption, flags):
                calls["text"] = text
                calls["caption"] = caption
                calls["flags"] = flags
                return 1

        class _FakeWindll:
            user32 = _FakeUser32()

        with mock.patch.object(tray_mod.ctypes, "windll", _FakeWindll(), create=True):
            tray_mod._show_message_box("标题", "内容\n第二行")
        self.assertEqual(calls["text"], "内容\n第二行")
        self.assertEqual(calls["caption"], "标题")
        self.assertTrue(calls["flags"] & 0x40, "要带信息图标")
        self.assertTrue(calls["flags"] & 0x00040000, "要置顶，避免藏在窗口后面")

    def test_弹窗失败不会静默(self):
        def boom(*a, **kw):
            raise OSError("no user32")

        with mock.patch.object(tray_mod.ctypes, "windll", boom, create=True), \
                self.assertLogs("tray", level="WARNING") as logs:
            tray_mod._show_message_box("标题", "内容")
        self.assertTrue(any("弹窗" in line for line in logs.output), logs.output)

    def test_状态取不到时仍给用户可见反馈(self):
        def broken():
            raise RuntimeError("boom")

        icon = tray_mod.TrayIcon(port=8765, status_provider=broken,
                                 on_quit=lambda: None, base_dir=self.base)
        menu = icon._build_menu(_FakeTray)
        pairs = {it.label: it.action for it in menu.items
                 if it != _FakeMenu.SEPARATOR}
        with mock.patch.object(tray_mod, "_show_message_box") as box, \
                mock.patch.object(tray_mod.threading, "Thread") as th, \
                self.assertLogs("tray", level="WARNING"):
            pairs["查看状态"](None, None)
            th.call_args.kwargs["target"]()
        box.assert_called_once()
        self.assertIn("失败", box.call_args.args[1])


class TestRestartSteps(unittest.TestCase):
    def test_Funnel地址说明无需重填(self):
        text = describe_restart_steps("laptop-x.tail1234.ts.net")
        self.assertIn("Funnel", text)
        self.assertIn("不用", text)
        self.assertNotIn("每次重启都会变", text)

    def test_临时隧道地址要求重填(self):
        text = describe_restart_steps("random-words-here.trycloudflare.com")
        self.assertIn("临时隧道", text)
        self.assertIn("start_tunnel.py", text)

    def test_地址未知时给出两种方案(self):
        for host in (None, "", "example.com"):
            text = describe_restart_steps(host)
            self.assertIn("Funnel", text)
            self.assertIn("临时隧道", text)

    def test_读取回调主机名且不吐token(self):
        with tempfile.TemporaryDirectory() as base:
            _write_callback(base, "https://laptop-x.tail1234.ts.net/hook?token=abcdefghij")
            host = read_callback_host(base)
        self.assertEqual(host, "laptop-x.tail1234.ts.net")
        self.assertNotIn("abcdefghij", host)

    def test_文件缺失返回None(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertIsNone(read_callback_host(base))


if __name__ == "__main__":
    unittest.main()
