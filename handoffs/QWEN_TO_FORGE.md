# Handoff — MusicSync V16 checkpoint: AppImage 0.2.0 rebuilt from the V15 source, BOTH established packaged tests PASS

From: Qwen (Mission 16, 2026-10-21) · To: next engineer on the same branch (Forge/Codex or Qwen continuation).
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remotes: handoff + github.
Full detail and evidence chain: PROJECT_STATUS.md, section "Continuation record — V16".

## ORIGINAL PRODUCT GOAL (unchanged)
MusicSync 0.2.0 with integrated Settings → Bulk Rename → Preview → Select → Apply → Sessions → byte-exact Undo; safe manual filename/ID3 editing; preserved KDE Connect sync, ReplayGain and recovery-data protection; verified standalone AppImage on synthetic MP3s; Fedora 44 RPM; final release artifacts with provenance. PRODUCT STATUS: INCOMPLETE. Live install only under separate authorization.

## What this checkpoint delivered (packaging milestone — NO src changes)
- **Previous artifact preserved:** V11 `dist/MusicSync-0.2.0-x86_64.AppImage` matched its recorded SHA before rebuild → single backup `dist/MusicSync-0.2.0-x86_64.AppImage.bak-d9865a3a` (re-hashed identical); V11 evidence JSONs preserved as `build/appimage/{runtime,bulk-rename}-tests.v11-d9865a3a.json`.
- **Built from the incoming checkpoint** (`python3 scripts/build_appimage.py --skip-container-build`, one detached nohup job, log `build/appimage/build-run-v15.log`): **BUILD_EXIT_CODE=0**, ~4.5 min wall with warm podman cache (Nuitka freeze → license collection → appimagetool; 758-file zstd squashfs).
- **NEW artifact:** `dist/MusicSync-0.2.0-x86_64.AppImage`, **127,695,352 bytes**, SHA-256 **587ee62ca97d3c801f8dab3a39ea57b3f5e27341c0f120909d4a46c59fd06214**. Corresponding source `dist/MusicSync-0.2.0-x86_64-sources.tar.gz` (652,851,873 B) SHA-256 **750d9cf31b513dde0fd40fc63703f977479a3969239f49b9a944222406587d3d**. `dist/SHA256SUMS` regenerated and verified against actual files; manifest 95f1195f…, bundled-components unchanged (same component set as V11).
- **V15 source confirmed bundled** in the frozen build: corresponding-source tarball's `src/musicsync/manual_edit.py` + `bulk_rename.py` byte-identical to worktree at f94a643; frozen `musicsync.bin` contains "ManualEditDialog", "Apply manual changes", "manual_edit_button" and the engine guard constant (canary absent).

## Actual test results this shift (exact commands → outcomes, all against the NEW artifact)
- `python3 scripts/test_appimage.py dist/MusicSync-0.2.0-x86_64.AppImage` → **exit 0** — "PASS: actual image, private runtime/tools, isolated tagging/mirror; requested GUI/preview checks" (evidence `build/appimage/runtime-tests.json`). Frozen python 3.12.3 + PySide6 6.11.2 from inside the extracted AppDir (host is 3.14 — no host borrowing), Qt libs and rsync/rsgain all in-image, **761/761 manifest files hash-verified**, real rsgain track-only tagging + skip-existing idempotency, unicode-name rsync dry-run/mirror verified.
- `python3 scripts/test_appimage_bulk_rename.py dist/MusicSync-0.2.0-x86_64.AppImage` → **exit 0** — "PASS: packaged Bulk Rename workflow on synthetic fixture; tree byte-exact after undo" (evidence `build/appimage/bulk-rename-tests.json`). In-image GUI flow on the isolated 8-file synthetic MP3 library: item_count 8, default_checked [], Approve All Safe → exactly f1/f2/f8 applied to exact proposed names, twins rejected proposal_collision; new session c6e397a3…; **GUI Undo via Sessions tab restored original names with tree byte- AND mtime-exact** (in-process + out-of-process re-verification, missing/extra/changed all empty), session 'undone', journal preserved, last-sync history unchanged. Vendored engine resolved inside extracted AppDir.
- Combined log: `build/appimage/v15-packaged-tests.log` (both exit codes timestamped; natural completions, no timeout kills). No phone, KDE Connect daemon, real music library or Android files touched at any point.

## Honest distinction — tested in-package vs not yet tested
The established packaged scripts exercise **Bulk Rename** in the image plus runtime/tagging/mirror behavior. They do NOT drive the manual-editor interaction. Manual editing is verified only at source level + real-GUI offscreen (V12–V15). An in-image end-to-end manual-edit run (`--manual-edit-test` or equivalent) does not exist yet and must NOT be claimed as tested-in-package.

## NOT done yet — remaining work, in order
1. **Fedora 44 native RPM** — `packaging/rpm/` still does not exist; rootless podman pull + `--network=host` pattern established (builder image cache valid).
2. **Release regression** — `QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py` vs baselines (GUI suite 12/12; overall 156/173 with documented environmental failures); outstanding since V10, re-baseline after the next src change.
3. **Packaged manual-editor acceptance** — new `--manual-edit-test` flow or equivalent driving the in-image Manual Edit dialog through Preview → Apply → Sessions → Undo on synthetic MP3s.
4. **Final release organization + provenance** (canonical repo + artifacts with hashes); live install only under separate explicit user authorization.

## Environment facts (carry forward — new/updated this shift)
- Executor foreground wall ≈30 s per command (`timeout: 30000ms`): observed kills at ~36–52 s; sleep-27 + tail polls return cleanly. Long jobs = ONE detached nohup log job with explicit exit-code markers, polled by ≤27 s commands. (Supersedes the older "~60 s" note.)
- podman rootless here needs an explicit `PATH=/usr/bin:/bin:/usr/sbin:/sbin` prefix for `newuidmap` to resolve; cached builder image: `localhost/musicsync-appimage-builder:latest`. With warm cache a full rebuild is ~4.5 min, not 15–20.
- $HOME = /home/reason in the executor env (the "empty HOME" fact from V12 is outdated).
- github push/ls-remote still ONLY via `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper='!gh auth git-credential' <push|ls-remote> github …`; handoff remote is a plain path.

## Checkpoint identity
Incoming base verified at shift start: local HEAD == handoff SHA == github SHA == f94a6436d9d5864e127dc300c3064ee320ca2d81 (clean tree) — that is also the **source commit used for the build**. This checkpoint commit contains exactly `PROJECT_STATUS.md` + `handoffs/QWEN_TO_FORGE.md` (docs only; dist/ and build/ are gitignored, no binaries in Git). Pushed to BOTH remotes on qwen/music-rename-settings; local HEAD == handoff SHA == github SHA verified by ls-remote after push. Never merged into main. No force-push.
