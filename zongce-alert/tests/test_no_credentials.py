"""仓库级卫生：凭据不能出现在任何被跟踪的文件里。

背景（2026-11-17 真实事故）：
`tests/test_startup_failure.py` 里有个测掩码的用例，当时图省事直接拿
**用户的真实 token** 当样本（一个 32 位的高熵字符串）。

这个文件随 PR 推到了 GitHub。更糟的是它触发了同仓库 Wanderer 项目的
隐私扫描测试（那个测试会遍历整个仓库的所有被跟踪文件），导致
`Wanderer Game Tests` 变红——一个和改动毫无关系的工作流。

教训有三条：
1. 测试样本必须是明显的假值，不能拿真实凭据图方便
2. 「看起来像密钥」的长串（>=24 位字母数字）本身就会被各类扫描器拦下，
   即使它是编的。所以样本要短，或者在明显的占位上下文里
3. **连检测脚本自己也不能写明文**。本文件用 sha256 前 16 位比对已知泄漏值，
   既精准报警，又不让检测器变成新的泄漏点
"""
import hashlib
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def _looks_like_word(value):
    """判断一个长串是不是"可读的标识符/单词组合"，而不是随机凭据。

    规则：只有字母（含大小写）和下划线，且能按 CamelCase 或下划线
    切出多个全字母片段。长类名、长函数名会通过；含数字混排的随机串不会。
    """
    if not re.fullmatch(r"[A-Za-z_]+", value):
        return False
    parts = [p for p in re.split(r"_|(?<=[a-z])(?=[A-Z])", value) if p]
    return len(parts) >= 2 and all(len(p) >= 2 for p in parts)


def _is_local_secret_file(name):
    """本地凭据文件及其任何副本（备份、时间戳副本）都不该被扫描。

    这些文件本来就装着真 token，扫它们只会制造噪音。
    它们靠 .gitignore 保证不提交——这一点由 TestGitignoreCoversBackups 守。
    """
    lower = name.lower()
    if lower in (".env", "启动失败.txt"):
        return True
    if lower.startswith(".env."):
        return True
    # secrets.local.json / secrets.local.json.bak-222718 / secrets.xxx.json
    # 注意备份名里 .json 在中间，所以用 startswith 判断，不能看后缀。
    # 但模板 secrets.example.json 要保留，它是给用户看的。
    if lower.startswith("secrets") and ".json" in lower:
        return "example" not in lower
    return False


def _iter_text_files():
    """遍历项目内所有**可能被提交**的文本文件。

    跳过运行时产物，以及本地凭据文件本身——`secrets.local.json` 里当然有真 token，
    那正是它的用途。它受 .gitignore 保护，不会被提交。
    """
    skip_dirs = {".git", "__pycache__", "data", "build", "dist", ".pytest_cache"}
    skip_suffix = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".db", ".exe", ".zip"}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            if _is_local_secret_file(name):
                continue
            if os.path.splitext(name)[1].lower() in skip_suffix:
                continue
            yield os.path.join(dirpath, name)


