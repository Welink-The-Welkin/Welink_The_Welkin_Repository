# 风起异途

《原神》「浮浪倾客」主题互动作品，提供自由对话和分支剧情旅途。剧情旅途从故事目录选择并使用本地剧情；自由对话的模型连接方式由项目配置决定。开始剧情前可输入自己的名字，未完成进度保存在本机。

## 启动

适用 Windows 10/11，需安装 Python 3.10+。双击 `start.bat`，或在 PowerShell 运行：

```powershell
./start.ps1
```

浏览器打开 <http://127.0.0.1:8000>。按 `Ctrl+C` 停止。首次启动会创建 `.venv` 并安装依赖，需要访问 Python 包索引；后续离线回放无需外网。

如果要启用「浮浪倾客」的 GPT-SoVITS 语音，先按下面的语音配置填写 `.env`。启动脚本默认自动检测可用 CUDA 并优先使用 GPU，无法使用时回退 CPU；模型首次加载可能需要几分钟，游戏在语音服务未就绪时仍能正常进行文字对话。

每次开机后，双击 `start.bat` 即可启动服务；启动脚本会显示实际启动目录，等待 `/api/health` 正常后自动打开浏览器。关闭启动脚本窗口会停止本次服务。
如果当前版本的游戏已经在运行，再次双击 `start.bat` 会直接打开现有页面。启动器通过健康接口中的版本号识别当前版本；遇到旧版服务会跳过并自动尝试其他端口，避免继续打开陈旧页面。若 8000 端口由其他程序占用，启动器会自动尝试 8001 至 8010；只有这些端口都不可用时才会显示错误并暂停窗口。

## 玩法

- **自由对话**：导航选择“自由对话”，可直接和「浮浪倾客」交谈。发送后玩家消息会立即显示，回复在固定气泡位置渐入；每条回复下方提供「复制」与「重新生成」快捷操作，历史标题按对话主题概括，会话可恢复或删除。
- **剧情旅途**：从故事目录选择一条路线，开始前填写名字，阅读前情概要，随后只通过点击预设选项推进剧情，经历 8 个回合；信任、共情、承担会持续变化，并影响后续内容和结局。旅途不提供玩家自定义输入。结局页包含旅途摘要和收束文字。未完成的旅途会保存在本机，再次打开时可选择继续。
- **离线模式**：使用确定性角色引擎，无需联网即可完整走完多分支剧情；自由聊天使用本地固定响应。
- **剧情分支**：调查、询问、保护、承担等选择会改变状态和后续台词，最终可达四种结局。
- **模型服务**：仅用于自由对话，由后端 `.env` 中的配置决定是否连接。模型 API 密钥只保存在后端；若凭据、模型名称、网络或额度有问题，页面会显示可识别的错误类别，不会假装模型已回复。剧情旅途始终使用本地剧情。
- **角色语音**：将 `WANDERER_TTS_ENABLED` 设为 `true` 后，启动时会接入本机 GPT-SoVITS v2Pro。剧情台词和自由对话回复会自动朗读；自由对话的回复操作栏会在播放时提供「暂停朗读/继续朗读」。默认参考音频是训练目录中与提示文本“可别让我失望.这世上没有纯粹的自由.”匹配的切片。

## 配置实时模型

推荐方式：复制 `.env.example` 为项目根目录的 `.env`，填写服务商文档提供的密钥、兼容接口基础地址和模型标识，然后重新启动服务：

```text
WANDERER_MODEL_API_KEY=你的服务商 API 密钥
WANDERER_MODEL_BASE_URL=https://api.zxcvbnqwerty.xyz
# 如果服务商文档提供完整的 Chat Completions 地址，可填写它；留空则自动追加 /chat/completions
WANDERER_MODEL_ENDPOINT=
WANDERER_MODEL_NAME=服务商提供的模型标识
WANDERER_DEMO_MODE=live
```

`.env` 只在后端读取，并且已加入忽略规则。基础地址按服务商文档填写；如果文档要求 `/v1` 前缀，就要把它保留在 `WANDERER_MODEL_BASE_URL` 中。程序会在基础地址后追加 `/chat/completions`；也可以直接填写完整的 `/chat/completions` 地址。更换模型时同时确认服务商账户有该模型的调用权限。

本地 LM Studio 示例：

```text
WANDERER_DEMO_MODE=live
WANDERER_MODEL_API_KEY=local
WANDERER_MODEL_BASE_URL=http://localhost:1235/v1
WANDERER_MODEL_ENDPOINT=
WANDERER_MODEL_NAME=qwen/qwen3.5-9b
WANDERER_MODEL_TIMEOUT=240
```

