"""Guard against syntax that only parses on Python 3.12+.

Nested same-quote f-strings were legalised by PEP 701 in 3.12. This project
runs on Python 3.11, where `f"{value("key")}"` is a SyntaxError, so a codemod
or an edit that introduces one would leave the user unable to start the program.
ast.parse on the running interpreter cannot see this, so the check is textual.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = ("cli.py", "tg.py", "crunchyroll.py", "platform_tools.py", "config.py")

# f"...{ ... " ... " ... }..." -- the inner quote matches the f-string delimiter.
FSTRING = re.compile(r"""f(["'])(?:[^\\]|\\.)*?\1""", re.DOTALL)


def nested_quote_offenders(source):
    """Lines where an f-string's replacement field reuses the delimiter quote."""
    offenders = []
    for number, line in enumerate(source.replace("\r\n", "\n").split("\n"), start=1):
        for match in re.finditer(r"""f(["'])""", line):
            quote = match.group(1)
            rest = line[match.end():]
            # Walk the replacement fields, skipping escaped delimiters.
            depth = 0
            for index, char in enumerate(rest):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth = max(0, depth - 1)
                elif depth > 0 and char == quote:
                    # Is it escaped?
                    backslashes = 0
                    probe = index - 1
                    while probe >= 0 and rest[probe] == "\\":
                        backslashes += 1
                        probe -= 1
                    if backslashes % 2 == 0:
                        offenders.append((number, line.strip()[:90]))
                        break
    return offenders


class TestPython311CompatibleSyntax(unittest.TestCase):
    def test_no_nested_same_quote_fstrings(self):
        for script in SCRIPTS:
            source = (REPO / script).read_text(encoding="utf-8")
            with self.subTest(script=script):
                offenders = nested_quote_offenders(source)
                self.assertEqual(
                    offenders, [],
                    f"{script} uses a nested same-quote f-string, which is a "
                    f"SyntaxError on Python 3.11: {offenders}",
                )

    def test_scripts_parse(self):
        import ast
        for script in SCRIPTS:
            with self.subTest(script=script):
                ast.parse((REPO / script).read_text(encoding="utf-8", newline="")
                          .replace("\r\n", "\n"))


if __name__ == "__main__":
    unittest.main()