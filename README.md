# 风起异途

《风起异途》是以《原神》「浮浪倾客」为主题的 AI 互动叙事作品，包含可复现的分支剧情旅途与由用户自行接入模型的自由对话。剧情规则、模型调用和角色语音彼此分层：剧情在无网环境下仍可完整游玩；自由对话不会用固定台词伪装模型成功；训练音色由部署方的独立语音服务生成。

- GitCode 仓库：<https://gitcode.com/IanElseWhere/Welink_The_Welkin_Repository>
- 作品展览馆：<https://gallery.developer.huaweicloud.com/gallery/007342752f000000>

## 功能概览

- **剧情旅途**：从故事目录选择路线，填写玩家称呼后，通过 8 回合预设选项推进剧情；信任、共情与承担三项状态共同影响 4 种结局。剧情使用确定性本地脚本，不依赖模型服务。
- **自由对话**：在网页中选择 OpenAI Chat Completions 兼容服务，填写接口地址、模型 ID 和 API Key 后与角色对话。支持 SSE 流式回复、暂停、复制、重新生成和历史会话。
- **角色语音**：提供训练音色、系统兼容音色和无语音三种明确模式。系统兼容音色必须由用户主动选择，训练音色不可用时不会静默换成浏览器中文语音。
- **安全失败**：模型未配置、权限不足、限流、超时或返回结构错误时，界面会给出对应说明和下一步操作，不会回退到内置固定回答。
- **跨设备访问**：公开 HTTPS 站点连接独立、持续在线的模型服务与语音主机；访问者无需安装 Python、GPT-SoVITS、权重或参考音频，也不依赖开发者电脑开机。

## Windows 一键启动

适用 Windows 10/11，需要 Python 3.10 或更高版本。

1. 双击 `start.bat`。
2. 首次启动会自动创建 `.venv` 并安装 `requirements.txt` 中的依赖，需要能够访问 Python 包索引。
3. 健康检查通过后浏览器会自动打开。默认地址为 <http://127.0.0.1:8000>；端口被占用时会自动尝试 8001 至 8010。
4. 关闭启动脚本窗口即可停止本次服务。

也可以在 PowerShell 中运行：

```powershell
./start.ps1
```

启动器会识别已运行的 `0.2.0` 版本并直接打开；遇到旧版本或端口冲突会换用其他可用端口。语音配置失败不会阻止文字页面启动，控制台会显示需要检查的变量名，不会静默使用错误音色。

## 使用模型设置

顶部导航选择 **模型设置**，或打开 `#/settings/model`：

1. 选择服务商预设，或填写自定义 HTTPS 接口地址。
2. 填写模型 ID 和 API Key。
3. 点击“测试连接”；成功后点击“保存设置”。测试只检查网络、鉴权和模型可用性，不要求服务商返回角色扮演 JSON。
4. 返回自由对话发送消息。

接口需兼容 OpenAI 风格的 `/v1/chat/completions`。填写没有路径的 HTTPS 域名时会自动补上 `/v1`，也可直接填写完整接口路径；服务需支持 Bearer 鉴权，并返回标准 `choices[0].message.content` 或直接 JSON 对象。

API Key 默认只保存在当前页面内存中。勾选“在此设备记住设置”后，设置和 Key 才会写入该设备的浏览器存储；“清除全部模型设置”会清除当前内存、设备存储和相关请求状态。请求会经过本站后端代理，网站运营者在技术上可能接触到 Key，服务商用量与费用由使用者承担。不要把 Key 写入仓库、截图或聊天记录。

模型故障时，界面会按错误类型提供“编辑模型设置”“检查 Key/权限”“等待后重试”或“重试”等操作。自由对话不会改用 fixture 或固定台词；剧情旅途仍可离线继续。

## 使用语音设置

顶部导航选择 **语音设置**，或打开 `#/settings/voice`。选择后点击“保存设置”：

- **训练音色**：使用部署方配置的 GPT-SoVITS 角色音色。
- **系统兼容音色**：仅在用户主动选择后使用当前设备的系统语音。
- **无语音**：只显示文字，不发起朗读。

语音服务不可用时，页面会保留用户原先选择并提供重试或改用其他模式的操作，不会自行覆盖设置。语音偏好仅保存在当前设备。

## 本机 GPT-SoVITS 配置

本机开发可在不提交 Git 的私有 `.env` 中配置已有的 GPT-SoVITS-v2Pro 安装。项目不会猜测任意安装目录；自动默认仅适用于受支持的标准目录结构，探测失败时会明确提示需要设置的变量。

```text
WANDERER_TTS_ENABLED=true
GPT_SOVITS_ROOT=
WANDERER_TTS_DEVICE=auto
WANDERER_TTS_API_URL=
WANDERER_TTS_GPT_WEIGHTS=
WANDERER_TTS_SOVITS_WEIGHTS=
WANDERER_TTS_REFERENCE_AUDIO=
WANDERER_TTS_PROMPT_TEXT=
WANDERER_TTS_SPEED_FACTOR=0.9
WANDERER_TTS_TIMEOUT=240
WANDERER_TTS_STARTUP_TIMEOUT=300
```

