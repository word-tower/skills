"""Build client packages from one Skill source; never read local credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/wordtower"
WORKBUDDY = ROOT / "connectors/workbuddy"
MCP_URL = "https://api.wordtower.cn/api/agent/v1/mcp"
SKILL_FILES = (
    "SKILL.md", "config.json", "references/protocol.md",
    "references/importing.md", "references/reading.md", "references/reading-companion.md",
    "references/epub-selection.md", "references/readpilot.md", "references/statistics.md",
    "references/annotations.md", "scripts/request.py", "scripts/export.py",
    "scripts/epub_select.py", "scripts/readpilot_validate.py", "scripts/youtube_subtitles.py",
)
TARGETS = ("skill", "workbuddy")


def read(root, name):
    source = root / name
    if source.is_symlink() or not source.is_file() or root.resolve() not in source.resolve().parents:
        raise ValueError(f"Invalid package source: {name}")
    return source.read_bytes()


def version():
    match = re.search(r'^version: "([0-9]+\.[0-9]+\.[0-9]+)"$', read(SKILL, "SKILL.md").decode(), re.M)
    if not match:
        raise ValueError("Skill version is missing")
    return match.group(1)


def validate():
    manifest = json.loads(read(ROOT, ".claude-plugin/plugin.json"))
    catalog = json.loads(read(ROOT, ".claude-plugin/marketplace.json"))
    if manifest["name"] != "wordtower" or manifest["version"] != version():
        raise ValueError("Plugin and Skill versions must match")
    plugins = catalog["plugins"]
    if (catalog["name"] != "wordtower" or len(plugins) != 1
            or plugins[0]["name"] != manifest["name"] or plugins[0]["source"] != "./"):
        raise ValueError("Marketplace must reference the single root plugin")
    # The default skills/ folder is discovered once; do not list it a second time.
    if "skills" in manifest or "skills" in catalog["plugins"][0]:
        raise ValueError("Do not register the default Skill directory twice")
    for name in SKILL_FILES:
        read(SKILL, name)


def workbuddy_entries():
    metadata = json.loads(read(WORKBUDDY, "connector-meta.json"))
    token = json.loads(read(WORKBUDDY, "token-schema.json"))
    config = json.loads(read(WORKBUDDY, "mcp.json"))
    server = config["mcpServers"]["wordtower"]
    if (metadata["auth_mode"] != "token" or token["fields"][0]["key"] != "WORDTOWER_API_KEY"
            or token["fields"][0]["type"] != "password" or server["url"] != MCP_URL
            or server["headers"]["Authorization"] != "Bearer ${WORDTOWER_API_KEY}"):
        raise ValueError("Invalid connector credential configuration")
    entries = {name: read(WORKBUDDY, name) for name in (
        "connector-meta.json", "mcp.json", "token-schema.json", "icon.png")}
    for name in SKILL_FILES:
        content = read(SKILL, name)
        if name == "SKILL.md":
            text = content.decode()
            text = re.sub(r'^(\s*version:) "[^"]+"', lambda m: m[1] + ' "' + metadata["version"] + '"', text, flags=re.M)
            text = text.replace("以 /_list 实际开放能力为准。", "以本次 MCP 连接实际提供的工具与 schema 为准。")
            start = text.index("连接凭据从用户本地 WORDTOWER_API_KEY 获取；")
            end = text.index("用户明确要求导入且 Key", start)
            text = text[:start] + (
                "通过已连接的词塔 MCP 工具执行业务操作，工具实际名称可能包含客户端命名空间。"
                "凭证由 WorkBuddy 连接表单管理；缺少或失效时引导到连接器填写词塔 API Key，"
                "不要让用户在对话中发送 Key。按调用协议转换共享文档中的 API 请求，"
                "不从本地进程读取连接表单凭证。\n\n") + text[end:]
            content = text.encode()
        elif name == "references/protocol.md":
            content = read(WORKBUDDY, "protocol.md")
        elif name.startswith("references/"):
            content = ("本包通过 MCP 调用业务接口。本文中的 api_name 请求和联网脚本示例按"
                       "[MCP 调用协议](protocol.md)转换，字段含义与业务规则保持一致。\n\n").encode() + content
        entries["skills/wordtower/" + name] = content
    return metadata["version"], entries


def package_entries(target):
    validate()
    if target == "workbuddy":
        return workbuddy_entries()
    if target not in TARGETS:
        raise ValueError("Unknown target")
    entries = {"wordtower/" + name: read(SKILL, name) for name in SKILL_FILES}
    return version(), entries


def build(target, output):
    package_version, entries = package_entries(target)
    output = Path(output)
    if output.suffix != ".zip":
        raise ValueError("Output must be a ZIP")
    if output.resolve().is_relative_to(SKILL.resolve()) or output.resolve().is_relative_to(WORKBUDDY.resolve()):
        raise ValueError("Output must not overwrite package sources")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(entries.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 11, 15, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return package_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--target", choices=TARGETS)
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, help="ZIP path for a single target")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if args.output and not args.target:
        parser.error("--output requires --target")
    if args.check:
        for target in TARGETS:
            package_entries(target)
        print("Package sources and metadata are valid")
        return
    for target in TARGETS if args.all else (args.target,):
        package_version, _ = package_entries(target)
        name = f"wordtower-{package_version}.zip" if target == "skill" else f"wordtower-{target}-{package_version}.zip"
        output = args.output or args.output_dir / name
        build(target, output)
        print(f"Built {target}: {output}")


if __name__ == "__main__":
    main()
