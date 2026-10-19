# Handoff — MusicSync V12 checkpoint: single-track manual filename/ID3 editor implemented at source level; focused smoke tests PASS; extended suite + regression pending

From: Qwen (V12 mission, 2026-10-19) · To: next engineer on the same branch (Forge/Codex or Qwen continuation).
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remotes: handoff + github.
Full detail and evidence chain: PROJECT_STATUS.md, section "Continuation record — V12".

## What this checkpoint delivered (all source-level; NO artifact rebuilt)
A working single-track manual editor for one MP3's filename plus eight ID3 text frames (TIT2, TPE1, TALB, TPE2, TCON, TRCK, TDRC, TCOM), integrated into the existing Bulk Rename dialog as a “Manual Edit…” action on the selected preview row.

- `src/musicsync/vendored/tags.py` — allow-list extended from 2 to 8 text frames; same set/delete semantics; unknown frame ids still refused; all other frames (artwork, ReplayGain, comments) preserved by mutagen's ID3v2-region-only save.
- `src/musicsync/manual_edit.py` (new) — ManualEditDialog: read-only open (lstat snapshot + observation), live filename validation (extension lock, separator/control-char rejection, 255-byte cap, LIVE-directory collision pre-check via name_key), per-field edits with multi-value frames locked (no silent collapse), tags-unreadable → filename-only mode, read-only inspection pane of every frame present at open time, live old→new preview. Explicit Apply… + Yes|No box DEFAULT NO; Enter bound to nothing (fail closed — this PySide build has no dialog default-button API). Mutation goes through the EXISTING journaled engine: one-item Preview/ItemPlan → RenameWorker('apply') → apply_changes → same journal, pre-mutation byte backup, changed-since-preview rejection, unresolved-session guard. Undo via existing Sessions flow restores original name AND exact bytes.
- `src/musicsync/bulk_rename.py` — “Manual Edit…” button (objectName manual_edit_button) + _on_manual_edit() slot; on changes_applied it refreshes the Sessions tab and re-scans. Only additive change to that module.
- `tests/test_manual_metadata_editor.py` (new, current content = smoke stage only): synthetic 8-frame MP3 fixtures with full 9-field tag set + APIC artwork + REPLAYGAIN TXXX + COMM decoys; reuses the bulk-rename suite's BoxAutoResponder/pump_until/snapshot helpers.

## Actual test results this shift (real, not inferred)
- `PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_manual_metadata_editor.ManualEditorSmokeTests -v` → **Ran 2 tests — OK, exit 0**:
  1. open + form edit + Cancel leaves bytes AND mtimes identical; no journal created;
  2. TIT2-only change behind an explicit Yes → on-disk tag updated, APIC artwork byte-identical, REPLAYGAIN/COMM intact, session 'closed' → engine `undo_session()` restores the exact original file bytes (sha256 match incl. tag area), tree byte+mtime identical to pre-snapshot, session 'undone'.
- py_compile + offscreen import of all three changed modules: OK. Bad-path dialog opens in a safe error state.

## NOT done yet (next actions, in order)
1. Extend tests/test_manual_metadata_editor.py with the remaining mission checklist items — filename-only + undo; combined + undo; all-eight-fields independence verified on disk; explicit deletion correct AND byte-exact undoable; unsafe-name/collision/no-op/stale-preview (`changed_since_preview`) safety cases; and the GUI integration test: ambiguous row corrected THROUGH THE REAL BulkRenameDialog button (design in PROJECT_STATUS V12 section — 25 ms polling QTimer started before manual_edit_button.click(); also click editor's cancel after apply to let exec() return), then Sessions-tab recognition + UI undo.
2. Regression: run all 12 tests/test_bulk_rename.py INDIVIDUALLY (known full-file flake class; every individual test passed at this base) — tags.py and bulk_rename.py were touched by this diff, so this re-run is mandatory before any "unchanged" claim; then scripts/run_release_tests.py vs baselines (GUI 12/12, overall 156/173 documented environmental failures).
3. Roadmap after that: AppImage rebuild + both packaged verification tests, Fedora 44 RPM, final arrangement. DO NOT start V13 or the persistent-memory project from this checkpoint.

## Environment facts (carry forward)
- run_command on this machine has NO default working directory: pass `working_directory=` every call; nonexistent cwd → ENOENT before execution. `/tmp` denied; scratch in QwenProjects/_probe_tmp (untracked, outside repo). Executor kills long commands — bound with timeout.
- github push/ls-remote ONLY via: `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper='!gh auth git-credential' <push|ls-remote> github …`. handoff remote is a plain path, no helper needed. $HOME empty in executor env.
- PEP 572 gotcha: walrus inside a LAMBDA does not bind the outer test scope — assign explicitly after pump_until (cost one debug cycle here).
- mutagen 1.47.0: `ID3.keys()` = full keys ('TXXX:<desc>', 'COMM::<lang>', 'APIC:') and getall(full_key) works; single-MPEG-frame files don't sync in MP3() — use the established 8-frame fixture builder.
- Live KDE Connect daemon exists on this host: tests must keep dropping DBUS_SESSION_BUS_ADDRESS / isolating XDG dirs (existing suite pattern). No phone involvement anywhere in V12 code paths.

## Checkpoint identity
Incoming base verified at shift start: local HEAD == handoff == github == 355aa3d898e578d479559d7631eec26e84f56c45 (clean tree). This checkpoint commit contains exactly: src/musicsync/vendored/tags.py, src/musicsync/manual_edit.py (new), src/musicsync/bulk_rename.py, tests/test_manual_metadata_editor.py (new), PROJECT_STATUS.md, this file — pushed to BOTH remotes on qwen/music-rename-settings; local HEAD == handoff SHA == github SHA verified by ls-remote after push (SHAs recorded in the commit report / PROJECT_STATUS continuation record). Never merged into main. No force-push.
