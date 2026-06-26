# Building a Google Photos Takeout Organizer — Correctness Guide

A checklist for implementing a Takeout metadata organizer **correctly**, organized
by where these tools actually go wrong. Audit your implementation against each
section.

Background on which tags Google Photos reads is in
[`docs/ARCHITECTURE.md`](ARCHITECTURE.md) (§4–5 and §9). This document is about
*doing the processing right*, not about MetaSort specifically.

> Note: Google publishes **no official spec** for how Google Photos parses
> metadata. Everything here comes from community reverse-engineering (chiefly
> StarGeek's `Metadata_Reference`) and the behavior of mature tools. Verify with a
> round-trip test (§6) before trusting any pipeline on a full library.

---

## 1. Cardinal rule: fill gaps, don't clobber good metadata

The single most common mistake is unconditionally writing the JSON-derived date
into every file. The camera already wrote the **correct local**
`DateTimeOriginal`; Google's `photoTakenTime` is a **UTC epoch** that's often
*less* accurate. Logic should be:

```
if EXIF:DateTimeOriginal exists and is valid  → leave it alone
else                                          → write from JSON
```

The right mental model (encoded in this repo's `compare_metadata.py`) separates
three cases:

- `date_exif_missing` — JSON has a date, EXIF doesn't → **fill it**.
- `date_tz` — EXIF and JSON differ by < 24h → almost always EXIF-is-correct-local
  vs JSON-is-UTC → **leave it alone**.
- `date_big_diff` — differ by > 24h → real disagreement → **investigate**, don't
  auto-overwrite.

Only the first category should trigger a write.

---

## 2. Sidecar pairing — this is the actually-hard part

Naive `media.jpg` → `media.jpg.json` matching fails on a large fraction of real
exports. Rules you must handle:

- **Two naming schemes, sometimes in the same export:** old `IMG_1234.jpg.json`
  and new (late-2024) `IMG_1234.jpg.supplemental-metadata.json`. The supplemental
  part is itself often truncated (`…supplemental-met.json`, etc.). **Match by
  prefix, not exact string.**
- **51-char truncation:** Google truncates `basename` to `51 − len(ext)`
  characters. The media file and its JSON are truncated **independently**, so they
  can end up with different stems.
- **Disambiguation counters move:** duplicates get `(1)`, but the counter is
  placed differently on each side — `IMG_1234(1).jpg` pairs with
  `IMG_1234.jpg(1).json` (counter *after* the extension on the JSON). This breaks
  `with_extension`-style matching.
- **`-edited` files share the original's JSON** and have no sidecar of their own.
  The suffix can also be truncated (`-edi`, `-`) or dropped entirely.
- **The JSON's `title` field** holds the *original* upload filename — useful as a
  secondary key when stem-matching fails, but it won't match the truncated on-disk
  name either, so it's a heuristic, not ground truth.
- **Live Photos:** `.HEIC`/`.JPG` + paired `.MP4`/`.MOV` with the same stem —
  decide whether to keep them together.

**Practical approach:** build a normalized index (strip `-edited`, strip `(n)`,
undo truncation by prefix-matching against actual JSON stems in the same folder)
rather than computing the expected JSON name from the media name.

**Measured against a real 33k-file export (2026):** deriving each JSON's *target
media name* (undo the supplemental suffix + trailing counter) and matching it to
the files in the same folder paired **99.7%** of media. Concrete observations:

- The supplemental suffix truncates to *many* lengths in one export, all prefixes
  of the full word: `.supplemental-metadata` → `.supplemental-met` →
  `.supplement` → `.suppl` → `.s`. Strip any non-empty dotted segment that is a
  prefix of `supplemental-metadata`; a real extension (`jpg`, `heic`) isn't one,
  so it survives.
- The duplicate counter sits at the **very end** of the JSON name, after the
  (possibly truncated) suffix: `PXL_…621(1).jpg` ↔
  `PXL_…621.jpg.supplemental-metada(1).json`.
- Derivative copies almost never carry their own sidecar (in this export: 80
  `-edited` media, 1 `-edited` JSON). They must **inherit** the original's JSON.
  Suffixes seen: `-edited`, `-EFFECTS` (repeatable), `_Bokeh`, `~2`, `-ANIMATION`,
  and combinations.
- **Pixel Live Photos** appear as a still + a separate `.MP` (an MP4 motion clip)
  sharing a stem; the `.MP` half has no sidecar and inherits the still's by stem.
- **Exclude album/account JSONs** (`metadata.json`, `shared_album_comments.json`,
  `user-generated-memory-titles.json`, …) — they aren't per-media sidecars.
- The stubborn residue (~0.3%) is Google-generated derivatives with mangled names
  (`.MOTION-02.ORIGINAL`, `.LONG_EXPOSURE-01.COVER`, `_exported_…`). Prefer
  leaving these **unpaired** (they recover a date from their `PXL_<timestamp>`
  filename) over risking a mis-pair — under-pairing beats writing a wrong date.

---

## 3. Dates — photos vs. videos are different systems

**Photos:** write `EXIF:DateTimeOriginal` (the highest-priority tag Google reads).
EXIF has no timezone and Google displays it literally, so the value should be
**local wall-clock time at capture**, not UTC. Since Takeout only gives you a UTC
epoch, getting local requires the original offset. Best available source: derive
the timezone from the JSON's **GPS coordinates** (lat/lon → tz via a
timezone-boundary lookup) when present; otherwise you're guessing, and writing UTC
is a defensible fallback — just know it'll be off by the offset.

For formats historically without EXIF (PNG, etc.), `XMP:DateCreated` and
`XMP:DateTimeOriginal` are read. **Note (round-trip tested, 2026):** modern PNGs
carry an `eXIf` chunk, and Google *does* read `EXIF:DateTimeOriginal` from it —
writing PNG dates via `-AllDates` works. Only the native `PNG:CreationTime` tEXt
chunk is ignored by Google.

**Videos:** EXIF tags don't apply. Write `QuickTime:CreateDate` and
`Keys:CreationDate` under `-api QuickTimeUTC=1`:

```bash
exiftool -api QuickTimeUTC=1 \
  -QuickTime:CreateDate="2023:07:15 14:30:00-05:00" \
  -Keys:CreationDate="2023:07:15 14:30:00-05:00" \
  -overwrite_original video.mp4
```

**Round-trip tested against Google Photos (2026) — this matters more than it
looks:**

- Writing a **naive local** value with no offset (and no `QuickTimeUTC`) is
  *wrong*. Google reads the QuickTime date as UTC and then **converts it to the
  viewing account's timezone**, so an intended 3:09 PM displayed as 9:09 AM
  (GMT-06:00). The displayed time is therefore *viewer-dependent*, not just
  shifted by a constant.
- Writing with an **explicit offset** in `Keys:CreationDate` (as above) is
  honored verbatim — Google displayed the intended 3:09 PM.
- When you have **no offset source** (the Takeout timestamp is a bare UTC epoch),
  write the true UTC instant with a `+00:00` offset. Tested: Google displays the
  UTC wall-clock at GMT+00:00 — off by the real local offset, but *predictable*
  and not viewer-dependent. Swap `+00:00` for a real offset (e.g. GPS-derived)
  later and the displayed time becomes exactly correct, no other change.

Google Photos imports only **date and GPS** from video metadata — nothing else.

---

## 4. GPS — two traps

- **The `0,0` sentinel:** Google writes `latitude: 0.0, longitude: 0.0` to mean
  "no location." Embedding that blindly geotags everything to the Gulf of Guinea.
  **Skip when both are 0.**
- **`geoData` vs `geoDataExif`:** prefer `geoData` (user/Google-resolved), fall
  back to `geoDataExif` (original camera). Don't overwrite GPS if the file already
  has real coordinates — same gap-fill principle as dates.

---

## 5. File safety

- **Never re-encode.** Use exiftool's `-overwrite_original_in_place` (or work on
  copies with `-overwrite_original`); don't pass image data through any
  decode/encode step. Pixels must be byte-identical.
