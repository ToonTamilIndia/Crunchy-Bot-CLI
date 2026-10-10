"""Concurrency and cancellation tests for the Telegram bot's session state.

`user_states` and `active_downloads` are plain dicts mutated from Pyrogram's
thread pool. These tests drive the real helpers from `tg` to pin the guarantees
the download flow depends on: one download per user, atomic start, real
cancellation, and cleanup that cannot clobber a newer session.
"""

import threading
import unittest

import config
import tg


def make_session(step="confirm_download", message=None):
    return {
        "step": step,
        "url": "",
        "data": {},
        "message": message,
        "is_series": False,
    }


class StateTestCase(unittest.TestCase):
    def setUp(self):
        config.user_states.clear()
        config.active_downloads.clear()
        tg.cancelled_users.clear()

    def tearDown(self):
        config.user_states.clear()
        config.active_downloads.clear()
        tg.cancelled_users.clear()


class TestStartTransitionIsAtomic(StateTestCase):
    def test_first_claim_succeeds(self):
        config.user_states[7] = make_session()
        self.assertTrue(tg.begin_active_download(7, "confirm_download"))
        self.assertTrue(tg.get_active_download(7))
        self.assertEqual(config.user_states[7]["step"], "downloading")

    def test_second_claim_is_refused(self):
        """A double-tapped Start button must not launch the job twice."""
        config.user_states[7] = make_session()
        self.assertTrue(tg.begin_active_download(7, "confirm_download"))
        self.assertFalse(tg.begin_active_download(7, "confirm_download"))

    def test_wrong_step_is_refused(self):
        config.user_states[7] = make_session(step="select_quality")
        self.assertFalse(tg.begin_active_download(7, "confirm_download"))
        self.assertFalse(tg.get_active_download(7))

    def test_missing_session_is_refused(self):
        self.assertFalse(tg.begin_active_download(999, "confirm_download"))

    def test_concurrent_claims_produce_exactly_one_winner(self):
        """Race the transition from many threads, as a double-tap would."""
        config.user_states[42] = make_session()
        winners = []
        barrier = threading.Barrier(16)

        def attempt():
            barrier.wait()
            if tg.begin_active_download(42, "confirm_download"):
                winners.append(1)

        threads = [threading.Thread(target=attempt) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(winners), 1, "exactly one thread may claim the download")


class TestCancellation(StateTestCase):
    def test_cancel_flags_the_user(self):
        config.user_states[7] = make_session(step="downloading")
        tg.request_cancel(7)
        self.assertTrue(tg.is_cancelled(7))

    def test_cancel_drops_session_and_guard(self):
        config.user_states[7] = make_session(step="downloading")
        config.active_downloads[7] = config.user_states[7]
        tg.request_cancel(7)
        self.assertNotIn(7, config.user_states)
        self.assertFalse(tg.get_active_download(7))

    def test_cancel_with_no_session_returns_none(self):
        self.assertIsNone(tg.request_cancel(7))

    def test_new_download_clears_a_stale_cancel_flag(self):
        """After cancelling, the user's next run must not self-cancel."""
        config.user_states[7] = make_session()
        tg.request_cancel(7)
        self.assertTrue(tg.is_cancelled(7))

        config.user_states[7] = make_session()          # user starts over
        self.assertTrue(tg.begin_active_download(7, "confirm_download"))
        self.assertFalse(tg.is_cancelled(7))


class TestCleanupOnlyReleasesOwnedResources(StateTestCase):
    def test_normal_finish_clears_state_and_guard(self):
        state = make_session()
        config.user_states[7] = state
        self.assertTrue(tg.begin_active_download(7, "confirm_download"))
        tg.finish_active_download(7, state)
        self.assertNotIn(7, config.user_states)
        self.assertFalse(tg.get_active_download(7))

    def test_stale_worker_does_not_delete_a_new_session(self):
        """The bug: a cancelled worker's cleanup wiping the user's new run."""
        old = make_session(step="downloading")
        config.user_states[7] = old
        config.active_downloads[7] = old

        tg.request_cancel(7)                      # user cancels run #1

        new = make_session()                      # ...and immediately starts run #2
        config.user_states[7] = new
        self.assertTrue(tg.begin_active_download(7, "confirm_download"))

        tg.finish_active_download(7, old)         # run #1 finally fires late

        self.assertIn(7, config.user_states, "new session must survive")
        self.assertIs(config.user_states[7], new)
        self.assertTrue(tg.get_active_download(7), "new run's guard must survive")

    def test_finish_without_expected_state_clears_everything(self):
        state = make_session()
        config.user_states[7] = state
        config.active_downloads[7] = state
        tg.finish_active_download(7, None)
        self.assertNotIn(7, config.user_states)
        self.assertFalse(tg.get_active_download(7))


class TestSudoUsersAreStillGuarded(StateTestCase):
    def test_sudo_membership_does_not_bypass_the_guard(self):
        """The guard prevents filesystem races; that applies to sudo users too."""
        self.assertNotIn("user_id in sudo_users", _decorator_source())

    def test_active_guard_reports_truthy_for_any_user(self):
        state = make_session()
        config.user_states[5] = state
        config.active_downloads[5] = state
        self.assertTrue(tg.get_active_download(5))


def _decorator_source():
    import inspect
    return inspect.getsource(tg.check_active_download)


if __name__ == "__main__":
    unittest.main()