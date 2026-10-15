"""MusicSyncRename — Phase 1 offline MP3 filename/metadata cleanup helpers.

Re-exports the valid public surface of the helper modules so callers can use a
single import::

    from musicsyncrename import scan_root, read_tag_snapshot, propose_name

NOTE (deliberate): ``musicsyncrename.engine`` is NOT imported or exported here.
It is a known-broken mid-rewrite draft (see PROJECT_STATUS.md); it will be
added to the public surface only once its apply/undo implementation passes the
focused test suite. Importing this package never executes engine code.
"""

from musicsyncrename.cleaning import (
    MAX_NAME_BYTES,
    CleanedText,
    Reason,
    clean_filename_stem,
    clean_text,
    name_key,
    normalize_text,
)
from musicsyncrename.scanner import ScannedFile, ScanResult, scan_root
from musicsyncrename.tags import ParseError, TagSnapshot, apply_tag_edits, read_tag_snapshot
from musicsyncrename.naming import (
    OST_SUFFIX,
    NameProposal,
    Override,
    make_ost_name,
    propose_name,
    propose_override,  # present in naming.py; part of documented public surface
)

__all__ = [
    # cleaning
    "MAX_NAME_BYTES",
    "CleanedText",
    "Reason",
    "clean_filename_stem",
    "clean_text",
    "name_key",
    "normalize_text",
    # scanner
    "ScannedFile",
    "ScanResult",
    "scan_root",
    # tags
    "ParseError",
    "TagSnapshot",
    "apply_tag_edits",
    "read_tag_snapshot",
    # naming
    "OST_SUFFIX",
    "NameProposal",
    "Override",
    "make_ost_name",
    "propose_name",
    "propose_override",
]
