"""Interface to Phil Harvey's ExifTool: binary discovery and metadata I/O.

The package is split into focused modules (``binary``, ``process``,
``metadata``, ``errors``), but the public API is re-exported here so callers
import from ``merge_google_photos_meta.exiftool`` directly.
"""

from __future__ import annotations

from .binary import MIN_VERSION, resolve_exiftool
from .errors import ExifToolError, ExifToolNotFound, UnsupportedFileType
from .metadata import (
    IMAGE_EXTENSIONS,
    MAX_BATCH_SIZE,
    SUPPORTED_EXTENSIONS,
    VIDEO_EXTENSIONS,
    BatchResult,
    PhotoMetadata,
    read_metadata,
    write_metadata,
    write_metadata_batch,
)

__all__ = [
    "IMAGE_EXTENSIONS",
    "MAX_BATCH_SIZE",
    "MIN_VERSION",
    "SUPPORTED_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "BatchResult",
    "ExifToolError",
    "ExifToolNotFound",
    "PhotoMetadata",
    "UnsupportedFileType",
    "read_metadata",
    "resolve_exiftool",
    "write_metadata",
    "write_metadata_batch",
]
