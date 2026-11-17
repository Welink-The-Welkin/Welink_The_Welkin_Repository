# 安全设计

这个程序会经隧道暴露到公网，所以做了几层防护。本文说明**怎么做**、**为什么这么做**，
以及**你需要自己守住什么**。

---

## 威胁模型

先说清楚在防什么：

| 威胁 | 后果 | 是否已防 |
|---|---|---|
| 别人拿到隧道地址，伪造通知 | 你屏幕上弹任意内容（骚扰、钓鱼） | ✅ token 鉴权 |
| 别人拿到地址读 `/health` | 窥探你的关键词、使用量 | ✅ 需 token |
| 日志被贴到网上求助 | 泄露回调地址/token | ✅ token 打码 |
| 仓库被公开/分享 | 泄露邮箱授权码，别人能登你邮箱 | ✅ 凭据分离 + gitignore |
| 提PR/改代码时看错换行 | `.bat` 坏掉 | ⚠ 靠人工注意 |
| 本机被入侵 | 一切皆失 | ❌ 超出范围 |

**不在防护范围内**：本机已被完全控制。这种情况下任何本地程序都守不住。

---

## 1. Token 鉴权

### 做法

`/hook` 和 `/health` 都要求 token，支持两种传递方式：

```
POST /hook?token=xxx
POST /hook  +  Header:  X-Token: xxx
```

比较用 `hmac.compare_digest`（定长比较），避免攻击者通过响应时间逐字节猜出 token。

### 为什么 token 在 URL query 里

这是妥协：多数 webhook 服务商只接受填一个 URL，不支持自定义 header。
所以 token 只能放 query。

**代价**：它会进 Cloudflare 的访问日志、你的本地日志、浏览器历史。
所以做了下一条的补偿。

### 补偿措施

- **日志打码**：启动横幅只显示 `f3***...***Nf`，搜索日志/贴日志求助不会泄露完整 token
- **`/health` 不回显 token**：响应体里只有关键词、已记录条数、邮件开关，没有任何凭据
- **生成足够随机**：`--gen-token` 用 `secrets.token_urlsafe(24)`，约 192 位熵，不可枚举

> ⚠️ **不要用生日、学号、`我的学校+年份` 这类可猜的值当 token。**
> 早期版本用过一串基于生日的数字，这是明显的安全隐患——它可被枚举。

---

## 2. `/health` 也要 token

### 为什么

早期版本里 `/health` 是完全公开的。这意味着任何拿到隧道地址的人都能：

- 读到你的关键词列表（知道你关心什么）
- 读到 `seen` 计数（知道你在用、用了多久）
- 确认这个地址确实是个"综测提醒"服务（精准投递骚扰）

更糟的是，某些实现会把回调地址打印在 `/health` 里——那等于把 token 直接送人。

### 现在

```
GET /health            → 401 {"ok": false, "error": "invalid_token"}
GET /health?token=xxx  → 200 {"ok": true, "keywords": [...], "seen": 12, ...}
```

响应体**不含** token、不含回调地址、不含文件路径。

### 如果确实想关掉

```json
"health_requires_token": false
```

**不建议**。关掉后等于公开上表所有信息。

---

## 3. `&test=1` 仅限本机

### 为什么单独讲

`&test=1` 会**跳过关键词筛选，放行全部文章**。它是用来验证通路的，但副作用很大：

如果它对公网开放，任何拿到隧道地址的人发一条任意标题的文章过来，你屏幕上就会弹出来。
这就是一个现成的定向骚扰工具。

### 现在怎么做

```json
"test_mode_allow_remote": false
```

- 本机（`127.0.0.1`）调 `&test=1` → 正常放行
- 公网调 `&test=1` → `403 test_mode_local_only`
- 公网调**不带** `test=1` → 正常按关键词筛选（这是生产路径，应该允许）

### 一个容易踩的坑

服务只监听 `127.0.0.1`，经隧道进来的请求 `client_address` **永远是 `127.0.0.1`**。
所以直接判断 `client_address` 等于没判断。

必须看 `CF-Connecting-IP` 头（Cloudflare 会设置真实客户端 IP）。
代码里优先读这个头，没有才退回 `client_address`。

> 这个细节是"仅限本机"能否真正生效的关键。如果你换掉 Cloudflare 用别的隧道，
> 记得把对应的转发头（如 `X-Forwarded-For`）也加进去。

---

## 4. 凭据与配置分离

