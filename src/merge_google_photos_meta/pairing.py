"""Pair media files with their Google Takeout JSON sidecars (pipeline step 6).

The hard part of the whole tool (``docs/TAKEOUT_CORRECTNESS.md`` §2). Rather than
computing the expected JSON name from a media name, we derive each JSON's
*target media name* (undoing the ``.supplemental-metadata`` suffix — which
Takeout truncates to any length — and the trailing ``(n)`` counter) and match
that against the real files in the same folder. Matching runs per directory,
since Takeout keeps each album's sidecars beside its media and may duplicate the
same photo across albums.

Passes, most to least confident:

1. **Exact** — JSON target equals a media filename (case-insensitively).
2. **Prefix** — independent 51-char truncation left a unique common-prefix match.
3. **Inheritance** — an unmatched media file (an ``-edited`` derivative, or the
   ``.MOV``/``.MP`` half of a Live Photo, which carry no sidecar of their own)
   inherits the sidecar of a matched sibling with the same normalized stem.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from .models import MediaFile

_COUNTER_RE = re.compile(r"\((\d+)\)$")
# Derivative suffixes Google/Pixel append to edited or generated copies; these
# files share the original's sidecar. Stripped (repeatedly) only for the
# inheritance pass, never for exact matching.
_DERIVATIVE_RE = re.compile(
    r"(-edited|-effects|-animation|-edit|_bokeh|_cover|_exported.*|~\d+)$"
)
_SUPPLEMENTAL = "supplemental-metadata"

# Minimum shared-prefix length before we'll risk a truncation match.
_MIN_PREFIX = 6


@dataclass
class PairingResult:
    """media path -> sidecar path (or ``None``), plus sidecars that matched nothing."""

    pairs: dict[str, str | None] = field(default_factory=dict)
    orphan_sidecars: list[str] = field(default_factory=list)


def _strip_counter(stem: str) -> tuple[str, str | None]:
    """Split a trailing ``(n)`` off a stem, returning ``(stem, n)``."""
    m = _COUNTER_RE.search(stem)
    if m:
        return stem[: m.start()], m.group(1)
    return stem, None


def _strip_supplemental(name: str) -> str:
    """Remove a trailing ``.<prefix-of-"supplemental-metadata">`` segment.

    Takeout truncates the suffix to any length (``.supplemental-metadata`` down
    to ``.s``), so we strip any non-empty dotted segment that is a prefix of the
    full word. A real media extension (``jpg``, ``heic``) isn't such a prefix, so
    it's left intact.
    """
    base, dot, seg = name.rpartition(".")
    if dot and seg and _SUPPLEMENTAL.startswith(seg):
        return base
    return name


def _json_target(json_name: str) -> str:
    """Derive the media filename a sidecar describes, from the JSON's filename."""
    name = json_name[:-5] if json_name.lower().endswith(".json") else json_name
    name, counter = _strip_counter(name)
    name = _strip_supplemental(name)
    if counter is not None:
        # Re-insert the counter where it sits on the media file: before the ext.
        base, dot, ext = name.rpartition(".")
        name = f"{base}({counter}).{ext}" if dot else f"{name}({counter})"
    return name


def _normalized_stem(filename: str) -> str:
    """Stem used to group derivative/companion files with their original.

    Lowercased, extension + ``(n)`` counter + derivative suffixes removed. So
    ``IMG_1-EFFECTS-edited.jpg`` and ``IMG_1.MOV`` both reduce to ``img_1``.
    """
    stem = os.path.splitext(filename)[0].lower()
    stem, _ = _strip_counter(stem)
    while True:
        stripped = _DERIVATIVE_RE.sub("", stem)
        if stripped == stem:
            break
        stem = stripped
    return stem


def _pair_dir(media: list[MediaFile], sidecars: list[str], result: PairingResult) -> None:
    """Pair one directory's media and sidecars, recording into ``result``."""
    media_by_name = {os.path.basename(m.path).casefold(): m for m in media}
    matched_media: dict[str, str] = {}  # media path -> sidecar path
    unmatched_sidecars: list[str] = []

    # Pass 1: exact target match.
    for sidecar in sidecars:
        target = _json_target(os.path.basename(sidecar)).casefold()
        m = media_by_name.get(target)
        if m is not None and m.path not in matched_media:
            matched_media[m.path] = sidecar
        else:
            unmatched_sidecars.append(sidecar)

    # Pass 2: prefix/truncation fallback — pair only when exactly one candidate.
    still_unmatched_sidecars: list[str] = []
    free_media = [m for m in media if m.path not in matched_media]
    for sidecar in unmatched_sidecars:
        target = _json_target(os.path.basename(sidecar)).casefold()
        t_stem, t_ext = os.path.splitext(target)
        candidates = [
            m
            for m in free_media
            if m.path not in matched_media
            and os.path.splitext(m.path)[1].casefold() == t_ext
            and _shared_prefix(os.path.basename(m.path).casefold(), t_stem)
        ]
        if len(candidates) == 1:
            matched_media[candidates[0].path] = sidecar
        else:
            still_unmatched_sidecars.append(sidecar)

    # Pass 3: inheritance — unmatched media adopts a matched sibling's sidecar.
    by_stem: dict[str, str] = {}  # normalized stem -> sidecar path (from matched)
    for path, sidecar in matched_media.items():
        by_stem.setdefault(_normalized_stem(os.path.basename(path)), sidecar)
    for m in media:
        if m.path in matched_media:
            continue
        inherited = by_stem.get(_normalized_stem(os.path.basename(m.path)))
        if inherited is not None:
            matched_media[m.path] = inherited

    for m in media:
        result.pairs[m.path] = matched_media.get(m.path)
    result.orphan_sidecars.extend(still_unmatched_sidecars)


def _shared_prefix(media_stem: str, target_stem: str) -> bool:
    """True if one stem is a prefix of the other and the overlap is long enough.

    Captures independent 51-char truncation, where the media name and the JSON's
    embedded name share a long head but diverge at the truncated tail.
    """
    overlap = min(len(media_stem), len(target_stem))
    if overlap < _MIN_PREFIX:
        return False
    return media_stem[:overlap] == target_stem[:overlap]


def pair(media: list[MediaFile], sidecars: list[str]) -> PairingResult:
    """Pair every media file with a sidecar (or ``None``), grouped by directory."""
    result = PairingResult()
    media_by_dir: dict[str, list[MediaFile]] = defaultdict(list)
    sidecars_by_dir: dict[str, list[str]] = defaultdict(list)
    for m in media:
        media_by_dir[os.path.dirname(m.path)].append(m)
    for s in sidecars:
        sidecars_by_dir[os.path.dirname(s)].append(s)

    for directory, dir_media in media_by_dir.items():
        _pair_dir(dir_media, sidecars_by_dir.get(directory, []), result)
    # Sidecars in directories with no media at all are orphans too.
    for directory, dir_sidecars in sidecars_by_dir.items():
        if directory not in media_by_dir:
            result.orphan_sidecars.extend(dir_sidecars)
    return result
