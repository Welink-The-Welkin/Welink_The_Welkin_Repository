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
        """判断标准是「git 有没有跟踪」，不是「目录存不存在」。

        跑过一次自检就会生成 data/（日志、去重库、原始 payload），
        这是正常现象。真正要防的是它被提交进仓库。
        """
        if not self.is_repo_copy:
            self.skipTest("开发副本，运行时数据存在是预期的")

        data_dir = os.path.join(ROOT, "data")
        if not os.path.exists(data_dir):
            return  # 没跑过，自然没问题

        # 目录存在则必须被 .gitignore 排除，且没有任何文件被跟踪
        import subprocess

        try:
            tracked = subprocess.run(
                ["git", "ls-files", "--", "data/"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            self.skipTest("无法调用 git，跳过")

        if tracked.returncode != 0:
            self.skipTest("不在 git 仓库内，跳过")

        self.assertEqual(
            tracked.stdout.strip(),
            "",
            "data/ 下的运行时数据被 git 跟踪了，应从索引中移除：%s"
            % tracked.stdout.strip()[:200],
        )

    def test_data目录被gitignore覆盖(self):
        """无论副本形态，data/ 都必须在 .gitignore 里。"""
        text = _read(os.path.join(ROOT, ".gitignore"))
        self.assertIn("data/", text, ".gitignore 必须排除 data/")

    def test_gitignore排除敏感项(self):
        """无论哪种副本都必须有这个保护。"""
        text = _read(os.path.join(ROOT, ".gitignore"))
        for must in ("secrets.local.json", "data/"):
            self.assertIn(must, text)


class TestWindowsOnlyDeclared(unittest.TestCase):
    def test_README声明只支持windows(self):
        readme = _read(os.path.join(ROOT, "README.md"))
        self.assertIn("Windows", readme)


class TestNoHardcodedUserPaths(unittest.TestCase):
    """可分发项目不能写死作者本机的绝对路径。

    `C:\\Python\\python.exe` 只在作者机器上成立；别人 clone 后若没有这个目录，
    脚本还得靠 PATH 兜底，等于那行 if exist 永远走 else 分支——
    既没用，又误导读者以为需要装到 C:\\Python。
    """

    # 需要扫描的文本类文件
    SUFFIXES = (".bat", ".py", ".json", ".md", ".yml", ".yaml", ".toml", ".txt")

    def _text_files(self):
        for dirpath, dirnames, filenames in os.walk(ROOT):
            # 跳过 git 与缓存目录
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "data")]
            for name in filenames:
                if name.lower().endswith(self.SUFFIXES):
                    yield os.path.join(dirpath, name)

    def test_批处理不硬编码C盘Python路径(self):
        """只看真正会被执行的行，注释里提到这个路径不算违规。"""
        offenders = []
        for path in self._text_files():
            if not path.lower().endswith(".bat"):
                continue
            for lineno, line in enumerate(_read(path).splitlines(), 1):
                stripped = line.strip()
                # 跳过注释与 echo 说明文字
                if stripped.lower().startswith(("rem ", "rem\t", "::")):
                    continue
                if stripped.lower().startswith("echo"):
                    continue
                if re.search(r"[Cc]:[\\/]Python", stripped):
                    offenders.append("%s:%d" % (os.path.relpath(path, ROOT), lineno))
        self.assertEqual(
            offenders,
            [],
            "以下位置写死了 C:\\Python 路径，换台机器就失效：%s" % offenders,
        )

    def test_源码优先使用当前解释器(self):
        """startup.py 必须首选「与当前解释器同目录」的 pythonw。"""
        text = _read(os.path.join(ROOT, "startup.py"))
        self.assertIn("sys.executable", text, "应基于 sys.executable 推导 pythonw")
        self.assertNotIn(
            r'r"C:\Python\pythonw.exe"',
            text.replace("'", '"'),
            "不应把 C:\\Python 作为首选回退",
        )

    def test_批处理里有解释器探测(self):
        """探测逻辑集中在 _find_python.bat，各脚本通过 call 复用。"""
        probe = os.path.join(ROOT, "_find_python.bat")
        self.assertTrue(os.path.exists(probe), "缺少共享的解释器探测脚本")
        probe_text = _read(probe).lower()
        self.assertIn("where python", probe_text, "应当用 where 探测 PATH 中的 python")
        self.assertIn("py -c", probe_text, "应当尝试 py launcher")

        # 各入口脚本必须引用这个共享片段，而不是各自硬编码
        for name in ("启动.bat", "自检.bat", "查看状态.bat", "安装开机自启.bat"):
            text = _read(os.path.join(ROOT, name))
            self.assertIn(
                "_find_python.bat",
                text,
                "%s 应调用共享的解释器探测，而不是自己写一套" % name,
            )


