"""Regression tests for job-scoped cancellation and stale-callback rejection.

B05 - cancellation was keyed on the reusable user id, so starting a second job
      discarded the first job's flag and a straggling worker kept downloading.
B06 - a cancel never reached curl/ffmpeg; those children ran to completion and
      the user watched a dead download finish.
B07 - inline buttons were validated by user and step only, so a tap on an old
      keyboard advanced whichever session was current at that moment.
"""

import subprocess
import threading
import time
import unittest

import config
import tg
from platform_tools import OperationCancelled, cancelled, run_cancellable


class FakeChat:
    def __init__(self, chat_id, username=None):
        self.id = chat_id
        self.username = username


class FakeMessage:
    def __init__(self, chat_id=5, username=None):
        self.chat = FakeChat(chat_id, username)
        self.from_user = type("U", (), {"id": chat_id})()


class TestJobScopedCancellation(unittest.TestCase):
    def setUp(self):
        config.user_states.clear()
        config.active_downloads.clear()
        tg.cancelled_jobs.clear()
        tg.cancel_events.clear()

    tearDown = setUp

    def _start(self, user_id=7, step="downloading"):
        config.user_states[user_id] = {"step": step, "url": "", "data": {},
                                       "message": None, "is_series": False,
                                       "nonce": "n0"}
        self.assertTrue(tg.begin_active_download(user_id, step))
        return config.active_downloads[user_id]["job_id"]

    def test_each_job_gets_a_distinct_id(self):
        first = self._start()
        tg.request_cancel(7)
        config.user_states[7] = {"step": "downloading", "url": "", "data": {},
                                 "message": None, "is_series": False, "nonce": "n1"}
        self.assertTrue(tg.begin_active_download(7, "downloading"))
        second = config.active_downloads[7]["job_id"]
        self.assertNotEqual(first, second)

    def test_cancelled_job_stays_cancelled_after_a_new_job_starts(self):
        first = self._start()
        tg.request_cancel(7)
        self._start()                      # user starts a second run
        self.assertTrue(tg.is_job_cancelled(first))

    def test_new_job_is_not_cancelled(self):
        self._start()
        tg.request_cancel(7)
        second = self._start()
        self.assertFalse(tg.is_job_cancelled(second))

    def test_cancel_reaches_the_media_event(self):
        self._start()
        state = config.active_downloads[7]
        self.assertFalse(state["cancel_event"].is_set())
        tg.request_cancel(7)
        self.assertTrue(state["cancel_event"].is_set())

    def test_unknown_job_is_not_cancelled(self):
        self.assertFalse(tg.is_job_cancelled("nope"))
        self.assertFalse(tg.is_job_cancelled(None))


class TestCancellableSubprocess(unittest.TestCase):
    """B06"""

    def test_none_means_never_cancel(self):
        self.assertFalse(cancelled(None))

    def test_set_event_reads_as_cancelled(self):
        event = threading.Event()
        self.assertFalse(cancelled(event))
        event.set()
        self.assertTrue(cancelled(event))

    def test_running_child_is_terminated(self):
        event = threading.Event()
        threading.Timer(0.5, event.set).start()
        started = time.time()
        with self.assertRaises(OperationCancelled):
            run_cancellable(["sleep", "60"], cancel_event=event,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertLess(time.time() - started, 20,
                        "child was not killed promptly")

    def test_pre_set_event_never_starts_the_child(self):
        event = threading.Event()
        event.set()
        marker = "/tmp/opencode/should-not-run"
        with self.assertRaises(OperationCancelled):
            run_cancellable(["touch", marker], cancel_event=event)
        import os
        self.assertFalse(os.path.exists(marker))

    def test_normal_completion_is_unaffected(self):
        result = run_cancellable(["echo", "ok"], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), b"ok")

    def test_download_segment_refuses_when_already_cancelled(self):
        from crunchyroll import download_segment
        event = threading.Event()
        event.set()
        with self.assertRaises(OperationCancelled):
            download_segment(["https://example.invalid/1.m4s"], "cancels", "mp4",
                             cancel_event=event)

    def test_bot_shell_command_reports_cancellation(self):
        event = threading.Event()
        event.set()
        _, stderr, code = tg.run_shell_command(["sleep", "30"], cancel_event=event)
        self.assertNotEqual(code, 0)
        self.assertIn("cancel", stderr.lower())


class TestStaleCallbackRejection(unittest.TestCase):
    """B07"""

    def test_callback_is_stamped_with_the_session_nonce(self):
        state = {"nonce": "abc123"}
        self.assertEqual(tg.cb("quality_1", state), "quality_1|abc123")

    def test_split_round_trips(self):
        action, nonce = tg.split_callback("quality_1|abc123")
        self.assertEqual((action, nonce), ("quality_1", "abc123"))

    def test_legacy_unstamped_callback_has_no_nonce(self):
        self.assertEqual(tg.split_callback("cancel"), ("cancel", None))

    def test_nonce_mismatch_is_detectable(self):
        """The handler's guard is `nonce != session_nonce(state)`."""
        old_state = {"nonce": "old111"}
        new_state = {"nonce": "new222"}
        stamped = tg.cb("confirm_start", old_state)
        action, nonce = tg.split_callback(stamped)
        self.assertNotEqual(nonce, tg.session_nonce(new_state))
        self.assertEqual(action, "confirm_start")

    def test_matching_nonce_is_accepted(self):
        state = {"nonce": "same1"}
        _, nonce = tg.split_callback(tg.cb("audio_done", state))
        self.assertEqual(nonce, tg.session_nonce(state))

    def test_buttons_in_the_bot_carry_a_nonce(self):
        import inspect
        source = inspect.getsource(tg)
        self.assertIn("callback_data=cb(", source)
        # cancel stays unstamped so a stale Cancel still cancels
        self.assertIn('callback_data="cancel"', source)


if __name__ == "__main__":
    unittest.main()