"""启动公网隧道，并把可复制的回调地址显眼地打印出来。

支持两种模式：

1. Cloudflare 快速隧道（默认）
   cloudflared 的 trycloudflare 地址每次重启都会变，需要人工去 FeedWe
   后台更新一次。本脚本自动把地址抓出来、拼上 token、存到
   data/callback-url.txt，并直接显示。

2. Tailscale Funnel（--mode funnel）
   地址固定为 https://<机器名>.<tailnet>.ts.net，重启不变。
   因此不再每次重写回调地址，也不会再打印"地址会变"的提醒。
   代价是走 Tailscale 的中继，延迟略高；且只能监听 443/8443/10000。

用法：
    python start_tunnel.py                # Cloudflare 快速隧道
    python start_tunnel.py --mode funnel  # Tailscale Funnel（需先 tailscale up）
    python start_tunnel.py --print-url    # 只打印当前应填的回调地址后退出
"""
import argparse
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

# Tailscale Funnel 只允许这三个端口，本地 8765 必须映射到其中之一
FUNNEL_PORTS = (443, 8443, 10000)
FUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net")

TAILSCALE_CANDIDATES = (
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
)


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


def find_tailscale():
    """找 tailscale 可执行文件。"""
    for name in ("tailscale", "tailscale.exe"):
        try:
            subprocess.run([name, "version"], capture_output=True, timeout=15, check=True)
            return name
        except Exception:
            continue
    for p in TAILSCALE_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def run(cmd, timeout=60):
    """跑一条命令，返回 (returncode, stdout+stderr)。"""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # pragma: no cover - 环境相关
        return 1, str(e)


