# Handoff — MusicSync Bulk Rename integration (INCOMPLETE, continue same mission)

From: Qwen (build+verification shift, 2026-10-18) · To: next engineer on the same branch
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remotes: handoff + github.
Full detail: PROJECT_STATUS.md in repo root (evidence chain, environment facts, exact next actions).

## Product goal (unchanged)
Deliver MusicSync 0.2.0 with Bulk Rename integrated into the graphical Settings menu — Preview → Select → Apply → Sessions → Undo (default no approvals; byte-exact undo restoring names AND bytes; works without a phone; preserves sync/ReplayGain/KDE Connect behavior) — plus an end-to-end-verified standalone AppImage on synthetic MP3s, a Fedora 44 native RPM, preserved source + artifacts. Live host installation only under separate user authorization.

## State in one paragraph
The GitHub checkpoint mirror is repaired (local = handoff = github at this commit). The rootless AppImage build blocker ("could not find pasta") is understood and fixed scopingly: podman 5.8.9's default netavark path execs `pasta` for the container netns and fails on this host despite /usr/bin/pasta existing (slirp4netns absent entirely); the build container now runs with `--network=host` (no global config changed), and `assemble.py download()` gained bounded retries after a demonstrated dead-kde-mirror failure. The **AppImage BUILT successfully** from the cached builder image: dist/MusicSync-0.2.0-x86_64.AppImage, SHA-256 185e79f1982c079ef3ae76ab71ec3383f06a941f35aa3d01437ec6fc60cccce6 (plus ~652MB corresponding-source tarball, manifest, SHA256SUMS). **`scripts/test_appimage.py` PASSED on the built artifact** (frozen runtime, no host leakage, 761-file manifest hash-verified, relocated AppRun OK, real rsgain tagging + rsync mirror verified in-image). **UNRESOLVED:** `scripts/test_appimage_bulk_rename.py` — the packaged `--bulk-rename-test` flow (the in-image Settings → Bulk Rename GUI self-test) exits 1 with EMPTY stdout after opening the Settings dialog; reproduced identically from source. Evidence chain + leading hypothesis in PROJECT_STATUS.md: the flow's 25 ms tick timer stops producing stage effects after its first iteration (which synchronously opens `SettingsDialog.exec()` via a button click), while MainWindow's own 15 s timer keeps firing — consistent with, but NOT proven to be, a modal/nested-loop timer starvation on PySide6 6.11.2 offscreen. That is the ONE next action; it is a hypothesis to test, not a fix to assume. RPM phase not started (packaging/rpm/ does not exist yet).

## What changed since previous checkpoint (5b72593a)
- `scripts/build_appimage.py`: added `--network=host` to the podman run args + explanatory comment. Nothing else.
- `packaging/appimage/assemble.py`: bounded retry loop in `download()` around urlopen only (5 attempts, backoff capped 30 s, fresh `.part` per attempt); checksum verification untouched.
- New artifacts on disk (gitignored dist/): MusicSync-0.2.0-x86_64.AppImage + sources tarball + manifest/bundled-components/SHA256SUMS as above.
- No src/, tests/ or Containerfile changes — the 12/12 GUI suite and 156/173 regression baselines remain valid for unchanged code; `scripts/run_release_tests.py` was NOT re-run this shift.

