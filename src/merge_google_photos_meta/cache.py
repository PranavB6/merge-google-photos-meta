"""SQLite read-cache and write-state store (Data model section of the plan).

Two jobs, one row per media file:

1. **Read cache** — avoid re-running ExifTool. Keyed by ``path`` plus the
   ``(mtime, size)`` stat tuple; a row whose stat still matches is a hit. After
   a file is written its mtime changes, so the cached read self-invalidates and
   a later run re-reads it (correct, if slightly slower).
2. **Write state** — a ``status`` column (``pending``/``written``/``skipped``/
   ``conflict``/``failed``) makes the write phase resumable: a crash mid-run
   leaves already-written files marked, so a re-run skips them by path.

The DB must live **outside** the media tree so discovery doesn't ingest it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .compare_metadata import ExistingMeta

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    path            TEXT PRIMARY KEY,
    mtime           REAL    NOT NULL,
    size            INTEGER NOT NULL,
    exif_date       TEXT,
    has_gps         INTEGER NOT NULL DEFAULT 0,
    has_description INTEGER NOT NULL DEFAULT 0,
    read_done       INTEGER NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'pending',
    error           TEXT
);
"""


class Cache:
    """A SQLite-backed read cache + write-state store. Use as a context manager."""

    def __init__(self, db_path: str | Path):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        # WAL: concurrent-friendly and far fewer fsyncs than the default journal.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # --- read cache ---------------------------------------------------------
    def get_existing(self, path: str, mtime: float, size: int) -> ExistingMeta | None:
        """Return cached :class:`ExistingMeta` iff a fresh read row matches stat."""
        row = self.conn.execute(
            "SELECT exif_date, has_gps, has_description FROM media "
            "WHERE path = ? AND mtime = ? AND size = ? AND read_done = 1",
            (path, mtime, size),
        ).fetchone()
        if row is None:
            return None
        return ExistingMeta(
            date_taken=(
                datetime.fromisoformat(row["exif_date"]) if row["exif_date"] else None
            ),
            has_gps=bool(row["has_gps"]),
            has_description=bool(row["has_description"]),
        )

    def put_existing_batch(
        self, entries: Iterable[tuple[str, float, int, ExistingMeta]]
    ) -> None:
        """Upsert many read results in a single transaction (cheap, no per-row fsync).

        Resets ``status`` to ``pending`` since a fresh read means the file's
        prior write state no longer applies.
        """
        rows = [
            (
                path,
                mtime,
                size,
                meta.date_taken.isoformat() if meta.date_taken else None,
                int(meta.has_gps),
                int(meta.has_description),
            )
            for path, mtime, size, meta in entries
        ]
        with self.conn:  # one transaction for the whole chunk
            self.conn.executemany(
                """
                INSERT INTO media (path, mtime, size, exif_date, has_gps,
                                   has_description, read_done, status)
                VALUES (?, ?, ?, ?, ?, ?, 1, 'pending')
                ON CONFLICT(path) DO UPDATE SET
                    mtime=excluded.mtime, size=excluded.size,
                    exif_date=excluded.exif_date, has_gps=excluded.has_gps,
                    has_description=excluded.has_description, read_done=1,
                    status='pending', error=NULL
                """,
                rows,
            )

    # --- write state --------------------------------------------------------
    def get_status(self, path: str) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM media WHERE path = ?", (path,)
        ).fetchone()
        return row["status"] if row else None

    def mark(self, path: str, status: str, error: str | None = None) -> None:
        """Record the write outcome for one file (path-keyed, stat-independent)."""
        with self.conn:
            self.conn.execute(
                "UPDATE media SET status = ?, error = ? WHERE path = ?",
                (status, error, path),
            )
