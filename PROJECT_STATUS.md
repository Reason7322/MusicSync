# MusicSyncRename — Project Status

## Current milestone
Phase 1: standalone offline MP3 filename/metadata cleanup engine (scan → deterministic preview → explicit approve → journaled apply → safe undo), testable with synthetic fixtures only. GUI integration is Phase 2, not started and not assigned to this checkpoint.

## Ownership and branch
- Current owner after this checkpoint: Forge (Qwen handed off).
- Working branch: `qwen/music-cleanup` in /home/reason/Temporary/QwenProjects/MusicSyncRename/.
- Neutral remote: `handoff` (/home/reason/Temporary/AgentHandoff/MusicSyncRename.git).

## Exact state at this checkpoint
- Qwen started from handoff SHA 39a29ed9d34c851fa29bf83de525cda5e3e61376 (verified local HEAD == remote branch before work began).
- Implementation committed in this checkpoint: `musicsyncrename/{cleaning,scanner,tags,naming}.py` drafted per design; **`engine.py` is a known-broken mid-rewrite draft**; **`__init__.py` was never created** (first write failed ENOENT, not retried) so the package cannot be imported. `.scratch_probe.py` preserved as an INTERMEDIATE mutagen probe prototype (working silent-MP3 builder; final successful roundtrip code was run via stdin and is NOT on disk). See handoffs/QWEN_TO_FORGE.md for module-by-module state and the recorded apply/undo/planner design.
- No tests exist yet. No test has been run against any module. Nothing deployed; no real library, phone, or historical backup touched.

## Verified this session (probe runs only — not feature validation)
- Python 3.14.8 + mutagen 1.47.0: synthetic silent-MP3 fixtures readable/writable by mutagen; TPE1/TIT2/TALB/RVRB/APIC/TXXX survive save+resave; audio region preserved (verified by first-`\xff\xfb` byte comparison).
- mutagen 1.47 API facts: `TXXX(..., text=...)` (not `value=`); key format `TXXX:<desc>`; APIC reload keys normalize to bare `"APIC:"`; no `MP3.close()`; `del tags["TIT2"]` works.
- Historical rename map analyzed for naming conventions and junk vocabulary only (never as song identities).

## Not done / must not be assumed
- Engine does NOT work: no module has ever been executed in a test; package import fails (missing `__init__.py`); `engine.py` is a knowingly broken draft.
- No pytest available; tests must use `unittest`.

## Next action (for Forge)
Read handoffs/QWEN_TO_FORGE.md, then execute its "Next actions" list in order: create the missing `__init__.py`, rewrite engine.py apply/undo per the recorded design (plan_moves core salvageable but untested), build tests/fixtures.py from .scratch_probe.py plus re-implemented PNG/TXXX helpers, write and run the mandated unittest matrix, then document usage in docs/USAGE.md.

## References
- /home/reason/Temporary/AgentHandoff/MusicSyncRename-references/REFERENCE_MANIFEST.md
- MusicSync v0.1.3 snapshot (read-only): backend/{android_names,filesystem,replaygain}.py style/safety patterns are the house conventions (no symlink traversal, "preview again" on stale state, deterministic collision handling).
