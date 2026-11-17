# 配置说明

配置文件分两个，**这是有意的设计**：

| 文件 | 能否分享 | 放什么 |
|---|---|---|
| `config.json` | ✅ 可以提交、可以发给别人 | 关键词、端口、开关等非敏感设置 |
| `secrets.local.json` | ❌ 绝不能提交 | token、邮箱授权码 |

加载优先级（后者覆盖前者）：

```
内置默认值  <  config.json  <  secrets.local.json  <  环境变量
```

`secrets.local.json` 不存在时程序照常运行，只是没有凭据。
模板见 `secrets.example.json`，复制改名即可；或者直接 `python run.py --gen-token` 自动生成。

---

## 关键词

```json
"keywords": ["综测", "综合素质测评", "加分", "第二课堂", "志愿时长", "德育分", "报名"]
```

命中**任意一个**就会提醒。调优建议：

| 症状 | 做法 |
|---|---|
| 太吵，无关文章也弹 | 删掉太宽的词（如「报名」「活动」） |
| 漏掉真正关心的 | 加上「招募」「征集」「选拔」「公示」 |
| 想更宽松 | 把 `match_field` 改成 `title_and_summary`，连摘要一起匹配 |

```json
"match_field": "title"   // title = 只看标题（推荐，噪音少）
                          // title_and_summary = 标题 + 摘要
```

**匹配规则**：大小写不敏感；只要关键词作为子串出现即可，不做分词。
所以「加分」会命中「加分活动」也会命中「不加分」——如果误报多，换更长的词。

---

## 端口与监听

```json
"port": 8765,
"host": "127.0.0.1"
```

- **不要改 `host`**。保持 `127.0.0.1` 意味着只有本机能直连，公网入口交给隧道。
  改成 `0.0.0.0` 会把服务直接暴露到局域网/公网，且没有 HTTPS。
- 端口冲突时程序会在程序目录生成 `启动失败.txt` 说明原因，改个端口重启即可。

也可以用环境变量临时覆盖：`ZONGCE_PORT=9000 python run.py`

---

## 弹窗

```json
"notify": {
  "popup": true,
  "sound": true,
  "popup_timeout": 60,
  "always_on_top": true,
  "tray": true
}
```

| 字段 | 说明 |
|---|---|
| `popup` | 关掉就只剩邮件提醒 |
| `sound` | 弹窗时响系统提示音 |
| `popup_timeout` | 自动关闭秒数，`0` 表示不自动关 |
| `always_on_top` | 置顶显示，防止被其他窗口压住 |
| `tray` | 托盘图标。关掉后静默运行就没有入口了，需谨慎 |

多条提醒会**排队依次显示**，不会互相覆盖——避免一次推来三篇时只看得到最后一篇。

---

## 邮件通知

程序会发一封 HTML 邮件到你手机，出门在外也能收到。

### 拿授权码

1. 登录 https://mail.qq.com
2. 设置 → 账号 → 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」
3. 开启「IMAP/SMTP服务」，按提示验证后会给你一串**授权码**
4. **授权码不是你的 QQ 密码**，是单独的一串字母

### 填进 secrets.local.json

```json
{
  "email": {
    "username": "你的QQ号@qq.com",
    "password": "刚才拿到的授权码",
    "to": "你的QQ号@qq.com"
  }
}
```

### 在 config.json 里只开开关

```json
"email": {
  "enabled": true,
  "smtp_host": "smtp.qq.com",
  "smtp_port": 465,
  "use_ssl": true
}
```

改完跑一次 `python run.py --test`，检查收件箱。

> 没收到先查**垃圾邮件**，把发件人加入白名单。
> 程序用纯地址作 `From`（不带中文显示名），因为带显示名容易触发 QQ/163 的垃圾过滤。

用其他邮箱时改 `smtp_host` / `smtp_port` / `use_ssl` 即可，例如 163：`smtp.163.com` + 465 + SSL。

---

## 存储

```json
"storage": {
  "save_raw_payload": true,
  "keep_raw_days": 7
}
```

| 字段 | 说明 |
|---|---|
| `save_raw_payload` | 把收到的原始 JSON 存到 `data/raw/`。**排障强烈建议开着** |
| `keep_raw_days` | 原始文件保留天数，超期自动清理 |
| `db_path` | 去重数据库路径，默认 `data/seen.db` |
| `raw_dir` | 原始 payload 目录，默认 `data/raw/` |

