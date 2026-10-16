# MusicSyncSettingsIntegration — Project Status

## PRODUCT STATUS: INCOMPLETE

Bulk Rename is implemented in source (preview/selection/apply/undo dialog + Settings wiring + vendored verified engine + packaging/version changes) but NOTHING has been integration-tested yet, no AppImage has been built for this feature, and the packaged-application verification workflow does not exist. A fresh Qwen chat continues the SAME mission from this checkpoint.

## Checkpoint identity
- Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration
- Branch: qwen/music-rename-settings (this file is committed on it)
- Incoming base verified at shift start: 051d23935a08fdc73883a073e2819faa60173b64 (local == handoff remote, clean).
- Reference backend: /home/reason/Temporary/QwenProjects/MusicSyncRename @ 802317530c8a2e62e289db27ebf150c95392974d (qwen/music-cleanup). Engine vendored byte-identical from there (`diff -q` verified for cleaning/scanner/tags/naming/engine).
- Remote: handoff → /home/reason/Temporary/AgentHandoff/MusicSyncSettingsIntegration.git; push ref refs/heads/qwen/music-rename-settings.

## What was implemented this shift (all committed in this checkpoint)
1. `src/musicsync/vendored/` — new package, the verified renaming engine:
   - cleaning.py, scanner.py, tags.py, naming.py, engine.py = byte-identical copies of musicsyncrename@8023175 (relative imports unchanged → work under the new package name).
   - `__init__.py` rewritten with provenance note + small re-export surface. Do not edit vendored code in place; fix upstream, re-verify, re-copy.
2. `src/musicsync/bulk_rename.py` — NEW dialog module:
   - `BulkRenameDialog(source)`: auto read-only scan on open; preview table (checkbox/Path/Current/Proposed/Status/Details); default NO approvals; ambiguous/error rows not checkable; collision list label; Sessions tab (list_sessions, never hides unresolved; corrupt journals shown, not undoable from UI); Apply = explicit confirm box then `begin_apply(approved)`; Undo = session select + confirm then `begin_undo(sid)`; QThread `RenameWorker` per operation (preview/apply/undo), queued signals only → all widget updates on GUI thread; busy flag blocks overlapping operations; Cancel button = cooperative apply cancellation via engine `cancel_check`; result dialogs show applied/rejected/partial/canceled exactly, undo shows restored + anomalies; re-scan after every apply/undo/failure.
   - Public test seams: `.preview`, `.report`, `.undo_report`, `.sessions`, `.busy`, `.applied_changed`, `_checked_rels()`, `_select_all(bool)`, `begin_apply(list[str])` (post-confirmation entry), `begin_undo(sid)` (post-confirmation entry).
3. `src/musicsync/settings_dialog.py`:
   - New "Bulk Rename…" button in the bottom row; enabled only for non-empty absolute source != '/'.
   - `_bulk_rename_clicked()` saves the form with FIRST-RUN validation (`validate(require_configured=False)` + atomic_json) — deliberately NOT `Settings.save()`, because save requires a configured phone and Bulk Rename must work without one. Sets `.bulk_rename_requested` and `.value`, then accept().
   - `_settings_from_form()` helper shared by Save and Bulk Rename paths (Save behavior unchanged, still full validation).
