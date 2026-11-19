"""Webhook 接收服务：把 FeedWe 的推送变成弹窗。

链路：POST /hook?token=xxx
   → 校验 token
   → 解析 payload（自适应）
   → 关键词分类、收件和派送任务一起落盘
   → 返回处理计数；后台按已启用的渠道逐篇或按批派送

安全考虑：
- 只监听 127.0.0.1，公网入口交给 Cloudflare Tunnel，不直接暴露
- token 校验失败返回 401，防止被人乱打
- 请求体大小上限，防止内存被打爆
"""
import json
import logging
import os
import sqlite3
from collections import OrderedDict
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from config import load_config, mask_secret
from filter import match_keywords
from notify import EmailSender, PopupNotifier, build_alert_text
from article_parser import parse_payload
from store import SeenStore
from inbox_store import InboxStore
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

MAX_BODY = 2 * 1024 * 1024  # 2MB
DEDUPE_TTL_DAYS = 90

# 本机来源，用于判断是否信任 ?test=1
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


class AlertService:
    """把"一条 payload"处理成"要不要提醒"。与 HTTP 解耦，方便测试。"""

    def __init__(self, cfg: Dict[str, Any], base_dir: str):
        self.cfg = cfg
        self.base_dir = base_dir

        storage = cfg.get("storage", {})
        db_path = storage.get("db_path") or os.path.join(base_dir, "data", "seen.db")
        self.legacy_problem = ""
        try:
            self.store = SeenStore(db_path)
        except (OSError, sqlite3.Error):
            # 不修改或重建损坏的旧库。新收件库仍可接收、去重与恢复派送。
            self.legacy_problem = "旧版去重库不可用；历史计数暂从本次启动算起。"
            log.warning(self.legacy_problem)
            self.store = SeenStore(":memory:")

        raw_dir = storage.get("raw_dir") or os.path.join(base_dir, "data", "raw")
        self.raw_dir = raw_dir
        self.save_raw = bool(storage.get("save_raw_payload", True))
        if self.save_raw:
            os.makedirs(raw_dir, exist_ok=True)

        self.keywords: List[str] = cfg.get("keywords", [])
        self.match_field = cfg.get("match_field", "title")

        notify_cfg = cfg.get("notify", {})
        self.popup_enabled = bool(notify_cfg.get("popup", True))
        self.notifier: Optional[PopupNotifier] = None
        if self.popup_enabled:
            self.notifier = PopupNotifier(notify_cfg)

        self.email = EmailSender(cfg.get("email", {}))
        self._lock = threading.Lock()
        self.batch_all = cfg.get("batch_all_accounts", True) is not False
        self.inbox_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), "inbox.db")
        self.inbox = None
        self.storage_problem = ""
        self._wake = threading.Event()
        self._unsaved_receipts = {}
        self._degraded_notices = OrderedDict()  # 只节流故障重投；不充当永久回执
        self._mail_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="outbox-mail")
        self._open_inbox()

    def _open_inbox(self):
        if self.inbox is None:
            with self._lock:
                if self.inbox is None:
                    try:
                        self.inbox = InboxStore(self.inbox_path)
                    except Exception:
                        self._storage_warning()
        return self.inbox

    def _storage_warning(self):
        self.storage_problem = "本机收件箱读写异常，请检查日志及磁盘。"
        log.warning(self.storage_problem)

    def inbox_status_text(self):
        try:
            state = self.inbox.status()
        except Exception:
            return self.storage_problem or "本机收件箱状态异常"
        return "\n".join(filter(None, [
            "待看：{} 篇；待派送：{}；派送失败：{}".format(state["unread"], state["pending"], state["failed"]),
            "最近正式投递：" + (state["last_received"] or "尚无记录"),
            "最近解析异常：" + state["last_parse_error"] if state["last_parse_error"] else "",
            self.legacy_problem, self.storage_problem]))

    def _parse_warning(self):
        log.warning("正式推送解析异常，请在本机查看原始推送记录。")
        try:
            self.inbox.note_parse_error()
        except Exception:
            self._storage_warning()

    def handle_payload(self, payload: Any, ignore_keywords: bool = False) -> Dict[str, Any]:
        articles = parse_payload(payload)
        account = payload.get("accountName", "") if isinstance(payload, dict) else ""
        test_envelope = isinstance(account, str) and account.strip() == "FeedWe System Test"
        if ignore_keywords:
            if not articles:
                return {"ok": True, "parsed": 0, "notified": 0, "reason": "no_articles"}
            items = []
            for art in articles:
                kws = ["（测试模式，跳过关键词）"]
                self._dispatch(art, kws)
                items.append({"title": art.title, "keywords": kws})
            return {"ok": True, "parsed": len(articles), "notified": len(items), "items": items,
                    "skipped_duplicate": 0, "skipped_keyword": 0}
        if test_envelope:
            return {"ok": True, "parsed": len(articles), "notified": 0, "skipped_keyword": len(articles),
                    "skipped_duplicate": 0, "items": [], "batch_notifications": 0, "inbox_new": 0}
        self._open_inbox()
        raw_items = payload.get("articles") if isinstance(payload, dict) else None
        if not articles:
            if not isinstance(payload, dict) or payload.get("event") in (None, "NEW_ARTICLE"):
                self._parse_warning()
            return {"ok": True, "parsed": 0, "notified": 0, "reason": "no_articles"}
        partial = (isinstance(raw_items, list) and len(articles) < len(raw_items)
                   and any(not parse_payload(item) for item in raw_items))
        entries = []
        for art in articles:
            if isinstance(account, str) and account.strip():
                art.account = account.strip()  # 作者名不等于这次推送所属的订阅号
            text = art.title if self.match_field != "title_and_summary" else f"{art.title}\n{art.summary}"
            kws = match_keywords(text, self.keywords).keywords
            try:
                legacy = bool(kws) and self.store.contains_article(art.url, art.title)
            except Exception:
                legacy = False  # 查不了旧记录时宁可多提醒一次
            entries.append((art, kws, legacy))
        channels = (["popup"] if self.notifier is not None else []) + (["email"] if self.email.enabled else [])
        try:
            result = self.inbox.ingest(entries, channels, batch_all=self.batch_all)
        except Exception:
            self._storage_warning()
            # 入库失败不能吞掉即时提醒；返回 503 允许上游重投。这里宁可多提醒一次。
            groups = {}
            for art, kws, legacy in entries:
                if legacy or not (kws or self.batch_all):
                    continue
                key = (art.account, art.url)
                now = time.monotonic()
                with self._lock:
                    if key in self._degraded_notices and now - self._degraded_notices[key] < 300:
                        continue
                    self._degraded_notices[key] = now
                    self._degraded_notices.move_to_end(key)
                    if len(self._degraded_notices) > 2048:
                        self._degraded_notices.popitem(last=False)
                if kws:
                    self._dispatch(art, kws)
                elif self.batch_all:
                    groups.setdefault(art.account or "未知来源", []).append(art)
            for name, group in groups.items():
                if self.notifier is not None:
                    try:
                        self.notifier.notify_batch(name, group)
                    except Exception:
                        log.warning("降级批弹窗失败")
                if self.email.enabled:
                    self._mail_pool.submit(self.email.send_batch, name, group)
            return {"ok": False, "degraded": True, "parsed": len(articles), "error": "inbox_unavailable"}
        self.storage_problem = ""
        if partial:
            self._parse_warning()
        self._wake.set()
        by_object = {id(a): kws for a, kws, _ in entries}
        items = []
        for art in result["hits"]:
            items.append({"title": art.title, "keywords": by_object[id(art)]})
            try:
                self.store.mark_if_new(art.url, art.title)  # 兼容旧版统计，派送以独立持久队列为准
            except Exception:
                log.warning("更新旧版去重统计失败，不影响已入队提醒")
        log.info("正式投递：解析 %d 篇，新收 %d 篇，关键词提醒 %d 条，按批提醒 %d 条",
                 len(articles), result["new"], len(items), result["batches"])
        return {"ok": True, "parsed": len(articles), "notified": len(items), "items": items,
                "skipped_keyword": sum(not kws for _, kws, _ in entries),
                "skipped_duplicate": result["duplicates"], "inbox_new": result["new"],
                "batch_notifications": result["batches"]}

    def pump_once(self):
        """领取已落盘任务；弹窗和邮件分别记录回执，回执不会更改未读状态。"""
        store = self.inbox
        if store is None:
            return
        def complete(job_id, ok):
            try:
                store.finish_job(job_id, bool(ok))
            except Exception:
                with self._lock:
                    self._unsaved_receipts[job_id] = ok
                self._storage_warning()
        # 临时写锁或磁盘故障恢复后只重写回执，不重新弹窗或发邮件。
        with self._lock:
            receipts, self._unsaved_receipts = self._unsaved_receipts, {}
        for job_id, ok in receipts.items():
            complete(job_id, ok)
        for job in store.take_jobs():
            arts, batch = job["articles"], job["kind"] == "batch"
            first = arts[0]
            account = first.account or "未知来源"
            def done(ok, key=job["id"]):
                complete(key, ok)
            try:
                if job["channel"] == "popup" and self.notifier is not None:
                    if batch:
                        self.notifier.notify_batch(account, arts, on_result=done)
                    else:
                        self.notifier.notify(first.title, build_alert_text(first, job["keywords"]), first.url, on_result=done)
                elif job["channel"] == "email" and self.email.enabled:
                    fn, args = (self.email.send_batch, (account, arts)) if batch else (self.email.send, (first, job["keywords"]))
                    def deliver(send=fn, arguments=args, report=done):
                        try:
                            ok = send(*arguments)
                        except Exception:
                            ok = False
                        report(ok)
                    self._mail_pool.submit(deliver)
                else:
                    done(False)
            except Exception:
                done(False)

    def delivery_loop(self, stop_event):
        recovered = False
        while not stop_event.is_set():
            self._wake.clear()
            try:
                if self._open_inbox() is not None:
                    if not recovered:
                        self.inbox.recover()
                        recovered = True
                    self.pump_once()
            except Exception:
                self._storage_warning()
            self._wake.wait(2)

    def _dispatch(self, article, keywords: List[str]) -> None:
        if self.notifier is not None:
            try:
                self.notifier.notify(
                    article.title, build_alert_text(article, keywords), article.url
                )
            except Exception as e:
                log.error("弹窗失败：%s", e)

        if self.email.enabled:
            # 邮件异步发，别阻塞 HTTP 响应
            threading.Thread(
                target=self.email.send, args=(article, keywords), daemon=True
            ).start()

    def save_raw_payload(self, body: bytes) -> None:
        if not self.save_raw:
            return
        try:
            name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json"
            path = os.path.join(self.raw_dir, name)
            with open(path, "wb") as f:
                f.write(body)
            self._cleanup_raw()
        except Exception as e:
            log.warning("原始 payload 保存失败：%s", e)

    def _cleanup_raw(self) -> None:
        days = int(self.cfg.get("storage", {}).get("keep_raw_days", 7) or 7)
        cutoff = time.time() - days * 86400
        try:
            for fn in os.listdir(self.raw_dir):
                p = os.path.join(self.raw_dir, fn)
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
        except Exception:
            pass


