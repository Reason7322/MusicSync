"""Deterministic filename proposal logic.

Two naming conventions are supported, matching the human review decisions in
the historical rename map (used strictly as *convention examples*, never as
verified song identities):

- Standard track:   ``Artist - Title.mp3``
- Game soundtrack:  ``Game Name OST - Track.mp3``  via :func:`make_ost_name` /
  caller-supplied game hints.

Reliability model
-----------------
- *Deterministic* proposals come from reliable ID3v2 tags (TPE1/TIT2) or from a
  filename that already has an unambiguous single ``Artist - Title`` shape.
  Only enumerated junk patterns are removed; nothing else is rewritten, and no
  word is ever invented, re-cased against external knowledge, or reordered
  across identities.
- Anything requiring identifying an unknown artist/title (missing metadata,
  conflicting frame values, multiple separators, one side empty after cleanup)
  becomes status ``ambiguous`` with machine-readable reasons/flags instead of a
  guessed name. Callers force exact results per file via :class:`Override`;
  overrides are validated exactly like any proposal and never bypass collision
  checks or the apply-time safety revalidation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .cleaning import (
    MAX_NAME_BYTES,
    Reason,
    clean_filename_stem,
    clean_text,
)
from .scanner import ScannedFile
from .tags import TagSnapshot

__all__ = [
    "OST_SUFFIX",
    "Override",
    "NameProposal",
    "make_ost_name",
    "propose_name",
]

#: Suffix appended to a caller-supplied game name for the OST convention.
OST_SUFFIX = " OST"

# ASCII hyphen/en-dash/em-dash/pipe as identity separator. The fullwidth bar
# ｜ is deliberately NOT a separator: files shaped like "Game｜DLC｜Track" would
# be misread as artist/title, so they stay ambiguous instead.
_SEPARATOR_RE = re.compile(r"\s+[-\u2013\u2014|]\s+")

_STEM_RE = re.compile(r"^(?P<stem>.+)\.mp3$", re.I)

_OST_HINT_TEXT_RE = re.compile(r"(?i)\b(?:original\s+soundtrack|soundtrack|ost\b)")


@dataclass(frozen=True)
class Override:
    """Caller-decided final filename for one file (review result)."""

    rel_path: str  # relative path, as produced by the scanner
    name: str  # bare stem or full filename; extension added if missing
    note: str = ""


@dataclass(frozen=True)
class NameProposal:
    status: str  # ok | no_change | ambiguous | error
    proposed_name: Optional[str] = None  # full filename incl. .mp3
    reasons: tuple[Reason, ...] = field(default=())
    flags: tuple[Reason, ...] = field(default=())

    @property
    def changed(self) -> bool:
        """True when applying this proposal would rename the file."""
        return self.status == "ok"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reason(code: str, detail: str = "") -> Reason:
    return Reason(code, detail)


def make_ost_name(game: str, track: str) -> str:
    """Build a ``Game OST - Track.mp3`` filename from cleaned parts."""
    game = clean_text(game).value.strip()
    track = clean_text(track).value.strip()
    if not game or not track:
        raise ValueError("OST name needs both a game and a track part")
    return _with_extension(f"{game}{OST_SUFFIX} - {track}")


def propose_override(override_name: str) -> NameProposal:
    """Wrap a caller override decision. Structural validation (collisions,
    length, path safety) is enforced by the engine at preview/apply time."""
    name = (override_name or "").strip()
    if not name:
        raise ValueError("override name must be non-empty")
    return NameProposal("ok", _with_extension(name), (_reason("caller_override"),))


def _stem_of(name: str) -> str:
    match = _STEM_RE.match(name)
    if not match:
        raise ValueError(f"not an mp3 filename: {name!r}")
    return match.group("stem")


def _with_extension(base: str) -> str:
    base = base.strip()
    if re.search(r"\.(mp3|flac|ogg|m4a)$", base, re.I):
        return base
    return f"{base}.mp3"


def _finalize_stem(stem: str) -> str:
    return re.sub(r"\s+", " ", stem).strip(" \t-–—|·.,:")


def _safety_flags(name: str) -> tuple[Reason, ...]:
    """Non-blocking safety notes about a proposed filename."""
    flags = []
    if len(name.encode("utf-8")) > MAX_NAME_BYTES:
        flags.append(_reason("name_too_long", f"{len(name.encode('utf-8'))} bytes > 255"))
    hard_invalid = [c for c in name if (c == "\x00" or c == "/" or c == "\\" or ord(c) < 32)]
    if hard_invalid:
        flags.append(_reason("name_contains_unsafe_chars", repr(hard_invalid)))
    soft_invalid = [c for c in name if c in '*?"<>|']
    if soft_invalid and not hard_invalid:
        # Legal on Linux, but the downstream Android mapping may alter them.
        flags.append(_reason("android_mapping_may_alter_chars", repr(sorted(set(soft_invalid)))))
    return tuple(flags)


def _dedupe_flags(flags) -> tuple[Reason, ...]:
    seen: dict[str, Reason] = {}
    for flag in flags:
        seen.setdefault(flag.code, flag)
    return tuple(seen.values())


def _finish(
    scanned: ScannedFile,
    status: str,
    proposed: Optional[str],
    reasons: tuple[Reason, ...],
    flags: tuple[Reason, ...],
) -> NameProposal:
    if proposed is not None and proposed != scanned.name:
        status = "ok"
    elif proposed == scanned.name:
        status = "no_change"
    return NameProposal(status, proposed, tuple(reasons), _dedupe_flags(flags + _extra(proposed)))


def _extra(proposed: Optional[str]) -> tuple[Reason, ...]:
    if proposed is None:
        return ()
    return _safety_flags(proposed)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def propose_name(
    scanned: ScannedFile,
    tags: TagSnapshot,
    override: Optional[Override] = None,
) -> NameProposal:
    """Propose a deterministic name for one file. Pure function; no I/O.

    ``tags`` is the :class:`TagSnapshot` captured at scan time (possibly with
    ``has_tags=False``). Unreadable files are reported by the engine as status
    ``error`` before this module is reached.
    """
    current = scanned.name
    stem = _stem_of(current)

    # 0) Caller override wins, still validated downstream.
    if override is not None and override.rel_path == scanned.rel_path:
        wrapped = propose_override(override.name)
        return _finish(scanned, "ok", wrapped.proposed_name, wrapped.reasons, (_reason("reviewed_by_caller"),))

    # 1) Reliable tags -> tag-based proposal.
    if tags.has_tags:
        artist_raw = tags.artist  # single distinct non-empty value else None
        title_raw = tags.title
        conflict_flags = tuple(_missing_tag_flags(tags))
        if artist_raw and title_raw:
            artist_cleaned = clean_text(artist_raw)
            title_cleaned = clean_text(title_raw)
            flags: list[Reason] = list(conflict_flags)
            if not artist_cleaned.value or not title_cleaned.value:
                return _finish(
                    scanned,
                    "ambiguous",
                    None,
                    (),
                    (_reason("tag_cleaned_to_empty", "junk removal emptied a tag value"),) + tuple(flags),
                )
            proposed = _with_extension(f"{artist_cleaned.value} - {title_cleaned.value}")
            reasons = (
                _reason("from_tags", "TPE1/TIT2")
            ) + artist_cleaned.reasons + title_cleaned.reasons
            if _OST_HINT_TEXT_RE.search(f"{artist_cleaned.value} {title_cleaned.value}") or _OST_HINT_TEXT_RE.search(stem):
                flags.append(_reason("ost_candidate", "consider 'Game OST - Track' convention"))
            return _finish(scanned, "ok", proposed, reasons, tuple(flags))
        # Tags incomplete -> fall through to filename review carrying the flags.
        flags0: tuple[Reason, ...] = conflict_flags
    else:
        flags0 = ()

    # 2) Conservative filename-derived proposal (structure must already exist).
    cleaned_stem = clean_filename_stem(stem)
    value = _finalize_stem(cleaned_stem.value)
    separator_count = len(_SEPARATOR_RE.findall(value))
    reasons = (_reason("from_filename"), *cleaned_stem.reasons)
    flags: list[Reason] = list(flags0)

    if separator_count == 1:
        left, right = _SEPARATOR_RE.split(value, maxsplit=1)
        left_clean = clean_text(left).value.strip()
        right_clean = clean_text(right).value.strip()
        if not left_clean or not right_clean:
            return _finish(
                scanned,
                "ambiguous",
                None,
                reasons,
                tuple(flags + (_reason("one_side_empty_after_cleanup"),)),
            )
        proposed = _with_extension(f"{left_clean} - {right_clean}")
    elif separator_count >= 2:
        return _finish(
            scanned,
            "ambiguous",
            None,
            reasons,
            tuple(flags + (_reason("multiple_separators", f"{separator_count} found"),)),
        )
    else:  # single identifier: cleanup only, no identity guessing
        proposed = _with_extension(value)

    if _OST_HINT_TEXT_RE.search(value):
        flags.append(_reason("ost_candidate", "consider 'Game OST - Track' convention"))
    return _finish(scanned, "ok", proposed, reasons, tuple(flags))


def _missing_tag_flags(tags: TagSnapshot) -> list[Reason]:
    out = []
    distinct_artists = {a.strip() for a in tags.artists if a.strip()}
    distinct_titles = {t.strip() for t in tags.titles if t.strip()}
    if len(distinct_artists) > 1:
        out.append(_reason("conflicting_artist_values", f"{len(distinct_artists)} values"))
    elif not distinct_artists:
        out.append(_reason("missing_or_empty_artist_tag"))
    if len(distinct_titles) > 1:
        out.append(_reason("conflicting_title_values", f"{len(distinct_titles)} values"))
    elif not distinct_titles:
        out.append(_reason("missing_or_empty_title_tag"))
    return out
