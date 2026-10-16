"""Vendored MusicSyncRename engine, integrated for the Settings Bulk Rename feature.

Provenance: byte-identical copy of the Qwen-owned ``musicsyncrename`` package at
checkpoint SHA 802317530c8a2e62e289db27ebf150c95392974d (branch qwen/music-cleanup,
remote handoff), where the complete preview/apply/undo suite passed: 89 tests OK.

- ``cleaning``, ``scanner``, ``tags``, ``naming`` — verified Mission 01 helpers.
- ``engine`` — verified Mission 02A/02B read-only preview, journaled apply and
  byte-exact undo (backups + fsync'd JSON-lines journals, collision protection).

The modules keep their original relative imports; the package was renamed from
``musicsyncrename`` to ``musicsync.vendored`` so the AppImage bundles it with no
cross-workspace imports. Do not edit vendored code in place: fix upstream and re-verify,
then re-copy.
"""

from musicsync.vendored.cleaning import (  # noqa: F401
    MAX_NAME_BYTES,
    CleanedText,
    Reason,
    clean_filename_stem,
    clean_text,
    name_key,
    normalize_text,
)
from musicsync.vendored.scanner import ScannedFile, ScanResult, scan_root  # noqa: F401
from musicsync.vendored.tags import ParseError, TagSnapshot  # noqa: F401
