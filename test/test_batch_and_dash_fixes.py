"""Regression tests for the batch-flow and DASH-parser fixes.

B02 - a failed audio license left the entry in selected_audios without a key,
      so the later download step raised KeyError on the missing 'segment'.
B04 - a batch run stored the chosen height but resolved by the positional index,
      which is only valid for the list it was typed against.
B09 - the token cache was returned before the credentials were even looked at,
      so a token issued to one account satisfied another account's login.
B12 - S r="-1" was bounded by the Period length instead of the next S entry.
B13 - a SegmentTemplate declaring media/init on the AdaptationSet and only
      timeline on the Representation resolved to nothing.
B14 - a video Representation inheriting width/height was filed as audio.
B15 - a Representation id is only unique per Period; duplicates picked the first.
B16 - relative BaseURL/SegmentTemplate values were never made absolute because
      the MPD document URL was discarded.
B25 - the summary claimed "lossless stream copy" while requesting an encoder.
"""

import unittest

from crunchyroll import (
    CrunchyrollAuth,
    get_segment_link_list,
    parse_mpd_content,
    resolve_encoding_config,
)

NS = "urn:mpeg:dash:schema:mpd:2011"
CENC = "urn:mpeg:cenc:2013"


def _mpd(period_body, period_attrs=""):
    return (f'<MPD xmlns="{NS}"><Period {period_attrs}>{period_body}</Period></MPD>').encode()


class TestNegativeRepeat(unittest.TestCase):
    """B12"""

    def _resolve(self, timeline, period_duration="PT100S"):
        doc = _mpd(
            '<AdaptationSet mimeType="video/mp4">'
            '<Representation id="v" width="1280" height="720" bandwidth="1">'
            f'<SegmentTemplate media="s-$Number$.m4s" initialization="i.mp4" '
            f'startNumber="1" timescale="1">'
            f'<SegmentTimeline>{timeline}</SegmentTimeline></SegmentTemplate>'
            '<BaseURL>https://cdn/</BaseURL></Representation></AdaptationSet>',
            f'duration="{period_duration}"')
        return get_segment_link_list(doc, "v", "https://cdn/").get("segments") or []

    def test_negative_repeat_stops_at_the_next_entry(self):
        # t=0 d=2 repeated up to t=8 -> 0,2,4,6 then the t=8 entry
        segs = self._resolve('<S t="0" d="2" r="-1"/><S t="8" d="2"/>')
        self.assertEqual(len(segs), 5)

    def test_last_entry_falls_back_to_period_length(self):
        segs = self._resolve('<S t="0" d="2" r="-1"/>', period_duration="PT10S")
        self.assertEqual(len(segs), 5)

    def test_period_length_is_not_used_when_a_later_entry_exists(self):
        """A 100s period must not produce 50 segments for a t=8 boundary."""
        segs = self._resolve('<S t="0" d="2" r="-1"/><S t="8" d="2"/>')
        self.assertLess(len(segs), 10)


class TestTemplateInheritance(unittest.TestCase):
    """B13"""

    def test_parent_media_and_init_merge_with_child_timeline(self):
        doc = _mpd(
            '<AdaptationSet mimeType="video/mp4">'
            '<SegmentTemplate media="base-$Number$.m4s" initialization="base-init.mp4"/>'
            '<Representation id="v" width="1280" height="720" bandwidth="1">'
            '<SegmentTemplate startNumber="3">'
            '<SegmentTimeline><S t="0" d="2" r="1"/></SegmentTimeline></SegmentTemplate>'
            '<BaseURL>https://cdn/</BaseURL></Representation></AdaptationSet>')
        result = get_segment_link_list(doc, "v", "https://cdn/")
        self.assertTrue(result, "inheritance resolved to nothing")
        self.assertEqual(result["init"], "https://cdn/base-init.mp4")
        self.assertEqual(result["segments"],
                         ["https://cdn/base-3.m4s", "https://cdn/base-4.m4s"])

    def test_child_start_number_is_respected(self):
        doc = _mpd(
            '<AdaptationSet mimeType="video/mp4">'
            '<SegmentTemplate media="base-$Number$.m4s" initialization="base-init.mp4"/>'
            '<Representation id="v" width="1280" height="720" bandwidth="1">'
            '<SegmentTemplate startNumber="7"><SegmentTimeline>'
            '<S t="0" d="2" r="0"/></SegmentTimeline></SegmentTemplate>'
            '<BaseURL>https://cdn/</BaseURL></Representation></AdaptationSet>')
        result = get_segment_link_list(doc, "v", "https://cdn/")
        self.assertEqual(result["segments"], ["https://cdn/base-7.m4s"])


