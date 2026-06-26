"""Pairing edge cases from docs/TAKEOUT_CORRECTNESS.md §2."""

from merge_google_photos_meta.models import FileKind, MediaFile
from merge_google_photos_meta.pairing import pair


def _media(*names: str, folder: str = "/album") -> list[MediaFile]:
    return [MediaFile(f"{folder}/{n}", FileKind.of(n)) for n in names]


def _sidecars(*names: str, folder: str = "/album") -> list[str]:
    return [f"{folder}/{n}" for n in names]


def test_exact_match_old_scheme():
    res = pair(_media("IMG_1234.jpg"), _sidecars("IMG_1234.jpg.json"))
    assert res.pairs["/album/IMG_1234.jpg"] == "/album/IMG_1234.jpg.json"


def test_supplemental_metadata_full_and_truncated():
    media = _media("a.jpg", "b.jpg", "c.jpg")
    sidecars = _sidecars(
        "a.jpg.supplemental-metadata.json",  # full
        "b.jpg.suppl.json",  # truncated
        "c.jpg.s.json",  # truncated to one char
    )
    res = pair(media, sidecars)
    assert res.pairs["/album/a.jpg"] == "/album/a.jpg.supplemental-metadata.json"
    assert res.pairs["/album/b.jpg"] == "/album/b.jpg.suppl.json"
    assert res.pairs["/album/c.jpg"] == "/album/c.jpg.s.json"


def test_moving_counter():
    # IMG(1).jpg pairs with IMG.jpg(1).json (counter moves past the extension).
    media = _media("PXL_1.jpg", "PXL_1(1).jpg")
    sidecars = _sidecars(
        "PXL_1.jpg.supplemental-metada.json",
        "PXL_1.jpg.supplemental-metada(1).json",
    )
    res = pair(media, sidecars)
    assert res.pairs["/album/PXL_1.jpg"] == "/album/PXL_1.jpg.supplemental-metada.json"
    assert res.pairs["/album/PXL_1(1).jpg"] == "/album/PXL_1.jpg.supplemental-metada(1).json"


def test_edited_inherits_originals_sidecar():
    media = _media("IMG_1.jpg", "IMG_1-edited.jpg", "IMG_1-EFFECTS-edited.jpg")
    sidecars = _sidecars("IMG_1.jpg.supplemental-metadata.json")
    res = pair(media, sidecars)
    sc = "/album/IMG_1.jpg.supplemental-metadata.json"
    assert res.pairs["/album/IMG_1-edited.jpg"] == sc
    assert res.pairs["/album/IMG_1-EFFECTS-edited.jpg"] == sc


def test_live_photo_video_half_inherits_still_sidecar():
    # The .MOV half of a Live Photo carries no sidecar; it inherits the still's.
    media = _media("IMG_9.HEIC", "IMG_9.MOV")
    sidecars = _sidecars("IMG_9.HEIC.supplemental-metadata.json")
    res = pair(media, sidecars)
    assert res.pairs["/album/IMG_9.MOV"] == "/album/IMG_9.HEIC.supplemental-metadata.json"


def test_media_without_sidecar_and_orphan_sidecar():
    res = pair(_media("lonely.jpg"), _sidecars("ghost.jpg.json"))
    assert res.pairs["/album/lonely.jpg"] is None
    assert res.orphan_sidecars == ["/album/ghost.jpg.json"]


def test_pairing_is_per_directory():
    media = _media("IMG.jpg", folder="/a") + _media("IMG.jpg", folder="/b")
    sidecars = _sidecars("IMG.jpg.json", folder="/a")
    res = pair(media, sidecars)
    assert res.pairs["/a/IMG.jpg"] == "/a/IMG.jpg.json"
    assert res.pairs["/b/IMG.jpg"] is None  # different album, no cross-match
