"""解释器探测：找到带 tkinter 的 Python，并派生出 python / pythonw 路径。

为什么单独抽出来：
- 五个 .bat 都要启动 Python，各自写一套探测逻辑必然走样
- 写死 C:\\Python 只在作者机器上成立，开源后对别人是误导
- tkinter 缺失是真实故障（弹窗画不出来），必须在启动前就报清楚，
  而不是等到 notify 模块 import 时才崩

探测顺序（先可信、再兜底、最后报错）：
1. 当前正在运行的解释器 —— 用户既然能用它跑这个脚本，它大概率是对的
2. PATH 里的 python（用 shutil.which，Windows 上会正确解析 .exe）
3. 常见安装位置（py launcher 能问出来就更准）
"""
import os
import shutil
import subprocess
import sys


def _has_tkinter(python_exe: str) -> bool:
    """实际执行一次 import tkinter，比猜路径可靠。"""
    try:
        # 用 -c 而不是 -m，避免受 sys.path 影响；超时防卡死
        r = subprocess.run(
            [python_exe, "-c", "import tkinter"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _candidates():
    """按可信度从高到低给出候选解释器。"""
    seen = set()

    def push(p):
        if not p:
            return
        p = os.path.abspath(p)
        if p.lower() in seen:
            return
        seen.add(p.lower())
        return p

    # 1. 当前解释器
    cur = sys.executable
    if cur and cur.lower().endswith(("python.exe", "pythonw.exe")):
        # pythonw 无法执行 -c 并拿到输出，统一换成 python
        d = os.path.dirname(cur)
        for name in ("python.exe", "python3.exe"):
            p = push(os.path.join(d, name))
            if p:
                yield p

    # 2. PATH
    for name in ("python", "python3"):
        p = push(shutil.which(name))
        if p:
            yield p

    # 3. py launcher 报告的路径
    try:
        r = subprocess.run(
            ["py", "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            p = push(r.stdout.strip())
            if p:
                yield p
    except (OSError, subprocess.SubprocessError):
        pass


def find_python(require_tkinter: bool = True):
    """返回 (python_exe, has_tkinter)。找不到返回 (None, False)。"""
    first_found = None
    for p in _candidates():
        if first_found is None:
            first_found = p
        if not require_tkinter or _has_tkinter(p):
            return p, True
    return first_found, False


def find_pythonw(python_exe: str):
    """由 python.exe 推出同目录的 pythonw.exe；不存在就返回原 exe。

    pythonw 是 GUI 子系统解释器，天然无控制台窗口，开机启动不会闪黑框。
    如果机器上确实没有 pythonw（少见），退回 python.exe 也能跑，
    只是会短暂出现一个终端窗口。
    """
    if not python_exe:
        return python_exe
    d = os.path.dirname(python_exe)
    for name in ("pythonw.exe", "pythonw"):
        cand = os.path.join(d, name)
        if os.path.exists(cand):
            return cand
    return python_exe


def main() -> int:
    py, ok = find_python(require_tkinter=False)
    if not py:
        print("NOTFOUND")
        return 1
    print(py)
    return 0


if __name__ == "__main__":
    sys.exit(main())
