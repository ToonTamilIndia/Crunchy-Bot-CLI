"""Regression tests for the live authorization filter and the quality prompt.

B08 - get_download_access_filter() built filters.chat()/filters.private once at
import, so restricting AUTHORIZED_USERS later still let any private user
through. The sudo half of the filter was already dynamic; the chat half was not.

B03 - the "Enter the video quality" prompt sat inside the loop that prints the
renditions, so N renditions produced N prompts.
"""

import ast
import re
import unittest
from pathlib import Path

from pyrogram import enums

import config
import tg

REPO = Path(__file__).resolve().parent.parent


def read_source(path):
    """Read a source file preserving line endings, on any supported interpreter.

    pathlib.Path.read_text() only gained the ``newline`` keyword in Python
    3.13, so using it that way breaks this module on Python 3.11.
    """
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


class FakeChat:
    def __init__(self, chat_id, chat_type, username=None):
        self.id = chat_id
        self.type = chat_type
        self.username = username


class FakeMessage:
    def __init__(self, chat_id, chat_type, username=None):
        self.chat = FakeChat(chat_id, chat_type, username)
        self.from_user = type("U", (), {"id": chat_id})()


PRIVATE = enums.ChatType.PRIVATE
GROUP = enums.ChatType.GROUP


class TestAuthorizationIsLive(unittest.TestCase):
    def setUp(self):
        self._saved = config.AUTHORIZED_USERS

    def tearDown(self):
        config.AUTHORIZED_USERS = self._saved

    def test_empty_allowlist_allows_any_private_chat(self):
        config.AUTHORIZED_USERS = []
        self.assertTrue(tg.update_is_authorized(FakeMessage(999, PRIVATE)))
        self.assertFalse(tg.update_is_authorized(FakeMessage(999, GROUP)))

    def test_restricting_the_allowlist_takes_effect_immediately(self):
        """The bug: the filter was built at import, so this never applied."""
        config.AUTHORIZED_USERS = []
        self.assertTrue(tg.update_is_authorized(FakeMessage(999, PRIVATE)))
        config.AUTHORIZED_USERS = [111]
        self.assertFalse(tg.update_is_authorized(FakeMessage(999, PRIVATE)),
                         "restrictive allowlist was ignored")
        self.assertTrue(tg.update_is_authorized(FakeMessage(111, PRIVATE)))

    def test_username_entries_are_honoured(self):
        config.AUTHORIZED_USERS = ["alice"]
        self.assertTrue(tg.update_is_authorized(
            FakeMessage(5, PRIVATE, username="alice")))
        self.assertFalse(tg.update_is_authorized(
            FakeMessage(5, PRIVATE, username="bob")))

    def test_missing_chat_is_denied(self):
        config.AUTHORIZED_USERS = []
        self.assertFalse(tg.update_is_authorized(type("M", (), {"chat": None})()))

    def test_filter_is_not_frozen_at_import(self):
        source = read_source(REPO / "tg.py").replace("\r\n", "\n")
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "DOWNLOAD_ACCESS_FILTER"
                    for t in node.targets):
                rendered = ast.unparse(node.value)
                self.assertIn("update_is_authorized", rendered)
                self.assertNotIn("filters.chat(", rendered)
                return
        self.fail("DOWNLOAD_ACCESS_FILTER assignment not found")


class TestQualityPromptRunsOnce(unittest.TestCase):
    """The quality prompt must not be nested inside the rendition-listing loop.

    Both the single-episode and the batch path print the menu in a for-loop;
    the prompt itself belongs after that loop, otherwise N renditions produce
    N prompts.
    """

    @staticmethod
    def _tree():
        source = read_source(REPO / "cli.py").replace("\r\n", "\n")
        tree = ast.parse(source)
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        return tree, parents

    @staticmethod
    def _quality_prompts(tree):
        found = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "input" and node.args
                    and "video quality" in ast.unparse(node.args[0]).lower()):
                found.append(node)
        return found

    @staticmethod
    def _menu_loops(tree):
        """For-loops whose body only prints the rendition menu.

        A loop qualifies when it prints height+bandwidth and contains no
        input() of its own. The per-episode batch loop contains both strings
        too, so the absence of input() is what distinguishes the menu loop
        from an outer loop that merely encloses it.
        """
        loops = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.For):
                continue
            rendered = ast.unparse(n)
            if "bandwidth" in rendered and "height" in rendered and "input(" not in rendered:
                loops.append(n)
        return loops

    def test_both_quality_prompts_exist(self):
        """Single-episode and batch each prompt once, outside the menu loop."""
        tree, _ = self._tree()
        prompts = self._quality_prompts(tree)
        self.assertEqual(len(prompts), 2,
                         f"expected 2 quality prompts, found {len(prompts)}")

    def test_menu_loops_exist(self):
        tree, _ = self._tree()
        self.assertEqual(len(self._menu_loops(tree)), 2,
                         "expected one rendition-menu loop per mode")

    def test_no_quality_prompt_is_nested_in_a_menu_loop(self):
        tree, parents = self._tree()
        menu_loops = self._menu_loops(tree)
        for call in self._quality_prompts(tree):
            with self.subTest(line=call.lineno):
                node = call
                while node in parents:
                    node = parents[node]
                    self.assertNotIn(
                        node, menu_loops,
                        f"line {call.lineno}: the quality prompt is nested inside "
                        f"the rendition-listing loop, so one prompt is shown per "
                        f"rendition")

    def test_menu_loops_only_print(self):
        tree, _ = self._tree()
        for n in self._menu_loops(tree):
            with self.subTest(line=n.lineno):
                self.assertNotIn("input(", ast.unparse(n),
                                 "rendition-printing loop still prompts")


if __name__ == "__main__":
    unittest.main()
