"""系统托盘图标。

目的：开机静默启动时，给用户一个"我还在运行"的可感知入口，
而不是一个占满前台的黑色终端窗口。

依赖：pystray + Pillow。缺失时优雅降级（只记日志，不影响核心提醒功能）。
"""
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from typing import Callable, List, Optional

log = logging.getLogger(__name__)


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
    改错了比崩溃更麻烦。
    """
    return [
        "查看状态",
        "在浏览器中查看状态",
        "打开日志",
        "打开回调地址文件",
        "重启提示",
        "退出",
    ]


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
                log.info("用户查看状态：\n%s", text)
                self._notify("当前状态", text)
            except Exception as e:
                log.warning("查看状态失败：%s", e)

        def open_health(icon=None, item=None):
            webbrowser.open(self.health_url())

        def open_log(icon=None, item=None):
            self._open_path(os.path.join(self.base_dir, "data", "alert.log"),
                            fallback=self.base_dir)

        def open_callback(icon=None, item=None):
            path = os.path.join(self.base_dir, "data", "callback-url.txt")
            self._open_path(path, fallback=self.base_dir)

        def show_restart_hint(icon=None, item=None):
            self._notify(
                "重启后要做的事",
                "隧道地址每次重启都会变。\n"
                "1. 运行 start_tunnel.py\n"
                "2. 复制 data\\callback-url.txt 里的地址\n"
                "3. 粘到 FeedWe 的 Webhook 设置",
            )

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
