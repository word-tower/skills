#!/usr/bin/env python3
"""Check ReadPilot draft enums and anchors locally before a write."""
import argparse
import json
from pathlib import Path
import sys


INTENTS = {"quote", "term", "contrast", "key_point", "reference", "context"}
EMPHASES = {"subtle", "normal", "strong"}


def read_object(path):
    with path.open("rb") as source:
        raw = source.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError(f"{path.name}: file exceeds 1 MiB")
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a JSON object")
    return data


def read_context(paths, draft):
    source = {}
    chapter = None
    for path in paths:
        payload = read_object(path)
        data = payload.get("data", payload)
        if not isinstance(data, dict) or not isinstance(data.get("sentences"), list):
            raise ValueError(f"{path.name}: expected /readpilot/context data")
        identity = (data.get("course_id"), data.get("content_version"))
        if not all(isinstance(field, str) and field for field in identity):
            raise ValueError(f"{path.name}: missing course ID or content version")
        if chapter is not None and identity != chapter:
            raise ValueError("Context files refer to different chapters or versions")
        chapter = identity
        for row in data["sentences"]:
            if (not isinstance(row, dict) or not isinstance(row.get("sentence_id"), str)
                    or not isinstance(row.get("text"), str)
                    or type(row.get("start_offset")) is not int or type(row.get("end_offset")) is not int):
                raise ValueError(f"{path.name}: malformed context sentence")
            key = row["sentence_id"]
            if key in source and source[key] != row:
                raise ValueError(f"{path.name}: conflicting sentence ID {key}")
            source[key] = row
    if chapter:
        for field, expected in zip(("course_id", "content_version"), chapter):
            if field in draft and draft[field] != expected:
                raise ValueError(f"{field}: draft does not match the context")
    return source


def validate(draft, source):
    errors = []

    def issue(path, message):
        errors.append({"path": path, "message": message})

    def unique(text, phrase, path):
        if not isinstance(phrase, str) or not phrase.strip():
            issue(path, "填写原文或口播中的一段非空原样文本")
            return
        first = text.find(phrase)
        if first < 0:
            issue(path, "找不到该短语，核对大小写、空格和标点")
        elif text.find(phrase, first + 1) >= 0:
            issue(path, "该短语出现多次，请选更长且唯一的原样片段")

    def anchors(items, path, trigger):
        if not isinstance(items, list):
            issue(path, "应为数组")
            return
        for index, item in enumerate(items):
            base = f"{path}.{index}"
            if not isinstance(item, dict):
                issue(base, "应为对象")
                continue
            sentence_id = item.get("sentence_id")
            row = source.get(sentence_id) if isinstance(sentence_id, str) else None
            if row is None:
                issue(f"{base}.sentence_id", "上下文中没有此句，请补取相应原文或核对 ID")
                continue
            if trigger and row["end_offset"] > trigger["end_offset"]:
                issue(f"{base}.sentence_id", "引用句晚于触发句")
            if item.get("quote") is not None:
                unique(row["text"], item["quote"], f"{base}.quote")

    cues = draft.get("cues")
    if not isinstance(cues, list) or not cues:
        return [{"path": "cues", "message": "应为非空数组"}]
    previous_start = -1
    seen_ids = set()
    for i, cue in enumerate(cues):
        base = f"cues.{i}"
        if not isinstance(cue, dict):
            issue(base, "应为对象")
            continue
        cue_id = cue.get("cue_id")
        if not isinstance(cue_id, str) or not cue_id or cue_id in seen_ids:
            issue(f"{base}.cue_id", "讲解点编号必须存在且唯一")
        else:
            seen_ids.add(cue_id)
        sentence_id = cue.get("trigger_sentence_id")
        trigger = source.get(sentence_id) if isinstance(sentence_id, str) else None
        if trigger is None:
            issue(f"{base}.trigger_sentence_id", "上下文中没有此触发句，请核对句子 ID")
        else:
            start = trigger["start_offset"]
            if start <= previous_start:
                issue(f"{base}.trigger_sentence_id", "触发句须按原文排序且不能重复")
            previous_start = start
        steps = cue.get("steps")
        if not isinstance(steps, list) or not steps:
            issue(f"{base}.steps", "应为非空数组")
            continue
        for j, step in enumerate(steps):
            step_path = f"{base}.steps.{j}"
            if not isinstance(step, dict) or not isinstance(step.get("speech_text"), str):
                issue(f"{step_path}.speech_text", "应为口播文本")
                continue
            anchors(step.get("highlights", []), f"{step_path}.highlights", trigger)
            annotations = step.get("annotations", [])
            if not isinstance(annotations, list):
                issue(f"{step_path}.annotations", "应为数组")
                continue
            for k, mark in enumerate(annotations):
                mark_path = f"{step_path}.annotations.{k}"
                if not isinstance(mark, dict):
                    issue(mark_path, "应为对象")
                    continue
                for field, allowed in (("intent", INTENTS), ("emphasis", EMPHASES)):
                    if field in mark and (not isinstance(mark[field], str) or mark[field] not in allowed):
                        issue(f"{mark_path}.{field}", "允许值为 " + ", ".join(sorted(allowed)) + "，也可省略")
                unique(step["speech_text"], mark.get("spoken_text"), f"{mark_path}.spoken_text")
                anchors(mark.get("source_anchors"), f"{mark_path}.source_anchors", trigger)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path, help="JSON with a cues array")
    parser.add_argument("--context", type=Path, action="append", required=True,
                        help="JSON from /readpilot/context, repeat for multiple pages")
    args = parser.parse_args()
    try:
        draft = read_object(args.draft)
        errors = validate(draft, read_context(args.context, draft))
    except (OSError, ValueError) as exc:
        print(f"Cannot validate the ReadPilot draft: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