class TestNoCredentialInTree(unittest.TestCase):
    # 历史上真实出现过的泄漏值。
    # 这里**不能写明文**——否则检测脚本自己就成了新的泄漏点。
    # 存 sha256 前 16 位：足够唯一，且无法反推出原值。
    KNOWN_LEAKED_SHA16 = {
        # 原值：真实 webhook token（32 位）
        "2b38f8f5d06fdc1b",
        # 原值：QQ 邮箱 SMTP 授权码（16 位）
        "58336bdc0a74eb62",
        # 原值：早期版本的弱 token
        "2889b9fbcffecfe4",
    }

    @staticmethod
    def _sha16(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def test_已知泄漏值不再出现(self):
        """按「候选串的 sha16 是否命中黑名单」判断，全程不出现明文。"""
        # 从每个文本文件里抽出所有 >=12 位的字母数字串，逐个比对哈希
        candidate = re.compile(r"[A-Za-z0-9_\-]{12,}")
        hits = []
        for path in _iter_text_files():
            rel = os.path.relpath(path, ROOT)
            if rel.replace("\\", "/").endswith("tests/test_no_credentials.py"):
                continue
            text = _read(path)
            for m in candidate.finditer(text):
                if self._sha16(m.group(0)) in self.KNOWN_LEAKED_SHA16:
                    hits.append(rel)
                    break
        self.assertEqual(
            sorted(set(hits)),
            [],
            "以下文件含有已知泄漏的真实凭据：%s" % sorted(set(hits)),
        )

    def test_黑名单本身不含明文(self):
        """守住检测脚本自己：源文件里不许出现长的高熵字面量。

        不能直接写「不许出现某个明文」——那样测试本身就是那串明文的载体。
        改成结构性检查：本文件里除了 sha16 常量、正则和路径，不该有
        >=24 位的纯字母数字串（那才是凭据的样子）。
        """
        me = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_no_credentials.py")
        text = _read(me)

        # 允许的形式：sha16 常量（16 位十六进制）、正则片段、普通单词
        long_token = re.compile(r"[A-Za-z0-9_\-]{24,}")
        offenders = []
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            # 跳过注释和正则定义行
            if stripped.startswith("#") or "re.compile" in line or r"[A-Za-z0-9" in line:
                continue
            for m in long_token.finditer(line):
                value = m.group(0)
                # 合法的 Python 标识符（类名/函数名/变量名）不是凭据。
                # CamelCase 或 snake_case 的长名字很常见，
                # 而真密码不会是 TestXxxYyy 这种可读词组合。
                if value.isidentifier() and _looks_like_word(value):
                    continue
                # sha16 常量是 16 位，不会命中；这里命中的才是可疑的长串
                if value.isalnum() and len(set(value)) > 3:
                    offenders.append("第%d行: %s..." % (lineno, value[:8]))
        self.assertEqual(
            offenders,
            [],
            "检测脚本里出现了长的高熵字面量，改用哈希比对：%s" % offenders,
        )

    def test_没有形如真实密钥的字面量(self):
        """长的高熵字符串若出现在 `token =` / `password =` 右侧，很可能是真凭据。

        这条会同时放过明显的占位符（your-token-here 之类）。
        """
        pattern = re.compile(
            r"""(?:token|password|secret|api[_-]?key)["']?\s*[:=]\s*["']([A-Za-z0-9_\-+/=]{24,})["']""",
            re.IGNORECASE,
        )
        allowed = {
            "your-token-here",
            "your_token_here",
            "change-me-please",
            "example-token-value-here",
        }
        hits = []
        for path in _iter_text_files():
            rel = os.path.relpath(path, ROOT)
            if rel.replace("\\", "/").endswith(("tests/test_no_credentials.py", "secrets.example.json")):
                continue
            for m in pattern.finditer(_read(path)):
                value = m.group(1)
                if value.lower() in allowed:
                    continue
                # 全同字符或明显递增序列视为占位
                if len(set(value)) <= 3:
                    continue
                hits.append("%s -> %s..." % (rel, value[:8]))
        self.assertEqual(
            hits,
            [],
            "以下位置疑似硬编码了密钥（请改成短占位符）：%s" % hits,
        )

    def test_测试里的样例凭据足够短(self):
        """专门盯 tests/：这里最容易被塞进真实值当样本。"""
        tests_dir = os.path.join(ROOT, "tests")
        if not os.path.isdir(tests_dir):
            self.skipTest("没有 tests 目录")
        pattern = re.compile(
            r"""(?:token|password)\s*=\s*["']([A-Za-z0-9_\-+/=]{20,})["']"""
        )
        hits = []
        for name in os.listdir(tests_dir):
            if not name.endswith(".py") or name == "test_no_credentials.py":
                continue
            path = os.path.join(tests_dir, name)
            for m in pattern.finditer(_read(path)):
                hits.append("%s -> %s" % (name, m.group(1)[:10]))
        self.assertEqual(
            hits,
            [],
            "测试里的样例凭据不该这么长，容易被隐私扫描误认为真密钥：%s" % hits,
        )


class TestGitignoreCoversBackups(unittest.TestCase):
    """回归：.gitignore 曾只写 secrets.local.json，拦不住轮换时的备份副本。

    `python run.py --gen-token` 之前手工备份会产生一份带时间戳的
    `secrets.local.json` 副本，里面是**旧 token 明文**。
    原来的规则精确匹配文件名，这类备份直接漏网，
    一次 `git add -A` 就把旧凭据又提交上去了。
    """

    def _gitignore(self):
        p = os.path.join(ROOT, ".gitignore")
        if not os.path.exists(p):
            self.skipTest("没有 .gitignore")
        return _read(p)

    def test_备份副本被忽略(self):
        lines = [l.strip() for l in self._gitignore().splitlines()]
        covered = any(
            l
            for l in lines
            if l in ("secrets.local.json.*", "secrets*.json", "*.json.bak*")
        )
        self.assertTrue(
            covered,
            "需要在 .gitignore 里用通配符覆盖 secrets.local.json 的备份副本",
        )

    def test_模板文件不被忽略(self):
        text = self._gitignore()
        self.assertIn(
            "!secrets.example.json",
            text,
            "secrets.example.json 是模板，必须能被提交，需要显式反忽略",
        )

    def test_环境变量文件被忽略(self):
        lines = [l.strip() for l in self._gitignore().splitlines()]
        self.assertTrue(
            any(l in (".env", ".env.*") for l in lines),
            ".env 及其变体（.env.local 等）都含凭据，必须忽略",
        )


if __name__ == "__main__":
    unittest.main()
