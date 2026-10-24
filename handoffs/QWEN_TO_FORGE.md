# Handoff — Mission 22 COMPLETE: all six Rename Preview table columns manually resizable; focused + targeted regression tests green (19/19 individually)

From: Qwen (Mission 22, 2026-10-23) · To: next engineer on the same branch (Forge/Codex or Qwen continuation).
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remotes: handoff + github.
Incoming base verified at shift start ONCE: local HEAD == handoff SHA == github SHA == `250f5f9bc772fd1309b21582457069446afc16bf` (Mission 21 checkpoint), clean tree, no untransferred WIP. Full detail: PROJECT_STATUS.md → "Continuation record — Mission 22".

## ORIGINAL PRODUCT GOAL (unchanged)
MusicSync 0.2.0 with integrated Settings → Bulk Rename → Preview → Select → Apply → Sessions → byte-exact Undo; safe manual filename/ID3 editing; preserved KDE Connect sync, ReplayGain and recovery-data protection; verified standalone AppImage on synthetic MP3s; Fedora 44 RPM; final release artifacts with provenance. **PRODUCT STATUS: INCOMPLETE.** Live install only under separate authorization.

## What this checkpoint delivered
Source + focused tests ONLY (geometry-only change):
- `src/musicsync/bulk_rename.py` — `_make_item_table()` now sets ALL SIX Rename Preview columns to `QHeaderView.ResizeMode.Interactive` (was `[RTC, RTC, Stretch, Stretch, RTC, Interactive]`), with useful initial widths: Apply 60 / Path 180 / Current name 200 / Proposed name 200 / Status 110 / Details 240 — same contract as the accepted Mission 20 Sessions table. Horizontal scroll (`ScrollBarAsNeeded`, unchanged default) covers overflow.
- NO changes to: column labels, `_fill_items()` content, checkbox/Approve flags, selection behavior, no-edit triggers, Apply/Preview/Sessions/Undo/journal logic; Mission 20's `_make_session_table()` untouched.
- `tests/test_bulk_rename.py` — `SessionTablePresentationTests.test_session_table_columns_are_interactively_resizable_and_preview_untouched` renamed **`test_session_and_preview_tables_are_interactively_resizable`**; Sessions half unchanged; Preview half now asserts: six labels intact, all six Interactive, no column unreasonably narrow at start, per-column resize round-trip `[84, 230, 160, 300, 70, 420]` sticks independently on each of the six columns, `horizontalScrollBarPolicy() == ScrollBarAsNeeded`.

## Actual results this shift (exact commands → outcomes)
- Focused: renamed column test **PASS** first run after edit (fresh offscreen process, 0.049 s).
- Targeted regression batch #2 — all directly relevant tests, each in its own fresh offscreen process with `PYTHONFAULTHANDLER=1`, bounded `timeout -s ABRT 58` (`build/mission22-run.sh`; logs gitignored `build/mission22-*`): **SUMMARY pass=19 fail=0 total=19** — full test_bulk_rename suite (BulkRenameDialogTests ×11, ResponderBoxHandlingTests ×1, SessionTablePresentationTests ×6 incl. the renamed column test) + `ManualEditorGuiIntegrationTests.test_manual_edit_button_fixes_ambiguous_row_and_sessions_undo_restores_exactly`. Both mandated Undo regressions green: `test_select_apply_verify_undo_restores_bytes_exactly`, `test_unresolved_crash_journal_blocks_apply_and_undo_recovers_it`.
- One honest anomaly, classified transient/environmental (full evidence in status record): batch #1 had a SINGLE 58 s stall on `test_select_apply...` (ABRT-killed, exit 124); isolated rerun PASS 0.149 s + 4 more isolated PASS (~0.33 s) + full batch #2 all green with fault handlers armed and no stack dump ever produced → consistent with the pre-existing documented Qt flake class; NOT attributable to this geometry-only diff (no worker/journal/logic path touched). If it recurs WITH a faulthandler stack, treat as new defect evidence.

## Honest distinctions
- Source-level only: build-V18 AppImage (`7a197215ab06…`, 127,715,832 B) does NOT contain this change; it ships at the next packaging milestone (no rebuild authorized or done here). Offscreen assertions are not visual proof — Reason's visual acceptance of the resizable Preview columns belongs with the next build.
- No RPM, no release work, no dependency changes, no live/real-music operations (all out of bounds for this mission by authorization and untouched in fact).

## CURRENT SCOPE CORRECTION (Reason, 2026-10-24 — supersedes prior instructions)

Reason explicitly authorized TWO MusicSync 0.2.0 packaging deliverables from the accepted Mission 22 source: an updated AppImage and a native Fedora 44 RPM. Preserve older builds; perform relevant package-specific verification, record hashes, and protect real music, phone data, and the live system. Product remains INCOMPLETE pending packages and Reason's acceptance.

The coordinator-added full release-suite re-baseline (`scripts/run_release_tests.py`) was NOT requested or authorized by Reason. It is NOT an outstanding product requirement, recommended next action, or gate for AppImage/RPM packaging. Do not resume the previous stalled full-suite investigation from historical records. Earlier tests and historical failure evidence remain documented without creating new work.

## Remaining authorized product work
1. Rebuild the AppImage from the accepted Mission 22 source and run both established packaged tests.
2. Build and verify a native Fedora 44 RPM from the same source, with isolated dependency/install checks.
3. Record artifact hashes/provenance and arrange Reason's appropriate packaged acceptance. No live install or public release without separate consent.

## ONE potential next action (documented, NOT execution authorization)
Package the existing accepted MusicSync 0.2.0 application as AppImage + native Fedora 44 RPM under Reason's separately provided packaging authorization. Do not add the full release-suite re-baseline.

## Environment facts (carry forward / new this shift)
- Batch runner pattern proven again this shift: gitignored bash script looping the exact dotted test list, each run in a fresh offscreen process with `timeout -s ABRT 58` + `PYTHONFAULTHANDLER=1`, per-test logs; ~0.2–0.4 s wall per fresh PySide6 process on this machine when healthy (fast CPU/warm cache).
- Executor foreground cap still ≈30–52 s: keep polls at sleep ≤ ~27 s or detach + poll.
- github push/ls-remote ONLY via `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper='!gh auth git-credential' …`; handoff remote is a plain path.

## Checkpoint identity
Branch qwen/music-rename-settings; this documentation commit sits on top of incoming base 250f5f9… and is pushed to BOTH remotes as the identical commit; local HEAD == handoff SHA == github SHA verified by ls-remote after push. Never merged into main. No force-push.
