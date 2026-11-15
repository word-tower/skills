#!/usr/bin/env python3
"""Fetch one YouTube video's existing captions using only Python's standard library."""
import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener
from xml.etree import ElementTree

from request import NoRedirect, read_subtitles

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/134.0.0.0 Safari/537.36"
CLIENTS = (("WEB", "1", None, USER_AGENT),
           ("ANDROID", "3", "20.10.38", "com.google.android.youtube/20.10.38 (Linux; U; Android 14; en_US)"),
           ("IOS", "5", "20.10.4", "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3 like Mac OS X; en_US)"))


class SubtitleError(Exception):
    def __init__(self, code, message, details=None):
        self.code, self.message, self.details = code, message, details or {}
        super().__init__(message)


def video_identity(value):
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value, "https://www.youtube.com/watch?v=" + value
    try:
        parsed = urlsplit(value)
        parts = parsed.path.strip("/").split("/")
        hosts = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
                 "youtube-nocookie.com", "www.youtube-nocookie.com"}
        if (parsed.scheme not in {"https", "http"} or parsed.hostname not in hosts
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}):
            raise ValueError()
        if parsed.hostname == "youtu.be" and len(parts) == 1:
            identity = parts[0]
        elif parsed.path == "/watch":
            identity = parse_qs(parsed.query).get("v", [""])[0]
        elif len(parts) == 2 and parts[0] in {"embed", "shorts", "live", "v"}:
            identity = parts[1]
        else:
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identity):
            raise ValueError()
    except ValueError:
        raise SubtitleError("INVALID_VIDEO", "请提供单个 YouTube 视频链接或 11 位视频 ID") from None
    return identity, "https://www.youtube.com/watch?v=" + identity



def fetch(url, *, payload=None, headers=None, limit=8 * 1024 * 1024):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com"}
            or parsed.username or parsed.password or parsed.port not in {None, 443}
            or parsed.path not in {"/watch", "/youtubei/v1/player", "/api/timedtext"}):
        raise SubtitleError("INVALID_SOURCE", "字幕来源不是受支持的 YouTube 地址")
    request_headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9", **(headers or {})}
    data = None
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    try:
        with build_opener(NoRedirect).open(Request(url, data=data, headers=request_headers), timeout=20) as response:
            raw = response.read(limit + 1)
    except HTTPError as error:
        status = error.code
        error.close()
        if status == 429:
            raise SubtitleError("RATE_LIMITED", "YouTube 暂时限流，请稍后再试") from None
        raise SubtitleError("ACCESS_REQUIRED", "YouTube 未返回可访问的字幕，请检查网络或提供字幕文件") from None
    except (URLError, OSError):
        raise SubtitleError("FETCH_FAILED", "无法访问 YouTube，请检查本机网络后重试") from None
    if len(raw) > limit:
        raise SubtitleError("INPUT_TOO_LARGE", "YouTube 返回内容超出处理限制")
    return raw.decode("utf-8-sig")


def page_value(page, name):
    match = re.search(r'"' + re.escape(name) + r'"\s*:\s*("(?:[^"\\]|\\.)*")', page)
    return json.loads(match.group(1)) if match else ""


def player_sources(identity, url):
    page = fetch(url + "&hl=en")
    decoder = json.JSONDecoder()
    initial = re.search(r'(?:var\s+)?ytInitialPlayerResponse\s*=\s*|window\["ytInitialPlayerResponse"\]\s*=\s*', page)
    yielded = False
    if initial:
        try:
            player, _ = decoder.raw_decode(page[initial.end():])
            if isinstance(player, dict):
                yielded = True
                yield "watch-page", player
        except ValueError:
            pass
    api_key = page_value(page, "INNERTUBE_API_KEY")
    version = page_value(page, "INNERTUBE_CLIENT_VERSION") or page_value(page, "clientVersion")
    visitor = page_value(page, "VISITOR_DATA") or page_value(page, "visitorData")
    last_error = SubtitleError("ACCESS_REQUIRED", "无法取得字幕目录，YouTube 可能要求访问验证")
    if api_key:
        endpoint = "https://www.youtube.com/youtubei/v1/player?" + urlencode({"key": api_key, "prettyPrint": "false"})
        for name, header_name, fixed_version, user_agent in CLIENTS:
            client_version = fixed_version or version
            if not client_version:
                continue
            client = {"clientName": name, "clientVersion": client_version, "hl": "en", "gl": "US"}
            if visitor:
                client["visitorData"] = visitor
            try:
                body = fetch(endpoint, payload={"videoId": identity, "context": {"client": client}},
                    headers={"User-Agent": user_agent, "Origin": "https://www.youtube.com", "Referer": url,
                             "X-YouTube-Client-Name": header_name, "X-YouTube-Client-Version": client_version})
                player = json.loads(body)
                if not isinstance(player, dict):
                    raise ValueError()
            except (ValueError, SubtitleError) as error:
                last_error = error if isinstance(error, SubtitleError) else last_error
                continue
            yielded = True
            yield name.lower(), player
    if not yielded:
        raise last_error


