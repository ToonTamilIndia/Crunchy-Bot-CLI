"""Regression tests for DRM key selection and decryption.

Two independent defects corrupted every downloaded episode:

1. `key.key.hex` instead of `key.key.hex()`. pywidevine stores `kid` as a
   uuid.UUID, whose `.hex` is a property, but `key` as bytes, whose `.hex` is a
   *method*. The extra `()` was missing, so the key field was a bound-method
   repr and mp4decrypt was handed a nonsense key, leaving the track encrypted.
   ffmpeg then decoded ciphertext and emitted "concealing ... DC, AC, MV
   errors" / "corrupt decoded frame" for every frame.

2. Key selection ignored which track was being decrypted. One license covers
   every rendition and returns several keys, all typed CONTENT, so "the first
   CONTENT key" picked a key that belonged to a different rendition.

The MPD supplies the fix: each AdaptationSet declares cenc:default_KID.
"""

import unittest

from lxml import etree

from crunchyroll import (
    LicenseError,
    build_license_key_entries,
    extract_content_key,
    get_track_kid,
    normalize_kid,
    parse_mpd_content,
)

NS = "urn:mpeg:dash:schema:mpd:2011"
CENC = "urn:mpeg:cenc:2013"

VIDEO_KID = "d2b1dbc41da7402d88de5dba577def74"
AUDIO_KID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


def key_entry(kid, key, type_="CONTENT"):
    return {"type": type_, "kid_hex": kid, "key_hex": key}


def mpd(protection_attr_on, video_kid=VIDEO_KID, audio_kid=AUDIO_KID):
    """Build an MPD with the default_KID placed either way."""
    if protection_attr_on == "adaptation_set":
        video_set = f'<AdaptationSet mimeType="video/mp4" cenc:default_KID="{video_kid}">'
        audio_set = f'<AdaptationSet mimeType="audio/mp4" cenc:default_KID="{audio_kid}">'
        video_prot = audio_prot = ""
    else:
        video_set = '<AdaptationSet mimeType="video/mp4">'
        audio_set = '<AdaptationSet mimeType="audio/mp4">'
        video_prot = f'<ContentProtection cenc:default_KID="{video_kid}"/>'
        audio_prot = f'<ContentProtection cenc:default_KID="{audio_kid}"/>'

    return (
        f'<MPD xmlns="{NS}" xmlns:cenc="{CENC}"><Period>'
        f'{video_set}'
        f'<Representation id="v720" width="1280" height="720" bandwidth="3000000">'
        f'{video_prot}<BaseURL>https://cdn/v.mp4</BaseURL></Representation>'
        f'</AdaptationSet>'
        f'{audio_set}'
        f'<Representation id="a-en" bandwidth="128000">'
        f'{audio_prot}<BaseURL>https://cdn/a.mp4</BaseURL></Representation>'
        f'</AdaptationSet>'
        f'</Period></MPD>'
    ).encode()


class TestGetTrackKid(unittest.TestCase):
    def _kid_of(self, doc, rep_id):
        root = etree.fromstring(doc)
        for rep in root.findall(f".//{{{NS}}}Representation"):
            if rep.get("id") == rep_id:
                return get_track_kid(rep)
        self.fail(f"representation {rep_id} not found")

    def test_kid_on_adaptation_set_attribute(self):
        self.assertEqual(self._kid_of(mpd("adaptation_set"), "v720"), VIDEO_KID)

    def test_kid_on_content_protection_element(self):
        self.assertEqual(self._kid_of(mpd("element"), "v720"), VIDEO_KID)

    def test_audio_and_video_kids_differ(self):
        doc = mpd("element")
        self.assertNotEqual(self._kid_of(doc, "v720"), self._kid_of(doc, "a-en"))

    def test_unencrypted_track_has_no_kid(self):
        doc = f'<MPD xmlns="{NS}"><Period><AdaptationSet><Representation id="v" ' \
              f'width="640" height="360" bandwidth="1"><BaseURL>u</BaseURL>' \
              f'</Representation></AdaptationSet></Period></MPD>'.encode()
        self.assertIsNone(self._kid_of(doc, "v"))

    def test_malformed_kid_is_ignored(self):
        doc = f'<MPD xmlns="{NS}" xmlns:cenc="{CENC}"><Period>' \
              f'<AdaptationSet cenc:default_KID="not-a-kid"><Representation id="v" ' \
              f'width="640" height="360" bandwidth="1"><BaseURL>u</BaseURL>' \
              f'</Representation></AdaptationSet></Period></MPD>'.encode()
        self.assertIsNone(self._kid_of(doc, "v"))


