# Handoff — MusicSync V11: packaged Bulk Rename unblocked; AppImage rebuilt & both packaged tests PASS

From: Qwen (V11 mission shift, 2026-10-18) · To: next engineer on the same branch (Forge/Codex)
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remotes: handoff + github.
Full detail + evidence chain: PROJECT_STATUS.md, section "Continuation record — V11".

## What this checkpoint delivered (source-level PASS → rebuilt image → packaged PASS)
The packaged `--bulk-rename-test` GUI self-test no longer stalls. One-hunk fix in `src/musicsync/packaging_check.py` (+14/−2): the `open_settings` stage of `tick()` now advances its stage first and enters the Settings→Bulk Rename modal chain via `QTimer.singleShot(0, …)` instead of a synchronous `settings_button.click()`. Demonstrated mechanism: on PySide6 6.11.2 offscreen, a QTimer whose timeout handler synchronously enters QDialog.exec() never gets further timeouts dispatched while its own slot is on the stack through both nested execs (SettingsDialog then BulkRenameDialog); from an idle slot it fires continuously inside each nested loop and every later stage proceeds. No dialog/state-machine rewrites; deferred body keeps RuntimeError→failure+conclude protection.

Verification (all actual, this shift):
- Source-level probe bench `build/appimage/isolate_flow4.py` (gitignored scratch; traced QTimer fire counts / SD exec lifecycle / on-disk markers) run TWICE: both RC=0 with full `MUSICSYNC_CHECK … "result": "PASS"` in ~0.45 s: default_checked []; approved = exactly {untagged junk 1, song_b, twin-a, twin-b, later-modified}; applied f1/f2/f8 to exact proposed names; twins rejected proposal_collision ×2 behind an explicit Yes|No (default No) confirmation the harness responder answers; GUI undo → tree_missing/extra/changed all [] (byte+mtime vs pre-snapshot), session 'undone', history_unchanged true.
- New AppImage built with the established procedure (`python3 scripts/build_appimage.py --skip-container-build`): `dist/MusicSync-0.2.0-x86_64.AppImage`, 127,629,816 bytes, **SHA-256 d9865a3abdc66ae50ca3dca156094c0a02fb1b50c39b2b9baaf53eb9ac38e39e**; corresponding source archive SHA-256 675c1ecb64a2fb6da5f79a814ca1133c51e2f29d71275947c6924654e28482c3 (dist/SHA256SUMS updated). Old artifact preserved: `dist/MusicSync-0.2.0-x86_64.AppImage.bak-185e79f1` (185e79f1…).
- BOTH packaged tests exit 0 on the NEW image:
  - `python3 scripts/test_appimage.py dist/MusicSync-0.2.0-x86_64.AppImage` → PASS (runtime/tools/tagging/mirror; evidence build/appimage/runtime-tests.json).
  - `python3 scripts/test_appimage_bulk_rename.py dist/MusicSync-0.2.0-x86_64.AppImage` → PASS with valid MUSICSYNC_CHECK demonstrating the complete Settings → Bulk Rename → Preview → Select → Apply → Sessions → Undo sequence; out-of-process tree re-verification byte-exact vs pre-run snapshot; engine module inside extracted AppDir (no host Python borrowing); journal preserved after undo.
- V10 recovery-data protection confirmed INSIDE the new image: `musicsyncrename` + `replaygain_stage` present in frozen bundle `MusicSync.AppDir/usr/lib/musicsync/musicsync.bin` (not inferred from checkout).

## What is NOT done (next, in priority order)
1. Re-run `QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py`; compare with baselines (GUI suite 12/12; overall 156/173 incl. documented environmental failures — sys.executable '' / missing cc1 / headless gio). Fix new/regression failures only.
2. Fedora 44 RPM: `packaging/rpm/` still does not exist — create spec + containerized rpmbuild via rootless podman (fedora:44 pull verified viable; build image uses `--network=host`).
3. Final arrangement (canonical source repo + AppImage + RPM with hashes/provenance) and the queued user request: manual filename/ID3 metadata editing (NOT implemented).

## Environment facts (verified this shift / carry forward)
- Command executor now kills at **~30 s** per foreground command (observed; config timeout=30000ms — older notes said 55–60 s): background + log + fast polls for anything longer. `$HOME` is EMPTY in the executor env.
- GitHub push/verify ONLY works with exactly: `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper='!gh auth git-credential' push|ls-remote github …` (plain pushes fail "could not read Username"; verified live this shift for ls-remote at intake).
- A live KDE Connect daemon runs here: test/probe envs must drop DBUS_SESSION_BUS_ADDRESS and isolate HOME/XDG_*/XDG_RUNTIME_DIR (orchestrators already do).
- `pgrep -f <pattern>` self-matches the polling shell — use bracket patterns (`[d]river4.py`).
- Known pre-existing flake class: full-file discovery run of tests/test_bulk_rename.py intermittently deadlocks at varying tests; every individual test passes in its own process. Not caused by V10 or V11 diffs (V11 touches only packaging_check self-test flow). Don't re-diagnose before checking that pattern.
- Never touch: Forge's workspace, installed production AppImage, real music/phone data, real .musicsyncrename/ recovery data. Host has no pytest — unittest only. Box auto-answers live ONLY inside test/harness responders, never production code.

## Checkpoint identity
Incoming base verified at shift start: local HEAD == handoff == github == fa95aa37c031c2e00ee02b5570929c51ca842731 (clean tree). This checkpoint commit = the one-file fix (`src/musicsync/packaging_check.py`) + these two documents, on qwen/music-rename-settings, pushed to BOTH remotes; local HEAD == handoff SHA == github SHA verified by ls-remote after push. Never merge into main merely to checkpoint.