class TestVideoClassification(unittest.TestCase):
    """B14"""

    def test_inherited_dimensions_classify_as_video(self):
        doc = _mpd('<AdaptationSet mimeType="video/mp4" width="1280" height="720">'
                   '<Representation id="v" bandwidth="1"><BaseURL>u</BaseURL>'
                   '</Representation></AdaptationSet>')
        video, audio = parse_mpd_content(doc)
        self.assertEqual(len(video), 1)
        self.assertEqual(len(audio), 0)

    def test_dimensions_are_reported_on_the_entry(self):
        doc = _mpd('<AdaptationSet mimeType="video/mp4" width="1280" height="720">'
                   '<Representation id="v" bandwidth="1"><BaseURL>u</BaseURL>'
                   '</Representation></AdaptationSet>')
        video, _ = parse_mpd_content(doc)
        self.assertEqual((video[0]["width"], video[0]["height"]), (1280, 720))

    def test_mime_type_alone_classifies_as_video(self):
        doc = _mpd('<AdaptationSet mimeType="video/mp4">'
                   '<Representation id="v" bandwidth="1" codecs="avc1.640028">'
                   '<BaseURL>u</BaseURL></Representation></AdaptationSet>')
        video, audio = parse_mpd_content(doc)
        self.assertEqual((len(video), len(audio)), (1, 0))

    def test_real_audio_track_is_still_audio(self):
        doc = _mpd('<AdaptationSet mimeType="audio/mp4" lang="en-US">'
                   '<Representation id="a" bandwidth="1"><BaseURL>u</BaseURL>'
                   '</Representation></AdaptationSet>')
        video, audio = parse_mpd_content(doc)
        self.assertEqual((len(video), len(audio)), (0, 1))


class TestPeriodDisambiguation(unittest.TestCase):
    """B15"""

    TWO_PERIODS = (
        f'<MPD xmlns="{NS}">'
        '<Period id="p1"><AdaptationSet mimeType="video/mp4">'
        '<Representation id="dup" width="1280" height="720" bandwidth="1">'
        '<SegmentTemplate media="p1-$Number$.m4s" initialization="p1-init.mp4" '
        'startNumber="1"><SegmentTimeline><S t="0" d="2" r="0"/>'
        '</SegmentTimeline></SegmentTemplate>'
        '<BaseURL>https://cdn/</BaseURL></Representation></AdaptationSet></Period>'
        '<Period id="p2"><AdaptationSet mimeType="video/mp4">'
        '<Representation id="dup" width="1280" height="720" bandwidth="1">'
        '<SegmentTemplate media="p2-$Number$.m4s" initialization="p2-init.mp4" '
        'startNumber="1"><SegmentTimeline><S t="0" d="2" r="0"/>'
        '</SegmentTimeline></SegmentTemplate>'
        '<BaseURL>https://cdn/</BaseURL></Representation></AdaptationSet></Period>'
        '</MPD>').encode()

    def test_period_id_selects_the_right_period(self):
        result = get_segment_link_list(self.TWO_PERIODS, "dup", "https://cdn/",
                                       period_id="p2")
        self.assertEqual(result["init"], "https://cdn/p2-init.mp4")

    def test_other_period_selects_the_first(self):
        result = get_segment_link_list(self.TWO_PERIODS, "dup", "https://cdn/",
                                       period_id="p1")
        self.assertEqual(result["init"], "https://cdn/p1-init.mp4")

    def test_unknown_period_does_not_crash(self):
        result = get_segment_link_list(self.TWO_PERIODS, "dup", "https://cdn/",
                                       period_id="nope")
        self.assertTrue(result)


