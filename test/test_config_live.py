"""Regression tests for the config-synchronisation and mode-precedence fixes.

Three defects prompted these:

1. `from config import *` snapshotted every setting at import time, so a value
   changed afterwards (`--debug`, `--lossy`, output format) was ignored.
2. `output_format` was half-live: the encoder honoured the fresh value while the
   filename still used the stale import-time copy, producing `.mkv` bytes in a
   `.mp4` name.
3. `original_quality = True` in config silently overrode an explicit `--lossy`.
"""

import ast
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

MODULES = ("cli.py", "tg.py", "crunchyroll.py")


def config_settings():
    tree = ast.parse((REPO / "config.py").read_text(encoding="utf-8").replace("\r\n", "\n"))
    return {t.id for n in tree.body if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)}


class TestLiveConfigReads(unittest.TestCase):
    def test_config_value_tracks_changes(self):
        import config
        from crunchyroll import config_value

        original = config.download_threads
        try:
            config.download_threads = 3
            self.assertEqual(config_value("download_threads"), 3)
            config.download_threads = 8
            self.assertEqual(config_value("download_threads"), 8)
        finally:
            config.download_threads = original

    def test_config_value_defaults_when_absent(self):
        from crunchyroll import config_value
        self.assertEqual(config_value("definitely_not_a_setting", "fallback"), "fallback")

    def test_no_star_import_of_config(self):
        for module in MODULES:
            with self.subTest(module=module):
                tree = ast.parse((REPO / module).read_text(encoding="utf-8", newline="")
                                 .replace("\r\n", "\n"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module == "config":
                        if any(a.name == "*" for a in node.names):
                            self.fail(f"{module} still uses `from config import *`")

    def test_no_bare_config_setting_reads(self):
        """Every config.py setting must be read live, not captured by a star import."""
        settings = config_settings()
        for module in MODULES:
            with self.subTest(module=module):
                tree = ast.parse((REPO / module).read_text(encoding="utf-8", newline="")
                                 .replace("\r\n", "\n"))
                shadowed = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
                        shadowed.add(node.id)
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for arg in node.args.args:
                            shadowed.add(arg.arg)
                    elif isinstance(node, ast.ExceptHandler) and node.name:
                        shadowed.add(node.name)
                bare = {n.id for n in ast.walk(tree)
                        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)} & settings
                self.assertEqual(bare - shadowed, set(),
                                 f"{module} still reads these settings as import-time globals")

    def test_output_format_is_read_live(self):
        """The stale half of the output-format split must be gone."""
        for module in ("cli.py", "tg.py"):
            with self.subTest(module=module):
                source = (REPO / module).read_text(encoding="utf-8", newline="")
                self.assertRegex(source, r"""config_value\(\s*['\"]output_format['\"]\s*\)""")


class TestExplicitModePrecedence(unittest.TestCase):
    def test_lossy_flag_beats_original_quality(self):
        from crunchyroll import resolve_encoding_config
        config = resolve_encoding_config(mode="lossy", original_quality=True)
        self.assertEqual(config.mode, "lossy")

    def test_lossless_flag_beats_original_quality(self):
        from crunchyroll import resolve_encoding_config
        config = resolve_encoding_config(mode="lossless", original_quality=True)
        self.assertEqual(config.mode, "lossless")

    def test_original_quality_still_applies_without_a_flag(self):
        """The legacy switch must keep working when no mode was requested."""
        from crunchyroll import resolve_encoding_config
        config = resolve_encoding_config(mode=None, original_quality=True)
        self.assertEqual(config.mode, "lossless")

    def test_default_is_lossy(self):
        from crunchyroll import resolve_encoding_config
        config = resolve_encoding_config(mode=None, original_quality=False)
        self.assertEqual(config.mode, "lossy")


class TestPython311Compatibility(unittest.TestCase):
    def test_nested_same_quote_fstrings_rejected(self):
        """PEP 701 (3.12) allows these; 3.11 does not, and 3.11 is the user's runtime."""
        pattern = __import__("re").compile(r"""f(["'])(?:[^\\]|\\.)*?\1""", __import__("re").DOTALL)
        for module in MODULES:
            with self.subTest(module=module):
                text = (REPO / module).read_text(encoding="utf-8", newline="")
                bad = [(i, l.strip()) for i, l in enumerate(text.replace("\r\n", "\n").split("\n"), 1)
                       if any(pattern.search(l) and _nested_same_quote(l) for l in [l])]
                self.assertEqual(bad, [], f"{module} uses a 3.12-only nested same-quote f-string: {bad}")


def _nested_same_quote(line):
    import re
    for match in re.finditer(r"""f(["'])""", line):
        quote, rest, depth = match.group(1), line[match.end():], 0
        for index, char in enumerate(rest):
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(0, depth - 1)
            elif depth and char == quote:
                backslashes = 0
                probe = index - 1
                while probe >= 0 and rest[probe] == "\\":
                    backslashes += 1
                    probe -= 1
                if backslashes % 2 == 0:
                    return True
    return False


class TestStartup(unittest.TestCase):
    def test_modules_import(self):
        for module in ("tg.py", "crunchyroll.py"):
            with self.subTest(module=module):
                # cli.py drives an interactive prompt at import time, so it is
                # covered by --help / the static checks instead.
                proc = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0,{str(REPO)!r});"
                                                                f" import {module[:-3]}"],
                                      capture_output=True, timeout=120, cwd=REPO)
                self.assertEqual(proc.returncode, 0, proc.stderr.decode()[-800:])


if __name__ == "__main__":
    unittest.main()