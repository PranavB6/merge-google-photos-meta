"""Takeout JSON sidecar parsing (step 5)."""

import json
from datetime import datetime

from merge_google_photos_meta.sidecar import parse_sidecar


def _write(tmp_path, data: dict):
    p = tmp_path / "x.jpg.supplemental-metadata.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_photo_taken_time_is_naive_utc(tmp_path):
    # 1724034202 == 2024-08-19 02:23:22 UTC.
    s = parse_sidecar(_write(tmp_path, {"photoTakenTime": {"timestamp": "1724034202"}}))
    assert s.date_taken == datetime(2024, 8, 19, 2, 23, 22)


def test_zero_zero_geo_is_treated_as_absent(tmp_path):
    s = parse_sidecar(
        _write(tmp_path, {"geoData": {"latitude": 0.0, "longitude": 0.0}})
    )
    assert s.latitude is None and s.longitude is None


def test_geodata_preferred_then_geodataexif(tmp_path):
    s = parse_sidecar(
        _write(
            tmp_path,
            {
                "geoData": {"latitude": 0.0, "longitude": 0.0},  # sentinel -> skip
                "geoDataExif": {"latitude": 37.5, "longitude": -122.0, "altitude": 9.0},
            },
        )
    )
    assert (s.latitude, s.longitude, s.altitude) == (37.5, -122.0, 9.0)


def test_empty_description_becomes_none(tmp_path):
    s = parse_sidecar(_write(tmp_path, {"description": "   "}))
    assert s.description is None


def test_to_photo_metadata_only_present_fields(tmp_path):
    s = parse_sidecar(
        _write(
            tmp_path,
            {
                "photoTakenTime": {"timestamp": "1724034202"},
                "geoData": {"latitude": 1.0, "longitude": 2.0},
                "description": "hi",
            },
        )
    )
    meta = s.to_photo_metadata()
    assert meta["date_taken"] == datetime(2024, 8, 19, 2, 23, 22)
    assert meta["latitude"] == 1.0 and meta["longitude"] == 2.0
    assert meta["description"] == "hi"
    assert "altitude" not in meta


def test_has_useful_metadata(tmp_path):
    empty = parse_sidecar(_write(tmp_path, {"title": "x.jpg", "description": ""}))
    assert not empty.has_useful_metadata
    dated = parse_sidecar(_write(tmp_path, {"photoTakenTime": {"timestamp": "1"}}))
    assert dated.has_useful_metadata


def test_malformed_json_yields_empty_sidecar(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    s = parse_sidecar(p)
    assert s.date_taken is None and s.latitude is None
