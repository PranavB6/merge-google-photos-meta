"""Discovery classification (steps 2-3) and the SQLite cache (Data model)."""

from datetime import datetime

from merge_google_photos_meta.cache import Cache
from merge_google_photos_meta.compare_metadata import ExistingMeta
from merge_google_photos_meta.discovery import classify, gather_files
from merge_google_photos_meta.models import FileKind


def test_classify_splits_media_sidecar_ignored(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"")
    (tmp_path / "b.mp4").write_bytes(b"")
    (tmp_path / "a.jpg.supplemental-metadata.json").write_text("{}")
    (tmp_path / "metadata.json").write_text("{}")  # album-level, not a sidecar
    (tmp_path / "notes.txt").write_bytes(b"")
    (tmp_path / "a.jpg:Zone.Identifier").write_bytes(b"")  # WSL stream -> ignored

    media, sidecars, ignored = classify(gather_files(tmp_path))

    assert {m.path.rsplit("/", 1)[-1] for m in media} == {"a.jpg", "b.mp4"}
    assert any(m.kind is FileKind.VIDEO for m in media)
    assert [s.name for s in sidecars] == ["a.jpg.supplemental-metadata.json"]
    assert {p.name for p in ignored} >= {"metadata.json", "notes.txt"}


def test_cache_round_trip_and_stat_invalidation(tmp_path):
    db = tmp_path / "c.sqlite"
    meta = ExistingMeta(date_taken=datetime(2020, 1, 1, 0, 0, 0), has_gps=True)
    with Cache(db) as cache:
        cache.put_existing_batch([("/a/x.jpg", 111.0, 222, meta)])

        hit = cache.get_existing("/a/x.jpg", 111.0, 222)
        assert hit is not None and hit.date_taken == datetime(2020, 1, 1, 0, 0, 0)
        assert hit.has_gps is True

        # changed stat -> miss (file was modified since we read it)
        assert cache.get_existing("/a/x.jpg", 999.0, 222) is None


def test_cache_status_marking(tmp_path):
    db = tmp_path / "c.sqlite"
    with Cache(db) as cache:
        cache.put_existing_batch([("/a/x.jpg", 1.0, 2, ExistingMeta())])
        assert cache.get_status("/a/x.jpg") == "pending"
        cache.mark("/a/x.jpg", "written")
        assert cache.get_status("/a/x.jpg") == "written"
