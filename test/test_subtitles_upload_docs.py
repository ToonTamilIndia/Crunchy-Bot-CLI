"""Regression tests for the subtitle-identity, upload and documentation fixes.

B18 - batch remembered only a language, so requesting an en-US subtitle replayed
      an en-US caption when an episode offered both.
B19 - scratch filenames were title+language, so an en-US caption and an en-US
      subtitle resolved to the same path and the second overwrote the first.
B20 - the track prompt sat inside the subtitles branch, so a caption-only
      episode never asked and silently downloaded nothing.
B21 - preferences were only marked collected at end of episode, so an early
      skip made the next episode re-prompt.
B23 - a failed upload returned None and the caller announced success anyway.
B24 - the uploader always claimed 1280x720 whatever the file actually was.
B28 - the README documented DEFAULT_QUALITY / ENABLE_WATERMARK / DEBUG, none of
      which any code read.
"""

import ast
import unittest
from pathlib import Path

from crunchyroll import resolve_batch_subtitles, track_key

REPO = Path(__file__).resolve().parent.parent

TRACKS = [
    {"type": "caption", "language": "en-US", "url": "c.vtt", "format": "vtt"},
    {"type": "subtitle", "language": "en-US", "url": "s.vtt", "format": "vtt"},
    {"type": "subtitle", "language": "es-ES", "url": "es.vtt", "format": "vtt"},
]


class TestTrackIdentity(unittest.TestCase):
    """B18"""

    def test_key_is_type_plus_language(self):
        self.assertEqual(track_key(TRACKS[0]), ("caption", "en-US"))
        self.assertEqual(track_key(TRACKS[1]), ("subtitle", "en-US"))

    def test_key_is_idempotent(self):
        key = track_key(TRACKS[1])
        self.assertEqual(track_key(key), key)
        self.assertEqual(track_key(list(key)), key)

    def test_subtitle_and_caption_with_one_language_do_not_collide(self):
        sub = resolve_batch_subtitles([track_key(TRACKS[1])], TRACKS)
        cap = resolve_batch_subtitles([track_key(TRACKS[0])], TRACKS)
        self.assertEqual([t["type"] for t in sub], ["subtitle"])
        self.assertEqual([t["type"] for t in cap], ["caption"])
        self.assertNotEqual(sub[0]["url"], cap[0]["url"])

    def test_wrong_track_is_never_returned(self):
        result = resolve_batch_subtitles([("subtitle", "en-US")], TRACKS)
        self.assertEqual([t["url"] for t in result], ["s.vtt"])

    def test_caption_only_episode_falls_back_to_language(self):
        result = resolve_batch_subtitles([track_key(TRACKS[1])], [TRACKS[0]])
        self.assertEqual([t["type"] for t in result], ["caption"])

    def test_absent_language_is_skipped(self):
        self.assertEqual(resolve_batch_subtitles([("subtitle", "fr-FR")], TRACKS), [])

    def test_plain_language_still_resolves(self):
        """Legacy callers passing a bare language must keep working."""
        result = resolve_batch_subtitles(["es-ES"], TRACKS)
        self.assertEqual([t["language"] for t in result], ["es-ES"])

    def test_empty_selection_returns_empty(self):
        self.assertEqual(resolve_batch_subtitles([], TRACKS), [])
        self.assertEqual(resolve_batch_subtitles(None, TRACKS), [])


