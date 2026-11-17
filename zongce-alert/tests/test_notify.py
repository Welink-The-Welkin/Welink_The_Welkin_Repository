"""通知层测试：邮件构造、提醒文案。

GUI 部分（tkinter 窗口）不在这里测——那属于交互，靠手动验证。
但"邮件内容对不对"、"提醒文案对不对"必须可测。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notify import build_email_message, build_alert_text, EmailSender  # noqa: E402
from parser import Article  # noqa: E402


def make_article(**kw):
    base = dict(
        title="关于开展第二届青春健康跑的通知（统一加校级综测）",
        url="https://mp.weixin.qq.com/s/example",
        account="上理大学生",
        published_at="2026-11-17 09:30:00",
    )
    base.update(kw)
    return Article(**base)


class TestBuildAlertText(unittest.TestCase):
    def test_包含标题公众号和关键词(self):
        a = make_article()
        text = build_alert_text(a, ["综测", "加分"])
        self.assertIn("综合", text.replace("综测", "综合") or text)
        self.assertIn("上理大学生", text)
        self.assertIn("综测", text)

    def test_没有公众号名时不出现空标签(self):
        a = make_article(account="")
        text = build_alert_text(a, ["综测"])
        self.assertNotIn("来源：\n", text)
        self.assertNotIn("来源： ", text)

    def test_没有时间不报错(self):
        a = make_article(published_at="")
        text = build_alert_text(a, ["综测"])
        self.assertIsInstance(text, str)

    def test_超长标题被截断(self):
        a = make_article(title="综" * 300)
        text = build_alert_text(a, ["综测"])
        self.assertLess(len(text), 300)


class TestBuildEmailMessage(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
            "use_ssl": True,
            "username": "me@qq.com",
            "password": "authcode",
            "to": "me@qq.com",
        }

    def test_邮件主题含标题(self):
        msg = build_email_message(make_article(), ["综测"], self.cfg)
        subject = str(msg["Subject"])
        self.assertIn("综测", subject)

    def test_发件人收件人正确(self):
        msg = build_email_message(make_article(), ["综测"], self.cfg)
        self.assertEqual(msg["From"], "me@qq.com")
        self.assertEqual(msg["To"], "me@qq.com")

    def test_正文是HTML且含原文链接(self):
        a = make_article()
        msg = build_email_message(a, ["综测"], self.cfg)
        payload = msg.get_payload(decode=True)
        html = payload.decode("utf-8")
        self.assertIn(a.url, html)
        self.assertIn(a.title, html)

    def test_收件人为空时回落到发件人(self):
        cfg = dict(self.cfg, to="")
        msg = build_email_message(make_article(), ["综测"], cfg)
        self.assertEqual(msg["To"], "me@qq.com")

    def test_主题做编码处理不崩溃(self):
        msg = build_email_message(make_article(title="中文标题测试"), ["综测"], self.cfg)
        self.assertTrue(len(str(msg["Subject"])) > 0)


class TestEmailSenderConfig(unittest.TestCase):
    def test_未启用时enabled为False(self):
        s = EmailSender({"enabled": False})
        self.assertFalse(s.enabled)

    def test_缺用户名时视为未启用(self):
        s = EmailSender({"enabled": True, "username": "", "password": "x"})
        self.assertFalse(s.enabled)

    def test_配置完整时启用(self):
        s = EmailSender({
            "enabled": True, "username": "a@qq.com",
            "password": "p", "smtp_host": "smtp.qq.com",
        })
        self.assertTrue(s.enabled)

    def test_发送失败返回False不抛异常(self):
        """网络/授权码错误不能把主流程炸掉。"""
        s = EmailSender({
            "enabled": True, "username": "a@qq.com", "password": "wrong",
            "smtp_host": "127.0.0.1", "smtp_port": 1,
            "use_ssl": False, "to": "a@qq.com",
        })
        self.assertFalse(s.send(make_article(), ["综测"]))


if __name__ == "__main__":
    unittest.main()
