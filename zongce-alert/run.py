"""程序入口。

用法：
  python run.py                # 正常启动
  python run.py --test         # 发一条假提醒，验证弹窗和邮件是否正常
  python run.py --config X.json
"""
import argparse
import threading
import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))

from config import load_config  # noqa: E402


def setup_logging(level: str, base_dir: str) -> None:
    """配置日志。

    关键：开机静默启动用 pythonw.exe，没有控制台。
    此时不能依赖 stdout，且未捕获异常会静默消失——
    所以必须挂全局异常钩子，把崩溃写进日志文件。
    """
    log_dir = os.path.join(base_dir, "data")
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    # 幂等：重复调用不堆积 handler
    for h in root.handlers[:]:
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handlers = []

    # 只有真的存在控制台时才挂 stdout
    has_console = sys.stdout is not None and not getattr(sys, "frozen", False)
    if has_console:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        handlers.append(sh)

    fh = logging.FileHandler(
        os.path.join(log_dir, "alert.log"), encoding="utf-8", delay=True
    )
    fh.setFormatter(fmt)
    handlers.append(fh)

    root.setLevel(getattr(logging, (level or "INFO").upper(), logging.INFO))
    for h in handlers:
        root.addHandler(h)

    _install_excepthook(log_dir)


def _install_excepthook(log_dir: str) -> None:
    """把未捕获异常写进日志。

    pythonw 下没有控制台，未捕获异常不会显示在任何地方，
    用户只会看到"开机后程序没起来"。这个钩子是唯一的线索。
    """
    log = logging.getLogger(__name__)

    def handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("未捕获异常，程序即将退出", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = handle

    # 线程里抛的异常不会走 sys.excepthook，需单独处理
    def thread_hook(args):
        log.critical(
            "线程 %s 未捕获异常",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = thread_hook


def self_test(cfg: dict, base_dir: str) -> int:
    """发一条模拟提醒，让用户确认弹窗/声音/邮件都通了。"""
    from article_parser import Article
    from server import AlertService

    service = AlertService(cfg, base_dir)

    demo = Article(
        title="【这是一条测试提醒】综测加分活动通知",
        # 用 example.com（RFC 2606 保留域名）而不是 mp.weixin.qq.com：
        # 后者是网站首页，点「打开原文」跳过去会让人以为程序抓错了文章。
        # 自检要验证的是按钮点得动，不是链接能不能打开真文章。
        url="https://example.com/",
        account="上理大学生",
        published_at="（测试）",
    )

    print("-" * 56)
    print("自检：如果你能看到弹窗、听到提示音，说明通知通路正常。")
    print("（弹窗里的「打开原文」指向示例地址 example.com，点开跳转属正常）")
    print("-" * 56)

    popup_reported = False
    if service.notifier is not None:
        service.notifier.notify(
            demo.title, "来源：上理大学生　命中：综测、加分", demo.url
        )
        # 等窗口真正构建完成，而不是靠猜时间
        shown = service.notifier._shown.wait(timeout=8)
        if service.notifier._available is False:
            print("弹窗：tkinter 不可用，已降级为系统 Toast 通知")
        elif shown:
            print("弹窗：已显示在屏幕右下角（会自动关闭）")
        elif service.notifier.last_error:
            print("弹窗：渲染失败 —", service.notifier.last_error)
        else:
            print("弹窗：8 秒内未确认窗口出现，请看 data/alert.log")
    else:
        print("弹窗已在配置中关闭。")

    if service.email.enabled:
        ok = service.email.send(demo, ["综测", "加分"])
        print("邮件：", "发送成功，请查收收件箱（若没看到，检查垃圾邮件）" if ok
              else "发送失败，请看日志中的具体错误")
    else:
        print("邮件：未启用（config.json 里 email.enabled 为 false，或缺少账号/授权码）")

    print("-" * 56)
    print("自检结束。上面若都正常，就可以去配置 FeedWe 回调了。")

    # 给弹窗留出展示时间，然后干净退出
    hold = int(cfg.get("notify", {}).get("popup_timeout", 10) or 10)
    print(f"（弹窗将保留 {hold} 秒后自动关闭；按 Ctrl+C 可提前结束）")
    try:
        import time as _t

        _t.sleep(min(hold, 20))
    except KeyboardInterrupt:
        pass

    service.store.close()
    return 0


def write_secrets(secrets_path: str, updates: dict) -> None:
    """把凭据写进 secrets.local.json（保留已有键，只覆盖传入的）。

    密钥只落在这个文件里，它已被 .gitignore 排除，不会随项目外泄。
    """
    import json

    data = {}
    if os.path.exists(secrets_path):
        try:
            with open(secrets_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            data = {}

    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k].update(v)
        else:
            data[k] = v

    parent = os.path.dirname(os.path.abspath(secrets_path))
    os.makedirs(parent, exist_ok=True)
    with open(secrets_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def gen_token(path: str) -> int:
    """生成随机 token 并写入 secrets.local.json。"""
    from config import generate_token, secrets_path_for

    sp = secrets_path_for(path)
    new_token = generate_token()
    write_secrets(sp, {"token": new_token})

    print("=" * 60)
    print("已生成新的回调 token，写入：")
    print("  " + sp)
    print()
    print("  token = " + new_token)
    print()
    print("下一步：")
    print("  1. 重启程序（托盘图标 → 退出，然后重新启动）")
    print("  2. 重新生成隧道地址（python start_tunnel.py），")
    print("     它会把 token 自动拼进回调地址")
    print("  3. 把新地址粘到 FeedWe 的 Webhook 设置")
    print("=" * 60)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="公众号综测加分提醒")
    ap.add_argument("--config", default=os.path.join(BASE_DIR, "config.json"))
    ap.add_argument("--test", action="store_true", help="发送一条测试提醒")
    ap.add_argument(
        "--tray",
        action="store_true",
        help="显示系统托盘图标（开机静默启动时使用）",
    )
    ap.add_argument(
        "--no-tray",
        action="store_true",
        help="不显示托盘图标（手动在终端运行时更清爽）",
    )
    ap.add_argument(
        "--gen-token",
        action="store_true",
        help="生成随机回调 token 并写入 secrets.local.json",
    )
    args = ap.parse_args()

    if args.gen_token:
        return gen_token(args.config)

    cfg = load_config(args.config)
    setup_logging(cfg.get("log_level", "INFO"), BASE_DIR)

    # 启动前校验：只警告不阻断，避免因为配置小问题就完全不能用
    from config import validate

    for problem in validate(cfg):
        logging.getLogger(__name__).warning("配置问题：%s", problem)

    if args.test:
        return self_test(cfg, BASE_DIR)

    from server import run

    # 托盘默认策略：明确指定则听从；否则读配置 notify.tray（默认 True）
    if args.no_tray:
        use_tray = False
    elif args.tray:
        use_tray = True
    else:
        use_tray = bool(cfg.get("notify", {}).get("tray", True))

    return run(cfg, BASE_DIR, use_tray=use_tray)


if __name__ == "__main__":
    sys.exit(main())
