"""通知层：桌面弹窗 + 提示音 + 邮件。

设计要点：
- 弹窗跑在独立线程，tkinter 非线程安全，所有 UI 操作都在该线程内完成
- 多个提醒排队显示，不覆盖（避免漏看）
- tkinter 不可用时降级为 Windows Toast
- 任何通知失败都不能影响主流程
"""
import html
import logging
import queue
import smtplib
import threading
import time
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Any, Dict, List, Optional

from article_parser import Article, is_safe_article_url

log = logging.getLogger(__name__)

TITLE_MAX = 80


def _truncate(text: str, limit: int = TITLE_MAX) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_alert_text(article: Article, keywords: List[str]) -> str:
    """弹窗正文（纯文本）。"""
    lines = [_truncate(article.title)]
    meta = []
    if article.account:
        meta.append(f"来源：{article.account}")
    if article.published_at:
        meta.append(article.published_at)
    if meta:
        lines.append("　".join(meta))
    if keywords:
        lines.append("命中：" + "、".join(keywords))
    return "\n".join(lines)


# ---------------------------------------------------------------- 邮件


def build_email_message(article: Article, keywords: List[str], cfg: Dict[str, Any]):
    """构造一封 HTML 邮件。"""
    kw_str = "、".join(keywords) if keywords else "—"
    subject = "[综测提醒] " + _truncate(" ".join(article.title.split()), 50)

    safe = {
        "title": html.escape(article.title),
        "url": html.escape(article.url, quote=True) if is_safe_article_url(article.url) else "",
        "account": html.escape(article.account or "未知来源"),
        "time": html.escape(article.published_at or "未知时间"),
        "kw": html.escape(kw_str),
    }

    body = f"""\
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:#f5f6f8;
             font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;
              overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);">
    <div style="background:#c62828;color:#fff;padding:16px 22px;">
      <div style="font-size:13px;opacity:.9;letter-spacing:1px;">综测加分活动提醒</div>
    </div>
    <div style="padding:22px;">
      <h2 style="margin:0 0 14px;font-size:19px;line-height:1.45;color:#1a1a1a;">
        {safe['title']}
      </h2>
      <table style="font-size:14px;color:#555;border-collapse:collapse;">
        <tr><td style="padding:3px 14px 3px 0;color:#999;">公众号</td><td>{safe['account']}</td></tr>
        <tr><td style="padding:3px 14px 3px 0;color:#999;">发布时间</td><td>{safe['time']}</td></tr>
        <tr><td style="padding:3px 14px 3px 0;color:#999;">命中关键词</td>
            <td style="color:#c62828;font-weight:600;">{safe['kw']}</td></tr>
      </table>
      <div style="margin-top:22px;">
        <a href="{safe['url']}"
           style="display:inline-block;background:#c62828;color:#fff;text-decoration:none;
                  padding:11px 26px;border-radius:8px;font-size:15px;font-weight:500;">
          打开原文 →
        </a>
      </div>
      <p style="margin-top:22px;font-size:12px;color:#aaa;line-height:1.6;">
        此邮件由本机综测提醒程序自动发送。若链接无法点击，请复制：<br>
        <span style="color:#888;word-break:break-all;">{safe['url']}</span>
      </p>
    </div>
  </div>
</body></html>
"""
    return _message(subject, body, cfg)


def _batch_title(account, articles):
    return f"{_truncate(' '.join(account.split()) or '未知公众号', 50)}有 {len(articles)} 篇新文章待看"


def build_batch_email(account, articles, cfg):
    title = _batch_title(account, articles)
    lines = []
    for art in articles:
        text = html.escape(_truncate(art.title, 300))
        if is_safe_article_url(art.url):
            text = '<a href="{}">{}</a>'.format(html.escape(art.url, quote=True), text)
        lines.append('<li>' + text + '</li>')
    body = '<h2>{}</h2><ol>{}</ol><p>可在本机托盘 → 待看文章中逐篇标记已看。</p>'.format(html.escape(title), ''.join(lines))
    return _message('[订阅更新] ' + title, body, cfg)


def _message(subject, body, cfg):
    sender = (cfg.get("username") or "").strip()
    to_addr = (cfg.get("to") or "").strip() or sender
    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    # From 用纯地址：带中文显示名在 QQ/163 客户端容易进垃圾箱
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    return msg


