<p align="center">
  <img src="assets/wordtower-logo.png" width="80" alt="词塔 Logo">
</p>

<h1 align="center">词塔 WordTower Skills</h1>

[词塔 Skill](skills/wordtower/SKILL.md) 可以导入文本、EPUB、YouTube 视频与带时间戳字幕，从最近保存的段落接着读，以及在授权后把讨论写回笔记或个人 ReadPilot 讲解。

## 快速开始

### 1. 安装词塔 Skill

```sh
npx skills add word-tower/skills -g
```

在终端运行，或把命令交给支持执行终端命令的 AI 客户端。安装器会识别本机客户端。Codex、Cursor、Gemini CLI 等共用 Skill 目录的客户端可读取同一份安装。出现客户端列表时，可以再选 Claude Code、Antigravity 等客户端。可用选项见 [Skills CLI 客户端列表](https://github.com/vercel-labs/skills/blob/main/docs/agents.md)。

安装完成后，如果 CLI 还没检测到 `find-skills`，且此前没有处理过这条提示，它可能会询问是否安装。想让 AI 帮你发现其他 Skill，可以选 `Yes`。只想使用词塔，选 `No` 即可。[了解 find-skills](https://skills.sh/vercel-labs/skills/find-skills)

也可以在词塔「账户 → Skill 与 Token」下载官方 ZIP，通过支持手动导入的客户端安装。

### 2. 创建 Token 并配置到客户端

打开词塔「账户 → Skill 与 Token」并创建 Token。首次连接只需授权「课程、目录与阅读位置」。复制以 `wtk-` 开头的 API Key，在 AI 客户端的本地运行环境中配置为 `WORDTOWER_API_KEY`。

如果从 macOS 或 Linux 终端启动客户端，可以在同一个终端先设置环境变量，再启动客户端。

```sh
export WORDTOWER_API_KEY='替换为你的 API Key'
```

通过桌面图标启动的客户端，请按该客户端的方式配置运行环境。将 Token 保存在本地，避免贴到 AI 对话或提交到 Git。

### 3. 试一句

> 用词塔告诉我最近在读哪本书。

能返回书名，或明确提示没有阅读记录，就说明读取成功。如果提示缺少 `WORDTOWER_API_KEY`，检查它是否配置在当前客户端的运行环境里，配置后重新启动客户端再试。

还可以试试「把这本 EPUB 的第 3 到第 5 章导入词塔」或「用词塔接着读，聊聊我停下的这段」。需要写回时，可以说「把刚才讨论的要点记到这段旁边」。

有关授权、请求格式和错误处理，见[调用协议](skills/wordtower/references/protocol.md)。

你也可以说「把这三篇文章都导入我的『每周精读』合集」或「新建『英语访谈』合集，把这几个 YouTube 视频导进去」。此功能需要支持手动合集导入的词塔后端。[手动合集导入指引](skills/wordtower/references/importing.md#导入到手动合集)

YouTube 导入可说「把这个 YouTube 视频和这份 VTT 字幕导入词塔，保留时间轴」。支持 JSON3 逐词时间戳，以及 SRT、VTT 和结构化 JSON 字幕，需要授权「导入课程」。可用权限、额度和剩余次数以服务端实时查询结果为准。具体命令见[导入指引](skills/wordtower/references/importing.md#youtube-视频与带时间戳字幕)。


## WorkBuddy MCP 连接器

WorkBuddy 可使用带 API Key 输入表单的词塔 MCP 连接器，安装与连接方法见 [WorkBuddy 连接教程](connectors/workbuddy/README.md)。

单个 YouTube 链接可由包内 `youtube_subtitles.py` 获取自带字幕并保留源字幕的词时间；需要 Python 3 和可访问 YouTube 的网络，无需 yt-dlp 或其他 Skill。无字幕或访问受限时可提供已有字幕文件，详见[导入指引](skills/wordtower/references/importing.md#只有视频链接时)。

## Claude Code 插件安装

仓库发布后，也可在 Claude Code 内通过插件市场安装同一份 Skill：

```text
/plugin marketplace add word-tower/skills
/plugin install wordtower@wordtower
```

插件和普通 Skill 使用相同的 `WORDTOWER_API_KEY` 配置，同一客户端选择一种安装方式。默认通过网关连接；可选 MCP 配置和 Codex 安装说明见[客户端指引](docs/clients.md)。

## 一键生成安装包

```sh
python3 scripts/build.py --all
```

在 `dist/` 仅生成通用 Skill 和 WorkBuddy 连接器两个 ZIP。业务脚本、领域文档和 Skill 路由共用一份源码，WorkBuddy 只适配凭证与 MCP 调用协议。构建不修改本机客户端配置，也不读取 Key。完整参数、版本与更新方式见[构建与发布](docs/clients.md#构建与发布)。

Claude Code 使用插件市场安装，Codex 使用通用 Skill，无需专用 ZIP。两者的 MCP 配置示例保留在[客户端指引](docs/clients.md)中，需另行配置；Skill 默认仍使用网关。