class TestParseMpdExposesKid(unittest.TestCase):
    def test_video_entry_carries_kid(self):
        video, _audio = parse_mpd_content(mpd("element"))
        self.assertEqual(video[0]["kid"], VIDEO_KID)

    def test_audio_entry_carries_its_own_kid(self):
        _video, audio = parse_mpd_content(mpd("element"))
        self.assertEqual(audio[0]["kid"], AUDIO_KID)

    def test_unencrypted_track_is_kept_without_kid(self):
        """Free episodes have no protection; dropping them would be a regression."""
        doc = f'<MPD xmlns="{NS}"><Period><AdaptationSet><Representation id="v" ' \
              f'width="640" height="360" bandwidth="1"><BaseURL>u</BaseURL>' \
              f'</Representation></AdaptationSet></Period></MPD>'.encode()
        video, _ = parse_mpd_content(doc)
        self.assertEqual(len(video), 1)
        self.assertNotIn("kid", video[0])


class TestKeySelection(unittest.TestCase):
    def setUp(self):
        self.license = {"key": [
            key_entry("aa" * 16, "11" * 16),   # a different rendition
            key_entry(VIDEO_KID, "22" * 16),   # the video rendition
            key_entry(AUDIO_KID, "33" * 16),   # the audio rendition
        ]}

    def test_picks_the_key_matching_the_video_kid(self):
        self.assertEqual(extract_content_key(self.license, kid=VIDEO_KID), f"{VIDEO_KID}:{'22' * 16}")

    def test_picks_a_different_key_for_audio(self):
        self.assertEqual(extract_content_key(self.license, kid=AUDIO_KID), f"{AUDIO_KID}:{'33' * 16}")

    def test_does_not_default_to_the_first_content_key(self):
        """The regression: the first key belongs to a different rendition."""
        self.assertNotEqual(
            extract_content_key(self.license, kid=VIDEO_KID),
            f"{'aa' * 16}:{'11' * 16}",
        )

    def test_kid_match_ignores_case_and_dashes(self):
        dashed = VIDEO_KID.upper()
        dashed = f"{dashed[0:8]}-{dashed[8:12]}-{dashed[12:16]}-{dashed[16:20]}-{dashed[20:]}"
        self.assertEqual(extract_content_key(self.license, kid=dashed), f"{VIDEO_KID}:{'22' * 16}")

    def test_unknown_kid_raises_instead_of_silently_mismatching(self):
        with self.assertRaises(LicenseError) as ctx:
            extract_content_key(self.license, kid="de" * 16, context="Tokyo Ghoul S1E1")
        self.assertIn("Tokyo Ghoul S1E1", str(ctx.exception))

    def test_missing_kid_still_falls_back(self):
        self.assertEqual(extract_content_key(self.license), f"{'aa' * 16}:{'11' * 16}")


class TestNormalizeKid(unittest.TestCase):
    def test_strips_dashes_and_lowercases(self):
        self.assertEqual(normalize_kid("D2B1DBC4-1DA7-402D-88DE-5DBA577DEF74"), VIDEO_KID)

    def test_none_is_empty(self):
        self.assertEqual(normalize_kid(None), "")


class TestBuildLicenseKeyEntries(unittest.TestCase):
    """Covers the actual construction site that get_license() uses."""

    class FakeKey:
        """Mirrors pywidevine.cdm.Key: kid is a UUID, key is bytes."""

        def __init__(self, type_, kid, key, permissions=()):
            self.type = type_
            self.kid = kid
            self.key = key
            self.permissions = list(permissions)

    def test_key_hex_is_hex_not_a_method_repr(self):
        import uuid

        entries = build_license_key_entries(
            [self.FakeKey("CONTENT", uuid.UUID(int=1), bytes(range(16)))]
        )
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertIsInstance(entry["key_hex"], str,
                              "key_hex must be a hex string, not bytes.hex method")
        self.assertEqual(entry["key_hex"], bytes(range(16)).hex())
        self.assertEqual(entry["kid_hex"], uuid.UUID(int=1).hex)

    def test_accepts_bytearray_and_memoryview(self):
        import uuid

        for raw in (bytearray(range(16)), memoryview(bytes(range(16))), bytes(range(16))):
            with self.subTest(kind=type(raw).__name__):
                entry = build_license_key_entries(
                    [self.FakeKey("CONTENT", uuid.UUID(int=1), raw)]
                )[0]
                self.assertEqual(entry["key_hex"], bytes(range(16)).hex())

    def test_payload_is_directly_usable_by_extract_content_key(self):
        import uuid

        kid = uuid.UUID(int=1).hex
        payload = {"key": build_license_key_entries(
            [self.FakeKey("CONTENT", uuid.UUID(int=1), bytes(range(16)))])}
        resolved = extract_content_key(payload, kid=kid)
        self.assertEqual(resolved, f"{kid}:{bytes(range(16)).hex()}")
        self.assertEqual(len(resolved.split(":")[1]), 32)


