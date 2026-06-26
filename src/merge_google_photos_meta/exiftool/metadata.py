"""Read and write Google Photos-relevant metadata via ExifTool."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypedDict

from .errors import UnsupportedFileType
from .process import run

# Still-image extensions we support, written via EXIF/IPTC/XMP.
IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".webp", ".tif", ".tiff"}
)

# Extensions stored in the QuickTime container, where metadata lives in the
# QuickTime tag group rather than EXIF/IPTC/XMP.
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".3gp", ".3g2"})

# Everything we know how to write metadata to.
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# ExifTool can process many files in one invocation, but the per-call arguments
# go on the command line, which the OS caps (~32 KB on Windows). Chunking keeps
# each call comfortably under that while still amortizing startup across files.
MAX_BATCH_SIZE = 100


class PhotoMetadata(TypedDict, total=False):
    """Google Photos-relevant metadata fields. All keys are optional; only the
    ones present are written.

    Attributes:
        date_taken: Capture time, written as naive local time; Google Photos
            does not read a timezone from the file.
        latitude/longitude: Decimal degrees. The hemisphere ref is derived from
            the sign.
        altitude: Meters; negative means below sea level.
        description: Caption/description text.
    """

    date_taken: datetime
    latitude: float
    longitude: float
    altitude: float
    description: str


def read_metadata(exiftool_path: str, image_path: str) -> dict:
    """Return all metadata tags for ``image_path`` as a dict.

    Tag names are ExifTool's, group-prefixed (``-G``), e.g.
    ``"EXIF:DateTimeOriginal"`` or ``"Composite:GPSPosition"``. Missing tags
    are simply absent from the dict, so prefer ``.get()`` over indexing.

    Args:
        exiftool_path: Path to the ExifTool binary, from ``resolve_exiftool``.
        image_path: The image (or any media file) to read.

    Raises:
        ExifToolError: if ExifTool exits non-zero (e.g. missing or unreadable
            file) or times out. The message carries ExifTool's own stderr.
    """
    result = run(
        exiftool_path, ["-json", "-G", image_path], action="read", target=image_path
    )
    # -json emits a list with one object per input file; we pass exactly one.
    return json.loads(result.stdout)[0]


def read_metadata_batch(
    exiftool_path: str,
    file_paths: list[str],
    *,
    batch_size: int = 50,
) -> dict[str, dict]:
    """Read metadata for many files, batching to amortize ExifTool startup.

    ``-json`` already returns one object per file, so each chunk is read in a
    single process by passing all its paths at once. The result maps each
    readable file's path (exactly the string you passed) to its tag dict. Files
    ExifTool can't read are simply absent, so ``result.get(path)`` is ``None``
    for them.

    Args:
        file_paths: Files to read.
        batch_size: Files per ExifTool invocation (1..``MAX_BATCH_SIZE``).

    Raises:
        ValueError: if ``batch_size`` is outside 1..``MAX_BATCH_SIZE``.
        ExifToolError: only for whole-chunk failures (e.g. a timeout);
            individual unreadable files are omitted, not raised.
    """
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")

    out: dict[str, dict] = {}
    for start in range(0, len(file_paths), batch_size):
        chunk = file_paths[start : start + batch_size]
        # check=False: unreadable files just won't appear in the JSON; we don't
        # want one missing file to abort the whole read.
        completed = run(
            exiftool_path,
            ["-json", "-G", *chunk],
            action="read",
            target=f"{len(chunk)} files",
            check=False,
        )
        if not completed.stdout.strip():
            continue
        for obj in json.loads(completed.stdout):
            # ExifTool sets SourceFile to the verbatim path argument, so it's
            # both our key and exactly the string the caller passed. A missing
            # one means malformed output, so let the KeyError surface.
            out[obj["SourceFile"]] = obj
    return out


def _image_write_args(metadata: PhotoMetadata) -> list[str]:
    """Tag assignments for still images (EXIF/IPTC/XMP)."""
    args: list[str] = []

    date_taken = metadata.get("date_taken")
    if date_taken is not None:
        # -AllDates sets EXIF DateTimeOriginal (Google's top date source) plus
        # CreateDate and ModifyDate so they all agree.
        args.append(f"-AllDates={date_taken.strftime('%Y:%m:%d %H:%M:%S')}")

    latitude = metadata.get("latitude")
    if latitude is not None:
        args.append(f"-GPSLatitude={abs(latitude)}")
        args.append(f"-GPSLatitudeRef={'N' if latitude >= 0 else 'S'}")

    longitude = metadata.get("longitude")
    if longitude is not None:
        args.append(f"-GPSLongitude={abs(longitude)}")
        args.append(f"-GPSLongitudeRef={'E' if longitude >= 0 else 'W'}")

    altitude = metadata.get("altitude")
    if altitude is not None:
        args.append(f"-GPSAltitude={abs(altitude)}")
        # ExifTool altitude ref: 0 = above sea level, 1 = below.
        args.append(f"-GPSAltitudeRef={'0' if altitude >= 0 else '1'}")

    description = metadata.get("description")
    if description is not None:
        args.append(f"-IPTC:Caption-Abstract={description}")
        args.append(f"-XMP-dc:Description={description}")

    return args


def _video_write_args(metadata: PhotoMetadata) -> list[str]:
    """Tag assignments for QuickTime-container video (MP4/MOV)."""
    args: list[str] = []

    date_taken = metadata.get("date_taken")
    if date_taken is not None:
        # Google reads QuickTime dates as UTC and converts them to the *viewer's*
        # account timezone, so a naive local value displays as the wrong time.
        # Instead we write the value with an explicit offset under
        # -api QuickTimeUTC=1, which Google honors verbatim (confirmed by a
        # round-trip test against Google Photos). The Takeout timestamp is a UTC
        # epoch with no offset, so we tag it +00:00; the displayed time is then
        # the UTC wall-clock, off by the real local offset until/unless we derive
        # one from GPS coordinates. CreateDate + Keys:CreationDate is the minimal
        # set Google reads.
        stamp = date_taken.strftime("%Y:%m:%d %H:%M:%S") + "+00:00"
        args += ["-api", "QuickTimeUTC=1"]
        args.append(f"-QuickTime:CreateDate={stamp}")
        args.append(f"-Keys:CreationDate={stamp}")

    # Video GPS is one combined Keys:GPSCoordinates tag, not separate lat/lon
    # with hemisphere refs. Google Photos ignores coordinates with more than 5
    # decimal places, so we round. Latitude and longitude must travel together.
    latitude = metadata.get("latitude")
    longitude = metadata.get("longitude")
    if latitude is not None and longitude is not None:
        coords = f"{latitude:.5f}, {longitude:.5f}"
        altitude = metadata.get("altitude")
        if altitude is not None:
            coords += f", {altitude}"
        args.append(f"-Keys:GPSCoordinates={coords}")

    description = metadata.get("description")
    if description is not None:
        args.append(f"-Keys:Description={description}")

    return args


def _write_args(
    file_path: str, metadata: PhotoMetadata, *, overwrite_original: bool
) -> list[str]:
    """Build the full ExifTool argument list (tag assignments + file) for one
    file, dispatching on its extension.

    Raises:
        UnsupportedFileType: if the extension isn't supported.
        ValueError: if no applicable fields are present in ``metadata``.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in VIDEO_EXTENSIONS:
        args = _video_write_args(metadata)
    elif ext in IMAGE_EXTENSIONS:
        args = _image_write_args(metadata)
    else:
        raise UnsupportedFileType(
            f"Unsupported file type {ext or '(none)'!r} for {file_path}"
        )

    if not args:
        raise ValueError(f"No metadata fields to write for {file_path}")

    if overwrite_original:
        args.append("-overwrite_original")
    args.append(file_path)
    return args


