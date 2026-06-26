# Pranav's Plan

Now that we have the core functionality of reading and writing metadata, lets focus on all the other stuff around this functionality. Here is how I want this program to work:

**Guiding principle:** correctness over speed. This tool mutates irreplaceable
photos, so every step defaults to the safe choice, and we **fill gaps — we never
clobber good metadata**. The detailed rules come from
[`docs/TAKEOUT_CORRECTNESS.md`](docs/TAKEOUT_CORRECTNESS.md); read it before
touching the writer. Section references below (§N) point into that doc.

Here are the steps it should take:

1. Prompt the user a few things:
    1. Should the source folder be copied (so that the original photos are untouched)? - The default should be yes
        1. If the source folder is going to be copied, what folder should it be copied to? - The default should be something like "merge-google-photos-meta-output/<original-folder-name>"
        1. If the source folder isn't going to be copied, ask a second confirmation i.e. "are you sure? the original files will be modified"
    2. For the files without a metadata file, should the program attempt to extract the original date / date taken from the file name?
    - Also support a `--dry-run` flag that runs steps 2–8 and prints the report
      (step 8) without writing anything. This is how we trust the tool before
      pointing it at a real library.
2. Gather all the file paths from the source directory
    - Walk recursively; stream entries (paths are tiny, no memory concern).
    - **Keep the SQLite cache DB outside the media tree** (see Data model) so this
      walk doesn't pick up its own database file.
3. Filter out all the files that are not media files or metadata files
    - Media = extension in `SUPPORTED_EXTENSIONS` (reuse the set from
      `exiftool/metadata.py` so the filter and the writer never disagree).
    - Metadata = `*.json` sidecars.
4. Batch read all the media file's metadata (using read_metadata_batch) (and I mean ALL of them) and store the results in sqlite cache
    - Cache keyed by `path` + `(mtime, size)` for invalidation (see Data model);
      a cached row whose stat still matches is a hit, so re-runs skip re-reading.
    - We only need a few fields per file to decide (existing `DateTimeOriginal`,
      whether GPS is present), so project down rather than storing the whole tag
      dump — keeps the cache small even at 100k+ files.
5. Batch read all the metadata files (the json files) and store the results in sqlite cache
    - Extract `photoTakenTime.timestamp` (UTC epoch), `geoData` (lat/lon/alt),
      `description`, and `title` (the original upload filename — useful for
      pairing). Map into `PhotoMetadata`.
    - **GPS `0,0` is Google's "no location" sentinel (§4)** — treat both-zero as
      absent, or everything geotags to the Gulf of Guinea.
    - Prefer `geoData` (user/Google-resolved); fall back to `geoDataExif`.
6. Read all the file path's of the media and json files, and Pair the metadata files with their corresponding media files

    **This is the actually-hard part (§2).** Naive `media.jpg → media.jpg.json`
    matching fails on a large fraction of real exports. **Build a normalized index
    of the JSON stems per folder and match media against it by prefix — do not
    compute the expected JSON name from the media name.** Cases to handle:

    | Case | Example | Handling |
    |---|---|---|
    | Two naming schemes | `IMG.jpg.json` vs `IMG.jpg.supplemental-metadata.json` (often truncated) | Match by **prefix**, not exact string |
    | 51-char truncation | `long_name.jpg` → `long_na.json` (each side truncated independently) | Undo by prefix-matching against actual JSON stems in the folder |
    | Moving `(n)` counter | `IMG(1).jpg` ↔ `IMG.jpg(1).json` (counter after the ext on the JSON) | Strip `(n)` from both sides before matching |
    | `-edited` derivatives | `IMG-edited.jpg` shares `IMG`'s JSON, has no sidecar of its own | Strip `-edited` (and truncated `-edi`/`-`) before matching |
    | `title` fallback | JSON `title` = original upload name | Heuristic secondary key when stem-match fails; **not** ground truth |
    | Live Photos | `IMG.HEIC` + `IMG.MOV`, same stem, one JSON | Decide whether to keep paired (Open decision) |