`data/seen.db` 是 SQLite 去重库，**删掉它会导致所有历史文章重新提醒一次**。

---

## 日志级别

```json
"log_level": "INFO"
```

| 值 | 什么时候用 |
|---|---|
| `DEBUG` | 在 `INFO` 基础上额外记录每条 HTTP 请求（来源 IP、方法、路径、状态码）。怀疑「请求根本没到」时开 |
| `INFO` | **默认**，日常使用。判定结果都在这一级：命中关键词、未命中被跳过、重复已提醒、测试模式放行 |
| `WARNING` | 只看异常 |
| `ERROR` | 只看失败 |

日志写在 `data/alert.log`，托盘菜单「打开日志」可以直接定位到它。

> 改完要重启程序才生效——配置只在启动时读一次。

**排查思路对照**：

| 现象 | 看什么 |
|---|---|
| 弹窗没出现 | 日志里有没有 `未命中关键词，跳过：<标题>` —— 有就说明请求到了，是关键词没匹配上 |
| 换了个关键词还是不弹 | 同上，重点看日志里打印的实际标题和摘要 |
| 完全没有任何记录 | 开 `DEBUG`，看有没有请求进来。没有就是隧道或回调地址的问题，见 [TROUBLESHOOTING](TROUBLESHOOTING.md) |
| 同一条提醒了两次 | 说明 `data/seen.db` 被删过，或文章 URL 变了 |

---

## 鉴权与测试模式

```json
"health_requires_token": true,
"test_mode_allow_remote": false
```

| 字段 | 默认 | 说明 |
|---|---|---|
| `health_requires_token` | `true` | `/health` 也要 token。因为它经隧道后公网可访问，关掉等于泄露内部信息 |
| `test_mode_allow_remote` | `false` | `&test=1` 仅限本机。改成 `true` 会让隧道地址持有者也能全量放行 |

**不要轻易关这两个。**

---

## 环境变量

优先级最高，适合临时覆盖或不想写进文件：

| 变量 | 覆盖 |
|---|---|
| `ZONGCE_TOKEN` | `token` |
| `ZONGCE_EMAIL_USERNAME` | `email.username` |
| `ZONGCE_EMAIL_PASSWORD` | `email.password` |
| `ZONGCE_PORT` | `port` |

---

## 开机自启

双击 **`安装开机自启.bat`**，输入 `Y` 确认。

它会在 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` 下创建一个
指向 `pythonw.exe` 的快捷方式，参数为 `run.py --tray`。

**为什么用 `pythonw.exe`**：这是 Python 的 GUI 版解释器，**天生没有控制台窗口**，
比任何"隐藏窗口"的 hack 都可靠。开机后你只会看到托盘区多一个红底对勾图标。

### 托盘菜单

| 菜单项 | 作用 |
|---|---|
| 查看状态 | 气泡显示端口、已记录文章数、邮件与鉴权状态 |
| 在浏览器中查看状态 | 打开 `/health`（自动带 token） |
| 打开日志 | 打开 `data\alert.log` |
| 打开回调地址文件 | 打开 `data\callback-url.txt` |
| 重启后要做什么？ | 提醒你更新隧道地址的步骤 |
| 退出 | 关掉程序 |

### 取消自启

双击 **`取消开机自启.bat`**。

### 为什么崩溃了看不到任何提示

`pythonw.exe` 没有 stdout，未捕获异常会静默消失。所以程序里装了全局异常钩子
（`sys.excepthook` + `threading.excepthook`），崩溃信息会写进 `data\alert.log`。
**出问题第一件事就是看这个日志。**

---

## 命令行参数

```bash
python run.py                  # 正常启动（带托盘）
python run.py --tray           # 强制显示托盘
python run.py --no-tray        # 不显示托盘（在终端里调试更清爽）
python run.py --test           # 发一条测试提醒
python run.py --gen-token      # 生成新 token 写入 secrets.local.json
python run.py --config X.json  # 用指定配置文件
```

其他脚本：

```bash
python check.py          # 一键查看运行状态（等同「查看状态.bat」）
python start_tunnel.py   # 开隧道并打印回调地址
python startup.py status # 查看自启安装详情
python startup.py install|uninstall
```
