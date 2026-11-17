"""安装 / 卸载开机自启。

为什么用 Python 而不是 .bat + PowerShell：
本机的安全策略拦截了 PowerShell 的 COM 实例化（WScript.Shell），
而 pywin32 走的是进程内 COM 调用，不受该策略影响。

快捷方式目标直接指向 pythonw.exe，参数为 run.py --tray：
pythonw 是 GUI 版解释器，天然没有控制台窗口，开机不会闪任何窗口。
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def startup_dir() -> str:
    return os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )


def lnk_path() -> str:
    return os.path.join(startup_dir(), "综测提醒.lnk")


def find_pythonw() -> str:
    """找 pythonw.exe。

    顺序：当前解释器同目录 → 探测到的其他解释器 → PATH 中的 pythonw。
    不再硬编码 C:\\Python——那是作者本机路径，对其他人无意义。
    """
    # 1. 与当前解释器同目录（最可信）
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.exists(candidate):
        return candidate

    # 2. 交给统一的解释器探测，再由 python 推导 pythonw
    try:
        from pyenv import find_python, find_pythonw as derive_pythonw

        py, _ = find_python(require_tkinter=False)
        if py:
            pw = derive_pythonw(py)
            if os.path.exists(pw):
                return pw
    except Exception:
        pass

    # 3. 退回 PATH 中的 pythonw
    return "pythonw.exe"


def create_shortcut(target: str, args: str, workdir: str, lnk: str) -> None:
    """创建 .lnk 快捷方式。"""
    import pythoncom
    from win32com.client import Dispatch

    pythoncom.CoInitialize()
    shell = None
    shortcut = None
    try:
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(lnk)
        shortcut.TargetPath = target
        shortcut.Arguments = args
        shortcut.WorkingDirectory = workdir
        shortcut.Description = "公众号综测加分活动提醒（静默运行）"
        # 7 = 最小化窗口
        shortcut.WindowStyle = 7
        shortcut.Save()
    finally:
        # 必须在 CoUninitialize 之前显式释放 COM 对象，
        # 否则解释器退出时会报 "Win32 exception releasing IUnknown"
        shortcut = None
        shell = None
        import gc

        gc.collect()
        pythoncom.CoUninitialize()


def install() -> int:
    target = find_pythonw()
    args = f'"{os.path.join(BASE_DIR, "run.py")}" --tray'
    lnk = lnk_path()

    os.makedirs(startup_dir(), exist_ok=True)

    # 已存在的先删掉，否则可能因占用无法覆盖
    if os.path.exists(lnk):
        try:
            os.remove(lnk)
        except OSError as e:
            print(f"无法删除旧快捷方式：{e}")

    try:
        create_shortcut(target, args, BASE_DIR, lnk)
    except Exception as e:
        print(f"[失败] 创建快捷方式出错：{e}")
        return 1

    if not os.path.exists(lnk):
        print("[失败] 快捷方式未生成")
        return 1

    print("[成功] 已安装静默开机自启")
    print(f"  快捷方式：{lnk}")
    print(f"  启动程序：{target}")
    print(f"  参数：{args}")
    print()
    print("下次开机：右下角出现红色对勾图标，不会有任何窗口弹出。")
    return 0


def uninstall() -> int:
    lnk = lnk_path()
    if not os.path.exists(lnk):
        print("[提示] 没有找到开机自启项，可能本来就没安装。")
        return 0
    try:
        os.remove(lnk)
    except OSError as e:
        print(f"[失败] 删除失败：{e}")
        return 1
    print("[完成] 已取消开机自启")
    return 0


def show_status() -> int:
    lnk = lnk_path()
    if not os.path.exists(lnk):
        print("当前状态：未安装开机自启")
        return 0
    print("当前状态：已安装开机自启")
    print(f"  快捷方式：{lnk}")
    try:
        import gc

        import pythoncom
        from win32com.client import Dispatch

        pythoncom.CoInitialize()
        s = None
        try:
            s = Dispatch("WScript.Shell").CreateShortcut(lnk)
            print(f"  目标：{s.TargetPath}")
            print(f"  参数：{s.Arguments}")
        finally:
            s = None
            gc.collect()
            pythoncom.CoUninitialize()
    except Exception as e:
        print(f"  （无法读取详情：{e}）")
    return 0


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    if action == "install":
        return install()
    if action == "uninstall":
        return uninstall()
    if action == "status":
        return show_status()
    print("用法：python startup.py [install|uninstall|status]")
    return 1


if __name__ == "__main__":
    sys.exit(main())
