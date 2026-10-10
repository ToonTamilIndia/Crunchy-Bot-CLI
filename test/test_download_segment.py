"""End-to-end tests for download_segment against a local HTTP origin.

These cover the two behaviours that matter for large Crunchyroll segments:
a single-file (SegmentBase) representation must be fetched byte-exact whether or
not the origin honours Range requests, and multi-segment DASH must concatenate
strictly in playlist order regardless of completion order.
"""

import hashlib
import random
from contextlib import suppress
import re
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import crunchyroll


def make_payload(size, seed=1234):
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(size))


class _Origin:
    """Mutable route table plus Range policy shared with the request handler."""

    def __init__(self):
        self.routes = {}
        self.allow_ranges = True
        self.seen_ranges = []
        self.range_lock = threading.Lock()


class _RangeHandler(BaseHTTPRequestHandler):
    """Serves ORIGIN.routes, optionally honouring Range requests."""

    origin = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _body_for(self):
        return self.origin.routes.get(self.path)

    def do_GET(self):
        body = self._body_for()
        if body is None:
            self.send_error(404)
            return

        header = self.headers.get("Range")
        match = re.match(r"bytes=(\d+)-(\d*)", header) if header else None
        if match and self.origin.allow_ranges:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else len(body) - 1
            end = min(end, len(body) - 1)
            with self.origin.range_lock:
                self.origin.seen_ranges.append((self.path, start, end))
            chunk = body[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(chunk)
            return

        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes" if self.origin.allow_ranges else "none")
        self.end_headers()
        self.wfile.write(body)


class DownloadSegmentTestCase(unittest.TestCase):
    def setUp(self):
        self.origin = _Origin()
        handler = type("BoundHandler", (_RangeHandler,), {"origin": self.origin})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

        self.temp_dir = Path(tempfile.mkdtemp())
        # Settings are read live from the config module, so that is what a test
        # must override; the crunchyroll globals are only a fallback snapshot.
        import config as config_module
        self._config_module = config_module
        self._saved = {
            name: getattr(crunchyroll, name)
            for name in ("TEMP_DIR", "download_threads", "max_retries", "retry_delay")
        }
        self._saved_config = {
            name: getattr(config_module, name, None)
            for name in ("download_threads", "max_retries", "retry_delay")
        }
        crunchyroll.TEMP_DIR = self.temp_dir
        crunchyroll.download_threads = 4
        crunchyroll.max_retries = 2
        crunchyroll.retry_delay = 0
        config_module.download_threads = 4
        config_module.max_retries = 2
        config_module.retry_delay = 0

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(crunchyroll, name, value)
        for name, value in self._saved_config.items():
            if value is None:
                with suppress(AttributeError):
                    delattr(self._config_module, name)
            else:
                setattr(self._config_module, name, value)
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def publish(self, path, data):
        """Expose bytes at an absolute origin path and return its full URL."""
        self.origin.routes[path] = data
        return f"{self.base_url}{path}"

    def part_ranges(self):
        """Real part fetches, excluding the 1-byte (0-0) size probe."""
        return [
            (start, end)
            for _path, start, end in self.origin.seen_ranges
            if not (start == 0 and end == 0)
        ]

    def download(self, links, name):
        return Path(crunchyroll.download_segment(links, name, "mp4"))


class TestSingleFileRepresentation(DownloadSegmentTestCase):
    def test_range_capable_origin_is_split_and_reassembled_exactly(self):
        """A range-capable origin must fan out and still produce identical bytes."""
        payload = make_payload(400_000)
        url = self.publish("/blob.mp4", payload)

        out = self.download([url], "split")

        self.assertEqual(out.read_bytes(), payload)
        ranges = self.part_ranges()
        self.assertGreater(len(ranges), 1, "expected the file to be split")

        covered = set()
        for start, end in ranges:
            self.assertGreaterEqual(start, 0)
            self.assertLessEqual(end, len(payload) - 1)
            overlap = covered.intersection(range(start, end + 1))
            self.assertFalse(overlap, "parallel ranges must not overlap")
            covered.update(range(start, end + 1))
        self.assertEqual(len(covered), len(payload), "ranges must not skip bytes")

    def test_split_stays_within_configured_thread_count(self):
        """The fan-out must not exceed download_threads parts."""
        payload = make_payload(400_000)
        url = self.publish("/blob.mp4", payload)

        self.download([url], "capped")

        self.assertLessEqual(len(self.part_ranges()), self._config_module.download_threads)

    def test_single_stream_fallback_still_matches_original(self):
        """An origin that ignores Range must fall back cleanly, not corrupt output."""
        payload = make_payload(400_000)
        url = self.publish("/blob.mp4", payload)
        self.origin.allow_ranges = False

        out = self.download([url], "fallback")

        self.assertEqual(out.read_bytes(), payload)
        self.assertEqual(self.origin.seen_ranges, [], "no ranges should be requested")

    def test_scratch_parts_are_cleaned_up(self):
        """Successful assembly must not leave scratch parts behind."""
        payload = make_payload(50_000)
        url = self.publish("/blob.mp4", payload)

        self.download([url], "cleanup")

        self.assertFalse((self.temp_dir / "cleanup" / "segments").exists())

    def test_result_hash_matches_source(self):
        """A byte-exact result must hash to the source digest."""
        payload = make_payload(50_000)
        url = self.publish("/blob.mp4", payload)

        out = self.download([url], "digest")

        self.assertEqual(
            hashlib.sha256(out.read_bytes()).hexdigest(),
            hashlib.sha256(payload).hexdigest(),
        )


class TestMultiSegmentRepresentation(DownloadSegmentTestCase):
    def test_segments_concatenate_in_playlist_order(self):
        """Distinct segments must be joined in playlist order, not completion order."""
        blob = make_payload(60_000)
        parts = [blob[:9_000], blob[9_000:41_000], blob[41_000:]]
        links = [
            self.publish(f"/seg{index}.m4s", chunk)
            for index, chunk in enumerate(parts)
        ]

        out = self.download(links, "multi")

        self.assertEqual(out.read_bytes(), blob)

    def test_init_segment_leads_the_media_segments(self):
        """An initialization segment must stay first when prepended to 'all'."""
        init = make_payload(1_200, seed=7)
        media = make_payload(20_000, seed=8)
        links = [
            self.publish("/init.mp4", init),
            self.publish("/m1.m4s", media[:10_000]),
            self.publish("/m2.m4s", media[10_000:]),
        ]

        out = self.download(links, "withinit")

        self.assertEqual(out.read_bytes(), init + media)

    def test_missing_segment_raises_runtime_error(self):
        """An unreachable segment must fail loudly rather than write a short file."""
        good = self.publish("/good.m4s", make_payload(2_000))
        bad = f"{self.base_url}/missing.m4s"

        with self.assertRaises(RuntimeError):
            crunchyroll.download_segment([good, bad], "partial", "mp4")


class TestStaleScratchIsDiscarded(DownloadSegmentTestCase):
    """A previous failed run must never contaminate the next attempt.

    Part files carry no expected length on the multi-segment path, so a stale
    part that survives a crash would be resumed and concatenated as if it were
    fresh. The scratch directory is wiped on entry to make that impossible.
    """

    def test_oversized_stale_part_is_not_reused(self):
        stale = bytes([0xCC]) * 40_000
        fresh = make_payload(4_000, seed=5)
        tail = bytes([0xAA]) * 9_000
        first = self.publish("/m0.ts", fresh)
        second = self.publish("/m1.ts", tail)

        scratch = self.temp_dir / "stale" / "segments"
        scratch.mkdir(parents=True, exist_ok=True)
        stale_part = scratch / "segment_0.ts"
        stale_part.write_bytes(stale)

        out = self.download([first, second], "stale")

        self.assertEqual(out.read_bytes(), fresh + tail)
        self.assertNotIn(bytes([0xCC]) * 64, out.read_bytes())

    def test_stale_part_counted_as_size_zero(self):
        """A zero-byte leftover must not be mistaken for a completed part."""
        stale = make_payload(3_000, seed=6)
        self.publish("/only.ts", stale)
        scratch = self.temp_dir / "empty" / "segments"
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "segment_0.ts").write_bytes(b"")

        out = self.download([self.publish("/only.ts", stale)], "empty")
        self.assertEqual(out.read_bytes(), stale)


if __name__ == "__main__":
    unittest.main()