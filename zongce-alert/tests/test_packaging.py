"""项目包装（开源准备）的回归测试。

这些测试不关心业务逻辑，只守卫"项目作为一个可分发开源件是否完整"：
许可证、依赖声明、文档链接、CI 配置、以及定位文案。

先写测试再补文件——每个失败都对应一个确实缺失的东西。
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
REPO_ROOT = os.path.dirname(ROOT)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _exists(name):
    return os.path.exists(os.path.join(ROOT, name))


class TestLicense(unittest.TestCase):
    def test_LICENSE文件存在(self):
        self.assertTrue(_exists("LICENSE"), "缺少 LICENSE，别人无法合法使用")

    def test_是MIT许可证(self):
        text = _read(os.path.join(ROOT, "LICENSE"))
        # MIT 的三个标志性短语，缺一不可
        self.assertIn("MIT License", text)
        self.assertIn("Permission is hereby granted, free of charge", text)
        self.assertIn("THE SOFTWARE IS PROVIDED \"AS IS\"", text)

    def test_有版权行和年份(self):
        text = _read(os.path.join(ROOT, "LICENSE"))
        self.assertRegex(text, r"Copyright \(c\) \d{4}")


class TestPyProject(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(ROOT, "pyproject.toml")
        self.assertTrue(os.path.exists(self.path), "缺少 pyproject.toml")

    def test_声明了requires_python(self):
        text = _read(self.path)
        self.assertIn("requires-python", text)

    def test_版本下限与代码实际需求匹配(self):
        """代码用了 threading.excepthook（3.8+），下限不能低于 3.8。"""
        text = _read(self.path)
        m = re.search(r'requires-python\s*=\s*"[><=~ ]*(\d+)\.(\d+)', text)
        self.assertIsNotNone(m, "requires-python 格式无法解析")
        major, minor = int(m.group(1)), int(m.group(2))
        self.assertGreaterEqual(
            (major, minor), (3, 8),
            "代码依赖 threading.excepthook（3.8 引入），下限过低会误导用户",
        )

    def test_有build_system否则pip安装失败(self):
        text = _read(self.path)
        self.assertIn("[build-system]", text)

    def test_托盘依赖标为可选(self):
        """pystray/Pillow 缺失时代码会优雅降级，所以不该是硬依赖。"""
        text = _read(self.path)
        self.assertIn("optional-dependencies", text)
        self.assertIn("pystray", text)

    def test_核心依赖为空(self):
        """主程序只用标准库，硬依赖应为空列表。"""
        text = _read(self.path)
        m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).strip(), "")


class TestTestsPackage(unittest.TestCase):
    def test_tests有init文件(self):
        self.assertTrue(
            os.path.exists(os.path.join(ROOT, "tests", "__init__.py")),
            "缺少 tests/__init__.py，从项目外无法 discover",
        )


class TestDocsExist(unittest.TestCase):
    """README 里链接到的每个 docs 文件都必须真实存在。"""

    REQUIRED = [
        "QUICKSTART.md",
        "CONFIG.md",
        "TROUBLESHOOTING.md",
        "PROVIDERS.md",
        "SECURITY.md",
    ]

    def test_必需的文档都在(self):
        for name in self.REQUIRED:
            path = os.path.join(DOCS, name)
            self.assertTrue(os.path.exists(path), f"缺少 docs/{name}")

    def test_README引用的docs链接全部可达(self):
        readme = _read(os.path.join(ROOT, "README.md"))
        links = re.findall(r"\]\((docs/[^)#\s]+|\./docs/[^)#\s]+)\)", readme)
        self.assertTrue(links, "README 里没有任何 docs 链接")
        for link in links:
            rel = link.replace("./", "", 1)
            target = os.path.join(ROOT, rel)
            self.assertTrue(
                os.path.exists(target), f"README 链接指向不存在的文件：{link}"
            )

    def test_文档之间没有断链(self):
        for name in self.REQUIRED:
            path = os.path.join(DOCS, name)
            if not os.path.exists(path):
                continue
            text = _read(path)
            # 匹配同目录文档之间的相对链接，如 (CONFIG.md) 或 (./CONFIG.md)
            for link in re.findall(r"\]\((?!https?:|#)([A-Za-z0-9_\-]+\.md)\)", text):
                self.assertTrue(
                    os.path.exists(os.path.join(DOCS, link)),
                    f"{name} 里的链接失效：{link}",
                )


class TestPositioning(unittest.TestCase):
    """回归：README 曾把「上理大学生」写成唯一用途，非上理学生看到就走。"""

    def test_README定位是通用的(self):
        readme = _read(os.path.join(ROOT, "README.md"))
        self.assertIn("任意", readme, "README 应说明适用于任意公众号")

    def test_上理只作为示例出现(self):
        readme = _read(os.path.join(ROOT, "README.md"))
        if "上理" in readme:
            # 出现就必须带"示例/例如/以…为例"这类限定词
            idx = readme.find("上理")
            window = readme[max(0, idx - 120): idx + 120]
            self.assertTrue(
                any(k in window for k in ("示例", "例如", "以", "比如")),
                "「上理」出现时应明确标注为示例，而不是唯一主体",
            )

    def test_标题不含校园专属词(self):
        readme = _read(os.path.join(ROOT, "README.md"))
        first_h1 = re.search(r"^#\s+(.+)$", readme, re.M)
        self.assertIsNotNone(first_h1)
        self.assertNotIn("上理", first_h1.group(1))


class TestReadmeFirstScreen(unittest.TestCase):
    """README 首屏（前 120 行）必须能让人明白：这是什么、长什么样、怎么跑。"""

    def setUp(self):
        self.text = _read(os.path.join(ROOT, "README.md"))
        self.first = "\n".join(self.text.splitlines()[:120])

    def test_首屏有截图引用(self):
        """首屏必须有图——文字再多也不如一张截图有说服力。

        同时接受 Markdown 语法和 HTML <img>，因为后者能控制宽度、居中。
        """
        md = re.search(r"!\[[^\]]*\]\(docs/[^)]+\.(png|jpg|gif|svg)\)", self.first)
        html = re.search(
            r"<img[^>]+src=[\"']docs/[^\"']+\.(png|jpg|gif|svg)[\"']", self.first
        )
        self.assertTrue(md or html, "首屏应有弹窗截图")

    def test_首屏有快速开始(self):
        self.assertIn("快速开始", self.first)

    def test_首屏长度合理(self):
        """门面页应精炼。整个 README 控制在 160 行内。"""
        self.assertLessEqual(
            len(self.text.splitlines()), 160,
            "README 过长，细节应拆到 docs/",
        )


class TestCiConfig(unittest.TestCase):
    """CI 配置位于仓库根 .github/workflows/，只在 monorepo 布局下存在。

    开发副本可能脱离仓库单独存在，此时跳过——CI 由仓库环境负责验证。
    """

    def setUp(self):
        self.path = os.path.join(
            REPO_ROOT, ".github", "workflows", "zongce-alert-tests.yml"
        )
        self.workflow_dir = os.path.join(REPO_ROOT, ".github", "workflows")
        if not os.path.isdir(self.workflow_dir):
            self.skipTest("当前不是 monorepo 布局，跳过 CI 配置测试")

    def test_CI文件存在(self):
        self.assertTrue(os.path.exists(self.path), "缺少 CI 配置")

    def test_YAML语法合法(self):
        try:
            import yaml  # type: ignore
        except ImportError:
            self.skipTest("环境没有 PyYAML，跳过语法校验")
        with open(self.path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # 注意：YAML 1.1 会把裸写的 on 解析成布尔键 True，这是规范行为不是错误。
        # GitHub Actions 能正确处理，测试只要能解析 + 有 jobs 就够了。
        self.assertIn("jobs", data)
        self.assertIsInstance(data["jobs"], dict)

    def test_用windows运行器(self):
        """代码有 winsound/pywin32/tkinter 专属调用，ubuntu 上跑不准。"""
        text = _read(self.path)
        self.assertIn("windows-latest", text)

    def test_工作目录指向本项目(self):
        text = _read(self.path)
        self.assertIn("working-directory: zongce-alert", text)

    def test_有路径过滤只跑受影响项目(self):
        """monorepo 约定：只运行受影响项目的任务。"""
        text = _read(self.path)
        self.assertIn("paths", text)


class TestNoSecretsCommitted(unittest.TestCase):
    """凭据绝不能出现在提交里。

    分两种情况：
    - monorepo 仓库副本（干净检出）：secrets.local.json / data/ 都不该存在
    - 开发副本（日常运行用）：它们存在是正常的，只要 .gitignore 排除了即可
    """

    def setUp(self):
        # 有 docs/ 和 .github 同级说明是仓库副本；否则视为开发副本
        self.is_repo_copy = os.path.isdir(os.path.join(REPO_ROOT, ".github"))

    def test_仓库副本里没有secrets_local(self):
        if not self.is_repo_copy:
            self.skipTest("开发副本，凭据文件存在是预期的")
        self.assertFalse(
            os.path.exists(os.path.join(ROOT, "secrets.local.json")),
            "secrets.local.json 不应出现在待提交目录中",
        )

    def test_仓库副本里没有data目录(self):
        if not self.is_repo_copy:
            self.skipTest("开发副本，运行时数据存在是预期的")
        self.assertFalse(
            os.path.exists(os.path.join(ROOT, "data")),
            "data/ 是运行时数据，不应提交",
        )

    def test_gitignore排除敏感项(self):
        """无论哪种副本都必须有这个保护。"""
        text = _read(os.path.join(ROOT, ".gitignore"))
        for must in ("secrets.local.json", "data/"):
            self.assertIn(must, text)


class TestWindowsOnlyDeclared(unittest.TestCase):
    def test_README声明只支持windows(self):
        readme = _read(os.path.join(ROOT, "README.md"))
        self.assertIn("Windows", readme)


if __name__ == "__main__":
    unittest.main()
