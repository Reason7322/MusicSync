# MusicSyncRename — Project Status

## Current milestone
Phase 1: implement and test a reusable, offline MP3 library-cleanup engine with deterministic preview, ambiguity handling, safe batch apply and restore/undo. Build it here, not in the original MusicSync checkout. MusicSync GUI integration is a separate Phase 2.

## Exact starting state
- Project bootstrap: d0d46060472466e3b6440f042b4ed9b31b834cd2 (main).
- Initial engineering branch: qwen/music-cleanup.
- Current receiving handoff commit: use git rev-parse HEAD and verify against git ls-remote handoff refs/heads/qwen/music-cleanup (coordinator supplies exact SHA).
- Upstream MusicSync reference version: v0.1.3, commit 051d23935a08fdc73883a073e2819faa60173b64.
- Current owner: Qwen.

## References
- /home/reason/Temporary/AgentHandoff/MusicSyncRename-references/REFERENCE_MANIFEST.md
- /home/reason/Temporary/AgentHandoff/MusicSyncRename-references/MusicSync-v0.1.3/ (read-only tracked source snapshot)
- /home/reason/Temporary/AgentHandoff/MusicSyncRename-references/rename-map-2026-10-06.tsv (154 historical original-to-approved filename mappings)
- /home/reason/Temporary/AgentHandoff/MusicSyncRename.git (neutral remote, named handoff)

## Implementation/verification state
Handoff preparation only. No MusicSyncRename engine has been implemented or tested. No runtime deployment or music-library modification has occurred.

## Scope/safety
- Do not modify original MusicSync checkouts, music library, phone, or backup files.
- Do not treat reference mappings as evidence that unknown tracks have been correctly identified.
- Use synthetic fixture MP3s and temporary directories for tests.
- Preserve ReplayGain, album art, valid tags, and audio content; never overwrite source files through renames.
- Preserve existing MusicSync behavior/appearance in the later integration phase; never silently delete phone files after PC renames.
- No resource-intensive AppImage builds, deployments, or live-phone activity without explicit user authorization.

## Next action
Read handoffs/FORGE_TO_QWEN.md for the concrete Phase 1 task, build the offline cleanup engine, and validate it with focused tests.
