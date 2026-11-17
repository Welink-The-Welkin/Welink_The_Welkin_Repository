"""安全相关回归测试。

覆盖三处曾经存在的真实风险：
1. /health 无鉴权泄露信息（且能看到回调地址/token）
2. token 出现在启动日志里
3. ?test=1 无来源限制 → 隧道泄露后任何人可让屏幕上弹任意通知
以及配置层：凭据明文写在 config.json / 缺 .gitignore。
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import (  # noqa: E402
    DEFAULT_CONFIG,
    generate_token,
    load_config,
    mask_secret,
    secrets_path_for,
    validate,
)
from server import AlertService, make_handler  # noqa: E402

TOKEN = "unit-test-token-123"


def _base_cfg(tmpdir):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["notify"]["popup"] = False
    cfg["email"]["enabled"] = False
    cfg["storage"]["save_raw_payload"] = False
    cfg["storage"]["db_path"] = os.path.join(tmpdir, "seen.db")
    cfg["storage"]["raw_dir"] = os.path.join(tmpdir, "raw")
    return cfg


class _ServerCase(unittest.TestCase):
    """起一个真实 HTTP 服务，用真实请求验证行为。"""

    allow_remote_test = False

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        cfg = _base_cfg(self.tmpdir)
        cfg["test_mode_allow_remote"] = self.allow_remote_test
        self.service = AlertService(cfg, self.tmpdir)
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(
                self.service,
                TOKEN,
                health_requires_token=True,
                test_mode_allow_remote=self.allow_remote_test,
            ),
        )
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.service.store.close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path, headers=None):
        req = urllib.request.Request(self.url(path), headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def post(self, path, obj, headers=None):
        req = urllib.request.Request(
            self.url(path),
            data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()


class TestHealthRequiresToken(_ServerCase):
    """回归：/health 曾是完全公开的，等于把 token 送人。"""

    def test_无token访问health被拒(self):
        code, _ = self.get("/health")
        self.assertEqual(code, 401)

    def test_错误token访问health被拒(self):
        code, _ = self.get("/health?token=wrong")
        self.assertEqual(code, 401)

    def test_正确token可访问health(self):
        code, body = self.get("/health?token=" + TOKEN)
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_header方式同样可用(self):
        code, _ = self.get("/health", {"X-Token": TOKEN})
        self.assertEqual(code, 200)

    def test_health响应不包含token明文(self):
        _, body = self.get("/health?token=" + TOKEN)
        self.assertNotIn(TOKEN, body)

    def test_health响应不包含回调地址(self):
        _, body = self.get("/health?token=" + TOKEN)
        self.assertNotIn("/hook", body)
        self.assertNotIn("trycloudflare", body)


class TestHookGetIsProbeOnly(_ServerCase):
    """回归：README 曾声称 GET /hook 能验证，实际返回 404。"""

    def test_GET_hook返回200且说明只探测(self):
        code, body = self.get("/hook")
        self.assertEqual(code, 200)
        payload = json.loads(body)
        self.assertIn("note", payload)

    def test_GET_hook不会触发提醒(self):
        before = self.service.store.count()
        self.get("/hook?test=1")
        self.assertEqual(self.service.store.count(), before)


class TestTestModeLocalOnly(_ServerCase):
    """回归：?test=1 曾对任何来源开放，隧道泄露即可远程弹窗。"""

    allow_remote_test = False

    def test_本机可用测试模式(self):
        code, body = self.post(
            f"/hook?token={TOKEN}&test=1",
            {"articles": [{"title": "无关标题", "url": "https://mp.weixin.qq.com/s/T1"}]},
        )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["notified"], 1)

    def test_远程来源用测试模式被拒(self):
        code, body = self.post(
            f"/hook?token={TOKEN}&test=1",
            {"articles": [{"title": "无关标题", "url": "https://mp.weixin.qq.com/s/T2"}]},
            {"CF-Connecting-IP": "8.8.8.8"},
        )
        self.assertEqual(code, 403)
        self.assertEqual(json.loads(body)["error"], "test_mode_local_only")

    def test_远程来源走正常流程仍会按关键词筛选(self):
        code, body = self.post(
            f"/hook?token={TOKEN}",
            {"articles": [{"title": "无关标题", "url": "https://mp.weixin.qq.com/s/T3"}]},
            {"CF-Connecting-IP": "8.8.8.8"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["notified"], 0)
        self.assertEqual(json.loads(body)["skipped_keyword"], 1)


class TestTestModeRemoteAllowed(_ServerCase):
    """显式开启 test_mode_allow_remote 后，远程也能测试。"""

    allow_remote_test = True

    def test_开启后远程可用测试模式(self):
        code, body = self.post(
            f"/hook?token={TOKEN}&test=1",
            {"articles": [{"title": "无关标题", "url": "https://mp.weixin.qq.com/s/T4"}]},
            {"CF-Connecting-IP": "8.8.8.8"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["notified"], 1)


class TestErrorNotLeakingInternals(unittest.TestCase):
    """500 响应不应把内部异常原文（可能含路径）回给调用方。"""

    def test_内部错误返回通用文案(self):
        tmpdir = tempfile.mkdtemp()
        cfg = _base_cfg(tmpdir)
        service = AlertService(cfg, tmpdir)

        class Boom(Exception):
            pass

        def explode(*a, **kw):
            raise Boom("C:\\secret\\internal\\path.db is locked")

        service.handle_payload = explode  # type: ignore
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, TOKEN))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/hook?token={TOKEN}",
                data=b'{"title":"x"}',
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 500)
            body = ctx.exception.read().decode()
            self.assertNotIn("secret", body)
            self.assertNotIn("path.db", body)
            self.assertEqual(json.loads(body)["error"], "internal_error")
        finally:
            httpd.shutdown()
            httpd.server_close()
            service.store.close()


class TestSecretHygiene(unittest.TestCase):
    """凭据必须能和可提交的配置文件分离。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.tmpdir, "config.json")

    def write(self, path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def test_secrets文件路径与config同目录(self):
        self.assertEqual(
            os.path.dirname(secrets_path_for(self.cfg_path)), self.tmpdir
        )

    def test_secrets文件覆盖主配置的token(self):
        self.write(self.cfg_path, {"token": "from-main"})
        self.write(os.path.join(self.tmpdir, "secrets.local.json"), {"token": "from-secret"})
        cfg = load_config(self.cfg_path, use_env=False)
        self.assertEqual(cfg["token"], "from-secret")

    def test_secrets文件可覆盖嵌套的邮件授权码(self):
        self.write(self.cfg_path, {"email": {"enabled": True, "username": "a@qq.com"}})
        self.write(
            os.path.join(self.tmpdir, "secrets.local.json"),
            {"email": {"password": "authcode"}},
        )
        cfg = load_config(self.cfg_path, use_env=False)
        self.assertEqual(cfg["email"]["password"], "authcode")
        # 主配置里的其他字段不能被覆盖掉
        self.assertEqual(cfg["email"]["username"], "a@qq.com")

    def test_主配置为空的token不强转空字符串(self):
        """主配置写空 token 时，若 secrets 有值应取 secrets。"""
        self.write(self.cfg_path, {"token": ""})
        self.write(os.path.join(self.tmpdir, "secrets.local.json"), {"token": "abc"})
        self.assertEqual(load_config(self.cfg_path, use_env=False)["token"], "abc")

    def test_掩码只露首尾(self):
        # 用假值，切勿写真实 token 进测试文件——测试文件是要提交的
        masked = mask_secret("AbCdEfGhIjK")
        self.assertTrue(masked.startswith("Ab"))
        self.assertTrue(masked.endswith("jK"))
        self.assertIn("*", masked)
        self.assertNotIn("CdEfGh", masked)

    def test_短值全遮(self):
        self.assertEqual(mask_secret("abc"), "***")
        self.assertEqual(mask_secret(""), "")

    def test_生成的token足够随机且可用作URL参数(self):
        a, b = generate_token(), generate_token()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 20)
        self.assertRegex(a, r"^[A-Za-z0-9_\-]+$")

    def test_validate_指出空token风险(self):
        problems = validate({"port": 8765, "token": "", "keywords": ["综测"]})
        self.assertTrue(any("token" in p for p in problems))

    def test_validate_指出空关键词(self):
        problems = validate({"port": 8765, "token": "x", "keywords": []})
        self.assertTrue(any("keywords" in p for p in problems))

    def test_validate_指出邮件缺授权码(self):
        problems = validate({
            "port": 8765, "token": "x", "keywords": ["综测"],
            "email": {"enabled": True, "username": "a@qq.com", "password": ""},
        })
        self.assertTrue(any("password" in p for p in problems))

    def test_validate_正常配置无问题(self):
        self.assertEqual(
            validate({"port": 8765, "token": "x", "keywords": ["综测"]}), []
        )


class TestRepoHasGitignore(unittest.TestCase):
    """回归：项目目录曾没有 .gitignore，config.json 里的真实授权码随时可能被提交。"""

    def test_gitignore存在且排除secrets和data(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, ".gitignore")
        self.assertTrue(os.path.exists(path), "项目根目录缺少 .gitignore")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("secrets.local.json", content)
        self.assertIn("data/", content)

    def test_示例密钥文件存在(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertTrue(os.path.exists(os.path.join(root, "secrets.example.json")))

    def test_可提交config里不含明文授权码(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "config.json")
        if not os.path.exists(path):
            self.skipTest("没有 config.json")
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        cfg = json.loads(raw)
        self.assertEqual(cfg.get("token", ""), "", "config.json 不应写明文 token")
        self.assertEqual(
            (cfg.get("email") or {}).get("password", ""),
            "",
            "config.json 不应写明文邮箱授权码",
        )


if __name__ == "__main__":
    unittest.main()
