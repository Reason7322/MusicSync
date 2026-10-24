> ### This application is 100% vibe coded by OpenAI Codex and my locally running Qwen model. Use it at your own discretion.


# MusicSync

MusicSync is a small Linux desktop application for synchronizing your local music library with an Android phone through KDE Connect.

It provides synchronization previews, ReplayGain processing, filename compatibility handling, and tools for organizing your music library.

**Latest release: [MusicSync v0.2.0](https://github.com/Reason7322/MusicSync/releases/tag/v0.2.0)**

<img width="2560" height="1376" alt="MusicSync running on Linux" src="https://github.com/user-attachments/assets/7bd8b67a-4e3c-4c05-a729-57e02237d37e" />


## Features

### Music synchronization

- Synchronizes your Linux music library with an Android phone through KDE Connect.
- Shows a preview of proposed changes before synchronization.
- Supports **Update-only** and **Mirror** synchronization modes.
- Translates Android-incompatible filenames on the phone without changing the corresponding PC filenames.
- Applies per-track ReplayGain metadata using `rsgain`.
- Includes safeguards against unexpected deletions.
- Never synchronizes automatically or runs synchronization tasks in the background.

### Music library management

Version 0.2.0 introduces additional tools for managing your local music library:

- **Bulk Rename:** Preview and rename multiple music files in one operation.
- **Selective approval:** Choose which proposed filename changes to apply.
- **Undo:** Reverse completed bulk-rename operations using the recorded session history.
- **Manual editing:** Edit filenames and music metadata, including ID3 tags.

Bulk Rename and local metadata editing do not require a connected Android device.

### Safety

MusicSync treats your PC music library as authoritative and never deletes files from it during synchronization.

> **Warning: Mirror mode can delete files from your phone.**
>
> When Mirror mode is enabled, files present only on the Android device may be removed to match the PC library.
>
> **Mirror mode is disabled by default.** Always review the synchronization preview before proceeding.

ReplayGain adjusts playback loudness through metadata. It does not re-encode music or modify the underlying audio samples.

## Download and installation

Prebuilt packages are available from the [GitHub Releases page](https://github.com/Reason7322/MusicSync/releases).

### Option 1: Linux AppImage

**Recommended for Linux distributions other than Fedora 44.**

Download:

[MusicSync-0.2.0-x86_64.AppImage](https://github.com/Reason7322/MusicSync/releases/download/v0.2.0/MusicSync-0.2.0-x86_64.AppImage)

Make it executable and launch it:

```bash
cd ~/Downloads
chmod +x MusicSync-0.2.0-x86_64.AppImage
./MusicSync-0.2.0-x86_64.AppImage
```

The AppImage bundles:

- Python
- PySide6 / Qt
- Mutagen
- rsync
- rsgain
- A Qt-compatible Kvantum style engine

These bundled dependencies do not need to be installed separately.

The AppImage also includes Kvantum integration for environments using `qt6ct`. Personal Kvantum themes and color settings are read from the desktop environment rather than bundled with MusicSync.

See the [Kvantum integration report](docs/kvantum-appimage-v013-report.md) for background information.

**Note:** KDE Connect and working SSHFS/FUSE support are still required for phone synchronization. These are external system integrations, not bundled AppImage dependencies.

### Option 2: Native Fedora 44 RPM

For Fedora 44 users, MusicSync is available as a native RPM package.

Download:

[musicsync-0.2.0-1.fc44.x86_64.rpm](https://github.com/Reason7322/MusicSync/releases/download/v0.2.0/musicsync-0.2.0-1.fc44.x86_64.rpm)

Install it with DNF:

```bash
cd ~/Downloads
sudo dnf install ./musicsync-0.2.0-1.fc44.x86_64.rpm
```

Launch MusicSync from your application menu or run:

```bash
musicsync
```

The RPM uses Fedora's system Python and libraries instead of bundling them.

#### RPM runtime dependencies

| Package | Purpose |
|---|---|
| `python3` | Python runtime |
| `python3-pyside6 >= 6.8` | Qt graphical interface |
| `python3-mutagen >= 1.47` | Music metadata and ID3 editing |
| `rsync` | File synchronization |
| `rsgain` | ReplayGain processing |

DNF automatically resolves these dependencies from enabled repositories.

The native RPM is specifically built for **Fedora 44 x86_64**. It is not a universal RPM intended for every RPM-based distribution.

### Package verification

Published v0.2.0 SHA-256 checksums:

**AppImage**
```text
3800b283bd287d09093176fb924e22a3314a1eb1ba7ada2161346faef41a9180
```

**Fedora RPM**
```text
5ac38a90ffb670cd477193a5a055c72e3d65be4bab4849710f4292501042ef7e
```

You can verify a downloaded file using:

```bash
sha256sum <downloaded-filename>
```

Compare the output against the corresponding checksum above.

## Android and KDE Connect requirements

To synchronize music with an Android phone, you need:

1. A 64-bit Linux PC (x86_64).
2. KDE Connect installed on the PC.
3. KDE Connect installed on the Android phone.
4. Both devices paired through KDE Connect.
5. KDE Connect's **Filesystem access** plugin enabled on Android.
6. Working SSHFS/FUSE support on the Linux PC.

### Troubleshooting phone storage access

If MusicSync detects your phone but cannot access its storage:

1. Open KDE Connect on your Android phone.
2. Select your paired PC.
3. Open **⋮ → Plugin settings**.
4. Enable **Filesystem access**.
5. Make sure the necessary Android storage permissions are granted.

The PC must be able to access the phone's shared filesystem for synchronization to work.

## Tested environments

I have personally tested MusicSync on:

| Distribution | Desktop environment | Test environment |
|---|---|---|
| Fedora 44 | Hyprland | Bare metal |
| Ubuntu 26.04 | Gnome | Virtual machine |
| EndeavourOS | KDE Plasma | Virtual machine |
| Pop!_OS 24.04 | COSMIC | Virtual machine |

The native Fedora 44 RPM for v0.2.0 has also been tested on real hardware with an Android device, including synchronization, Bulk Rename, and Undo.

Testing across these environments does not guarantee that every feature or release has been verified on every distribution.

## Building from source

MusicSync is written in Python and uses PySide6 with Qt Widgets.

### Python project requirements

| Dependency | Version |
|---|---|
| Python | 3.11 or newer |
| PySide6 | >= 6.8, < 7 |
| Mutagen | >= 1.47, < 2 |
| Setuptools | >= 77 (build system) |

The source code and packaging scripts are included in this repository.

The native Fedora RPM additionally requires RPM build tooling and `desktop-file-utils` at build time.

The standalone AppImage uses a separate Nuitka-based packaging process.

## Additional information

- **Current version:** 0.2.0
- **Platform:** Linux x86_64
- **GUI:** Python / PySide6 / Qt Widgets
- **Phone integration:** KDE Connect
- **Desktop application ID:** `io.github.reason7322.MusicSync`
- **License:** MIT

MusicSync is a personal open-source project, developed with AI-assisted coding tools and tested primarily against my own workflow and hardware.

It is provided as-is, without any warranty. Back up important music files before using bulk editing tools or enabling destructive synchronization modes.

Source code, packaging files, documentation, and development history are available in this repository.
