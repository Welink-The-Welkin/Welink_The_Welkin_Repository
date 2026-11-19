"""通知渠道回执：不启动真实 GUI，不连接 SMTP。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import notify
from article_parser import Article


class Channels(unittest.TestCase):
    def test_batch_popup_and_fallback_receipt(self):
        n = notify.PopupNotifier({"sound": False})
        n._available = False
        cb = Mock()
        arts = [Article(title="第一篇"), Article(title="第二篇")]
        with patch.object(notify, "_toast_fallback", return_value=False) as toast:
            n.notify_batch("新号", arts, on_result=cb)
        cb.assert_called_once_with(False)
        title, message = toast.call_args.args
        self.assertIn("2 篇", title)
        self.assertIn("第二篇", message)
        self.assertNotIn("命中", message)

    def test_first_failed_gui_start_falls_back_without_queue_loss(self):
        n = notify.PopupNotifier({"sound": False})
        cb = Mock()
        with patch.object(n, "start", side_effect=lambda: setattr(n, "_available", False)), patch.object(notify, "_toast_fallback", return_value=True):
            n.notify("标题", "正文", on_result=cb)
        cb.assert_called_once_with(True)
        self.assertTrue(n._queue.empty())

    def test_queue_acceptance_is_not_a_display_receipt(self):
        n = notify.PopupNotifier({"sound": False})
        cb = Mock()
        with patch.object(n, "start"):
            n.notify("标题", "正文", on_result=cb)
        cb.assert_not_called()
        n._queue.put(None)
        def show(tk, title, msg, url, receipt, batch):
            receipt(True)
            raise RuntimeError("after show")
        with patch.object(n, "_show_one", side_effect=show), patch.object(notify, "_toast_fallback") as fallback:
            n._run()
        cb.assert_called_once_with(True)
        fallback.assert_not_called()

    def test_batch_email_escapes_titles_and_only_safe_links(self):
        s = notify.EmailSender({"enabled": True, "username": "me@example.test", "password": "dummy"})
        arts = [Article(title="<a>", url="https://mp.weixin.qq.com/s/mock"), Article(title="B", url="file:///example")]
        with patch.object(notify.smtplib, "SMTP_SSL") as smtp:
            self.assertTrue(s.send_batch("订阅号\n演示", arts))
            msg = smtp.return_value.send_message.call_args.args[0]
            body = msg.get_payload(decode=True).decode("utf-8")
            self.assertIn("&lt;a&gt;", body)
            self.assertIn("https://mp.weixin.qq.com/s/mock", body)
            self.assertNotIn("file:///", body)
            self.assertNotIn("\n", str(msg["Subject"]))
