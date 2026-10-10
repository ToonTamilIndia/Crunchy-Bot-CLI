"""Tests for DASH segment resolution across the MPD addressing modes."""

import unittest
from crunchyroll import get_segment_link_list, parse_iso8601_duration

NS = "urn:mpeg:dash:schema:mpd:2011"


def build_mpd(representation_body, period_duration="PT10S", rep_id="1"):
    return f'''<?xml version="1.0"?>
<MPD xmlns="{NS}" type="static" mediaPresentationDuration="{period_duration}">
 <Period id="0" duration="{period_duration}">
  <AdaptationSet contentType="video" mimeType="video/mp4">
   <Representation id="{rep_id}" bandwidth="1663878" width="854" height="480" codecs="avc1.64001F">
    {representation_body}
   </Representation>
  </AdaptationSet>
 </Period>
</MPD>'''


class TestParseIso8601Duration(unittest.TestCase):
    def test_common_durations(self):
        self.assertEqual(parse_iso8601_duration("PT10S"), 10.0)
        self.assertEqual(parse_iso8601_duration("PT1H2M3S"), 3723.0)
        self.assertEqual(parse_iso8601_duration("PT1.5S"), 1.5)

    def test_invalid_and_empty(self):
        self.assertEqual(parse_iso8601_duration(""), 0.0)
        self.assertEqual(parse_iso8601_duration(None), 0.0)
        self.assertEqual(parse_iso8601_duration("not-a-duration"), 0.0)


class TestGetSegmentLinkList(unittest.TestCase):
    def test_segment_timeline(self):
        """The timeline form should expand repeats and substitute template vars."""
        mpd = build_mpd('''
    <BaseURL>https://example.test/v/</BaseURL>
    <SegmentTemplate timescale="1000" initialization="init-$RepresentationID$.mp4"
                     media="seg-$RepresentationID$-$Number$.m4s" startNumber="1">
     <SegmentTimeline><S t="0" d="4000" r="2"/></SegmentTimeline>
    </SegmentTemplate>''')
        result = get_segment_link_list(mpd, "1", "https://example.test/v/")
        self.assertEqual(result["init"], "https://example.test/v/init-1.mp4")
        self.assertEqual(len(result["segments"]), 3)
        self.assertEqual(result["all"][0], result["init"])
        self.assertEqual(result["all"][-1], "https://example.test/v/seg-1-3.m4s")

    def test_fixed_duration_segment_template(self):
        """A SegmentTemplate with duration but no timeline must still resolve."""
        mpd = build_mpd('''
    <BaseURL>https://example.test/v/</BaseURL>
    <SegmentTemplate timescale="1000" duration="2000" initialization="init.mp4"
                     media="seg-$Number%05d$.m4s" startNumber="1"/>''')
        result = get_segment_link_list(mpd, "1", "https://example.test/v/")
        self.assertEqual(len(result["segments"]), 5)
        self.assertEqual(result["segments"][0], "https://example.test/v/seg-00001.m4s")
        self.assertEqual(result["all"][0], "https://example.test/v/init.mp4")

    def test_segment_list(self):
        """An explicit SegmentList should resolve its Initialization and SegmentURLs."""
        mpd = build_mpd('''
    <BaseURL>https://example.test/v/</BaseURL>
    <SegmentList timescale="1000" duration="2000">
     <Initialization sourceURL="init.mp4"/>
     <SegmentURL media="a.m4s"/>
     <SegmentURL media="b.m4s"/>
    </SegmentList>''')
        result = get_segment_link_list(mpd, "1", "https://example.test/v/")
        self.assertEqual(result["init"], "https://example.test/v/init.mp4")
        self.assertEqual(
            result["all"],
            [
                "https://example.test/v/init.mp4",
                "https://example.test/v/a.m4s",
                "https://example.test/v/b.m4s",
            ],
        )

    def test_segment_base_single_file(self):
        """SegmentBase means the base URL is already the complete stream."""
        mpd = build_mpd('''
    <BaseURL>https://example.test/v/full.mp4</BaseURL>
    <SegmentBase indexRange="1000-2000"/>''')
        result = get_segment_link_list(mpd, "1", "https://example.test/v/full.mp4")
        self.assertIsNone(result["init"])
        self.assertEqual(result["all"], ["https://example.test/v/full.mp4"])

    def test_falls_back_to_mpd_base_url(self):
        """A missing caller-supplied base URL should be recovered from the MPD."""
        mpd = build_mpd('''
    <BaseURL>https://example.test/v/</BaseURL>
    <SegmentTemplate timescale="1000" initialization="init.mp4" media="s-$Number$.m4s">
     <SegmentTimeline><S t="0" d="4000" r="1"/></SegmentTimeline>
    </SegmentTemplate>''')
        result = get_segment_link_list(mpd, "1", None)
        self.assertEqual(result["init"], "https://example.test/v/init.mp4")
        self.assertEqual(result["segments"], [
            "https://example.test/v/s-1.m4s",
            "https://example.test/v/s-2.m4s",
        ])

    def test_unknown_representation_returns_empty(self):
        """An unresolvable representation must return {} so callers can report it."""
        mpd = build_mpd('''
    <BaseURL>https://example.test/v/</BaseURL>
    <SegmentTemplate timescale="1000" initialization="init.mp4" media="s-$Number$.m4s">
     <SegmentTimeline><S t="0" d="4000"/></SegmentTimeline>
    </SegmentTemplate>''')
        self.assertEqual(get_segment_link_list(mpd, "999", "https://example.test/v/"), {})

    def test_malformed_mpd_returns_empty(self):
        """Malformed MPD content must return {} rather than raising."""
        self.assertEqual(get_segment_link_list("<MPD><unclosed>", "1", "https://x/"), {})

    def test_all_is_always_present_when_resolved(self):
        """Callers index ["all"] directly, so a resolved result must always have it."""
        bodies = [
            '<BaseURL>https://example.test/v/</BaseURL><SegmentBase/>',
            '<BaseURL>https://example.test/v/</BaseURL><SegmentList><SegmentURL media="a.m4s"/></SegmentList>',
            '<BaseURL>https://example.test/v/</BaseURL><SegmentTemplate timescale="1" initialization="i.mp4" media="s-$Number$.m4s"><SegmentTimeline><S d="1"/></SegmentTimeline></SegmentTemplate>',
            '<BaseURL>https://example.test/v/</BaseURL><SegmentTemplate timescale="1" duration="1" initialization="i.mp4" media="s-$Number$.m4s"/>',
        ]
        for body in bodies:
            with self.subTest(body=body[:60]):
                result = get_segment_link_list(build_mpd(body), "1", "https://example.test/v/")
                self.assertTrue(result, "expected a resolved segment list")
                self.assertIn("all", result)
                self.assertTrue(result["all"])


if __name__ == "__main__":
    unittest.main()