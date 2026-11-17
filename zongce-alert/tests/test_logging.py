"""日志配置测试。

背景：开机静默启动使用 pythonw.exe，它没有控制台，
sys.stdout / sys.stderr 在 pythonw 下为 None。
若 setup_logging 无条件挂 StreamHandler，会在启动瞬间抛异常——
而因为窗口是隐藏的，用户完全看不到报错，只会发现"开机后没反应"。
"""
import io
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import run as run_module  # noqa: E402


class TestSetupLogging(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # 清掉已有 handler，避免测试互相干扰
        root = logging.getLogger()
        self._old_handlers = root.handlers[:]
        self._old_level = root.level
        root.handlers.clear()

    def tearDown(self):
        root = logging.getLogger()
        root.handlers.clear()
        for h in self._old_handlers:
            root.addHandler(h)
        root.setLevel(self._old_level)
        for rootdir, dirs, files in os.walk(self.tmpdir, topdown=False):
            for f in files:
                os.remove(os.path.join(rootdir, f))
            for d in dirs:
                os.rmdir(os.path.join(rootdir, d))
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_无控制台时不崩溃(self):
        """模拟 pythonw：stdout 为 None。"""
        old = sys.stdout
        sys.stdout = None
        try:
            run_module.setup_logging("INFO", self.tmpdir)
            logging.getLogger("t").info("这条应写入文件而不报错")
        finally:
            sys.stdout = old

    def test_有控制台时也正常(self):
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            run_module.setup_logging("INFO", self.tmpdir)
            logging.getLogger("t").info("正常输出")
            self.assertIn("正常输出", sys.stdout.getvalue())
        finally:
            sys.stdout = old

    def test_日志文件一定被创建(self):
        """无论有无控制台，文件日志必须工作——这是排障唯一途径。"""
        old = sys.stdout
        sys.stdout = None
        try:
            run_module.setup_logging("INFO", self.tmpdir)
            logging.getLogger("t").warning("必须落盘")
            for h in logging.getLogger().handlers:
                h.flush()
        finally:
            sys.stdout = old

        log_path = os.path.join(self.tmpdir, "data", "alert.log")
        self.assertTrue(os.path.exists(log_path), "日志文件未创建")
        content = open(log_path, encoding="utf-8").read()
        self.assertIn("必须落盘", content)

    def test_重复调用不会重复挂handler(self):
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            run_module.setup_logging("INFO", self.tmpdir)
            n1 = len(logging.getLogger().handlers)
            run_module.setup_logging("INFO", self.tmpdir)
            n2 = len(logging.getLogger().handlers)
            self.assertEqual(n1, n2, "重复调用导致 handler 堆积，日志会重复输出")
        finally:
            sys.stdout = old


class TestExcepthook(unittest.TestCase):
    """pythonw 下未捕获异常不显示在任何地方，必须落进日志。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._old_hook = sys.excepthook
        self._old_handlers = logging.getLogger().handlers[:]
        logging.getLogger().handlers.clear()

    def tearDown(self):
        sys.excepthook = self._old_hook
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        for h in self._old_handlers:
            root.addHandler(h)
        for rootdir, dirs, files in os.walk(self.tmpdir, topdown=False):
            for f in files:
                os.remove(os.path.join(rootdir, f))
            for d in dirs:
                os.rmdir(os.path.join(rootdir, d))
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_未捕获异常写入日志(self):
        old = sys.stdout
        sys.stdout = None
        try:
            run_module.setup_logging("INFO", self.tmpdir)
            try:
                raise RuntimeError("模拟启动崩溃")
            except RuntimeError:
                sys.excepthook(*sys.exc_info())
        finally:
            sys.stdout = old

        log_path = os.path.join(self.tmpdir, "data", "alert.log")
        for h in logging.getLogger().handlers:
            h.flush()

        self.assertTrue(os.path.exists(log_path))
        with open(log_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("模拟启动崩溃", content)
        self.assertIn("未捕获异常", content)

    def test_KeyboardInterrupt不写critical(self):
        old = sys.stdout
        sys.stdout = None
        try:
            run_module.setup_logging("INFO", self.tmpdir)
            try:
                raise KeyboardInterrupt()
            except KeyboardInterrupt:
                sys.excepthook(*sys.exc_info())
        finally:
            sys.stdout = old

        log_path = os.path.join(self.tmpdir, "data", "alert.log")
        for h in logging.getLogger().handlers:
            h.flush()
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                self.assertNotIn("未捕获异常", f.read())

    def test_线程异常也写入日志(self):
        """托盘/邮件都在子线程里，线程异常不走 sys.excepthook。"""
        import threading

        old = sys.stdout
        sys.stdout = None
        try:
            run_module.setup_logging("INFO", self.tmpdir)

            def boom():
                raise ValueError("线程内崩溃")

            t = threading.Thread(target=boom, name="测试线程")
            t.start()
            t.join()
        finally:
            sys.stdout = old

        log_path = os.path.join(self.tmpdir, "data", "alert.log")
        for h in logging.getLogger().handlers:
            h.flush()
        self.assertTrue(os.path.exists(log_path))
        with open(log_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("线程内崩溃", content)


if __name__ == "__main__":
    unittest.main()
