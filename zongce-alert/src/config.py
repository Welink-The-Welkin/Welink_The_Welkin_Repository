"""配置加载。

分层优先级（后者覆盖前者）：
    DEFAULT_CONFIG  <  config.json  <  secrets.local.json  <  环境变量

为什么要拆出 secrets.local.json：
config.json 是"可以给人看、可以提交进仓库"的文件，只放非敏感设置。
token 和邮箱授权码放 secrets.local.json，该文件已被 .gitignore 排除。
这样即使整个项目被推到 GitHub 或被发给别人，也不会泄露凭据。

约定：配置文件缺失 / 损坏时一律回退到默认值，绝不让程序因配置问题启动失败。
"""
import copy
import json
import logging
import os
import secrets as _secrets
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "综测",
    "综合素质测评",
    "加分",
    "第二课堂",
    "志愿时长",
    "德育分",
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "port": 8765,
    "host": "127.0.0.1",
    # webhook 鉴权：FeedWe 填回调地址时带在 query 里，如 http://xxx/hook?token=abc
    # 真实值放 secrets.local.json 或环境变量 ZONGCE_TOKEN
    "token": "",
    "keywords": DEFAULT_KEYWORDS,
    "match_field": "title",  # title | title_and_summary
    "batch_all_accounts": True,  # 无需维护公众号名单；仅关闭未命中时的批提醒
    "notify": {
        "popup": True,
        "sound": True,
        "toast_fallback": True,
        "popup_timeout": 60,       # 秒，0 表示不自动关。给足时间注意
        "always_on_top": True,
        "tray": True,              # 系统托盘图标（静默运行时的主要入口）
    },
    "email": {
        "enabled": False,
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "use_ssl": True,
        "username": "",       # 完整邮箱，如 123456@qq.com
        "password": "",       # QQ邮箱授权码，不是登录密码
        "to": "",             # 收件人，留空则发给 username
    },
    "storage": {
        "db_path": "",        # 空则用程序目录下 data/seen.db
        "save_raw_payload": True,
        "raw_dir": "",        # 空则用程序目录下 data/raw
        "keep_raw_days": 7,
    },
    # /health 是否需要 token。默认 True——它经隧道后是公网可访问的。
    "health_requires_token": True,
    # 是否允许非本机来源使用 ?test=1（放行全部文章）。默认 False，只信本机。
    "test_mode_allow_remote": False,
    "log_level": "INFO",
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    """读一个 JSON 对象文件；任何异常都返回 None 并记日志。"""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        log.warning("配置文件读取失败，已忽略：%s (%s)", path, e)
        return None
    if not isinstance(data, dict):
        log.warning("配置文件顶层不是对象，已忽略：%s", path)
        return None
    return data


def mask_secret(value: str) -> str:
    """把凭据打码，用于日志和状态展示。

    只保留首尾各 2 个字符，短值直接全遮。
    """
    if not isinstance(value, str) or not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def generate_token(nbytes: int = 24) -> str:
    """生成一个高强度随机 token（URL 安全字符）。"""
    return _secrets.token_urlsafe(nbytes)


def secrets_path_for(config_path: str) -> str:
    """secrets.local.json 与 config.json 同目录。"""
    return os.path.join(
        os.path.dirname(os.path.abspath(config_path)), "secrets.local.json"
    )


def load_config(
    path: str,
    secrets_path: Optional[str] = None,
    use_env: bool = True,
) -> Dict[str, Any]:
    """加载配置。

    path          主配置（可安全提交）
    secrets_path  敏感配置，默认与 path 同目录的 secrets.local.json
    use_env       是否允许环境变量覆盖（测试里关掉，避免受宿主环境影响）
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    user_cfg = _read_json(path)
    if user_cfg is not None:
        cfg = _deep_merge(cfg, user_cfg)
        _warn_inline_secrets(path, user_cfg)

    if secrets_path is None and path:
        secrets_path = secrets_path_for(path)
    secret_cfg = _read_json(secrets_path)
    if secret_cfg is not None:
        cfg = _deep_merge(cfg, secret_cfg)

    if use_env:
        _apply_env(cfg)

    return cfg


def _apply_env(cfg: Dict[str, Any]) -> None:
    """环境变量覆盖（优先级最高）。"""
    if os.environ.get("ZONGCE_TOKEN"):
        cfg["token"] = os.environ["ZONGCE_TOKEN"]
    if os.environ.get("ZONGCE_EMAIL_PASSWORD"):
        cfg.setdefault("email", {})["password"] = os.environ["ZONGCE_EMAIL_PASSWORD"]
    if os.environ.get("ZONGCE_EMAIL_USERNAME"):
        cfg.setdefault("email", {})["username"] = os.environ["ZONGCE_EMAIL_USERNAME"]
    if os.environ.get("ZONGCE_PORT"):
        try:
            cfg["port"] = int(os.environ["ZONGCE_PORT"])
        except ValueError:
            pass


def _warn_inline_secrets(path: str, user_cfg: Dict[str, Any]) -> None:
    """如果主配置里出现凭据，提醒用户挪到 secrets.local.json。"""
    if (user_cfg.get("token") or "").strip():
        log.warning(
            "config.json 里写了明文 token，建议挪到 secrets.local.json：%s", path
        )
    email = user_cfg.get("email")
    if isinstance(email, dict) and (email.get("password") or "").strip():
        log.warning(
            "config.json 里写了明文邮箱授权码，建议挪到 secrets.local.json：%s", path
        )


def validate(cfg: Dict[str, Any]) -> list:
    """启动时校验关键配置，返回问题清单（空列表表示没问题）。

    只报"会导致功能不可用或存在风险"的问题，不抛异常——
    由调用方决定是警告还是拒绝启动。
    """
    problems = []
    port = cfg.get("port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        problems.append("port 不是合法端口号：%r" % (port,))

    if not (cfg.get("token") or "").strip():
        problems.append(
            "token 为空——任何人都能往 /hook 发消息触发弹窗。"
            "请在 secrets.local.json 里设置 token，或运行 "
            "python run.py --gen-token 自动生成"
        )

    kw = cfg.get("keywords")
    if not isinstance(kw, list) or not [
        k for k in kw if isinstance(k, str) and k.strip()
    ]:
        problems.append("keywords 为空——没有关键词即时提醒；批提醒取决于 batch_all_accounts")

    email = cfg.get("email") or {}
    if email.get("enabled"):
        if not (email.get("username") or "").strip():
            problems.append("邮件已启用但 username 为空")
        if not (email.get("password") or "").strip():
            problems.append("邮件已启用但 password（授权码）为空")

    return problems
