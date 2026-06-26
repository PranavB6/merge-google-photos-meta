"""Walk a source directory and classify its files (pipeline steps 2-3)."""

from __future__ import annotations

import os
from pathlib import Path

from .exiftool.metadata import SUPPORTED_EXTENSIONS
from .models import FileKind, MediaFile

# Per-album / account-level JSON files Takeout drops alongside the photos. They
# are not per-media sidecars, so we never try to pair them.
NON_SIDECAR_JSON_NAMES = frozenset(
    {
        "metadata.json",
        "print-subscriptions.json",
        "shared_album_comments.json",
        "user-generated-memory-titles.json",
    }
)


def gather_files(source_dir: str | Path):
    """Yield every regular file under ``source_dir``, recursively.

    Streams with ``os.scandir`` (via ``Path.rglob`` would also work) so we never
    hold the whole tree in memory — though paths are tiny, this keeps discovery
    constant-memory regardless of library size.
    """
    for root, _dirs, files in os.walk(source_dir):
        for name in files:
            yield Path(root) / name


def classify(
    paths,
) -> tuple[list[MediaFile], list[Path], list[Path]]:
    """Split discovered paths into ``(media, sidecars, ignored)``.

    - **media**: extension in :data:`SUPPORTED_EXTENSIONS` (shared with the
      writer so the filter and writer can never disagree).
    - **sidecars**: ``*.json`` files that aren't album/account-level metadata.
    - **ignored**: everything else (including Takeout's ``metadata.json`` and
      WSL ``*:Zone.Identifier`` streams, whose extension isn't recognized).
    """
    media: list[MediaFile] = []
    sidecars: list[Path] = []
    ignored: list[Path] = []

    for path in paths:
        ext = path.suffix.lower()
        if ext in SUPPORTED_EXTENSIONS:
            media.append(MediaFile(str(path), FileKind.of(path)))
        elif ext == ".json" and path.name.lower() not in NON_SIDECAR_JSON_NAMES:
            sidecars.append(path)
        else:
            ignored.append(path)

    return media, sidecars, ignored
