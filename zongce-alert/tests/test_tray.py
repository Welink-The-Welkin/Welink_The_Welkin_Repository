"""托盘模块的可测逻辑。

GUI 本身（pystray 图标）靠手动验证，但"状态文案""菜单项"这类逻辑必须可测。
"""
import inspect
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


HELP_QUESTIONS = (
    "第一次使用：怎样收到第一篇文章？",
    "收到提醒后，去哪里看文章？",
    "测试成功，为什么待看还是空的？",
    "公众号发文了，却没收到提醒？",
    "有弹窗，为什么没邮件？",
    "电脑重启后，要重新设置吗？",
)


def _menu_actions(menu):
    return {it.label: _menu_actions(it.action) if isinstance(it.action, _FakeMenu) else it.action
            for it in menu.items if it != _FakeMenu.SEPARATOR}


def _built_menu(base_dir, status_text="状态占位"):
    """保留菜单层级，便于按用户实际看到的问题调用回调。"""
    icon = tray_mod.TrayIcon(
        port=8765,
        status_provider=lambda: status_text,
        on_quit=lambda: None,
        base_dir=base_dir,
    )
    return _menu_actions(icon._build_menu(_FakeTray)), icon


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


class TestHelpMenu(unittest.TestCase):
    def test_原顶层入口和顺序不变且帮助是六题子菜单(self):
        menu, icon = _built_menu(".")
        self.assertEqual(list(menu), ["查看状态", "待看文章", "在浏览器中查看状态", "打开日志",
                                      "打开回调地址文件", "帮助", "退出"])
        self.assertTrue(icon._build_menu(_FakeTray).items[0].default)
        self.assertEqual(tuple(menu["帮助"]), HELP_QUESTIONS)
        for action in menu["帮助"].values():
            self.assertEqual(len(inspect.signature(action).parameters), 2)

    def test_逐题弹出对应短答且不执行帮助中提到的操作(self):
        terms = (
            ("启动.bat", "右下角", "^", "FeedWe", "订阅", "打开回调地址文件", "完整地址",
             "自定义 Webhook", r"docs\QUICKSTART.md", "不要公开", "最近正式投递", "待看文章"),
            ("收到", "解析", "默认", "关键词", "同一次", "合并", "待看文章", "刷新", "打开原文", "标记已看", "不会自动"),
            ("自检.bat", "本机", "邮件", "System Test", "不弹", "待看", "最近正式投递", "公网"),
            ("查看状态", "最近正式投递", "待看", "订阅", "隧道", "Webhook", "刷新", "待派送", "派送失败", "最近解析异常", "打开日志"),
            ("查看状态", "邮件", "垃圾", "授权码", "自检.bat"),
            ("自启", "隧道", "图标"),
        )
        with mock.patch.object(tray_mod, "_show_async") as show, \
                mock.patch.object(tray_mod, "read_callback_host", return_value=None) as read_host, \
                mock.patch.object(tray_mod.webbrowser, "open") as browser, \
                mock.patch.object(tray_mod.TrayIcon, "_open_path") as open_path, \
                mock.patch.object(tray_mod.subprocess, "Popen") as launch:
            menu, _ = _built_menu(".")
            show.assert_not_called()
            self.assertIn("帮助", menu)
            for question, expected in zip(HELP_QUESTIONS, terms):
                with self.subTest(question=question):
                    read_host.assert_not_called()
                    menu["帮助"][question](None, None)
                    show.assert_called_once()
                    title, body = show.call_args.args
                    self.assertIn(question, title)
                    for term in expected:
                        self.assertIn(term, body)
                    self.assertLessEqual(len(body), 260)
                    self.assertLessEqual(len(body.splitlines()), 10)
                    self.assertLessEqual(max(map(len, body.splitlines())), 48)
                    show.reset_mock()
            read_host.assert_called_once_with(".")
            browser.assert_not_called()
            open_path.assert_not_called()
            launch.assert_not_called()


