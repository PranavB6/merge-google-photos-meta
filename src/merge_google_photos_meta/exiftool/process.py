"""Run the ExifTool binary, translating failures into ``ExifToolError``."""

from __future__ import annotations

import subprocess

from .errors import ExifToolError


def run(
    exiftool_path: str,
    args: list[str],
    *,
    action: str,
    target: str,
    check: bool = True,
    timeout: float | None = 30,
) -> subprocess.CompletedProcess[str]:
    """Run ExifTool, translating failures into ``ExifToolError``.

    ``action``/``target`` only shape the error message (e.g. "read"/"write"
    and the file involved). Recoverable problems are reported by ExifTool on
    stderr while it still exits 0, so a returned result may carry warnings.

    Args:
        check: If True (default), a non-zero exit raises ``ExifToolError``. Pass
            False for batch runs, where individual-file errors are expected and
            inspected via the returned result instead of aborting everything.
        timeout: Seconds to wait, or None to wait indefinitely (use for large
            batches in a single process).
    """
    try:
        return subprocess.run(
            [exiftool_path, *args],
            capture_output=True,
            text=True,
            check=check,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as err:
        detail = err.stderr.strip() or f"ExifTool exited with status {err.returncode}"
        raise ExifToolError(f"Failed to {action} {target}: {detail}") from err
    except subprocess.TimeoutExpired as err:
        raise ExifToolError(f"ExifTool timed out trying to {action} {target}") from err