def write_metadata(
    exiftool_path: str,
    file_path: str,
    metadata: PhotoMetadata,
    *,
    overwrite_original: bool = True,
) -> None:
    """Write Google Photos-relevant metadata into ``file_path`` in place.

    Dispatches on file type. For still images (JPEG/HEIC) the highest-priority
    tags Google Photos reads are written: ``EXIF:DateTimeOriginal`` (via
    ``-AllDates``), the ``GPS:*`` group, and ``IPTC:Caption-Abstract`` +
    ``XMP-dc:Description``. For QuickTime video (extensions in
    :data:`VIDEO_EXTENSIONS`) the equivalent QuickTime tags are written under
    ``-api QuickTimeUTC=1``: ``QuickTime:CreateDate`` and ``Keys:CreationDate``
    (both with an explicit ``+00:00`` offset so Google displays them verbatim),
    ``Keys:GPSCoordinates`` (one combined, 5-decimal-rounded value), and
    ``Keys:Description``.

    Only the keys present in ``metadata`` are written; absent keys are left
    untouched. For video, latitude and longitude are written only when both are
    present, since they form a single tag.

    Args:
        file_path: The image or video to update.
        metadata: The fields to write. See :class:`PhotoMetadata`.
        overwrite_original: If True (default), edit in place without leaving an
            ExifTool ``*_original`` backup copy.

    Raises:
        UnsupportedFileType: if ``file_path``'s extension isn't supported.
        ValueError: if no applicable fields are present in ``metadata``.
        ExifToolError: if ExifTool exits non-zero or times out.
    """
    args = _write_args(file_path, metadata, overwrite_original=overwrite_original)
    run(exiftool_path, args, action="write", target=file_path)


