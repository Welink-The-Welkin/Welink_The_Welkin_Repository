"""启动 Cloudflare 快速隧道，并把可复制的回调地址显眼地打印出来。

为什么要这个脚本：
cloudflared 的快速隧道地址每次重启都会变，需要人工去 FeedWe 后台更新。
这个脚本自动把地址抓出来、拼上 token、存到 data/callback-url.txt，
并直接显示，省得你去翻日志。
"""
import os
import re
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))

from config import load_config  # noqa: E402

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared():
    """找 cloudflared 可执行文件。"""
    for name in ("cloudflared", "cloudflared.exe"):
        try:
            subprocess.run([name, "--version"], capture_output=True, timeout=10, check=True)
            return name
        except Exception:
            continue
    # 常见安装位置
    for p in (
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        r"C:\Program Files\cloudflared\cloudflared.exe",
        os.path.expanduser(r"~\cloudflared.exe"),
    ):
        if os.path.exists(p):
            return p
    return None


def main() -> int:
    cfg = load_config(os.path.join(BASE_DIR, "config.json"))
    port = int(cfg.get("port", 8765))
    token = cfg.get("token", "") or ""

    if not token:
        print("=" * 62)
        print("警告：还没有设置回调 token！")
        print()
        print("没有 token，任何知道隧道地址的人都能往你的程序发消息弹窗。")
        print("先运行：")
        print("  python run.py --gen-token")
        print("然后再回来运行本脚本。")
        print("=" * 62)
        print()

    exe = find_cloudflared()
    if not exe:
        print("=" * 62)
        print("没有找到 cloudflared。请任选一种方式安装，然后重新运行本脚本：")
        print()
        print("  winget install --id Cloudflare.cloudflared")
        print()
        print("或者手动下载：")
        print("  https://github.com/cloudflare/cloudflared/releases/latest")
        print("  下载 cloudflared-windows-amd64.exe，改名 cloudflared.exe 放到本目录")
        print("=" * 62)
        return 1

    print("=" * 62)
    print("正在启动 Cloudflare 快速隧道…（首次可能要 10-20 秒）")
    print("=" * 62)

    proc = subprocess.Popen(
        [exe, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    found_url = None
    deadline = time.time() + 60

    def reader():
        nonlocal found_url
        for line in proc.stdout:
            print("  [cloudflared] " + line.rstrip())
            m = URL_RE.search(line)
            if m and not found_url:
                found_url = m.group(0)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    while time.time() < deadline and not found_url and proc.poll() is None:
        time.sleep(0.5)

    if not found_url:
        print()
        print("隧道启动失败或超时。检查网络是否能访问 Cloudflare。")
        try:
            proc.terminate()
        except Exception:
            pass
        return 1

    suffix = f"?token={token}" if token else ""
    callback = f"{found_url}/hook{suffix}"

    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    out = os.path.join(BASE_DIR, "data", "callback-url.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(callback + "\n")

    print()
    print("=" * 62)
    print("  把这个地址复制到 FeedWe 的 Webhook 设置里：")
    print()
    print("  " + callback)
    print()
    print("  （已保存到 data\\callback-url.txt）")
    print()
    print("  重要提醒：这个地址每次重启电脑都会变。")
    print("  变了以后要回 FeedWe 后台改一次。")
    print("=" * 62)
    print()
    print("隧道运行中，关闭本窗口即断开。按 Ctrl+C 停止。")

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n正在关闭隧道…")
        try:
            proc.terminate()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