4. `src/musicsync/main_window.py`: `_settings()` opens `BulkRenameDialog(self.settings.source)` when `dialog.bulk_rename_requested`; after close refreshes library state when `applied_changed`. Local import keeps startup imports light.
5. Version bump 0.1.3 → 0.2.0 (distinct artifact name for controlled install/rollback): pyproject.toml, src/musicsync/__init__.py, packaging/appimage/assemble.py VERSION; tests/test_release_packaging.py consistency test updated to '0.2.0' + renamed `test_version_is_consistent_across_source_and_appimage_outputs`; README.md filenames (also fixed pre-existing 0.1.2/0.1.3 mismatch) and bundle list (+mutagen); THIRD-PARTY-NOTICES.md filenames (+ mutagen bullet).
6. Packaging for Mutagen: pyproject deps += `Mutagen>=1.47,<2`; pysidedeploy.spec `[python] packages = Nuitka==4.2.1, mutagen==1.47.0` (deploy-time install into build env; pin verified present on PyPI — latest there is 1.48.1); licenses.py collects mutagen wheel METADATA/license with sdist fallback (`pip download mutagen==1.47.0`, extract_notices) and REFUSES to package without its license; BUNDLED-COMPONENTS inventory += mutagen entry. Containerfile UNCHANGED (podman image cache stays valid).
7. `src/musicsync/entry.py` + `src/musicsync/packaging_check.py`: NEW test mode `--bulk-rename-test`. INCOMPLETE: only the mode is accepted and install_check's ready() guards it; the actual self-test `_flow()` body was NOT written this shift. Running that flag today times out at 180s with result FAIL — do not treat it as passing.

## Tests ACTUALLY executed (honest list)
- `python3 -m py_compile` on bulk_rename.py, settings_dialog.py, vendored/__init__.py, engine.py → OK.
- Vendored engine import from src tree under host python 3.14.8 / mutagen 1.47.0 → OK.
- Offscreen SettingsDialog construction with unconfigured settings + tempdir source: constructs; bulk_rename_button enabled=True; flag False initially → OK.
- `diff -q` vendored modules vs upstream backend repo → identical (5/5).
- PyPI availability check for mutagen 1.47.0 → exists.
NOT run this shift (do not claim otherwise): any unittest suite, tests/test_release_packaging.py with the new literals, full regression via scripts/run_release_tests.py, any GUI exercise of BulkRenameDialog beyond constructor smoke, AppImage build, packaged-app verification.

## Known defects / open risks
- bulk_rename.py never instantiated against a real library; expect first-test failures (worker plumbing, enum usage). Fix targeted, do not rewrite the module for cosmetic reasons.
- packaging_check `--bulk-rename-test` flow missing (see above) — must be implemented before it can serve AppImage verification.
- Nuitka/pysidedeploy mutagen bundling is UNTESTED until build: [python] packages install path and import tracing of the vendored subpackage are assumptions; fallback if spec-level install fails = add `mutagen==1.47.0` to Containerfile pip line + rebuild image (podman, rootless).
- licenses.py sdist step assumes a tarball named mutagen-1.47.0* lands in upstream/; verify at build.
- No AppImage built this shift. dist/ has no 0.2.0 artifact. Installed production AppImage is OUTSIDE authorized write paths — never overwrite it; deliver for controlled install only.

## Exact next implementation actions (in order)
1. Write `tests/test_bulk_rename.py` (fixture design below; repo conventions: unittest, flat imports in tests/, set `os.environ['QT_QPA_PLATFORM']='offscreen'` before QtWidgets import, shared-app pattern like test_process.py). Run offscreen from repo root with PYTHONPATH=src until green. Fix demonstrated failures in bulk_rename.py only.
2. Implement the missing `_flow()` for mode '--bulk-rename-test' inside `install_check` (packaging_check.py): SettingsDialog button click → BulkRenameDialog(source) on env-var library (`MUSICSYNC_BULK_RENAME_LIBRARY`) → wait preview (pump app.processEvents until `not dialog.busy and dialog.preview is not None`) → select safe + real `_on_apply()` with an installed app-level QMessageBox auto-accept event filter (Yes/Ok) → verify report partitions + on-disk names/bytes + tag edits via vendored read_tag_snapshot → undo selected session the same way → assert tree == pre-snapshot EXCLUDING `.musicsyncrename/` (journals/backups are preserved by design after undo) → evidence JSON + finish(). Plus orchestrator `scripts/test_appimage_bulk_rename.py` (isolated HOME/XDG, fake kdeconnect-cli in PATH, host-side synthetic MP3 builder, final tree re-verification outside the process).
3. Full regression: `env QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py` — must be green including updated version test.
4. Build AppImage (existing pipeline, cached image): `python3 scripts/build_appimage.py --skip-container-build`; expect dist/MusicSync-0.2.0-x86_64.AppImage + sources tarball + manifest; fix demonstrated build failures (likely first touch of mutagen spec install).
5. Verify the BUILT AppImage: base checks via scripts/test_appimage.py (headless parts), then rename orchestrator end-to-end (launch → Settings button present → preview proposals → apply renames synthetic files → undo byte-exact restore, no host Python needed for engine, no phone ops, last-sync.json untouched). Iterate until PASS.

