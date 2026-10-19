# Handoff — MusicSync V13 checkpoint: manual editor filename & metadata editing VERIFIED by four focused acceptance test cases (test-only diff; all 6 tests pass individually)

From: Qwen (V13 mission, 2026-10-19) · To: next engineer on the same branch (Forge/Codex or Qwen continuation).
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remotes: handoff + github.
Full detail and evidence chain: PROJECT_STATUS.md, section "Continuation record — V13".

## What this checkpoint delivered (test-only; NO src/ changes)
`tests/test_manual_metadata_editor.py` extended from 2 to 6 tests — the four mandated acceptance cases plus the two unchanged V12 smoke tests. No defect in `src/musicsync/manual_edit.py` or `src/musicsync/vendored/tags.py` was found: every apply came back with zero rejected/partial, so neither file needed a correction (they remain exactly as committed at V12).

- Case 1 filename-only: change only the filename → explicit Yes on 'Apply manual changes' → renamed file exists, old path gone, MP3 bytes byte-identical; engine undo restores original name + exact sha256 bytes + mtime_ns.
- Case 2 combined (filename + TIT2 + TALB): all three verified on disk in one session; other six supported fields intact; APIC/REPLAYGAIN/COMM decoys intact; audio tail (all 8 MPEG frames) byte-identical; undo restores name, exact bytes and mtime to the pre-test snapshot.
- Case 3 independence: eight subTests — TIT2/TPE1/TALB/TPE2/TCON/TRCK/TDRC/TCOM — each on a FRESH fixture in its own subdir (own journal root): intended frame changed on disk, every other field unchanged (leakage fails the test), decoys intact, undo restores exact original bytes.
- Case 4 explicit deletion: clearing TCOM shows 'Composer: "Old Composer" → deleted' in the live preview; apply only after explicit Yes; `getall('TCOM') == []` on disk while other fields + decoys survive; undo restores frame AND exact original MP3 bytes; session ends 'undone'.

Helpers added (module + class level): `ORIGINAL_VALUES`, `AUDIO_TAIL_LEN`, `assert_decoys_intact()`, `assert_other_fields_unchanged()`, `_fresh_track()` (isolated fixture per case), `_apply_explicit_yes()` (enforces a NEW explicit-Yes confirmation box and zero rejected/partial before returning the report), `_undo_session_and_check_state()` (closed → undo → no anomalies → undone). All on the existing `build_manual_fixture` / `BoxAutoResponder` / `pump_until` / `snapshot_tree` / `assert_same_tree` — nothing reimplemented.

## Actual test results this shift (real, not inferred)
- Each of the 6 tests run INDIVIDUALLY in a fresh process:
  `PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_manual_metadata_editor.ManualEditorSmokeTests.<test> -v` → **6/6 OK, exit 0** (0.02–0.4 s wall each; Case 3 includes all eight field subtests). Both V12 smoke tests still pass.
- Full-file single-process run of the mandated command: **2/2 attempts deadlocked at different tests** (attempt 1: inside Case 3; attempt 2: SIGABRT dump = freeze in `QDialog::exec()` of the 'Manual edit result' box, nested inside dispatch of the posted worker-finished signal while `pump_until`'s QEventLoop is active, no pending timers). That is the documented pre-existing Qt cross-test-state deadlock class (2026-10-18 record: test_bulk_rename.py full-file runs 'intermittently deadlocks at varying tests while every individual test passes'; open product work). Same shared responder/pump pattern already exercised by V12's smoke test 2 → not attributable to this diff; recorded as evidence, no re-investigation per mission bounds.

## NOT done yet (next actions, in order)
1. Safety & failure-path tests for the manual editor: unsafe filenames (separator/traversal/control char/over-length), live collision refusal, unchanged-input no-op ('No changes' info box path), stale-preview rejection (`changed_since_preview` while dialog open).
2. GUI integration test: ambiguous row corrected THROUGH THE REAL BulkRenameDialog 'Manual Edit…' button (objectName `manual_edit_button`) → session recognized in the Sessions tab → UI undo verified byte-exact. Design already worked out at V12 and recorded in PROJECT_STATUS remaining-work list: start a 25 ms polling QTimer BEFORE `manual_edit_button.click()` (the click blocks in editor.exec()), drive form+Apply with the responder, then after apply+result box click the editor's Cancel so exec() returns; assert on-disk state + `list_sessions` + Sessions-tab row + UI undo.
3. Regression: all 12 `tests/test_bulk_rename.py` tests INDIVIDUALLY (known full-file flake class), then `scripts/run_release_tests.py` vs baselines (GUI 12/12; overall 156/173 documented environmental failures). tags.py/bulk_rename.py were NOT touched in V13, so this is now due to V12's outstanding item, not a new one.
4. Roadmap: AppImage rebuild + BOTH packaged verification tests, Fedora 44 native RPM, final release organization and provenance. Manual editor source work (V12) is still NOT in any built artifact.

## Environment facts (carry forward)
- run_command on this machine has NO default working directory: pass `working_directory=` every call; nonexistent cwd → ENOENT before execution. `/tmp` denied; scratch in QwenProjects/_probe_tmp (untracked, outside repo). Executor kills long commands — bound with timeout / nohup+log+poll.
- github push/ls-remote ONLY via: `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper='!gh auth git-credential' <push|ls-remote> github …`. handoff remote is a plain path, no helper needed. $HOME empty in executor env (set HOME=/home/reason if needed).
- PEP 572 gotcha: walrus inside a LAMBDA does not bind the outer test scope — assign explicitly after pump_until.
- mutagen 1.47.0: `ID3.keys()` = full keys ('TXXX:<desc>', 'COMM::<lang>', 'APIC:'); single-MPEG-frame files don't sync in MP3() — use the established 8-frame fixture builder (`build_manual_fixture`).
- Live KDE Connect daemon exists on this host: tests must keep dropping DBUS_SESSION_BUS_ADDRESS / isolating XDG dirs (existing suite pattern). No phone involvement anywhere in V12/V13 code paths.

## Checkpoint identity
Incoming base verified at shift start: local HEAD == handoff == github == 561e679c5670dc7c2dbf49ef5961f1af7132a627 (clean tree). This checkpoint commit contains exactly: tests/test_manual_metadata_editor.py, PROJECT_STATUS.md, this file — pushed to BOTH remotes on qwen/music-rename-settings; local HEAD == handoff SHA == github SHA verified by ls-remote after push. Never merged into main. No force-push.
