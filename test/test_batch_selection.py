"""Regression tests for the batch-mode selections cli.py replays across episodes.

In batch mode the user answers every selection prompt once (guarded by `aka == 1`)
and those answers are then applied to each remaining episode. These tests pin
the resolution helpers that make that safe when episodes disagree, so a later
refactor cannot silently reintroduce an IndexError, a wrong-language mux, or an
aborted batch.
"""

import unittest

from crunchyroll import (
    resolve_batch_subtitles,
    resolve_batch_audios,
    resolve_video_quality,
    dedup_preserving_order,
)


class TestBatchSubtitleResolution(unittest.TestCase):
    def setUp(self):
        self.tracks = [
            {"language": "ja-JP", "url": "ja", "format": "vtt", "type": "subtitle"},
            {"language": "de-DE", "url": "de", "format": "vtt", "type": "subtitle"},
        ]

    def test_same_order_resolves_identically(self):
        result = resolve_batch_subtitles(["ja-JP", "de-DE"], self.tracks)
        self.assertEqual([t["url"] for t in result], ["ja", "de"])

    def test_reordered_episode_tracks_do_not_shift_languages(self):
        """A differently ordered track list must not mux the wrong language."""
        reordered = [self.tracks[1], self.tracks[0]]
        result = resolve_batch_subtitles(["de-DE"], reordered)
        self.assertEqual([t["url"] for t in result], ["de"])

    def test_missing_language_is_skipped_not_indexed(self):
        """An episode lacking the chosen language must not raise or substitute."""
        only_japanese = [self.tracks[0]]
        result = resolve_batch_subtitles(["ja-JP", "de-DE"], only_japanese)
        self.assertEqual([t["url"] for t in result], ["ja"])

    def test_locale_map_renames_display_language(self):
        result = resolve_batch_subtitles(["ja-JP"], self.tracks, {"ja-JP": "Japanese"})
        self.assertEqual(result[0]["language"], "Japanese")

    def test_no_requested_tracks_yields_empty_selection(self):
        """Captions-only episodes must resolve to empty, never stay unbound."""
        caption = {"language": "en-US", "url": "cc", "format": "vtt", "type": "caption"}
        self.assertEqual(resolve_batch_subtitles([], self.tracks), [])
        self.assertEqual(resolve_batch_subtitles([], [caption]), [])
        self.assertEqual(resolve_batch_subtitles(None, [caption]), [])


class TestBatchAudioResolution(unittest.TestCase):
    def setUp(self):
        self.versions = [
            {"audio_locale": "en-US", "guid": "g-en"},
            {"audio_locale": "ja-JP", "guid": "g-ja"},
        ]

    def test_locales_resolve_per_episode(self):
        resolved, missing = resolve_batch_audios(["ja-JP", "en-US"], self.versions)
        self.assertEqual([a["guid"] for a in resolved], ["g-ja", "g-en"])
        self.assertEqual(missing, [])

    def test_missing_locale_does_not_abort_the_batch(self):
        """One absent dub must be reported and skipped, not end the whole run."""
        english_only = [{"audio_locale": "en-US", "guid": "g-en"}]
        resolved, missing = resolve_batch_audios(["en-US", "ja-JP"], english_only)
        self.assertEqual([a["guid"] for a in resolved], ["g-en"])
        self.assertEqual(missing, ["ja-JP"])

    def test_no_matching_locales_yields_nothing_to_download(self):
        resolved, missing = resolve_batch_audios(["fr-FR"], self.versions)
        self.assertEqual(resolved, [])
        self.assertEqual(missing, ["fr-FR"])

    def test_locale_map_renames_display_name(self):
        resolved, _ = resolve_batch_audios(["ja-JP"], self.versions, {"ja-JP": "Japanese"})
        self.assertEqual(resolved[0]["audio_locale"], "Japanese")


class TestBatchQualityResolution(unittest.TestCase):
    def setUp(self):
        self.video_list = [
            {"height": 360, "bandwidth": 1170735},
            {"height": 480, "bandwidth": 1920211},
            {"height": 720, "bandwidth": 4113890},
            {"height": 1080, "bandwidth": 8887030},
        ]

    def test_requested_height_wins_over_a_stale_index(self):
        """A batch run's index refers to the list it was typed against.

        Honouring it on a later episode whose list differs downloaded whatever
        happened to sit there (asking 720p returned 480p), so the stable height
        is what wins.
        """
        self.assertEqual(resolve_video_quality(self.video_list, 1, 1080)["height"], 1080)

    def test_height_is_honoured_when_the_index_is_out_of_range(self):
        self.assertEqual(resolve_video_quality(self.video_list, 9, 1080)["height"], 1080)

    def test_index_is_used_when_no_height_was_requested(self):
        self.assertEqual(resolve_video_quality(self.video_list, 1, None)["height"], 480)

    def test_short_episode_falls_back_to_nearest_height(self):
        """An episode with fewer renditions must not IndexError."""
        shorter = [{"height": 360}, {"height": 720}]
        self.assertEqual(resolve_video_quality(shorter, 3, 1080)["height"], 720)

    def test_fallback_prefers_closest_not_first(self):
        shorter = [{"height": 360}, {"height": 480}, {"height": 720}]
        self.assertEqual(resolve_video_quality(shorter, 9, 480)["height"], 480)

    def test_empty_list_returns_none(self):
        self.assertIsNone(resolve_video_quality([], 0, 720))


class TestSelectionDeduplication(unittest.TestCase):
    def test_repeated_audio_choices_are_collapsed(self):
        """'1,1' must not download and mux the same track twice."""
        self.assertEqual(
            dedup_preserving_order(["en-US", "en-US", "ja-JP"]),
            ["en-US", "ja-JP"],
        )

    def test_order_is_preserved(self):
        self.assertEqual(dedup_preserving_order(["c", "a", "b", "a"]), ["c", "a", "b"])

    def test_empty_and_none_are_safe(self):
        self.assertEqual(dedup_preserving_order([]), [])
        self.assertEqual(dedup_preserving_order(None), [])


if __name__ == "__main__":
    unittest.main()