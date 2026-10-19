# Handoff — MusicSync V14 checkpoint: manual editor MANUAL FILENAME SAFETY VERIFIED (2 new tests pass individually; one demonstrated defect fixed with a 1-line src patch)

From: Qwen (V14 mission, 2026-10-19) · To: next engineer on the same branch (Forge/Codex or Qwen continuation).
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remotes: handoff + github.
Full detail and evidence chain: PROJECT_STATUS.md, section "Continuation record — V14".

## ORIGINAL PRODUCT GOAL (unchanged)
MusicSync 0.2.0 with integrated Settings → Bulk Rename → Preview → Select → Apply → Sessions → byte-exact Undo; safe collisions and explicit approval; preserved KDE Connect synchronization, ReplayGain and recovery data; manual filename and supported ID3 editing; verified standalone AppImage; Fedora 44 RPM; and final release artifacts with verified provenance. PRODUCT STATUS: INCOMPLETE. Live install only under separate authorization. Last built artifact still `dist/MusicSync-0.2.0-x86_64.AppImage` (SHA-256 d9865a3abdc66ae50ca3dca156094c0a02fb1b50c39b2b9baaf53eb9ac38e39e), which predates ALL manual-editor source work (V12–V14 not in any artifact).

## What this checkpoint delivered
`tests/test_manual_metadata_editor.py` extended from 6 to 8 tests; ONE demonstrated defect fixed with a single added line in `src/musicsync/manual_edit.py`.

- **Test 1** `ManualEditorSmokeTests.test_unsafe_filenames_are_rejected_and_cannot_bypass` (fresh isolated fixture per case): eight unsafe inputs — empty, whitespace-only, missing stem (`.mp3`), extension changed to `.flac`, forward slash / traversal (`../escape.mp3`), backslash separator, control character U+0001, 304-UTF-8-byte name (>255). For EVERY input verified: `validate_filename()` error, live filename-error label non-empty, preview line `Filename: INVALID — …` with the error carried by `pending_changes()`, **Apply disabled**, original bytes AND mtime_ns unchanged, no renamed/extra entry appears, NO journal dir and NO session. Final subTest proves a pending metadata edit (Title) CANNOT bypass an invalid filename (`traversal/bypass.mp3`): both lines in preview, Apply still disabled, and even a direct `apply_button.click()` is fail-closed — nothing applied, tree byte-exact afterwards.
- **Test 2** `ManualEditorSmokeTests.test_existing_file_collisions_are_rejected`: second MP3 (`target existing.mp3`) created inside the same isolated fixture dir; renaming onto it → `filename_collision()` identifies it ('…already exists in that folder'), label shows it, error carried by `pending_changes()`, Apply disabled, **neither** file's bytes/mtimes change, both names present, no journal/session. Second subTest drives the repo's case-insensitive `name_key()` (NFKC+casefold): proposed `TARGET EXISTING.mp3` is likewise refused byte-exact.
- **Defect proven + fixed (only src change):** `pending_changes()` left `proposed_out` unassigned on every invalid-filename path → `UnboundLocalError` in the textChanged slot, so the error label was never shown and `apply_button.setEnabled(False)` was never reached (Apply could sit STALE-enabled with no feedback). Pre-existing; V12/V13 only ever entered valid names. Fix = one line: initialize `proposed_out = None` before the branch chain (else-branch semantics preserved). Journal engine untouched.

## Actual test results this shift (real, not inferred — each run individually in a fresh process from repo root)
- `PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_manual_metadata_editor.ManualEditorSmokeTests.test_unsafe_filenames_are_rejected_and_cannot_bypass -v` → first run pre-fix FAILED (UnboundLocalError, defect above); post-fix **OK, exit 0** (8 unsafe subtests + bypass subtest).
- `…python3 -m unittest test_manual_metadata_editor.ManualEditorSmokeTests.test_existing_file_collisions_are_rejected -v` → **OK, exit 0** on first post-fix run.
- Bounded re-check (warranted: src/ changed) of the six pre-existing tests in this file, each still individually: `test_open_and_close_without_apply_is_byte_identical`, `test_metadata_edit_applies_and_undo_restores_exact_bytes`, `test_filename_only_rename_applies_and_undoes`, `test_combined_filename_and_metadata_applies_and_undoes`, `test_independent_single_field_edits_all_supported_fields`, `test_deletion_of_existing_field_is_explicit_and_undoable` → **6/6 OK**.
- NOT run (mission bounds / known pre-existing issue): full-file single-process runs of this file (documented Qt cross-test-process hang — do not reopen), test_bulk_rename regression, release suite.

