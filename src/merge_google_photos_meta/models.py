"""Shared data types passed between the pipeline stages.

Kept in one place so :mod:`discovery`, :mod:`pairing`, :mod:`compare_metadata`,
:mod:`cache`, and :mod:`cli` agree on the vocabulary without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .exiftool.metadata import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    PhotoMetadata,
)


class FileKind(str, Enum):
    """Whether a media file is a still image or a QuickTime-container video.

    The two go through different metadata tag systems (see
    ``docs/TAKEOUT_CORRECTNESS.md`` §3), so we tag every media file up front.
    """

    IMAGE = "image"
    VIDEO = "video"

    @classmethod
    def of(cls, path: str | Path) -> "FileKind":
        ext = Path(path).suffix.lower()
        if ext in VIDEO_EXTENSIONS:
            return cls.VIDEO
        if ext in IMAGE_EXTENSIONS:
            return cls.IMAGE
        raise ValueError(f"Not a supported media extension: {path}")


class DateSource(str, Enum):
    """Where a date we intend to write came from, in priority order.

    Embedded EXIF always wins and is never overwritten, so it never appears as a
    *source to write* — only ``JSON`` and ``FILENAME`` do. ``FILENAME`` is a
    last-resort guess and is surfaced separately to the user.
    """

    JSON = "json"
    FILENAME = "filename"
    NONE = "none"


class Category(str, Enum):
    """Top-level pairing bucket for a media file (drives the report tree)."""

    NO_SIDECAR = "no_sidecar"
    SIDECAR_EMPTY = "sidecar_empty"  # paired, but JSON had nothing useful
    PAIRED = "paired"  # paired with a JSON that has a date and/or GPS


class Outcome(str, Enum):
    """What we decided to do with a media file (drives the report + writing)."""

    UPDATE = "update"  # has gaps to fill -> will be written
    MATCH = "match"  # already has everything -> nothing to do
    TZ_MISMATCH = "tz_mismatch"  # date differs < 24h (EXIF-local vs JSON-UTC)
    CONFLICT = "conflict"  # date differs > 24h -> report, don't auto-write
    NO_DATA = "no_data"  # nothing available anywhere to write


@dataclass(frozen=True)
class MediaFile:
    """A discovered media file and its kind."""

    path: str
    kind: FileKind


@dataclass
class Decision:
    """The verdict for one media file after pairing + comparison.

    ``to_write`` holds only the gap-fill fields we will actually write (empty
    when :attr:`outcome` is not :attr:`Outcome.UPDATE`). ``date_source`` records
    where a written date came from so the CLI can ask for separate confirmation
    on filename-derived guesses.
    """

    media_path: str
    kind: FileKind
    sidecar_path: str | None
    category: Category
    outcome: Outcome
    to_write: PhotoMetadata = field(default_factory=lambda: PhotoMetadata())
    date_source: DateSource = DateSource.NONE

    @property
    def needs_update(self) -> bool:
        return self.outcome is Outcome.UPDATE and bool(self.to_write)
