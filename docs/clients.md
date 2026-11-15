# 选择安装方式

词塔 Skill 的唯一源码位于 `skills/wordtower/`。各渠道复用相同脚本和领域文档；WorkBuddy 的调用协议适配 MCP。使用本地文件能力需 Python 3，单视频字幕获取还需可访问 YouTube 的网络。

## 普通 Skill：Codex、Claude Code 等

Codex 使用通用 Skill，不再单独生成 Codex ZIP。MCP 连接按本文配置。

```sh
npx skills add word-tower/skills -g
```

选择实际使用的客户端。也可解压通用 Skill ZIP，把完整 `wordtower/` 安装到客户端 Skill 目录。Codex 用户级目录为 `~/.agents/skills/`，项目级为 `.agents/skills/`。不要同时安装同一 Skill 的多份副本。

在词塔「账户 → Skill 与 Token」创建 Key，并在启动 AI 客户端的本地环境中设置 `WORDTOWER_API_KEY`。桌面图标启动的程序需要使用对应客户端的环境配置；一次终端 export 不会自动配置所有桌面程序。Key 不放进对话、仓库或安装包。

先说「用词塔告诉我最近在读哪本书」验证只读连接，再按需授权导入、正文、笔记和个人讲解。权限与额度以服务端为准。

## Claude Code 插件

仓库发布后，在 Claude Code 内执行：

```text
/plugin marketplace add word-tower/skills
/plugin install wordtower@wordtower
```

插件直接加载同一 `skills/wordtower/`，默认使用 JSON 网关，与普通 Skill 使用相同 Key 环境变量。不要同时通过 npx 和插件给同一 Claude Code 安装两份词塔。

本地验证：`claude plugin validate .`，之后可用 `claude --plugin-dir .` 测试，不必先公开发布。Claude Code 通过仓库插件市场安装，不再单独生成插件 ZIP。插件命令带命名空间，通常为 `/wordtower:wordtower`。

更新时通过 `/plugin` 管理市场更新及自动更新选项；已安装版本是否更新取决于客户端设置，不承诺 push 后立即自动更新。

## 可选：直接连接 MCP

Skill 默认通过网关调用；MCP 是另一种连接方式，服务地址为：

```text
https://api.wordtower.cn/api/agent/v1/mcp
```

客户端配置只引用环境变量名称，实际 Key 留在本地。工具 schema、授权和日限额由同一后端提供。本仓库不包含另一个 MCP 服务进程。示例配置不会在安装 Skill 或插件时自动注册连接。

### Codex

可将以下片段合并进自己的 `~/.codex/config.toml`，不要覆盖已有配置：

```toml
[mcp_servers.wordtower]
url = "https://api.wordtower.cn/api/agent/v1/mcp"
bearer_token_env_var = "WORDTOWER_API_KEY"
```

也可自行执行：

```sh
codex mcp add wordtower --url https://api.wordtower.cn/api/agent/v1/mcp --bearer-token-env-var WORDTOWER_API_KEY
```

### Claude Code

将以下内容合并进项目 `.mcp.json`，不要覆盖已有服务。启动 Claude Code 前配置 `WORDTOWER_API_KEY`，按客户端提示批准连接：

```json
{
  "mcpServers": {
    "wordtower": {
      "type": "http",
      "url": "https://api.wordtower.cn/api/agent/v1/mcp",
      "headers": {"Authorization": "Bearer ${WORDTOWER_API_KEY}"}
    }
  }
}
```

通过 MCP 使用时，以客户端实际发现的工具为准，工具名可能带命名空间；不要将 `api_name`、`skill_version` 或用户 ID 作为业务参数，也不从 MCP 连接中提取 Key 给脚本。需要包内文件上传和导出配合时，可参考 [MCP 调用与本地脚本](../connectors/workbuddy/protocol.md) 中的 API 转工具规则和离线模式；其中 WorkBuddy 连接表单说明仅适用于 WorkBuddy。普通 Skill 默认仍使用网关，不会仅因存在示例配置就切换连接。

### WorkBuddy

用生成的 WorkBuddy ZIP 提交连接器审核，Key 填写在连接表单。完整操作见 [WorkBuddy 教程](../connectors/workbuddy/README.md)。插件市场更新不代替 WorkBuddy 连接器审核发布。

## 构建与发布

在仓库根目录运行：

```sh
python3 scripts/build.py --check
python3 scripts/build.py --all
```

也支持 `--target skill|workbuddy`，单目标可带 `--output /tmp/package.zip`，或用 `--output-dir` 指定输出目录。默认产物在被 Git 忽略的 `dist/`，不会安装客户端、写入用户配置、读取 Key 或调用线上接口。所有 ZIP 按白名单打包，排除缓存、IDE 文件和仓库历史。

- Skill 和插件版本以公共 SKILL.md 为准，plugin.json 必须同步；校验会阻止版本不一致的构建。
- WorkBuddy 版本在 connector-meta.json 中维护，生成的 Skill 入口使用该渠道版本。
- `connectors/workbuddy/build.py --output …` 旧命令继续可用。
- 新增公共脚本或文档时更新 `scripts/build.py` 的 SKILL_FILES，并运行测试。
- Git tag 发布工作流使用同一构建入口，仅生成通用 Skill 和 WorkBuddy 两类 ZIP；构建不会自动发布。

格式依据：[Claude 插件规范](https://code.claude.com/docs/en/plugins-reference)、[插件市场](https://code.claude.com/docs/en/plugin-marketplaces)、[Codex MCP](https://developers.openai.com/codex/mcp/)。

## 仓库维护

维护者使用根目录 CLAUDE.md 和项目 `/release-skills` 整理发布；`/release-skills --dry-run` 只预览计划。发布 Skill 在 `.claude/skills/` 下标记为 internal，不属于用户安装内容。版本变更记录见[CHANGELOG.md](../CHANGELOG.md)。