7. Go through each pairing and figure out whether the media file's metadata will need to be updated.

    **Cardinal rule: fill gaps, don't clobber (§1).** The camera's existing
    `DateTimeOriginal` is correct *local* time; Google's `photoTakenTime` is a UTC
    epoch that's often *less* accurate. Classify each file into the buckets your
    tree report (step 8) already shows, using this three-case logic (to live in a
    new `compare_metadata.py` — it's referenced by the doc but doesn't exist yet):

    - **date missing in file, present in JSON** → fill it (a file *to update*).
    - **date differs by < 24h** → EXIF-local vs JSON-UTC → leave it (timezone
      mismatch, *nothing to update*).
    - **date differs by > 24h** → real conflict → report, don't auto-write.

    Same gap-fill principle for GPS: don't overwrite coordinates the file already
    has. **Date source priority is: embedded EXIF (keep) > JSON `photoTakenTime` >
    filename-parsed date.** Filename parsing (step 1.2) is a **last resort**, used
    only when the JSON has no date *and* the file has no embedded date — and those
    updates are flagged separately since the parsed date is a guess.

    > ⚠️ **Current code does the wrong thing here.** `cli.py` writes metadata
    > unconditionally and `write_metadata_batch` has no notion of "only the gaps."
    > This step (reading existing tags first, comparing, writing only gaps) is
    > net-new work.

8. Show and output something like this:
33,446 media files found
├── 20,573 with no metadata file (61.5%)
├── 2,300 paired with metadata file that has no relevant information (5%) # Metadata file was empty or did not have date_taken, gps location, etc properties
|   └── 5,000 media files where the file name can be parsed into a taken_at date
|        └── 500 date taken matches metadata (nothing to update) (5.8%)
|        └── 500 date taken differs by less than 24h (likely timezone mismatch) (nothing to update) (5.8%)
|        └── 50 media files to update metadata (5%)
└── 12,873 paired with a metadata file (38.5%)
    ├── 747 fully match (nothing to update) (5.8%)
    ├── 500 fully match except taken_at time differs by less than 24h (likely timezone mismatch) (nothing to update) (5.8%)
    └── 12,126 files to update metadata (94.2%)


9. Final prompt user to update the 12,126 metadata files
    - also somehow prompt them to confirm to update metadata of files with date extracted from file name

