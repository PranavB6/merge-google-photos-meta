"""Locate and validate the external ExifTool binary.

This package shells out to Phil Harvey's ExifTool (https://exiftool.org), which
is a separate, OS-level dependency rather than a Python package. We detect it at
runtime instead of bundling or downloading it: the OS package manager owns the
binary, its updates, and its security.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess

from .errors import ExifToolNotFound

# Minimum ExifTool version we rely on. Recent versions handle Google Takeout
# sidecars and date writing more reliably; bump this as we depend on newer flags.
MIN_VERSION = (12, 0)


def _install_hint() -> str:
    hints = {
        "Darwin": "  brew install exiftool",
        "Linux": (
            "  sudo apt install libimage-exiftool-perl   # Debian/Ubuntu\n"
            "  sudo dnf install perl-Image-ExifTool       # Fedora/RHEL"
        ),
        "Windows": (
            "  winget install OliverBetz.ExifTool\n"
            "  # or: scoop install exiftool   /   choco install exiftool"
        ),
    }
    cmd = hints.get(platform.system(), "  see https://exiftool.org/install.html")
    return (
        "ExifTool is required but was not found on your PATH.\n\n"
        f"Install it with:\n{cmd}\n\n"
        "Or set EXIFTOOL_PATH to point at an existing binary."
    )


def _query_version(path: str) -> tuple[int, ...] | None:
    """Return ExifTool's version as a tuple, or None if it can't be parsed."""
    try:
        out = subprocess.run(
            [path, "-ver"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    try:
        return tuple(int(part) for part in out.split("."))
    except ValueError:
        return None


def resolve_exiftool() -> str:
    """Return the path to a usable ExifTool binary.

    Resolution order:
      1. The EXIFTOOL_PATH environment variable, if it points at a real binary.
      2. ``exiftool`` on PATH (``.exe`` resolution on Windows is automatic).

    Raises:
        ExifToolNotFound: if no binary is found or it is older than MIN_VERSION.
    """
    override = os.environ.get("EXIFTOOL_PATH")
    path = shutil.which(override) if override else None
    if path is None:
        path = shutil.which("exiftool")
    if path is None:
        raise ExifToolNotFound(_install_hint())

    version = _query_version(path)
    if version is not None and version < MIN_VERSION:
        have = ".".join(map(str, version))
        need = ".".join(map(str, MIN_VERSION))
        raise ExifToolNotFound(
            f"Found ExifTool {have} at {path}, but version {need} or newer is "
            f"required.\n\n{_install_hint()}"
        )

    return path