- **Batch your exiftool calls.** One process per file is brutally slow on large
  libraries — exiftool's `-@ argfile` or `-stay_open` mode is the difference
  between minutes and hours for 50k+ files.
- **Preserve `FileModifyDate`** (`-P`) if you care about it, since it's Google's
  last-resort date fallback.

---

## 6. Close the loop (verification)

After writing, read the tag back and confirm the exact tag/value landed:

```bash
exiftool -G1 -a -time:all -gps:all file.jpg
```

Then upload **one** file to Google Photos and verify the displayed date before
trusting the pipeline on your whole library — Google's behavior shifts, and a
round-trip test is the only real proof.

---

## Sources

- [exiftool forum — Takeout `.json` naming change & filename truncation](https://exiftool.org/forum/index.php?topic=17536.0)
- [Metadata Fixer — Google Takeout JSON files explained](https://metadatafixer.com/learn/google-takeout-json-files-explained)
- [exiftool forum — parentheses placement in JSON names](https://exiftool.org/forum/index.php?topic=12882.0)
- [StarGeek — Metadata_Reference / Photos.google.com.md](https://github.com/StarGeekSpaceNerd/Metadata_Reference/blob/master/Photos.google.com.md)
- [GooglePhotosTakeoutHelper #353 — supplemental-metadata suffix](https://github.com/TheLastGimbus/GooglePhotosTakeoutHelper/issues/353)
- [Google Photos Community — Which EXIF dates does Google Photos use?](https://support.google.com/photos/thread/110841/which-exif-dates-does-google-photos-use-to-organise-images?hl=en)
