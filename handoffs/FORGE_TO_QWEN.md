# Coordinator → Qwen: initial MusicSyncRename task

This is a coordinator-prepared bootstrap, not an implementation handoff from Forge.
No earlier MusicSyncRename feature code or tests exist. The current branch is qwen/music-cleanup, created from the clean main bootstrap.

## Read once
- PROJECT_STATUS.md.
- /home/reason/Temporary/AgentHandoff/MusicSyncRename-references/REFERENCE_MANIFEST.md
- /home/reason/Temporary/AgentHandoff/MusicSyncRename-references/rename-map-2026-10-06.tsv
- Relevant reference source under /home/reason/Temporary/AgentHandoff/MusicSyncRename-references/MusicSync-v0.1.3/, especially src/musicsync/backend/{filesystem,android_names,replaygain,workflow}.py, src/musicsync/main_window.py, src/musicsync/settings.py, and relevant tests.

## Phase 1 implementation target
Implement a reusable standalone Python library-cleanup engine suitable for later embedding into MusicSync (Python/PySide6 application). No GUI integration yet.
- Scan a user-selected root safely (nested folders, Unicode, no symlink traversal), initially MP3 only.
- Read ID3 tags, propose deterministic Artist - Song Title.mp3 names and supported Game OST - Track.mp3 conventions; remove well-recognized downloader/video junk while preserving genuine version descriptors.
- Distinguish reliable deterministic fixes from ambiguous artist/title identity. Don't invent identifications or silently apply uncertain changes. Allow callers to override/review proposal decisions.
- Produce a complete read-only preview with original/proposed filenames, metadata deltas, review flags, and collisions. Don't edit any real file at preview time.
- Apply only explicitly selected and approved changes. Detect case-insensitive and Unicode-normalized filename collisions, changed-since-preview source files, symlinks, conflicts, and path escapes. Never overwrite.
- Preserve audio bytes, cover art, ReplayGain and legitimate tags. Remove only specifically identified metadata junk. Back up the original ID3 tags and keep a durable journal allowing safe undo; fail safely on interruption/partial changes without destroying historical backups.
- Include tests for normal examples, ambiguous files, malformed/no tags, Unicode, collisions, filename cycles, apply/undo, changed-source, cancellation/partial errors, artwork/ReplayGain preservation. Only synthetic/disposable fixtures.
- Document how to call the engine for scan → propose → approve → apply → undo; no default mutation of the live PC library.

## Next milestone, not yet assigned
Phase 2 integrates the tested engine into the existing MusicSync v0.1.3 PySide6 UI, preserving synchronization previews, Android filename translation, Mirror-mode safeguards and current native Qt appearance. Rename-induced old-phone-file duplicates must be visible in sync preview. Do not begin this phase until Phase 1 has a tested checkpoint.

## Test and tool notes
python3, git, mutagen, PySide6, rsync, rsgain and ffmpeg were detected locally; pytest was not. The existing MusicSync project uses Python's unittest. The reference code is available for reading under the neutral handoff directory, not for editing. Qwen owns only its own workspace and branch; check exact effective access before any new destination.

## Checkpoint
When Phase 1 produces meaningful source + tests, preserve them in Qwen's own branch and push to handoff. Report exact remote SHA, focused test results, and remaining work. Do not claim in-app or live-phone verification.
