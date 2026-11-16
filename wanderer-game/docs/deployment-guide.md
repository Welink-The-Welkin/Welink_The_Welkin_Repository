# 风起异途部署指南

本指南说明如何将《风起异途》部署为可公开访问的 HTTPS 网站，并让访问者在不安装 Python、GPT-SoVITS、模型权重或参考音频的情况下使用自由对话与训练音色。

- GitCode 仓库：<https://gitcode.com/IanElseWhere/Welink_The_Welkin_Repository>
- 作品展览馆：<https://gallery.developer.huaweicloud.com/gallery/007342752f000000>

项目包含 FastAPI 后端和静态前端，必须部署为 Python Web Service 或容器服务，不能只上传到静态网页托管。

## 一、部署边界

线上体验由三个彼此独立的部分组成：

1. **网站服务**：运行本仓库中的 FastAPI 后端和前端，负责剧情、会话、模型代理与语音代理。
2. **用户选择的对话模型**：访问者在网页的“模型设置”中填写兼容 OpenAI Chat Completions 的服务地址、模型 ID 和 API Key。
3. **部署方的角色语音服务**：GPT-SoVITS、训练权重和参考音频运行在独立、持续在线的计算主机上，由网站后端通过 HTTPS 调用。

开发者电脑可以关机。公开网站不能连接开发者电脑上的 `127.0.0.1`，也不应把权重、参考音频、真实语音端点或访问凭据打包进仓库或镜像。

## 二、部署网站服务

### 1. 通用配置

将本仓库导入支持 Python Web Service 或 Docker 的平台。若平台支持直接运行 Python，可使用：

| 设置 | 值 |
| --- | --- |
| Python | 3.10 或更高版本 |
| 根目录 | 仓库根目录 |
| 构建命令 | `pip install -r requirements.txt` |
| 启动命令 | `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` |
| 健康检查 | `/api/health` |

仓库也提供 `Dockerfile` 与 `render.yaml`。平台注入的端口变量应原样保留，不要把监听地址改成 `127.0.0.1`，也不要填写本机磁盘路径。

### 2. 数据库

默认 SQLite 数据库适合试玩和验收。可通过运行时环境变量指定路径：

```text
WANDERER_DATABASE_PATH=data/sessions.db
```

许多免费实例使用临时文件系统，重启或重新部署后可能丢失会话。需要长期保存时，应使用平台的持久磁盘，或先完成后端的持久数据库适配。仅修改连接字符串不能自动把当前 SQLite 实现变成 PostgreSQL。

### 3. 上线检查

部署完成后依次检查：

1. 访问 `https://wanderer-site.invalid/api/health`（替换为实际站点地址），确认返回 `status: ok`。
2. 打开首页，分别进入剧情旅途、自由对话、模型设置和语音设置。
3. 用手机或另一台电脑访问同一 HTTPS 地址，确认页面布局、输入与导航正常。
4. 对照部署平台显示的 Git 提交编号，确认运行的是预期版本。

浏览器显示旧页面时，先确认新部署成功，再强制刷新。网站仍能打开不代表最新版本已经部署。

## 三、部署训练音色服务

### 1. 持续在线要求

公网访问者要在开发者电脑关机时仍能听到正确的训练音色，必须把 GPT-SoVITS、训练权重、参考音频及其提示文本部署在独立、持续在线的计算主机上。该主机需要足够的 CPU/GPU、内存和磁盘，并由部署方承担运行成本。

语音主机前应配置有效 TLS 证书的 HTTPS 反向代理：

- `POST /tts`：接受 GPT-SoVITS 合成请求并返回标准 PCM WAV。
- `GET /openapi.json`：就绪检查中应能识别 `/tts` 路由。
- 不要把请求重定向到另一个地址。
- 配置访问控制、调用额度、并发限制和适合合成时长的超时。

示例地址仅使用 `https://voice-service.invalid/tts`。不要把真实地址、内网拓扑、用户名、密码、查询参数或令牌写进公开文档。

### 2. 网站服务端配置

在网站部署平台的私有环境变量中配置：

```text
WANDERER_TTS_ENABLED=true
WANDERER_TTS_API_URL=https://voice-service.invalid/tts
WANDERER_TTS_REFERENCE_AUDIO=
WANDERER_TTS_PROMPT_TEXT=
WANDERER_TTS_TIMEOUT=240
```

- `WANDERER_TTS_REFERENCE_AUDIO` 是语音主机能够识别的服务端值，不是访问者设备上的路径。
- `WANDERER_TTS_PROMPT_TEXT` 必须与参考音频内容一致。
- 地址不能包含凭据；访问控制应由服务端网络或反向代理处理。
- 远程模式拒绝 HTTP、回环地址和非公网 IP 字面量，避免公开网站意外连接本机或内网服务。

