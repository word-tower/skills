"""Check multi-client artifacts and the one-source packaging boundary."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("unified_build", ROOT / "scripts/build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildTests(unittest.TestCase):
    def test_marketplace_registers_one_root_plugin(self):
        builder.validate()
        catalog = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(len(catalog["plugins"]), 1)
        self.assertEqual(catalog["plugins"][0]["source"], "./")
        self.assertNotIn("skills", catalog["plugins"][0])

    def test_archives_contain_only_manifest_sources_and_are_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            for target in builder.TARGETS:
                with self.subTest(target=target):
                    output = Path(temporary) / (target + ".zip")
                    builder.build(target, output)
                    original = output.read_bytes()
                    builder.build(target, output)
                    self.assertEqual(output.read_bytes(), original)
                    with zipfile.ZipFile(output) as archive:
                        names = archive.namelist()
                        self.assertEqual(len(names), len(set(names)))
                        self.assertFalse(any(part in name for name in names for part in (
                            "__pycache__", ".idea", ".git/", "server.py", ".env",
                            "release-skills", "CLAUDE.md", "CHANGELOG.md")))
                        prefix = "skills/wordtower/" if target == "workbuddy" else "wordtower/"
                        for name in builder.SKILL_FILES:
                            if target == "workbuddy" and (name == "SKILL.md" or name.startswith("references/")):
                                continue
                            self.assertEqual(archive.read(prefix + name), (builder.SKILL / name).read_bytes())
                        self.assertNotIn(".mcp.json", names)
                        if "INSTALL.md" in names:
                            self.assertNotIn(b"(../connectors/", archive.read("INSTALL.md"))

    def test_workbuddy_entry_uses_shared_routes_and_its_own_credentials(self):
        _, entries = builder.package_entries("workbuddy")
        text = entries["skills/wordtower/SKILL.md"].decode()
        source = (builder.SKILL / "SKILL.md").read_text()
        table = source[source.index("| 任务 | 文档 |"):source.index("连接凭据从")]
        self.assertIn(table, text)
        self.assertIn('version: "0.1.3"', text)
        self.assertNotIn("连接凭据从用户本地", text)
        self.assertNotIn("使用包内 scripts/request.py 调用", text)
        self.assertIn("凭证由 WorkBuddy 连接表单管理", text)

    def test_removed_client_zip_targets_are_rejected(self):
        for target in ("codex", "claude-code"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                builder.package_entries(target)

    def test_missing_sources_do_not_replace_existing_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing.zip"
            output.write_bytes(b"previous artifact")
            with patch.object(builder, "SKILL_FILES", builder.SKILL_FILES + ("scripts/missing.py",)):
                with self.assertRaises(ValueError):
                    builder.build("skill", output)
            self.assertEqual(output.read_bytes(), b"previous artifact")

    def test_symlink_sources_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source").write_text("data")
            (root / "linked").symlink_to(root / "source")
            with self.assertRaises(ValueError):
                builder.read(root, "linked")

    def test_all_command_writes_two_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/build.py"),
                "--all", "--output-dir", temporary], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list(Path(temporary).glob("*.zip"))), 2)
            invalid = subprocess.run([sys.executable, str(ROOT / "scripts/build.py"),
                "--all", "--output", str(Path(temporary) / "bad.zip")], capture_output=True)
            self.assertNotEqual(invalid.returncode, 0)


if __name__ == "__main__":
    unittest.main()
