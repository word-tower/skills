"""Build the connector from shared Skill resources and MCP-specific instructions."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import zipfile

FILES = ("connector-meta.json", "mcp.json", "token-schema.json", "icon.png", "skills/wordtower/SKILL.md")
SHARED_FILES = (
    "config.json",
    "scripts/youtube_subtitles.py", "scripts/request.py", "scripts/export.py", "scripts/epub_select.py", "scripts/readpilot_validate.py",
    "references/importing.md", "references/reading.md", "references/reading-companion.md",
    "references/epub-selection.md", "references/readpilot.md", "references/statistics.md",
    "references/annotations.md",
)


def build(output):
    root = Path(__file__).resolve().parent
    shared = root.parents[1] / "skills/wordtower"
    metadata = json.loads((root / "connector-meta.json").read_text())
    token = json.loads((root / "token-schema.json").read_text())
    config = json.loads((root / "mcp.json").read_text())
    if (metadata["auth_mode"] != "token" or token["fields"][0]["key"] != "WORDTOWER_API_KEY"
            or token["fields"][0]["type"] != "password"
            or config["mcpServers"]["wordtower"]["headers"]["Authorization"] != "Bearer ${WORDTOWER_API_KEY}"):
        raise ValueError("Invalid connector credential configuration")
    entries = {name: (root / name).read_bytes() for name in FILES}
    for name in SHARED_FILES:
        content = (shared / name).read_bytes()
        if name.startswith("references/"):
            content = ("本包通过 MCP 调用业务接口。本文中的 api_name 请求和联网脚本示例按"
                       "[MCP 调用协议](protocol.md)转换，字段含义与业务规则保持一致。\n\n").encode() + content
        entries["skills/wordtower/" + name] = content
    protocol = "skills/wordtower/references/protocol.md"
    entries[protocol] = (root / protocol).read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return metadata["version"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    version = build(args.output)
    print(f"Built WorkBuddy connector {version}: {args.output}")