def make_handler(service: AlertService, token: str, health_requires_token: bool = True,
                 test_mode_allow_remote: bool = False):
    """构造 HTTP 处理器。

    安全要点：
    - /hook 与 /health 都校验 token（token 为空时视为未启用鉴权，但启动时会警告）
    - /health 只返回非敏感统计，绝不回显 token 或回调地址
    - ?test=1 会放行全部文章，因此默认只信任本机来源
    """

    class Handler(BaseHTTPRequestHandler):
        server_version = "ZongceAlert/1.0"

        def log_message(self, fmt, *args):  # 覆盖掉默认 stderr 噪音
            log.debug("%s - %s", self.address_string(), fmt % args)

        def _json(self, code: int, obj: Dict[str, Any]) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _client_ip(self) -> str:
            """真实来源 IP。

            服务只监听 127.0.0.1，经隧道进来的请求 client_address 永远是本机，
            所以要走隧道时必须以 CF-Connecting-IP 为准，否则"仅限本机"形同虚设。
            """
            forwarded = (self.headers.get("CF-Connecting-IP") or "").strip()
            if forwarded:
                return forwarded
            return self.client_address[0] if self.client_address else ""

        def _is_local(self) -> bool:
            return self._client_ip() in _LOOPBACK

        def _token_ok(self) -> bool:
            if not token:
                return True
            qs = parse_qs(urlparse(self.path).query)
            supplied = (qs.get("token") or [""])[0]
            if not supplied:
                supplied = self.headers.get("X-Token", "")
            if not supplied:
                return False
            # 定长比较，避免通过响应时间猜测 token
            import hmac

            return hmac.compare_digest(supplied, token)

        def _check_token(self) -> bool:
            if self._token_ok():
                return True
            log.warning("token 校验失败，来自 %s", self._client_ip())
            self._json(401, {"ok": False, "error": "invalid_token"})
            return False

        def do_GET(self):
            path = urlparse(self.path).path

            # /hook 的 GET 只用于"服务活着吗"探测——不处理正文，绝不触发提醒
            if path in ("/", "/health") or (path in ("/hook", "/webhook") and health_requires_token):
                pass
            else:
                self._json(404, {"ok": False, "error": "not_found"})
                return

            if path in ("/hook", "/webhook"):
                # GET /hook 不是投递端点，明确告知，避免误解为"验证成功"
                self._json(
                    200,
                    {
                        "ok": True,
                        "service": "zongce-alert",
                        "note": "本端点只接受 POST 投递；GET 仅用于连通性探测，不会触发提醒",
                    },
                )
                return

            if health_requires_token and not self._check_token():
                return

            self._json(200, {
                "ok": True,
                "service": "zongce-alert",
                "keywords": service.keywords,
                "seen": service.store.count(),
                "email_enabled": service.email.enabled,
                # 注意：不返回 token、回调地址、路径等任何可被利用的信息
                "test_mode_allow_remote": test_mode_allow_remote,
            })

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ("/hook", "/webhook", "/"):
                self._json(404, {"ok": False, "error": "not_found"})
                return

            if not self._check_token():
                return

            # ?test=1 跳过关键词筛选，用于联通性验证。
            # 它会放行全部文章，所以默认只信任本机来源——
            # 否则隧道地址一旦泄露，别人可以让你屏幕上弹任意通知。
            qs = parse_qs(urlparse(self.path).query)
            test_mode = (qs.get("test") or ["0"])[0] in ("1", "true", "yes")
            if test_mode and not test_mode_allow_remote and not self._is_local():
                log.warning("拒绝非本机的 test 请求，来自 %s", self._client_ip())
                self._json(
                    403,
                    {
                        "ok": False,
                        "error": "test_mode_local_only",
                        "hint": "test=1 只允许本机调用；如需远程测试，在本机执行 curl",
                    },
                )
                return

            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0

            if length > MAX_BODY:
                self._json(413, {"ok": False, "error": "payload_too_large"})
                return

            body = self.rfile.read(length) if length else b""
            if not body:
                self._json(400, {"ok": False, "error": "empty_body"})
                return

            service.save_raw_payload(body)

            try:
                payload = json.loads(body.decode("utf-8", "replace"))
            except (ValueError, UnicodeDecodeError):
                payload = body.decode("utf-8", "replace")

            try:
                result = service.handle_payload(payload, ignore_keywords=test_mode)
            except Exception as e:
                # 不把内部异常原文回给调用方（可能含文件路径等实现细节）
                log.exception("处理 payload 出错：%s", e)
                self._json(500, {"ok": False, "error": "internal_error"})
                return

            self._json(503 if result.get("degraded") else 200, result)

    return Handler


