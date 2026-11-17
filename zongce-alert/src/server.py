"""Webhook 接收服务：把 FeedWe 的推送变成弹窗。

链路：POST /hook?token=xxx
   → 校验 token
   → 解析 payload（自适应）
   → 关键词筛选
   → 去重
   → 弹窗 + 邮件
   → 返回 JSON（FeedWe 侧能看到结果）

安全考虑：
- 只监听 127.0.0.1，公网入口交给 Cloudflare Tunnel，不直接暴露
- token 校验失败返回 401，防止被人乱打
- 请求体大小上限，防止内存被打爆
"""
import json
import logging
import os
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
        self.store = SeenStore(db_path)

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

    def handle_payload(self, payload: Any, ignore_keywords: bool = False) -> Dict[str, Any]:
        """返回处理摘要，同时作为 HTTP 响应体。

        ignore_keywords=True 用于联通性测试（?test=1）：
        FeedWe 的测试消息标题是 "Test article title"，不含任何关键词，
        正常模式下会被正确拦截，导致用户无法验证通路是否打通。
        """
        articles = parse_payload(payload)
        if not articles:
            log.warning("payload 未解析出任何文章")
            return {"ok": True, "parsed": 0, "notified": 0, "reason": "no_articles"}

        notified = []
        skipped_dup = 0
        skipped_kw = 0

        for art in articles:
            text = art.title
            if self.match_field == "title_and_summary":
                text = f"{art.title}\n{art.summary}"

            if ignore_keywords:
                hit_kws = ["（测试模式，跳过关键词）"]
                # 测试模式不写去重库：FeedWe 的测试消息标题/链接固定不变，
                # 一旦入库，第二次点「发送测试消息」就会被判"已提醒过"而静默跳过。
                # 测试模式的存在意义就是可反复验证，所以直接放行、不记录。
                log.info("测试模式，直接提醒：%s", art.title)
                self._dispatch(art, hit_kws)
                notified.append({"title": art.title, "keywords": hit_kws})
                continue

            hit = match_keywords(text, self.keywords)
            if not hit.matched:
                skipped_kw += 1
                log.info("未命中关键词，跳过：%s", art.title)
                continue
            hit_kws = hit.keywords

            # 去重放在关键词之后：未命中的不必占库
            with self._lock:
                is_new = self.store.mark_if_new(art.url, art.title)
            if not is_new:
                skipped_dup += 1
                log.info("已提醒过，跳过：%s", art.title)
                continue

            log.info("命中 %s | %s", hit_kws, art.title)
            self._dispatch(art, hit_kws)
            notified.append({"title": art.title, "keywords": hit_kws})

        return {
            "ok": True,
            "parsed": len(articles),
            "notified": len(notified),
            "skipped_duplicate": skipped_dup,
            "skipped_keyword": skipped_kw,
            "items": notified,
        }

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

            self._json(200, result)

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
        _report_startup_failure(cfg, port, msg)
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

            def status_provider() -> str:
                return build_status_text(
                    port=port,
                    seen=service.store.count(),
                    email_enabled=service.email.enabled,
                    token_set=bool(token),
                    token_masked=mask_secret(token) if token else "",
                )

            tray = TrayIcon(
                port=port,
                status_provider=status_provider,
                on_quit=request_shutdown,
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
        if tray is not None:
            tray.stop()
        service.store.close()
        log.info("已退出")
    return 0


def _report_startup_failure(cfg: Dict[str, Any], port: int, msg: str) -> None:
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
        import os as _os
        from datetime import datetime as _dt

        # server.py 位于 <root>/src/，上一级就是程序根目录
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        path = _os.path.join(root, "启动失败.txt")
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
