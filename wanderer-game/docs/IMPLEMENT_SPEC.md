<!-- 本文件由 codex 辅助生成（外围模块） -->
# 风起异途实施规格

本文件是随 Git 仓库一起交付的当前规格，不依赖仓库外的文件。开发交付目录中的早期规格仅作为历史背景；当前代码状态与实施决策以本文件、项目根目录的 `HANDOFF.md` 和 `README.md` 为准。

当前产品包括独立的自由对话与剧情旅途；原生 HTML/CSS/JavaScript + FastAPI + SQLite；剧情旅途使用本地固定剧情，自由对话是否连接实时模型由后端环境变量决定，页面不提供模式切换模块。核心状态机和响应映射均已实现。`docs/codearts-handoff.md` 保留为赛事留证背景与代码导览，不再是待 CodeArts 实现清单。

## 当前流程

- 玩家可在开始前输入并保存自定义姓名，名字会写入剧情状态和自由对话会话。
- 剧情旅途从故事目录选择路线，通过预设选项推进八个回合，由后端状态机决定状态变化和四种结局；不接收玩家自由文本。
- 自由对话独立保存历史，不推进剧情状态；支持复制、重新生成、恢复和删除对话。
- 模型 API 密钥只在后端环境变量中配置；剧情始终使用本地确定性内容。模型失败时明确显示错误。
- 浏览器保存会话标识，SQLite 保存实际内容；清除浏览器数据会失去本机的续玩入口，服务端数据库丢失则无法恢复对应会话。

## 项目文件树

```text
project-root/
├─ README.md
├─ HANDOFF.md
├─ requirements.txt
├─ render.yaml
├─ Dockerfile
├─ start.bat / start.ps1
├─ .github/workflows/test.yml
├─ docs/
│  ├─ IMPLEMENT_SPEC.md
│  ├─ role-authority.md
│  └─ deployment-guide.md
├─ frontend/
│  ├─ app.js
│  ├─ index.html
│  └─ styles.css
├─ backend/app/
│  ├─ main.py
│  ├─ config.py
│  ├─ api/routes/
│  ├─ contracts/
│  ├─ core/
│  ├─ services/
│  ├─ storage/
│  └─ replay/
├─ scripts/package_release.py
└─ tests/
   ├─ test_api.py
   ├─ test_frontend.py
   ├─ test_profile_authority.py
   └─ frontend_behavior.test.cjs
```

前端使用原生 HTML/CSS/JavaScript，由 FastAPI 同时提供页面和 API；不需要独立前端构建。核心代码职责见 `HANDOFF.md`，部署和日常更新步骤见 `deployment-guide.md`。

## 部署与验证

Render 运行 Python Web Service，监听 `0.0.0.0` 和平台提供的 `PORT`，健康检查路径是 `/api/health`。本地开发仍使用 `start.bat` 或 `start.ps1`。

GitHub Actions 在独立检出目录运行 `python -m pytest tests -q --basetemp=.pytest-basetemp-ci`、后端编译检查和前端语法检查。测试使用仓库内的文档，不读取交付目录中的外部规格或本机凭据。

## 交互更新记录

2026-10-18 对话体验更新：自由对话隐藏模型返回的情绪标签；发送消息后立即显示玩家消息，并在助手气泡内显示等待提示，收到回复后以整体淡入动画显现。聊天标题由模型概括对话主题，旧记录会在恢复时迁移生成主题标题。首页入口统一固定在页眉右侧，自由对话和剧情内容内不再重复显示。

2026-10-18 交互更新：剧情入口先展示可扩展故事目录；所有剧情使用本地固定剧情，实时模型仅用于自由对话，页面删除实时/固定回放模块。未完成旅途弹出续玩确认，选择否不删除进度。页眉导航固定提供回首页入口。剧情台词/结局不显示情绪，并删除指定身份和免责声明文字。自由对话 403 错误会安全显示上游状态、模型、脱敏接口地址及服务商请求编号（若有）。模型客户端发送兼容网关所需的应用 User-Agent，并支持完整端点配置。
