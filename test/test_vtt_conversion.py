"""Regression tests for VTT -> SRT conversion.

B29 - cue identifiers (the ``38``, ``39`` ... lines Crunchyroll writes before
      each timing line) were appended to the end of the previous cue's text,
      because the converter ignored blank lines and only reacted to timing
      lines. Every cue shipped with one stray number glued onto it.
"""

import unittest

from crunchyroll import convert_vtt_to_srt_custom

CRUNCHYROLL_VTT = """WEBVTT
X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000

37
00:00:01.000 --> 00:00:02.500 line:90%,end:95% align:middle position:50%
<i>Previously on Tokyo Ghoul...</i>

38
00:00:03.712 --> 00:00:05.881 line:90%,end:95% align:middle position:50%
[NEWSCASTER A] Early this
morning, authorities discovered

39
00:00:05.923 --> 00:00:09.093 line:90%,end:95% align:middle position:50%
several unidentified male bodies
inside the Aqua Building,

40
00:00:09.133 --> 00:00:12.846 line:90%,end:95% align:middle position:50%
a commercial center located
in Tokyo's 20th Ward.
"""

EXPECTED_SRT = """1
00:00:01,000 --> 00:00:02,500
Previously on Tokyo Ghoul...

2
00:00:03,712 --> 00:00:05,881
[NEWSCASTER A] Early this
morning, authorities discovered

3
00:00:05,923 --> 00:00:09,093
several unidentified male bodies
inside the Aqua Building,

4
00:00:09,133 --> 00:00:12,846
a commercial center located
in Tokyo's 20th Ward.
"""


class TestVttConversion(unittest.TestCase):
    def _convert(self, vtt_text, tmp_path):
        vtt = tmp_path / "in.vtt"
        srt = tmp_path / "out.srt"
        vtt.write_text(vtt_text, encoding="utf-8")
        convert_vtt_to_srt_custom(str(vtt), str(srt))
        return srt.read_text(encoding="utf-8")

    def test_cue_identifiers_are_not_glued_to_text(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            result = self._convert(CRUNCHYROLL_VTT, Path(tmp))

        self.assertEqual(result, EXPECTED_SRT)
        for stray in ("\n38\n", "\n39\n", "\n40\n", "\n37\n"):
            self.assertNotIn(stray, result, f"cue identifier {stray!r} leaked into cue text")

    def test_timing_settings_are_stripped(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            result = self._convert(CRUNCHYROLL_VTT, Path(tmp))

        self.assertNotIn("line:90%", result)
        self.assertNotIn("align:middle", result)
        self.assertNotIn("position:50%", result)

    def test_vtt_without_identifiers_still_converts(self):
        import tempfile
        from pathlib import Path

        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\nHello\n\n"
            "00:00:03.000 --> 00:00:04.000\nWorld\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = self._convert(vtt, Path(tmp))

        self.assertIn("1\n00:00:01,000 --> 00:00:02,000\nHello", result)
        self.assertIn("2\n00:00:03,000 --> 00:00:04,000\nWorld", result)


if __name__ == "__main__":
    unittest.main()
