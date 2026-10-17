"""Tests for ASS subtitle handling.

B30 - Crunchyroll serves its translator subtitles as .ass, not .vtt. Those
      tracks should be embedded in the MKV with their styling intact rather than
      silently converted, with an escape hatch to force SRT and a fallback when
      the container (mp4) cannot hold ASS.
"""

import tempfile
import unittest
from pathlib import Path

import config
from crunchyroll import (
    convert_ass_to_srt_custom,
    resolve_keep_ass_subtitles,
    subtitle_needs_srt,
)

SAMPLE_ASS = """[Script Info]
Title: Sample
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour
Style: Default,Arial,20,&H00FFFFFF

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:03.71,0:00:05.88,On Top,,0000,0000,0000,,"{\\pos(320,20)}[NEWSCASTER A] Early this\\Nmorning, authorities discovered"
Comment: 0,0:00:06.00,0:00:07.00,Default,,0000,0000,0000,,this comment is skipped
Dialogue: 0,0:00:09.13,0:00:12.84,Default,,0000,0000,0000,,A commercial center, located\\Nin Tokyo's 20th Ward.
Dialogue: 0,0:00:13.00,0:00:14.00,Default,,0000,0000,0000,,non\\hbreaking space
"""

EXPECTED_SRT = """1
00:00:03,710 --> 00:00:05,880
[NEWSCASTER A] Early this
morning, authorities discovered

2
00:00:09,130 --> 00:00:12,840
A commercial center, located
in Tokyo's 20th Ward.

3
00:00:13,000 --> 00:00:14,000
non breaking space
"""


class TestAssToSrt(unittest.TestCase):
    def _convert(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            ass = Path(tmp) / "in.ass"
            srt = Path(tmp) / "out.srt"
            ass.write_text(text, encoding="utf-8")
            convert_ass_to_srt_custom(str(ass), str(srt))
            return srt.read_text(encoding="utf-8")

    def test_dialogue_becomes_srt(self):
        self.assertEqual(self._convert(SAMPLE_ASS), EXPECTED_SRT)

    def test_comments_are_skipped(self):
        self.assertNotIn("this comment is skipped", self._convert(SAMPLE_ASS))

    def test_override_tags_and_breaks_are_stripped(self):
        result = self._convert(SAMPLE_ASS)
        self.assertNotIn("{\\pos", result)
        self.assertNotIn("\\N", result)
        self.assertNotIn("\\h", result)

    def test_text_with_commas_survives(self):
        self.assertIn("A commercial center, located", self._convert(SAMPLE_ASS))

    def test_non_events_sections_are_ignored(self):
        # The Style line above contains a comma and starts with "Style:"; it must
        # not be mistaken for a cue.
        self.assertNotIn("Arial", self._convert(SAMPLE_ASS))

    def test_empty_ass_yields_empty_srt(self):
        self.assertEqual(self._convert("[Script Info]\nTitle: nothing\n"), "")


class TestKeepAssSetting(unittest.TestCase):
    def test_cli_choice_overrides_config(self):
        self.assertTrue(resolve_keep_ass_subtitles(True))
        self.assertFalse(resolve_keep_ass_subtitles(False))

    def test_defaults_to_true(self):
        original = getattr(config, "keep_ass_subtitles", None)
        try:
            config.keep_ass_subtitles = True
            self.assertTrue(resolve_keep_ass_subtitles())
        finally:
            config.keep_ass_subtitles = original

    def test_config_false_is_honoured(self):
        original = getattr(config, "keep_ass_subtitles", None)
        try:
            config.keep_ass_subtitles = False
            self.assertFalse(resolve_keep_ass_subtitles())
        finally:
            config.keep_ass_subtitles = original


class TestSubtitleNeedsSrt(unittest.TestCase):
    def test_vtt_always_converts(self):
        self.assertTrue(subtitle_needs_srt("vtt", True, "mkv"))
        self.assertTrue(subtitle_needs_srt("VTT", False, "mp4"))

    def test_ass_is_kept_for_mkv(self):
        self.assertFalse(subtitle_needs_srt("ass", True, "mkv"))
        self.assertFalse(subtitle_needs_srt("ASS", True, "MKV"))

    def test_ass_converts_when_asked(self):
        self.assertTrue(subtitle_needs_srt("ass", False, "mkv"))

    def test_ass_converts_for_mp4(self):
        self.assertTrue(subtitle_needs_srt("ass", True, "mp4"))

    def test_other_formats_are_left_alone(self):
        self.assertFalse(subtitle_needs_srt("srt", True, "mkv"))
        self.assertFalse(subtitle_needs_srt("", True, "mkv"))


if __name__ == "__main__":
    unittest.main()
