"""Cross-platform discovery and execution of external media tools."""

from pathlib import Path
import os
import platform
import shlex
import shutil
import subprocess
import sys
import ctypes
from ctypes import wintypes


APP_ROOT = Path(__file__).resolve().parent


def executable_name(name):
    """Return the native executable name for the current platform."""
    if os.name == "nt" and not name.lower().endswith(".exe"):
        return f"{name}.exe"
    return name


def resolve_executable(name, configured_path=None, project_fallback=True):
    """Find a configured, PATH, or project-local executable."""
    candidates = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())

    path_match = shutil.which(executable_name(name)) or shutil.which(name)
    if path_match:
        candidates.append(Path(path_match))

    if project_fallback:
        if platform.system() == "Darwin":
            candidates.append(APP_ROOT / f"{name}-macos")
        else:
            candidates.append(APP_ROOT / executable_name(name))
        if os.name != "nt" and platform.system() != "Darwin":
            candidates.append(APP_ROOT / name)

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    searched = ", ".join(str(path) for path in candidates) or "system PATH"
    raise FileNotFoundError(
        f"{name} was not found. Install it for {sys.platform} or configure its path "
        f"(searched: {searched})."
    )


def display_command(command):
    """Format an argument list for diagnostics on the current platform."""
    if os.name == "nt":
        return subprocess.list2cmdline([str(part) for part in command])
    return shlex.join([str(part) for part in command])


def quote_argument(argument):
    """Quote one argument using the native command-line convention."""
    if os.name == "nt":
        return subprocess.list2cmdline([str(argument)])
    return shlex.quote(str(argument))


def split_command(command):
    """Split a command line according to the native platform convention."""
    if os.name != "nt":
        return shlex.split(command)
    argc = ctypes.c_int()
    parser = ctypes.windll.shell32.CommandLineToArgvW
    parser.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parser.restype = ctypes.POINTER(wintypes.LPWSTR)
    argv = parser(command, ctypes.byref(argc))
    if not argv:
        raise OSError("Could not parse Windows command line")
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def run_command(command, **kwargs):
    """Run a command without invoking a platform-specific shell."""
    return subprocess.run([str(part) for part in command], check=False, **kwargs)