class TestSubtitleFilenames(unittest.TestCase):
    """B19"""

    @staticmethod
    def _stem():
        tree = ast.parse((REPO / "cli.py").read_text(encoding="utf-8")
                         .replace("\r\n", "\n"))
        node = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "subtitle_stem")
        ns = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<x>", "exec"), ns)
        return ns["subtitle_stem"]

    def test_same_language_different_kind_differ(self):
        stem = self._stem()
        cap = stem("E01", {"type": "caption", "language": "en-US"}, "srt")
        sub = stem("E01", {"type": "subtitle", "language": "en-US"}, "srt")
        self.assertNotEqual(cap, sub)

    def test_kind_is_in_the_name(self):
        stem = self._stem()
        self.assertIn("caption", stem("E01", {"type": "caption", "language": "en-US"}, "vtt"))
        self.assertIn("subtitle", stem("E01", {"type": "subtitle", "language": "en-US"}, "vtt"))

    def test_extension_is_honoured(self):
        stem = self._stem()
        sub = {"type": "subtitle", "language": "en-US"}
        self.assertTrue(stem("E01", sub, "vtt").endswith(".vtt"))
        self.assertTrue(stem("E01", sub, "srt").endswith(".srt"))

    def test_no_title_language_only_name_remains(self):
        source = (REPO / "cli.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertNotIn('f"{Title}_{subtitle[\'language\']}', source)


class TestBatchPromptPlacement(unittest.TestCase):
    """B20 + B21"""

    @staticmethod
    def _tree():
        return ast.parse((REPO / "cli.py").read_text(encoding="utf-8")
                         .replace("\r\n", "\n"))

    def test_prompt_is_not_inside_the_subtitles_branch(self):
        tree = self._tree()
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        # The single-episode path already prompts under an `or` of both kinds,
        # which is correct. Only the batch prompt was mis-nested, so target the
        # one guarded by the preference flag.
        lines = (REPO / "cli.py").read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        batch_guard = next(i for i, l in enumerate(lines)
                           if "if aka == 1 and available_tracks:" in l)
        prompts = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "input" and n.args
                   and "track number" in ast.unparse(n.args[0]).lower()
                   and n.lineno > batch_guard]
        self.assertTrue(prompts, "batch track prompt not found")
        for prompt in prompts:
            node = prompt
            enclosing = []
            while node in parents:
                node = parents[node]
                enclosing.append(node)
            # A shared `if captions ... or subtitles ...:` guard is correct;
            # only a subtitles-ONLY `if` mis-nests the prompt.
            for node in enclosing:
                if not isinstance(node, ast.If):
                    continue
                test = ast.unparse(node.test)
                if "subtitles" in test and "captions" not in test:
                    self.fail(
                        f"line {prompt.lineno}: the track prompt is nested in a "
                        f"subtitles-only branch ({test}), so a caption-only "
                        f"episode never asks")

    def test_prompt_also_requires_available_tracks(self):
        source = (REPO / "cli.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("if aka == 1 and available_tracks:", source)

    def test_preferences_marked_collected_at_prompt_time(self):
        """aka must flip when choices are captured, not at end of episode."""
        tree = self._tree()
        lines = (REPO / "cli.py").read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        prompt_at = next(i for i, l in enumerate(lines)
                         if "if aka == 1 and available_tracks:" in l)
        aka_at = next(i for i, l in enumerate(lines)
                      if i > prompt_at and l.strip() == "aka = 0")
        # the original reset sat in the per-episode cleanup near the end
        self.assertLess(aka_at - prompt_at, 30,
                        "aka is reset far from the prompt, so an early skip re-asks")


class TestUploadOutcome(unittest.TestCase):
    """B23 + B24"""

    @staticmethod
    def _tree():
        return ast.parse((REPO / "tg.py").read_text(encoding="utf-8")
                         .replace("\r\n", "\n"))

    def test_upload_reports_success(self):
        source = (REPO / "tg.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("return True,", source)

    def test_upload_reports_failure_instead_of_swallowing(self):
        source = (REPO / "tg.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("return False,", source)

    def test_caller_does_not_announce_success_unconditionally(self):
        source = (REPO / "tg.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("if ok:", source)
        self.assertIn("Upload failed:", source)

    def test_dimensions_are_probed_not_hardcoded(self):
        source = (REPO / "tg.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("def get_dimensions(", source)
        self.assertIn("get_dimensions(file_path)", source)
        self.assertNotIn('"width": 1280', source)
        self.assertNotIn('"height": 720', source)

    def test_get_dimensions_returns_zero_when_unknown(self):
        tree = self._tree()
        node = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "get_dimensions")
        ns = {"createParser": lambda p: None, "extractMetadata": lambda p: None}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<x>", "exec"), ns)
        self.assertEqual(ns["get_dimensions"]("nope.mp4"), (0, 0))


class TestReadmeSettingsAreReal(unittest.TestCase):
    """B28"""

    def _config_names(self):
        tree = ast.parse((REPO / "config.py").read_text(encoding="utf-8")
                         .replace("\r\n", "\n"))
        return {t.id for n in tree.body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}

    def test_readme_config_block_only_names_real_settings(self):
        names = self._config_names()
        text = (REPO / "README.md").read_text(encoding="utf-8")
        start = text.index("## Configuration")
        block = text[start:text.index("```", text.index("```python", start) + 10)]
        # assignments shown in the example
        assigned = set()
        for line in block.split("```python")[1].split("```")[0].splitlines():
            line = line.split("#")[0].strip()
            if "=" in line and not line.startswith("print"):
                assigned.add(line.split("=")[0].strip())
        unknown = {a for a in assigned if a and a not in names}
        self.assertEqual(unknown, set(),
                         f"README documents settings the code never reads: {unknown}")

    def test_documented_settings_are_not_only_called_out_as_absent(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        start = text.index("## Configuration")
        example = text[start:text.index("```", text.index("```python", start) + 10)]
        for name in ("DEFAULT_QUALITY", "ENABLE_WATERMARK"):
            self.assertNotIn(f"{name} =", example,
                             f"{name} is still presented as a setting")


if __name__ == "__main__":
    unittest.main()