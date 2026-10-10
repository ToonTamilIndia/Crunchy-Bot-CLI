"""Telegram's key selection must match the CLI's.

tg.py carried its own copy of the key-selection logic that returned "the first
CONTENT key". A single license covers every rendition and returns several keys
that are all typed CONTENT, so that picked a key belonging to a different
rendition and produced corrupt video. get_decryption_key now delegates to the
shared extract_content_key and takes the track's default_KID.
"""

import unittest

from crunchyroll import LicenseError, extract_content_key
import tg

VIDEO_KID = "d2b1dbc41da7402d88de5dba577def74"
AUDIO_KID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
OTHER_KID = "0f1041f6e2e60000000000000000000ab"


def license_payload():
    return {"key": [
        {"type": "CONTENT", "kid_hex": OTHER_KID, "key_hex": "11" * 16},
        {"type": "CONTENT", "kid_hex": VIDEO_KID, "key_hex": "22" * 16},
        {"type": "CONTENT", "kid_hex": AUDIO_KID, "key_hex": "33" * 16},
    ]}


class TestTelegramKeySelection(unittest.TestCase):
    def test_picks_key_matching_the_video_kid(self):
        self.assertEqual(tg.get_decryption_key(license_payload(), VIDEO_KID),
                         f"{VIDEO_KID}:{'22' * 16}")

    def test_does_not_return_the_first_content_key(self):
        """The regression: index 0 belongs to a different rendition."""
        self.assertNotEqual(tg.get_decryption_key(license_payload(), VIDEO_KID),
                            f"{OTHER_KID}:{'11' * 16}")

    def test_audio_gets_its_own_key(self):
        video = tg.get_decryption_key(license_payload(), VIDEO_KID)
        audio = tg.get_decryption_key(license_payload(), AUDIO_KID)
        self.assertEqual(audio, f"{AUDIO_KID}:{'33' * 16}")
        self.assertNotEqual(video.split(":")[1], audio.split(":")[1])

    def test_agrees_with_the_shared_extractor(self):
        payload = license_payload()
        self.assertEqual(tg.get_decryption_key(payload, VIDEO_KID),
                         extract_content_key(payload, kid=VIDEO_KID))

    def test_kid_match_is_case_and_dash_insensitive(self):
        dashed = "D2B1DBC4-1DA7-402D-88DE-5DBA577DEF74"
        self.assertEqual(tg.get_decryption_key(license_payload(), dashed),
                         f"{VIDEO_KID}:{'22' * 16}")

    def test_returns_none_instead_of_raising(self):
        """Call sites rely on falsy checks to skip an episode, not on exceptions."""
        self.assertIsNone(tg.get_decryption_key(None, VIDEO_KID))
        self.assertIsNone(tg.get_decryption_key({}, VIDEO_KID))
        self.assertIsNone(tg.get_decryption_key({"key": []}, VIDEO_KID))

    def test_unknown_kid_returns_none(self):
        self.assertIsNone(tg.get_decryption_key(license_payload(), "de" * 16))

    def test_no_kid_still_falls_back_to_first_content_key(self):
        self.assertEqual(tg.get_decryption_key(license_payload()),
                         f"{OTHER_KID}:{'11' * 16}")


class TestCallSitesPassAKid(unittest.TestCase):
    """Static guard: every get_decryption_key call must supply the track KID."""

    def test_all_call_sites_pass_a_kid(self):
        import ast
        import inspect

        source = inspect.getsource(tg)
        tree = ast.parse(source)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "get_decryption_key"]
        # 1 definition site is a FunctionDef, not a Call, so every hit is a caller
        self.assertEqual(len(calls), 4, "expected 4 get_decryption_key call sites")
        for call in calls:
            with self.subTest(line=call.lineno):
                self.assertGreaterEqual(
                    len(call.args), 2,
                    f"get_decryption_key at line {call.lineno} does not pass a kid",
                )
                self.assertIn("kid", ast.unparse(call.args[1]))


if __name__ == "__main__":
    unittest.main()