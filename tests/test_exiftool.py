import json
import subprocess
from datetime import datetime
from unittest import mock

import pytest

from merge_google_photos_meta.exiftool import (
    ExifToolError,
    UnsupportedFileType,
    read_metadata,
    read_metadata_batch,
    write_metadata,
    write_metadata_batch,
)


def _completed(stdout: str, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr
    )


def test_read_metadata_parses_single_file_object():
    payload = json.dumps(
        [{"SourceFile": "photo.jpg", "EXIF:DateTimeOriginal": "2024:01:02 03:04:05"}]
    )

    with mock.patch("subprocess.run", return_value=_completed(payload)) as run:
        meta = read_metadata("/usr/bin/exiftool", "photo.jpg")

    assert meta["EXIF:DateTimeOriginal"] == "2024:01:02 03:04:05"
    # Invoked with structured, group-prefixed output for exactly one file.
    args = run.call_args.args[0]
    assert args == ["/usr/bin/exiftool", "-json", "-G", "photo.jpg"]


def test_read_metadata_missing_tag_is_absent():
    payload = json.dumps([{"SourceFile": "photo.jpg"}])
    with mock.patch("subprocess.run", return_value=_completed(payload)):
        meta = read_metadata("/usr/bin/exiftool", "photo.jpg")

    assert "GPSLatitude" not in meta
    assert meta.get("GPSLatitude") is None


def test_read_metadata_raises_on_nonzero_exit():
    err = subprocess.CalledProcessError(
        returncode=1,
        cmd=["exiftool"],
        stderr="Error: File not found - missing.jpg\n",
    )
    with mock.patch("subprocess.run", side_effect=err):
        with pytest.raises(ExifToolError, match="File not found"):
            read_metadata("/usr/bin/exiftool", "missing.jpg")


def test_read_metadata_raises_on_timeout():
    with mock.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["exiftool"], timeout=30),
    ):
        with pytest.raises(ExifToolError, match="timed out"):
            read_metadata("/usr/bin/exiftool", "slow.jpg")


def test_write_metadata_builds_expected_args():
    with mock.patch("subprocess.run", return_value=_completed("")) as run:
        write_metadata(
            "/usr/bin/exiftool",
            "photo.jpg",
            {
                "date_taken": datetime(2024, 1, 2, 3, 4, 5),
                "latitude": 37.5,
                "longitude": -122.25,
                "altitude": -10.0,
                "description": "Beach day",
            },
        )

    args = run.call_args.args[0]
    assert args[0] == "/usr/bin/exiftool"
    assert args[-1] == "photo.jpg"
    assert "-AllDates=2024:01:02 03:04:05" in args
    # Hemisphere/altitude refs derived from sign; coordinates written as abs.
    assert "-GPSLatitude=37.5" in args
    assert "-GPSLatitudeRef=N" in args
    assert "-GPSLongitude=122.25" in args
    assert "-GPSLongitudeRef=W" in args
    assert "-GPSAltitude=10.0" in args
    assert "-GPSAltitudeRef=1" in args
    assert "-IPTC:Caption-Abstract=Beach day" in args
    assert "-XMP-dc:Description=Beach day" in args
    assert "-overwrite_original" in args


def test_write_metadata_only_writes_provided_fields():
    with mock.patch("subprocess.run", return_value=_completed("")) as run:
        write_metadata("/usr/bin/exiftool", "photo.jpg", {"description": "hi"})

    args = run.call_args.args[0]
    assert "-IPTC:Caption-Abstract=hi" in args
    assert not any(a.startswith("-GPSLatitude") for a in args)
    assert not any(a.startswith("-AllDates") for a in args)


def test_write_metadata_can_keep_original_backup():
    with mock.patch("subprocess.run", return_value=_completed("")) as run:
        write_metadata(
            "/usr/bin/exiftool",
            "photo.jpg",
            {"description": "hi"},
            overwrite_original=False,
        )

    assert "-overwrite_original" not in run.call_args.args[0]


