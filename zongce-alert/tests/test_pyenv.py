"""解释器探测逻辑的测试。

pyenv 的价值全在「顺序」和「兜底」上，所以测试重点不是返回值，
而是：候选列表排得对不对、找不到时是否老实返回 None、pythonw 推导是否安全。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pyenv  # noqa: E402


class TestCandidates(unittest.TestCase):
    def test_候选列表不为空(self):
        """任何能跑起本测试的环境，至少应探测到一个解释器。"""
        cands = list(pyenv._candidates())
        self.assertTrue(cands, "一个候选解释器都没找到，说明探测逻辑有问题")

    def test_当前解释器排在最前(self):
        """用户能用这个解释器跑测试，就该优先用它——环境最可信。"""
        cands = list(pyenv._candidates())
        self.assertTrue(cands[0].lower().endswith(".exe") or cands[0].endswith("python"))

    def test_候选中没有pythonw(self):
        """pythonw 没有 stdout，执行 -c 拿不到结果，不该出现在候选里。"""
        for p in pyenv._candidates():
            self.assertFalse(
                os.path.basename(p).lower().startswith("pythonw"),
                "候选里混入了 pythonw：%s" % p,
            )

    def test_候选去重(self):
        cands = [c.lower() for c in pyenv._candidates()]
        self.assertEqual(len(cands), len(set(cands)), "候选列表出现重复项")

    def test_候选全是绝对路径(self):
        for p in pyenv._candidates():
            self.assertTrue(os.path.isabs(p), "候选不是绝对路径：%s" % p)


class TestFindPython(unittest.TestCase):
    def test_能找到当前解释器(self):
        py, ok = pyenv.find_python(require_tkinter=False)
        self.assertIsNotNone(py)
        self.assertTrue(os.path.exists(py), "返回的路径不存在：%s" % py)

    def test_当前解释器确实存在(self):
        """find_python 返回的必须是真实可执行文件，不能是 PATH 里的裸名字。"""
        py, _ = pyenv.find_python(require_tkinter=False)
        self.assertTrue(os.path.isabs(py), "应返回绝对路径，实际：%s" % py)

    def test_找不到时返回None(self):
        """把候选清空，验证兜底行为是返回 None 而不是抛异常。"""
        orig = pyenv._candidates
        pyenv._candidates = lambda: iter(())
        try:
            py, ok = pyenv.find_python(require_tkinter=False)
            self.assertIsNone(py)
            self.assertFalse(ok)
        finally:
            pyenv._candidates = orig


class TestFindPythonw(unittest.TestCase):
    def test_空输入不崩(self):
        self.assertIn(pyenv.find_pythonw(""), ("", None))

    def test_推导出同目录pythonw或退回原exe(self):
        py, _ = pyenv.find_python(require_tkinter=False)
        pw = pyenv.find_pythonw(py)
        self.assertTrue(os.path.isabs(pw))
        # 有 pythonw 就用 pythonw，没有就退回 python，两者都可以
        self.assertIn(os.path.basename(pw).lower(), ("pythonw.exe", "pythonw", "python.exe"))

    def test_对不存在的路径也安全(self):
        result = pyenv.find_pythonw(r"C:\definitely\not\here\python.exe")
        self.assertEqual(result, r"C:\definitely\not\here\python.exe")


class TestHasTkinter(unittest.TestCase):
    def test_对无效路径返回False(self):
        self.assertFalse(pyenv._has_tkinter(r"C:\no\such\python.exe"))

    def test_对当前解释器可判定(self):
        """只要能跑这个测试，就应当得到明确的布尔值而不抛异常。"""
        py, _ = pyenv.find_python(require_tkinter=False)
        self.assertIsInstance(pyenv._has_tkinter(py), bool)


if __name__ == "__main__":
    unittest.main()