def tailscale_dns_name(ts_exe):
    """取 Funnel 用的固定域名，形如 https://host.tailnet.ts.net。

    `tailscale status --json` 里的 Self.DNSName 就是它，
    但末尾带一个点，需要去掉。
    """
    code, out = run([ts_exe, "status", "--json"])
    if code != 0:
        return None, "无法读取 Tailscale 状态：" + out.strip()
    import json

    try:
        data = json.loads(out)
    except ValueError:
        return None, "Tailscale 状态不是合法 JSON"
    dns = ((data.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not dns:
        return None, "Tailscale 尚未分配域名（可能还没登录，或 MagicDNS 没开）"
    return f"https://{dns}", None


def make_callback(url, token):
    suffix = f"?token={token}" if token else ""
    return f"{url}/hook{suffix}"


def save_callback(callback):
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    out = os.path.join(BASE_DIR, "data", "callback-url.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(callback + "\n")
    return out


def warn_if_no_token(token):
    if token:
        return
    print("=" * 62)
    print("警告：还没有设置回调 token！")
    print()
    print("没有 token，任何知道隧道地址的人都能往你的程序发消息弹窗。")
    print("先运行：")
    print("  python run.py --gen-token")
    print("然后再回来运行本脚本。")
    print("=" * 62)
    print()


def print_callback_block(callback, *, stable: bool, saved_path=None):
    """统一打印回调地址。stable=True 时不提示"地址会变"。"""
    print()
    print("=" * 62)
    print("  把这个地址复制到 FeedWe 的 Webhook 设置里：")
    print()
    print("  " + callback)
    print()
    if saved_path:
        print(f"  （已保存到 {os.path.relpath(saved_path, BASE_DIR)}）")
        print()
    if stable:
        print("  这个地址是固定的，重启电脑也不会变。")
        print("  只需要在 FeedWe 后台填一次。")
    else:
        print("  重要提醒：这个地址每次重启电脑都会变。")
        print("  变了以后要回 FeedWe 后台改一次。")
        print("  想彻底解决，改用：python start_tunnel.py --mode funnel")
    print("=" * 62)
    print()


def max_funnel_port_pref():
    """Funnel 端口优先级：443 > 8443 > 10000。"""
    return FUNNEL_PORTS[0]


def main_funnel(cfg, port, token, print_url_only=False) -> int:
    """Tailscale Funnel 模式：地址固定，不需要抓日志。"""
    ts_exe = find_tailscale()
    if not ts_exe:
        print("=" * 62)
        print("没有找到 tailscale。请先安装：")
        print()
        print("  winget install --id Tailscale.Tailscale")
        print()
        print("装好后在【管理员】终端里运行一次：")
        print(r"  & 'C:\Program Files\Tailscale\tailscale.exe' up")
        print("=" * 62)
        return 1

    code, out = run([ts_exe, "status"])
    if code != 0 or "Logged out" in out:
        print("=" * 62)
        print("Tailscale 还没有登录。请在【管理员】终端里运行：")
        print()
        print(r"  & 'C:\Program Files\Tailscale\tailscale.exe' up")
        print()
        print("浏览器里授权一次即可，之后开机自动连。")
        print("=" * 62)
        return 1

    base_url, err = tailscale_dns_name(ts_exe)
    if not base_url:
        print("=" * 62)
        print(err)
        print()
        print("请在 Tailscale 管理后台开启 MagicDNS 后重试。")
        print("=" * 62)
        return 1

    callback = make_callback(base_url, token)

    if print_url_only:
        print(callback)
        return 0

    https_port = max_funnel_port_pref()
    print("=" * 62)
    print(f"正在把本机 {port} 端口通过 Funnel 暴露到 {https_port} …")
    print("=" * 62)

    # tailscale funnel --bg --https=443 http://127.0.0.1:8765
    rc, out = run(
        [
            ts_exe,
            "funnel",
            "--bg",
            f"--https={https_port}",
            f"http://127.0.0.1:{port}",
        ],
        timeout=120,
    )
    if rc != 0:
        print(out.strip())
        print()
        print("=" * 62)
        print("Funnel 启动失败。常见原因：")
        print("  1. 没用【管理员】终端运行 —— Windows 上必须提权")
        print("  2. 管理后台没开 Funnel（Access controls 里要有 funnel 节点属性）")
        print("  3. 没开 HTTPS 证书（DNS 页面里勾上 Enable HTTPS）")
        print()
        print("如果是第 2、3 条，看 docs/QUICKSTART.md 的 Funnel 小节。")
        print("=" * 62)
        return 1

    saved = save_callback(callback)
    print_callback_block(callback, stable=True, saved_path=saved)
    print("Funnel 已在后台运行，可以关闭本窗口。停止用：")
    print(f'  "{ts_exe}" funnel --https={https_port} off')
    print()
    return 0


def main_cloudflare(cfg, port, token, print_url_only=False) -> int:
    """Cloudflare 快速隧道模式（原有行为）。"""
    if print_url_only:
        p = os.path.join(BASE_DIR, "data", "callback-url.txt")
        if os.path.exists(p):
            print(open(p, encoding="utf-8").read().strip())
            return 0
        print("还没有保存过的回调地址。先运行：python start_tunnel.py")
        return 1

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

    callback = make_callback(found_url, token)
    saved = save_callback(callback)
    print_callback_block(callback, stable=False, saved_path=saved)
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="启动公网隧道并打印回调地址")
    parser.add_argument(
        "--mode",
        choices=("cloudflare", "funnel"),
        default="cloudflare",
        help="cloudflare = trycloudflare 临时隧道（地址会变）；funnel = Tailscale 固定域名",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="只打印当前应填的回调地址后退出，不启动隧道",
    )
    args = parser.parse_args(argv)

    cfg = load_config(os.path.join(BASE_DIR, "config.json"))
    port = int(cfg.get("port", 8765))
    token = cfg.get("token", "") or ""

    warn_if_no_token(token)

    if args.mode == "funnel":
        return main_funnel(cfg, port, token, print_url_only=args.print_url)
    return main_cloudflare(cfg, port, token, print_url_only=args.print_url)


if __name__ == "__main__":
    sys.exit(main())
