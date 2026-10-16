"""ID3 tag reading and surgical editing for MP3 files via mutagen.

Design constraints (Phase 1):
- Reading is pure observation; nothing here writes unless :func:`apply_tag_edits`
  is called explicitly by the engine during an approved apply step.
- Edits are limited to replacing TIT2/TPE1 text frames with caller-supplied
  cleaned values (or deleting a frame). mutagen rewrites only the ID3v2 region
  on save; audio bytes, cover art (APIC), ReplayGain (RVRB / TXXX:REPLAYGAIN_*)
  and all other frames are preserved (verified by tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    from mutagen.id3 import ID3, TIT2, TPE1
except ImportError as exc:  # pragma: no cover - dependency guard
    raise ImportError(
        "musicsyncrename requires the 'mutagen' package (pip install mutagen)."
    ) from exc

__all__ = [
    "TagSnapshot",
    "ParseError",
    "read_tag_snapshot",
    "apply_tag_edits",
]


class ParseError(Exception):
    """File is not a readable MP3/ID3 source."""


@dataclass(frozen=True)
class TagSnapshot:
    """Observational snapshot of an MP3 file's ID3v2 metadata.

    ``artists``/``titles`` contain the individual text values as stored (a
    frame may hold several lines/values). Empty tuples mean "absent".
    """

    has_tags: bool
    artists: tuple[str, ...] = ()
    titles: tuple[str, ...] = ()
    album: Optional[str] = None
    replaygain_keys: tuple[str, ...] = ()  # e.g. ("RVRB", "TXXX:REPLAYGAIN_TRACK_GAIN")
    artwork_frames: int = 0
    frame_key_count: int = 0

    @property
    def artist(self) -> Optional[str]:
        """Single reliable artist value, or None when absent or conflicting."""
        distinct = {a.strip() for a in self.artists if a.strip()}
        return next(iter(distinct)) if len(distinct) == 1 else None

    @property
    def title(self) -> Optional[str]:
        distinct = {t.strip() for t in self.titles if t.strip()}
        return next(iter(distinct)) if len(distinct) == 1 else None


def _frame_texts(frames, key: str) -> tuple[str, ...]:
    values: list[str] = []
    for frame in frames:
        text = getattr(frame, "text", None)
        if isinstance(text, (list, tuple)):
            values.extend(str(part).strip() for part in text)
        elif isinstance(text, str):
            values.append(text.strip())
    return tuple(v for v in values if v)


def read_tag_snapshot(path: os.PathLike | str) -> TagSnapshot:
    """Read ID3 tags without modifying the file.

    Returns a snapshot with ``has_tags=False`` when the file carries no
    readable ID3v2 block (ID3v1-only or untagged files count as "no reliable
    metadata"; filename-based review still applies upstream). Raises
    :class:`ParseError` for unreadable or non-MP3 content.
    """
    from mutagen.mp3 import MP3

    try:
        audio = MP3(str(path))
    except Exception as exc:  # mutagen raises assorted types per failure mode
        raise ParseError(f"not a readable MP3 file: {exc}") from exc

    tags = audio.tags if isinstance(audio.tags, ID3) else None
    if tags is None:
        return TagSnapshot(has_tags=False)
    artists = _frame_texts(tags.getall("TPE1"), "TPE1") or _frame_texts(
        tags.getall("TPE2"), "TPE2"  # fallback; band vs artist is a review concern
    )
    titles = _frame_texts(tags.getall("TIT2"), "TIT2")
    album_frames = _frame_texts(tags.getall("TALB"), "TALB")
    replaygain_keys = tuple(
        sorted(k for k in tags.keys() if k == "RVRB" or k.startswith("TXXX:REPLAYGAIN"))
    )
    artwork = 0
    for key in list(tags.keys()):
        if key.startswith("APIC"):
            artwork += len(tags.getall(key))
    return TagSnapshot(
        has_tags=True,
        artists=tuple(dict.fromkeys(artists)),
        titles=tuple(dict.fromkeys(titles)),
        album=album_frames[0] if album_frames else None,
        replaygain_keys=replaygain_keys,
        artwork_frames=artwork,
        frame_key_count=len(list(tags.keys())),
    )


_EDITABLE_FRAMES = {"TIT2": TIT2, "TPE1": TPE1}


def apply_tag_edits(path: os.PathLike | str, edits: dict[str, Optional[str]]) -> None:
    """Replace TIT2/TPE1 frame text in-place.

    ``edits`` maps a frame id to the cleaned value (empty/None deletes the
    frame). Only listed frames change; every other frame and all audio bytes
    are preserved. Refuses any other frame id rather than guessing.
    """
    from mutagen.mp3 import MP3

    if not edits:
        return
    unknown = set(edits) - set(_EDITABLE_FRAMES)
    if unknown:
        raise ValueError(f"refusing to edit unsupported frames: {sorted(unknown)}")
    try:
        audio = MP3(str(path))
    except Exception as exc:
        raise ParseError(f"cannot open for tag edit: {exc}") from exc

    if not isinstance(audio.tags, ID3):
        audio.add_tags()
    tags = audio.tags
    changed = False
    for frame_id, value in edits.items():
        current = tuple(
            text.strip()
            for frame in tags.getall(frame_id)
            for part in getattr(frame, "text", [])
            if (text := str(part).strip())
        )
        target: tuple[str, ...] | None
        if value is None or str(value).strip() == "":
            target = None
        else:
            target = (str(value).strip(),)
        if current != target:
            for key in list(tags.keys()):
                if key == frame_id or key.startswith(frame_id + ":"):
                    del tags[key]
            if target is not None:
                tags.add(_EDITABLE_FRAMES[frame_id](encoding=3, text=[target[0]]))
            changed = True
    if changed:
        audio.save()
