"""Filename date parsing (last-resort, step 1.2/7)."""

from datetime import datetime

import pytest

from merge_google_photos_meta.filename_date import parse_filename_date


@pytest.mark.parametrize(
    "name,expected",
    [
        ("IMG_20230715_143000.jpg", datetime(2023, 7, 15, 14, 30, 0)),
        ("VID_20230715_143000.mp4", datetime(2023, 7, 15, 14, 30, 0)),
        ("PXL_20230715_143000123.jpg", datetime(2023, 7, 15, 14, 30, 0)),  # millis tail
        ("2015-06-26 05.20.33.png", datetime(2015, 6, 26, 5, 20, 33)),
        ("Screenshot_2015-06-26-05-20-33.png", datetime(2015, 6, 26, 5, 20, 33)),
        # disambiguation suffixes must not break extraction
        ("IMG_20230715_143000(1).jpg", datetime(2023, 7, 15, 14, 30, 0)),
        ("IMG_20230715_143000-edited.jpg", datetime(2023, 7, 15, 14, 30, 0)),
        ("2015-06-26 05.20.33~2.png", datetime(2015, 6, 26, 5, 20, 33)),
    ],
)
def test_parses_known_patterns(name, expected):
    assert parse_filename_date(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "vacation.jpg",
        "DSC_0001.jpg",
        "IMG_20231345_143000.jpg",  # month 13 -> invalid
        "12345678_123456.jpg",  # year 1234 out of range
    ],
)
def test_no_match_returns_none(name):
    assert parse_filename_date(name) is None
