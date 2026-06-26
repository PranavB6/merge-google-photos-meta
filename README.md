# merge-google-photos-meta (`mgpm`)

> **`mgpm`** is just shorthand for **m**erge-**g**oogle-**p**hotos-**m**eta — the
> two commands are identical, so use whichever you prefer.

A correctness-first CLI that repairs media metadata in a **Google Photos Takeout**
export. It reads each photo/video's embedded metadata, pairs it with its Takeout
`.json` sidecar, and **fills in missing dates, GPS, and descriptions — without ever
overwriting good metadata that's already there.**

```bash
$ mgpm ~/Takeout/Google\ Photos --dry-run
```

## Why this exists

Google Takeout hands back your library with the capture date, location, and
caption split out into per-file `.json` sidecars instead of embedded in the
photos. Re-import those files anywhere and the dates are wrong. The naive fix —
blindly writing the JSON date into every file — is actively harmful: the camera's
embedded `DateTimeOriginal` is the correct *local* time, while Google's
`photoTakenTime` is a UTC epoch that's often *less* accurate.

This tool follows one guiding principle: **correctness over speed.** It mutates
irreplaceable photos, so every step defaults to the safe choice and it **fills
gaps, never clobbers good metadata.** The detailed rules (which tags Google
Photos actually reads, how sidecar pairing really works, how video dates differ
from photo dates) live in [`docs/TAKEOUT_CORRECTNESS.md`](docs/TAKEOUT_CORRECTNESS.md).

## Requirements

- Python 3.10+
- [**ExifTool**](https://exiftool.org) on your `PATH` (or pointed at by
  `$EXIFTOOL_PATH`). This is an OS-level dependency, not a Python package:

  ```bash
  brew install exiftool                          # macOS
  sudo apt install libimage-exiftool-perl        # Debian/Ubuntu
  winget install OliverBetz.ExifTool             # Windows
  ```

## Install

```bash
pipx install merge-google-photos-meta     # recommended: isolated, on your PATH
# or
pip install merge-google-photos-meta
```

[pipx](https://pipx.pypa.io) is recommended for command-line tools — it installs
the package into its own isolated environment and puts the commands on your
`PATH` without touching your global Python.

Either way you get two equivalent commands: `merge-google-photos-meta` and the
short alias `mgpm`.

### Install from source

```bash
git clone https://github.com/PranavB6/merge-google-photos-meta.git
cd merge-google-photos-meta
pip install .
```

## Usage

```bash
mgpm <takeout_dir> --dry-run        # analyze + print the report, write nothing
mgpm <takeout_dir>                  # full run (interactive prompts)
```

Always start with `--dry-run`. It runs the entire analysis and prints a report,
but writes nothing — this is how you trust the tool before pointing it at a real
library.

A full run prompts you for two things:

1. **Copy the source first?** (default: **yes**) — operates on a copy so your
   originals are never touched. If you say no, it asks again to confirm before
   modifying originals in place.
2. **Parse dates from filenames** for files with no embedded date *and* no
   sidecar? (default: **no**) — a last-resort guess (`IMG_20230715_143000` →
   that date), confirmed separately before anything is written.

### Options

| Flag | Effect |
| --- | --- |
| `--dry-run` | Analyze and report only; write nothing. |
| `--copy` / `--no-copy` | Copy the source first (skip the prompt). |
| `-o, --output <dir>` | Where to copy (default: `output-merge-google-photos-meta/<name>`). |
| `--filename-dates` / `--no-filename-dates` | Use filename-derived dates (skip the prompt). |
| `-y, --yes` | Skip the final write confirmation. |

### What the report tells you

Every media file lands in one outcome:

- **to update** — has a gap (no embedded date / GPS / description) that a sidecar
  or filename can fill. The only category that gets written.
- **already complete** — has a trusted embedded date; nothing to do.
- **date differs < 24h** — almost always embedded-local-time vs JSON-UTC; left
  alone.
- **date differs > 24h** — a real disagreement; flagged for you to review, never
  auto-overwritten.
- **no date available** — nothing anywhere to write; skipped.

## How it works

A linear pipeline (see [`pranav-plan.md`](pranav-plan.md) for the full spec):

1. **Discover & classify** every file into media, sidecars, and ignored.
2. **Pair** each media file with its Takeout JSON. This is the hard part —
   Google's sidecar naming has two schemes, independent 51-char truncation,
   moving duplicate counters, and derivative files (`-edited`, Live Photo
   `.MOV`/`.MP`) that share an original's sidecar. Measured at **99.7%** pairing
   on a real 33k-file export (`docs §2`).
3. **Read** existing embedded metadata (batched ExifTool calls, cached in SQLite).
4. **Decide** per file: fill only what's missing, keeping any trusted embedded
   value (`docs §1`).
5. **Report**, confirm, then **write** — resumably (a crash mid-run is picked up
   where it left off).

Photos and videos go through different tag systems: images get EXIF/IPTC/XMP
tags; videos get QuickTime tags with an explicit UTC offset that Google Photos
honors verbatim — both round-trip-tested against Google Photos (`docs §3`).

## Development

Set up an editable install with the dev dependencies in a virtualenv:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # or: make install
```

Editable mode (`-e`) means your edits take effect immediately — no reinstall
needed.

| Command | What it does |
| --- | --- |
| `make install` | Install the package + dev dependencies (editable). |
| `make test` | Run the test suite with `pytest`. |
| `make build` | Clean, test, build the wheel/sdist, and check them. |
| `make clean` | Remove `dist/` and build artifacts. |

```bash
make test
pytest tests/test_pairing.py                       # one file
pytest tests/test_pairing.py::test_moving_counter  # one test
```

The test suite mocks out the ExifTool subprocess, so it runs without the binary
installed and asserts on the exact arguments passed. The pairing and
date-comparison tests map directly to the edge cases catalogued in
`docs/TAKEOUT_CORRECTNESS.md`.
