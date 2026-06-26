# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Typer CLI (`merge-google-photos-meta`, alias `mgpm`) that repairs media metadata in a Google Photos Takeout export: it reads each photo/video's embedded metadata, pairs it with its Takeout `.json` sidecar, and **fills missing dates / GPS / descriptions without ever overwriting good existing metadata**. It shells out to Phil Harvey's [ExifTool](https://exiftool.org) (an OS-level dependency, not a Python package) to do the actual reads and writes.

> Note: `README.md` is stale — it still describes an old "pranavpy" greeting tool and does not reflect this codebase. Don't trust it; use this file and the docs below.

## Read before touching the writer or pairing logic

- **`docs/TAKEOUT_CORRECTNESS.md`** — the source of truth for *why* the code behaves the way it does. Every non-obvious decision (which tags Google reads, the fill-don't-clobber rule, sidecar pairing edge cases, video date offsets) is justified there and cited from code/tests as `§N`. Read the relevant section before changing pairing, date comparison, or ExifTool write args.
- **`pranav-plan.md`** — the 10-step pipeline spec the CLI implements, plus the SQLite data model.

## Commands

```bash
make install        # pip install -e ".[dev]"  (needs a venv; requires exiftool on PATH)
make test           # pytest
pytest tests/test_pairing.py                       # one test file
pytest tests/test_pairing.py::test_moving_counter  # one test
make build          # clean + test + python -m build + twine check
```

Run the tool:

```bash
mgpm <takeout_dir> --dry-run        # analyze + print the report, write nothing
mgpm <takeout_dir>                  # full run (prompts: copy first? filename dates?)
mgpm <takeout_dir> --no-copy -y     # skip prompts/confirmation (mutates originals!)
```

ExifTool must be on `PATH` (or pointed to by `$EXIFTOOL_PATH`); `preflight()` aborts otherwise. Tests that exercise real reads/writes are skipped when it's absent.

## Architecture — the pipeline

`cli.py:main` orchestrates a linear pipeline; each stage is its own module and they communicate only through the dataclasses/enums in `models.py` (so modules don't import each other):

1. **`discovery.py`** — `gather_files` walks the tree; `classify` splits paths into media (extension in `SUPPORTED_EXTENSIONS`), sidecars (`*.json` minus album/account-level files like `metadata.json`), and ignored.
2. **`pairing.py`** — the genuinely hard part (`docs §2`). Per-directory, 3-pass matching: exact → prefix/truncation → inheritance. Instead of deriving the JSON name from the media name, it derives each JSON's **target media name** (`_json_target`: strip `.json`, the trailing `(n)` counter, and any prefix-of-`supplemental-metadata` segment) and matches that against real files. `-edited` derivatives and Live Photo `.MOV`/`.MP` halves carry no sidecar and **inherit** a sibling's via `_normalized_stem`.
3. **`exiftool/metadata.py:read_metadata_batch`** — reads existing tags, batched (one ExifTool process per chunk) to amortize startup.
4. **`compare_metadata.py:build_decision`** — the **fill-gaps-never-clobber** core (`docs §1`). Date priority: embedded EXIF/QuickTime (keep, never write) > JSON > filename. Produces an `Outcome`: `UPDATE` / `MATCH` / `TZ_MISMATCH` (EXIF-local vs JSON-UTC, <24h, left alone) / `CONFLICT` (>24h, left alone for review) / `NO_DATA`.
5. **`exiftool/metadata.py:write_metadata_batch`** — writes only `to_write` gap-fill fields, batched with `-execute`, per-file failures collected rather than aborting.

`sidecar.py` parses one Takeout JSON (tolerant: bad file → empty `Sidecar`, never raises); `filename_date.py` is the last-resort date guesser; `cache.py` is the SQLite store.

### Key invariants (don't break these)

- **`SUPPORTED_EXTENSIONS` (`exiftool/metadata.py`) is the single source of truth** for what counts as media — discovery filters and the writer dispatch both use it, so they can never disagree.
- **Photos vs. videos are different metadata systems** (`docs §3`). Images: `-AllDates` (EXIF) + GPS + IPTC/XMP description, written as naive local time. Videos: `QuickTime:CreateDate` + `Keys:CreationDate` under `-api QuickTimeUTC=1` with an **explicit offset** (the Takeout epoch has none, so `+00:00`), plus a single combined `Keys:GPSCoordinates`. The offset detail was round-trip-tested against Google Photos — see the long comment in `_video_write_args` before changing it.
- **GPS `0,0` is Google's "no location" sentinel** — `sidecar.py:_parse_geo` drops it (prefers `geoData` over `geoDataExif`). Never geotag from `0,0`.
- **The SQLite cache DB lives *outside* the media tree** (`cli.py:_cache_db_path`) so discovery doesn't ingest its own database.

### The cache (`cache.py`) does two jobs in one table

- **Read cache** keyed by `path` + `(mtime, size)` — skips re-running ExifTool on unchanged files. Self-invalidates after a write (mtime changes).
- **Write state** (`status` column) makes the write phase **resumable**: a crash leaves already-written files marked `written`, so a re-run skips them by path.

## Conventions

- `src/` layout, Python 3.10+, `from __future__ import annotations` everywhere. Modules carry rich docstrings explaining *why* (often citing `docs/TAKEOUT_CORRECTNESS.md §N`) — match that density and keep the citations accurate when you change behavior.
- Tests in `tests/` are plain pytest functions, organized by module, and pairing/comparison tests explicitly map to `docs §` cases. When you touch pairing or date logic, add the new edge case as a test and cite the doc section.
- PR titles and commits use `<type>(<scope>): <imperative summary>` (Conventional Commits).
