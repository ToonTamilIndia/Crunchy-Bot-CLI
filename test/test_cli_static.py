"""Static checks over cli.py.

cli.py is a script: importing it runs a whole download, so no test can import it
directly. That left a class of bug completely uncovered -- reading a name before
it is assigned, or reading a name config.py never defines. Both shipped once and
broke every download with a bare NameError, so they are checked statically here.
"""

import ast
import builtins
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "cli.py"
CONFIG = REPO / "config.py"

BUILTINS = set(dir(builtins))
BLOCK_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
               ast.AsyncWith, ast.Try, ast.Match)
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def cli_source():
    return CLI.read_text(encoding="utf-8").replace("\r\n", "\n")


def cli_tree():
    return ast.parse(cli_source())


def config_names():
    """Top-level names config.py defines; `from config import *` binds these."""
    names = set()
    tree = ast.parse(CONFIG.read_text(encoding="utf-8").replace("\r\n", "\n"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def module_bindings():
    """Names available before the first module-level statement runs.

    Excludes assignment targets on purpose: those are bound in source order by
    the caller, and seeding them here would hide a read-before-assignment.
    """
    names = set()
    for node in cli_tree().body:
        if isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def module_flow(body):
    """Yield module-level statements, flattening control flow into one scope."""
    for node in body:
        yield node
        if isinstance(node, BLOCK_NODES):
            for field in ("body", "orelse", "finalbody"):
                yield from module_flow(getattr(node, field, []) or [])
            for handler in getattr(node, "handlers", []) or []:
                yield from module_flow(handler.body)
            for case in getattr(node, "cases", []) or []:
                yield from module_flow(case.body)


def scope_free_nodes(root):
    """Descend into `root` but stop at nested function/lambda/class scopes."""
    if isinstance(root, SCOPE_NODES):
        return
    stack = list(ast.iter_child_nodes(root))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, SCOPE_NODES):
            stack.extend(ast.iter_child_nodes(node))


def comprehension_names(tree):
    """Loop variables of comprehensions and lambda parameters.

    In `[x for x in y]` the element expression is written before the loop
    variable is bound, so a strict source-order scan sees a phantom read. These
    names live in their own scope and are pre-seeded to avoid that false positive.
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.comprehension):
            for child in ast.walk(node.target):
                if isinstance(child, ast.Name):
                    names.add(child.id)
        elif isinstance(node, ast.Lambda):
            for arg in node.args.args:
                names.add(arg.arg)
    return names


def binding_events(tree):
    """(line, column, name) for every module-level binding, in source order."""
    events = []
    for node in module_flow(tree.body):
        for child in scope_free_nodes(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                events.append((child.lineno, child.col_offset, child.id))
        # Bindings that are not Name nodes.
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    events.append((child.lineno, child.col_offset, (alias.asname or alias.name).split(".")[0]))
            elif isinstance(child, ast.ImportFrom):
                for alias in child.names:
                    events.append((child.lineno, child.col_offset, alias.asname or alias.name))
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                events.append((child.lineno, child.col_offset, child.name))
            elif isinstance(child, ast.ExceptHandler) and child.name:
                events.append((child.lineno, child.col_offset, child.name))
    return events


def load_events(tree):
    """(line, column, name) for every module-level read, in source order."""
    events = []
    for node in module_flow(tree.body):
        for child in scope_free_nodes(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                events.append((child.lineno, child.col_offset, child.id))
    return events


class TestNoUseBeforeAssignment(unittest.TestCase):
    """A module-level name read before it is bound is a guaranteed NameError.

    Bindings and reads are interleaved in source order. Only module-level flow
    is considered: function, lambda and comprehension bodies resolve their own
    names and would otherwise produce false positives.
    """

    def test_no_module_level_name_is_read_before_it_is_bound(self):
        tree = cli_tree()
        available = set(BUILTINS) | module_bindings() | config_names() | comprehension_names(tree)

        timeline = [(line, col, 0, name) for line, col, name in binding_events(tree)]
        timeline += [(line, col, 1, name) for line, col, name in load_events(tree)]
        timeline.sort()

        problems = []
        for line, col, is_load, name in timeline:
            if is_load:
                if name not in available:
                    problems.append((name, line))
            else:
                available.add(name)

        unique = sorted(set(problems), key=lambda item: item[1])
        self.assertEqual(
            unique, [],
            "cli.py reads these names before they are bound: "
            + ", ".join(f"{name!r} at line {line}" for name, line in unique),
        )


class TestConfigNamesResolve(unittest.TestCase):
    def test_custom_title_setting_name_matches(self):
        """The feature read `custom_title`; config.py defines `Custom_Title`."""
        self.assertIn("Custom_Title", config_names())
        self.assertNotIn("custom_title.format(", cli_source())


class TestInteractivePromptsAreGuarded(unittest.TestCase):
    """int(input()) without a ValueError handler turns a typo into a traceback."""

    def test_int_from_input_is_inside_a_value_error_handler(self):
        ranges = []
        for node in ast.walk(cli_tree()):
            if not isinstance(node, ast.Try):
                continue
            catches = any(
                (isinstance(h.type, ast.Name) and h.type.id == "ValueError")
                or (isinstance(h.type, ast.Tuple)
                    and any(isinstance(e, ast.Name) and e.id == "ValueError" for e in h.type.elts))
                for h in node.handlers
            )
            if catches:
                ranges.append((node.lineno, node.end_lineno))

        unguarded = []
        for node in ast.walk(cli_tree()):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "int" and node.args
                    and isinstance(node.args[0], ast.Call)
                    and isinstance(node.args[0].func, ast.Name)
                    and node.args[0].func.id == "input"):
                if not any(start <= node.lineno <= end for start, end in ranges):
                    unguarded.append(node.lineno)
        self.assertEqual(unguarded, [], f"unguarded int(input(...)) at lines {unguarded}")


if __name__ == "__main__":
    unittest.main()