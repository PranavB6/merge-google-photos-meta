"""Command-line entry point: prompt, discover, pair, decide, report, write.

Implements the pipeline in ``pranav-plan.md`` (steps 1-10). Correctness-first:
defaults to copying the source so originals are never touched, fills gaps but
never clobbers good metadata, and offers ``--dry-run`` to preview without
writing.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import typer

from .cache import Cache
from .compare_metadata import build_decision, extract_existing
from .discovery import classify, gather_files
from .exiftool import ExifToolNotFound, resolve_exiftool
from .exiftool.metadata import read_metadata_batch, write_metadata_batch
from .filename_date import parse_filename_date
from .models import Category, DateSource, Decision, Outcome
from .pairing import pair
from .sidecar import Sidecar, parse_sidecar

app = typer.Typer(add_completion=False)

# Files read/written per ExifTool invocation, and rows per progress tick.
READ_CHUNK = 200
WRITE_CHUNK = 50


@app.command()
def main(
    source_dir: str = typer.Argument(..., help="Path to the Google Photos directory"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Analyze and report only; write nothing."
    ),
    copy: bool | None = typer.Option(
        None, "--copy/--no-copy", help="Copy the source first (default: ask)."
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output folder when copying."
    ),
    filename_dates: bool | None = typer.Option(
        None,
        "--filename-dates/--no-filename-dates",
        help="Fall back to dates parsed from filenames (default: ask).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the final write confirmation."
    ),
) -> None:
    exiftool_path = preflight()

    work_dir = _resolve_work_dir(source_dir, dry_run, copy, output)
    use_filename = _resolve_filename_dates(filename_dates)

    db_path = _cache_db_path(source_dir, work_dir)
    typer.echo(f"Cache: {db_path}")

    with Cache(db_path) as cache:
        decisions = _analyze(exiftool_path, work_dir, cache, use_filename)
        _render_report(decisions)

        if dry_run:
            typer.secho("\nDry run — nothing written.", fg=typer.colors.YELLOW)
            return

        _write_phase(exiftool_path, decisions, cache, assume_yes=yes)


# --- step 1: prompts / options ---------------------------------------------
def _resolve_work_dir(
    source_dir: str, dry_run: bool, copy: bool | None, output: str | None
) -> str:
    """Decide where we operate, copying the source first unless told otherwise."""
    source = Path(source_dir)
    if not source.is_dir():
        typer.secho(f"Not a directory: {source}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if dry_run:  # never copy for a preview
        return str(source)

    should_copy = copy if copy is not None else typer.confirm(
        "Copy all files first (to protect the originals)?", default=True
    )
    if not should_copy:
        if copy is None:
            typer.confirm(
                "Are you sure? The original files will be modified.", abort=True
            )
        return str(source)

    dest = Path(output) if output else Path("output-merge-google-photos-meta") / source.name
    if output is None:
        dest = Path(
            typer.prompt("Output folder", default=str(dest))
        )
    typer.echo(f"Copying {source} -> {dest} ...")
    shutil.copytree(source, dest, dirs_exist_ok=True)
    return str(dest)


def _resolve_filename_dates(filename_dates: bool | None) -> bool:
    if filename_dates is not None:
        return filename_dates
    return typer.confirm(
        "For files without metadata, parse the date from the filename "
        "(last resort)?",
        default=False,
    )


def _cache_db_path(source_dir: str, work_dir: str) -> Path:
    """A cache DB kept OUTSIDE the media tree so discovery doesn't ingest it."""
    if work_dir != source_dir:  # copied: park it beside the output folder
        return Path(work_dir).parent / f".{Path(work_dir).name}.mgpm-cache.sqlite"
    base = Path(source_dir)
    return base.parent / f".{base.name}.mgpm-cache.sqlite"


# --- steps 2-7: analysis ----------------------------------------------------
def _analyze(
    exiftool_path: str, work_dir: str, cache: Cache, use_filename: bool
) -> list[Decision]:
    typer.echo("Scanning files...")
    media, sidecars, _ignored = classify(gather_files(work_dir))
    typer.echo(f"  {len(media)} media files, {len(sidecars)} metadata files")

    typer.echo("Pairing media with metadata...")
    pairing = pair(media, [str(s) for s in sidecars])

    typer.echo("Reading existing metadata (this can take a while)...")
    existing = _read_existing(exiftool_path, media, cache)

    sidecar_cache: dict[str, Sidecar] = {}
    decisions: list[Decision] = []
    for m in media:
        sidecar_path = pairing.pairs.get(m.path)
        sidecar = None
        if sidecar_path is not None:
            sidecar = sidecar_cache.get(sidecar_path)
            if sidecar is None:
                sidecar = parse_sidecar(sidecar_path)
                sidecar_cache[sidecar_path] = sidecar
        fname_date = parse_filename_date(m.path) if use_filename else None
        decisions.append(
            build_decision(m, sidecar_path, sidecar, existing[m.path], fname_date)
        )
    return decisions


