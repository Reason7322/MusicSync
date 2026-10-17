# MusicSyncRename

Bulk music-renaming engine developed for **MusicSync**.

The project focuses on making mass filename/tag cleanup safe enough to preview, apply and undo rather than performing destructive ad-hoc renames.

## Implemented engineering work

The `qwen/music-cleanup` branch preserves scanner/tag/naming repairs, synthetic MP3/ID3 fixtures, safe preview generation, invalid-name rejection, move planning, transactional apply/undo and recovery behavior.

Recorded milestones reached 42, then 65, then 89 passing tests as the engine grew.

This is the focused rename-engine project. Integration into the real MusicSync application/settings flow is tracked separately in `MusicSyncSettingsIntegration`.
