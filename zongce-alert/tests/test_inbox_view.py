"""本机待看文章：模拟 Tk、子进程和浏览器，不创建窗口或联网。"""
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import inbox_view as view  # noqa: E402


class TestWindowLauncher(unittest.TestCase):
    def test_固定脚本独立参数无凭据且只启动一个存活窗口(self):
        db = Path("带空格 & 符号") / "inbox.sqlite"
        with mock.patch.object(view, "_window_process", None), \
                mock.patch.object(view.subprocess, "Popen") as spawn, \
                mock.patch.dict(os.environ, {"ZONGCE_TOKEN": "dummy-auth", "OTHER_API_KEY": "dummy-key"}):
            process = spawn.return_value
            process.poll.side_effect = [None, 0]
            self.assertTrue(view.open_inbox_window(db))
            self.assertTrue(view.open_inbox_window(db))
            spawn.assert_called_once()
            process.wait.assert_not_called()
            argv, = spawn.call_args.args
            self.assertEqual(argv[0], sys.executable)
            self.assertTrue(all(arg.startswith("-") for arg in argv[1:-2]))
            self.assertEqual(Path(argv[-2]), SRC / "inbox_view.py")
            self.assertEqual(Path(argv[-1]), db.absolute())
            kwargs = spawn.call_args.kwargs
            self.assertFalse(kwargs.get("shell", False))
            self.assertNotIn("ZONGCE_TOKEN", kwargs["env"])
            self.assertNotIn("OTHER_API_KEY", kwargs["env"])
            self.assertTrue(view.open_inbox_window(db))
            self.assertEqual(spawn.call_count, 2)

    def test_启动失败可重试且不记录原始异常(self):
        with mock.patch.object(view, "_window_process", None), \
                mock.patch.object(view.subprocess, "Popen", side_effect=[OSError("dummy-secret"), mock.Mock()]), \
                self.assertLogs(view.__name__, level="WARNING") as logs:
            self.assertFalse(view.open_inbox_window("inbox.db"))
            self.assertTrue(view.open_inbox_window("inbox.db"))
        self.assertNotIn("dummy-secret", str(logs.output))


class TestInboxWindow(unittest.TestCase):
    first = {"id": "first", "title": "同名文章", "url": "https://example.test/a?mid=12&idx=1",
             "account": "来源甲", "received_at": 1700000000.0}
    second = dict(first, id="second", account="来源乙", url="http://example.test/b")

    def setUp(self):
        self.store = mock.Mock()
        self.store.unread.return_value = [self.first, self.second]
        self.factory = mock.Mock(return_value=self.store)
        self.commands = {}
        self.tk = ModuleType("tkinter")
        self.tk.Tk = mock.Mock()
        self.tk.StringVar = mock.Mock()
        self.tk.ttk = mock.MagicMock()
        self.tree = self.tk.ttk.Treeview.return_value
        self.tree.selection.return_value = ()
        self.status = self.tk.StringVar.return_value
        self.tk.ttk.Button.side_effect = self._button
        self.browser = mock.Mock(return_value=True)

    def _button(self, parent, *, text, command):
        self.commands[text] = command
        return mock.Mock()

    def run_window(self, actions):
        self.tk.Tk.return_value.mainloop.side_effect = actions
        with mock.patch.dict(sys.modules, {"tkinter": self.tk, "tkinter.ttk": self.tk.ttk}), \
                mock.patch.object(view.webbrowser, "open", self.browser):
            view._show_window("local.db", self.factory)

    def test_只显示时间来源标题_打开不写入_标已看按稳定ID(self):
        self.store.unread.side_effect = [[self.first, self.second], [self.second, self.first], [self.first]]

        def actions():
            headings = [args.kwargs["text"] for args in self.tree.heading.call_args_list]
            self.assertEqual(headings, ["接收时间", "来源", "标题"])
            local_time = datetime.fromtimestamp(self.first["received_at"]).strftime("%Y-%m-%d %H:%M:%S")
            self.tree.insert.assert_any_call("", "end", iid="first", values=(local_time, "来源甲", "同名文章"))
            self.assertNotIn("example.test", str(self.tree.insert.call_args_list))
            self.commands["刷新"]()
            self.browser.assert_not_called()
            self.store.mark_read.assert_not_called()
            self.tree.selection.return_value = ("second",)
            self.commands["打开原文"]()
            self.browser.assert_called_once_with(self.second["url"])
            self.store.mark_read.assert_not_called()
            self.commands["标记已看"]()
            self.store.mark_read.assert_called_once_with("second")
            self.assertEqual(self.store.unread.call_count, 3)

        self.run_window(actions)
        self.factory.assert_called_once_with("local.db")
        self.store.close.assert_called_once_with()

    def test_无选中或过期选中不打开不标已看(self):
        def actions():
            for selection in ((), ("no-longer-listed",)):
                self.tree.selection.return_value = selection
                self.commands["打开原文"]()
                self.commands["标记已看"]()
        self.run_window(actions)
        self.browser.assert_not_called()
        self.store.mark_read.assert_not_called()

    def test_拒绝不规范协议凭据和畸形地址(self):
        invalid = [None, "", "//example.test/a", "file:///local", "javascript:void(0)",
                   "https:example.test/a", "https:///missing-host", "https://u:p@example.test/",
                   "https://@example.test/", "https://example.test:99999/", "https://[broken/",
                   "https://[::1]extra/", " https://example.test/", "https://example.test/a\nb",
                   "https://example.test/a\\b", "https://bad host/", "https://example.test/%0D",
                   "https://example.test/%zz", "https://bad%2fhost/", "https://example.test/a?token=dummy"]
        self.store.unread.return_value = [dict(self.first, id=str(i), url=url) for i, url in enumerate(invalid)]

        def actions():
            for i, url in enumerate(invalid):
                with self.subTest(url=url):
                    self.tree.selection.return_value = (str(i),)
                    self.commands["打开原文"]()
                    self.browser.assert_not_called()
        self.run_window(actions)
        self.store.mark_read.assert_not_called()
        self.assertNotIn("example.test", str(self.status.set.call_args_list))

    def test_合法文章地址保留查询参数(self):
        url = self.first["url"]

        def actions():
            self.tree.selection.return_value = ("first",)
            self.commands["打开原文"]()
        self.run_window(actions)
        self.browser.assert_called_once_with(url)
        self.store.mark_read.assert_not_called()

    def test_数据库和浏览器失败可恢复且只显示通用错误(self):
        secret = "dummy-private-detail"
        self.factory.side_effect = [OSError(secret), self.store]
        self.store.unread.side_effect = [OSError(secret), [self.first]]
        self.store.mark_read.side_effect = OSError(secret)
        self.browser.side_effect = OSError(secret)

        def actions():
            self.assertIn("失败", self.status.set.call_args.args[0])
            self.commands["刷新"]()
            self.assertIn("失败", self.status.set.call_args.args[0])
            self.commands["刷新"]()
            self.tree.selection.return_value = ("first",)
            self.commands["打开原文"]()
            self.assertIn("失败", self.status.set.call_args.args[0])
            self.store.mark_read.assert_not_called()
            self.commands["标记已看"]()
            self.assertIn("失败", self.status.set.call_args.args[0])
            self.assertNotIn(secret, str(self.status.set.call_args_list))
        self.run_window(actions)
        self.store.close.assert_called_once_with()

    def test_关闭时清理失败不标已看或打开链接(self):
        self.store.close.side_effect = OSError("dummy-close-error")
        self.run_window(lambda: None)
        self.store.close.assert_called_once_with()
        self.store.mark_read.assert_not_called()
        self.browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