class TestAudioAndVideoKeySelection(unittest.TestCase):
    """Audio and video must each get their own key when the MPD says so.

    Verified against a real account: every title surveyed declared one
    default_KID shared by the video and audio AdaptationSets, and the license
    returned four CONTENT keys of which only one matched. The correct key's
    index varied per title, so the old "first CONTENT key" heuristic was right
    only by luck. These tests pin both shapes: the shared-KID layout Crunchyroll
    actually serves, and the per-track layout the matcher must handle if it ever
    appears.
    """

    SHARED = "afcdf05509fc30df9e84302dcf716bf8"

    def _shared_license(self):
        """The real layout: one MPD KID, four unrelated keys in the license."""
        return {"key": [
            key_entry("21f596c6c60311111111111111111111", "11" * 16),
            key_entry(self.SHARED, "22" * 16),
            key_entry("afe939b90ab82222222222222222222", "33" * 16),
            key_entry("fd1ee62c3f95333333333333333333", "44" * 16),
        ]}

    def test_shared_kid_yields_the_same_key_for_both_tracks(self):
        payload = self._shared_license()
        video = extract_content_key(payload, kid=self.SHARED)
        audio = extract_content_key(payload, kid=self.SHARED)
        self.assertEqual(video, audio)
        self.assertEqual(video, f"{self.SHARED}:{'22' * 16}")

    def test_correct_key_is_not_always_the_first_one(self):
        """The matched key sat at index 1 for this title; 'first key' was wrong."""
        payload = self._shared_license()
        first_key = f"{payload['key'][0]['kid_hex']}:{payload['key'][0]['key_hex']}"
        self.assertNotEqual(extract_content_key(payload, kid=self.SHARED), first_key)

    def test_every_kid_in_a_license_resolves_to_its_own_key(self):
        """The matcher must handle a license full of genuinely distinct KIDs."""
        payload = self._shared_license()
        for key in payload["key"]:
            with self.subTest(kid=key["kid_hex"][:12]):
                self.assertEqual(extract_content_key(payload, kid=key["kid_hex"]),
                                 f"{key['kid_hex']}:{key['key_hex']}")

    def test_distinct_audio_and_video_kids_get_distinct_keys(self):
        payload = {"key": [
            key_entry(VIDEO_KID, "aa" * 16),
            key_entry(AUDIO_KID, "bb" * 16),
        ]}
        video = extract_content_key(payload, kid=VIDEO_KID)
        audio = extract_content_key(payload, kid=AUDIO_KID)
        self.assertNotEqual(video, audio)
        self.assertEqual(video.split(":")[1], "aa" * 16)
        self.assertEqual(audio.split(":")[1], "bb" * 16)

    def test_audio_kid_absent_from_license_raises_rather_than_mismatching(self):
        payload = {"key": [key_entry(VIDEO_KID, "aa" * 16)]}
        with self.assertRaises(LicenseError):
            extract_content_key(payload, kid=AUDIO_KID)

    def test_telegram_matches_each_track_the_same_way(self):
        import tg

        payload = {"key": [
            key_entry(VIDEO_KID, "aa" * 16),
            key_entry(AUDIO_KID, "bb" * 16),
        ]}
        self.assertEqual(tg.get_decryption_key(payload, VIDEO_KID),
                         f"{VIDEO_KID}:{'aa' * 16}")
        self.assertEqual(tg.get_decryption_key(payload, AUDIO_KID),
                         f"{AUDIO_KID}:{'bb' * 16}")


class TestCliCallSitesPassAKid(unittest.TestCase):
    """Static guard mirroring the one on tg.py."""

    def test_all_cli_call_sites_pass_a_kid(self):
        import ast
        from pathlib import Path

        cli = Path(__file__).resolve().parent.parent / "cli.py"
        tree = ast.parse(cli.read_text(encoding="utf-8", newline="").replace("\r\n", "\n"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "extract_content_key"]
        self.assertEqual(len(calls), 4, "expected 4 extract_content_key call sites")
        for call in calls:
            with self.subTest(line=call.lineno):
                self.assertGreaterEqual(len(call.args), 3,
                                        f"cli.py:{call.lineno} does not pass a kid")
                self.assertIn("kid", ast.unparse(call.args[2]))


if __name__ == "__main__":
    unittest.main()