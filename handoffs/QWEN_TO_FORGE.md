# Qwen → Forge: MusicSyncRename Phase 1 checkpoint (implementation in progress)

Date: 2026-10-15 (local). Branch: `qwen/music-cleanup`. Incoming SHA at start of work:
`39a29ed9d34c851fa29bf83de525cda5e3e61376`.

This is a **mid-implementation checkpoint, not a completed feature**. All five
engine modules exist on disk; none of them has been exercised by tests. Do NOT
claim any runtime behavior works until the test suite exists and passes.

## What was implemented (source state in this commit)

| File | State |
|---|---|
| `musicsyncrename/__init__.py` | **MISSING — never created.** The initial write attempt failed with ENOENT before the package directory existed and was not retried. The package cannot be imported until this file is written (intended public surface: cleaning helpers, scanner entry points, TagSnapshot/tags functions, naming API incl. `Override`, engine API: `build_preview`, `apply_changes`, `undo_session`, `list_sessions`, plus re-export of `make_ost_name`/`propose_override`). |
| `musicsyncrename/cleaning.py` | Complete per design, untested. NFC normalization (`normalized_nfc` reason), zero-width stripping, broken-punctuation map (fullwidth colon/quotes/parens etc.), anchored paren-junk patterns ("Official HD Video", "(HQ…)", "[Lyrics]", "(1080p …)", "audio NNN kbps" variants), trailing junk suffixes (" - Lyrics", "Lyric Video", "audio 320 kbps original"), leading track-number removal (filename context only via `clean_filename_stem`), quote-unwrap, whitespace finalize. Every step reported as `Reason(code, detail)`. Design rule: fullwidth bar `｜` is deliberately NOT a separator (files shaped "Game｜DLC｜Track" must stay ambiguous). |
| `musicsyncrename/scanner.py` | Complete per design, untested. Non-recursive-symlink-safe walk (`follow_symlinks=False`, symlinks recorded in `symlinks_skipped`), deterministic ordering, MP3-only track items with (size, mtime_ns) snapshot, `dir_entries: dict[rel_dir -> tuple[names]]` for collision detection. |
| `musicsyncrename/tags.py` | Complete per design, untested as a module. `read_tag_snapshot()` (TPE1→artists with TPE2 fallback, TIT2→titles, TALB album, ReplayGain key detection `RVRB`/`TXXX:REPLAYGAIN*`, APIC count) and `apply_tag_edits(path, {frame: value})` restricted to TIT2/TPE1 (refuses other frames). API shape against mutagen 1.47 was verified by probe runs (below); the module code itself was never imported/executed in tests. |
| `musicsyncrename/naming.py` | Complete per design, untested. Entry point `propose_name(scanned, tags: TagSnapshot, override=None)` — NOTE contract: caller passes a TagSnapshot even when tags are absent (`has_tags=False`); ParseError handling belongs to the engine (status "error"), NOT naming. Paths: reliable TPE1+TIT2 → `Artist - Title.mp3`; else filename-derived with single/zero/multi separator analysis; multiple separators or one-side-empty-after-cleanup → status `ambiguous` with reason codes (`multiple_separators`, `one_side_empty_after_cleanup`, `conflicting_*_values`, `missing_or_empty_*_tag`). Overrides win but are revalidated downstream. `make_ost_name(game, track)` for the explicit `Game OST - Track.mp3` convention; OST hints only ever produce a non-blocking `ost_candidate` flag otherwise (historical map proves auto-reordering OST names is human judgment, not determinism). |
| `musicsyncrename/engine.py` | **BROKEN DRAFT — do not trust any part of it.** It contains a plausible-but-unverified `plan_moves()` core plus heavily contradictory fragments in `build_preview`, `apply_changes`, and `undo_session` (duplicate/conflicting bookkeeping, dead lines referencing `anomalies[0][0]`, inconsistent report fields). It needs a full rewrite of the apply/undo sections. See design notes below so it is not re-derived from scratch. |
| `.scratch_probe.py` | **Useful but INTERMEDIATE** probe (committed here on purpose): working synthetic silent-MP3 builder (`0xFF 0xFB 0x90 0xC0` header + zero-fill, 417 bytes/frame = MPEG-1 Layer III 128 kbps/44.1 kHz mono) and the `audio_part()` first-`\xff\xfb` comparison helper; it demonstrates the FAILING TXXX case (`value=` kwarg → empty text). The final SUCCESSFUL roundtrip code (PNG builder, `text=` TXXX usage) was executed via stdin during this session and is NOT saved on disk. Reimplement those parts in `tests/fixtures.py` using the verified API facts listed below. |

