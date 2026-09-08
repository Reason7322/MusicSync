# MusicSync
MusicSync is a small Linux app for syncing a local music library to an Android phone through KDE Connect.

<img width="2560" height="1376" alt="2026-09-09-014021_hyprshot" src="https://github.com/user-attachments/assets/7bd8b67a-4e3c-4c05-a729-57e02237d37e" />


This app is 100% vibe coded by Codex. Use at your own discretion.

I have personally tested it on Fedora 44 + Hyprland on bare metal, as well as on:
 - Ubuntu 26.04 (VM)
 - EndeavourOS running KDE Plasma (VM)
 - Pop!_OS 24.04 running COSMIC (VM)



The PC library is treated as the source of truth. MusicSync can preview changes, copy new or updated files, remove files that no longer exist on the PC, and apply per-track ReplayGain before syncing.
Built with Python, PySide6 and Qt Widgets.

Warning: MusicSync treats the PC library as authoritative. With Mirror mode enabled, files that exist only on the phone may be deleted. Mirror mode can be disabled in Settings. Always review the preview before syncing.

## What it does

- Syncs a music folder from your Linux PC to Android
- Uses KDE Connect for access to the phone
- Shows a preview before anything is copied or deleted
- Supports mirror mode and update-only mode
- Applies per-track ReplayGain using `rsgain`
- Protects KDE Connect's `.thumbnails` directory
- Checks the phone filesystem before syncing
- Refuses suspicious or unexpectedly large deletion operations without confirmation
- Does not run in the background or sync automatically

MusicSync never deletes files from the PC.

## Requirements
- 64-bit Linux (x86_64)
- KDE Connect installed on both the Linux PC and Android device, with the devices paired
- SSHFS / FUSE support installed on the Linux PC
- Android filesystem access enabled for KDE Connect

The AppImage bundles Python, PySide6/Qt, rsync, and rsgain; you do not need to install those separately.


## Download and run
Download the latest AppImage from the [Releases](https://github.com/Reason7322/MusicSync/releases) page.

Then run these commands in your terminal:
```bash
chmod +x MusicSync-0.1.0-x86_64.AppImage
./MusicSync-0.1.0-x86_64.AppImage
```
