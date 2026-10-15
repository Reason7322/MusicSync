"""Synthetic MP3 fixtures for the focused unittest suite.

Offline-only: everything is built from scratch in caller-provided tempdirs.
Reuses the verified silent-MP3 builder and ``audio_part`` comparison helper
from .scratch_probe.py, plus a minimal 1x1 PNG generator and tag helpers using
the documented mutagen 1.47 API facts:

- TXXX constructor takes ``text=`` (NOT ``value=``),
- TXXX lookup key format is ``"TXXX:<desc>"``,
- APIC keys on reload are normalized to the bare ``"APIC:"`` prefix,
- MP3 has no ``close()``.
"""

import os
import struct
import sys
import zlib

# Make the project root importable regardless of cwd (belt and braces; the
# mandated command is run from the project root anyway).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def mpeg_frame() -> bytes:
    """One silent MPEG-1 Layer III 128 kbps/44.1 kHz mono frame (417 bytes)."""
    return bytes([0xFF, 0xFB, 0x90, 0xC0]) + b"\x00" * 413


def build_mp3(path, frames: int = 8) -> str:
    """Write a minimal silent MP3 to ``path``. Returns the path as str."""
    with open(str(path), "wb") as f:
        for _ in range(frames):
            f.write(mpeg_frame())
    return str(path)


def audio_part(data: bytes) -> bytes:
    """Audio region of an MP3 blob: from the first 0xFFFB sync after offset 10.

    This is the verified preservation check from .scratch_probe.py (do not use
    ID3 header size-field arithmetic instead).
    """
    i = data.find(b"\xff\xfb", 10)
    return data[i:] if i >= 0 else data


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    body = struct.pack(">I", len(payload)) + tag + payload
    return body + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)


def make_png_1x1() -> bytes:
    """Minimal valid 1x1 RGBA PNG used as cover-art fixture data.

    The single scanline is exactly 5 bytes: one filter byte (0 = None) plus a
    4-byte RGBA pixel. (The earlier payload was 4 bytes total and decoded to a
    truncated scanline; mutagen stores APIC data opaquely, so tests stayed
    green while the fixture PNG was invalid.)
    """
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    scanline = b"\x00" + bytes((0xFF, 0x00, 0x00, 0xFF))  # filter byte + RGBA pixel
    idat = _png_chunk(b"IDAT", zlib.compress(scanline))
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + _png_chunk(b"IEND", b"")


def add_basic_tags(path) -> None:
    """Attach the full synthetic tag set used by preservation tests.

    Frames written: TPE1, TIT2 (with junk suffix for cleaning tests), TALB,
    RVRB, one APIC PNG cover, and two ReplayGain TXXX frames (``text=``).
    """
    from mutagen.id3 import APIC, ID3, RVRB, TALB, TIT2, TPE1, TXXX
    from mutagen.mp3 import MP3

    audio = MP3(str(path))
    tags = audio.tags if isinstance(audio.tags, ID3) else ID3()
    tags.add(TPE1(encoding=3, text="Test Artist"))
    tags.add(TIT2(encoding=3, text="Dream On - Lyrics (Official HD Video)"))
    tags.add(TALB(encoding=3, text="Toys in the Attic"))
    tags.add(RVRB())
    tags.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=make_png_1x1()))
    tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text="-8.2 dB"))
    tags.add(TXXX(encoding=3, desc="REPLAYGAIN_ALBUM_PEAK", text="0.987654"))
    audio.tags = tags
    audio.save()


def set_tags(path, *, artist=None, title=None) -> None:
    """(Re)write only TPE1/TIT2 on an MP3; a value of None removes the frame."""
    from mutagen.id3 import ID3, TIT2, TPE1
    from mutagen.mp3 import MP3

    audio = MP3(str(path))
    if not isinstance(audio.tags, ID3):
        audio.add_tags()
    tags = audio.tags
    for frame_id in ("TPE1", "TIT2"):
        for key in list(tags.keys()):
            if key == frame_id or key.startswith(frame_id + ":"):
                del tags[key]
    if artist is not None:
        tags.add(TPE1(encoding=3, text=artist))
    if title is not None:
        tags.add(TIT2(encoding=3, text=title))
    audio.save()


def frame_frames(tags, prefix: str):
    """All frames whose reload key starts with ``prefix`` (APIC keys normalize
    to the bare 'APIC:' form on reload)."""
    out = []
    for key in list(tags.keys()):
        if key.startswith(prefix):
            out.extend(tags.getall(key))
    return out
