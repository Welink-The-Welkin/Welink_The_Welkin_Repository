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

`secrets.local.json` 不存在时程序仍可启动，但在公开回调端点前须先设置 token。仅在还没有 token 时运行 `python run.py --gen-token`；已有 token 请沿用。邮箱凭据的字段可参考 `secrets.example.json`，不要用模板覆盖现有凭据。

---

## 所有订阅号的批提醒与本机待看文章

`"batch_all_accounts": true`（默认开启）：不需要列名单，今后新增的订阅号也生效。已解析的正式文章全部进入本机收件箱；同一批中，关键词命中的仍逐篇立即安排提醒，其余新文章按公众号合并提醒一次。只用已开启的弹窗或邮件渠道，不会自动开启邮件、登录微信、抓取正文或新增网络入口。

托盘右键 → **待看文章**：可刷新、打开所选原文，或者主动标记已看。弹窗消失、邮件发送成功、打开原文都不等于已看。托盘 → **查看状态** 可看未读数、待派送/最终失败数、最近正式投递与解析异常时间。首次使用是空清单，不会自动把历史原始请求再弹一遍。

重复投递不会增加新未读或正常情况下重复弹窗。发送失败按渠道有限重试（最多三次明确失败）；退出重启会恢复未完成任务。如果发送后、写回执前恰好中断，可能多提醒一次。关掉 `batch_all_accounts` 只影响**后续**未命中的批提醒，文章仍入箱；已经排队的任务不因此取消。上游没有投递的文章不可能出现在本机收件箱。

## 关键词

```json
"keywords": ["综测", "综合素质测评", "加分", "第二课堂", "志愿时长", "德育分", "报名"]
```

命中**任意一个**就会提醒。调优建议：

| 症状 | 做法 |
|---|---|
| 太吵，无关文章也弹 | 删掉太宽的词（如「报名」「活动」） |
| 漏掉真正关心的 | 加上「招募」「征集」「选拔」「公示」 |
| 想扩大匹配范围，且服务商推送中带有效摘要 | 把 `match_field` 改成 `title_and_summary` |

```json
"match_field": "title"
```

- `title`（默认）：只匹配标题。
- `title_and_summary`：匹配标题和推送中的非空摘要（如 `summary`、`digest`）。摘要缺失、是 `null`、为空或只有空白时，效果与只匹配标题相同。
- **摘要不是全文。** 程序不会访问文章链接获取正文，也不会把推送中的独立正文字段当作摘要。

在「上理大学生」的一批 FeedWe 真实投递中，两篇文章的 `summary` 都为空；这个样本中开启摘要模式不会多匹配任何内容。FeedWe 后台的「发送测试消息」即使带示例摘要，也不能证明真实投递会带摘要。要确认自己的订阅是否提供摘要，应查看实际发文后收到的 `data/raw/` 记录。

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

邮件默认关闭，和桌面弹窗分别设置。启用后，程序会把提醒发到指定邮箱，手机登录该邮箱就能查看。

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

保存后可运行 `python run.py --test`：若邮件已启用，自检会真实发送一封测试邮件。检查自检结果和邮箱收件箱；已在运行的程序需退出并重新启动，才会使用新配置。

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

`data/seen.db` 保留旧版关键词去重记录。新收件箱和未完成派送保存在同目录的 `inbox.db`，与 `data/raw/` 的保留期限无关。不要删除这两个库，也不要把含文章链接的库或原始推送公开分享。收件箱写入失败时，程序仍尽力发送原来的提醒，并向上游返回 503；上游是否重投由其决定。

---

## 日志级别

```json
"log_level": "INFO"
```

| 值 | 什么时候用 |
|---|---|
| `DEBUG` | 在 `INFO` 基础上额外记录每条 HTTP 请求（来源 IP、方法、路径、状态码）。怀疑「请求根本没到」时开 |
| `INFO` | **默认**，记录正式投递的解析数、新收文章数、关键词提醒数及批提醒数 |
| `WARNING` | 只看异常 |
| `ERROR` | 只看失败 |

日志写在 `data/alert.log`，托盘菜单「打开日志」可以直接定位到它。

> 改完要重启程序才生效——配置只在启动时读一次。

**排查思路对照**：

| 现象 | 看什么 |
|---|---|
| 弹窗没出现 | 先看托盘「查看状态」的最近正式投递、待派送和失败数，再到「待看文章」找该篇；检查弹窗是否已开启 |
| 换了个关键词还是不弹 | 核对待看清单的实际标题；用摘要模式时，再到 `data/raw/` 确认是否带有效摘要 |
| 完全没有任何记录 | 开 `DEBUG`，看有没有请求进来。没有就是隧道或回调地址的问题，见 [TROUBLESHOOTING](TROUBLESHOOTING.md) |
| 同一条提醒了两次 | 检查是否为不同文章地址、入库失败后上游重投，或在发送后、记录回执前重启 |

---

## 鉴权与测试模式

```json
"health_requires_token": true,
"test_mode_allow_remote": false
```

| 字段 | 默认 | 说明 |
|---|---|---|
| `health_requires_token` | `true` | `/health` 也要 token。因为它经隧道后公网可访问，关掉等于泄露内部信息 |
| `test_mode_allow_remote` | `false` | 限制远程请求使用 `&test=1`；正常订阅和 FeedWe 的「发送测试消息」都不需要开启它 |

建议保留这两项的默认值，用普通回调地址接收投递。

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
| 查看状态 | 本机显示端口、待看数、最近投递、异常及派送状态 |
| 待看文章 | 本机查看未读、手动打开原文、标记已看 |
| 在浏览器中查看状态 | 打开 `/health`（自动带 token） |
| 打开日志 | 打开 `data\alert.log` |
| 打开回调地址文件 | 打开 `data\callback-url.txt` |
| 帮助 | 展开问题子菜单，按需选择「第一次使用：怎样收到第一篇文章？」「测试成功，为什么待看还是空的？」或「电脑重启后，要重新设置吗？」等；六个问题的详细步骤见[快速开始](QUICKSTART.md) |
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