class TestBatchFileEncoding(unittest.TestCase):
    """Windows 批处理的编码/换行是硬约束，踩过就别再踩。

    两条规则，任一违反都会让脚本在真实双击场景下崩溃：
    1. 换行必须是 CRLF —— 纯 LF 时 cmd 会把整行当一条命令，
       `goto` 标签和续行符全部失效
    2. 若非纯 ASCII，必须先 chcp 65001，否则中文按 GBK 解析成乱码，
       连 `@echo off` 之后的命令都可能被截断
    """

    def _bats(self):
        return sorted(
            os.path.join(ROOT, n) for n in os.listdir(ROOT) if n.lower().endswith(".bat")
        )

    @staticmethod
    def _read_bytes(path):
        with open(path, "rb") as f:
            return f.read()

    def test_存在批处理文件(self):
        self.assertTrue(self._bats(), "一个 .bat 都没有？这项目是给 Windows 用的")

    def test_全部使用CRLF换行(self):
        bad = []
        for path in self._bats():
            raw = self._read_bytes(path)
            crlf = raw.count(b"\r\n")
            bare_lf = raw.count(b"\n") - crlf
            if bare_lf > 0:
                bad.append("%s(裸LF=%d)" % (os.path.basename(path), bare_lf))
        self.assertEqual(bad, [], "以下批处理混入了裸 LF，cmd 会解析错乱：%s" % bad)

    def test_无UTF8_BOM(self):
        """BOM 会让 cmd 把第一行识别成乱码命令。"""
        bad = []
        for path in self._bats():
            if self._read_bytes(path)[:3] == b"\xef\xbb\xbf":
                bad.append(os.path.basename(path))
        self.assertEqual(bad, [], "以下批处理带 UTF-8 BOM：%s" % bad)

    def test_含中文的批处理先切换代码页(self):
        bad = []
        for path in self._bats():
            raw = self._read_bytes(path)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue  # GBK 编码的文件由 Windows 原生解析，不需要 chcp
            has_non_ascii = any(ord(c) > 127 for c in text)
            if has_non_ascii and "chcp 65001" not in text:
                bad.append(os.path.basename(path))
        self.assertEqual(
            bad,
            [],
            "以下批处理含中文却没 chcp 65001，中文会变乱码：%s" % bad,
        )

    def test_探测脚本可被call执行(self):
        """_find_python.bat 用 call 执行时应返回 0 并设置 PY。"""
        import subprocess
        import tempfile

        probe = os.path.join(ROOT, "_find_python.bat")
        if not os.path.exists(probe):
            self.skipTest("探测脚本不存在")
        with tempfile.TemporaryDirectory() as td:
            runner = os.path.join(td, "run.bat")
            with open(runner, "w", encoding="utf-8", newline="\r\n") as f:
                f.write("@echo off\n")
                f.write("chcp 65001 >nul\n")
                f.write('call "%s"\n' % probe)
                f.write("echo RESULT=[%PY%]\n")
                f.write("echo RC=[%errorlevel%]\n")
            r = subprocess.run(
                ["cmd", "/c", runner],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        self.assertIn("RC=[0]", r.stdout, "探测失败：%s" % r.stdout)
        self.assertNotIn("RESULT=[]", r.stdout, "探测成功但没设置 PY")


class TestDocsMatchCode(unittest.TestCase):
    """文档里承诺的行为，代码里必须真有。

    写文档最容易犯的错是「按自己的想象写」，比如把某个日志说成 DEBUG 级，
    实际却是 INFO；或者引用了根本不存在的日志文案。用户照着文档排查就会走空。
    """

    def test_配置文档记录的键都存在于默认配置(self):
        """CONFIG.md 里以 `"键":` 形式出现的名字，必须真能在默认配置里找到。

        只认 JSON 键的写法，避免把取值（如 match_field 的 title_and_summary）误当键。
        """
        sys.path.insert(0, os.path.join(ROOT, "src"))
        import config as cfg_mod  # noqa: E402

        known = set()

        def walk(d):
            for k, v in d.items():
                if not isinstance(k, str) or k.startswith("_") or " " in k:
                    continue
                known.add(k)
                if isinstance(v, dict):
                    walk(v)

        walk(cfg_mod.DEFAULT_CONFIG)

        doc = _read(os.path.join(DOCS, "CONFIG.md"))
        # 匹配 "key": 这种 JSON 键写法（允许前后有空格）
        mentioned = set(re.findall(r'"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:', doc))
        suspicious = {m for m in mentioned if m not in known}
        self.assertEqual(
            suspicious,
            set(),
            "CONFIG.md 以键的形式提到了代码里并不存在的配置项：%s" % sorted(suspicious),
        )

    def test_配置文档引用的日志文案真实存在(self):
        """文档里整段引用的日志文案，应在源码里找得到。"""
        doc = _read(os.path.join(DOCS, "CONFIG.md"))

        sources = ""
        for base in (ROOT, os.path.join(ROOT, "src")):
            if not os.path.isdir(base):
                continue
            for name in os.listdir(base):
                if name.endswith(".py"):
                    sources += _read(os.path.join(base, name))

        # 只挑「中文 + 冒号 + 占位符」这种明确的日志引用，且长度够长，
        # 避免把表格里的普通说明文字也当成日志
        quoted = re.findall(r"`([\u4e00-\u9fa5]{2,}，[^`]{0,20}：<[^`]+>)`", doc)
        for q in set(quoted):
            core = q.split("：")[0]
            self.assertIn(
                core,
                sources,
                "CONFIG.md 引用了不存在的日志文案：`%s`" % q,
            )


if __name__ == "__main__":
    unittest.main()
