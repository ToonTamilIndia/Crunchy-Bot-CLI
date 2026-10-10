"""Regression tests for two defects in the track-KID parser introduced with the
DRM key-selection fix, plus the Python 3.11 test-harness incompatibility.

B10 - the AdaptationSet fallback walked the whole subtree with iter(), reaching
sibling Representations, so a clear rendition inherited a protected sibling's
key ID and would then be handed a key it does not need.

B11 - lxml exposes comments and processing instructions as nodes whose .tag is
a callable, so .tag.endswith() raised AttributeError. Any comment inside an MPD
aborted the entire parse, i.e. every download failed.

B27 - these very tests called pathlib.Path.read_text(newline=...), which only
exists from Python 3.13, so they could not run on the 3.11 interpreter this
project targets.
"""

import ast
import sys
import unittest
from pathlib import Path

from lxml import etree

from crunchyroll import get_track_kid, parse_mpd_content

REPO = Path(__file__).resolve().parent.parent
NS = "urn:mpeg:dash:schema:mpd:2011"
CENC = "urn:mpeg:cenc:2013"
VIDEO_KID = "d2b1dbc41da7402d88de5dba577def74"
OTHER_KID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


class TestKidParserHandlesComments(unittest.TestCase):
    """B11: comments and processing instructions must not abort parsing."""

    def _mpd(self, inner):
        return (f'<MPD xmlns="{NS}" xmlns:cenc="{CENC}"><Period><!--period--><AdaptationSet>'
                f'<!--aset-->{inner}</AdaptationSet></Period></MPD>').encode()

    def test_comment_inside_representation_does_not_crash(self):
        doc = self._mpd(
            '<Representation id="v" width="1280" height="720" bandwidth="1">'
            '<!--comment--><ContentProtection cenc:default_KID="%s"/>'
            '<BaseURL>u</BaseURL></Representation>' % VIDEO_KID)
        video, _ = parse_mpd_content(doc)
        self.assertEqual(video[0]["kid"], VIDEO_KID)

    def test_comment_before_content_protection(self):
        doc = self._mpd(
            '<Representation id="v" width="1280" height="720" bandwidth="1">'
            '<!--a--><!--b--><ContentProtection cenc:default_KID="%s"/>'
            '<BaseURL>u</BaseURL></Representation>' % VIDEO_KID)
        video, _ = parse_mpd_content(doc)
        self.assertEqual(video[0]["kid"], VIDEO_KID)

    def test_processing_instruction_is_tolerated(self):
        doc = (f'<MPD xmlns="{NS}" xmlns:cenc="{CENC}"><Period><AdaptationSet>'
               f'<?target-screen?><Representation id="v" width="1280" height="720" '
               f'bandwidth="1"><ContentProtection cenc:default_KID="{VIDEO_KID}"/>'
               f'<BaseURL>u</BaseURL></Representation></AdaptationSet></Period></MPD>').encode()
        video, _ = parse_mpd_content(doc)
        self.assertEqual(video[0]["kid"], VIDEO_KID)

    def test_comment_in_adaptation_set_scope_is_tolerated(self):
        doc = (f'<MPD xmlns="{NS}" xmlns:cenc="{CENC}"><Period><AdaptationSet '
               f'mimeType="video/mp4" cenc:default_KID="{VIDEO_KID}">'
               f'<!--note--><Representation id="v" width="1280" height="720" '
               f'bandwidth="1"><BaseURL>u</BaseURL></Representation>'
               f'</AdaptationSet></Period></MPD>').encode()
        video, _ = parse_mpd_content(doc)
        self.assertEqual(video[0]["kid"], VIDEO_KID)


