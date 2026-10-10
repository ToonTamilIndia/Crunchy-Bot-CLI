"""Tests for the credential-scoping guard on CrunchyrollBase.request.

The guard strips cookies and Authorization from any host that is not
Crunchyroll-owned. That is only safe if the trusted list is complete: a missing
entry silently strips credentials from a legitimate API call, which shows up as
an opaque 401 rather than an obvious failure.

The hosts below are derived from the module's own URL constants, so adding a new
Crunchyroll endpoint without trusting its domain fails here immediately.
"""

import unittest

import crunchyroll
from crunchyroll import is_crunchyroll_url


class TestProductionEndpointsAreTrusted(unittest.TestCase):
    """Every URL the library actually calls must be recognised as ours."""

    def _production_urls(self):
        return [
            f"{crunchyroll.CR_API_BASE}/content/v2/cms/series/X",
            f"{crunchyroll.CR_PLAYBACK_BASE}/EP/X/web/chrome/play",
            f"{crunchyroll.CR_PLAYBACK_TOKEN_BASE}/EP/X/token/inactive",
            crunchyroll.CR_LICENSE_URL,
            crunchyroll.CR_ETP_TOKEN_URL,
            crunchyroll.CR_SSO_LOGIN_URL,
            f"{crunchyroll.CR_SSO_AUTHORIZE_URL}?client_id=x",
            f"{crunchyroll.CR_API_BASE}/auth/v1/token",
        ]

    def test_all_production_endpoints_are_trusted(self):
        for url in self._production_urls():
            with self.subTest(url=url):
                self.assertTrue(
                    is_crunchyroll_url(url),
                    "a production endpoint is not recognised as Crunchyroll-owned; "
                    "its credentials would be stripped",
                )

    def test_cdn_is_trusted(self):
        self.assertTrue(is_crunchyroll_url("https://vod-fy-mod.crunchyrollcdn.com/a/video.mp4"))

    def test_playback_domain_is_crunchyrollsvc(self):
        """crunchyrollsvc.com is a separate registrable domain and easy to miss."""
        self.assertTrue(is_crunchyroll_url("https://cr-play-service.prd.crunchyrollsvc.com/v3"))
        self.assertTrue(is_crunchyroll_url("https://cr-license-proxy.prd.crunchyrollsvc.com/v1"))


class TestThirdPartiesAreNotTrusted(unittest.TestCase):
    def test_community_metadata_host_is_untrusted(self):
        self.assertFalse(
            is_crunchyroll_url("https://crunchy-dl.github.io/Crunchy-Downloader/data.json")
        )

    def test_unrelated_hosts_are_untrusted(self):
        for url in ("https://evil.com/", "https://example.test/x", ""):
            with self.subTest(url=url):
                self.assertFalse(is_crunchyroll_url(url))

    def test_lookalike_domains_are_untrusted(self):
        """A suffix match must not be satisfiable by an attacker's domain."""
        for url in (
            "https://crunchyroll.com.evil.net/p",
            "https://notcrunchyroll.com/p",
            "https://crunchyrollcdn.com.evil.io/p",
            "https://crunchyrollsvc.com.evil.io/p",
            "https://evil.com/crunchyroll.com",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_crunchyroll_url(url))

    def test_subdomains_of_trusted_domains_are_trusted(self):
        for url in (
            "https://a.b.crunchyroll.com/x",
            "https://vod-1.crunchyrollcdn.com/x",
            "https://x.crunchyrollsvc.com/x",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_crunchyroll_url(url))

    def test_malformed_url_does_not_raise(self):
        for url in ("not a url", "http://", None, 12345):
            with self.subTest(url=url):
                self.assertFalse(is_crunchyroll_url(url))


class TestGuardPreservesCredentialsForOwnHosts(unittest.TestCase):
    """The guard must not touch requests to Crunchyroll at all."""

    def setUp(self):
        self.cr = crunchyroll.Crunchyroll.__new__(crunchyroll.Crunchyroll)
        self.sent = {}

        class FakeSession:
            def __init__(self, outer):
                self.outer = outer
                self.cookies = {"etp_rt": "secret"}
                self.headers = {"authorization": "Bearer secret"}

            def _record(self, url, kwargs):
                self.outer["url"] = url
                self.outer["kwargs"] = kwargs
                self.outer["cookies_seen"] = dict(self.cookies)
                self.outer["headers_seen"] = dict(self.headers)
                return "response"

            def get(self, url, **kwargs):
                return self._record(url, kwargs)

            def post(self, url, **kwargs):
                return self._record(url, kwargs)

            def patch(self, url, **kwargs):
                return self._record(url, kwargs)

        self.session = FakeSession(self.sent)
        self.cr.session = self.session

    def test_authorization_reaches_playback_endpoint(self):
        self.cr.request("get", f"{crunchyroll.CR_PLAYBACK_BASE}/EP/x/web/chrome/play")
        self.assertEqual(self.sent["headers_seen"].get("authorization"), "Bearer secret")
        self.assertEqual(self.sent["cookies_seen"].get("etp_rt"), "secret")

    def test_authorization_reaches_license_endpoint(self):
        self.cr.request("post", crunchyroll.CR_LICENSE_URL, data=b"x")
        self.assertEqual(self.sent["headers_seen"].get("authorization"), "Bearer secret")

    def test_credentials_are_stripped_from_third_parties(self):
        self.cr.request("get", "https://crunchy-dl.github.io/data.json",
                        cookies={"etp_rt": "secret"})
        self.assertNotIn("etp_rt", self.sent["cookies_seen"])
        self.assertNotIn("authorization", self.sent["headers_seen"])

    def test_session_state_is_restored_after_a_third_party_call(self):
        self.cr.request("get", "https://crunchy-dl.github.io/data.json")
        self.assertEqual(self.session.headers.get("authorization"), "Bearer secret")
        self.assertEqual(self.session.cookies.get("etp_rt"), "secret")


if __name__ == "__main__":
    unittest.main()