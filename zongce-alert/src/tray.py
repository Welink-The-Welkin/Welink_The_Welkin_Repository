"""系统托盘图标。

目的：开机静默启动时，给用户一个"我还在运行"的可感知入口，
而不是一个占满前台的黑色终端窗口。

依赖：pystray + Pillow。缺失时优雅降级（只记日志，不影响核心提醒功能）。
"""
import ctypes
import logging
import os
import re
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
        "待看文章",
        "在浏览器中查看状态",
        "打开日志",
        "打开回调地址文件",
        "帮助",
        "退出",
    ]


_HELP_TOPICS = (
    ("第一次使用：怎样收到第一篇文章？",
     "1. 双击「启动.bat」。点任务栏右下角的 ^，右键红底白勾。\n"
     "2. 在 FeedWe 的「订阅管理」添加想看的公众号。\n"
     "3. 点托盘「打开回调地址文件」，复制完整地址；不要公开。\n"
     "   在 FeedWe 的「自定义 Webhook」中粘贴并保存。\n"
     "   没有地址？看插件文件夹里的 docs\\QUICKSTART.md 第 4 步。\n"
     "   已配好就跳过，不用重新生成回调密码。\n"
     "4. 等订阅号发新文并投递，先看「查看状态」里的「最近正式投递」。\n"
     "   再到「待看文章」点「刷新」；看到那篇的标题才算收到。"),
    ("收到提醒后，去哪里看文章？",
     "右键红底白勾，点「待看文章」→「刷新」。选中一篇，点「打开原文」。\n"
     "打开不会自动标记已看；读完点「标记已看」，这篇才会从待看列表移走。\n\n"
     "默认提醒所有订阅号，但只算本机收到并解析出的新文章。\n"
     "含关键词的逐篇提醒；同一次推送里，同一公众号的其余文章合并成一条提醒，列表里仍可逐篇看。"),
    ("测试成功，为什么待看还是空的？",
     "「自检.bat」只验证本机通知，不增加待看文章。\n"
     "如果启用了邮件，它会真的发一封自检邮件。\n\n"
     "FeedWe 的 System Test 发到默认回调地址时，\n"
     "不弹窗、不进待看，也不更新「最近正式投递」。\n"
     "不用改地址或开公网测试。等订阅号发新文章，再看「查看状态」和「待看文章」。"),
    ("公众号发文了，却没收到提醒？",
     "先点托盘「查看状态」，看「最近正式投递」的时间和待看篇数。\n\n"
     "时间没更新：确认该号发了新文、FeedWe 仍有订阅。\n"
     "再查隧道是否连通、自定义 Webhook 是否填了当前完整地址。\n"
     "时间有更新：在「待看文章」点「刷新」，找那篇的标题。\n"
     "仍没提醒，查「待派送」「派送失败」「最近解析异常」，再点「打开日志」。\n\n"
     "本机只能处理送到这里的文章。不要删除数据库，删库不能补回漏送的文章。"),
    ("有弹窗，为什么没邮件？",
     "点托盘「查看状态」，看「邮件通知」。\n"
     "未启用：按插件文件夹 docs\\CONFIG.md 的邮件步骤开启。\n\n"
     "已开启：先查收件箱和垃圾邮件，再核对收件地址和邮箱授权码。\n"
     "授权码不是登录密码，不要展示或分享。\n"
     "双击「自检.bat」验证：邮件启用时会发自检邮件，可按窗口结果检查是否收到。"),
    ("电脑重启后，要重新设置吗？", None),  # 点击时才根据本机回调地址生成答案。
)


def read_callback_host(base_dir: str) -> Optional[str]:
    """读 data/callback-url.txt 里的主机名。

    只返回 hostname：那个文件里带着 token，绝不能整段显示或写日志。
    """
    path = os.path.join(base_dir, "data", "callback-url.txt")
    try:
        with open(path, encoding="utf-8") as f:
            url = f.read().strip()
        if any(c.isspace() or not c.isprintable() for c in url):
            return None
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username is not None:
            return None
        _ = parts.port  # urlsplit 在读取 port 时才检查端口是否合法。
        host = parts.hostname or ""
        if re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9-]+", host):
            return host
    except (OSError, ValueError):  # 包括无法解码的文件、括号或端口损坏的地址。
        pass
    return None


def describe_tunnel_steps(host: Optional[str]) -> str:
    """托盘和状态脚本使用同一份说明，不回显地址或凭据。"""
    if host and host.endswith(".ts.net"):
        return ("Tailscale Funnel 使用固定地址。先确认 Tailscale 已连接，\n"
                "Funnel 已开启；地址没变就不用重填 FeedWe 的 Webhook。")
    if host and host.endswith(".trycloudflare.com"):
        return ("Cloudflare 临时隧道：在插件文件夹运行 python start_tunnel.py，\n"
                "保持窗口开着。把新的完整地址更新到 FeedWe 的 Webhook。")
    return ("没能识别回调地址。先看 docs\\QUICKSTART.md 第 4 步确认隧道：\n"
            "Tailscale Funnel 用固定地址；Cloudflare 临时隧道重开后，\n"
            "需更新 FeedWe 的地址并保持窗口开着。")


def describe_restart_steps(host: Optional[str]) -> str:
    startup = ("已装自启也先确认：红底白勾还在，不用重复启动。\n"
               "没看到图标就双击「查看状态.bat」；若未运行，再双击「启动.bat」。\n"
               "图标只说明本机程序在运行，不代表隧道已连通。")
    return startup + "\n\n" + describe_tunnel_steps(host)


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
        on_open_inbox: Optional[Callable[[], Optional[bool]]] = None,
    ):
        self.port = port
        self._status_provider = status_provider
        self._on_quit = on_quit
        self._on_open_inbox = on_open_inbox
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

        def open_inbox(icon=None, item=None):
            if self._on_open_inbox is None:
                _show_async("待看文章", "本次运行未启用待看文章。")
                return
            try:
                if self._on_open_inbox() is not False:
                    return
            except Exception:
                log.warning("待看文章窗口启动失败")
            _show_async("待看文章", "打开窗口失败，请重试。")

        def open_health(icon=None, item=None):
            webbrowser.open(self.health_url())

        def open_log(icon=None, item=None):
            self._open_path(os.path.join(self.base_dir, "data", "alert.log"),
                            fallback=self.base_dir)

        def open_callback(icon=None, item=None):
            path = os.path.join(self.base_dir, "data", "callback-url.txt")
            self._open_path(path, fallback=self.base_dir)

        def help_item(question, answer):
            def show_help(icon, item):
                text = answer if answer is not None else describe_restart_steps(read_callback_host(self.base_dir))
                _show_async(question, text)
            return MenuItem(question, show_help)

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
            MenuItem("待看文章", open_inbox),
            MenuItem("在浏览器中查看状态", open_health),
            MenuItem("打开日志", open_log),
            MenuItem("打开回调地址文件", open_callback),
            Menu.SEPARATOR,
            MenuItem("帮助", Menu(*(help_item(q, a) for q, a in _HELP_TOPICS))),
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