## Synthetic fixture design (for step 1; deterministic statuses)
Silent MP3 builder: replicate MusicSyncRename/tests/fixtures.py pattern — frame = b'\xff\xfb\x90\xc0' + 413 zero bytes (417 B), write ~8 frames; tags via mutagen ID3 TPE1/TIT2 encoding=3. Files:
- f1 `untagged junk 1.mp3` + TPE1 'Junk Artist', TIT2 'Dream On (Official HD Video)' → status ok, rename + TIT2 tag edit to 'Dream On'.
- f2 `song_b.mp3` + clean tags 'Clean Band'/'Pure Title' → ok, rename only.
- f3 `Clean Duo - Same Name.mp3` with matching tags → no_change (never checkable).
- f4 `one - two - three.mp3` without ID3 → ambiguous (multiple_separators), not approvable; approving it programmatically must be rejected `status_ambiguous_not_applicable`.
- f5 `broken.mp3` junk bytes → error (parse_error); scan must not crash.
- f6/f7 `twin-a.mp3`,`twin-b.mp3` identical tags 'Twin Act'/'Same Song' → proposed_vs_proposed collision; both approved → BOTH rejected proposal_collision, session_id '', zero mutations; one side only → applies (target slot is free).
- f8 `later-modified.mp3` + clean tags → ok; mutate file after preview before apply → rejected changed_since_preview while others still apply.
Scenarios: default no approvals; preview read-only proof (bytes+mtime snapshot); zero-mutation no-approval path; cancel-before-confirm / mid-apply cancel → canceled partition, zero mutations; apply only approved; byte-exact undo incl. tag bytes + session state 'undone' + repeat undo no-op; file-changed-after-preview; collision pair; unresolved crash journal (hand-write header-only `.musicsyncrename/sessions/<id>.jsonl`) → new apply refused via EngineError surfaced, session still visible; double-click busy guard (second start must be a no-op while worker active).

## Environment facts
- Host python 3.14.8 with PySide6 + mutagen 1.47.0; pytest NOT installed — use unittest.
- Tests import musicsync from src/ via PYTHONPATH; run_release_tests.py handles that and writes docs/release-test-results.json evidence.
- Builder: rootless podman image localhost/musicsync-appimage-builder:latest (cached); build_appimage.py mounts repo ro, /work rw, dist → /out. AppImage test base check: `python3 scripts/test_appimage.py <AppImage>` (no --gui) runs headless; --gui/--preview assert wayland platform.
- Qt widget tests offscreen only; never click Sync Now; phone operations forbidden in all tests.

## Product acceptance criteria (unchanged, from mission 03)
Deliver a working MusicSync AppImage with Bulk Rename inside Settings: Open → Settings → Bulk Rename; Preview proposed filename + metadata changes (reasons/warnings/ambiguity/collisions, malformed files don't crash, never mutates); Select/approve individual changes (default none approved); Apply ONLY approved after explicit confirmation with accurate completed/rejected/partial/canceled reporting and overlap protection; Inspect sessions; Undo restores original names AND bytes with anomalies displayed, unresolved sessions never hidden; works without a phone; existing MusicSync sync behavior preserved (no auto-rename during sync, no ReplayGain/KDE Connect changes, no phone file modification); build + verify the real AppImage end-to-end on synthetic MP3s. Installed app and real music protected until separately authorized.
