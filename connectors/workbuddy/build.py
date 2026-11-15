"""Build the WorkBuddy upload ZIP from an explicit file whitelist."""
import argparse
import json
from pathlib import Path
import zipfile

FILES = ("connector-meta.json", "mcp.json", "token-schema.json", "icon.png", "skills/wordtower/SKILL.md")


def build(output):
    root = Path(__file__).resolve().parent
    metadata = json.loads((root / "connector-meta.json").read_text())
    token = json.loads((root / "token-schema.json").read_text())
    config = json.loads((root / "mcp.json").read_text())
    assert metadata["auth_mode"] == "token"
    assert token["fields"][0]["key"] == "WORDTOWER_API_KEY"
    assert token["fields"][0]["type"] == "password"
    assert config["mcpServers"]["wordtower"]["headers"]["Authorization"] == "Bearer ${WORDTOWER_API_KEY}"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(root / name, name)
    return metadata["version"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    version = build(args.output)
    print(f"Built WorkBuddy connector {version}: {args.output}")