class EmailSender:
    """QQ 邮箱 SMTP 发送器。失败只记日志，绝不抛到主流程。"""

    def __init__(self, cfg: Optional[Dict[str, Any]]):
        self.cfg = cfg or {}
        self.enabled = bool(
            self.cfg.get("enabled")
            and (self.cfg.get("username") or "").strip()
            and (self.cfg.get("password") or "").strip()
        )
        if self.cfg.get("enabled") and not self.enabled:
            log.warning("邮件已启用但缺少 username/password，视为未启用")

    def send(self, article: Article, keywords: List[str]) -> bool:
        return self._send(build_email_message, article, keywords)

    def send_batch(self, account, articles) -> bool:
        return self._send(build_batch_email, account, articles)

    def _send(self, build, *args):
        if not self.enabled:
            return False
        try:
            msg = build(*args, self.cfg)
            host = self.cfg.get("smtp_host", "smtp.qq.com")
            port = int(self.cfg.get("smtp_port", 465))
            timeout = 20

            if self.cfg.get("use_ssl", True):
                server = smtplib.SMTP_SSL(host, port, timeout=timeout)
            else:
                server = smtplib.SMTP(host, port, timeout=timeout)
                server.starttls()

            try:
                server.login(self.cfg["username"], self.cfg["password"])
                server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass

            log.info("提醒邮件已交给 SMTP 服务器")
            return True

        except Exception as e:
            log.error("邮件发送失败：%s", e)
            return False


# ---------------------------------------------------------------- 弹窗


def _play_sound() -> None:
    """播放系统提示音；失败静默。"""
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


