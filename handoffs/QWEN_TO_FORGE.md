# Handoff — MusicSync Bulk Rename integration (INCOMPLETE, continue same mission)

From: Qwen (focused continuation shift, 2026-10-17) · To: next engineer on the same branch
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remote handoff.
Full detail: PROJECT_STATUS.md in repo root (fixture design, observed failures, exact next actions).

## State in one paragraph
The verified renaming engine remains vendored byte-identical (`src/musicsync/vendored/`) and the full `BulkRenameDialog` plus Settings→"Bulk Rename…" wiring are committed. THIS SHIFT unblocked the GUI-test responder question: with the code as it stood at incoming SHA 7235678a48d18c8d62a7e1b3cf5552c9e9973cc2, the previously reported hang in `QMessageBox.information(…).exec()` does NOT reproduce — a bounded probe of the exact production path (never-shown dialog as box parent → `_on_apply` with nothing approved) closed with Ok in 0.03s. One new focused test was added to lock this down (`ResponderBoxHandlingTests`, watchdog-bounded). Both mandated targets pass: `test_responder_dismisses_info_box_and_yes_no_confirmations` and `test_apply_with_nothing_approved_is_a_noop` (2 tests, ~0.17s, OK; no-op path creates no session, mutates nothing, leaves no operation running). NO changes were needed to `BoxAutoResponder` or `bulk_rename.py`. The full integration file is still not green-verified at this state; everything downstream of the GUI suite (packaging flow, AppImage) remains undone.

## What changed since previous checkpoint
- `tests/test_bulk_rename.py`: + imports `faulthandler`, `threading`; + new class `ResponderBoxHandlingTests` with ONE focused test verifying, against the existing timer-poll `BoxAutoResponder` and real production box shapes (parented to a never-shown `BulkRenameDialog`): informational box closes via Ok; Yes/No with default No is answered explicitly Yes (`exec()` returns `StandardButton.Yes`); a deliberately declined title is answered No; repeated titles are treated as new boxes. Bounded 20s watchdog: on stuck, `faulthandler.dump_traceback()` + exit(2) — a failure is an immediate non-zero result, never an infinite hang.
- `PROJECT_STATUS.md`: continuation record with evidence; known-defect bullet updated (responder resolved at focused level).
- No source changes under `src/` this shift.

## Evidence (exact commands, all offscreen, timeout-bounded)
- Focused pair run: `PYTHONPATH=$PWD/src:$PWD/tests QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_bulk_rename.ResponderBoxHandlingTests.test_responder_dismisses_info_box_and_yes_no_confirmations test_bulk_rename.BulkRenameDialogTests.test_apply_with_nothing_approved_is_a_noop -v` → `Ran 2 tests in ~0.17s — OK`.
- Each target also passed individually (<0.15s each). A bounded probe script (scratch dir outside the repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration-scratch/probe_noop_path.py) confirmed all three box shapes close within one tick interval of the 25ms timer.
- Inference recorded in status doc: earlier hang likely came from a mid-evolution responder variant or stale bytecode; not re-investigated per assignment bounds.

## What the next engineer does (order matters)
1. Drive the FULL integration file green: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_bulk_rename.py' -v` (bound runs to <60s or background+poll; scratch dir available for diagnostics). Fix demonstrated defects in `bulk_rename.py`/tests with targeted patches only — do not rewrite the test file. If a suite-level hang appears, probe cross-test state first (`APP.allWidgets()` is app-global across tests in one process; per-test responders are separate instances but widget visibility is shared).
2. Implement the missing `_flow()` for `--bulk-rename-test` in packaging_check.py + orchestrator scripts/test_appimage_bulk_rename.py (design preserved in PROJECT_STATUS.md; auto-Yes allowed ONLY inside the isolated harness).
3. Full regression: `QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py` — must be green including the 0.2.0 version test.
4. Build AppImage with existing pipeline (`python3 scripts/build_appimage.py --skip-container-build`); expect dist/MusicSync-0.2.0-x86_64.AppImage; mutagen bundling untested — fix demonstrated build failures within the existing pipeline (fallback: pin in Containerfile + rebuild image).
5. Verify the BUILT AppImage headlessly (base checks via scripts/test_appimage.py + full rename workflow on synthetic MP3s, isolated HOME/XDG/runtime dirs, engine module path inside extracted AppDir, no phone ops, last-sync untouched) until PASS; report artifact absolute path + SHA-256.
After the AppImage phase: continue toward the Fedora-native RPM objective that preserves canonical source repo + standalone AppImage (not started; same mission chain).

## Hard constraints
- Do not touch Forge's workspace (/home/reason/Codex-Projects — denied), the installed production AppImage (outside write paths), real music/library data, or phone files. Host has no pytest — unittest only. Preserve vendored engine byte identity; upstream-fix-and-recopy is its change path. Never auto-approve confirmations in production code; automated Yes/No handling exists only inside test/harness responders.
- A working preview, a standalone renamer, or documentation alone does not satisfy the mission: deliverable = the built AppImage where Settings → Bulk Rename → Preview → Select → Apply → Undo works on synthetic files with byte-exact undo and no host-Python borrowing.