保存环境变量并重新部署网站后，检查 `/api/voice/status`。就绪时应显示远程模式已启用；缺少参考音频或提示文本时，接口只返回变量名和处理建议，不回显真实配置值。

随后从另一台设备调用页面中的训练音色。关闭开发者电脑再次验收，确保语音仍由远程主机生成。自动化测试使用模拟传输，不替代真实部署的 TLS、音质、容量、超时和断线验收。

### 3. 语音模式行为

网页提供三种明确模式：

- **训练音色**：调用部署方配置的 GPT-SoVITS 服务。
- **系统兼容音色**：仅在访问者主动选择后使用该设备的系统语音。
- **无语音**：只显示文字。

训练音色不可用时，页面会保留当前选择并提供重试或切换操作，不会静默改用浏览器中文语音。

## 四、自由对话模型设置

自由对话不要求仓库或服务器存在 `.env` 模型配置。访问者在顶部导航进入 **模型设置**（`#/settings/model`），填写：

1. 服务商预设或自定义 HTTPS 接口地址；
2. 模型 ID；
3. API Key。

点击“测试连接”成功后再保存设置。接口需兼容 OpenAI 风格的 `/v1/chat/completions`、Bearer 鉴权和标准回复结构。

API Key 默认只保留在当前页面内存中。只有访问者主动勾选“在此设备记住设置”后，设置和 Key 才会写入该设备的浏览器存储。“清除全部模型设置”会清理当前内存、设备存储及相关请求状态。

请求会经过网站后端代理，因此网站运营者在技术上可能接触到访问者提交的 Key；部署方应使用 HTTPS，禁止记录请求头和请求正文中的密钥，并在隐私说明中披露这一事实。访问者应使用可撤销、有限额的 Key。

模型未配置、鉴权失败、限流、超时或返回格式错误时，自由对话会显示可操作的错误提示，例如重试、检查 Key/权限或返回设置页。它不会返回内置固定回答来伪装模型调用成功。剧情旅途使用本地确定性脚本，不受该故障影响。

## 五、本机开发

Windows 用户可以双击 `start.bat`，或在 PowerShell 中运行：

```powershell
./start.ps1
```

启动器会创建或复用 `.venv`、安装依赖、启动后端并打开浏览器。默认从 <http://127.0.0.1:8000> 开始尝试可用端口。

本机 GPT-SoVITS 可以通过未提交的私有 `.env` 或系统环境变量配置。项目不会在探测失败后静默回退；控制台和语音状态接口会指出需要设置的变量名。常用变量包括：

```text
GPT_SOVITS_ROOT=
WANDERER_TTS_GPT_WEIGHTS=
WANDERER_TTS_SOVITS_WEIGHTS=
WANDERER_TTS_REFERENCE_AUDIO=
WANDERER_TTS_PROMPT_TEXT=
```

不要把本机路径、权重文件名、参考音频、提示文本或真实配置值提交到 Git。

## 六、发布前验证

在仓库根目录运行：

```powershell
./.venv/Scripts/python.exe -m pytest tests -q --basetemp=.pytest-basetemp
./.venv/Scripts/python.exe -m compileall -q backend
node --test tests/frontend_behavior.test.cjs
node --check frontend/app.js
git diff --check
```

创建只包含 Git 已跟踪公开文件的源码包：

```powershell
./.venv/Scripts/python.exe scripts/package_release.py --output dist/wanderer-game-source.zip
```

上传前检查压缩包清单和待提交差异，确认不包含：

- `.env`、API Key、Token、Cookie、证书或私有端点；
- GPT-SoVITS 权重、参考音频、提示文本和本机安装路径；
- SQLite 数据库、缓存、日志、虚拟环境和测试临时文件；
- 个人联系方式、本机用户目录和含隐私信息的截图或文档。

不要使用强制推送覆盖远端更新。先获取远端分支，确认差异和提交目标，再提交并推送。

## 七、常见问题

- **页面可以打开但自由对话不可用**：进入模型设置，检查 HTTPS 地址、模型 ID、Key 权限与服务商状态；界面不会使用固定回答兜底。
- **测试连接显示网络错误**：确认从部署服务器能够访问服务商，并检查接口路径、TLS 证书、CORS/代理策略和服务商区域限制。
- **训练音色不可用**：检查 `/api/voice/status`、语音主机的 `/openapi.json`、TLS、反向代理超时和运行时环境变量；不要改成浏览器语音来掩盖故障。
- **开发者电脑关机后语音消失**：说明网站仍在连接本机服务，必须把 GPT-SoVITS 和私有音色资产迁移到独立持续在线的主机。
- **重启后历史会话消失**：当前实例使用临时文件系统，需要持久磁盘或数据库适配。
- **部署后仍是旧版本**：核对远端提交、部署事件中的提交编号和浏览器缓存。

平台功能、区域和价格可能变化，请以实际控制台和官方文档为准。
