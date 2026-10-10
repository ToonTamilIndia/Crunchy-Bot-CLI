"""Tests for DASH segment resolution across the MPD addressing modes."""

import unittest
from crunchyroll import (
    get_segment_link_list,
    parse_iso8601_duration,
    build_byte_ranges,
    parse_content_range_total,
)

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


class TestBuildByteRanges(unittest.TestCase):
    def test_ranges_tile_the_file_exactly_once(self):
        """Concatenating every range in order must reproduce the whole file."""
        for size, parts in [(1000, 8), (1006461632, 8), (7, 3), (999, 1)]:
            with self.subTest(size=size, parts=parts):
                ranges = build_byte_ranges(size, parts)
                self.assertTrue(ranges)
                self.assertEqual(ranges[0][0], 0)
                self.assertEqual(ranges[-1][1], size - 1)
                for (_, prev_end), (next_start, _) in zip(ranges, ranges[1:]):
                    self.assertEqual(next_start, prev_end + 1)
                self.assertEqual(sum(e - s + 1 for s, e in ranges), size)

    def test_never_exceeds_byte_count(self):
        """More threads than bytes must not produce an empty final range."""
        self.assertEqual(build_byte_ranges(3, 8), [(0, 0), (1, 1), (2, 2)])

    def test_unusable_sizes_return_empty(self):
        """An unknown size disables splitting rather than guessing."""
        for bad in (0, -1, None, 2.5, True, "x"):
            with self.subTest(bad=bad):
                self.assertEqual(build_byte_ranges(bad, 4), [])


class TestParseContentRangeTotal(unittest.TestCase):
    def test_reads_total_from_partial_response(self):
        self.assertEqual(
            parse_content_range_total("HTTP/1.1 206 Partial Content\r\nContent-Range: bytes 0-0/1006461632\r\n\r\n"),
            1006461632,
        )

    def test_case_insensitive_and_partial_header(self):
        self.assertEqual(parse_content_range_total("content-range: BYTES 5-9/40"), 40)

    def test_unsized_or_missing_range_is_unusable(self):
        """No range header or '*' total means the split cannot be trusted."""
        self.assertIsNone(parse_content_range_total("Content-Range: bytes 0-0/*"))
        self.assertIsNone(parse_content_range_total("HTTP/1.1 200 OK\r\nContent-Length: 42\r\n"))
        self.assertIsNone(parse_content_range_total(""))
        self.assertIsNone(parse_content_range_total(None))


class TestSegmentTimelineRepeats(unittest.TestCase):
    """`r` on an `<S>` element controls repetition per ISO/IEC 23009-1."""

    def _mpd(self, timeline, period_duration="PT20S"):
        return f'''<?xml version="1.0"?>
<MPD xmlns="{NS}" type="static" mediaPresentationDuration="{period_duration}">
 <Period duration="{period_duration}">
  <AdaptationSet contentType="video" mimeType="video/mp4">
   <Representation id="1" bandwidth="1000">
    <BaseURL>https://example.test/v/</BaseURL>
    <SegmentTemplate timescale="1000" initialization="init.mp4"
                     media="seg-$Number$.m4s" startNumber="1">
     <SegmentTimeline>{timeline}</SegmentTimeline>
    </SegmentTemplate>
   </Representation>
  </AdaptationSet>
 </Period>
</MPD>'''

    def test_negative_one_repeats_until_end_of_period(self):
        """r="-1" means "to the end of the Period", not zero repetitions.

        Reading it as r+1 yields one segment for the whole episode, which
        downloads successfully and silently produces a truncated file.
        """
        result = get_segment_link_list(self._mpd('<S t="0" d="4000" r="-1"/>'), "1", None)
        self.assertEqual(len(result["segments"]), 5)          # 20s / 4s
        self.assertEqual(result["segments"][-1], "https://example.test/v/seg-5.m4s")

    def test_negative_one_uses_explicit_s_timestamps(self):
        """r="-1" must count from the S element's own t, not from zero."""
        result = get_segment_link_list(
            self._mpd('<S t="0" d="4000"/><S d="4000" r="-1"/>'), "1", None
        )
        self.assertEqual(len(result["segments"]), 5)

    def test_positive_repeat_is_inclusive(self):
        """r="2" means the S element plus two repeats."""
        result = get_segment_link_list(self._mpd('<S t="0" d="4000" r="2"/>'), "1", None)
        self.assertEqual(len(result["segments"]), 3)

    def test_absent_repeat_yields_one(self):
        result = get_segment_link_list(self._mpd('<S t="0" d="4000"/>'), "1", None)
        self.assertEqual(len(result["segments"]), 1)

    def test_zero_repeat_yields_one(self):
        result = get_segment_link_list(self._mpd('<S t="0" d="4000" r="0"/>'), "1", None)
        self.assertEqual(len(result["segments"]), 1)


