#!/usr/bin/env python3
"""Download authorized, paginated records and write a private local export."""
import argparse
import csv
import json
import os
from pathlib import Path
import sys
from urllib.error import URLError

from request import call, load_config


def collect(payload, config):
    if payload.get("api_name") == "/statistics/export":
        return call(payload, config)["data"]
    if payload.get("api_name") not in {"/annotations/list", "/annotations/export"}:
        raise ValueError("Use an annotation or statistics export request")
    if payload.get("cursor"):
        raise ValueError("Start an export without a cursor")
    payload = {"limit": 50, **payload, "api_name": "/annotations/export"}
    items, seen, cursors = [], set(), set()
    while True:
        page = call(payload, config)["data"]
        for item in page["items"]:
            if item["annotation_id"] in seen:
                raise ValueError("Duplicate annotation in export")
            seen.add(item["annotation_id"])
            items.append(item)
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
        if not cursor or cursor in cursors:
            raise ValueError("Invalid pagination")
        cursors.add(cursor)
        payload["cursor"] = cursor
    return {"format_version": "wordtower.annotations.v1", "items": items,
            "complete": True, "consistency": "per_record_version"}


def write_export(bundle, target, format):
    is_stats = bundle["format_version"] == "wordtower.statistics.v1"
    if format == "csv" and not is_stats:
        raise ValueError("Use JSON or Markdown for annotations; CSV cannot preserve anchors")
    if format == "markdown" and is_stats:
        raise ValueError("Use JSON or CSV for statistics")
    # Never overwrite another export; an interrupted write removes its own partial file.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            if format == "json":
                json.dump(bundle, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.write("\n")
            elif format == "csv":
                writer = csv.DictWriter(output, fieldnames=["timezone", *bundle["days"][0]])
                writer.writeheader()
                writer.writerows({"timezone": bundle["timezone"], **day} for day in bundle["days"])
            else:
                output.write("# 词塔笔记导出\n\n位置、ID 和版本保存在配套 JSON 中；此 Markdown 用于阅读。\n\n")
                for item in bundle["items"]:
                    output.write(f"## 笔记 {item['annotation_id']} · {item['color']}\n\n")
                    output.write("\n".join("> " + line for line in item["text"].splitlines()) + "\n\n")
                    output.write((item.get("note_text") or "") + "\n\n")
                    output.write(f"[回到词塔]({item['reader_link']})\n\n")
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="Export WordTower notes or reading statistics locally")
    parser.add_argument("request_file", type=Path, help="JSON request without credentials")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=("json", "csv", "markdown"), default="json")
    args = parser.parse_args()
    if args.request_file.stat().st_size > 1024 * 1024:
        raise ValueError("Request file too large")
    payload = json.loads(args.request_file.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    bundle = collect(payload, load_config())
    # Markdown always has an exact JSON sidecar for later write-back.
    if args.format == "markdown":
        sidecar = args.output.with_suffix(args.output.suffix + ".json")
        if args.output.exists() or sidecar.exists():
            raise ValueError("Choose new export paths")
        write_export(bundle, sidecar, "json")
    write_export(bundle, args.output, args.format)
    print(json.dumps({"output": str(args.output.resolve()), "format": args.format,
                      "records": len(bundle.get("items", bundle.get("days", [])))}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, URLError):
        print("Export failed; check the response and choose a new output path. Do not treat a partial export as complete.", file=sys.stderr)
        raise SystemExit(1)
