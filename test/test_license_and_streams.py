"""Tests for license-key extraction and playback-stream cleanup.

Two defects are pinned here:
- get_license() returns None on any failure, so indexing it directly raised
  TypeError deep in the CLI instead of a reportable error.
- The active-stream cleanup used to deactivate every stream the account had
  running, including ones on the user's phone or TV, instead of only the title
  being requested.
"""

import json
import unittest

from crunchyroll import (
    Crunchyroll,
    extract_content_key,
    LicenseError,
)


def key_entry(kid, key, type_="CONTENT"):
    return {"type": type_, "kid_hex": kid, "key_hex": key}


class FakeResponse:
    def __init__(self, payload, status_code=400):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestExtractContentKey(unittest.TestCase):
    def test_none_raises_a_descriptive_error(self):
        """The None return is the exact case that used to TypeError."""
        with self.assertRaises(LicenseError) as ctx:
            extract_content_key(None, "Tokyo Ghoul S1E1")
        message = str(ctx.exception)
        self.assertIn("Tokyo Ghoul S1E1", message)
        self.assertIn("No decryption license", message)

    def test_missing_or_empty_key_list_raises(self):
        for bad in ({}, {"key": []}, {"other": 1}, {"key": None}):
            with self.subTest(bad=bad):
                with self.assertRaises(LicenseError):
                    extract_content_key(bad)

    def test_keys_without_hex_are_rejected(self):
        with self.assertRaises(LicenseError):
            extract_content_key({"key": [{"type": "CONTENT", "kid_hex": "aa"}]})

    def test_single_key_is_formatted(self):
        self.assertEqual(
            extract_content_key({"key": [key_entry("AA", "BB")]}), "AA:BB"
        )

    def test_content_key_is_preferred(self):
        payload = {"key": [
            key_entry("11", "22", type_="SINGLE_VALUE"),
            key_entry("33", "44", type_="CONTENT"),
        ]}
        self.assertEqual(extract_content_key(payload), "33:44")

    def test_falls_back_to_first_usable_key(self):
        payload = {"key": [
            {"type": "CONTENT"},                       # unusable
            key_entry("55", "66", type_="UNKNOWN"),
        ]}
        self.assertEqual(extract_content_key(payload), "55:66")

    def test_context_is_optional(self):
        self.assertEqual(extract_content_key({"key": [key_entry("AA", "BB")]}), "AA:BB")


class TestActiveStreamCleanup(unittest.TestCase):
    def setUp(self):
        self.cr = Crunchyroll.__new__(Crunchyroll)   # no network/session needed
        self.deactivated = []
        self.cr.deauth_video = lambda cid, token: self.deactivated.append((cid, token))

    def _response(self, streams):
        return FakeResponse({"activeStreams": streams})

    def test_only_the_requested_title_is_released(self):
        """A stream on the user's phone for a different show must survive."""
        response = self._response([
            {"contentId": "EP-OTHER", "token": "TOK-OTHER"},   # their TV
            {"contentId": "EP-MINE", "token": "TOK-MINE"},     # ours
        ])
        self.assertTrue(self.cr._retry_after_active_stream_cleanup(response, "EP-MINE"))
        self.assertEqual(self.deactivated, [("EP-MINE", "TOK-MINE")])

    def test_no_matching_title_releases_nothing(self):
        response = self._response([{"contentId": "EP-OTHER", "token": "TOK"}])
        self.assertFalse(self.cr._retry_after_active_stream_cleanup(response, "EP-MINE"))
        self.assertEqual(self.deactivated, [])

    def test_entries_without_content_id_are_skipped(self):
        """Under-releasing only costs a retry; over-releasing breaks other devices."""
        response = self._response([{"token": "TOK-ORPHAN"}])
        self.assertFalse(self.cr._retry_after_active_stream_cleanup(response, "EP-MINE"))
        self.assertEqual(self.deactivated, [])

    def test_duplicate_streams_are_released_once(self):
        response = self._response([
            {"contentId": "EP-MINE", "token": "TOK"},
            {"contentId": "EP-MINE", "token": "TOK"},
        ])
        self.assertTrue(self.cr._retry_after_active_stream_cleanup(response, "EP-MINE"))
        self.assertEqual(self.deactivated, [("EP-MINE", "TOK")])

    def test_empty_and_malformed_payloads_are_safe(self):
        self.assertFalse(self.cr._retry_after_active_stream_cleanup(
            FakeResponse({"activeStreams": []}), "EP-MINE"))
        self.assertFalse(self.cr._retry_after_active_stream_cleanup(
            FakeResponse({}), "EP-MINE"))
        self.assertEqual(self.deactivated, [])

    def test_snake_case_field_names_are_supported(self):
        response = self._response([{"content_id": "EP-MINE", "token": "TOK"}])
        self.assertTrue(self.cr._retry_after_active_stream_cleanup(response, "EP-MINE"))
        self.assertEqual(self.deactivated, [("EP-MINE", "TOK")])


if __name__ == "__main__":
    unittest.main()