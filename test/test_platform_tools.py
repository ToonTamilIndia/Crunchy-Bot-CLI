"""Tests for cross-platform executable resolution.

The repository ships a Linux ELF `mp4decrypt`, so on Windows the resolver must
select `mp4decrypt.exe` and must never fall back to the extensionless ELF: it
exists but cannot execute, and picking it fails at spawn with a confusing error.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import platform_tools
from platform_tools import executable_name, resolve_executable


class TestExecutableName(unittest.TestCase):
    def test_windows_appends_exe_once(self):
        with mock.patch.object(os, "name", "nt"):
            self.assertEqual(executable_name("mp4decrypt"), "mp4decrypt.exe")

    def test_windows_does_not_double_append(self):
        with mock.patch.object(os, "name", "nt"):
            self.assertEqual(executable_name("mp4decrypt.exe"), "mp4decrypt.exe")

    def test_posix_is_unchanged(self):
        with mock.patch.object(os, "name", "posix"):
            self.assertEqual(executable_name("mp4decrypt"), "mp4decrypt")


class ResolverTestCase(unittest.TestCase):
    """Builds a throwaway project root so resolution can be exercised per OS."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def place(self, name, payload=b"MZ"):
        target = self.root / name
        target.write_bytes(payload)
        return target

    def resolve_on(self, os_name, system_name):
        """Run resolve_executable as if running on the given platform."""
        with mock.patch.object(platform_tools, "APP_ROOT", self.root), \
             mock.patch.object(os, "name", os_name), \
             mock.patch.object(platform_tools.platform, "system", lambda: system_name), \
             mock.patch.object(platform_tools.shutil, "which", lambda n: None):
            return resolve_executable("mp4decrypt")


class TestProjectFallbackSelection(ResolverTestCase):
    def test_windows_prefers_the_exe(self):
        """Both builds present: Windows must select the PE image."""
        self.place("mp4decrypt", b"\x7fELF")
        exe = self.place("mp4decrypt.exe")
        self.assertEqual(self.resolve_on("nt", "Windows"), str(exe.resolve()))

    def test_windows_never_selects_the_extensionless_elf(self):
        """Only the ELF exists: fail loudly rather than return an unusable file."""
        self.place("mp4decrypt", b"\x7fELF")
        with self.assertRaises(FileNotFoundError) as ctx:
            self.resolve_on("nt", "Windows")
        self.assertIn("Linux binary", str(ctx.exception))

    def test_posix_still_finds_the_extensionless_build(self):
        elf = self.place("mp4decrypt", b"\x7fELF")
        self.assertEqual(self.resolve_on("posix", "Linux"), str(elf.resolve()))

    def test_posix_prefers_the_native_build_over_the_exe(self):
        self.place("mp4decrypt", b"\x7fELF")
        self.place("mp4decrypt.exe")
        self.assertTrue(self.resolve_on("posix", "Linux").endswith("mp4decrypt"))
        self.assertFalse(self.resolve_on("posix", "Linux").endswith(".exe"))


class TestBundledBinaries(unittest.TestCase):
    root = Path(platform_tools.APP_ROOT)

    def test_project_ships_both_platform_builds(self):
        self.assertTrue((self.root / "mp4decrypt").is_file(), "Linux build missing")
        self.assertTrue((self.root / "mp4decrypt.exe").is_file(), "Windows build missing")

    def test_windows_build_is_a_pe_image_not_a_renamed_elf(self):
        """Guards against copying the ELF and renaming it to .exe."""
        head = (self.root / "mp4decrypt.exe").read_bytes()[:2]
        self.assertEqual(head, b"MZ", "mp4decrypt.exe must be a PE image")

    def test_linux_build_is_an_elf_image(self):
        head = (self.root / "mp4decrypt").read_bytes()[:4]
        self.assertEqual(head, b"\x7fELF", "mp4decrypt must be an ELF image")


if __name__ == "__main__":
    unittest.main()