def _read_existing(exiftool_path: str, media, cache: Cache) -> dict:
    """Read each file's existing metadata, using the cache to skip unchanged ones."""
    existing: dict = {}
    to_read = []
    for m in media:
        try:
            st = os.stat(m.path)
        except OSError:
            existing[m.path] = extract_existing(None, m.kind)
            continue
        cached = cache.get_existing(m.path, st.st_mtime, st.st_size)
        if cached is not None:
            existing[m.path] = cached
        else:
            to_read.append((m, st))

    if to_read:
        with typer.progressbar(length=len(to_read), label="  Reading") as bar:
            for start in range(0, len(to_read), READ_CHUNK):
                chunk = to_read[start : start + READ_CHUNK]
                tags = read_metadata_batch(exiftool_path, [m.path for m, _ in chunk])
                entries = []
                for m, st in chunk:
                    em = extract_existing(tags.get(m.path), m.kind)
                    existing[m.path] = em
                    entries.append((m.path, st.st_mtime, st.st_size, em))
                cache.put_existing_batch(entries)
                bar.update(len(chunk))
    return existing


# --- step 8: report ---------------------------------------------------------
def _render_report(decisions: list[Decision]) -> None:
    total = len(decisions)
    by_cat: dict[Category, list[Decision]] = {c: [] for c in Category}
    for d in decisions:
        by_cat[d.category].append(d)

    def line(indent: str, n: int, label: str) -> None:
        pct = f"{100 * n / total:.1f}%" if total else "0%"
        typer.echo(f"{indent}{n} {label} ({pct})")

    typer.echo("")
    typer.echo(f"{total} media files found")

    no_sidecar = by_cat[Category.NO_SIDECAR]
    line("├── ", len(no_sidecar), "with no metadata file")
    _outcome_breakdown(no_sidecar, "│   ")

    empty = by_cat[Category.SIDECAR_EMPTY]
    line("├── ", len(empty), "paired with metadata that has no usable info")
    _outcome_breakdown(empty, "│   ")

    paired = by_cat[Category.PAIRED]
    line("└── ", len(paired), "paired with usable metadata")
    _outcome_breakdown(paired, "    ")


def _outcome_breakdown(group: list[Decision], indent: str) -> None:
    if not group:
        return
    n = len(group)
    counts = {o: 0 for o in Outcome}
    fname_updates = 0
    for d in group:
        counts[d.outcome] += 1
        if d.outcome is Outcome.UPDATE and d.date_source is DateSource.FILENAME:
            fname_updates += 1

    def sub(num: int, label: str) -> None:
        if num:
            typer.echo(f"{indent}└── {num} {label} ({100 * num / n:.1f}%)")

    updates = counts[Outcome.UPDATE]
    sub(updates, "to update" + (f" ({fname_updates} from filename)" if fname_updates else ""))
    sub(counts[Outcome.MATCH], "already complete (nothing to update)")
    sub(counts[Outcome.TZ_MISMATCH], "date differs < 24h, likely timezone (left alone)")
    sub(counts[Outcome.CONFLICT], "date differs > 24h — review (left alone)")
    sub(counts[Outcome.NO_DATA], "no date available (skipped)")


# --- steps 9-10: confirm + write --------------------------------------------
def _write_phase(
    exiftool_path: str,
    decisions: list[Decision],
    cache: Cache,
    *,
    assume_yes: bool,
) -> None:
    updates = [d for d in decisions if d.needs_update]
    # Already-written files (a previous interrupted run) are skipped by status.
    pending = [d for d in updates if cache.get_status(d.media_path) != "written"]
    if not pending:
        typer.secho("\nNothing to update.", fg=typer.colors.GREEN)
        return

    json_updates = [d for d in pending if d.date_source is not DateSource.FILENAME]
    fname_updates = [d for d in pending if d.date_source is DateSource.FILENAME]

    if not assume_yes and json_updates:
        typer.confirm(
            f"\nUpdate metadata for {len(json_updates)} files?", abort=True
        )
    chosen = list(json_updates)
    if fname_updates:
        if assume_yes or typer.confirm(
            f"Also update {len(fname_updates)} files using dates parsed from "
            "filenames (a guess)?",
            default=False,
        ):
            chosen += fname_updates

    _write(exiftool_path, chosen, cache)


def _write(exiftool_path: str, chosen: list[Decision], cache: Cache) -> None:
    if not chosen:
        return
    by_path = {d.media_path: d for d in chosen}
    written = failed = 0
    with typer.progressbar(length=len(chosen), label="  Writing") as bar:
        for start in range(0, len(chosen), WRITE_CHUNK):
            batch = chosen[start : start + WRITE_CHUNK]
            result = write_metadata_batch(
                exiftool_path,
                [(d.media_path, d.to_write) for d in batch],
            )
            for path in result.updated:
                cache.mark(path, "written")
                written += 1
            for path, reason in result.failed:
                d = by_path[path]
                status = "conflict" if d.outcome is Outcome.CONFLICT else "failed"
                cache.mark(path, status, reason)
                failed += 1
            bar.update(len(batch))

    typer.secho(f"\nWritten: {written}", fg=typer.colors.GREEN)
    if failed:
        typer.secho(f"Failed:  {failed} (see cache 'error' column)", fg=typer.colors.RED)


def preflight() -> str:
    """Verify required external tools before running any command."""
    try:
        return resolve_exiftool()
    except ExifToolNotFound as err:
        typer.secho(str(err), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
