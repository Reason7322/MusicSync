"""Deterministic text normalization and junk-removal rules for track names.

Everything here is pure: same input -> same output, no I/O, no randomness, no
wall clock. Two kinds of transformation are allowed:

1. Unicode normalizations that repair well-known broken encoding (NFC form,
   zero-width characters, fullwidth/broken punctuation mapped to their ASCII
   equivalents).
2. Removal of *enumerated* junk patterns from recognizable downloader/video
   publishing sources (official video markers, lyric markers, audio-quality
   suffixes, leading track numbers).

Anything that would require identifying an unknown artist or title is NOT done
here: the naming layer reports such files as ambiguous instead of guessing.
Every removal is reported through :class:`CleanedText.reasons` so previews can
show exactly what was removed and why.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

__all__ = [
    "MAX_NAME_BYTES",
    "Reason",
    "CleanedText",
    "normalize_text",
    "name_key",
    "clean_text",
    "clean_filename_stem",
]

#: Maximum byte length of a single filename component (ext4/Android FUSE).
MAX_NAME_BYTES = 255


@dataclass(frozen=True)
class Reason:
    """A single reported transformation or flag.

    ``code`` is stable and machine-readable; ``detail`` carries the affected
    text for human review.
    """

    code: str
    detail: str = ""


@dataclass(frozen=True)
class CleanedText:
    value: str
    reasons: tuple[Reason, ...] = field(default=())

    @property
    def changed(self) -> bool:  # noqa: D102 - trivial helper
        return any(r.code != "unchanged" for r in self.reasons)


# --------------------------------------------------------------------------
# Normalization (step 1)
# --------------------------------------------------------------------------

_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")

#: Well-known broken punctuation mapped to safe ASCII equivalents.
_BROKEN_PUNCTUATION = str.maketrans(
    {
        "\uff1a": ":",  # fullwidth colon
        "\uff1f": "?",  # fullwidth ?
        "\uff01": "!",  # fullwidth !
        "\uff02": '"',  # fullwidth decorative double quote
        "\u2033": "'",  # double prime often misused as apostrophe
        "\u2019": "'",  # right single quotation mark
        "\uff07": "'",  # fullwidth '
        "\u201c": '"',  # left "
        "\u201d": '"',  # right "
        "\uff08": "(",  # fullwidth (
        "\uff09": ")",  # fullwidth )
    }
)


def normalize_text(value: str) -> tuple[str, list[Reason]]:
    """NFC-normalize ``value``, strip zero-width characters and map a small set
    of well-known broken punctuation to ASCII. Returns (text, reasons)."""
    reasons: list[Reason] = []
    nfc = unicodedata.normalize("NFC", value)
    if nfc != value:
        reasons.append(Reason("normalized_nfc"))
    out = nfc
    if _ZERO_WIDTH_RE.search(out):
        replaced = _ZERO_WIDTH_RE.sub("", out)
        removed = "".join(_ZERO_WIDTH_RE.findall(out))
        reasons.append(Reason("stripped_zero_width_chars", repr(removed)))
        out = replaced
    mapped = out.translate(_BROKEN_PUNCTUATION)
    if mapped != out:
        reasons.append(Reason("replaced_broken_punctuation"))
        out = mapped
    return out, reasons


def name_key(name: str) -> str:
    """Collision key for filenames on case- and normalization-insensitive
    filesystems (Android shared storage / macOS). Two names that share a key
    cannot both exist there, so proposals must not produce one from the other.
    Used ONLY for comparison, never to rewrite text."""
    return unicodedata.normalize("NFKC", name).casefold()


# --------------------------------------------------------------------------
# Junk patterns (step 2)
# --------------------------------------------------------------------------

_QUOTE_WRAP_RE = re.compile(r'^"(.*)"$', re.S)
_APOSTROPHE_WRAP_RE = re.compile("^'(.*)'$", re.S)

#: Parenthetical/bracket groups whose ENTIRE content matches one of these are
#: recognized downloader/video junk. Matching is anchored on the group's whole
#: inner text, so genuine version descriptors like "(Remastered)" or
#: "(DmC: Devil May Cry OST)" never match and are preserved.
_PAREN_JUNK_RES = (
    re.compile(r"\A\s*official\s+(?:hd|4k)(\s+video)?\s*\Z", re.I),
    re.compile(r"\A\s*(?:official\s+)?(?:hq|hi[\s\-]?fi|high[\s-]*quality)\b[a-z0-9 .\-]*\Z", re.I),
    re.compile(r"\A\s*(?:official\s+)?lyric(?:al)?\s*(?:music\s*)?video\s*\Z", re.I),
    re.compile(r"\A\s*(?:official\s+)?music\s*video\s*\Z", re.I),
    re.compile(r"\A\s*(?:official\s+)?(?:video|clip)\s*\Z", re.I),
    re.compile(r"\A\s*(?:with\s+)?lyrics?\s*\Z", re.I),
    re.compile(r"\A\s*words\s*\Z", re.I),
    re.compile(r"\A\s*\d{3,4}p\b[^\w]\S*\Z", re.I),  # e.g. "(1080p ...)"
    re.compile(r"\A\s*(?:official\s+)?audio\s+\d{2,4}\s*kbps\b[a-z ()\-]*\Z", re.I),
)

_PAREN_GROUP_RE = re.compile(r"[（(\[]([^()[\]{}]{0,160})[）)\]]")


def _remove_junk_groups(text: str, reasons: list[Reason]) -> str:
    """Remove parenthetical/bracket groups whose content is recognized junk."""

    def replace(match: re.Match) -> str:
        inner = match.group(1).strip()
        if any(rx.match(inner) for rx in _PAREN_JUNK_RES):
            reasons.append(Reason("removed_junk_group", f"({inner})"))
            return ""
        return match.group(0)

    previous = None
    while previous != text:  # fixed point handles nested/adjacent groups
        previous = text
        text = _PAREN_GROUP_RE.sub(replace, text).replace(" .", " ")
    return text


#: Trailing junk at the END of a title or filename stem.
_TRAILING_JUNK_RES = (
    re.compile(r"\s*[-–—|·]?\s*(?:lyrics?|words)\s*\Z", re.I),
    re.compile(r"\s*[-–—|·]?\s*(?:official\s+)?(?:hq|hd|4k)\b[a-z0-9 .\-]*\Z", re.I),
    re.compile(r"\s*[-–—|·]?\s*(?:lyric(?:al)?\s*)?music\s*video\b[^\w(]*\Z", re.I),
    re.compile(r"(?i)\baudio\s+\d{2,4}\s*kbps\b[a-z ()\-]*\Z"),
    re.compile(r"\s*[-–—|·]?\s*(?:official\s+)?(?:hd|4k)(\s+video)?\s*\Z", re.I),
)


def _remove_trailing_junk(text: str, reasons: list[Reason]) -> str:
    previous = None
    while previous != text:
        previous = text
        for rx in _TRAILING_JUNK_RES:
            match = rx.search(text)
            if match:
                removed = text[match.start():].strip()
                text = text[: match.start()].rstrip(" -–—|·.,")
                reasons.append(Reason("removed_junk_suffix", f"({removed})"))
                break
    return text


#: Leading junk at the START of a filename stem (track numbering). Never
#: applied to tag values.
_LEADING_JUNK_RES = (
    re.compile(r"(?i)^track\s+\d{1,4}\s*[:\-–—|]?\s*"),
    re.compile(r"^\d{1,3}\s*[.)]\s+"),
    re.compile(r"^\d{1,5}[\s]+[-–—|]?[\s]*"),
)


def _remove_leading_junk(text: str, reasons: list[Reason]) -> str:
    for rx in _LEADING_JUNK_RES:
        match = rx.match(text)
        if match and match.end() < len(text):
            removed = text[: match.end()].strip()
            text = text[match.end():]
            reasons.append(Reason("removed_track_number", f"({removed})"))
    return text


def _unwrap_quotes(text: str, reasons: list[Reason]) -> str:
    for _ in range(3):  # nested decorative quoting
        match = _QUOTE_WRAP_RE.match(text) or _APOSTROPHE_WRAP_RE.match(text)
        if not match or not match.group(1).strip():
            break
        text = match.group(1).strip()
        reasons.append(Reason("removed_quote_wrap"))
    return text


_EDGE_TRAILING_PUNCT_RE = re.compile(r"[\s\-–—·.,:!?'\"~*]+$")


def _finalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = _EDGE_TRAILING_PUNCT_RE.sub("", text).strip()
    return text


# --------------------------------------------------------------------------
# Public cleaning entry points
# --------------------------------------------------------------------------


def clean_text(value: str) -> CleanedText:
    """Clean a tag value (title/artist). Deterministic; reports all steps."""
    if not isinstance(value, str):
        raise TypeError("clean_text expects str")
    reasons: list[Reason] = []
    text, norm_reasons = normalize_text(value)
    reasons.extend(norm_reasons)
    text = _unwrap_quotes(text, reasons)
    text = _remove_junk_groups(text, reasons)
    text = _remove_trailing_junk(text, reasons)
    text = _finalize(text)
    if not reasons and text == value:
        return CleanedText(value, ())
    if not reasons:  # whitespace/edge punctuation changed only; keep it visible.
        reasons.append(Reason("trimmed_whitespace"))
    return CleanedText(text, tuple(reasons))


def clean_filename_stem(stem: str) -> CleanedText:
    """Clean a filename stem (without extension). In addition to tag cleaning,
    removes leading track-number prefixes from downloader rips."""
    cleaned = clean_text(stem)
    if not any(r.code == "removed_track_number" for r in cleaned.reasons):
        text, reasons = cleaned.value, list(cleaned.reasons)
        stripped = _remove_leading_junk(text, reasons)
        if stripped != text:
            text = _finalize(stripped)
        return CleanedText(text, tuple(reasons))
    return cleaned
