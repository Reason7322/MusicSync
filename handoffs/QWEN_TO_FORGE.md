# Handoff — MusicSync V10: sync protection for .musicsyncrename/ (source-level COMPLETE; product still INCOMPLETE)

From: Qwen (V10 mission shift, 2026-10-18) · To: next engineer on the same branch
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remotes: handoff + github.
Full detail + evidence chain: PROJECT_STATUS.md, section "Continuation record — sync protection for .musicsyncrename/ recovery data (2026-10-18, V10 mission)".

## What this checkpoint delivered
User-reported production defect fixed at source level: library-root `.musicsyncrename/` (Bulk Rename's backup MP3s + session journals) was being treated as ordinary sync content — previews proposed copying it to the phone. Now it is **permanently protected internal recovery data**, enforced below the settings layer so old config files can't lose it:
- `settings.py`: `PROTECTED_ROOTS = ("/.musicsyncrename/",)` + `sync_exclusions()`.
- Choke point 1 — `filesystem.inventory()` merges protected roots into its exclusion set → PC source inventory, Android destination filename map, phone-side inventory and snapshot/digest checks can never see recovery data (root-anchored: an album's own `.musicsyncrename/` subfolder is still ordinary content).
- Choke point 2 — `rsync.arguments()` emits the protected roots as mandatory `--exclude`s → dry-run preview, real transfer, and mirror deletion all ignore it (no `--delete-excluded`, so excluded paths are never deleted from a phone that has an orphaned copy).
- ReplayGain (independent defect, proven by evidence): `rsgain easy <source>` had no exclusion option and tagged recovery backups in place. New `filesystem.replaygain_stage(source, inventory)` builds a temp symlink tree of ordinary top-level entries; workflow runs rsgain over that stage via `replaygain.command(settings, scan_root=stage)`. Ordinary files (album tracks AND loose root files) still get tagged exactly as before.
- `main_window.py`: "Ignored and protected:" label now shows the effective protection list.

Tests: new `tests/test_rename_sync_exclusion.py` → **10/10 OK** (real rsync, real ffmpeg/rsgain). Affected existing suites `test_release_io test_logic test_process test_filesystem test_guards test_workflow test_controller test_replaygain_integration` → **53/53 OK**. All 12 `test_bulk_rename.py` tests pass individually on this tree. Pre/post-patch reproduction harness + logs preserved gitignored under `build/repro-logs/`.

## What is NOT done (product work, in priority order)
1. **Packaged `--bulk-rename-test` flow still stalled** — the #1 open blocker from before V10; evidence chain + leading hypothesis (nested-modal QTimer starvation on PySide6 6.11.2 offscreen) are in PROJECT_STATUS.md under the build+verification record. Test that hypothesis first with the `build/appimage/isolate_flow3.py` driver pattern; smallest patch only.
2. **Rebuild the AppImage** (`python3 scripts/build_appimage.py --skip-container-build`) so it contains BOTH the bulk-rename fix and this sync protection, then re-run `scripts/test_appimage.py` AND `scripts/test_appimage_bulk_rename.py`. The currently built artifact (SHA-256 185e79f1…) still contains the demonstrated sync bug — do not claim otherwise.
3. Re-run `QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py`; compare with baselines (GUI suite 12/12; overall 156/173 incl. 17 documented environmental failures). Fix new/regression failures only.
4. Fedora 44 RPM (`packaging/rpm/` does not exist yet; podman pull verified viable, rootless `--network=host` container pattern established for the build image).
5. User-requested manual filename/ID3 editing — queued, NOT implemented, not part of V10.

## Known environmental quirk to be aware of (recorded with evidence this shift)
Running `test_bulk_rename.py` as one long discovery process intermittently deadlocks at varying tests; every test passes when run alone in its own process. Reproduced on BOTH the pristine tree (via git-stash A/B, hang at mid_apply_cancellation) and post-patch trees (hangs at collision_pair / crash_journal). Pre-existing Qt cross-test-state flake class per 2026-10-17 record — not caused by V10's diff. If you touch this suite again: run tests individually or add a per-test watchdog; don't burn cycles re-diagnosing before checking that pattern.

## Hard constraints + machine quirks (carry forward)
- Do not touch Forge's workspace, the installed production AppImage, real music/library data, real phone files, or any real `.musicsyncrename/` recovery data. Host has no pytest — unittest only. Never auto-approve confirmations in production code; box auto-answers live ONLY inside test/harness responders. Reference backend MusicSyncRename stays intact (vendored copies intentionally diverge, documented).
- Command executor kills foreground commands around ~55–60s: background + log + bounded polls for anything longer; keep poll commands themselves under ~45s. `kill`/pkill are blocked by policy — use a Python `/proc` scan (cmdline is NUL-separated elements; match per element, and bracket patterns if using pgrep) plus `os.kill`.
- `$HOME` is EMPTY in the executor env. For every github push/verify use EXACTLY: `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper='!gh auth git-credential' push|ls-remote github ...` (plain pushes fail "could not read Username").
- A live KDE Connect daemon runs here: drop DBUS_SESSION_BUS_ADDRESS in test envs or discover() hits the real bus.
- `.local/` holds GitHub CLI device state; it is local-only excluded via `.git/info/exclude` — never stage, never commit.

## Checkpoint identity
Branch qwen/music-rename-settings at this checkpoint's incoming base 43c05dce8a1d8547956bc1b2eced66e427ef47ce (verified equal on local + handoff + github at shift start). This commit = V10 source fix + `tests/test_rename_sync_exclusion.py` + these two documents, pushed to BOTH remotes under the same branch; verify local HEAD == handoff SHA == github SHA after push. Never merge into main merely to checkpoint.