No tests exist yet. No `docs/USAGE.md` was written. Nothing has been run against
any real music library; no file outside this workspace was touched.

## Environment facts (verified this session)

- Python 3.14.8, mutagen 1.47.0 system-installed. **pytest is NOT installed** — use `unittest` (`python3 -m unittest discover -s tests -v`).
- Synthetic MP3s work: files built from the probe's silent frames open in mutagen with valid length; tag write/read/re-write cycles preserve TPE1/TIT2/TALB, RVRB, APIC (data byte-equal), and TXXX frames.
- Audio-byte preservation check that works: compare file bytes starting at the first `b"\xff\xfb"` search hit at offset ≥ 10 (probe printed "audio preserved: True" for a save+resave). Do NOT rely on ID3 header size-field arithmetic for this — one probe iteration got the strip offset wrong.

## mutagen 1.47 pitfalls discovered by probes (verified)

- `TXXX` constructor takes **`text=`**, not `value=`; with `value=` the frame is created with empty text and silently drops out after save/reload.
- TXXX lookup key format is `"TXXX:<desc>"` (e.g. `tags.getall("TXXX:REPLAYGAIN_TRACK_GAIN")`), NOT `"TXXX:desc=..."`.
- APIC keys on reload are normalized to bare `"APIC:"` regardless of mime/type suffix; match by prefix when iterating.
- `MP3` objects have **no `.close()`** in 1.47 — do not call it. Frame deletion via `del tags["TIT2"]` works.

## Design decisions already made (recorded so the rewrite is mechanical, not research)

Preview model:
- `ItemPlan(rel_path, current_name, size, mtime_ns, status, proposed_name, reasons, flags, tag_edits)`; statuses `ok | no_change | ambiguous | error`. `tag_edits` = tuple of `(frame, old, new)` limited to TIT2/TPE1 single-value frames where cleaning actually changes text.
- Collisions computed per directory with key = NFKC+casefold (`cleaning.name_key`). Kinds: `proposed_vs_proposed`, `proposed_vs_live_file` (honest conservative report — approval is unknown at preview time; do NOT try to predict which occupant will be renamed away).
- Previews are read-only by construction and must remain timestamp-free/deterministic for same library state.

