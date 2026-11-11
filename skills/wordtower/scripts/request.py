#!/usr/bin/env python3
"""Words Skill helper. Credentials stay in the environment, never argv/output."""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_config():
    config = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())
    parsed = urlsplit(config["api_origin"])
    if (not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or not (parsed.scheme == "https" or
                parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})):
        raise ValueError("Invalid official API configuration")
    if config["gateway_path"] != "/api/agent/v1/gateway":
        raise ValueError("Unexpected gateway path")
    return config


def call(payload, config):
    key = os.environ.get("WORDTOWER_API_KEY", "")
    if not re.fullmatch(r"wtk-[A-Za-z0-9_-]{24}", key):
        raise ValueError("Configure WORDTOWER_API_KEY locally using the WordTower account connection page")
    payload = {**payload, "skill_version": config["skill_version"]}
    request = Request(config["api_origin"].rstrip("/") + config["gateway_path"],
                      data=json.dumps(payload, ensure_ascii=False).encode(), method="POST",
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with build_opener(NoRedirect).open(request, timeout=90) as response:
                data = json.load(response)
        except HTTPError as error:
            with error:
                try: data = json.loads(error.read(262144))
                except (ValueError, UnicodeError): raise ValueError(f"Words request failed (HTTP {error.code})") from None
        failure = data.get("error")
        if not failure:
            return data
        if failure.get("code") == "RATE_LIMITED" and attempt < 3:
            delay = int(failure.get("details", {}).get("retry_after", 60))
            if not 1 <= delay <= 60:
                raise ValueError("Invalid retry interval")
            time.sleep(delay)
            continue
        # A protocol failure is data, not a command or an upgrade script.
        print(json.dumps(data, ensure_ascii=False, indent=2))
        raise SystemExit(1)


def epub_preview(path, title, config):
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("EPUB must be at most 20 MiB")
    data = path.read_bytes()
    upload = call({"api_name": "/imports/upload-url", "file_name": path.name, "size_bytes": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()}, config)["data"]
    parsed = urlsplit(upload["upload_url"])
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".myqcloud.com") or parsed.username or parsed.password:
        raise ValueError("Unexpected upload destination")
    headers = upload["headers"]
    if any(name.lower() in {"authorization", "cookie"} for name in headers):
        raise ValueError("Unexpected upload credentials")
    request = Request(upload["upload_url"], method="PUT", data=data, headers=headers)
    try:
        with build_opener(NoRedirect).open(request, timeout=120) as response:
            response.read(1024)
    except HTTPError as error:
        error.close()
        raise ValueError(f"EPUB upload failed (HTTP {error.code}); do not submit an import") from None
    params = {"api_name": "/imports/epub/preview", "upload_id": upload["upload_id"]}
    if title: params["title"] = title
    return call(params, config)


def subtitle_time(value):
    match = re.fullmatch(r"(?:(\d{2,}):)?([0-5]\d):([0-5]\d)[.,](\d{3})", value)
    if not match:
        raise ValueError("Invalid subtitle timestamp")
    hours, minutes, seconds, millis = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def read_subtitles(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Subtitles must be at most 1 MiB")
    content = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        cues = json.loads(content)
        if not isinstance(cues, list):
            raise ValueError("Subtitle JSON must be a list")
        return cues
    if path.suffix.lower() not in {".srt", ".vtt"}:
        raise ValueError("Choose SRT, VTT or JSON subtitles")
    cues = []
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if not content.strip():
        raise ValueError("No timed subtitles found")
    for block in re.split(r"\n[ \t]*\n", content.strip()):
        lines = block.splitlines()
        first = lines[0].strip()
        if path.suffix.lower() == ".vtt" and (
            first.startswith("WEBVTT") or first in {"NOTE", "STYLE", "REGION"} or first.startswith("NOTE ")
        ):
            continue
        index = 0 if "-->" in first else 1
        if len(lines) <= index + 1 or "-->" not in lines[index]:
            raise ValueError("Invalid subtitle cue")
        times = lines[index].split("-->")
        if len(times) != 2:
            raise ValueError("Invalid subtitle cue")
        end_parts = times[1].strip().split()
        if not end_parts:
            raise ValueError("Missing subtitle end time")
        start = subtitle_time(times[0].strip())
        end = subtitle_time(end_parts[0])
        text = html.unescape(re.sub(r"<[^>]*>", "", "\n".join(lines[index + 1:]))).strip()
        if not text or end <= start:
            raise ValueError("Subtitle cue needs text and a positive duration")
        cues.append({"text": text, "start": start, "duration": end - start})
    if not cues:
        raise ValueError("No timed subtitles found")
    return cues


def main():
    parser = argparse.ArgumentParser(description="Call Words using the official package configuration")
    parser.add_argument("request_file", nargs="?", help="JSON request file, without credentials")
    parser.add_argument("--text", type=Path, help="UTF-8 plaintext file to preview")
    parser.add_argument("--epub", type=Path, help="EPUB file to upload and preview")
    parser.add_argument("--subtitles", type=Path, help="SRT, VTT or timed JSON subtitles")
    parser.add_argument("--youtube", help="YouTube video URL for the subtitles")
    parser.add_argument("--title", help="Title for a file import")
    args = parser.parse_args()
    if sum(bool(value) for value in (args.request_file, args.text, args.epub, args.subtitles)) != 1:
        parser.error("choose one JSON request, --text, --epub or --subtitles")
    if bool(args.youtube) != bool(args.subtitles):
        parser.error("--youtube and --subtitles must be used together")
    config = load_config()
    if args.subtitles:
        result = call({"api_name": "/imports/youtube/preview", "title": args.title or args.subtitles.stem,
                       "url": args.youtube, "subtitles": read_subtitles(args.subtitles)}, config)
    elif args.epub:
        result = epub_preview(args.epub, args.title, config)
    elif args.text:
        if args.text.stat().st_size > 1024 * 1024:
            raise ValueError("Text file must be at most 1 MiB")
        result = call({"api_name": "/imports/preview", "title": args.title or args.text.stem,
                       "text": args.text.read_text(encoding="utf-8-sig")}, config)
    else:
        path = Path(args.request_file)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("Request file must be at most 1 MiB")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict): raise ValueError("Request must be a JSON object")
        result = call(payload, config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, URLError):
        # Never stringify network errors: they can contain presigned URLs.
        print("Request failed. Check WORDTOWER_API_KEY, API configuration, file encoding and connection; preserve the original idempotency key.", file=sys.stderr)
        raise SystemExit(1)
