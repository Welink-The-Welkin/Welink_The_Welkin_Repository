"""配置加载测试。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import load_config, DEFAULT_KEYWORDS  # noqa: E402


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "config.json")

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)
        os.rmdir(self.tmpdir)

    def write(self, obj):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def test_文件不存在时用默认配置(self):
        cfg = load_config(os.path.join(self.tmpdir, "nope.json"))
        self.assertEqual(cfg["keywords"], DEFAULT_KEYWORDS)
        self.assertEqual(cfg["port"], 8765)

    def test_用户配置覆盖默认值(self):
        self.write({"keywords": ["综测"], "port": 9000})
        cfg = load_config(self.path)
        self.assertEqual(cfg["keywords"], ["综测"])
        self.assertEqual(cfg["port"], 9000)

    def test_部分配置时其余走默认(self):
        self.write({"keywords": ["加分"]})
        cfg = load_config(self.path)
        self.assertEqual(cfg["keywords"], ["加分"])
        self.assertEqual(cfg["port"], 8765)

    def test_损坏的JSON回退默认值(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{broken")
        cfg = load_config(self.path)
        self.assertEqual(cfg["keywords"], DEFAULT_KEYWORDS)

    def test_默认关键词含综测(self):
        self.assertIn("综测", DEFAULT_KEYWORDS)

    def test_邮件配置结构存在(self):
        cfg = load_config(self.path)
        self.assertIn("email", cfg)
        self.assertIn("enabled", cfg["email"])

    def test_环境变量可覆盖token(self):
        self.write({"token": "fromfile"})
        old = os.environ.get("ZONGCE_TOKEN")
        os.environ["ZONGCE_TOKEN"] = "fromenv"
        try:
            self.assertEqual(load_config(self.path)["token"], "fromenv")
        finally:
            if old is None:
                del os.environ["ZONGCE_TOKEN"]
            else:
                os.environ["ZONGCE_TOKEN"] = old


if __name__ == "__main__":
    unittest.main()