class TestAddressingModeInheritance(unittest.TestCase):
    """SegmentTemplate/List/Base declared above the Representation is inherited."""

    TEMPLATE = (
        '<SegmentTemplate timescale="1000" initialization="init.mp4" '
        'media="seg-$Number$.m4s" startNumber="1">'
        '<SegmentTimeline><S d="4000" r="4"/></SegmentTimeline></SegmentTemplate>'
    )

    def _mpd_with_template_at(self, level):
        if level == "mpd":
            opening = f'<MPD xmlns="{NS}" mediaPresentationDuration="PT20S">{self.TEMPLATE}<Period duration="PT20S">'
        elif level == "period":
            opening = (
                f'<MPD xmlns="{NS}" mediaPresentationDuration="PT20S">'
                f'<Period duration="PT20S">{self.TEMPLATE}'
            )
        else:
            opening = f'<MPD xmlns="{NS}" mediaPresentationDuration="PT20S"><Period duration="PT20S">'
        inner = self.TEMPLATE if level == "representation" else ""
        return f'''<?xml version="1.0"?>
{opening}
  <AdaptationSet contentType="video" mimeType="video/mp4">
   <Representation id="1" bandwidth="1000">
    <BaseURL>https://example.test/v/</BaseURL>
    {inner}
   </Representation>
  </AdaptationSet>
 </Period>
</MPD>'''

    def test_template_inherited_from_mpd_level(self):
        result = get_segment_link_list(self._mpd_with_template_at("mpd"), "1", None)
        self.assertTrue(result, "MPD-level SegmentTemplate should be inherited")
        self.assertEqual(len(result["segments"]), 5)

    def test_template_inherited_from_period_level(self):
        result = get_segment_link_list(self._mpd_with_template_at("period"), "1", None)
        self.assertTrue(result, "Period-level SegmentTemplate should be inherited")
        self.assertEqual(len(result["segments"]), 5)

    def test_representation_level_still_works(self):
        result = get_segment_link_list(self._mpd_with_template_at("representation"), "1", None)
        self.assertTrue(result)
        self.assertEqual(len(result["segments"]), 5)

    def test_absent_template_is_still_unresolved(self):
        """No addressing mode anywhere must stay unresolved, not half-resolve."""
        self.assertEqual(get_segment_link_list(self._mpd_with_template_at("none"), "1", None), {})


class TestBaseUrlChainResolution(unittest.TestCase):
    """The effective BaseURL resolves each level against its parent."""

    TEMPLATE = (
        '<SegmentTemplate timescale="1000" initialization="init.mp4" '
        'media="seg-$Number$.m4s" startNumber="1">'
        '<SegmentTimeline><S d="4000" r="0"/></SegmentTimeline></SegmentTemplate>'
    )

    @staticmethod
    def _base(text):
        return f"<BaseURL>{text}</BaseURL>" if text else ""

    def _mpd(self, mpd, period, adaptation, representation):
        return f'''<?xml version="1.0"?>
<MPD xmlns="{NS}" mediaPresentationDuration="PT20S">{self._base(mpd)}
 <Period duration="PT20S">{self._base(period)}
  <AdaptationSet contentType="video">{self._base(adaptation)}
   <Representation id="1" bandwidth="1000">{self._base(representation)}
    {self.TEMPLATE}
   </Representation>
  </AdaptationSet>
 </Period>
</MPD>'''

    def _first_segment(self, *bases):
        result = get_segment_link_list(self._mpd(*bases), "1", "")
        self.assertTrue(result, "expected the representation to resolve")
        return result["segments"][0]

    def test_all_four_levels_concatenate(self):
        self.assertEqual(
            self._first_segment("https://cdn.test/drm/", "eps/E01/", "video/", "720/"),
            "https://cdn.test/drm/eps/E01/video/720/seg-1.m4s",
        )

    def test_relative_chain_stays_relative(self):
        self.assertEqual(
            self._first_segment("drm/", "eps/", "video/", ""),
            "drm/eps/video/seg-1.m4s",
        )

    def test_single_level_is_used_as_is(self):
        self.assertEqual(
            self._first_segment("", "", "", "https://cdn.test/v/"),
            "https://cdn.test/v/seg-1.m4s",
        )

    def test_base_without_trailing_slash_resolves_per_rfc3986(self):
        """RFC 3986 drops the last path segment of a base that is a file."""
        self.assertEqual(
            self._first_segment("https://cdn.test/drm/", "eps", "", ""),
            "https://cdn.test/drm/seg-1.m4s",
        )

    def test_mpd_base_without_trailing_slash_gets_directory(self):
        self.assertEqual(
            self._first_segment("https://cdn.test/drm", "eps/", "", ""),
            "https://cdn.test/drm/eps/seg-1.m4s",
        )

    def test_absolute_inner_base_replaces_outer_chain(self):
        self.assertEqual(
            self._first_segment("https://cdn.test/drm/", "", "https://other.test/x/", ""),
            "https://other.test/x/seg-1.m4s",
        )


if __name__ == "__main__":
    unittest.main()