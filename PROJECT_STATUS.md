# MusicSyncRename — Project Status

## Current milestone
Mission 02A COMPLETE: preview engine repaired and verified — `build_preview()` handles invalid overrides, empty-stem proposals and malformed files; ambiguity/collision detection (incl. Unicode casefold) is correct; previews are proven read-only and deterministic; `plan_moves()` chain/swap/cycle planning had two demonstrated non-root data-loss defects fixed and is now verified by executing planned steps against real tempdir trees. Full suite: 65/65 OK, run twice consecutively (synthetic fixtures only). `apply_changes`/`undo_session` remain known-broken mid-rewrite drafts — UNCHANGED this mission; that rewrite is Mission 02B scope and nothing in them should be trusted. Next: Mission 02B per handoffs/QWEN_TO_FORGE.md.

## Ownership and branch
- Qwen executed the current shift on `qwen/music-cleanup` under explicit coordinator assignment (the previous checkpoint named Forge as next owner; that instruction is superseded for this mission only).
- Neutral remote: `handoff` (/home/reason/Temporary/AgentHandoff/MusicSyncRename.git).

## Exact state at this checkpoint (Mission 02A)
- Started from verified checkpoint SHA `67cf65857332f2aba3a63f9969d23bc9806bf7f8` on `qwen/music-cleanup` (local HEAD == remote branch, clean tree).
- Changed files in this mission:
  - `musicsyncrename/engine.py` — PREVIEW PATH REPAIRED AND TESTED (apply/undo sections untouched):
    - `plan_moves()` TWO DEMONSTRATED DEFECTS FIXED: (1) holder tracking compared full rel-path keys against bare filename keys, so in any non-root directory dependency ordering was silently disabled and executing a plan could overwrite another content's slot; both sides now compare `Path(...).name` filename keys. (2) cycle-break temp moves stored the temp name without its parent dir, pointing the final rename at a nonexistent path; they now store the full rel path via `_join(parent, tmp)`.
    - `build_preview()`: caller-invalid overrides (e.g. empty override name — previously raised ValueError and CRASHED THE WHOLE SCAN) are now per-item `status="error"` + reason code `invalid_override`; new `_guard_empty_stem()` downgrades proposals whose stem is entirely extension/junk (naming emits `.mp3`) to `ambiguous`, `proposed_name=None`, flag `empty_stem`; rel_dir grouping simplified.
    - `_name_safety_flags()`: `/` and `\\` added to unsafe chars so caller-controlled OST hints containing path separators are flagged at preview time.
  - `tests/fixtures.py` — `make_png_1x1()` scanline corrected from 4 bytes (filter byte + only 3 pixel bytes) to the proper 5-byte line (filter 0x00 + RGBA opaque red). It stayed undetected because mutagen stores APIC data opaquely.
  - `tests/test_preview_engine.py` — NEW, 23 tests: planner execution harness executing returned steps on real tempdirs with per-content marker payloads (root AND non-root chain/swap/3-cycle/mixed; no-op + case-variant filter; duplicate normalized target → EngineError); preview status matrix on an 11-track synthetic tree; both collision kinds with exact involved lists incl. NFD-tag vs NFC-live-file and case-insensitive live occupancy; malformed file → `error`/`parse_error` without crash; empty-stem rejection (filename + override paths); empty-override crash guard; safety flags (`name_too_long`, slash in hints); determinism via full dataclass equality of two previews; read-only proof via byte+mtime_ns snapshot plus no `.musicsyncrename` created; 5-byte PNG scanline validation + APIC roundtrip.
- UNCHANGED: `musicsyncrename/__init__.py` (engine still NOT part of the public package surface — boundary test in `tests/test_imports.py` stays green), all Mission 01 helper modules and their tests, engine apply/undo sections.

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