def test_write_metadata_video_uses_quicktime_tags():
    with mock.patch("subprocess.run", return_value=_completed("")) as run:
        write_metadata(
            "/usr/bin/exiftool",
            "clip.mp4",
            {
                "date_taken": datetime(2024, 1, 2, 3, 4, 5),
                "latitude": 37.123456789,
                "longitude": -122.25,
                "altitude": 10.0,
                "description": "Beach day",
            },
        )

    args = run.call_args.args[0]
    assert args[-1] == "clip.mp4"
    # QuickTime date tags under QuickTimeUTC, with an explicit +00:00 offset so
    # Google displays them verbatim. Not EXIF/AllDates.
    assert "-api" in args and "QuickTimeUTC=1" in args
    assert "-QuickTime:CreateDate=2024:01:02 03:04:05+00:00" in args
    assert "-Keys:CreationDate=2024:01:02 03:04:05+00:00" in args
    assert not any(a.startswith("-AllDates") for a in args)
    # Single combined coordinate tag, signed, rounded to 5 decimals.
    assert "-Keys:GPSCoordinates=37.12346, -122.25000, 10.0" in args
    assert not any(a.startswith("-GPSLatitude") for a in args)
    assert "-Keys:Description=Beach day" in args


def test_write_metadata_video_needs_both_lat_and_lon():
    with mock.patch("subprocess.run", return_value=_completed("")) as run:
        write_metadata(
            "/usr/bin/exiftool",
            "clip.mov",
            {"date_taken": datetime(2024, 1, 2, 3, 4, 5), "latitude": 37.5},
        )

    # Lat alone can't form the combined tag; nothing GPS gets written.
    assert not any("GPSCoordinates" in a for a in run.call_args.args[0])


def test_write_metadata_rejects_unsupported_extension():
    with mock.patch("subprocess.run") as run:
        with pytest.raises(UnsupportedFileType, match="txt"):
            write_metadata("/usr/bin/exiftool", "notes.txt", {"description": "x"})
    run.assert_not_called()


def test_write_metadata_rejects_empty_update():
    with mock.patch("subprocess.run") as run:
        with pytest.raises(ValueError, match="No metadata fields"):
            write_metadata("/usr/bin/exiftool", "photo.jpg", {})
    run.assert_not_called()


def test_read_metadata_batch_keys_by_source_file():
    payload = json.dumps(
        [
            {"SourceFile": "a.jpg", "EXIF:DateTimeOriginal": "2024:01:02 03:04:05"},
            {"SourceFile": "b.jpg", "EXIF:DateTimeOriginal": "2020:06:07 08:09:10"},
        ]
    )
    with mock.patch("subprocess.run", return_value=_completed(payload)) as run:
        result = read_metadata_batch("/usr/bin/exiftool", ["a.jpg", "b.jpg"])

    run.assert_called_once()
    args = run.call_args.args[0]
    assert args[:3] == ["/usr/bin/exiftool", "-json", "-G"]
    assert result["a.jpg"]["EXIF:DateTimeOriginal"] == "2024:01:02 03:04:05"
    assert set(result) == {"a.jpg", "b.jpg"}


def test_read_metadata_batch_omits_unreadable_files():
    # ExifTool returns no JSON object for files it couldn't read.
    payload = json.dumps([{"SourceFile": "good.jpg", "File:FileName": "good.jpg"}])
    with mock.patch(
        "subprocess.run",
        return_value=_completed(payload, stderr="Error: File not found - bad.jpg\n"),
    ):
        result = read_metadata_batch("/usr/bin/exiftool", ["good.jpg", "bad.jpg"])

    assert "good.jpg" in result
    assert result.get("bad.jpg") is None


