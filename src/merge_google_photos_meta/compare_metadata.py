"""Decide what (if anything) to write to a media file (pipeline step 7).

Encodes the cardinal rule from ``docs/TAKEOUT_CORRECTNESS.md`` §1: **fill gaps,
never clobber good metadata.** Embedded EXIF/QuickTime dates are trusted local
time and left alone; the JSON date is only written when the file has none.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .models import (
    Category,
    DateSource,
    Decision,
    FileKind,
    MediaFile,
    Outcome,
)
from .exiftool.metadata import PhotoMetadata
from .sidecar import Sidecar

# A date differing by more than this is a real disagreement (investigate), not
# the EXIF-local-vs-JSON-UTC timezone artifact we tolerate (§1).
TZ_THRESHOLD = timedelta(hours=24)

# Existing-date tag preference per kind, highest first. We only need to know
# whether *any* trusted date is present (and its value, to compare).
_IMAGE_DATE_TAGS = (
    "EXIF:DateTimeOriginal",
    "XMP:DateCreated",
    "XMP:DateTimeOriginal",
    "EXIF:CreateDate",
)
_VIDEO_DATE_TAGS = ("QuickTime:CreateDate", "Keys:CreationDate")

# Presence of any of these means the file already has coordinates / a caption.
_GPS_TAGS = (
    "EXIF:GPSLatitude",
    "Composite:GPSLatitude",
    "Composite:GPSPosition",
    "QuickTime:GPSCoordinates",
    "Keys:GPSCoordinates",
)
_DESCRIPTION_TAGS = (
    "IPTC:Caption-Abstract",
    "XMP:Description",
    "EXIF:ImageDescription",
    "Keys:Description",
    "QuickTime:Description",
)


@dataclass
class ExistingMeta:
    """The narrow projection of a media file's current metadata we care about."""

    date_taken: datetime | None = None
    has_gps: bool = False
    has_description: bool = False


def _parse_exif_datetime(value: object) -> datetime | None:
    """Parse an ExifTool date string (``YYYY:MM:DD HH:MM:SS[.sub][±offset]``).

    Returns naive local time (we drop any offset — comparison is a coarse
    <24h heuristic). The all-zero placeholder some cameras write is rejected.
    """
    if not isinstance(value, str) or len(value) < 19:
        return None
    head = value[:19]
    if head.startswith("0000"):
        return None
    try:
        return datetime.strptime(head, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def extract_existing(tags: dict | None, kind: FileKind) -> ExistingMeta:
    """Project a ``read_metadata`` tag dict down to :class:`ExistingMeta`.

    A missing/unreadable file (``tags`` is ``None`` or empty) yields an all-empty
    result, so it's treated as having gaps everywhere.
    """
    if not tags:
        return ExistingMeta()

    date_tags = _VIDEO_DATE_TAGS if kind is FileKind.VIDEO else _IMAGE_DATE_TAGS
    date_taken = None
    for tag in date_tags:
        date_taken = _parse_exif_datetime(tags.get(tag))
        if date_taken is not None:
            break

    return ExistingMeta(
        date_taken=date_taken,
        has_gps=any(tags.get(t) for t in _GPS_TAGS),
        has_description=any(tags.get(t) for t in _DESCRIPTION_TAGS),
    )


def _category(sidecar_path: str | None, sidecar: Sidecar | None) -> Category:
    if sidecar_path is None or sidecar is None:
        return Category.NO_SIDECAR
    if not sidecar.has_useful_metadata:
        return Category.SIDECAR_EMPTY
    return Category.PAIRED


def build_decision(
    media: MediaFile,
    sidecar_path: str | None,
    sidecar: Sidecar | None,
    existing: ExistingMeta,
    filename_date: datetime | None,
) -> Decision:
    """Combine existing metadata, the sidecar, and a filename date into a verdict.

    Date priority is embedded (keep) > JSON > filename. Existing coordinates and
    captions are never overwritten. The returned :attr:`Decision.to_write` holds
    only the gap-fill fields, and is empty unless the outcome is
    :attr:`Outcome.UPDATE`.
    """
    sidecar_meta: PhotoMetadata = sidecar.to_photo_metadata() if sidecar else {}
    json_date = sidecar_meta.get("date_taken")

    to_write: PhotoMetadata = {}
    date_source = DateSource.NONE
    date_outcome = Outcome.NO_DATA  # the date dimension's verdict

    # --- date: fill only if the file has none (§1) ---
    if existing.date_taken is not None:
        if json_date is not None:
            diff = abs(existing.date_taken - json_date)
            if diff == timedelta(0):
                date_outcome = Outcome.MATCH
            elif diff <= TZ_THRESHOLD:
                date_outcome = Outcome.TZ_MISMATCH
            else:
                date_outcome = Outcome.CONFLICT
        else:
            date_outcome = Outcome.MATCH  # has a trusted date, nothing to compare
    elif json_date is not None:
        to_write["date_taken"] = json_date
        date_source = DateSource.JSON
    elif filename_date is not None:
        to_write["date_taken"] = filename_date
        date_source = DateSource.FILENAME

    # --- gps: fill only if the file has none ---
    if not existing.has_gps and "latitude" in sidecar_meta:
        to_write["latitude"] = sidecar_meta["latitude"]
        to_write["longitude"] = sidecar_meta["longitude"]
        if "altitude" in sidecar_meta:
            to_write["altitude"] = sidecar_meta["altitude"]

    # --- description: fill only if the file has none ---
    if not existing.has_description and "description" in sidecar_meta:
        to_write["description"] = sidecar_meta["description"]

    if to_write:
        outcome = Outcome.UPDATE
    elif date_outcome in (Outcome.CONFLICT, Outcome.TZ_MISMATCH, Outcome.MATCH):
        outcome = date_outcome
    else:
        outcome = Outcome.NO_DATA

    return Decision(
        media_path=media.path,
        kind=media.kind,
        sidecar_path=sidecar_path,
        category=_category(sidecar_path, sidecar),
        outcome=outcome,
        to_write=to_write,
        date_source=date_source,
    )
