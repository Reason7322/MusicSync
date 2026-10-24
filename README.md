# MusicSync
MusicSync is a small Linux app for syncing a local music library to an Android phone through KDE Connect.

<img width="2560" height="1376" alt="2026-09-09-014021_hyprshot" src="https://github.com/user-attachments/assets/7bd8b67a-4e3c-4c05-a729-57e02237d37e" />


This app is 100% vibe coded by Codex and my local model Qwen. Use at your own discretion.

I have personally tested it on Fedora 44 + Hyprland on bare metal, as well as on:
 - Ubuntu 26.04 (VM)
 - EndeavourOS running KDE Plasma (VM)
 - Pop!_OS 24.04 running COSMIC (VM)


## What it does

- Syncs your Linux music library to Android through KDE Connect
- Shows a preview before making changes
- Translates Android-incompatible phone filenames while leaving PC filenames unchanged
- Supports update-only and mirror modes
- Applies per-track ReplayGain with `rsgain`
- Includes safeguards against unexpected deletions
- Does not sync automatically or run in the background

MusicSync never deletes files from the PC.
ReplayGain makes individual tracks play at a more consistent perceived loudness by adding volume metadata. It does not re-encode the music or permanently change the audio.
Built with Python, PySide6 and Qt Widgets.

> **Warning:** MusicSync treats the PC library as authoritative. With Mirror mode enabled, files that exist only on the phone may be deleted. Mirror mode is **disabled** by default. Always review the preview before syncing.

Desktop application ID: **`io.github.reason7322.MusicSync`**

## Requirements
- 64-bit Linux (x86_64)
- KDE Connect installed on both the Linux PC and Android device, with the devices paired
- KDE Connect's **Filesystem access** plugin enabled on the Android device

- If MusicSync detects your phone but cannot access its storage, open KDE Connect on Android, select your PC, then go to **⋮ → Plugin settings** and enable **Filesystem access**. 
- SSHFS / FUSE support installed on the Linux PC

The AppImage bundles Python, PySide6/Qt, mutagen, rsync, and rsgain; you do not need to install those separately.
It also bundles a Qt-matched **Kvantum style engine** so a `qt6ct`-configured
Kvantum theme can work inside the AppImage. Personal Kvantum theme files and
color settings are still loaded from your desktop, not embedded in MusicSync.
See the [v0.1.3 Kvantum integration report](docs/kvantum-appimage-v013-report.md).


## Download and run
Download the latest **published** AppImage from the [MusicSync Releases](https://github.com/Reason7322/MusicSync/releases) page. As of 2026-10-18, the latest published release is **v0.1.3**; the local v0.2.0 AppImage is a development candidate and is not available from Releases.

For the published v0.1.3 AppImage, run:
```bash
cd ~/Downloads
chmod +x MusicSync-0.1.3-x86_64.AppImage
./MusicSync-0.1.3-x86_64.AppImage
```

When a newer release is published, substitute its actual downloaded filename. The packaged GUI for this settings-integration development branch has not been independently runtime-verified.
