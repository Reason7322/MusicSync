"""Safe read-only scanning of a user-selected music root.

Guarantees (Phase 1):
- Never follows directory symlinks; symlinked files are reported and skipped,
  never scanned for tags and never rename candidates.
- Deterministic ordering: directories walked top-down, entries sorted by name.
- No file is opened for writing anywhere in this module.
- Only regular non-symlink ``*.mp3`` (case-insensitive) become track items;
  everything else is counted so callers can report what was ignored.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["ScannedFile", "ScanResult", "scan_root"]

TRACK_SUFFIXES = {".mp3"}


@dataclass(frozen=True)
class ScannedFile:
    rel_path: str  # relative to root, "/" separated
    name: str
    size: int
    mtime_ns: int

    @property
    def parent(self) -> str:
        head, _, _ = self.rel_path.rpartition("/")
        return head


@dataclass(frozen=True)
class ScanResult:
    root: str  # absolute path (as given, resolved for containment later)
    files: tuple[ScannedFile, ...]  # MP3 tracks only
    symlinks_skipped: tuple[str, ...]  # rel paths of symlinks (files or dirs)
    other_file_count: int  # non-MP3 regular files seen
    directory_count: int
    dir_entries: dict[str, tuple[str, ...]] = field(default_factory=dict)  # rel_dir -> all entry names

    def file(self, rel_path: str) -> ScannedFile | None:
        for candidate in self.files:
            if candidate.rel_path == rel_path:
                return candidate
        return None


def scan_root(root: os.PathLike | str) -> ScanResult:
    """Scan ``root`` recursively without following symlinks. Read-only."""
    root_path = Path(os.path.abspath(os.fspath(root)))
    if not root_path.is_dir():
        raise NotADirectoryError(f"scan root is not a directory: {root}")

    files: list[ScannedFile] = []
    symlinks_skipped: list[str] = []
    dir_entries: dict[str, list[str]] = {}
    other_file_count = 0
    directory_count = 0

    def walk(rel_dir: str, dir_path: Path) -> None:
        nonlocal other_file_count
        try:
            with os.scandir(dir_path) as it:
                entries = sorted(it, key=lambda e: (e.is_symlink(), e.name))
        except OSError as exc:
            raise PermissionError(f"cannot read directory {dir_path}: {exc}") from exc
        dir_entries[rel_dir] = [entry.name for entry in entries]
        for entry in entries:
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_link = entry.is_symlink()
            except OSError:  # vanished mid-scan; treat conservatively as skipped link
                symlinks_skipped.append(rel)
                continue
            if is_link:
                symlinks_skipped.append(rel)
                continue  # never traverse or rename through links
            if is_dir:
                directory_count += 1
                walk(rel, dir_path / entry.name)
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                symlinks_skipped.append(rel)
                continue
            mode = getattr(info, "st_mode", None)
            if not (mode is not None and stat.S_ISREG(mode)):  # fifos/sockets/devices ignored+counted
                other_file_count += 1
                continue
            suffix = os.path.splitext(entry.name)[1].lower()
            if suffix in TRACK_SUFFIXES:
                files.append(
                    ScannedFile(rel, entry.name, int(info.st_size), int(info.st_mtime_ns))
                )
            else:
                other_file_count += 1

    walk("", root_path)
    return ScanResult(
        root=str(root_path),
        files=tuple(files),
        symlinks_skipped=tuple(symlinks_skipped),
        other_file_count=other_file_count,
        directory_count=directory_count,
        dir_entries={k: tuple(v) for k, v in dir_entries.items()},
    )


def fingerprint_files(result: ScanResult) -> dict[str, tuple[int, int]]:
    """Map rel_path -> (size, mtime_ns); used to prove a preview touched nothing."""
    return {f.rel_path: (f.size, f.mtime_ns) for f in result.files}
