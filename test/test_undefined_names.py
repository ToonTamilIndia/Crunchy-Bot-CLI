"""Undefined-name checks for the two entry points, via symtable.

cli.py and tg.py are scripts: importing either runs the program, so no test can
import them. That left `custom_title` (config.py defines `Custom_Title`) and
`ep_num_str` (never bound anywhere) shipping unnoticed -- each raised NameError
the moment that code path ran. symtable resolves names properly per scope, so
this catches what a regex or a bare AST walk cannot.
"""

import ast
import builtins
import symtable
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = ("cli.py", "tg.py")
BUILTINS = set(dir(builtins))


def source(name):
    return (REPO / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def star_imported_names(name):
    """Names a script binds via `from <module> import *`."""
    names = set()
    for node in ast.parse(source(name)).body:
        if isinstance(node, ast.ImportFrom) and node.module in ("config", "crunchyroll"):
            names.update(a.asname or a.name for a in node.names)
    return names


def config_names():
    names = set()
    for node in ast.parse(source("config.py")).body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def tables(root):
    yield root
    for child in root.get_children():
        yield from tables(child)


def undefined_names(script):
    """Names referenced but never bound, in any scope of the script."""
    root = symtable.symtable(source(script), script, "exec")
    bound = set(BUILTINS) | config_names() | star_imported_names(script)
    for table in tables(root):
        for sym in table.get_symbols():
            if (sym.is_assigned() or sym.is_imported() or sym.is_parameter()
                    or sym.is_namespace()):
                bound.add(sym.get_name())

    problems = set()
    for table in tables(root):
        for sym in table.get_symbols():
            name = sym.get_name()
            if name.startswith("__") or name in bound:
                continue
            if (sym.is_referenced() and not sym.is_assigned() and not sym.is_imported()
                    and not sym.is_parameter() and not sym.is_namespace()):
                problems.add(name)
    return problems


class TestNoUndefinedNames(unittest.TestCase):
    def test_entry_points_have_no_undefined_names(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                problems = undefined_names(script)
                self.assertEqual(
                    problems, set(),
                    f"{script} references names that are never defined: {sorted(problems)}",
                )


class TestCustomTitleSettingName(unittest.TestCase):
    """config.py defines `Custom_Title`; both scripts used to read `custom_title`."""

    def test_config_defines_the_expected_name(self):
        self.assertIn("Custom_Title", config_names())

    def test_scripts_reference_the_defined_name(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertNotIn("custom_title.format(", source(script))
                self.assertIn("Custom_Title.format(", source(script))


class TestEpNumStrIsBound(unittest.TestCase):
    """The batch error handler interpolated a name that was never assigned."""

    def test_cli_does_not_reference_ep_num_str(self):
        self.assertNotIn("ep_num_str", source("cli.py"))


if __name__ == "__main__":
    unittest.main()