def tracks(player, identity):
    details = player.get("videoDetails") or {}
    if details.get("videoId") != identity:
        if (player.get("playabilityStatus") or {}).get("status") == "LOGIN_REQUIRED":
            raise SubtitleError("ACCESS_REQUIRED", "YouTube 要求登录或访问验证，请提供已有字幕文件")
        raise SubtitleError("VIDEO_UNAVAILABLE", "无法访问指定视频")
    rows = (player.get("captions") or {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
    available = []
    for row in rows:
        language, source = row.get("languageCode", ""), row.get("baseUrl", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", language) or not source or parse_qs(urlsplit(source).query).get("tlang"):
            continue
        available.append({"language": language, "kind": "automatic" if row.get("kind") == "asr" else "manual", "source": source})
    return available


def choose_track(available, language):
    matching = [track for track in available if track["language"] == language or track["language"].startswith(language + "-")]
    if not matching:
        raise SubtitleError("LANGUAGE_UNAVAILABLE", "没有所选语言的可用原始字幕", {"available": [
            {key: track[key] for key in ("language", "kind")} for track in available]})
    return min(matching, key=lambda track: (track["kind"] != "automatic", track["language"] != language, track["language"]))


def caption_payload(track):
    parsed = urlsplit(track["source"])
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["fmt"] = ["json3"]
    content = fetch(urlunsplit(parsed._replace(query=urlencode(query, doseq=True))), limit=1024 * 1024)
    if not content.strip():
        raise SubtitleError("EMPTY_SUBTITLES", "YouTube 字幕响应为空，请稍后重试或提供字幕文件")
    try:
        payload = json.loads(content)
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise ValueError()
        return "json3", payload
    except ValueError:
        if "<!DOCTYPE" in content.upper() or "<!ENTITY" in content.upper():
            raise SubtitleError("INVALID_SUBTITLES", "字幕 XML 含不支持的声明") from None
        try:
            root = ElementTree.fromstring(content)
            cues = [{"text": html.unescape("".join(row.itertext())), "start": float(row.attrib["start"]),
                     "duration": float(row.attrib["dur"])} for row in root.findall("text")]
            if not cues:
                raise ValueError()
            return "json", cues
        except (ValueError, KeyError, ElementTree.ParseError):
            raise SubtitleError("INVALID_SUBTITLES", "YouTube 未返回有效的时间戳字幕") from None


def validate_cues(cues):
    if not isinstance(cues, list) or not cues or len(cues) > 10000:
        raise SubtitleError("INVALID_SUBTITLES", "字幕为空或片段数超出导入限制")
    previous_start = -1
    for cue in cues:
        start, duration = cue.get("start"), cue.get("duration")
        if (not isinstance(cue.get("text"), str) or not cue["text"].strip() or "\x00" in cue["text"]
                or not isinstance(start, (int, float)) or not isinstance(duration, (int, float))
                or not math.isfinite(start) or not math.isfinite(duration)
                or isinstance(start, bool) or isinstance(duration, bool)
                or start < 0 or start < previous_start or duration <= 0):
            raise SubtitleError("INVALID_SUBTITLES", "字幕缺少真实、有序的时间戳或有效正文")
        previous_start = start



def save_preview(identity, url, title, track, output):
    extension, payload = caption_payload(track)
    output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=identity + "-", dir=output))
    try:
        source = directory / ("subtitles." + track["language"] + "." + extension)
        source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        cues = read_subtitles(source)
        validate_cues(cues)
        request = {"api_name": "/imports/youtube/preview", "title": title, "url": url, "subtitles": cues}
        data = json.dumps(request, ensure_ascii=False, allow_nan=False).encode()
        if len(data) > 1024 * 1024:
            raise SubtitleError("INPUT_TOO_LARGE", "字幕请求超出 1 MiB，请缩小材料范围")
        request_file = directory / "preview-request.json"
        with request_file.open("xb") as target:
            target.write(data)
        return {"video_id": identity, "url": url, "title": title, "language": track["language"], "kind": track["kind"],
                "format": extension, "subtitle_file": str(source.resolve()), "preview_request": str(request_file.resolve()),
                "subtitle_count": len(cues), "word_timing_available": any(cue.get("segs") for cue in cues),
                "subtitle_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    except BaseException:
        shutil.rmtree(directory)
        raise


def prepare_video(value, output, language="en", title=None, *, list_only=False):
    identity, url = video_identity(value)
    if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", language):
        raise SubtitleError("INVALID_LANGUAGE", "请填写单个语言代码，例如 en 或 en-US")
    last_error = SubtitleError("NO_SUBTITLES", "此视频没有可获取的原始字幕，请提供已有字幕文件")
    for provider, player in player_sources(identity, url):
        try:
            available = tracks(player, identity)
            if not available:
                continue
            video_title = title or player["videoDetails"].get("title") or identity
            if list_only:
                return {"video_id": identity, "url": url, "title": video_title, "available": [
                    {key: track[key] for key in ("language", "kind")} for track in available]}
            track = choose_track(available, language)
            # Try the chosen original track, then other matching original tracks
            # if an advertised caption endpoint returns an empty response.
            candidates = [track] + [row for row in available if row is not track and (
                row["language"] == language or row["language"].startswith(language + "-"))]
            for candidate in candidates:
                try:
                    return {**save_preview(identity, url, video_title, candidate, output), "provider": provider}
                except SubtitleError as error:
                    last_error = error
        except SubtitleError as error:
            last_error = error
    raise last_error


def main():
    parser = argparse.ArgumentParser(description="Get one YouTube video's existing subtitles using Python's standard library")
    parser.add_argument("video", help="Single video URL or 11-character ID")
    parser.add_argument("--output", type=Path, default=Path("wordtower-youtube"))
    parser.add_argument("--language", default="en", help="One original subtitle language, default en")
    parser.add_argument("--title")
    parser.add_argument("--list", action="store_true", help="List original subtitle languages")
    args = parser.parse_args()
    result = prepare_video(args.video, args.output, args.language, args.title, list_only=args.list)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except SubtitleError as error:
        print(json.dumps({"error": {"code": error.code, "message": error.message, "details": error.details}}, ensure_ascii=False))
        raise SystemExit(1)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print(json.dumps({"error": {"code": "INVALID_SUBTITLES", "message": "无法解析字幕或写入文件，请检查来源及本地环境"}}, ensure_ascii=False))
        raise SystemExit(1)
