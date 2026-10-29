# 流浪者剧情深化与模型接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将”风起异途”改成全中文可读、无重复台词、具有状态驱动分支,并接入可配置的 DeepSeek 兼容实时模型。

**Architecture:** 前端负责展示层翻译、历史记录去重和稳定的用户文本；后端保留核心状态机契约，扩展离线回放为状态驱动的长剧情，并将实时模型配置集中到环境变量。模型客户端使用 OpenAI Chat Completions 兼容协议，因此只需替换端点、模型名和密钥即可切换供应商。

**Tech Stack:** 原生 HTML/CSS/JavaScript、FastAPI、Pydantic、SQLite、Python pytest。

**Spec:** 本轮已获用户确认的中文化、剧情深化、状态关联和 DeepSeek 接入设计。

## Global Constraints

- 用户可见界面不显示英文内部标识、原始场景 ID、原始情绪枚举或会话 UUID。
- `trust`、`compassion`、`responsibility` 始终限制在 `[0, 100]`；模型状态变化单项先限制在 `[-10, 10]`。
- 离线模式必须无网络可运行；实时模式缺少配置时返回明确错误。
- 实时模型使用 `WANDERER_MODEL_API_KEY`、`WANDERER_MODEL_BASE_URL`、`WANDERER_MODEL_NAME` 和 `WANDERER_MODEL_TIMEOUT`。

### Task 1: 中文界面与重复台词回归

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend.py`

- [ ] 写测试，断言没有 `CONVERSATIONS`、`FREE ROLEPLAY`、原始 `scene_id` 和 UUID 截取展示，且当前回复不会重复渲染。
- [ ] 运行前端测试确认失败。
- [ ] 增加中文场景/情绪映射，历史只渲染已完成回合，当前回复只渲染一次，聊天历史只显示标题。
- [ ] 运行测试、`node --check frontend/app.js`。

### Task 2: 长剧情与状态驱动离线回放

**Files:**
- Modify: `backend/app/replay/replays.py`
- Modify: `backend/app/replay/playback.py`
- Modify: `backend/app/services/session_service.py`
- Test: `tests/test_replay.py`, `tests/test_api.py`

- [ ] 写测试，断言剧情至少 8 回合、不同选择改变指标和中段内容、四个结局可达。
- [ ] 运行测试确认失败。
- [ ] 添加状态增量、分支回放和结局数据；服务保存用户可读的选项文本。
- [ ] 运行相关测试和全量测试。

### Task 3: DeepSeek 兼容实时模型与切换配置

**Files:**
- Modify: `backend/app/core/model_client.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Modify: `README.md`, `HANDOFF.md`
- Test: `tests/test_live_and_chat.py`, `tests/test_model_client.py`

- [ ] 写测试，断言默认模型名、端点拼接、JSON 响应解析和模型切换配置。
- [ ] 运行测试确认失败。
- [ ] 实现 OpenAI 兼容客户端默认 `deepseek-v4.1-flash`，并保留环境变量覆盖。
- [ ] 增强角色系统提示和近期对话上下文，保留结构化响应校验与错误映射。
- [ ] 运行全量测试、编译检查和实际 API 健康/离线回归。