这里的 `WANDERER_MODEL_BASE_URL` 只写到 `/v1`，程序会请求 `/v1/chat/completions`。`WANDERER_MODEL_API_KEY=local` 是本地服务常用的占位值；如果你的本地服务要求特定密钥，再替换成它。修改 `.env` 后必须关闭旧的 Python/Uvicorn 窗口，再从项目目录重新运行 `start.bat` 或 `./start.ps1`，因为运行中的进程不会重新读取配置。

如果 `.env` 中另有 `PROVIDER_*` 配置段，目前客户端不会自动读取或根据它切换模型；实际生效的是上面的 `WANDERER_*` 变量。手动更换模型时，请修改 `WANDERER_MODEL_BASE_URL`、`WANDERER_MODEL_ENDPOINT`、`WANDERER_MODEL_NAME`、`WANDERER_MODEL_API_KEY` 和 `WANDERER_MODEL_TIMEOUT`。

也可以在启动服务的同一个 PowerShell 窗口配置：

```powershell
$env:WANDERER_MODEL_API_KEY = "你的 API 密钥"
$env:WANDERER_MODEL_BASE_URL = "https://api.example.com/v1"
$env:WANDERER_MODEL_NAME = "服务商提供的模型标识"
$env:WANDERER_MODEL_TIMEOUT = "30"
$env:WANDERER_DEMO_MODE = "live"
./start.ps1
```

服务需兼容 `/chat/completions`，支持 Bearer 密钥鉴权，并返回标准 `choices[0].message.content` JSON 文本或直接 JSON 对象。客户端使用 `response_format: {type: text}`，再由程序解析模型返回的 JSON 文本；这样可以兼容 LM Studio 等不接受 `json_object` 的本地服务。密钥只在后端使用；不要把密钥写入源代码、截图、聊天记录或提交仓库。要回到本地离线模型，将 `WANDERER_DEMO_MODE` 设为 `offline` 并重启。

自由对话会优先使用 SSE 分段接收回复：模型分段持续写入浏览器缓存，只有对应语音真正触发 `playing` 时才同步释放这段文字。播放队列保留“当前段 + 下一段”两段预生成窗口，当前段朗读期间就会加载下一段语音，以消除上一段结束后才开始合成造成的额外停顿；语音仍严格按原文顺序播放。角色回复在进入 SSE、语音队列和历史记录前会统一整理成一个连续自然段，模型产生的换行或空行不会再形成单独语音片段；已有历史回复在读取时也会按同一规则显示。回复气泡只在首段出现时播放一次入场动画，后续文字直接在原气泡内更新，不刷新聊天框。更新到包含该功能的代码后，需要关闭旧的 `start.ps1`/Uvicorn 服务并重新启动；如果浏览器仍加载旧脚本，再按 `Ctrl + F5` 强制刷新。上游模型服务若不支持流式响应，程序仍会回退到原有 JSON 响应。

如果页面提示未读取到 API 密钥，请检查 `.env` 是否在项目根目录，且变量名是 `WANDERER_MODEL_API_KEY`。更新密钥或模型配置后，必须关闭运行中的服务窗口并重新启动。

## 配置 GPT-SoVITS 角色语音

将 `.env.example` 复制为 `.env` 后，保留或补充以下配置。`GPT_SOVITS_ROOT` 指向本机的 `GPT-SoVITS-v2pro-20250604` 目录；`WANDERER_TTS_REFERENCE_AUDIO` 可以使用默认的训练切片，也可以改成同一角色的其他 32 kHz WAV 参考音频。

```text
WANDERER_TTS_ENABLED=true
GPT_SOVITS_ROOT=C:\path\to\GPT-SoVITS-v2pro-20250604
WANDERER_TTS_DEVICE=auto
WANDERER_TTS_API_URL=http://127.0.0.1:9880/tts
WANDERER_TTS_REFERENCE_AUDIO=logs/wanderer/5-wav32k/6.1流浪者全语音无音效无背景音乐（自用）.mp3_0000716160_0000856960.wav
WANDERER_TTS_PROMPT_TEXT=可别让我失望.这世上没有纯粹的自由.
WANDERER_TTS_TIMEOUT=240
WANDERER_TTS_STARTUP_TIMEOUT=300
```

这组配置使用 `GPT_weights_v2Pro\流浪者-e15.ckpt` 和 `GPT_SoVITS\pretrained_models\v2Pro\s2Gv2Pro.pth`。`start.ps1` 会在游戏服务退出时清理本次启动的 TTS 进程；如果 `9880` 已经是一个 GPT-SoVITS 服务，则会复用它，不会停止外部启动的进程。语音合成结果会缓存到 `data/voice-cache`，该目录已被 Git 忽略。

