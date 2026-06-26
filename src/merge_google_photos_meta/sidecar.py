"""Parse a Google Takeout JSON sidecar into our metadata model (step 5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .exiftool.metadata import PhotoMetadata


@dataclass
class Sidecar:
    """The Google-Photos-relevant fields pulled from a Takeout JSON.

    ``date_taken`` is the **naive UTC** wall-clock from ``photoTakenTime`` (the
    Takeout timestamp is a UTC epoch with no offset; see ``TAKEOUT_CORRECTNESS``
    §3). ``title`` is the original on-disk upload name, kept as a secondary
    pairing key. Any field Google didn't provide is ``None``.
    """

    date_taken: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    description: str | None = None
    title: str | None = None

    @property
    def has_useful_metadata(self) -> bool:
        """True if there's anything worth writing (a date or real coordinates)."""
        return self.date_taken is not None or (
            self.latitude is not None and self.longitude is not None
        )

    def to_photo_metadata(self) -> PhotoMetadata:
        """Project to a :class:`PhotoMetadata` containing only present fields."""
        meta: PhotoMetadata = {}
        if self.date_taken is not None:
            meta["date_taken"] = self.date_taken
        if self.latitude is not None and self.longitude is not None:
            meta["latitude"] = self.latitude
            meta["longitude"] = self.longitude
            if self.altitude is not None:
                meta["altitude"] = self.altitude
        if self.description:
            meta["description"] = self.description
        return meta


def _parse_timestamp(node: dict | None) -> datetime | None:
    """Return naive UTC datetime from a ``{"timestamp": "<epoch>"}`` node."""
    if not node:
        return None
    raw = node.get("timestamp")
    if raw is None:
        return None
    try:
        epoch = int(raw)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)


def _parse_geo(data: dict) -> tuple[float | None, float | None, float | None]:
    """Pull (lat, lon, alt), preferring ``geoData`` over ``geoDataExif``.

    Google writes ``0.0, 0.0`` to mean "no location" (§4), so both-zero is
    treated as absent rather than geotagging everything to the Gulf of Guinea.
    """
    for key in ("geoData", "geoDataExif"):
        geo = data.get(key)
        if not isinstance(geo, dict):
            continue
        lat = geo.get("latitude")
        lon = geo.get("longitude")
        if lat is None or lon is None:
            continue
        if lat == 0 and lon == 0:
            continue  # sentinel for "no location"
        alt = geo.get("altitude")
        return float(lat), float(lon), float(alt) if alt is not None else None
    return None, None, None


def parse_sidecar(path: str | Path) -> Sidecar:
    """Read and parse one Takeout JSON sidecar.

    Tolerant by design: a malformed or unexpected file yields an empty
    :class:`Sidecar` rather than raising, so one bad sidecar can't abort a run.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Sidecar()
    if not isinstance(data, dict):
        return Sidecar()

    lat, lon, alt = _parse_geo(data)
    description = data.get("description")
    return Sidecar(
        date_taken=_parse_timestamp(data.get("photoTakenTime")),
        latitude=lat,
        longitude=lon,
        altitude=alt,
        description=description.strip() if isinstance(description, str) and description.strip() else None,
        title=data.get("title") or None,
    )
