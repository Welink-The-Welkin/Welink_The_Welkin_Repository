# 快速开始

从零到收到第一条真实提醒，共五步。全程约 15 分钟。

---

## 前置条件

- Windows 10 / 11
- Python 3.8+（[下载](https://www.python.org/downloads/)）
- 一个邮箱（用于注册监测服务和接收提醒，QQ 邮箱即可）

> **安装 Python 时务必勾选这两项**：
> - `Add python.exe to PATH` —— 否则双击 `.bat` 时找不到解释器
> - `tcl/tk and IDLE` —— 弹窗靠 tkinter 绘制，缺了它程序无法提醒
>
> 检查是否就绪：命令行执行 `python -c "import tkinter"`，没有任何输出就是正常的。

**关于 `.bat` 脚本**：双击即用，不需要手动配环境。脚本会按以下顺序自动找解释器，
找到的第一个能 `import tkinter` 的即被采用：

1. PATH 中的 `python`
2. Windows 自带的 `py` 启动器
3. `%LOCALAPPDATA%\Programs\Python\Python31x` 等常见安装位置

都找不到时会明确提示去哪装、勾什么，而不是闪一下就消失。

---

## 第 1 步：安装并设置回调密码

```bash
pip install -e ".[tray,win]"
python run.py --gen-token
```

第二条命令会生成一串高强度随机 token 并写入 `secrets.local.json`。

**为什么要 token**：这个程序会经隧道暴露到公网，token 就是门锁。没有它，任何知道地址的人都能往你屏幕上弹消息。

**为什么写在 `secrets.local.json` 而不是 `config.json`**：
`config.json` 是"可以给人看、可以传到 GitHub"的配置文件，里面只放非敏感设置；
token 和邮箱授权码一律放 `secrets.local.json`，该文件已被 `.gitignore` 排除。

> 顺便一提：如果你要把项目分享给别人，直接把 `secrets.local.json` 删掉再打包即可。

---

## 第 2 步：验证弹窗和声音

```bash
python run.py --test
```

或者双击 **`自检.bat`**。

**期望结果**：屏幕中央弹出一个红色大窗口，同时听到提示音。

| 现象 | 说明 |
|---|---|
| 看到弹窗 + 听到声音 | 通知通路正常，继续下一步 |
| 没弹窗 | 看 `data\alert.log` 里的报错 |
| 弹窗但没有声音 | 检查系统是否静音，或 `config.json` 里 `notify.sound` 是否为 true |

---

## 第 3 步：注册监测服务并添加公众号

微信公众号没有公开订阅接口，必须借助第三方服务来"盯号"。本项目默认用 [FeedWe](https://feedwe.top/auth/register)
作为示例，**但你可以用任何支持 webhook 的服务**（见 [PROVIDERS.md](PROVIDERS.md)）。

1. 打开监测服务网站，用邮箱注册并验证
2. 进入「订阅管理」，搜索并添加要盯的公众号，例如：
   - `上理大学生`（示例）
   - 你所在学院的团委号（学院号也经常发加分活动）
3. 给重点的号选最快档位（通常是 1 分钟档）

> 搜不到某个号时，试试完整全名。仍搜不到可在服务商页面点「反馈」让他们补充。

---

## 第 4 步：开隧道，拿到公网回调地址

监测服务在云端，它需要一个公网地址才能把消息推到你电脑。用 Cloudflare 免费隧道 :

1. 重新生成隧道并打印回调地址：

   ```bash
   python start_tunnel.py
   ```

2. 第一次运行会提示没装 `cloudflared`，按提示安装：

   ```
   winget install --id Cloudflare.cloudflared
   ```

3. 装完重新运行，脚本会自动打印并保存地址：

   ```
   https://一串随机单词.trycloudflare.com/hook?token=你的token
   ```

**把这个地址复制下来。**

> 隧道窗口要一直开着。关掉 = 断开 = 收不到推送。

---

## 第 5 步：填到监测服务，发测试消息

1. 在监测服务里找到「配置推送通知」→ 选 **自定义 Webhook**
2. 把上一步的完整地址粘进去（**必须带 `?token=`**）
3. 点「发送测试消息」
4. 回到电脑，应该立刻弹窗

### 如果测试消息没弹窗——这是正常的

服务商的测试消息标题通常是 `Test article title` 这类占位文本，**不含你的关键词**，
所以会被关键词筛选正确拦下。这是设计如此，不是故障。

想验证通路，用**测试模式**（加 `&test=1` 跳过关键词筛选）：

```bash
# 在本机命令行执行（推荐，见下方说明）
curl -X POST "http://127.0.0.1:8765/hook?token=你的token&test=1" ^
  -H "Content-Type: application/json" ^
  -d "{\"articles\":[{\"title\":\"测试综测通知\",\"url\":\"https://mp.weixin.qq.com/\"}]}"
```

> ⚠ **`&test=1` 默认只允许本机调用。** 它会放行全部文章；
> 如果对公网开放，任何拿到隧道地址的人都能让你屏幕上弹任意通知。
> 从隧道（公网）来的 `&test=1` 请求会返回 `403 test_mode_local_only`。
>
> 确实需要放行公网测试（不推荐），把 `config.json` 里 `test_mode_allow_remote` 改成 `true`。

### 只想知道服务活着没

```bash
curl "http://127.0.0.1:8765/hook?token=你的token"
```

会返回 `{"ok": true, "note": "本端点只接受 POST 投递；GET 仅用于连通性探测，不会触发提醒"}`。
**GET 不会触发弹窗**，别用它判断"提醒是否正常"。

---

## 完成之后

建议接着做：

1. **配置邮箱** —— 手机在外面也能收到提醒，见 [CONFIG.md 的邮件章节](CONFIG.md#邮件通知)
2. **设置开机自启** —— 静默后台运行，不弹终端窗口，见 [CONFIG.md 的自启章节](CONFIG.md#开机自启)
3. **调关键词** —— 嫌吵删掉太宽的词，怕漏加上「招募」「征集」，见 [CONFIG.md](CONFIG.md#关键词)

---

## 每次重启电脑后要做的事

隧道地址每次重启都会变，所以：

1. 程序会随开机自启自动运行（如果装了自启）
2. **需要手动重开隧道**：`python start_tunnel.py`
3. 把新地址粘到监测服务的 Webhook 设置里

实测下这是当前架构最麻烦的一环。想彻底解决，见 [TROUBLESHOOTING.md 的「隧道地址每次重启都变」](TROUBLESHOOTING.md#隧道地址每次重启都变)。
