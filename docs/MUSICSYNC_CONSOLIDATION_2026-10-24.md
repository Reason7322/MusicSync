# MusicSync repository and filesystem consolidation

MusicSync 0.2.0 is product-complete and owner-accepted. The canonical local
project is `/home/reason/Codex-Projects/MusicSync/`, and the canonical GitHub
repository is `https://github.com/Reason7322/MusicSync`.

## Authoritative source

The canonical `main` branch began at the accepted settings-integration commit
`1c2c8ba990e2415a98c7bed5878a5ee7742c8bb7`. Consolidation changes add only
artifact and provenance records; application functionality is unchanged.

Historical Git lines remain reachable through these branches:

- `archive/original-master`
- `archive/original-appimage-packaging`
- `archive/original-android-filenames-v0.1.1`
- `archive/original-chatgpt-liquid-glass-ui`
- `archive/rename-main`
- `archive/rename-qwen-music-cleanup`

Historical MusicSync tags `v0.1.0` through `v0.1.3` are retained.

## Artifacts and evidence

`release-artifacts/0.2.0/` contains the accepted release set. The Fedora 44
binary RPM is tracked by Git. The V19 AppImage, source RPM, and corresponding
source archive are retained there locally but excluded from Git.

`archive/` is a local-only collection of historical corresponding-source
archives, manifests, runtime evidence, screenshots, logs, legacy launcher
records, handoffs, and small diagnostic probes. It is excluded from Git to
avoid publishing large or machine-specific evidence.

## Destructive-operation recovery

The pre-deletion recovery set is retained at
`/home/reason/Temporary/MusicSync-Consolidation-Recovery/2026-10-24-pre-delete/`.
It contains verified mirrors and bundles for all three former repositories,
exported GitHub metadata, the historical pull request record, and all 18
assets from the four former MusicSync releases.

Repository recreation does not preserve original GitHub repository IDs,
timestamps, PR identity, or release identity. The recovery set preserves
content and metadata for reference, not those hosted identities.