## Verification evidence (Mission 02A)
- Command (run from project root): `python3 -m unittest discover -s tests` → **Ran 65 tests, OK**, run twice consecutively for stability. Pre-patch demonstration runs recorded in session: non-root swap planned as `[sub/a→sub/b, sub/b→sub/a]` with NO temp step (execution would overwrite content B); PNG IDAT payload decoded to 4 bytes instead of the required 5; junk-stem file previewed as `status='ok', proposed_name='.mp3'`.
- Coverage added this mission: planner execution harness (root + subdirectory chain/2-cycle/3-cycle/mixed, no-op and case-insensitive filters, duplicate normalized target → EngineError); preview status matrix on an 11-track synthetic tree; both collision kinds with NFD/NFC Unicode casefold and case-insensitive live occupancy; malformed-file handling without crashing the scan; empty-stem rejection (filename + override paths); empty-override crash guard; safety flags (`name_too_long`, `name_contains_unsafe_chars` incl. `/` in OST hints); determinism via full dataclass equality of two previews; read-only proof via byte+mtime_ns snapshot and absence of `.musicsyncrename`; 5-byte PNG scanline validation (chunk CRC + IHDR) with APIC roundtrip.
- Engine-dependent matrix items still outstanding for Mission 02B: apply/undo roundtrip, changed-since-preview, cancellation/partial failure, live-file collision reporting at APPLY level (handoff test-matrix items exercised through the journal), concurrency guard.

## Verification evidence (Mission 01)
- Command (run from project root): `python3 -m unittest discover -s tests -v` → **Ran 42 tests, OK** (no failures, no errors; zero warnings after file-handle hygiene fix in tests).
- Coverage of mission acceptance criteria: module imports incl. engine-absence boundary; deterministic filename normalization + `name_key` collision semantics; junk removal from historical-map conventions with preservation of genuine descriptors ("(Remastered)", "(Game Version)"); ambiguous handling (multiple_separators, tags-cleaned-to-empty, conflicting multi-value flags); safe scan + symlink exclusion (file and dir symlinks recorded in `symlinks_skipped`, never traversed, deterministic ordering, non-MP3 counted); ID3 read snapshot; restricted tag editing (TIT2/TPE1 only — other frames refused with ValueError; delete via None); preservation of artwork bytes (APIC data byte-equal), RVRB, TXXX:REPLAYGAIN_* (text intact) and audio region (`audio_part` first-`\xff\xfb` comparison) after tag edits.
- Engine-dependent matrix items (apply/undo roundtrip, collisions, cycles/chains, changed-since-preview, cancellation/partial failure, live-file collision reporting — handoff test matrix items 1, 5–11 at the engine level) remain for Mission 02.

## Observations carried to Mission 02 (status updated in 02A)
- mutagen 1.47: sequential `ID3.add(TPE1(...))` calls are LAST-WRITE-WINS (the second add replaces, not appends). The on-disk form of conflicting multi-values is ONE frame with `.text` as a list; that list survives save+reload, and `_frame_texts`/TagSnapshot conflict detection works off it.
- `naming.py` branch `one_side_empty_after_cleanup` is defensive/unreachable with the current cleaning regex set (any recognized junk on one side of a single separator is removed by whole-stem cleaning first or leaves both sides non-empty). Not a defect; noted so Mission 02 does not chase it.
- Degenerate edge: a filename whose ENTIRE stem is recognized junk (e.g. `(Official HD Video).mp3`) gets proposal `.mp3` from the preserved naming code — **RESOLVED in Mission 02A**: `_guard_empty_stem` downgrades such proposals to `ambiguous` + `empty_stem` flag at preview time; naming.py unchanged.
- Malformed-file handling verified only at module level: `read_tag_snapshot`/`apply_tag_edits` raise `ParseError` for non-MP3 bytes — **engine-level wrapping DONE in Mission 02A**: ParseError items get status "error"/reason `parse_error`; invalid caller overrides get "error"/`invalid_override`; neither crashes the scan.

