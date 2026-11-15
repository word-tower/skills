---
name: release-skills
description: 维护 word-tower/skills 仓库的版本、变更记录和发布。用户在本仓库要求发布新版、更新版本或预览发布计划时使用；日常课程导入和阅读不适用。
metadata:
  internal: "true"
---

# 发布词塔 Skill

这是词塔仓库维护流程。仅在当前目录确认为 word-tower/skills 仓库，且存在 skills/wordtower/SKILL.md、.claude-plugin/plugin.json、connectors/workbuddy/connector-meta.json、scripts/build.py 时执行。路径以仓库根目录为基准；不修改其他项目。读取本仓库 CLAUDE.md 和当前文件实现，下面的命令是操作指引，不是已安装的发布程序。

## 范围与预览

区分用户要求的是预览、准备、提交、推送还是正式发布，按已授权范围推进。`/release-skills --dry-run` 只读取状态并展示计划，不改版本、文件、索引、tag、远程或 Release，也不安装依赖。不要因看到本流程就自动发布。

先检查 git status、当前分支、origin 地址、最近 tag 和 tag 之后的提交；识别未提交的任务改动与其他改动。预览需说明目标提交、公共版本、WorkBuddy 版本、变更摘要、待提交文件、两份预计产物和验证/鉴权缺口。范围或版本存在实质歧义时先说明，不能把无关改动打进发布。

未指定版本时，根据实际兼容性提出下一个版本；有未发布的版本号时先核对，不重复递增。准备阶段可修改版本和变更记录；只有用户要求发布时才推送 main 和 tag。不要移 tag、force push 或删除旧 Release。

## 准备发布

1. 公共版本同步 `skills/wordtower/SKILL.md` 的顶层 version、metadata.version 和 `.claude-plugin/plugin.json` 的 version。保留 name 和展示字段，不改 API Key、认证目标或网关 skill_version。
2. WorkBuddy 的源内容、打包内容或协议有更新时，递增 `connectors/workbuddy/connector-meta.json` 的 version；构建会生成对应版本的入口，无需维护另一份 SKILL.md。
3. 更新 CHANGELOG.md，区分已发布版本与 Unreleased；记录用户可感知变化、兼容性和部署前提，不编造测试或历史。
4. 核对 README.md、docs/clients.md 和 WorkBuddy 教程。公共调用能力若依赖后端更新，明确前提，不把本仓库发布当成后端部署。

对脚本、打包、版本或协议变更运行：

```sh
python3 -m unittest discover -s tests -q
python3 scripts/build.py --check
python3 scripts/build.py --all
```

构建只应产生 `dist/wordtower-<公共版本>.zip` 和 `dist/wordtower-workbuddy-<渠道版本>.zip`。校验白名单、无凭据及维护文件；不要重新启用 Claude Code/Codex 专用 ZIP。已有其他 dist 文件不能作为上传通配符的来源。

涉及 Skill 发现或目录变化时运行只读列举 `npx skills add . --list`，默认只能显示公共 wordtower。维护 Skill 使用 metadata.internal，不能加入公共 skills/ 或 ZIP。客户端未安装或无可用网络时如实报告未验收，不安装全局工具来伪造验证通过。

## 提交、推送与发布

检查差异，只暂存本次相关路径。排除用户其他修改、IDE 文件、缓存与 dist/，不使用 git add . 或 git add -A 来收集发布内容。发布文件一并提交，tag 必须引用完整提交，工作区遗留其他修改不能被偷偷带入。

正式发布前核对公共版本对应 tag 尚不存在，且远程未有冲突更新。不强行覆盖远程提交；有冲突先协调。按用户授权推送当前主分支及新建的注释 tag `v<公共版本>`；优先使用原子推送。缺少 HTTPS 凭据时可使用已经配置的同仓库 SSH 身份，不修改用户全局认证配置。

推 tag 后由 `.github/workflows/release.yml` 创建 Release 并上传两个包。不再平行手动创建另一份 Release。查看 Actions，等待完成并核对目标 SHA、tag、非 draft 状态、附件名称和大小。失败时查看日志，在当前对话中解决可修复问题；不宣称发布成功，也不移动已存在的 tag。

发布结束报告提交、tag、Release 链接、两类产物和未完成的真实客户端或线上验证。Claude Code 自建市场可以直接安装；官方目录提交及 WorkBuddy 平台审核单独处理。