## Evidence (exact commands + outcomes)
- Push: `GIT_TERMINAL_PROMPT=0 timeout 90s git -c credential.helper= -c credential.helper='!gh auth git-credential' push github HEAD:...` → `09bf5a7..5b72593`; then ls-remote on both remotes + `git rev-parse HEAD` all equal.
- Build: `python3 scripts/build_appimage.py --skip-container-build` (backgrounded) → dist/MusicSync-0.2.0-x86_64.AppImage; zero tracebacks in build log; host `sha256sum` matches build-time SHA256SUMS.
- Base verification: `python3 scripts/test_appimage.py dist/MusicSync-0.2.0-x86_64.AppImage` → PASS (build/appimage/runtime-tests.json).
- Packaged workflow: `python3 scripts/test_appimage_bulk_rename.py ...` → FAIL (no MUSICSYNC_CHECK line; returncode 1; empty stdout) — evidence build/appimage/bulk-rename-tests.json.
- Source-level reproduction + instrumentation drivers and their run logs are preserved gitignored under build/appimage/ (isolate_flow{,2,3}.py, src_probe.py, src-probe*/ app state+logs). Key facts: flow body starts (`vendored_engine_file` evidence key set); SettingsDialog visible by ~T+1.5 s with value=None to T+45 s; BulkRenameDialog never instantiated; NO QMessageBox object ever existed (warning paths ruled out via call tracer + hidden-object absence); ZERO inner-stderr lines (unhandled slot exception ruled out); settings.json never written; 15 s refresh timer kept firing while the flow's 25 ms tick produced no further stage effects.

## What the next engineer does (order matters)
1. ONE bounded action: test the leading hypothesis in a source-level bench (copy build/appimage/isolate_flow3.py as template). Candidate probe per PROJECT_STATUS.md: defer `window.settings_button.click()` to `QTimer.singleShot(0, ...)` and advance `st['stage']` BEFORE entering the modal chain. Confirm stages keep advancing via passive periodic dumps (BulkRenameDialog appears; scan/apply/undo evidence keys populate; a MUSICSYNC_CHECK line prints). Smallest patch only — do not rewrite the dialog or flow. If disproven, record what actually differs and pick ONE new bounded probe from the same evidence set; do not fan out into multiple investigations.
2. Once source-level PASS: rebuild (`python3 scripts/build_appimage.py --skip-container-build`, ~15–20 min) and re-run BOTH `scripts/test_appimage.py` AND `scripts/test_appimage_bulk_rename.py` on the new AppImage until PASS; record new artifact path + SHA-256.
3. Re-run `QT_QPA_PLATFORM=offscreen python3 scripts/run_release_tests.py`; compare with baselines (12/12 GUI suite; 156/173 overall, 17 documented environmental failures). Fix new/regression failures only.
4. Fedora 44 RPM: create packaging/rpm/ (spec + containerized rpmbuild via rootless podman; fedora:44 pull verified viable — `podman pull` does NOT hit the pasta problem); declared runtime deps python3-pyside6/python3-mutagen; validate in an isolated installroot (deps, files, desktop integration, launch). Host/live install ONLY with explicit user authorization; never overwrite installed AppImage or launcher.
5. Final arrangement + safe cleanup per PROJECT_STATUS.md. Separately queued user request (not checkpoint work): manual filename/ID3 metadata editing.

## Hard constraints (unchanged) + this machine's quirks
- Do not touch Forge's workspace (/home/reason/Codex-Projects — denied), installed production AppImage, real music/library data, or phone files. Host has no pytest — unittest only. Never auto-approve confirmations in production code; box auto-answers live ONLY inside test/harness responders. Reference backend MusicSyncRename stays intact (vendored copies intentionally diverge, documented).
- Command executor kills commands around ~60 s: background + log + bounded polls for long runs.
- $HOME is EMPTY in the executor env. For every github push/verify use EXACTLY: `git -c credential.helper= -c credential.helper='!gh auth git-credential' push|ls-remote github ...` (plain pushes fail "could not read Username"; this form verified working twice on 2026-10-18).
- A live KDE Connect daemon runs here: drop DBUS_SESSION_BUS_ADDRESS in test envs or discover() hits the real bus. `pgrep -f` self-matches your polling shell — use [x] bracket patterns.

## Checkpoint identity
- Incoming branch qwen/music-rename-settings at 5b72593a6d0defd1841511ca219765dbfab6a4b5 (clean tree verified before this shift's work).
- This checkpoint commit = the two build-file fixes + these documents, pushed to BOTH remotes under the same branch; verify local HEAD == handoff SHA == github SHA after push.