10. Update metadata, show progress
    - Use the existing `write_metadata_batch` (chunked `-execute`, returns
      `BatchResult`). Drive the progress bar and final tally off it + the cache
      `status` column, so a crash mid-run resumes instead of restarting.
    - **Photos vs videos are different systems (§3) — and the writer needs work:**
        - **Photos:** `EXIF:DateTimeOriginal`. **Decided (#2): write the UTC value
          as-is, no timezone derivation** — accept that displayed times will be
          off by the local UTC offset. (No `timezonefinder` dependency.)
          For EXIF-less formats (PNG): `XMP:DateCreated` → `XMP:DateTimeOriginal`.
          *(Current `_image_write_args` writes the datetime as-is via `-AllDates`,
          which matches this decision but still has no XMP path for PNG.)*
        - **Videos:** `-api QuickTimeUTC=1` + `QuickTime:CreateDate` +
          `Keys:CreationDate`, writing the true UTC instant with a **`+00:00`
          offset** (no derivation, per #2). **Proven by round-trip test (#1) and
          implemented in `_video_write_args`.** (The old naive-local "Approach A"
          made Google convert the value to the viewer's account timezone and show
          the wrong time — replaced.)
    - **Safety (§5):** never re-encode (exiftool only, pixels byte-identical);
      keep batching to amortize startup; preserve `FileModifyDate` (`-P`).
    - **Verify (§6):** after writing, read back a sample
      (`exiftool -G1 -a -time:all -gps:all file.jpg`) and confirm the value
      landed. Before a full-library run, upload **one** file to Google Photos and
      confirm the displayed date.

---

## Data model — SQLite cache / state store

Not just a memory trick (projecting to needed fields would handle memory) — its
real value is **resumability and idempotency**: reading a big library is slow and
writes are destructive + partial-failure-prone, so we persist progress.

- **Location:** output folder root or a `.cache/` dir — **outside** the media tree
  (step 2 walks that tree).
- **One row per media file**, keyed by `path` + invalidation tuple `(mtime, size)`
  from `os.stat` (no hashing). Re-stat on lookup; mismatch = miss = re-read. This
  self-heals: after a write the file's mtime changes, so a later run re-reads it
  rather than trusting stale data.
- **Projected columns, not a JSON blob:** the fields we compare, plus `status`
  (`pending`/`written`/`skipped`/`conflict`/`failed`) + `error` text. The status
  column is what makes step 10 resumable and drives the step 8 report.
- **Perf:** `PRAGMA journal_mode=WAL`; insert each read-chunk in one transaction
  (per-row autocommit fsyncs every row — minutes vs seconds at 100k files).

---

## Module layout

- `exiftool/metadata.py` — exists (read/write batch, `PhotoMetadata`, `BatchResult`).
- `cli.py` — replace the hardcoded scaffold with the prompt + pipeline driver.
- `discovery.py` *(new)* — walk + classify (steps 2–3).
- `pairing.py` *(new)* — normalized-index sidecar matching (step 6).
- `sidecar.py` *(new)* — parse Google JSON → `PhotoMetadata` (step 5).
- `filename_date.py` *(new)* — parse a taken-at date from filenames (step 1.2 / 7).
- `compare_metadata.py` *(new)* — gap-fill precedence logic (step 7).
- `cache.py` *(new)* — SQLite state store.

---

## Decisions

1. **Video timezone — DECIDED via round-trip test: use Approach B.** Uploaded the
   same intended capture time written two ways to Google Photos:
   - **Approach A** (naive local, no `QuickTimeUTC`) → Google showed the **wrong**
     time: it treated the stored value as UTC and converted it to the *account's*
     timezone (intended 3:09 PM → displayed 9:09 AM GMT-06:00). Viewer-dependent.
   - **Approach B** (`-api QuickTimeUTC=1` + `QuickTime:CreateDate` +
     `Keys:CreationDate` with explicit offset) → Google showed the **correct**
     3:09 PM. The explicit offset in `Keys:CreationDate` is what made it work.
   - **Resolution (consistent with #2):** adopt Approach B, but since we have no
     offset source, write the true UTC instant with a `+00:00` offset. Same
     "off-by-local-offset" tradeoff as photos, but *predictable* (not
     viewer-dependent). Adding GPS→tz later just swaps `+00:00` for the real
     offset and both photos and videos become exactly correct.
   - ✅ Confirmed: a third upload with `+00:00` displayed `3:09 PM GMT+00:00`.
     **`_video_write_args` now implements this** (`-api QuickTimeUTC=1` +
     `QuickTime:CreateDate` + `Keys:CreationDate`, both `+00:00`); tests updated.
2. **Photo timezone — DECIDED: no derivation.** Write the UTC value as-is; no
   `timezonefinder`. Accept that displayed times are off by the local UTC offset.
   Reflected in step 10.
3. **Live Photos — DECIDED: group them.** A sidecar-less media file that shares a
   stem with a media file that *has* a sidecar **inherits that JSON**. This is what
   gives Live Photo video halves (the `.MOV`, which usually has no sidecar) the
   correct date + GPS instead of dropping them into the no-metadata bucket.
   Implemented as one inheritance rule in `pairing.py`.
4. **Filename-date — DECIDED: last resort, multiple patterns.** Used only when the
   JSON has no date *and* the file has no embedded date (priority encoded in step
   7). Patterns to support, including a trailing `(1)` / `-1` disambiguation suffix
   on any of them:
   - `IMG_20230715_143000` (and `VID_…`, `PXL_…` variants)
   - `2015-06-26 05.20.33`
   - `Screenshot_…` timestamped variants
   - …each optionally followed by ` (1)`, `(1)`, or `-1` before the extension.