## Changed files in this checkpoint commit
- `tests/test_manual_metadata_editor.py` (+2 tests)
- `src/musicsync/manual_edit.py` (+1 line defect fix in `pending_changes()`)
- `PROJECT_STATUS.md`, `handoffs/QWEN_TO_FORGE.md` (this file)

## NOT done yet — remaining work, in order (all original acceptance criteria still open until each is green)
1. Manual editor: unchanged-input/no-op safety ('No changes' info-box path; no journal on click-apply with zero diff) and stale-preview rejection (`changed_since_preview` while the dialog is open). NO stale-preview testing was done this mission per bounds.
2. GUI integration: ambiguous row corrected THROUGH THE REAL BulkRenameDialog 'Manual Edit…' button (objectName `manual_edit_button`) → session recognized in Sessions tab → UI Undo verified byte-exact. Design already worked out and recorded: start a 25 ms polling QTimer BEFORE `manual_edit_button.click()` (click blocks in editor.exec()), drive form + Apply with BoxAutoResponder, after apply+result box click the editor's Cancel so exec() returns; then assert on-disk state + `list_sessions` + Sessions-tab row + UI undo.
3. Regression: all 12 `tests/test_bulk_rename.py` tests INDIVIDUALLY (known full-file flake class), then `scripts/run_release_tests.py` vs baselines (GUI suite 12/12; overall 156/173 with documented environmental failures). Due to V12 since tags.py/bulk_rename.py were untouched by V13/V14 — but re-baseline after any future src change.
4. AppImage rebuild (`python3 scripts/build_appimage.py --skip-container-build`) + BOTH packaged verification tests (`scripts/test_appimage.py`, `scripts/test_appimage_bulk_rename.py`) against the new artifact; record new SHA-256s (current image still lacks V10-V14 source work).
5. Fedora 44 native RPM (`packaging/rpm/` does not exist yet; rootless podman, fedora:44 pull verified viable; `--network=host` pattern for build containers).
6. Final release organization + provenance (canonical repo + artifacts with hashes); live install only under separate explicit user authorization.

## Environment facts (carry forward)
- run_command on this machine has NO default working directory: pass `working_directory=` every call; `/tmp` denied; scratch in QwenProjects/_probe_tmp (untracked, outside repo). Executor kills long commands — bound with `timeout`. The mandated focused-test command form assumes CWD = repo root (`PYTHONPATH=src:tests … python3 -m unittest test_manual_metadata_editor.ManualEditorSmokeTests.<name> -v`); running it from tests/ breaks the relative PYTHONPATH.
- github push/ls-remote ONLY via: `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper='!gh auth git-credential' <push|ls-remote> github …`. handoff remote is a plain path, no helper needed. $HOME empty in executor env (set HOME=/home/reason if needed).
- PEP 572 gotcha: walrus inside a LAMBDA does not bind the outer test scope — assign explicitly after pump_until.
- mutagen 1.47.0: `ID3.keys()` = full keys ('TXXX:<desc>', 'COMM::<lang>', 'APIC:'); single-MPEG-frame files don't sync in MP3() — use the established 8-frame fixture builder (`build_manual_fixture`).
- Live KDE Connect daemon exists on this host: tests keep dropping DBUS_SESSION_BUS_ADDRESS / isolating XDG dirs (existing suite pattern). No phone involvement anywhere.
- Qt: PySide6 6.11.2 offscreen; a programmatic `QPushButton.click()` while the button is disabled may or may not emit clicked depending on slot path — V14's bypass subtest is written to be safe under both semantics (asserts end-state only, drains any surfaced refusal box).

## Checkpoint identity
Incoming base verified at shift start: local HEAD == handoff SHA == github SHA == 7d2262b65e324afa63ba20523a76903e9f723400 (clean tree). This checkpoint commit contains exactly the four files listed above — pushed to BOTH remotes on qwen/music-rename-settings; local HEAD == handoff SHA == github SHA verified by ls-remote after push. Never merged into main. No force-push.