def run(cfg: Dict[str, Any], base_dir: str, use_tray: bool = False) -> int:
    """启动服务。返回进程退出码（0 正常，非 0 表示启动失败）。"""
    service = AlertService(cfg, base_dir)
    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 8765))

    token = cfg.get("token", "") or ""
    health_requires_token = bool(cfg.get("health_requires_token", True))
    test_mode_allow_remote = bool(cfg.get("test_mode_allow_remote", False))

    # ---- 端口占用：必须给出可感知的提示，不能静默死掉 ----
    try:
        httpd = ThreadingHTTPServer(
            (host, port),
            make_handler(
                service,
                token,
                health_requires_token=health_requires_token,
                test_mode_allow_remote=test_mode_allow_remote,
            ),
        )
    except OSError as e:
        msg = (
            f"端口 {port} 无法监听（{e.__class__.__name__}: {e.strerror or e}）。\n"
            "最常见原因：已经有一个综测提醒在运行。\n"
            "解决办法：右键点托盘图标 → 退出，然后重新启动；\n"
            "或者改 config.json 里的 port 换一个端口。"
        )
        log.error("启动失败：%s", msg)
        _report_startup_failure(base_dir, port, msg)
        service.store.close()
        return 2

    httpd.daemon_threads = True

    log.info("=" * 56)
    log.info("综测提醒服务已启动")
    log.info("  监听：http://%s:%d", host, port)
    log.info("  关键词：%s", "、".join(service.keywords))
    log.info("  已记录文章：%d 篇", service.store.count())
    log.info("  邮件：%s", "已启用" if service.email.enabled else "未启用")
    if token:
        log.info("  回调 token：%s（已打码）", mask_secret(token))
    else:
        log.warning("  回调 token 为空：任何人都能触发弹窗，请尽快设置！")
    log.info("  /health 鉴权：%s", "需要 token" if health_requires_token else "不需要")
    log.info("  远程测试模式：%s", "允许" if test_mode_allow_remote else "仅限本机")
    log.info("=" * 56)

    # 托盘图标：给静默运行一个可感知入口，也让用户能主动退出
    tray = None
    stop_event = threading.Event()

    def request_shutdown() -> None:
        stop_event.set()

    if use_tray:
        try:
            from tray import TrayIcon
            from inbox_view import open_inbox_window

            def status_provider() -> str:
                return build_status_text(
                    port=port,
                    seen=service.store.count(),
                    email_enabled=service.email.enabled,
                    token_set=bool(token),
                    token_masked=mask_secret(token) if token else "",
                ) + "\n" + service.inbox_status_text()

            tray = TrayIcon(
                port=port,
                status_provider=status_provider,
                on_quit=request_shutdown,
                on_open_inbox=lambda: open_inbox_window(service.inbox_path),
                base_dir=base_dir,
                token=token,
            )
            if not tray.start():
                log.warning("托盘不可用，程序继续在后台运行（无托盘图标）")
        except Exception as e:
            log.warning("托盘初始化失败，忽略：%s", e)

    # 监听放在子线程，主线程等待退出信号，这样托盘菜单的"退出"能生效
    server_thread = threading.Thread(
        target=httpd.serve_forever, name="http", daemon=True
    )
    delivery_thread = threading.Thread(target=service.delivery_loop, args=(stop_event,), name="outbox", daemon=True)
    delivery_thread.start()
    server_thread.start()

    try:
        while not stop_event.is_set():
            stop_event.wait(1.0)
        log.info("收到退出请求，正在关闭…")
    except KeyboardInterrupt:
        log.info("收到中断，正在退出…")
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
        stop_event.set()
        service._wake.set()
        delivery_thread.join(timeout=5)
        service._mail_pool.shutdown(wait=False)
        if tray is not None:
            tray.stop()
        service.store.close()
        log.info("已退出")
    return 0