### 结构

```
config.json           ← 可提交、可分享。只有关键词、端口、开关
secrets.local.json    ← 绝不提交。token、邮箱授权码
secrets.example.json  ← 模板
.gitignore            ← 排除 secrets.local.json / data/ / __pycache__/
```

加载优先级：`默认值 < config.json < secrets.local.json < 环境变量`

### 为什么这么设计

早期版本把真实 token 和 QQ 邮箱 SMTP 授权码**明文写在 `config.json` 里**，
而且项目目录**没有 `.gitignore`**。一旦推到 GitHub 或发给同学"帮我看看"，
授权码就等于公开——**别人能直接登录你的 QQ 邮箱发信**。

拆分后，`config.json` 可以放心分享。

### 环境变量也支持

不想在文件里落盘的话：

```bash
ZONGCE_TOKEN=xxx ZONGCE_EMAIL_PASSWORD=yyy python run.py
```

优先级最高，会覆盖两个文件里的值。

---

## 5. 错误响应不泄露内部信息

500 错误只返回：

```json
{"ok": false, "error": "internal_error"}
```

不回显异常原文。原因：异常信息里经常含本地文件路径、数据库路径、库的内部状态，
这些对攻击者有价值（比如知道你的目录结构、用的是哪个库）。

完整堆栈只写进 `data/alert.log`。

---

## 6. 请求体大小限制

```python
MAX_BODY = 2 * 1024 * 1024  # 2MB
```

超过就返回 `413 payload_too_large`。防止有人往你的 2MB 内存里灌 2GB 数据。

---

## 7. 监听地址

```json
"host": "127.0.0.1"
```

**不要改成 `0.0.0.0`**。那会把服务直接暴露到局域网，而且没有 HTTPS——
token 会在局域网内明文传输。

公网入口永远走隧道（隧道负责 HTTPS 终止）。

### 隧道选型对暴露面的影响

| | Cloudflare 快速隧道 | Tailscale Funnel |
|---|---|---|
| 地址可预测性 | 随机单词，**难猜** | `机器名.tailnet名.ts.net`，**比较好猜** |
| 边沿身份验证 | 无 | 无 |
| token 的作用 | 主要防线 | **唯一防线** |

> ⚠ 从快速隧道换到 Funnel，等于把"地址难猜"这层弱保护也去掉了。
> `机器名` 和 `tailnet名` 在 Tailscale 里不算秘密，别人可能拼得出来。
> 所以**用 Funnel 时 token 必须足够强**（`--gen-token` 生成的 32 位随机串就够）。
> 别用 `abc123`、别用公众号名、别用生日。

---

## 你需要自己守住的事

程序能做的防护就上面这些。以下几件事只能靠你：

### 1. 不要用可猜的 token

```bash
python run.py --gen-token   # ✅ 用这个
```

### 2. 不要提交 `secrets.local.json`

`.gitignore` 已经排除了，但如果你用 `git add -f` 强制添加，就失效了。

提交前自查：

```bash
git status --short
# 确认列表里没有 secrets.local.json、没有 data/
```

### 3. 贴日志求助前先扫一眼

日志里的 token 已打码，但 `data/raw/*.json` 里是**真实的文章标题和链接**。
要贴出来时，把标题内容替换成占位文本。

### 4. token 泄露了怎么办

```bash
python run.py --gen-token   # 生成新 token
# 重启程序
python start_tunnel.py      # 拿新地址（token 已拼进去）
# 把新地址更新到监测服务
```

三步就换干净了。旧 token 立即失效。

### 5. 定期看看有没有异常

```bash
python check.py
```

或者看 `data/alert.log` 里有没有大量 `token 校验失败`——那说明有人在试你的地址。

---

## 已知的取舍（不是漏洞，但你该知道）

| 取舍 | 原因 |
|---|---|
| token 在 URL 里 | 服务商只接受填 URL，没法放 header |
| 快速隧道地址每次重启都变 | Cloudflare 免费快速隧道的固有限制，换个角度也是"地址不固定"的弱保护 |
| Funnel 地址固定且可猜 | 换来了"重启不用改后台"的便利，代价是 token 成为唯一防线（见第 7 节的表） |
| 隧道不可用时没有重试队列 | 本机停机期间推送会丢；监测服务侧通常有历史记录可查 |
| 没有速率限制 | 单用户本机工具，加限流收益不大；靠 token 挡外部请求 |
