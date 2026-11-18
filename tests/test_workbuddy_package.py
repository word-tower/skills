"""Exercise the packaged scripts, not source-tree substitutes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("connector_build", ROOT / "connectors/workbuddy/build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class WorkBuddyPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        package = self.directory / "connector.zip"
        self.assertEqual(builder.build(package), "0.1.4")
        with zipfile.ZipFile(package) as archive:
            self.assertEqual(len(archive.namelist()), 19)
            archive.extractall(self.directory)
        self.skill = self.directory / "skills/wordtower"

    def run_script(self, name, *arguments):
        env = dict(os.environ, WORDTOWER_API_KEY="intentionally-invalid")
        return subprocess.run([sys.executable, str(self.skill / "scripts" / name), *map(str, arguments)],
                              text=True, capture_output=True, env=env, cwd=self.directory)

    def test_all_shared_resources_and_links_survive_packaging(self):
        for directory, suffix in (("scripts", ".py"), ("references", ".md")):
            expected = {path.name for path in (ROOT / "skills/wordtower" / directory).glob("*" + suffix)}
            actual = {path.name for path in (self.skill / directory).glob("*" + suffix)}
            self.assertEqual(actual, expected)
        for name in builder.SHARED_FILES:
            packaged = (self.skill / name).read_bytes()
            original = (ROOT / "skills/wordtower" / name).read_bytes()
            if name.startswith("references/"):
                self.assertTrue(packaged.endswith(original), name)
            else:
                self.assertEqual(packaged, original, name)
        for name in ("SKILL.md", "references/protocol.md"):
            self.assertTrue((self.skill / name).is_file())
        self.assertFalse(any("__pycache__" in str(path) for path in self.skill.rglob("*")))
        for name in ("epub_select.py", "readpilot_validate.py", "youtube_subtitles.py"):
            self.assertEqual(self.run_script(name, "--help").returncode, 0)

    def test_prepare_text_without_key_or_api_configuration(self):
        (self.skill / "config.json").unlink()
        text = self.directory / "lesson.txt"
        text.write_text("Hello learner. 😀", encoding="utf-8")
        result = self.run_script("request.py", "--text", text, "--prepare-only", "--collection-id", "123")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["text"], "Hello learner. 😀")
        self.assertEqual(payload["collection_id"], "123")
        conflict = self.run_script("request.py", "--text", text, "--prepare-only",
                                   "--collection-id", "123", "--new-collection-title", "English")
        self.assertEqual(conflict.returncode, 2)

    def test_prepare_epub_hash_and_signed_upload(self):
        epub = self.directory / "book.epub"
        epub.write_bytes(b"test selected EPUB bytes")
        result = self.run_script("request.py", "--epub", epub, "--prepare-only")
        metadata = json.loads(result.stdout)
        self.assertEqual(metadata["sha256"], hashlib.sha256(epub.read_bytes()).hexdigest())
        self.assertEqual(metadata["api_name"], "/imports/upload-url")
        spec = importlib.util.spec_from_file_location("packaged_request", self.skill / "scripts/request.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        upload = {"upload_url": "https://bucket.cos.ap-test.myqcloud.com/private/book.epub?signature=secret",
                  "headers": {"Content-Type": "application/epub+zip"}, "upload_id": "a" * 32}
        response = self.directory / "upload.json"
        response.write_text(json.dumps({"data": upload}))
        requests = []
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, count): return b""
        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                return Reply()
        args = ["request.py", "--epub", str(epub), "--upload-response", str(response),
                "--expected-sha256", metadata["sha256"]]
        with patch.object(sys, "argv", args), patch.object(helper, "build_opener", return_value=Opener()), patch("builtins.print") as output:
            helper.main()
            prepared = json.loads(output.call_args.args[0])
        self.assertEqual(prepared, {"api_name": "/imports/epub/preview", "upload_id": "a" * 32})
        self.assertEqual(requests[0].get_method(), "PUT")
        self.assertEqual(requests[0].data, epub.read_bytes())
        self.assertNotIn("authorization", {name.lower() for name, _ in requests[0].header_items()})
        epub.write_bytes(b"changed")
        result = self.run_script("request.py", *args[1:])
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("signature=secret", result.stdout + result.stderr)
        for url, headers in [("https://evil.example/book", {}), (upload["upload_url"], {"Authorization": "secret"})]:
            with self.assertRaises(ValueError):
                helper.upload_epub(b"bytes", {**upload, "upload_url": url, "headers": headers})

    def test_prepare_json3_preserves_word_offsets(self):
        subtitle = self.directory / "lesson.json3"
        subtitle.write_text(json.dumps({"events": [{"tStartMs": 1000, "dDurationMs": 2000,
            "segs": [{"utf8": "Hello", "tOffsetMs": 0}, {"utf8": " world.", "tOffsetMs": 500}]}]}))
        result = self.run_script("request.py", "--youtube", "https://youtu.be/dQw4w9WgXcQ",
                                 "--subtitles", subtitle, "--prepare-only", "--new-collection-title", "English videos")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["new_collection_title"], "English videos")
        cue = payload["subtitles"][0]
        self.assertEqual(cue["segs"][1]["tOffsetMs"], 500)
        self.assertEqual(cue["start"], 1.0)

    def test_render_complete_notes_preserves_json_sidecar_and_refuses_overwrite(self):
        bundle = {"format_version": "wordtower.annotations.v1", "complete": True,
                  "items": [{"annotation_id": "1", "color": "sky", "text": "Hello learner.",
                    "note_text": "A note", "reader_link": "https://example.test/read", "anchor": {"start_offset": 0},
                    "revision": 2}]}
        source = self.directory / "notes.json"
        source.write_text(json.dumps(bundle))
        target = self.directory / "notes.md"
        result = self.run_script("export.py", source, "--bundle", "--output", target, "--format", "markdown")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(target.with_suffix(".md.json").read_text()), bundle)
        self.assertIn("A note", target.read_text())
        self.assertNotEqual(self.run_script("export.py", source, "--bundle", "--output", target, "--format", "markdown").returncode, 0)
        bundle["items"] *= 2
        source.write_text(json.dumps(bundle))
        self.assertNotEqual(self.run_script("export.py", source, "--bundle", "--output", self.directory / "duplicates.json").returncode, 0)
        bundle["complete"] = False
        source.write_text(json.dumps(bundle))
        self.assertNotEqual(self.run_script("export.py", source, "--bundle", "--output", self.directory / "partial.json").returncode, 0)

    def test_render_statistics_csv_from_mcp_envelope(self):
        source = self.directory / "stats.json"
        source.write_text(json.dumps({"data": {"format_version": "wordtower.statistics.v1", "timezone": "Asia/Shanghai",
            "days": [{"date": "2026-11-15", "reading_valid_seconds": 120}]}}))
        target = self.directory / "stats.csv"
        result = self.run_script("export.py", source, "--bundle", "--output", target, "--format", "csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Asia/Shanghai,2026-11-15,120", target.read_text())


if __name__ == "__main__":
    unittest.main()
