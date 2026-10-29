# 风起异途：GitHub 上传、Render 部署与后续更新

GitHub 保存代码和运行自动测试；Render 运行游戏，提供队员可以打开的网址。本项目同时包含 Python/FastAPI 后端和前端，请部署为 **Web Service**，不能只使用 GitHub Pages 或 Static Site。

## 一、发布前检查

只发布项目源代码、测试、部署配置和必要的公开资源。不要把 `.env`、API 密钥、数据库、语音模型、参考音频、训练数据、缓存、个人截图或本机路径加入提交。提交前检查 GitHub Desktop 的差异，并确认 GitHub Actions 对当前提交运行成功。

## 二、先用 GitHub Desktop 上传这次修复

### 1. 确认本地项目和远程仓库

1. 打开 GitHub Desktop，左上角 **Current repository（当前仓库）** 选择这个项目。
2. 如果列表中没有它，选择 **File → Add local repository**，选中你当前的 `wanderer-game` 文件夹。该文件夹里应直接有 `requirements.txt`、`backend`、`frontend` 和 `render.yaml`。
3. 通过 **Repository → Show in Explorer** 确认打开的是你正在修改的项目目录。
4. 通过 **Repository → Repository settings → Remote** 查看远程地址，也可用 **Repository → View on GitHub** 打开核对。

请在 GitHub Desktop 中确认选择的是你实际要维护的目标仓库和分支。不要把个人账号、私有仓库地址、访问令牌或其他凭据写入代码、文档或截图。

### 2. 提交修改

1. 顶部 **Current branch（当前分支）** 应为 `main`。
2. 左侧 **Changes（更改）** 应能看到这次修改的四个文件：`tests/test_frontend.py`、`docs/IMPLEMENT_SPEC.md`、`docs/deployment-guide.md`、`.python-version`。
3. 检查文件是否勾选；若还存在你自己的修改，先阅读差异，确认一起提交是否合适。
4. 左下角 **Summary（摘要）** 填写 `Fix CI spec path and document Render deployment`。
5. 点击 **Commit to main（提交到 main）**。这一步只保存到本机 Git 历史，还没有上传。

`.env`、`.venv`、数据库和缓存不需要为了 Git 上传而从电脑删除；已正确忽略且从未被跟踪的文件不会随推送上传。如果它们已经被 Git 跟踪，后来添加 `.gitignore` 并不能自动移除，须先停止跟踪。浏览器手工上传文件不会按本地 `.gitignore` 自动筛选，建议使用 GitHub Desktop。

### 3. 拉取、推送和确认

1. 点击顶部 **Fetch origin（获取远程更新）**。
2. 如果出现 **Pull origin（拉取）**，先拉取；如果提示冲突，处理冲突并完成提交后再继续。不要使用强制推送覆盖队员的提交。
3. 点击 **Push origin（推送）**，等待完成。部分界面把拉取、推送整合为“同步”，以实际按钮文字为准。
4. 选择 **Repository → View on GitHub**，确认网页分支是 `main`，最新提交的摘要就是刚才填写的内容。
5. 点击网页顶部 **Actions**，打开最新一次 `Test` 运行，等待显示绿色勾。红色旧记录不用删除。

如果仍然失败，先确认查看的是新提交，不是旧失败记录；展开新的红色步骤查看最新日志。本地验证不能代替 GitHub 上推送后的实际运行结果。

## 三、在 Render 上创建游戏服务

以下使用手工创建 **Web Service** 的方式。项目也提供 `render.yaml`，但那是 **Blueprint** 方式读取的文件；按本节操作时，请直接填写下列设置。

### 1. 登录并连接 GitHub

1. 打开 <https://render.com/>，注册或登录。
2. 在控制台选择 **New → Web Service**。
3. 在 Git 提供商区域选择连接 GitHub，完成授权。至少允许 Render 访问上述项目仓库。
4. 返回 Render，找到你实际要部署的目标仓库，点击 **Connect**。
5. 如果列表中找不到仓库，进入 GitHub 的 Render 应用安装设置，检查授权范围后再刷新。若将来用组织仓库，还需要该组织允许应用访问。

为了后续自动部署，请通过 GitHub 集成连接仓库。仅用“Public Git Repository”输入公开地址创建的服务，不具备同样的自动部署能力。

### 2. 填写服务设置

| Render 字段 | 填写内容 |
| --- | --- |
| Name（名称） | `wanderer-game`，也可用其他可用名称 |
| Region（区域） | 选择适合队员所在地的区域，例如可选时使用 Singapore |
| Branch（分支） | `main` |
| Language / Runtime（语言） | **Python 3** |
| Root Directory（根目录） | **留空** |
| Build Command（构建命令） | `pip install -r requirements.txt` |
| Start Command（启动命令） | `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` |
| Instance Type（实例类型） | 首次试玩选择 **Free**，以页面实际价格为准 |

注意：

