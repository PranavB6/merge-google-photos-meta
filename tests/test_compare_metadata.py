"""Gap-fill comparison logic (step 7, docs/TAKEOUT_CORRECTNESS.md §1)."""

from datetime import datetime

from merge_google_photos_meta.compare_metadata import (
    ExistingMeta,
    build_decision,
    extract_existing,
)
from merge_google_photos_meta.models import DateSource, FileKind, MediaFile, Outcome
from merge_google_photos_meta.sidecar import Sidecar

IMG = MediaFile("/a/p.jpg", FileKind.IMAGE)
VID = MediaFile("/a/v.mp4", FileKind.VIDEO)


def _decide(existing, sidecar=None, filename_date=None, media=IMG, sidecar_path="/a/p.json"):
    return build_decision(
        media,
        sidecar_path if sidecar else None,
        sidecar,
        existing,
        filename_date,
    )


def test_extract_existing_image_date_and_gps():
    tags = {
        "EXIF:DateTimeOriginal": "2020:01:02 03:04:05",
        "EXIF:GPSLatitude": "37.0",
    }
    em = extract_existing(tags, FileKind.IMAGE)
    assert em.date_taken == datetime(2020, 1, 2, 3, 4, 5)
    assert em.has_gps is True


def test_extract_existing_video_uses_quicktime_tags():
    em = extract_existing({"QuickTime:CreateDate": "2020:01:02 03:04:05"}, FileKind.VIDEO)
    assert em.date_taken == datetime(2020, 1, 2, 3, 4, 5)


def test_extract_existing_rejects_zero_placeholder():
    em = extract_existing({"EXIF:DateTimeOriginal": "0000:00:00 00:00:00"}, FileKind.IMAGE)
    assert em.date_taken is None


def test_missing_date_filled_from_json():
    sc = Sidecar(date_taken=datetime(2021, 5, 5, 5, 5, 5))
    d = _decide(ExistingMeta(), sc)
    assert d.outcome is Outcome.UPDATE
    assert d.to_write["date_taken"] == datetime(2021, 5, 5, 5, 5, 5)
    assert d.date_source is DateSource.JSON


def test_existing_date_close_is_tz_mismatch_left_alone():
    existing = ExistingMeta(date_taken=datetime(2021, 5, 5, 0, 0, 0))
    sc = Sidecar(date_taken=datetime(2021, 5, 5, 6, 0, 0))  # 6h -> < 24h
    d = _decide(existing, sc)
    assert d.outcome is Outcome.TZ_MISMATCH
    assert "date_taken" not in d.to_write


def test_existing_date_far_is_conflict_left_alone():
    existing = ExistingMeta(date_taken=datetime(2021, 5, 5, 0, 0, 0))
    sc = Sidecar(date_taken=datetime(2021, 6, 5, 0, 0, 0))  # ~month -> conflict
    d = _decide(existing, sc)
    assert d.outcome is Outcome.CONFLICT
    assert "date_taken" not in d.to_write


def test_filename_only_when_no_json_or_existing_date():
    d = _decide(ExistingMeta(), sidecar=None, sidecar_path=None,
                filename_date=datetime(2019, 9, 9, 9, 9, 9))
    assert d.date_source is DateSource.FILENAME
    assert d.to_write["date_taken"] == datetime(2019, 9, 9, 9, 9, 9)


def test_json_date_beats_filename_date():
    sc = Sidecar(date_taken=datetime(2021, 1, 1, 0, 0, 0))
    d = _decide(ExistingMeta(), sc, filename_date=datetime(1999, 1, 1))
    assert d.date_source is DateSource.JSON


def test_gps_filled_only_when_absent():
    sc = Sidecar(latitude=1.0, longitude=2.0)
    assert "latitude" in _decide(ExistingMeta(has_gps=False), sc).to_write
    assert "latitude" not in _decide(ExistingMeta(has_gps=True), sc).to_write


def test_nothing_available_is_no_data():
    d = _decide(ExistingMeta(), sidecar=None, sidecar_path=None)
    assert d.outcome is Outcome.NO_DATA
    assert not d.to_write
