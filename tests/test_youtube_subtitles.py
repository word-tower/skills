import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/wordtower/scripts"))
import youtube_subtitles as youtube

VIDEO_ID = "aDblEBU41nA"
VIDEO = "https://www.youtube.com/watch?v=" + VIDEO_ID
CAPTION = "https://www.youtube.com/api/timedtext?v=" + VIDEO_ID + "&lang=en&signature=private"
JSON3 = {"events": [{"tStartMs": 1000, "dDurationMs": 2000, "segs": [
    {"utf8": "Hello", "tOffsetMs": 0}, {"utf8": " world.", "tOffsetMs": 500}]}]}


def player(language="en", kind="asr"):
    return {"videoDetails": {"videoId": VIDEO_ID, "title": "A lesson"},
            "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
                {"languageCode": language, "kind": kind, "baseUrl": CAPTION}]}}}


class YouTubeSubtitlesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "output"

    def test_single_video_urls_and_playlist_rejection(self):
        for value in (VIDEO_ID, VIDEO, "https://youtu.be/" + VIDEO_ID, "https://www.youtube.com/shorts/" + VIDEO_ID,
                      VIDEO + "&list=PLanything"):
            self.assertEqual(youtube.video_identity(value), (VIDEO_ID, VIDEO))
        for value in ("https://youtube.com.evil.test/watch?v=" + VIDEO_ID,
                      "https://www.youtube.com/playlist?list=123", "https://www.youtube.com/@channel",
                      "https://user:secret@youtube.com/watch?v=" + VIDEO_ID):
            with self.subTest(value=value), self.assertRaises(youtube.SubtitleError):
                youtube.video_identity(value)

    def test_native_json3_download_preserves_words_without_external_tool(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            if url.startswith(VIDEO):
                return 'var ytInitialPlayerResponse = ' + json.dumps(player()) + ';'
            self.assertIn("fmt=json3", url)
            return json.dumps(JSON3)
        with patch.object(youtube, "fetch", side_effect=fetch):
            result = youtube.prepare_video(VIDEO, self.output)
        self.assertEqual(result["provider"], "watch-page")
        self.assertTrue(result["word_timing_available"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(Path(result["subtitle_file"]).read_text()), JSON3)
        request = json.loads(Path(result["preview_request"]).read_text())
        self.assertEqual(request["subtitles"][0]["segs"][1]["tOffsetMs"], 500)
        self.assertEqual(request["url"], VIDEO)
        self.assertNotIn("signature=private", json.dumps(result))

    def test_manual_xml_retains_original_time_without_claiming_words(self):
        with patch.object(youtube, "player_sources", return_value=iter([("web", player(kind="manual"))])), \
             patch.object(youtube, "fetch", return_value='<transcript><text start="1.25" dur="2.5">Hello &amp; world.</text></transcript>'):
            result = youtube.prepare_video(VIDEO, self.output)
        self.assertFalse(result["word_timing_available"])
        cue = json.loads(Path(result["preview_request"]).read_text())["subtitles"][0]
        self.assertEqual(cue, {"text": "Hello & world.", "start": 1.25, "duration": 2.5})

    def test_list_does_not_download_caption_or_create_files(self):
        with patch.object(youtube, "player_sources", return_value=iter([("web", player())])), \
             patch.object(youtube, "caption_payload", side_effect=AssertionError("unexpected subtitle download")):
            result = youtube.prepare_video(VIDEO, self.output, list_only=True)
        self.assertEqual(result["available"], [{"language": "en", "kind": "automatic"}])
        self.assertFalse(self.output.exists())
        self.assertNotIn("signature=private", json.dumps(result))

    def test_language_unavailable_does_not_translate_or_create_output(self):
        with patch.object(youtube, "player_sources", return_value=iter([("web", player("ja"))])):
            with self.assertRaises(youtube.SubtitleError) as error:
                youtube.prepare_video(VIDEO, self.output)
        self.assertEqual(error.exception.code, "LANGUAGE_UNAVAILABLE")
        self.assertNotIn("source", error.exception.details["available"][0])
        self.assertFalse(self.output.exists())

    def test_original_automatic_track_is_preferred_and_translated_track_excluded(self):
        data = player(kind="manual")
        data["captions"]["playerCaptionsTracklistRenderer"]["captionTracks"] += [
            {"languageCode": "en-US", "kind": "asr", "baseUrl": CAPTION},
            {"languageCode": "zh", "kind": "asr", "baseUrl": CAPTION + "&tlang=zh"}]
        available = youtube.tracks(data, VIDEO_ID)
        self.assertEqual(len(available), 2)
        self.assertEqual(youtube.choose_track(available, "en")["kind"], "automatic")

    def test_empty_page_caption_tries_innertube(self):
        calls = []
        page = ('"INNERTUBE_API_KEY":"public-player-key", "INNERTUBE_CLIENT_VERSION":"web-version", '
                '"VISITOR_DATA":"visitor-data"; var ytInitialPlayerResponse = ' + json.dumps(player()) + ';')
        def fetch(url, **kwargs):
            calls.append((url, kwargs))
            if url.startswith(VIDEO): return page
            if "youtubei/v1/player" in url:
                self.assertEqual(kwargs["payload"]["videoId"], VIDEO_ID)
                self.assertEqual(kwargs["payload"]["context"]["client"]["clientName"], "WEB")
                return json.dumps(player())
            return "" if len(calls) == 2 else json.dumps(JSON3)
        with patch.object(youtube, "fetch", side_effect=fetch):
            result = youtube.prepare_video(VIDEO, self.output)
        self.assertEqual(result["provider"], "web")
        self.assertEqual(len(calls), 4)

    def test_empty_or_invalid_caption_fails_cleanly(self):
        for content in ("", "<html>Blocked</html>", '{"events":[]}',
                        '<!DOCTYPE transcript [<!ENTITY x "bad">]><transcript/>'):
            with self.subTest(content=content), \
                 patch.object(youtube, "player_sources", return_value=iter([("web", player())])), \
                 patch.object(youtube, "fetch", return_value=content), self.assertRaises(youtube.SubtitleError):
                youtube.prepare_video(VIDEO, self.output)
            self.assertFalse(self.output.exists() and list(self.output.iterdir()))

    def test_no_captions_and_unavailable_video(self):
        for data, code in (({"videoDetails": {"videoId": VIDEO_ID}}, "NO_SUBTITLES"),
                           ({"playabilityStatus": {"status": "LOGIN_REQUIRED"}}, "ACCESS_REQUIRED")):
            with patch.object(youtube, "player_sources", return_value=iter([("web", data)])):
                with self.assertRaises(youtube.SubtitleError) as error:
                    youtube.prepare_video(VIDEO, self.output)
            self.assertEqual(error.exception.code, code)

    def test_http_requests_never_send_wordtower_credentials_or_follow_redirects(self):
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'{}'
        class Opener:
            def open(self, request, timeout):
                calls.append(request)
                return Response()
        with patch.dict("os.environ", {"WORDTOWER_API_KEY": "private-key"}), \
             patch.object(youtube, "build_opener", return_value=Opener()) as opener:
            youtube.fetch(VIDEO)
        self.assertIs(opener.call_args.args[0], youtube.NoRedirect)
        headers = {name.lower(): value for name, value in calls[0].header_items()}
        self.assertNotIn("authorization", headers)
        self.assertNotIn("cookie", headers)
        with self.assertRaises(youtube.SubtitleError):
            youtube.fetch("https://evil.example/api/timedtext")

    def test_rate_limit_has_sanitized_error(self):
        with patch.object(youtube, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError(CAPTION, 429, "signature=private", {}, None)
            with self.assertRaises(youtube.SubtitleError) as error:
                youtube.fetch(CAPTION)
        self.assertEqual(error.exception.code, "RATE_LIMITED")
        self.assertNotIn("signature=private", str(error.exception))

    def test_negative_and_boolean_times_are_rejected(self):
        for start, duration in ((-0.5, 1), (True, 1), (0, True)):
            with self.subTest(start=start, duration=duration), self.assertRaises(youtube.SubtitleError):
                youtube.validate_cues([{"text": "Hello", "start": start, "duration": duration}])

    def test_out_of_order_cues_fail_and_repeated_runs_keep_separate_outputs(self):
        with self.assertRaises(youtube.SubtitleError):
            youtube.validate_cues([{"text": "first", "start": 2, "duration": 1}, {"text": "second", "start": 1, "duration": 1}])
        def run():
            with patch.object(youtube, "player_sources", return_value=iter([("web", player())])), \
                 patch.object(youtube, "fetch", return_value=json.dumps(JSON3)):
                return youtube.prepare_video(VIDEO, self.output)
        first, second = run(), run()
        self.assertNotEqual(first["preview_request"], second["preview_request"])
        self.assertTrue(Path(first["preview_request"]).is_file())


if __name__ == "__main__":
    unittest.main()
