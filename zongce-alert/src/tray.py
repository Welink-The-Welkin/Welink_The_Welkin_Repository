"""系统托盘图标。

目的：开机静默启动时，给用户一个"我还在运行"的可感知入口，
而不是一个占满前台的黑色终端窗口。

依赖：pystray + Pillow。缺失时优雅降级（只记日志，不影响核心提醒功能）。
"""
import ctypes
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from typing import Callable, List, Optional
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

# MessageBoxW 的样式位（winuser.h）
MB_ICONINFORMATION = 0x00000040
MB_SETFOREGROUND = 0x00010000
MB_TOPMOST = 0x00040000


def _show_message_box(title: str, message: str) -> None:
    """弹一个系统原生信息框（阻塞，调用方负责放到后台线程）。

    为什么不用托盘气泡：Windows 会把通知折叠进操作中心，专注助手/勿扰一开
    就直接不显示，用户点了菜单等于什么都没发生。原生对话框一定能看见。
    也不用 tkinter：文章弹窗已经有自己的 Tk 主循环，再起一个容易互相干扰。
    """
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        flags = MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST
        user32.MessageBoxW(None, message, title, flags)
    except Exception as e:  # user32 缺失或调用被拦
        log.warning("弹窗失败，用户可能看不到提示：%s", e)


def _show_async(title: str, message: str) -> None:
    """在后台线程弹窗，避免阻塞托盘菜单的消息循环。"""
    def _target():
        _show_message_box(title, message)

    threading.Thread(target=_target, name="tray-dialog", daemon=True).start()


def build_status_text(port: int, seen: int, email_enabled: bool,
                      token_set: bool = True, token_masked: str = "") -> str:
    """托盘悬浮提示的文字。多行便于阅读。"""
    if token_set:
        auth = f"已启用（{token_masked}）" if token_masked else "已启用"
    else:
        auth = "⚠ 未设置，任何人不经鉴权就能触发弹窗"
    return "\n".join([
        "综测加分提醒 · 运行中",
        f"监听端口：{port}",
        f"已记录文章：{seen} 篇",
        f"邮件通知：{'已开启' if email_enabled else '未启用'}",
        f"回调鉴权：{auth}",
        "右键点此图标可查看更多",
    ])


def build_menu_labels(port: int) -> List[str]:
    """菜单项文字（顺序即显示顺序）。

    独立成函数是为了可测——菜单项文案是用户唯一的交互指引，
    改错了比崩溃更麻烦。必须与 _build_menu 里的实际标签逐字一致。
    """
    return [
        "查看状态",
        "在浏览器中查看状态",
        "打开日志",
        "打开回调地址文件",
        "重启后要做什么？",
        "退出",
    ]


def read_callback_host(base_dir: str) -> Optional[str]:
    """读 data/callback-url.txt 里的主机名。

    只返回 hostname：那个文件里带着 token，绝不能整段显示或写日志。
    """
    path = os.path.join(base_dir, "data", "callback-url.txt")
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            url = f.read().strip()
    except OSError:
        return None
    if not url:
        return None
    return urlsplit(url).hostname or None


def describe_restart_steps(host: Optional[str]) -> str:
    """按当前回调地址的主机名，给出重启后真正该做的事。

    临时隧道的地址会变、Funnel 的不会——两种情况混着说，
    用户就会按错的那套去操作（比如白跑一趟去改 FeedWe）。
    """
    head = "程序会随开机自启自动运行（装过自启的话）。"
    common_tail = (
        "怎么确认在用哪种地址：\n"
        "  右键托盘 →「打开回调地址文件」，看域名。\n"
        "    以 .ts.net 结尾  →  Tailscale Funnel\n"
        "    以 .trycloudflare.com 结尾  →  Cloudflare 临时隧道"
    )

    if host and host.endswith(".ts.net"):
        return "\n".join([
            "你用的是 Tailscale Funnel，地址固定不变。",
            "",
            "重启后只需要：",
            "1. 等 Tailscale 自己连上（托盘图标出现即算就绪）",
            "2. 启动本程序（双击 启动.bat）",
            "3. FeedWe 后台的 Webhook 不用动，地址不会变",
            "",
            "只有这三种情况才需要回 FeedWe 改一次：",
            "  · 换了电脑（机器名变了，域名跟着变）",
            "  · 退出了 tailnet 或改了 tailnet 名称",
            "  · 用 python run.py --gen-token 轮换了 token",
            "",
            head,
            "托盘图标出现就说明 Tailscale 和本程序都在跑。",
            "",
            "如果长时间收不到推送，先看 data\\alert.log，",
            "那多半是程序没起来，而不是隧道的问题。",
        ])

    if host and host.endswith(".trycloudflare.com"):
        return "\n".join([
            "你用的是 Cloudflare 临时隧道，地址每次启动都会变。",
            "",
            "重启后要：",
            "1. 运行 python start_tunnel.py，等它打印新地址",
            "2. 复制 data\\callback-url.txt 里的完整地址",
            "3. 粘到 FeedWe 后台的 Webhook 设置里",
            "",
            "嫌麻烦的话，可以改用 Tailscale Funnel，地址固定：",
            "  python start_tunnel.py --mode funnel",
            "",
            head,
        ])

    return "\n".join([
        "还没读到当前的回调地址（data\\callback-url.txt 不存在或为空）。",
        "",
        "请先确定自己用的是哪种隧道：",
        "",
        "【A. Tailscale Funnel】地址固定，重启后什么都不用改",
        "  1. 确认托盘图标出现（Tailscale 已连上）",
        "  2. 双击 启动.bat",
        "  3. FeedWe 后台不用动",
        "  启动命令：python start_tunnel.py --mode funnel",
        "",
        "【B. Cloudflare 临时隧道】地址每次都变",
        "  1. python start_tunnel.py，记下新地址",
        "  2. 粘到 FeedWe 后台的 Webhook 设置里",
        "",
        common_tail,
    ])