def test_read_metadata_batch_chunks_by_batch_size():
    def _per_chunk(cmd, **kwargs):
        paths = [a for a in cmd[3:]]  # after exiftool -json -G
        payload = json.dumps([{"SourceFile": p} for p in paths])
        return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")

    paths = [f"f{i}.jpg" for i in range(5)]
    with mock.patch("subprocess.run", side_effect=_per_chunk) as run:
        result = read_metadata_batch("/usr/bin/exiftool", paths, batch_size=2)

    assert run.call_count == 3  # 2, 2, 1
    assert set(result) == set(paths)


def _fake_batch_run(*, stderr: str = "", returncode: int = 0):
    """A subprocess.run replacement returning a canned result per chunk."""

    def _run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    return _run


def _chunk_args(call) -> list[str]:
    """The inline ExifTool args (minus the binary path) from a run() call."""
    return call.args[0][1:]


def test_write_metadata_batch_single_process_per_chunk():
    items = [
        ("a.jpg", {"description": "first"}),
        ("clip.mp4", {"date_taken": datetime(2024, 1, 2, 3, 4, 5)}),
    ]
    with mock.patch("subprocess.run", side_effect=_fake_batch_run()) as run:
        result = write_metadata_batch("/usr/bin/exiftool", items)

    # Both files fit one chunk -> one ExifTool invocation, args passed inline.
    run.assert_called_once()
    args = _chunk_args(run.call_args)
    assert "-IPTC:Caption-Abstract=first" in args
    assert "a.jpg" in args and "clip.mp4" in args
    assert "-QuickTime:CreateDate=2024:01:02 03:04:05+00:00" in args
    assert args.count("-execute") == 2
    assert result.updated == ["a.jpg", "clip.mp4"]
    assert result.failed == []


def test_write_metadata_batch_chunks_by_batch_size():
    items = [(f"f{i}.jpg", {"description": str(i)}) for i in range(5)]
    with mock.patch("subprocess.run", side_effect=_fake_batch_run()) as run:
        result = write_metadata_batch("/usr/bin/exiftool", items, batch_size=2)

    # 5 files at batch_size 2 -> chunks of 2, 2, 1.
    assert run.call_count == 3
    assert [_chunk_args(c).count("-execute") for c in run.call_args_list] == [2, 2, 1]
    assert result.updated == [f"f{i}.jpg" for i in range(5)]


def test_write_metadata_batch_collects_prevalidation_failures():
    items = [
        ("good.jpg", {"description": "ok"}),
        ("notes.txt", {"description": "x"}),  # unsupported type
        ("empty.jpg", {}),  # no fields
    ]
    with mock.patch("subprocess.run", side_effect=_fake_batch_run()) as run:
        result = write_metadata_batch("/usr/bin/exiftool", items)

    assert result.updated == ["good.jpg"]
    assert {path for path, _ in result.failed} == {"notes.txt", "empty.jpg"}
    # Rejected files never reach ExifTool's args.
    assert "notes.txt" not in _chunk_args(run.call_args)


def test_write_metadata_batch_attributes_exiftool_errors():
    items = [("a.jpg", {"description": "x"}), ("b.jpg", {"description": "y"})]
    stderr = "Error: Writing of this type of file is not supported - b.jpg\n"
    with mock.patch(
        "subprocess.run", side_effect=_fake_batch_run(stderr=stderr, returncode=1)
    ):
        result = write_metadata_batch("/usr/bin/exiftool", items)

    assert result.updated == ["a.jpg"]
    assert result.failed == [("b.jpg", "Writing of this type of file is not supported")]


def test_write_metadata_batch_empty_does_not_run():
    with mock.patch("subprocess.run") as run:
        result = write_metadata_batch("/usr/bin/exiftool", [])
    run.assert_not_called()
    assert result.updated == [] and result.failed == []


def test_write_metadata_batch_rejects_bad_batch_size():
    with mock.patch("subprocess.run") as run:
        with pytest.raises(ValueError, match="batch_size"):
            write_metadata_batch(
                "/usr/bin/exiftool", [("a.jpg", {"description": "x"})], batch_size=101
            )
    run.assert_not_called()