## Environment facts (verified this session + Mission 0)
- Python 3.14.8, mutagen 1.47.0 system-installed. **pytest NOT installed** — use `unittest` (`python3 -m unittest discover -s tests -v`).
- Synthetic silent-MP3 fixtures readable/writable by mutagen; TPE1/TIT2/TALB/RVRB/APIC/TXXX survive save+resave; audio region preserved (first-`\xff\xfb` comparison). APIC reload keys normalize to bare `"APIC:"`; `TXXX:<desc>` lookup keys; `TXXX(..., text=...)` not `value=`; no `MP3.close()`; `del tags["TIT2"]` works.

## Observations carried to Mission 02B
- `plan_moves()` contract now verified and safe for apply/undo: same-directory ops with FULL rel paths, filename-key collision detection (`name_key` on `Path(...).name`), cycles broken by exactly one `.tmp-musicsync-rename-<hex>` temp step (kind "temp"). Note: in ROOT-directory cycles the temp step's rel paths carry a `./` prefix (`Path("a.mp3").parent == Path(".")`) — harmless for `os.rename`/`Path` and covered by tests, but normalize it if journal string-matching ever trips on it.
- TEST CONVENTION (do not break): `tests/test_preview_engine.py` imports `musicsyncrename.engine` LAZILY inside test bodies and its filename sorts alphabetically AFTER `test_imports.py`. This keeps the Mission 01 boundary assertion (`'engine'` attribute absent from the package in the shared unittest process) green. Any future engine-level test file must follow both rules (lazy import + name sorting after test_imports.py, e.g. a `z` prefix or explicit ordering awareness).
- Apply/undo rewrite inputs: preview items already carry everything apply needs — status gate (`ok|no_change` approvable; `ambiguous|error` rejected via the documented stable codes), exact `tag_edits` tuples (TIT2/TPE1 single-value changes only), size+mtime_ns snapshots for `changed_since_preview`, and per-directory grouping available from `ItemPlan.rel_dir`. The apply draft's journal/backup/validation scaffolding is contradictory mid-rewrite code; treat design notes in handoffs/QWEN_TO_FORGE.md as the source of truth, not that code.

## Not done / must not be assumed
- `engine.py` is PARTIALLY tested: the preview path (`build_preview`, `_detect_collisions`, `_guard_empty_stem`, `_tag_edits_for`, `_name_safety_flags`, `plan_moves`) is verified by Mission 02A. The apply/undo sections remain a contradictory mid-rewrite draft — never exercised, do not trust any part of them.
- Nothing deployed; no real library, phone, live MusicSync installation, or historical backup touched. All test I/O is synthetic in tempdirs.

## Next action (Mission 02B — per handoffs/QWEN_TO_FORGE.md)
1. ~~Rewrite `engine.py` apply/undo/build_preview/list_sessions~~ — **DONE in Mission 02A** for `build_preview` + verified `plan_moves` core with direct unit tests (chain/cycle/duplicate-target, executed against real tempdirs) and the empty-stem guard. Remaining: implement `apply_changes`, `undo_session`, `list_sessions` per the recorded design notes (journal events + fsync, backups before mutation, stable rejection codes, stop-on-first-failure with undoable session id), reusing the now-verified `plan_moves`.
2. Add engine-level test matrix items 1, 5–11 (apply/undo level: roundtrip byte-exactness, changed-since-preview, cancellation/partial failure via cancel_check seam, live-file collision reporting) on top of the current 65-test suite (`tests/fixtures.py` ready to reuse; PNG fixture now valid).
3. Write `docs/USAGE.md`, update status/handoff, checkpoint commit + push with full-SHA report.

## References
- /home/reason/Temporary/AgentHandoff/MusicSyncRename-references/REFERENCE_MANIFEST.md
- MusicSync v0.1.3 snapshot (read-only): backend/{android_names,filesystem,replaygain}.py style/safety conventions (no symlink traversal, "preview again" on stale state, deterministic collision handling).
- `.scratch_probe.py` — intermediate probe prototype preserved for reference; `tests/fixtures.py` is the tested successor.