def make_icon_image(size: int = 64):
    """画一个托盘图标：红底白色对勾，暗示"提醒/已完成"。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角红底
    m = max(1, size // 16)
    d.ellipse([m, m, size - m, size - m], fill=(198, 40, 40, 255))

    # 白色对勾
    s = size
    d.line(
        [(s * 0.28, s * 0.52), (s * 0.44, s * 0.68), (s * 0.74, s * 0.34)],
        fill=(255, 255, 255, 255),
        width=max(2, size // 9),
        joint="curve",
    )
    return img


class TrayIcon:
    """托盘图标的生命周期管理。

    用法：
        tray = TrayIcon(on_quit=stop_server, status_provider=fn)
        tray.start()   # 非阻塞
        ...
        tray.stop()
    """

    def __init__(
        self,
        port: int,
        status_provider: Callable[[], str],
        on_quit: Callable[[], None],
        base_dir: str,
        token: str = "",
    ):
        self.port = port
        self._status_provider = status_provider
        self._on_quit = on_quit
        self.base_dir = base_dir
        # /health 默认要鉴权，托盘打开浏览器时必须自动带上
        self._token = token or ""
        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self.available = False

    def health_url(self) -> str:
        url = f"http://127.0.0.1:{self.port}/health"
        if self._token:
            from urllib.parse import quote

            url += "?token=" + quote(self._token, safe="")
        return url

    def start(self) -> bool:
        """启动托盘。失败返回 False，不影响主服务。"""
        try:
            import pystray
        except Exception as e:
            log.warning("pystray 不可用，跳过托盘图标：%s", e)
            return False

        try:
            image = make_icon_image(64)
        except Exception as e:
            log.warning("托盘图标生成失败：%s", e)
            return False

        try:
            self._icon = pystray.Icon(
                "zongce_alert",
                image,
                "综测加分提醒",
                menu=self._build_menu(pystray),
            )
        except Exception as e:
            log.warning("托盘菜单创建失败：%s", e)
            return False

        def _run():
            try:
                self._icon.run()
            except Exception as e:
                log.warning("托盘运行异常：%s", e)

        self._thread = threading.Thread(target=_run, name="tray", daemon=True)
        self._thread.start()
        self.available = True
        log.info("托盘图标已启动（右下角）")
        return True

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass

    # -- 内部 --

    def _build_menu(self, pystray):
        Menu = pystray.Menu
        MenuItem = pystray.MenuItem

        def show_status(icon=None, item=None):
            try:
                text = self._status_provider()
            except Exception as e:
                log.warning("查看状态失败：%s", e)
                _show_async("查看状态",
                            "读取状态失败，详细信息见 data\\alert.log：\n%s" % e)
                return
            log.info("用户查看状态：\n%s", text)
            _show_async("综测加分提醒 · 当前状态", text)

        def open_health(icon=None, item=None):
            webbrowser.open(self.health_url())

        def open_log(icon=None, item=None):
            self._open_path(os.path.join(self.base_dir, "data", "alert.log"),
                            fallback=self.base_dir)

        def open_callback(icon=None, item=None):
            path = os.path.join(self.base_dir, "data", "callback-url.txt")
            self._open_path(path, fallback=self.base_dir)

        def show_restart_hint(icon=None, item=None):
            host = read_callback_host(self.base_dir)
            _show_async("重启后要做什么？", describe_restart_steps(host))

        def quit_app(icon=None, item=None):
            log.info("用户从托盘退出程序")
            try:
                if icon is not None:
                    icon.stop()
            except Exception:
                pass
            try:
                self._on_quit()
            except Exception as e:
                log.warning("退出回调失败：%s", e)

        return Menu(
            MenuItem("查看状态", show_status, default=True),
            MenuItem("在浏览器中查看状态", open_health),
            MenuItem("打开日志", open_log),
            MenuItem("打开回调地址文件", open_callback),
            Menu.SEPARATOR,
            MenuItem("重启后要做什么？", show_restart_hint),
            Menu.SEPARATOR,
            MenuItem("退出", quit_app),
        )

    def _notify(self, title: str, message: str) -> None:
        """用托盘气泡显示信息（失败静默）。"""
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title)
        except Exception:
            pass

    def _open_path(self, path: str, fallback: str) -> None:
        """用系统默认程序打开文件；不存在就打开所在目录。"""
        target = path if os.path.exists(path) else fallback
        try:
            os.startfile(target)  # type: ignore[attr-defined]
        except Exception:
            try:
                subprocess.Popen(["explorer", target])
            except Exception as e:
                log.warning("打开路径失败：%s", e)