- 仓库内有 `Dockerfile`，如果 Render 自动选成 Docker，请在创建时改选 **Python 3**，才能直接使用上表的 Python 命令。
- 根目录留空，是因为仓库首页直接有 `requirements.txt`、`backend` 和 `frontend`。不要填本机磁盘路径，也不要因为本地文件夹叫 `wanderer-game` 就填这个名字。如果将来整个项目搬到仓库子目录，才填那个子目录。
- 启动命令中的 `$PORT` 原样填入 Render 网页；它由平台设置。不要改成 `127.0.0.1` 或本机固定端口。
- `.python-version` 会让 Render 使用最新可用的 Python 3.11 补丁版本，无需上传 `.venv`。

### 3. 添加环境变量和健康检查

在创建页的 **Environment Variables** 区域逐条添加：

| Key（变量名） | Value（值） |
| --- | --- |
| `WANDERER_DEMO_MODE` | `offline` |
| `WANDERER_DATABASE_PATH` | `data/sessions.db` |

先用离线模式验收：剧情和自由对话能运行；自由对话使用预设回复，不会调用实时模型，不需要密钥。

语音不需要上传任何私有模型或参考音频到 Render。Render 无法启动本机 GPT-SoVITS 时，网页会自动改用队员浏览器提供的中文语音；本机配置了 GPT-SoVITS 的 Windows 启动方式仍会优先使用本地角色音色。

在 **Advanced** 或服务设置中找到 **Health Check Path**，填写 `/api/health`。如果创建页没有此字段，创建后到 **Settings** 修改。

找到 **Auto-Deploy（自动部署）** 时，推荐选择 **After CI Checks Pass（CI 检查通过后）**。本项目已有 GitHub Actions 测试；这样新推送先经过测试，再自动部署。若创建页没有该选项，创建后到 **Settings** 调整。

如果选择 **On Commit**，每次向连接分支推送都会触发部署，但不会等待 GitHub 测试结果。**Off** 表示需要手动部署。

### 4. 创建并等待完成

1. 再检查一次仓库所有者、分支、实例价格和上面的命令。
2. 点击 **Deploy Web Service** 或页面上的创建按钮。
3. 等待依赖安装、启动和健康检查完成。可以在 **Events / Logs** 查看进度。
4. 成功后应看到 **Live** 或成功的部署记录。核对该部署的提交编号是否与 GitHub 最新提交一致。
5. 在服务顶部找到 Render 分配的网址，形如 `https://你的服务名称.onrender.com`。这里是格式示例，实际地址以控制台显示为准。
6. 点击实际网址，进入游戏。把这个网址发给队员；不用让队员安装 Python，也不用让你自己的电脑持续开机。

### 5. 分享前验收

1. 访问实际网址后加 `/api/health`，确认返回 JSON，包含 `status: ok`。
2. 回到首页，检查角色介绍、剧情目录和自由对话。
3. 新建剧情旅途，选择预设选项，确认能推进剧情并到达结局。
4. 新建自由对话，发送消息，确认能收到离线回复。
5. 用手机再打开一次，检查按钮、文字和输入框是否正常。

`/api/health` 的版本字段不是 Git 提交编号。判断上线的是哪次修改，请对照 Render 的部署记录和 GitHub 提交编号。

## 四、免费实例与存档

Render 免费 Web Service 连续约 15 分钟没有访问会休眠，下次打开可能需要约一分钟唤醒。首次等待较久不一定是部署失败，可以稍等后刷新。

当前 SQLite 数据库存放在本地文件系统。免费实例的文件系统是临时的，休眠、重启或重新部署会丢失本地修改，包括数据库中的剧情存档与聊天记录。免费实例也不能挂载持久磁盘，适合先试玩验收。

需要长期保存时，可以选择以下一种方式：

- 使用支持持久磁盘的付费 Web Service，挂载磁盘到 `/var/data`，将 `WANDERER_DATABASE_PATH` 改为 `/var/data/sessions.db`，保存配置并重新部署。**仅升级实例、不挂磁盘，仍不能保证保存数据库**。旧数据库不会自动搬迁，需另行备份和迁移。
- 改造后端接入持久数据库，例如 PostgreSQL。当前代码没有该适配，不能只改连接字符串就完成。

浏览器中保存的会话标识不能代替服务端数据库。数据库丢失后，浏览器可能还记得旧会话，但无法恢复内容，验收时可以创建新会话。Render 免费 PostgreSQL 也有到期限制，不应当作永久免费存档方案。

## 五、需要实时模型时怎么设置

先完成离线部署，再在服务页 **Environment** 配置：

| 变量 | 填写内容 |
| --- | --- |
| `WANDERER_DEMO_MODE` | `live` |
| `WANDERER_MODEL_BASE_URL` | 云服务器可以访问的、兼容 Chat Completions 的服务地址 |
| `WANDERER_MODEL_NAME` | 服务商允许使用的模型名称 |
| `WANDERER_MODEL_API_KEY` | 该服务商的有效密钥 |
| `WANDERER_MODEL_TIMEOUT` | 可选，请求超时秒数 |