Apply model:
- Only rel_paths explicitly in `approved` run. Rejection codes (keep stable): `not_in_preview`, `nothing_to_do`, `status_ambiguous_not_applicable`, `parent_missing`, `parent_not_plain_dir`, `source_missing`, `is_symlink`, `not_regular_file`, `changed_since_preview` (size+mtime_ns vs preview snapshot), `unsafe_name_chars` (NUL//\, leading-control; "." and ".." rejected), `name_too_long` (>255 UTF-8 bytes), `proposal_collision` (two batch items same target key in one dir), `target_exists` (live occupant not freed by another approved item in the same dir), `planning_failed`.
- Journal: `<root>/.musicsyncrename/sessions/<hex>.jsonl`, JSON-lines, **fsync after every append**, event types `header/op/done/closed|aborted`; backups at `.musicsyncrename/backups/<session_id>/<sha1(rel_path)>.mp3` = full-file copy (superset of "original ID3 tags" requirement), made **before any mutation**, only for contents with tag edits.
- Rename mechanics: same-dir `os.rename` only; per-directory plan via `plan_moves(ops)` where ops map identity → (from_rel, to_rel); chains execute dependency-first; cycles broken by temp names `.tmp-musicsync-rename-<hex>` (kind "temp"); EngineError when two contents target the same collision key. Stop-on-first-failure; partial state must always be undoable via the returned session id. Add `ApplyReport.session_id, applied[(rel,new_name|None)], rejected[(rel,code)], partial[(rel,code)], canceled[rel]`.
- Concurrency guard worth adding: refuse a new apply while any session is not in terminal state (`closed`/`undone`) — check via list_sessions; optionally an O_EXCL lock file under `.musicsyncrename/`.

Undo model:
- Rebuild per-content op chains from journal; "done" marks the latest pending op for that content. Current position = replay done ops; for an interrupted op probe live FS (at `to` → moved, at `from` → not yet, neither → anomaly `missing_after_interrupted_op`).
- Two phases: validate everything first (lstat current regular non-symlink; original slot free or freed by another undo move in same dir batch — else anomalies, NO changes); then execute per-directory undo plan through the SAME planner (undo of a swap is itself a cycle), appending `undo_begin/undo_op/undo_done` events; finally byte-restore from backup via tmp+`os.replace` only when bytes differ (idempotent for never-edited files); close with `undone`. Backups and journals are preserved after undo (audit).
- Undo must handle: completed sessions, canceled sessions, crash-interrupted sessions.

Test matrix to write (mandated; synthetic fixtures in tempdirs only):
1. Normal deterministic rename from clean tags → proposed name + apply/undo roundtrip byte-exact.
2. Junk removal cases from the historical map conventions: "(Official HD Video)", "- Lyrics", "[Lyrics]", "audio 320 kbps original", leading "6." numbering, fullwidth `：` colon — assert cleaned forms; preserve genuine descriptors ("(Remastered)", "(Game Version)", "(NFS … Edition)") untouched.
3. Ambiguous: no tags + no separator; conflicting TIT2/TPE1 multi-values; multiple separators → status ambiguous, NO proposal, not approvable.
4. Malformed/no-tag file (e.g. random bytes .mp3) → engine status "error", excluded from apply.
5. Unicode: NFD vs NFC filenames collide in preview (`proposed_vs_live_file`); fullwidth punctuation normalized; proposed names written as NFC.
6. Collisions: case-insensitive duplicate proposals rejected both; proposal onto live file rejected unless occupant is another approved item being renamed away (then it must succeed via chain ordering).
7. Filename cycles: A↔B swap and a 3-cycle apply correctly with temp-name planning; undo restores exactly.
8. Chain: A→B, B→C executes in dependency order without overwrite.
9. Changed source between preview and apply → that item rejected `changed_since_preview`, independent items still applied.
10. Cancellation/partial failure via the `cancel_check` hook (or fault injection seam) → partial state journaled; undo restores original names AND bytes exactly.
11. Artwork/ReplayGain preservation: APIC data byte-equal, RVRB and TXXX REPLAYGAIN frames intact after a tag-edit apply; audio region (first-`\xff\xfb` scan) identical before/after for every applied file.

Reference material: `/home/reason/Temporary/AgentHandoff/MusicSyncRename-references/rename-map-2026-10-06.tsv`
(154 rows) is convention/junk-vocabulary reference ONLY — never a source of song identities, never an input to renaming.

## Next actions for the next engineer (smallest first)

1. Create the missing `musicsyncrename/__init__.py` (see table above for intended exports).
2. Rewrite `engine.py`: keep/verify the `plan_moves()` core (untested — add direct unit tests for chain/cycle/duplicate-target), then implement clean `build_preview`, `apply_changes`, `undo_session`, `list_sessions` per the design above. The current engine.py file is a broken draft; deleting/replacing its apply+undo sections is expected work, not "fixing what was verified".
3. Build `tests/fixtures.py`: reuse the MP3 builder and `audio_part()` helper from `.scratch_probe.py`, re-implement a small PNG generator (zlib+struct, 1x1 RGBA) and TXXX fixtures using `text=` per the verified API facts above, then write the test matrix with `unittest`.
4. Run `python3 -m unittest discover -s tests -v`; iterate until green. Only then is anything "verified".
5. Write `docs/USAGE.md` (scan → propose → approve → apply → undo code samples, no-default-mutation statement) and update PROJECT_STATUS.md; checkpoint commit + push to handoff remote with full-SHA report.

## Unresolved / honest status

- No test has ever run against any of the five modules.
- `engine.py` is knowingly broken (mid-rewrite draft). The package cannot be imported: `musicsyncrename/__init__.py` was never created (first write attempt failed ENOENT and was not retried).
- Nothing deployed anywhere; live library untouched; historical backups untouched.
