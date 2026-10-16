# Handoff — MusicSync Bulk Rename integration (INCOMPLETE, continue same mission)

From: Qwen (Mission 03 shift, 2026-10-16) · To: next engineer on the same branch
Repo: /home/reason/Temporary/QwenProjects/MusicSyncSettingsIntegration · Branch qwen/music-rename-settings · Remote handoff.
Full detail: PROJECT_STATUS.md in repo root (fixture design, exact next actions, test evidence).

## State in one paragraph
The verified renaming engine is vendored byte-identical into `src/musicsync/vendored/` and a complete `BulkRenameDialog` (preview/select/apply/undo/sessions/failure surfacing) plus Settings→"Bulk Rename…" wiring (phone-independent save path), 0.1.3→0.2.0 version bump, and Mutagen packaging edits (spec pin, license collection, notices) are committed in this checkpoint. NOTHING beyond constructor-level smoke tests has been executed: no integration tests written/run yet, `packaging_check.py`'s `--bulk-rename-test` self-test flow is a stub that times out FAIL, and NO AppImage has been built for 0.2.0.

## What the next engineer does (order matters)
1. Write `tests/test_bulk_rename.py` per PROJECT_STATUS.md fixture design; run offscreen until green; fix demonstrated defects in bulk_rename.py with targeted patches only.
2. Implement the missing `_flow()` for `--bulk-rename-test` in packaging_check.py + orchestrator scripts/test_appimage_bulk_rename.py (design in PROJECT_STATUS.md).
3. Full regression via scripts/run_release_tests.py (offscreen) — must be green, including the updated 0.2.0 version test.
4. Build the AppImage with scripts/build_appimage.py --skip-container-build; expect dist/MusicSync-0.2.0-x86_64.AppImage; fix real build failures (first mutagen-bundling run — fallback: pin in Containerfile + image rebuild).
5. Verify the built image headlessly (base checks + full rename workflow on synthetic MP3s, isolated HOME/XDG, no host packages for engine, no phone ops) until PASS; report artifact path/SHA-256.

## Hard constraints
- Do not touch Forge's workspace (/home/reason/Codex-Projects — denied anyway), the installed AppImage (outside write paths), or real music/library data. No pytest on host — unittest only. Preserve vendored engine code identity; upstream-fix-and-recopy is the change path for it.
- A working preview, a standalone renamer, or documentation alone does NOT satisfy the mission: deliverable = the built AppImage where Settings → Bulk Rename → Preview → Select → Apply → Undo works on synthetic files.