class TestInboxMenu(unittest.TestCase):
    def test_待看文章只调用无参本机回调(self):
        open_inbox = mock.Mock()
        icon = tray_mod.TrayIcon(8765, mock.Mock(), mock.Mock(), ".", "dummy",
                                 on_open_inbox=open_inbox)
        menu = icon._build_menu(_FakeTray)
        item = next(it for it in menu.items if getattr(it, "label", None) == "待看文章")
        open_inbox.assert_not_called()
        with mock.patch.object(tray_mod.webbrowser, "open") as browser:
            item.action(icon, item)
        open_inbox.assert_called_once_with()
        browser.assert_not_called()

    def test_未接线或回调失败不泄露原因(self):
        with tempfile.TemporaryDirectory() as base:
            menu, _ = _built_menu(base)
            with mock.patch.object(tray_mod, "_show_async") as show:
                menu["待看文章"](None, None)
                show.assert_called_once()
            icon = tray_mod.TrayIcon(8765, mock.Mock(), mock.Mock(), base,
                                     on_open_inbox=mock.Mock(side_effect=OSError("dummy-secret")))
            item = next(it for it in icon._build_menu(_FakeTray).items
                        if getattr(it, "label", None) == "待看文章")
            with mock.patch.object(tray_mod, "_show_async") as show, \
                    self.assertLogs("tray", level="WARNING") as logs:
                item.action(icon, item)
            show.assert_called_once()
            self.assertNotIn("dummy-secret", str(show.call_args) + str(logs.output))


    def test_窗口启动回报失败时给出可见提示(self):
        icon = tray_mod.TrayIcon(8765, mock.Mock(), mock.Mock(), ".",
                                 on_open_inbox=lambda: False)
        menu = icon._build_menu(_FakeTray)
        item = next(it for it in menu.items if getattr(it, "label", None) == "待看文章")
        with mock.patch.object(tray_mod, "_show_async") as show:
            item.action(icon, item)
        show.assert_called_once()
        self.assertIn("失败", show.call_args.args[1])


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
            self.assertIn("帮助", self.menu)
            self.menu["帮助"][HELP_QUESTIONS[-1]](None, None)
            th.return_value.start.assert_called_once_with()
            box.assert_not_called()
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
        self.assertIn("自启", text)
        self.assertIn("未运行", text, "装了自启但启动失败时，也要告诉用户如何恢复")
        self.assertIn("图标", text)
        self.assertNotIn("即算就绪", text)
        self.assertNotIn("每次重启都会变", text)

    def test_临时隧道地址要求重填(self):
        text = describe_restart_steps("random-words-here.trycloudflare.com")
        self.assertIn("临时隧道", text)
        self.assertIn("start_tunnel.py", text)
        self.assertIn("窗口", text)
        self.assertIn("完整地址", text)
        self.assertIn("Webhook", text)

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

    def test_损坏或不支持的地址使用未知指引而非猜测隧道(self):
        with tempfile.TemporaryDirectory() as base:
            for authority in ("https://[broken.ts.net", "https://private.ts.net:bad",
                              "ftp://private.ts.net", "https://private.ts.net.example.org",
                              "https://name@private.ts.net", "https://bad host.ts.net"):
                with self.subTest(authority=authority):
                    _write_callback(base, authority + "/hook?token=dummy-secret")
                    host = read_callback_host(base)
                    self.assertEqual(describe_restart_steps(host), describe_restart_steps(None))

    def test_每次点重启题都按当前地址回答且不显示主机或凭据(self):
        with tempfile.TemporaryDirectory() as base, mock.patch.object(tray_mod, "_show_async") as show:
            menu, _ = _built_menu(base)
            self.assertIn("帮助", menu)
            restart = menu["帮助"][HELP_QUESTIONS[-1]]
            for host in (None, "private.ts.net", "private.trycloudflare.com", "[broken-private"):
                with self.subTest(host=host):
                    if host:
                        _write_callback(base, f"https://{host}/hook?token=dummy-secret")
                    restart(None, None)
                    show.assert_called_once()
                    title, body = show.call_args.args
                    expected_host = None if host == "[broken-private" else host
                    self.assertEqual(body, describe_restart_steps(expected_host))
                    for private_text in ("private", "https://", "dummy-secret"):
                        self.assertNotIn(private_text, title + body)
                    show.reset_mock()

    def test_文件缺失返回None(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertIsNone(read_callback_host(base))


if __name__ == "__main__":
    unittest.main()