class TestDocumentUrlResolution(unittest.TestCase):
    """B16"""

    def _relative(self):
        return _mpd('<AdaptationSet mimeType="video/mp4">'
                    '<Representation id="v" width="1280" height="720" bandwidth="1">'
                    '<SegmentTemplate media="seg-$Number$.m4s" '
                    'initialization="seg-init.mp4" startNumber="1">'
                    '<SegmentTimeline><S t="0" d="2" r="0"/></SegmentTimeline>'
                    '</SegmentTemplate>'
                    '<BaseURL>media/</BaseURL></Representation></AdaptationSet>')

    def test_relative_paths_become_absolute(self):
        result = get_segment_link_list(
            self._relative(), "v", "media/",
            document_url="https://cdn/manifests/ep.mpd")
        self.assertEqual(result["init"],
                         "https://cdn/manifests/media/seg-init.mp4")
        self.assertTrue(result["segments"][0].startswith("https://"))

    def test_absolute_paths_are_left_alone(self):
        doc = _mpd('<AdaptationSet mimeType="video/mp4">'
                   '<Representation id="v" width="1280" height="720" bandwidth="1">'
                   '<SegmentTemplate media="https://cdn/seg-$Number$.m4s" '
                   'initialization="https://cdn/i.mp4" startNumber="1">'
                   '<SegmentTimeline><S t="0" d="2" r="0"/></SegmentTimeline>'
                   '</SegmentTemplate><BaseURL>https://cdn/</BaseURL>'
                   '</Representation></AdaptationSet>')
        result = get_segment_link_list(doc, "v", "https://cdn/",
                                       document_url="https://other/manifest.mpd")
        self.assertEqual(result["init"], "https://cdn/i.mp4")


class TestTokenCacheIsAccountBound(unittest.TestCase):
    """B09"""

    def setUp(self):
        self.auth = CrunchyrollAuth.__new__(CrunchyrollAuth)

    def test_same_account_is_reused(self):
        payload = {"account": "alice@example.com", "access_token": "A"}
        self.assertTrue(self.auth._cache_matches_account(payload, "Alice@Example.com"))

    def test_other_account_is_refused(self):
        payload = {"account": "alice@example.com", "access_token": "A"}
        self.assertFalse(self.auth._cache_matches_account(payload, "bob@example.com"))

    def test_legacy_cache_without_account_is_refused(self):
        self.assertFalse(self.auth._cache_matches_account(
            {"access_token": "A"}, "alice@example.com"))

    def test_no_email_is_permitted(self):
        """The etp_rt/cookie flow has no account to compare against."""
        payload = {"account": "alice@example.com"}
        self.assertTrue(self.auth._cache_matches_account(payload, ""))
        self.assertTrue(self.auth._cache_matches_account(payload, None))

    def test_cache_write_stamps_the_current_login_account(self):
        import inspect
        source = inspect.getsource(CrunchyrollAuth._write_etp_rt_cache)
        self.assertIn("last_login_account", source)

    def test_password_login_sets_the_account_before_any_cache_read(self):
        import inspect
        source = inspect.getsource(CrunchyrollAuth.get_password_token)
        set_at = source.index("last_login_account")
        read_at = source.index("_read_etp_rt_cache")
        self.assertLess(set_at, read_at,
                        "the cache is consulted before the account is recorded")


class TestEncodingSummaryWording(unittest.TestCase):
    """B25"""

    def setUp(self):
        import config
        self._saved = config.audio_codec

    def tearDown(self):
        import config
        config.audio_codec = self._saved

    def test_encoder_is_not_described_as_a_stream_copy(self):
        import config
        config.audio_codec = "aac"
        summary = resolve_encoding_config(mode="lossy").summary()
        self.assertIn("aac", summary)
        self.assertNotIn("lossless stream copy", summary)

    def test_real_copy_is_still_described_as_lossless(self):
        import config
        config.audio_codec = "copy"
        summary = resolve_encoding_config(mode="lossy").summary()
        self.assertIn("lossless stream copy", summary)

    def test_lossless_summary_is_unchanged(self):
        summary = resolve_encoding_config(mode="lossless").summary()
        self.assertIn("LOSSLESS", summary)
        self.assertIn("Audio: copy", summary)


class TestUnresolvedAudioIsDropped(unittest.TestCase):
    """B02"""

    def test_both_paths_filter_unresolved_audio(self):
        import ast
        from pathlib import Path

        source = (Path(__file__).resolve().parent.parent / "cli.py") \
            .read_text(encoding="utf-8").replace("\r\n", "\n")
        tree = ast.parse(source)
        filters = [n for n in ast.walk(tree)
                   if isinstance(n, ast.ListComp)
                   and "key" in ast.unparse(n)
                   and "segment" in ast.unparse(n)]
        self.assertGreaterEqual(
            len(filters), 2,
            "both the single-episode and batch paths must drop unresolved audio")

    def test_downstream_no_longer_requires_a_bare_exit_on_empty_audio(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parent.parent / "cli.py") \
            .read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("if a.get('key') and a.get('segment')", source)


if __name__ == "__main__":
    unittest.main()