权重、参考音频、提示文本和本机安装路径都属于私有运行资产，不得提交。语音缓存位于 `data/voice-cache`，已被 Git 忽略；缓存按回复文本、参考音频、提示词和权重指纹隔离，可以删除后重新生成。

## 公网 HTTPS 部署

本项目包含 FastAPI 后端，不能只作为静态网页部署。仓库提供 `Dockerfile` 与 `render.yaml`，也可部署到支持 Python Web Service 或容器的其他平台。

基本运行命令：

```text
pip install -r requirements.txt
uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
```

健康检查路径为 `/api/health`。运行时数据库路径可通过 `WANDERER_DATABASE_PATH` 指定；部署平台的临时磁盘可能在重启后清空历史会话，如需长期保存应挂载持久存储。

### 独立训练音色服务

公网访问者要在开发者电脑关机时仍能听到训练音色，必须把 GPT-SoVITS 与训练权重部署在独立、持续在线的计算主机上，并通过有效 TLS 证书提供 HTTPS `/tts` 服务。网站后端只转发合成请求，不把权重、参考音频或主机凭据交给浏览器。

部署环境中私下设置：

```text
WANDERER_TTS_ENABLED=true
WANDERER_TTS_API_URL=https://voice-service.invalid/tts
WANDERER_TTS_REFERENCE_AUDIO=
WANDERER_TTS_PROMPT_TEXT=
WANDERER_TTS_TIMEOUT=240
```

远程模式拒绝 HTTP、回环地址和带凭据的 URL。`WANDERER_TTS_REFERENCE_AUDIO` 是语音主机能够识别的服务端值，不是访问者电脑上的文件路径。公开仓库和镜像不包含 GPT-SoVITS、模型权重、参考音频、真实端点或访问密钥。

完整部署与验收步骤见 [`docs/deployment-guide.md`](docs/deployment-guide.md)。

## 发布与隐私

仓库中可以公开发布的内容包括应用源代码、前端资源、测试、示例空配置、部署描述和文档。以下内容不得上传：

- `.env` 与任何 API Key、Token、Cookie 或私有服务地址；
- GPT-SoVITS 权重、参考音频、提示文本和本机安装路径；
- SQLite 数据库、语音缓存、日志、测试缓存和虚拟环境；
- 含个人联系方式、账号凭据或本机用户目录的截图和文档。

`.gitignore`、隐私测试和发布打包脚本会共同拦截上述内容。创建干净源码包：

```powershell
./.venv/Scripts/python.exe scripts/package_release.py --output dist/wanderer-game-source.zip
```

打包器只读取 Git 已跟踪文件，并拒绝数据库、音频、权重、缓存和模型文件扩展名。推送前仍应检查 `git diff --cached` 与压缩包清单。

## 验证

```powershell
./.venv/Scripts/python.exe -m pytest tests -q --basetemp=.pytest-basetemp
./.venv/Scripts/python.exe -m compileall -q backend
node --test tests/frontend_behavior.test.cjs
node --check frontend/app.js
```

- 健康检查：<http://127.0.0.1:8000/api/health>
- API 文档：<http://127.0.0.1:8000/docs>

## 项目结构

- `frontend/`：原生 HTML、CSS、JavaScript 页面、哈希路由与流式交互。
- `backend/app/api/routes/`：剧情、自由对话、模型设置测试和语音 API。
- `backend/app/core/roleplay_engine.py`：剧情回合编排。
- `backend/app/core/state_machine.py`：状态推进与唯一结局裁决。
- `backend/app/core/model_client.py`：确定性剧情数据与实时模型客户端。
- `backend/app/core/model_transport.py`：请求作用域的安全 HTTPS 模型传输。
- `backend/app/core/language_guard.py`：角色回复语言质量守卫。
- `backend/app/core/voice_config.py`：本机与远程语音配置及无敏感值诊断。
- `backend/app/storage/`：SQLite 剧情存档与自由对话历史。
- `docs/role-authority.md`：角色语气、事实与边界的项目内权威摘要。
- `scripts/package_release.py`：只打包 Git 已跟踪且允许公开的源码。

## 开源组件

项目直接依赖 FastAPI、Uvicorn、Pydantic、HTTPX 与 Pytest；前端使用浏览器原生 HTML/CSS/JavaScript，不需要前端构建工具。角色训练音色由独立部署的 GPT-SoVITS 提供，GPT-SoVITS 本体、权重和音频不包含在本仓库中。使用和再发布第三方组件时，应分别遵守其许可证与模型/素材授权要求。

## 关于 AI 编码协作

项目开发中使用华为云码道 CodeArts 与 Codex 辅助进行需求拆解、跨文件实现、错误定位、回归测试、隐私检查和文档同步。产品方向、角色设定边界、体验取舍与最终验收由团队成员决定；AI 生成或修改的代码必须经过自动化测试和人工试玩后才进入发布版本。
