# 疑难排查

按「症状」索引。大部分问题的答案在 `data\alert.log` 里。

---

## 排查的第一步永远是看日志

```
data\alert.log
```

或者双击 **`查看状态.bat`**，它会一次性告诉你：服务是否在跑、端口、已记录条数、
关键词、回调地址、自启是否已安装。

---

## 不弹窗

这是最常见的问题，按这个顺序查：

### 1. 先确认弹窗本身没问题

```bash
python run.py --test
```

不弹 → 问题在本机，跟隧道/服务商无关，继续往下看。
弹了 → 本机正常，问题在「消息有没有到」。

### 2. 看请求到底有没有到

```bash
ls data/raw/
```

- **有新文件** → 请求到了，问题在解析或筛选
- **没有新文件** → 请求没到，问题在隧道或服务商配置

### 3. 请求到了但没弹

打开 `data/raw/` 里最新的 `.json`，对照日志看：

| 日志内容 | 含义 | 处理 |
|---|---|---|
| `未命中关键词，跳过：xxx` | 解析成功，但标题不含关键词 | 改关键词；如果标题里明显有词却报这个，检查是否有全角/半角差异 |
| `已提醒过，跳过：xxx` | 去重库里有记录 | 正常行为。想重新测试用 `&test=1`，或删 `data/seen.db` |
| `payload 未解析出任何文章` | 字段结构不认识 | 见 [PROVIDERS.md](PROVIDERS.md#换服务商的步骤) |
| 什么都没记录 | 可能被 token 挡了 | 搜日志里的 `token 校验失败` |

### 4. 请求没到

按顺序查：

```bash
# a. 服务活着吗
curl "http://127.0.0.1:8765/hook?token=你的token"
```

**期待**：`{"ok": true, "note": "..."}`

- 连不上 → 服务没启动，或端口不对
- 返回 `401` → token 不对，检查 `secrets.local.json`

```bash
# b. 隧道活着吗
curl "https://你的隧道地址/hook?token=你的token"
```

- 连不上 → 隧道断了，重开 `python start_tunnel.py`
- 能连上但地址变了 → 更新服务商的 webhook 地址

```bash
# c. 服务商那边配置对吗
```

检查 webhook 地址是否**带了 `?token=`**、是否用 `https`、尾部没多余空格。

---

## 弹窗出现了但一闪就没 / 没注意到

调 `config.json`：

```json
"notify": {
  "popup_timeout": 0,        // 0 = 不自动关闭，必须手动点"知道了"
  "always_on_top": true
}
```

`popup_timeout` 默认是 60 秒。改成 0 就常驻，直到你处理。

---

## 弹窗没声音

1. 系统是否静音
2. `config.json` 里 `notify.sound` 是否为 `true`
3. 程序用的是 `winsound.MessageBeep`，某些系统主题下这个音效非常轻，几乎听不到

---

## 隧道地址每次重启都变

这是 **Cloudflare 免费快速隧道**（quick tunnel）的固有设计：每次启动分配新的
`*.trycloudflare.com` 随机域名。不是 bug，也没有办法把这个随机域名"买断"或"占住"。
Cloudflare 的产品逻辑就是：临时试用走免费随机域名，要固定地址就走命名隧道。

### 三条路

| 方案 | 结果 | 成本 |
|---|---|---|
| **接受它** | 每次重启后重开隧道 + 更新服务商地址 | 免费，麻烦 |
| **Tailscale Funnel** ⭐ | 地址永久固定，重启不用管 | 免费，需注册账号 |
| **Cloudflare 命名隧道** | 地址永久固定 | 需要一个域名（几块钱/年）+ Cloudflare 免费账号 |

### 推荐：Tailscale Funnel（不用买域名）

完整步骤见 [QUICKSTART.md 的「B. Tailscale Funnel」](QUICKSTART.md#b-tailscale-funnel固定地址推荐)。

一句话版本（全部在**管理员**终端里执行）：

```powershell
winget install --id Tailscale.Tailscale
& "C:\Program Files\Tailscale\tailscale.exe" up
python start_tunnel.py --mode funnel
```

拿到 `https://机器名.tailnet名.ts.net/hook?token=...`，填到监测服务后台，**从此不再变**。

**踩坑清单**（报错对号入座）：

| 报错 | 原因 | 解法 |
|---|---|---|
| `Funnel not available; nodeAttrs does not include "funnel"` | 后台没开 funnel 属性 | ACL policy 里加 `nodeAttrs`，见 QUICKSTART |
| `Funnel not available; HTTPS must be enabled` | 没开 HTTPS 证书 | <https://login.tailscale.com/admin/dns> 点 Enable HTTPS |
| `Access denied: this command must be run as administrator` | 没用管理员终端 | Win+X → 终端(管理员) |
| `Tailscale 尚未分配域名` | 没登录，或 MagicDNS 没开 | 先 `tailscale up`，再开 MagicDNS |
| `failed to get cert: rate limited` | Let's Encrypt 签证书太频繁 | 等 34 小时，别反复重试 |

> **为什么必须写 `--https=443`**：Funnel 只监听 **443 / 8443 / 10000** 三个端口，
> 而程序默认在 8765。脚本已经自动带上这个映射，手动敲命令时别漏。

### 备选：Cloudflare 命名隧道

需要一个托管在 Cloudflare 的域名。

```bash
cloudflared tunnel login
cloudflared tunnel create zongce
cloudflared tunnel route dns zongce alert.你的域名.com
cloudflared tunnel run --url http://127.0.0.1:8765 zongce
```

配好后地址固定为 `https://alert.你的域名.com/hook?token=...`，重启也不用改。

---

## 端口被占用 / 程序启动后没反应

### 症状

开机后托盘没有图标，`查看状态.bat` 说"服务未响应"。

### 检查

看程序目录下有没有 **`启动失败.txt`**：

```
时间：2026-11-17 18:29:40
端口：8765

端口 8765 无法监听（PermissionError: ...）。
最常见原因：已经有一个综测提醒在运行。
解决办法：右键点托盘图标 → 退出，然后重新启动；
或者改 config.json 里的 port 换一个端口。
```

### 处理

1. 右键点托盘图标 → 退出（关掉旧实例）
2. 如果托盘图标也没了，用任务管理器结束所有 `pythonw.exe`
3. 重启程序

或者换个端口：

```json
"port": 8766
```

> 早期版本遇到这个情况会**静默死掉**——用户只看到"开机后没图标"，没有任何线索。
> 现在会弹 Toast + 写 `启动失败.txt`。

---

## 电脑关机/休眠时会漏消息吗

**会。** 程序和隧道都在你电脑上，关机就停了。

不过：

- 监测服务通常会把文章记在自己的历史里，重新开机后可以去看
- 如果服务商在你上线后重推，去重库会让它**不重复提醒**
- 想绝对不漏，只能搬到云服务器上 7×24 跑

---

## 邮件收不到

1. **先查垃圾邮件**，把发件人加白名单
2. 确认 `config.json` 里 `email.enabled` 是 `true`
3. 确认 `secrets.local.json` 里 `email.password` 填的是**授权码**不是登录密码
4. 跑 `python run.py --test`，看日志里有没有 `邮件发送失败`

常见错误：

| 日志 | 原因 |
|---|---|
| `SMTPAuthenticationError: 535` | 授权码错，或没开启 SMTP 服务 |
| `TimeoutError` | 网络问题，或端口被防火墙拦 |
| `邮件已启用但缺少 username/password` | 凭据没读到，检查 `secrets.local.json` 位置 |

> 程序用纯地址作 `From`（不带中文显示名），因为带显示名更容易触发 QQ/163 的垃圾过滤。
> 如果还是进垃圾箱，把发件人加入白名单。

---

## `.bat` 文件双击闪一下就关

可能原因：

1. **换行被改成 LF**。`.bat` 必须是 **CRLF**，否则 `goto` 标签失效、脚本会乱跳。
   仓库已在 `.gitattributes` 里锁定 `*.bat text eol=crlf`，正常 clone 不会出问题。
2. **BOM**。文件开头不能有 UTF-8 BOM，否则第一行 `@echo off` 会变成乱码命令。
3. **找不到带 tkinter 的 Python**。脚本会自动探测（PATH → `py` 启动器 → 常见安装目录），
   全都没有时会打印安装指引并 `pause` 等你按任意键，不会秒退。

手动验证：

```bash
python -c "d=open('启动.bat','rb').read(); print('CRLF:', d.count(b'\r\n'), 'BOM:', d[:3]==b'\xef\xbb\xbf')"
```

如果只是想确认探测到的是哪个解释器：

```bash
_find_python.bat
```

（这个脚本单独运行不会启动程序，只做探测。）

---

## 提示找不到可用的 Python

先确认 tkinter 在不在——这是最常见的坑，很多人装 Python 时没勾 `tcl/tk`：

```bash
python -c "import tkinter"
```

- 无输出 = 正常
- `ModuleNotFoundError: No module named 'tkinter'` = 缺 tcl/tk，需要重装 Python 并勾选该组件

然后确认这个 `python` 就是脚本会用的那个：

```bash
where python
```

如果装了多个 Python，用 `py -0` 可以看到全部版本。脚本优先用 PATH 里第一个能 `import tkinter` 的。

> 想强制指定解释器：临时把目标 Python 目录放到 PATH 最前面，或用
> `安装开机自启.bat` 生成快捷方式后，右键属性里看到的 `目标` 就是实际使用的路径。

---

## 改了关键词不生效

改 `config.json` 里的 `keywords` 后**必须重启程序**——配置只在启动时读一次。

改完重启，`查看状态.bat` 会显示当前实际生效的关键词列表。

---

## `已提醒过，跳过` 但我想重新看一遍

去重库是 `data/seen.db`。三个办法：

1. **只想测一次** → 用 `&test=1`（本机调用，跳过去重和关键词）
2. **只删一条** → 用 SQLite 工具打开 `data/seen.db`，删掉对应行
3. **全部清空** → 删掉整个 `data/seen.db`，重启（**注意：所有历史文章都会重新提醒一次**）

---

## 托盘图标不见了

1. 点任务栏的 `^` 展开隐藏图标，可能被折叠了
2. 检查 `config.json` 里 `notify.tray` 是否为 `true`
3. 托盘组件没装：`pip install pystray Pillow`
4. 程序崩了 → 看 `data\alert.log` 末尾

> `pythonw.exe` 没有控制台，崩溃时会静默消失。程序里装了全局异常钩子，
> 崩溃信息一定会在 `alert.log` 里，这是唯一的线索来源。

---

## 我还是搞不定

贴 issue 时请附上：

1. `data\alert.log` 最后 50 行
2. `查看状态.bat` 的输出
3. `data\raw\` 里最新那份 JSON 的**字段结构**（标题内容请替换成占位文本）
4. Python 版本（`python --version`）和 Windows 版本

**不要**贴 `secrets.local.json` 的内容。
