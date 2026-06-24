"""Exceptions raised by the ``exiftool`` package."""

from __future__ import annotations


class ExifToolNotFound(RuntimeError):
    """Raised when ExifTool cannot be found or is too old."""


class ExifToolError(RuntimeError):
    """Raised when an ExifTool invocation fails (non-zero exit or timeout)."""


class UnsupportedFileType(ValueError):
    """Raised when a file's extension isn't one we know how to write."""
