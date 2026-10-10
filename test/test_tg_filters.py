"""Tests for the bot's dynamic privilege filters and config coercion.

pyrogram's filters.user() copies its argument into a set when the filter object
is constructed. Every decorator written as `filters.user(sudo_users)` is
therefore frozen at import, so a user added later by /addsudo passes the
`user_id in sudo_users` check but is still rejected by the admin command they
were just granted. These tests pin the dynamic replacement.
"""

import unittest

import tg


class FakeMessage:
    def __init__(self, user_id):
        self.from_user = type("U", (), {"id": user_id})()


class TestSudoFilterIsDynamic(unittest.TestCase):
    def setUp(self):
        self._saved = (list(tg.sudo_users), list(tg.premium_users))
        tg.sudo_users.clear()
        tg.premium_users.clear()

    def tearDown(self):
        tg.sudo_users[:] = self._saved[0]
        tg.premium_users[:] = self._saved[1]

    def test_newly_added_sudo_user_becomes_privileged(self):
        """The bug: /addsudo appended, but the decorator never saw it."""
        self.assertFalse(tg.is_sudo_user(999))

        tg.sudo_users.append(999)          # what /addsudo does

        self.assertTrue(tg.is_sudo_user(999), "in-list check must see the addition")

        # And the filter object used by the decorators must agree.
        # filters.create() returns a Filter whose __call__(client, update)
        # evaluates the lambda on every update.
        message = FakeMessage(999)
        self.assertTrue(tg.is_sudo(None, message),
                        "filters.user(sudo_users) would still reject user 999")

    def test_non_sudo_user_is_still_rejected(self):
        tg.sudo_users.append(999)
        self.assertFalse(tg.is_sudo(None, FakeMessage(1000)))

    def test_removed_sudo_user_loses_privilege(self):
        tg.sudo_users.append(999)
        self.assertTrue(tg.is_sudo(None, FakeMessage(999)))
        tg.sudo_users.remove(999)
        self.assertFalse(tg.is_sudo(None, FakeMessage(999)))

    def test_frozen_filters_are_not_used_for_privilege(self):
        """Guards against reintroducing filters.user(sudo_users)."""
        import inspect
        source = inspect.getsource(tg)
        self.assertNotIn("filters.user(sudo_users)", source)


class TestPremiumFilterIsDynamic(unittest.TestCase):
    def setUp(self):
        self._saved = list(tg.premium_users)
        tg.premium_users.clear()

    def tearDown(self):
        tg.premium_users[:] = self._saved

    def test_premium_added_at_runtime_is_honoured(self):
        self.assertFalse(tg.is_premium_user(555))
        tg.premium_users.append(555)
        self.assertTrue(tg.is_premium(None, FakeMessage(555)))


class TestUserLimits(unittest.TestCase):
    def setUp(self):
        self._saved = (list(tg.sudo_users), list(tg.premium_users))
        tg.sudo_users.clear()
        tg.premium_users.clear()

    def tearDown(self):
        tg.sudo_users[:] = self._saved[0]
        tg.premium_users[:] = self._saved[1]

    def test_limits_are_numbers_comparable_to_an_int_height(self):
        """A quoted limit must not raise TypeError against an int quality."""
        import config
        original = config.REGULAR_USER_VIDEO_LIMIT_P
        try:
            config.REGULAR_USER_VIDEO_LIMIT_P = "480"
            _, max_p = tg.get_user_limits(1234)
            self.assertIsInstance(max_p, int)
            # The comparisons that used to raise TypeError against a str.
            self.assertTrue(480 <= max_p)
            self.assertFalse(720 <= max_p)
        finally:
            config.REGULAR_USER_VIDEO_LIMIT_P = original

    def test_sudo_and_premium_get_unlimited(self):
        inf = float("inf")
        tg.sudo_users.append(1)
        tg.premium_users.append(2)
        self.assertEqual(tg.get_user_limits(1), (inf, inf))
        self.assertEqual(tg.get_user_limits(2), (inf, inf))


class TestBooleanCoercion(unittest.TestCase):
    def test_string_false_is_not_truthy(self):
        """`use_watermark = "False"` must switch the watermark off."""
        self.assertFalse(tg.as_bool("False"))
        self.assertFalse(tg.as_bool("false"))
        self.assertFalse(tg.as_bool(" no "))
        self.assertFalse(tg.as_bool("0"))
        self.assertFalse(tg.as_bool(""))

    def test_string_true_is_truthy(self):
        self.assertTrue(tg.as_bool("True"))
        self.assertTrue(tg.as_bool("yes"))
        self.assertTrue(tg.as_bool("1"))
        self.assertTrue(tg.as_bool("on"))

    def test_real_booleans_and_fallbacks(self):
        self.assertTrue(tg.as_bool(True))
        self.assertFalse(tg.as_bool(False))
        self.assertFalse(tg.as_bool(None))
        self.assertTrue(tg.as_bool(None, default=True))
        self.assertFalse(tg.as_bool("garbage"))
        self.assertTrue(tg.as_bool("garbage", default=True))


class TestIntCoercion(unittest.TestCase):
    def test_quoted_numbers_are_accepted(self):
        self.assertEqual(tg.as_int("480", 360), 480)
        self.assertEqual(tg.as_int(480.0, 360), 480)

    def test_unusable_values_fall_back(self):
        for bad in (None, "", "abc", object()):
            with self.subTest(bad=bad):
                self.assertEqual(tg.as_int(bad, 360), 360)


class TestStrayDirectoryIsNotCreated(unittest.TestCase):
    def test_series_output_dir_is_not_created_relative_to_cwd(self):
        """A relative makedirs litters the process CWD and can fail outright."""
        import inspect
        source = inspect.getsource(tg.process_download)
        self.assertNotIn("os.makedirs(series_output_dir", source)


if __name__ == "__main__":
    unittest.main()