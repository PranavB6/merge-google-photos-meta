"""Best-effort capture date parsed from a filename (last resort, step 1.2/7).

Only used when neither the embedded metadata nor a JSON sidecar has a date. The
result is a *guess* — the CLI surfaces filename-derived dates separately for
explicit confirmation. Because we search for the date as a substring, trailing
disambiguation suffixes (``(1)``, ``-1``, ``~2``, ``-edited``) don't interfere.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# Each pattern captures (year, month, day, hour, minute, second). Ordered most-
# to least specific. Anchored loosely (substring search) so prefixes like
# ``IMG_`` / ``PXL_`` / ``Screenshot_`` and trailing junk are tolerated.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 2015-06-26 05.20.33  and  2015-06-26_05.20.33
    re.compile(r"(\d{4})-(\d{2})-(\d{2})[ _](\d{2})\.(\d{2})\.(\d{2})"),
    # Screenshot_2015-06-26-05-20-33  (all-dash form)
    re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})"),
    # IMG_20230715_143000 / VID_/PXL_/Screenshot_20230715_143000 (millis tolerated)
    re.compile(r"(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})"),
)


def parse_filename_date(path: str | Path) -> datetime | None:
    """Return a capture datetime parsed from the filename, or ``None``.

    Tries each known pattern in order and returns the first that forms a valid
    calendar date in a plausible year range (1990–2100). The returned value is
    naive (filename timestamps carry no timezone).
    """
    stem = Path(path).name
    for pattern in _PATTERNS:
        match = pattern.search(stem)
        if not match:
            continue
        year, month, day, hour, minute, second = (int(g) for g in match.groups())
        if not 1990 <= year <= 2100:
            continue
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            continue  # e.g. matched digits that aren't a real date
    return None
