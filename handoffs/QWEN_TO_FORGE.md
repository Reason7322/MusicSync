# Handoff — MusicSync Bulk Rename integration (INCOMPLETE, continue same mission)

From: Qwen (product-continuation shift, 2026-10-17) · To: next engineer on the same branch
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remote handoff.
Full detail: PROJECT_STATUS.md in repo root (fixture design, continuation records, exact next actions).

## State in one paragraph
The FULL GUI integration suite passes 12/12 under the mandated command; that run surfaced and fixed two real production defects plus three wrong test expectations. Defect 1: RenameWorker's exception handler passed an exception object to a string-only helper, crashing inside QThread::run before any result payload was emitted — every engine error path (refused apply on unresolved session, etc.) left the dialog busy forever with no failure box; now `clean(str(error))`. Defect 2 (vendored): after an aborted apply wrote backups into `.musicsyncrename/backups/`, post-op re-scans indexed those backup MP3s as approvable rename candidates — fixed by pruning the journal directory in `scan_root` (new `prune_dirnames` param, passed from `build_preview`). Test fixes: collision test no longer assumes checkbox state survives a re-scan; select_apply + file_changed no longer demand byte-equality for F1 across its legitimate TIT2 tag edit (audio-tail integrity + read_tag_snapshot instead). The packaged self-test is now REAL code, not a stub: `packaging_check.install_check` drives the actual Settings → Bulk Rename GUI on an isolated synthetic fixture with in-flow verification and a test-only auto-Yes responder; orchestrator `scripts/test_appimage_bulk_rename.py` builds the 8-file fixture, isolates HOME/XDG/runtime, passes an expectation manifest, re-verifies the tree out-of-process after undo. First full regression run: 156/173 pass including all bulk-rename tests and the 0.2.0 version test; the 17 failures are all in sync/process/AppImage-launcher/desktop files and trace to this execution environment (sys.executable empty → subprocess launches die "No program defined"; cc1 missing so AppRun.c can't compile; headless gio), not to changed code. NOTHING has been built yet: no 0.2.0 AppImage, no RPM.

## What changed since previous checkpoint
- `src/musicsync/bulk_rename.py`: worker error handler `clean(error)` → `clean(str(error))`.
- `src/musicsync/vendored/scanner.py` + `engine.py`: journal-directory pruning in scans (deliberate, documented divergence from MusicSyncRename @ 8023175; reference repo untouched).
- `tests/test_bulk_rename.py`: 3 expectation fixes listed above.
- `src/musicsync/packaging_check.py`: full `--bulk-rename-test` flow + `_HarnessBoxResponder`; one-shot scheduling guard on first status ready.
- `scripts/test_appimage_bulk_rename.py`: new orchestrator (compiles; not yet run against an image — none exists).
- `PROJECT_STATUS.md`, `docs/release-test-results.json`: updated with evidence from this shift's runs.

## Evidence (exact commands)
- GUI suite: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_bulk_rename.py' -v` → Ran 12 tests — OK, EXIT=0.
- Regression: `QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py` (backgrounded) → FAILED (failures=10, errors=7) of 173; environment root causes proven in-process: `python3 -c 'import sys; print(repr(sys.executable))'` → `''`; gcc runs but cannot execute cc1.
- Tag-edit byte behavior probe (real engine on scratch fixture): rename+TIT2 edit preserves audio tail, orig len == new len (4506).

## What the next engineer does (order matters)
1. Build the AppImage: `python3 scripts/build_appimage.py --skip-container-build` → dist/MusicSync-0.2.0-x86_64.AppImage. If Mutagen bundling or any packaging step fails, fix the demonstrated defect in the existing pipeline and rebuild (builder image cached; Containerfile is the change point if a pin/dep is missing).
2. Verify the BUILT artifact: `python3 scripts/test_appimage.py dist/MusicSync-0.2.0-x86_64.AppImage` then `python3 scripts/test_appimage_bulk_rename.py dist/MusicSync-0.2.0-x86_64.AppImage`. Both must pass headlessly; the second drives preview → select-all → apply (auto-Yes in harness only) → on-disk byte/tag verification → undo → out-of-process tree equality.
3. Re-run `QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py`; compare against the 17 known-environmental failures recorded above; any NEW failure is a real regression to fix.
4. Then the RPM phase per PROJECT_STATUS.md (packaging/rpm/, Fedora 44 containerized rpmbuild, isolated installroot validation, host install within permission boundaries).

## Hard constraints (unchanged)
- Do not touch Forge's workspace (/home/reason/Codex-Projects — denied), the installed production AppImage, real music/library data, or phone files. Host has no pytest — unittest only. Never auto-approve confirmations in production code; automated Yes/No handling exists ONLY inside test/harness responders (tests/test_bulk_rename.py BoxAutoResponder and packaging_check._HarnessBoxResponder).
- The reference backend MusicSyncRename stays intact at 8023175 as provenance (no edits/deletes); the vendored copies in this repo intentionally diverge now (documented).
- A passing test suite alone, a standalone renamer, or documentation does not satisfy the mission: deliverable = built AppImage (+ later RPM) where Settings → Bulk Rename → Preview → Select → Apply → Undo works on synthetic files with byte-exact undo and no host-Python borrowing.