@dataclass
class BatchResult:
    """Outcome of :func:`write_metadata_batch`.

    Attributes:
        updated: Paths ExifTool reported as successfully written.
        failed: ``(path, reason)`` pairs for files that couldn't be written,
            whether rejected before running (unsupported type, no fields) or
            reported as an error by ExifTool.
    """

    updated: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _parse_error_files(stderr: str) -> dict[str, str]:
    """Map file path -> error message from ExifTool stderr.

    ExifTool prints one ``Error: <message> - <file>`` line per failed file. The
    path is whatever we passed in, so it matches our batch keys verbatim.
    """
    errors: dict[str, str] = {}
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("Error:") and " - " in line:
            message, path = line[len("Error:") :].strip().rsplit(" - ", 1)
            errors[path] = message.strip()
    return errors


def _run_chunk(
    exiftool_path: str, chunk: list[tuple[str, list[str]]], result: BatchResult
) -> None:
    """Write one chunk in a single process and record outcomes into ``result``."""
    args: list[str] = []
    for _, file_args in chunk:
        args.extend(file_args)
        # -execute separates the per-file commands so each gets its own values.
        args.append("-execute")

    # check=False: a non-zero exit just means some file in the chunk errored; we
    # want the per-file detail from stderr rather than aborting the whole run.
    completed = run(
        exiftool_path,
        args,
        action="write",
        target=f"{len(chunk)} files",
        check=False,
    )

    errored = _parse_error_files(completed.stderr)
    for file_path, _ in chunk:
        if file_path in errored:
            result.failed.append((file_path, errored[file_path]))
        else:
            result.updated.append(file_path)


def write_metadata_batch(
    exiftool_path: str,
    items: list[tuple[str, PhotoMetadata]],
    *,
    overwrite_original: bool = True,
    batch_size: int = 50,
) -> BatchResult:
    """Write metadata to many files, batching to amortize ExifTool startup.

    ExifTool's startup cost dominates per-file writes, so files are grouped into
    chunks of ``batch_size`` and each chunk is written in a single process: the
    per-file tag assignments are passed inline, separated by ``-execute``.

    Processing continues past individual failures: files rejected up front
    (unsupported type, no fields) and files ExifTool reports errors for are
    collected in :attr:`BatchResult.failed`; everything else is in
    :attr:`BatchResult.updated`.

    Args:
        items: ``(file_path, metadata)`` pairs to write.
        overwrite_original: If True (default), edit in place without leaving an
            ExifTool ``*_original`` backup copy.
        batch_size: Files per ExifTool invocation (1..``MAX_BATCH_SIZE``). Larger
            means fewer process launches; capped to keep the command line under
            OS limits.

    Raises:
        ValueError: if ``batch_size`` is outside 1..``MAX_BATCH_SIZE``.
        ExifToolError: only for whole-chunk failures (e.g. a timeout); per-file
            errors are reported via the result, not raised.
    """
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")

    result = BatchResult()
    blocks: list[tuple[str, list[str]]] = []
    for file_path, metadata in items:
        try:
            args = _write_args(
                file_path, metadata, overwrite_original=overwrite_original
            )
        except (UnsupportedFileType, ValueError) as err:
            result.failed.append((file_path, str(err)))
            continue
        blocks.append((file_path, args))

    for start in range(0, len(blocks), batch_size):
        _run_chunk(exiftool_path, blocks[start : start + batch_size], result)

    return result
