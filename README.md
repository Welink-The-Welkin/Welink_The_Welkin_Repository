# Welink The Welkin

Welink The Welkin 团队项目仓库。每个项目使用独立子目录维护自己的源码、依赖、测试、部署说明和本地启动方式；仓库根目录只保存团队级索引、自动化流程与跨项目配置。

## 项目

| 项目 | 内容 | 入口 |
| --- | --- | --- |
| `wanderer-game` | 《风起异途》AI 互动叙事项目，包含剧情旅途、自由对话、模型设置与三种明确语音模式 | [项目说明](wanderer-game/README.md) |

## 仓库约定

- 新项目放在独立的一级目录中，不把项目源码直接堆放在仓库根目录。
- 每个项目自行维护 README、依赖文件、测试和部署配置。
- GitHub Actions 位于根目录 `.github/workflows/`，并通过路径过滤只运行受影响项目的任务。
- `.env`、API Key、Token、数据库、日志、缓存、模型权重、参考音频和本机绝对路径不得提交。
- 部署 `wanderer-game` 时，将服务根目录设为 `wanderer-game`；也可以使用仓库根目录的 `render.yaml`。

## 链接

- GitHub 仓库：<https://github.com/IanElseWhere/Welink_The_Welkin_Repository>
- GitCode 镜像：<https://gitcode.com/IanElseWhere/Welink_The_Welkin_Repository>
- 作品展览馆：<https://gallery.developer.huaweicloud.com/gallery/007342752f000000>
