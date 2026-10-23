# Handoff — Mission 21 COMPLETE: build-V18 AppImage rebuilt from accepted Mission 20 checkpoint; BOTH established packaged tests PASS on the new artifact; V17 preserved

From: Qwen (Mission 21, 2026-10-23) · To: next engineer on the same branch (Forge/Codex or Qwen continuation).
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remotes: handoff + github.
Incoming base verified at shift start ONCE: local HEAD == handoff SHA == github SHA == `2caad1fc70b76bb25624e05bc77962a702b95fe1`, clean tree, no untransferred WIP. Full detail and evidence chain: PROJECT_STATUS.md → "Continuation record — Mission 21".

## ORIGINAL PRODUCT GOAL (unchanged)
MusicSync 0.2.0 with integrated Settings → Bulk Rename → Preview → Select → Apply → Sessions → byte-exact Undo; safe manual filename/ID3 editing; preserved KDE Connect sync, ReplayGain and recovery-data protection; verified standalone AppImage on synthetic MP3s; Fedora 44 RPM; final release artifacts with provenance. **PRODUCT STATUS: INCOMPLETE.** Live install only under separate authorization.

## What this checkpoint delivered
Packaging + verification ONLY (zero src/ or tests/ changes — built tree == incoming commit exactly):
- **V17 preserved before overwrite:** `dist/MusicSync-0.2.0-x86_64.AppImage.bak-18808cb2` (re-hashed identical: `18808cb25c…`) plus versioned provenance copies in build/appimage/: `SHA256SUMS.v17-18808cb2`, `appimage-build-manifest.v17-18808cb2.json` (== the V17 manifest hash recorded at Mission 19), `runtime-tests.v17-18808cb2.json`, `bulk-rename-tests.v17-18808cb2.json` — all four re-hashed identical after copy.
- **Build V18** (established command, one detached job, BUILD_EXIT_CODE=0): `dist/MusicSync-0.2.0-x86_64.AppImage` — **127,715,832 bytes, SHA-256 `7a197215ab06ed6032d7df7520abbc0cffd0357c776e15737513f292dd33bc1d`**; corresponding source tarball 652,871,526 bytes SHA-256 `5a7eb0f1…`; manifest **761 files** (same count as V17), `bundled-components.json` byte-identical to V17; dist/SHA256SUMS matches independent host hashes.
- **Provenance:** tarball members src/tests/scripts diff-clean vs worktree at 2caad1fc; per-file cmp BYTE-IDENTICAL for bulk_rename.py, packaging_check.py, manual_edit.py, vendored/engine.py. **Mission 20 confirmed inside the packaged build**: frozen bundle contains SESSION_STATE_LABELS / session_sort_key ×2 / format_session_started_local ×2 / parse_session_started ×2 / 'Started (local)', and TEST2's in-image flow exercised the new numbered-row→UserRole Undo path live.

## Actual results this shift (exact commands → outcomes)
- `python3 scripts/build_appimage.py --skip-container-build` (PATH-prefixed, one nohup job; log build/appimage/build-run-v18.log) → **BUILD_EXIT_CODE=0**, wall ≈1 min 20 s.
- TEST1 `python3 scripts/test_appimage.py dist/MusicSync-0.2.0-x86_64.AppImage` → **exit 0** — "PASS: actual image, private runtime/tools, isolated tagging/mirror; requested GUI/preview checks" (evidence build/appimage/runtime-tests.json): frozen python 3.12.3 + PySide6 6.11.2, all Qt libs from in-image, rsync/rsgain from `usr/libexec/musicsync/`, **761/761 manifest files hash-verified**, real rsgain track-only tagging + skip-existing idempotency, unicode rsync dry-run/mirror fixtures with .thumbnails preservation.
- TEST2 `python3 scripts/test_appimage_bulk_rename.py dist/MusicSync-0.2.0-x86_64.AppImage` → **exit 0** — "PASS: packaged Bulk Rename workflow on synthetic fixture; tree byte-exact after undo" (evidence build/appimage/bulk-rename-tests.json, `image_sha256` == new artifact): isolated 8-file synthetic library, no phone ("Error querying KDE Connect"); item_count 8 {ok 5, ambiguous 1, error 1, no_change 1}; default_checked [] (no-approval default intact); exactly f1/f2/f8 applied to exact proposed names; twins rejected proposal_collision; partial {} / canceled []; **GUI Undo via Sessions tab (Mission 20 numbered rows resolved through UserRole) restored all three files — tree byte-exact after out-of-process re-verification**; session 'undone'; history bytes unchanged; journal preserved; vendored engine inside extracted AppDir (no host Python borrowing).
- Both test runs used orchestrator scratch rooted at the project-owned persistent dir `build/appimage/testtmp-v18/` (TMPDIR override honored end-to-end — even FUSE self-mounts landed there; nothing placed in /tmp by this mission; root empty after run). Log: build/appimage/v18-packaged-tests.log.
- Mission 20 source tests NOT rerun — zero new failures at any level (standing rule; no material trigger).

## Honest distinctions
- TESTED IN-PACKAGE vs ACCEPTED: the two established scripts exercise Bulk Rename inside the image + runtime/tagging/mirror behavior; they do NOT drive the manual editor, and offscreen assertions are not visual proof. Visual acceptance of the new Sessions table (and packaged manual-editor acceptance `--manual-edit-test` or equivalent) in this V18 build remains Reason's job.
- Deployment state: BUILT + TESTED OFFLINE only. No RPM, no release publication, no live install, no real music/phone operations — all out of bounds for this mission by authorization.

## Remaining product work (updated, in order)
1. `QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py` re-baseline vs recorded baselines (GUI suite 12/12; overall 156/173 with documented environmental failures) — outstanding since V10, due after this src change.
2. Packaged manual-editor acceptance (`--manual-edit-test` or equivalent) + Reason's visual UI acceptance of the Sessions table and manual editor in this new AppImage (V18). Fedora 44 native RPM (`packaging/rpm/` does not exist yet); final release organization + provenance; live install only under separate explicit user authorization.

## ONE potential next action (NOT authorized)
Run the release-suite re-baseline against recorded baselines: `QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py` — outstanding since V10 and due after any src change, including Mission 20's.

## Environment facts (carry forward / new this shift)
- Executor foreground wall ≈30–52 s: long work as ONE detached nohup job with explicit exit-code markers, polled by short commands (sleep ≤ ~24 s). A `sleep 30` poll was killed once; `sleep 24`/`25` returned cleanly.
- podman rootless on this host needs the explicit `PATH=/usr/bin:/bin:/usr/sbin:/sbin:$PATH` prefix for the build job (established; re-used, worked).
- Warm podman cache: full AppImage rebuild wall ≈1 min 20 s this shift vs ~4–4.5 min earlier records.
- **TMPDIR is honored by both test orchestrators AND the type-2 AppImage FUSE self-mount** — setting `TMPDIR=<project dir>` keeps every fixture/mount out of /tmp (newly proven this shift; root left empty after cleanup).
- github push/ls-remote ONLY via `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper='!gh auth git-credential' …`; handoff remote is a plain path.

## Checkpoint identity
Branch qwen/music-rename-settings; this documentation commit sits on top of incoming base 2caad1fc… and is pushed to BOTH remotes as the identical commit; local HEAD == handoff SHA == github SHA verified by ls-remote after push. Never merged into main. No force-push.
