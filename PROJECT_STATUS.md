# MusicSyncRename — Project Status

## Current milestone
Mission 01 COMPLETE: foundation restored and verified — helper modules import through the package and pass a focused 42-test unittest suite (synthetic fixtures only). `engine.py` remains a known-broken mid-rewrite draft (unchanged this mission; rewriting it is explicitly out of Mission 01 scope). Next: Mission 02 per handoffs/QWEN_TO_FORGE.md "Next actions".

## Ownership and branch
- Qwen executed the current shift on `qwen/music-cleanup` under explicit coordinator assignment (the previous checkpoint named Forge as next owner; that instruction is superseded for this mission only).
- Neutral remote: `handoff` (/home/reason/Temporary/AgentHandoff/MusicSyncRename.git).

## Exact state at this checkpoint (Mission 01)
- Started from verified checkpoint SHA `3203400d92e6806a62b0bacd106c85f42de0750c` on `qwen/music-cleanup` (local HEAD == remote branch, clean tree).
- Changed files in this mission:
  - `musicsyncrename/__init__.py` — CREATED. Re-exports the valid public surface of cleaning/scanner/tags/naming (incl. `propose_override`). Deliberately does NOT import/export `engine` (known-broken draft; must not make package import depend on it).
  - `musicsyncrename/tags.py` — SYNTAX FIXED: orphaned `try:` in `apply_tag_edits` (opened a block with no except/finally → SyntaxError at line 164) removed and its body dedented. Behavior unchanged; exceptions during save propagate as before.
  - `musicsyncrename/naming.py` — TWO DEMONSTRATED DEFECTS FIXED (targeted edits, no redesign):
    1. `_reason("from_tags", ...)` used bare instead of a singleton tuple → `TypeError: Reason + tuple` on EVERY tag-based proposal. Now `(_reason(...),)`.
    2. `tuple(flags + (_reason(...),))` in both ambiguous returns (flags is a list) → `TypeError: can only concatenate list (not "tuple") to list`. Now `tuple((*flags, _reason(...)))`.
  - `musicsyncrename/scanner.py` — ONE DEMONSTRATED DEFECT FIXED: `walk()` increments `directory_count` without declaring it nonlocal → `UnboundLocalError` on entry into ANY subdirectory. Fixed with one added nonlocal name.
  - `tests/` — CREATED: `fixtures.py` (silent-MP3 builder + `audio_part` from `.scratch_probe.py`; 1x1 PNG generator; tag helpers using verified mutagen facts) and 42 tests in `test_imports.py`, `test_cleaning.py`, `test_scanner.py`, `test_naming.py`, `test_tags.py`.
- UNCHANGED: `musicsyncrename/engine.py` (still broken draft — do not trust any part; see handoff design notes), `.scratch_probe.py`, cleaning logic in `cleaning.py` (passed all tests unmodified).

## Verification evidence (Mission 01)
- Command (run from project root): `python3 -m unittest discover -s tests -v` → **Ran 42 tests, OK** (no failures, no errors; zero warnings after file-handle hygiene fix in tests).
- Coverage of mission acceptance criteria: module imports incl. engine-absence boundary; deterministic filename normalization + `name_key` collision semantics; junk removal from historical-map conventions with preservation of genuine descriptors ("(Remastered)", "(Game Version)"); ambiguous handling (multiple_separators, tags-cleaned-to-empty, conflicting multi-value flags); safe scan + symlink exclusion (file and dir symlinks recorded in `symlinks_skipped`, never traversed, deterministic ordering, non-MP3 counted); ID3 read snapshot; restricted tag editing (TIT2/TPE1 only — other frames refused with ValueError; delete via None); preservation of artwork bytes (APIC data byte-equal), RVRB, TXXX:REPLAYGAIN_* (text intact) and audio region (`audio_part` first-`\xff\xfb` comparison) after tag edits.
- Engine-dependent matrix items (apply/undo roundtrip, collisions, cycles/chains, changed-since-preview, cancellation/partial failure, live-file collision reporting — handoff test matrix items 1, 5–11 at the engine level) remain for Mission 02.

## Observations carried to Mission 02
- mutagen 1.47: sequential `ID3.add(TPE1(...))` calls are LAST-WRITE-WINS (the second add replaces, not appends). The on-disk form of conflicting multi-values is ONE frame with `.text` as a list; that list survives save+reload, and `_frame_texts`/TagSnapshot conflict detection works off it.
- `naming.py` branch `one_side_empty_after_cleanup` is defensive/unreachable with the current cleaning regex set (any recognized junk on one side of a single separator is removed by whole-stem cleaning first or leaves both sides non-empty). Not a defect; noted so Mission 02 does not chase it.
- Degenerate edge: a filename whose ENTIRE stem is recognized junk (e.g. `(Official HD Video).mp3`) gets proposal `.mp3` from the preserved naming code (verified observation, no code change this mission). The engine SHOULD reject/flag empty-stem proposals at preview time — add to Mission 02 scope.
- Malformed-file handling verified only at module level: `read_tag_snapshot`/`apply_tag_edits` raise `ParseError` for non-MP3 bytes (engine-level "error" status wrapping is Mission 02).

## Environment facts (verified this session + Mission 0)
- Python 3.14.8, mutagen 1.47.0 system-installed. **pytest NOT installed** — use `unittest` (`python3 -m unittest discover -s tests -v`).
- Synthetic silent-MP3 fixtures readable/writable by mutagen; TPE1/TIT2/TALB/RVRB/APIC/TXXX survive save+resave; audio region preserved (first-`\xff\xfb` comparison). APIC reload keys normalize to bare `"APIC:"`; `TXXX:<desc>` lookup keys; `TXXX(..., text=...)` not `value=`; no `MP3.close()`; `del tags["TIT2"]` works.

## Not done / must not be assumed
- `engine.py` does NOT work: never exercised by tests; apply/undo sections are a contradictory mid-rewrite draft (parses, but do not trust). No preview/apply/undo behavior exists yet.
- Nothing deployed; no real library, phone, live MusicSync installation, or historical backup touched. All test I/O is synthetic in tempdirs.

## Next action (Mission 02 — per handoffs/QWEN_TO_FORGE.md)
1. Rewrite `engine.py` apply/undo/build_preview/list_sessions per the recorded design in the handoff (keep/verify `plan_moves()` core; add direct unit tests for chain/cycle/duplicate-target). Include empty-stem proposal guard (see observations above).
2. Add engine-level test matrix items 1, 5–11 on top of the existing 42-test suite (`tests/fixtures.py` is ready to reuse; add cancel/fault-injection seams as designed).
3. Write `docs/USAGE.md`, update status/handoff, checkpoint commit + push with full-SHA report.

## References
- /home/reason/Temporary/AgentHandoff/MusicSyncRename-references/REFERENCE_MANIFEST.md
- MusicSync v0.1.3 snapshot (read-only): backend/{android_names,filesystem,replaygain}.py style/safety conventions (no symlink traversal, "preview again" on stale state, deterministic collision handling).
- `.scratch_probe.py` — intermediate probe prototype preserved for reference; `tests/fixtures.py` is the tested successor.