### 角色语音增强候选

已用 `P7-6.2主线.mp3`、`P8-6.3主线.mp3` 和 `P9-6.6主线.mp3` 补充训练集。训练产生的候选 GPT 权重位于
`data/voice-training/wanderer-augmented-20261024/candidate/weights/wanderer_augmented-e4.ckpt`，并已通过独立 GPT-SoVITS 推理和 WAV 校验。它没有自动覆盖原权重；试听确认音质后，在 `.env` 设置 `WANDERER_TTS_GPT_WEIGHTS` 指向该文件并重启 `start.ps1` 即可切换。候选训练数据和权重属于本机大文件，已由 `.gitignore` 排除。

缓存按回复文本、参考音频、提示词和 GPT/SoVITS 权重指纹命名，重复剧情、重复提问和重新生成相同文本都能命中。当前缓存约几十 MB，可以安全删除；删除后第一次播放对应文本会重新合成，之后会再次建立缓存：

```powershell
Remove-Item -LiteralPath .\data\voice-cache\*.wav -Force -ErrorAction SilentlyContinue
```

如果实时对话显示 **HTTP 401**，服务商没有验证通过当前请求。确认密钥属于这个 API 地址对应的服务商、复制的是原始密钥（不要自行加 `Bearer ` 前缀），并确认接口使用 Bearer 鉴权。**HTTP 403** 表示服务商禁止了请求，可能与模型权限、账号策略、IP 白名单或接口访问策略有关，不一定是密钥错误。若错误详情包含 `CF-RAY` 或服务商请求编号，把该编号交给服务商核查；不要把密钥发到聊天、截图或公开仓库。

## 用自然语言修改游戏内容

可以直接在已打开本项目的 Codex 对话里用中文提出修改，不必先自己写代码：

1. 说清要改的页面或场景，例如首页、角色介绍、自由对话、旧档案场景或结局页。
2. 写明希望看到的文字或行为，并指出限制，例如“只改叙事和按钮文字，保留状态变化与结局规则”。
3. 让 Codex 先说明会改哪些文件，再执行修改、运行测试并汇报结果。
4. 查看它展示的文件差异；启动游戏后亲自走一遍受影响页面。

可以直接复制这个例子再改成你的需求：

> 把第二幕的旧档案改成一封被涂改过的信，增加一段发现信件时的环境描写，并把两个选项改得更容易区分。只改故事文字和选项，不改变信任、共情、承担的计算方式或结局判定。请修改后运行相关测试，并告诉我如何在游戏里验收。

故事选项和离线台词主要在 `backend/app/core/model_client.py`；场景说明、页面文案和名称展示在 `frontend/app.js`；配色与布局在 `frontend/styles.css`；角色语气约束在 `docs/role-authority.md`。若你确实要调整状态或结局规则，请在请求中明确说这是玩法逻辑改动，并要求同步更新测试。游戏中的实时模型只生成回复，不会自行修改游戏文件；代码内容要在 Codex 的项目对话里提出。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp=.pytest-basetemp
.\.venv\Scripts\python.exe -m compileall -q backend
node --check frontend/app.js
```

健康检查：<http://127.0.0.1:8000/api/health>。API 文档：<http://127.0.0.1:8000/docs>。

## 发布到 GitHub 和网址

本项目包含 FastAPI 后端，不能只用 GitHub Pages 运行。推荐把代码放在 GitHub，把服务部署到 Render；项目已提供 `Dockerfile`、`render.yaml` 和 GitHub Actions 检查配置。完整的中文操作步骤见 [`docs/deployment-guide.md`](docs/deployment-guide.md)。

发布前可以执行 `python scripts/package_release.py --output dist/wanderer-game-source.zip` 创建干净上传包；脚本会排除 `.env`、本机数据库、缓存和日志。

## 架构

- `frontend/`：原生 HTML/CSS/JavaScript 页面和路由。
- `backend/app/api/routes/`：剧情 API 与自由聊天 API。
- `backend/app/core/roleplay_engine.py`：剧情回合编排。
- `backend/app/core/state_machine.py`：剧情状态推进与唯一结局裁决。
- `backend/app/core/response_mapping.py`：剧情模型响应校验与状态映射。
- `backend/app/core/model_client.py`：固定离线响应和实时模型客户端。
- `backend/app/core/language_guard.py`：自由对话的高置信度语言质量守门，拦截机械罗列与比喻堆叠。
- `backend/app/storage/`：SQLite 剧情存档和自由聊天历史。
- `docs/role-authority.md`：角色语气、事实和边界的项目内权威摘要。
- `HANDOFF.md`：当前 API、核心契约、模型配置和验证说明。

## 作品说明