class TestKidDoesNotBorrowFromSiblings(unittest.TestCase):
    """B10: a clear rendition must not inherit a sibling's key ID."""

    def _two_reps(self, protected_id, clear_id):
        return (f'<MPD xmlns="{NS}" xmlns:cenc="{CENC}"><Period><AdaptationSet '
                f'mimeType="video/mp4">'
                f'<Representation id="{protected_id}" width="1280" height="720" bandwidth="2">'
                f'<ContentProtection cenc:default_KID="{VIDEO_KID}"/><BaseURL>u1</BaseURL>'
                f'</Representation>'
                f'<Representation id="{clear_id}" width="640" height="360" bandwidth="1">'
                f'<BaseURL>u2</BaseURL></Representation>'
                f'</AdaptationSet></Period></MPD>').encode()

    def test_clear_representation_has_no_kid(self):
        video, _ = parse_mpd_content(self._two_reps("v-protected", "v-clear"))
        clear = next(t for t in video if t["name"] == "v-clear")
        self.assertNotIn("kid", clear,
                         "clear rendition inherited a protected sibling's key ID")

    def test_protected_representation_keeps_its_own_kid(self):
        video, _ = parse_mpd_content(self._two_reps("v-protected", "v-clear"))
        prot = next(t for t in video if t["name"] == "v-protected")
        self.assertEqual(prot["kid"], VIDEO_KID)

    def test_sibling_key_is_ignored_regardless_of_order(self):
        """Clear rendition first in document order must still be keyless."""
        doc = (f'<MPD xmlns="{NS}" xmlns:cenc="{CENC}"><Period><AdaptationSet '
               f'mimeType="video/mp4">'
               f'<Representation id="v-clear" width="640" height="360" bandwidth="1">'
               f'<BaseURL>u1</BaseURL></Representation>'
               f'<Representation id="v-protected" width="1280" height="720" bandwidth="2">'
               f'<ContentProtection cenc:default_KID="{VIDEO_KID}"/><BaseURL>u2</BaseURL>'
               f'</Representation></AdaptationSet></Period></MPD>').encode()
        video, _ = parse_mpd_content(doc)
        clear = next(t for t in video if t["name"] == "v-clear")
        self.assertNotIn("kid", clear)

    def test_audio_sibling_cannot_leak_its_kid_into_a_clear_video_track(self):
        doc = (f'<MPD xmlns="{NS}" xmlns:cenc="{CENC}"><Period><AdaptationSet '
               f'mimeType="video/mp4">'
               f'<Representation id="v" width="640" height="360" bandwidth="1">'
               f'<BaseURL>u</BaseURL></Representation>'
               f'<Representation id="a" bandwidth="1">'
               f'<ContentProtection cenc:default_KID="{OTHER_KID}"/><BaseURL>a</BaseURL>'
               f'</Representation></AdaptationSet></Period></MPD>').encode()
        video, audio = parse_mpd_content(doc)
        self.assertNotIn("kid", video[0])
        self.assertEqual(audio[0]["kid"], OTHER_KID)

    def test_get_track_kid_directly_ignores_siblings(self):
        doc = self._two_reps("v-protected", "v-clear").decode()
        rep = etree.fromstring(doc.encode()).find(f".//{{{NS}}}Representation[@id='v-clear']")
        self.assertIsNone(get_track_kid(rep))


class TestTestsRunOnPython311(unittest.TestCase):
    """B27: the suite must not use APIs newer than the supported interpreter."""

    FORBIDDEN_READ_TEXT = "read_text(encoding=\"utf-8\", newline="

    def test_no_read_text_newline_in_test_sources(self):
        offenders = []
        for path in sorted((REPO / "test").glob("test_*.py")):
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            if self.FORBIDDEN_READ_TEXT in text:
                offenders.append(path.name)
        self.assertEqual(offenders, [],
                         f"Path.read_text(newline=) needs Python 3.13: {offenders}")

    def test_test_modules_do_not_use_3_13_only_stdlib(self):
        """Guard the whole test package, not just the files touched by the fix."""
        banned = ("Path.walk(", "itertools.batched(")
        self_path = Path(__file__).resolve()
        for path in sorted((REPO / "test").glob("*.py")):
            if path.resolve() == self_path:
                continue  # this file necessarily spells the banned names out
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            for needle in (self.FORBIDDEN_READ_TEXT,) + banned:
                if needle in text:
                    self.fail(f"{path.name} uses {needle}, which needs a newer "
                              f"interpreter than 3.11")

    def test_read_source_helper_is_available(self):
        for name in ("test_config_live.py", "test_py311_syntax.py",
                     "test_drm_key_selection.py"):
            with self.subTest(module=name):
                text = (REPO / "test" / name).read_text(encoding="utf-8")
                self.assertIn("def read_source", text)
                self.assertIn('open(path, "r", encoding="utf-8", newline="")', text)

    def test_target_interpreter_is_at_least_311(self):
        self.assertGreaterEqual(sys.version_info[:2], (3, 11))

    def test_production_sources_use_no_3_13_only_pathlib(self):
        """The shipped modules must not import-break on 3.11 either."""
        for name in ("cli.py", "tg.py", "crunchyroll.py", "platform_tools.py"):
            with self.subTest(module=name):
                text = (REPO / name).read_text(encoding="utf-8")
                self.assertNotIn(self.FORBIDDEN_READ_TEXT, text)
                ast.parse(text.replace("\r\n", "\n"))


if __name__ == "__main__":
    unittest.main()