def _report_startup_failure(base_dir: str, port: int, msg: str) -> None:
    """启动失败时让用户"看得见"。

    静默运行时（pythonw + 托盘）没有任何窗口，失败必须主动冒出来——
    否则用户只看到"开机后托盘没图标"，无从下手。
    """
    # 1) 冒一个 Toast/弹窗（尽力而为，失败无所谓）
    try:
        from notify import _toast_fallback

        _toast_fallback("综测提醒启动失败", msg)
    except Exception as e:
        log.debug("启动失败提示未能显示：%s", e)

    # 2) 在程序目录留一个显眼的文本文件
    try:
        from datetime import datetime as _dt

        path = os.path.join(base_dir, "启动失败.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("时间：%s\n端口：%d\n\n%s\n" % (
                _dt.now().strftime("%Y-%m-%d %H:%M:%S"), port, msg
            ))
        log.error("已把失败原因写入：%s", path)
    except Exception as e:
        log.debug("写入启动失败说明失败：%s", e)


def build_status_text(port: int, seen: int, email_enabled: bool,
                      token_set: bool = True, token_masked: str = "") -> str:
    """转发到 tray 里的实现，保持 server 模块不直接依赖 Pillow。"""
    from tray import build_status_text as _impl

    return _impl(
        port=port,
        seen=seen,
        email_enabled=email_enabled,
        token_set=token_set,
        token_masked=token_masked,
    )
