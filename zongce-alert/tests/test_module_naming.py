"""模块命名约束：不能用标准库已占用的名字。

背景（2026-11-17）：
项目里原本有 `src/parser.py`。`parser` 在 Python 3.8/3.9 是标准库模块
（CPython 旧解析器），3.10 才移除。项目声明支持 3.8+，所以：

- 在 3.8/3.9 上，即便 `sys.path.insert(0, "src")` 能让自定义模块优先命中，
  一旦某处导入早于 path 注入（比如第三方包内部、或打包后），就会静默拿到标准库那个，
  报错信息还很难懂
- 更实际的问题是可读性：任何人看到 `import parser` 都会以为是标准库

改成 `article_parser` 后语义也更准确——它解析的是「文章」，不是「源码语法」。
"""
import ast
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")


class TestModuleNaming(unittest.TestCase):
    def test_src下没有叫parser的模块(self):
        self.assertFalse(
            os.path.exists(os.path.join(SRC, "parser.py")),
            "src/parser.py 与 Python 3.8/3.9 标准库同名，应改名为 article_parser.py",
        )

    def test_存在article_parser模块(self):
        self.assertTrue(
            os.path.exists(os.path.join(SRC, "article_parser.py")),
            "缺少 article_parser.py",
        )

    def _py_files(self):
        for base in (ROOT, SRC):
            if not os.path.isdir(base):
                continue
            for name in os.listdir(base):
                if name.endswith(".py"):
                    yield os.path.join(base, name)
        tests = os.path.join(ROOT, "tests")
        if os.path.isdir(tests):
            for name in os.listdir(tests):
                if name.endswith(".py"):
                    yield os.path.join(tests, name)

    def test_没有残留的import_parser(self):
        """任何 `import parser` / `from parser import` 都是漏改。"""
        bad = []
        for path in self._py_files():
            with open(path, encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    # 跳过注释行
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if re.search(r"^\s*(import\s+parser\b|from\s+parser\s+import)", line):
                        bad.append("%s:%d" % (os.path.relpath(path, ROOT), lineno))
        self.assertEqual(
            bad,
            [],
            "以下位置还在 import parser，应改为 article_parser：%s" % bad,
        )

    def test_pyproject声明了article_parser模块(self):
        path = os.path.join(ROOT, "pyproject.toml")
        if not os.path.exists(path):
            self.skipTest("没有 pyproject.toml")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        # py-modules 列表里应包含新名字
        m = re.search(r"py-modules\s*=\s*\[([^\]]*)\]", text)
        if not m:
            self.skipTest("pyproject 里没有 py-modules 声明")
        modules = re.findall(r'"([^"]+)"', m.group(1))
        self.assertIn(
            "article_parser",
            modules,
            "pyproject.toml 的 py-modules 应包含 article_parser",
        )
        self.assertNotIn(
            "parser",
            modules,
            "py-modules 里不该再有 parser",
        )


class TestNoStdlibCollision(unittest.TestCase):
    """把「哪些名字不能用」写成可查的规则，防止以后再撞。"""

    # Python 3.8 标准库里存在、且名字容易被业务代码误用的模块
    RESERVED = {
        "parser",
        "types",
        "token",
        "code",
        "codeop",
        "copy",
        "queue",
        "socket",
        "select",
        "signal",
        "string",
        "struct",
        "random",
        "json",
        "email",
        "html",
        "http",
        "logging",
        "unittest",
        "parser",
    }

    def test_src下的模块名不与标准库冲突(self):
        if not os.path.isdir(SRC):
            self.skipTest("没有 src 目录")
        offenders = []
        for name in os.listdir(SRC):
            if not name.endswith(".py"):
                continue
            stem = name[:-3]
            if stem in self.RESERVED:
                offenders.append(name)
        self.assertEqual(
            offenders,
            [],
            "src/ 下的模块名与标准库冲突，换个名字：%s" % offenders,
        )


if __name__ == "__main__":
    unittest.main()
