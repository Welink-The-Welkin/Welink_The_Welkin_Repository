"""start_tunnel.py 的 Funnel 模式回归测试。

背景：原来脚本只会走 Cloudflare 快速隧道，地址每次重启都变，
必须人工去 FeedWe 后台改。加了 Tailscale Funnel 模式后，地址固定，
所以有两件事必须保证：

1. Funnel 模式不再打印"每次重启都会变"的提醒（否则用户白折腾）；
2. Funnel 模式不再每次覆盖 data/callback-url.txt（覆盖虽无害，
   但会让用户以为地址又变了）。

这些测试只测纯函数和输出，不碰真实网络和真实 tailscale。
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import start_tunnel  # noqa: E402


def _capture(fn, *a, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*a, **kw)
    return buf.getvalue()


class TestFunnelPorts(unittest.TestCase):
    """Funnel 只允许 443/8443/10000，本地端口必须映射过去。"""

    def test_端口白名单就是这三个(self):
        self.assertEqual(set(start_tunnel.FUNNEL_PORTS), {443, 8443, 10000})

    def test_默认选443(self):
        self.assertEqual(start_tunnel.max_funnel_port_pref(), 443)


class TestCallbackBuilding(unittest.TestCase):
    def test_有token时拼上查询参数(self):
        url = "https://host.tailnet.ts.net"
        self.assertEqual(
            start_tunnel.make_callback(url, "abc"),
            "https://host.tailnet.ts.net/hook?token=abc",
        )

    def test_没token时不带问号(self):
        url = "https://host.tailnet.ts.net"
        self.assertEqual(start_tunnel.make_callback(url, ""), "https://host.tailnet.ts.net/hook")


class TestStableUrlMessage(unittest.TestCase):
    """Funnel 是固定地址，说"会变"就是误导。"""

    def test_稳定模式不提会变(self):
        out = _capture(
            start_tunnel.print_callback_block,
            "https://h.t.ts.net/hook?token=x",
            stable=True,
        )
        self.assertNotIn("每次重启电脑都会变", out)
        self.assertNotIn("变了以后要回 FeedWe 后台改一次", out)

    def test_稳定模式明确说是固定的(self):
        out = _capture(
            start_tunnel.print_callback_block,
            "https://h.t.ts.net/hook?token=x",
            stable=True,
        )
        self.assertIn("固定", out)
        self.assertIn("只需要在 FeedWe 后台填一次", out)

    def test_临时模式仍然警告会变(self):
        out = _capture(
            start_tunnel.print_callback_block,
            "https://a-b-c.trycloudflare.com/hook?token=x",
            stable=False,
        )
        self.assertIn("每次重启电脑都会变", out)

    def test_临时模式指向funnel出路(self):
        out = _capture(
            start_tunnel.print_callback_block,
            "https://a-b-c.trycloudflare.com/hook?token=x",
            stable=False,
        )
        self.assertIn("--mode funnel", out)

    def test_两种模式都会打印地址本身(self):
        for stable in (True, False):
            out = _capture(
                start_tunnel.print_callback_block,
                "https://example.test/hook?token=x",
                stable=stable,
            )
            self.assertIn("https://example.test/hook?token=x", out)


class TestTailscaleDnsName(unittest.TestCase):
    """从 tailscale status --json 的 Self.DNSName 取域名。"""

    def test_去掉末尾的点并补https(self):
        payload = '{"Self": {"DNSName": "mybox.tail1a2b.ts.net."}}'
        orig = start_tunnel.run
        start_tunnel.run = lambda cmd, timeout=60: (0, payload)
        try:
            url, err = start_tunnel.tailscale_dns_name("tailscale")
        finally:
            start_tunnel.run = orig
        self.assertIsNone(err)
        self.assertEqual(url, "https://mybox.tail1a2b.ts.net")

    def test_没登录时给错误说明(self):
        orig = start_tunnel.run
        start_tunnel.run = lambda cmd, timeout=60: (0, '{"Self": {}}')
        try:
            url, err = start_tunnel.tailscale_dns_name("tailscale")
        finally:
            start_tunnel.run = orig
        self.assertIsNone(url)
        self.assertIn("MagicDNS", err)

    def test_命令失败时给错误说明(self):
        orig = start_tunnel.run
        start_tunnel.run = lambda cmd, timeout=60: (1, "boom")
        try:
            url, err = start_tunnel.tailscale_dns_name("tailscale")
        finally:
            start_tunnel.run = orig
        self.assertIsNone(url)
        self.assertIn("boom", err)


class TestNoTokenWarning(unittest.TestCase):
    def test_有token时不输出警告(self):
        self.assertEqual(_capture(start_tunnel.warn_if_no_token, "x"), "")

    def test_没token时提示去生成(self):
        out = _capture(start_tunnel.warn_if_no_token, "")
        self.assertIn("--gen-token", out)


class TestArgvWiring(unittest.TestCase):
    """--mode funnel 必须真的走 funnel 分支。"""

    def test_mode_funnel分发到funnel(self):
        called = {}

        def fake_funnel(cfg, port, token, print_url_only=False):
            called["funnel"] = True
            return 0

        def fake_cf(cfg, port, token, print_url_only=False):
            called["cloudflare"] = True
            return 0

        o1, o2 = start_tunnel.main_funnel, start_tunnel.main_cloudflare
        start_tunnel.main_funnel = fake_funnel
        start_tunnel.main_cloudflare = fake_cf
        try:
            start_tunnel.main(["--mode", "funnel"])
        finally:
            start_tunnel.main_funnel, start_tunnel.main_cloudflare = o1, o2
        self.assertTrue(called.get("funnel"))
        self.assertNotIn("cloudflare", called)

    def test_默认走cloudflare(self):
        called = {}

        def fake_funnel(cfg, port, token, print_url_only=False):
            called["funnel"] = True
            return 0

        def fake_cf(cfg, port, token, print_url_only=False):
            called["cloudflare"] = True
            return 0

        o1, o2 = start_tunnel.main_funnel, start_tunnel.main_cloudflare
        start_tunnel.main_funnel = fake_funnel
        start_tunnel.main_cloudflare = fake_cf
        try:
            start_tunnel.main([])
        finally:
            start_tunnel.main_funnel, start_tunnel.main_cloudflare = o1, o2
        self.assertTrue(called.get("cloudflare"))
        self.assertNotIn("funnel", called)


class TestNoHardcodedRealHost(unittest.TestCase):
    """回归：文档/代码里不应出现用户真实的 tailnet 名或 token。"""

    def test_测试文件本身不含长密钥字面量(self):
        import re

        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            text = f.read()
        # 24 位以上的连续字母数字（排除 ts.net 这类域名片段）
        bad = re.findall(r"['\"][A-Za-z0-9_-]{24,}['\"]", text)
        self.assertEqual(bad, [], f"疑似真实密钥：{bad}")


if __name__ == "__main__":
    unittest.main()
