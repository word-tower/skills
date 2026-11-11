<p align="center">
  <img src="assets/wordtower-logo.png" width="80" alt="词塔 Logo">
</p>

<h1 align="center">词塔 WordTower Skills</h1>

[词塔 Skill](skills/wordtower/SKILL.md) 可以导入文本和 EPUB、从最近保存的段落接着读，以及在授权后把讨论写回笔记或个人 ReadPilot 讲解。

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
