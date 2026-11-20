"""一键查看运行状态。

因为程序平时在后台静默运行（没有窗口），需要有个不打扰的办法确认它还活着。
"""
import json
import os
import subprocess
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_json(url: str, timeout: float = 3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"_error": str(e)}


def is_process_running() -> bool:
    """看有没有 pythonw/python 在跑 run.py。"""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='pythonw.exe'", "get", "ProcessId"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        if out and any(ch.isdigit() for ch in out):
            return True
    except Exception:
        pass

    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "CommandLine"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return "run.py" in (out or "")
    except Exception:
        return False


def main() -> int:
    sys.path.insert(0, os.path.join(BASE_DIR, "src"))
    try:
        from config import load_config, mask_secret

        cfg = load_config(os.path.join(BASE_DIR, "config.json"))
        port = int(cfg.get("port", 8765))
        token = cfg.get("token", "") or ""
    except Exception:
        port = 8765
        token = ""
        mask_secret = None  # type: ignore

    print("=" * 50)
    print("  综测提醒 · 运行状态")
    print("=" * 50)

    # /health 需要 token，本地自检时自动带上
    url = f"http://127.0.0.1:{port}/health"
    if token:
        from urllib.parse import quote

        url += "?token=" + quote(token, safe="")
    health = get_json(url)

    if "_error" in health:
        print()
        print("  ✗ 服务未响应")
        print()
        print(f"  原因：{health['_error']}")
        print()
        print("  可能是：")
        print("   1. 程序没启动 → 双击「启动.bat」")
        print("   2. 程序崩了 → 看 data\\alert.log 最后几行")
        print("   3. 端口被占了 → 看程序目录下的「启动失败.txt」")
        print("   4. token 不对 → 看 secrets.local.json 里的 token")
        print()
        print("=" * 50)
        return 1

    print()
    print("  ✓ 服务运行中")
    print(f"    端口：{port}")
    print(f"    已记录文章：{health.get('seen', '?')} 篇")
    print(f"    邮件通知：{'已开启' if health.get('email_enabled') else '未启用'}")
    if token and mask_secret is not None:
        print(f"    回调鉴权：已启用（{mask_secret(token)}）")
    else:
        print("    回调鉴权：⚠ 未设置——任何人都能触发弹窗")
    kws = health.get("keywords") or []
    if kws:
        print(f"    关键词：{'、'.join(kws)}")

    # 状态输出常用于排障；只说明隧道类型，不在这里打印带凭据的地址。
    from tray import describe_tunnel_steps, read_callback_host

    print()
    print(describe_tunnel_steps(read_callback_host(BASE_DIR)))
    print("  需要复制地址？右键托盘 →「打开回调地址文件」，或在插件文件夹打开 data\\callback-url.txt。")
    print("  完整地址只填到自己的监测服务，不要公开或截图。")

    # 自启状态
    lnk = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
        "综测提醒.lnk",
    )
    print()
    print(f"  开机自启：{'已安装' if os.path.exists(lnk) else '未安装'}")

    print()
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