def _toast_fallback(title: str, message: str) -> bool:
    """tkinter 不可用时降级为 Windows Toast。"""
    try:
        from win10toast import ToastNotifier  # type: ignore

        if ToastNotifier().show_toast(title, message, duration=15, threaded=False):
            return True
    except Exception:
        pass

    try:
        # 最后兜底：PowerShell 原生 Toast
        import subprocess

        import os
        ps = """
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $t.GetElementsByTagName('text')
$texts.Item(0).AppendChild($t.CreateTextNode($env:ZC_TITLE)) | Out-Null
$texts.Item(1).AppendChild($t.CreateTextNode($env:ZC_BODY)) | Out-Null
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('综测提醒').Show([Windows.UI.Notifications.ToastNotification]::new($t))
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            env=dict(os.environ, ZC_TITLE=_truncate(title, 200), ZC_BODY=_truncate(message, 600)),
            timeout=15,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
    except Exception as e:
        log.error("Toast 兜底也失败：%s", e)
        return False


class PopupNotifier:
    """基于 tkinter 的置顶弹窗，单线程消费队列。"""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = cfg or {}
        self.timeout = int(self.cfg.get("popup_timeout", 30) or 0)
        self.always_on_top = bool(self.cfg.get("always_on_top", True))
        self.sound = bool(self.cfg.get("sound", True))
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._start_lock = threading.Lock()
        self._started = threading.Event()
        self._available = True
        # 诊断信息：最近一次弹窗是否真的显示成功，供 --test 报告
        self.last_show_ok = False
        self.last_error = ""
        self._shown = threading.Event()

    def start(self) -> None:
        with self._start_lock:
            if self._available and not (self._thread and self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, name="popup", daemon=True)
                self._thread.start()
        self._started.wait()

    def notify(self, title: str, message: str, url: str = "", on_result=None) -> None:
        self._enqueue(title, message, url if is_safe_article_url(url) else "", on_result, False)

    def notify_batch(self, account, articles, on_result=None) -> None:
        preview = [_truncate(a.title, 48) for a in articles[:3]]
        preview.append("全部文章见托盘 → 待看文章。")
        self._enqueue(_batch_title(account, articles), "\n".join(preview), "", on_result, True)

    def _enqueue(self, title, message, url, callback, batch):
        reported = False
        def receipt(ok):
            nonlocal reported
            if reported:
                return
            reported = True
            self.last_show_ok = bool(ok)
            self.last_error = "" if ok else "未能显示提醒"
            self._shown.set()
            if callback:
                try:
                    callback(bool(ok))
                except Exception:
                    log.warning("通知回执处理失败")
        if self._available:
            self.start()
        if not self._available:
            receipt(_toast_fallback(title, message))
            return
        self._queue.put((title, message, url, receipt, batch))
        if self.sound:
            _play_sound()

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """等弹窗队列清空（自检用）。返回是否在超时前清空。"""
        import time as _t

        deadline = _t.time() + timeout
        while _t.time() < deadline:
            if self._queue.empty():
                return True
            _t.sleep(0.2)
        return False

    # -- 内部 --

    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as e:
            log.error("tkinter 不可用（%s），降级为 Toast 通知", e)
            self._available = False
            self._started.set()
            return

        self._started.set()

        while True:
            item = self._queue.get()
            if item is None:
                break
            title, message, url, receipt, batch = item
            displayed = False
            def visible(ok):
                nonlocal displayed
                displayed = bool(ok)
                receipt(ok)
            try:
                self._show_one(tk, title, message, url, visible, batch)
            except Exception as e:
                log.warning("弹窗渲染失败：%s", e)
            if not displayed:
                receipt(_toast_fallback(title, message))

    def _show_one(self, tk, title: str, message: str, url: str, receipt, batch=False) -> None:
        win = tk.Tk()
        caption = "订阅号更新 · 待看文章" if batch else "综测加分活动提醒"
        win.title(caption)
        win.configure(bg="#c62828")
        win.attributes("-topmost", self.always_on_top)
        win.resizable(False, False)

        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()

        # 尺寸：不超过屏幕的 70%，避免小屏幕上溢出
        w = max(480, min(760, int(sw * 0.6)))
        h = 380
        if h > int(sh * 0.6):
            h = int(sh * 0.6)

        # 居中偏上——比角落里更容易被注意到
        x = max(0, (sw - w) // 2)
        y = max(0, int((sh - h) * 0.38))
        win.geometry(f"{w}x{h}+{x}+{y}")

        # 外层红边框（3px），让窗口在浅色桌面上跳出来
        outer = tk.Frame(win, bg="#ffffff")
        outer.pack(fill="both", expand=True, padx=3, pady=3)

        # 标题栏
        head = tk.Frame(outer, bg="#c62828", height=64)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(
            head, text=caption, bg="#c62828", fg="#ffffff",
            font=("Microsoft YaHei UI", 16, "bold"), anchor="w", padx=20,
        ).pack(fill="both", expand=True)

        body = tk.Frame(outer, bg="#ffffff")
        body.pack(fill="both", expand=True, padx=24, pady=16)

        # 标题：大字、粗体、自动换行
        tk.Label(
            body, text=title, bg="#ffffff", fg="#1a1a1a",
            font=("Microsoft YaHei UI", 15, "bold"),
            wraplength=w - 70, justify="left", anchor="w",
        ).pack(fill="x", pady=(4, 12))

        # 分隔线
        tk.Frame(body, bg="#eeeeee", height=1).pack(fill="x", pady=(0, 12))

        tk.Label(
            body, text=message, bg="#ffffff", fg="#555555",
            font=("Microsoft YaHei UI", 12),
            wraplength=w - 70, justify="left", anchor="w",
        ).pack(fill="x")

        btns = tk.Frame(outer, bg="#ffffff")
        btns.pack(fill="x", padx=24, pady=(0, 18), side="bottom")

        def open_article():
            if url:
                try:
                    import webbrowser

                    webbrowser.open(url)
                except Exception as e:
                    log.error("打开链接失败：%s", e)
            close()

        def close():
            try:
                win.destroy()
            except Exception:
                pass

        if url:
            tk.Button(
                btns, text="  打开原文  ", command=open_article,
                bg="#c62828", fg="#ffffff", relief="flat", cursor="hand2",
                font=("Microsoft YaHei UI", 12, "bold"), padx=24, pady=10, bd=0,
                activebackground="#a01c1c", activeforeground="#ffffff",
            ).pack(side="left")

        tk.Button(
            btns, text="  知道了  ", command=close,
            bg="#eeeeee", fg="#333333", relief="flat", cursor="hand2",
            font=("Microsoft YaHei UI", 12), padx=22, pady=10, bd=0,
            activebackground="#dddddd",
        ).pack(side="left", padx=(12, 0))

        if self.timeout > 0:
            win.after(self.timeout * 1000, close)

        # 把窗口真实状态记进日志——"没报错"不代表"用户看得见"。
        def _report_state():
            try:
                geo = win.geometry()
                viewable = win.winfo_viewable()
                topmost = win.attributes("-topmost")
                log.info(
                    "弹窗已显示：geometry=%s viewable=%s topmost=%s screen=%dx%d",
                    geo, viewable, topmost,
                    win.winfo_screenwidth(), win.winfo_screenheight(),
                )
                # 再抬一次，防止被其他前台窗口压住
                win.lift()
                win.focus_force()
            except Exception as e:
                log.warning("弹窗状态检查失败：%s", e)

        win.after(120, _report_state)

        # 根窗口映射到桌面才算显示；回执独立于关闭、打开原文或标为已看。
        def mapped(event):
            if event.widget is win and win.winfo_viewable():
                receipt(True)
        win.bind("<Map>", mapped, add="+")

        win.mainloop()