基础地址按服务商文档填写，需要 `/v1` 时应保留；程序会追加 `/chat/completions`，也支持直接填写完整端点。保存环境变量后，选择保存并部署，或手动 **Deploy latest commit**，等待新的部署成功。

你电脑上的 `http://localhost:1235`、`http://127.0.0.1:1235` 等 LM Studio 地址不能直接供 Render 使用：云服务器访问这些地址时，指向的是云服务器自身。首次试玩建议保留 `offline`；启用 `live` 时使用 Render 能访问的模型服务。

本机 `.env` 不会随 Git 上传，也不会自动成为 Render 环境变量。密钥只在 Render 后端环境变量中填写，不要写进网页、文档或 GitHub。实时调用可能产生你的模型账户费用，当前应用没有面向公开运营的登录与调用额度控制，先限于团队试玩。实时模型只用于自由对话，剧情旅途仍使用固定剧情。

## 六、以后修改代码，怎样确认网站也更新了

**GitHub Desktop 的同步不能单独保证修改全面生效。** 它同步的是已提交的 Git 内容；网站还需要通过测试、完成部署，浏览器才会使用新版本。

每次修改后，按这个顺序操作：

1. **保存文件**：在编辑器保存代码。未保存的内容不在磁盘上，也不能被 Git 提交。
2. **检查修改**：打开 Desktop，确认选中正确仓库和 `main`，在 Changes 阅读差异。
3. **提交**：填写 Summary，点击 Commit to main。只点击同步，不会自动把尚未提交的修改变成提交。
4. **同步**：Fetch origin；需要时 Pull origin，处理冲突；然后 Push origin。若界面提供“同步（拉取然后推送）”，在已提交的前提下使用它完成这一环节。
5. **确认 GitHub**：网页查看最新提交和 Actions，确认新提交测试为绿色。
6. **确认 Render**：等待新提交对应的自动部署显示 Live。若未触发，先检查连接的仓库、分支和 Auto-Deploy 设置，再选择 Manual Deploy → Deploy latest commit。
7. **确认网页**：等待部署成功后打开 Render 网址，Windows 浏览器按 `Ctrl + F5` 强制刷新，实际操作这次修改涉及的功能。必要时新建会话测试。

只有完成这些步骤，才能确认这次代码修改已经上线并按预期工作。若 Render 新部署失败，先前成功的版本可能继续提供服务，因此“网址还能打开”不代表新版本已上线。

以下情况需要另外处理：

| 修改内容 | 还需要做什么 |
| --- | --- |
| Python、JavaScript、CSS、HTML | 提交、推送、测试通过、Render 部署成功后验收 |
| 本机 `.env` | 在 Render 的 Environment 单独修改并部署；它不随 Git 同步 |
| 本机 `.db`、`.sqlite`、存档或缓存 | 不随 Git 同步，代码推送不会迁移这些数据 |
| 只改 `docs/role-authority.md` | 这是角色权威文档；运行时使用 `backend/app/core/character_profile.py` 等实现，需要同步修改对应代码与验证，文档不会被运行中的模型自动重新读取 |
| `render.yaml` | 本指南手工创建的服务不会自动套用它；在 Render 设置中修改对应项，或另行采用 Blueprint 管理 |
| 本机运行的程序 | Render 部署不会重启本机；本机改配置或后端代码后需按本地启动方式重启 |
| 另一个账号下的同名仓库 | 当前推送不会更新另一份仓库，需统一实际使用的远程地址 |

## 七、部署常见问题

- **找不到 `requirements.txt`**：检查根目录是否误填；本仓库应留空。
- **`Could not import module`**：确认启动命令完整为 `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`，并使用 Python 3 运行环境。
- **提示没有开放端口**：确认监听 `0.0.0.0`，端口用 Render 的 `$PORT`。
- **页面还是旧样子**：对照 GitHub 与 Render 的提交编号，确认部署已成功，再强制刷新。
- **GitHub 测试成功却没有自动部署**：检查是否通过 GitHub 集成连接、分支是否为 `main`、Auto-Deploy 是否开启，以及部署事件中是否有失败或等待。
- **自由对话实时模型报错**：先改为 `offline` 并部署验证；再核对云端接口、模型权限、密钥和服务商状态。不要把包含密钥的配置发给别人。
- **队员看到不同的仓库内容**：对照完整网址中的所有者、仓库名及分支。试玩请统一发送 Render 网址。

## 参考

- [Render：部署 FastAPI](https://render.com/docs/deploy-fastapi)
- [Render：自动部署与手动部署](https://render.com/docs/deploys)
- [Render：Python 版本设置](https://render.com/docs/python-version)
- [Render：免费服务限制](https://render.com/docs/free)
- [Render：持久磁盘](https://render.com/docs/disks)

平台页面文字、可用区域与价格可能调整，请以创建服务时显示的信息为准。
