"""Compatibility entry point; implementation lives in scripts/build.py."""
import argparse
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("wordtower_package_build", Path(__file__).resolve().parents[2] / "scripts/build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
SHARED_FILES = tuple(name for name in builder.SKILL_FILES if name not in {"SKILL.md", "references/protocol.md"})


def build(output):
    return builder.build("workbuddy", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    version = build(args.output)
    print(f"Built WorkBuddy connector {version}: {args.output}")
