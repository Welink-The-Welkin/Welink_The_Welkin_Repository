"""启动失败的可见性测试。

回归：端口被占用时 run() 曾直接抛异常，在 pythonw 下等于静默退出——
用户只看到"开机后托盘没图标"，没有任何线索。
"""
import json
import os
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import server  # noqa: E402
from config import DEFAULT_CONFIG  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestPortConflict(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        self.cfg["notify"]["popup"] = False
        self.cfg["email"]["enabled"] = False
        self.cfg["storage"]["save_raw_payload"] = False
        self.cfg["storage"]["db_path"] = os.path.join(self.tmpdir, "seen.db")
        self.cfg["storage"]["raw_dir"] = os.path.join(self.tmpdir, "raw")
        self.cfg["token"] = "t"
        self.fail_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "启动失败.txt",
        )

    def tearDown(self):
        if os.path.exists(self.fail_file):
            os.remove(self.fail_file)

    def test_端口被占时返回非零退出码而不抛异常(self):
        port = _free_port()
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", port))
        blocker.listen(1)
        self.cfg["port"] = port
        try:
            rc = server.run(self.cfg, self.tmpdir, use_tray=False)
        finally:
            blocker.close()
        self.assertEqual(rc, 2)

    def test_端口被占时留下可读的说明文件(self):
        port = _free_port()
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", port))
        blocker.listen(1)
        self.cfg["port"] = port
        try:
            server.run(self.cfg, self.tmpdir, use_tray=False)
        finally:
            blocker.close()
        self.assertTrue(os.path.exists(self.fail_file), "应生成 启动失败.txt")
        with open(self.fail_file, encoding="utf-8") as f:
            content = f.read()
        self.assertIn(str(port), content)
        self.assertIn("端口", content)


class TestStartupLogMasking(unittest.TestCase):
    """回归：启动日志曾把完整 token 打进 alert.log（并可能被贴到聊天里）。"""

    def test_日志打码函数被用于token(self):
        # 直接验证行为：mask_secret 的输出不会包含原 token 的中段
        from config import mask_secret

        token = "f3S8jN5yaU0S_3OEGf444T-ABZzQKGNf"
        masked = mask_secret(token)
        self.assertNotIn("N5yaU0S", masked)
        self.assertNotEqual(masked, token)


if __name__ == "__main__":
    unittest.main()
