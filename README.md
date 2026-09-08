# Music Sync

This app is 100% vibe coded, use at your own discretion.

A native Linux desktop music synchronization utility built with **Python 3,
PySide6 and Qt Widgets**. KDE Connect supplies SSHFS access, rsgain applies
ReplayGain, and rsync performs previews and synchronization. The UI uses Qt
Widgets, without a browser, Electron, QML or Qt Quick. The application inherits the existing Qt theme and
does not set a stylesheet or force a Qt platform plugin.

Music Sync grew from a known-working personal `syncmusic` Fish script.
It implements the workflow independently and does not require or modify that script. See
[the exact script behavior and deliberate changes](docs/script-reference.md).

## Launch

After completing the development environment setup below, run this from the
MusicSync source directory, using Fish or another shell:

```fish
./scripts/musicsync
```

After desktop integration is installed, open **Music Sync** from your application
launcher, or run `musicsync`. The original fallback command is **syncmusic**;
these names are deliberately different.

The app starts with read-only local-library and KDE Connect status checks. It
never mounts or synchronizes automatically. Connection status refreshes every
15 seconds while idle; Refresh also rescans the local library.

1. **Preview Changes** checks and mounts the phone if needed, validates storage,
   and runs rsync with `--dry-run`. It does not invoke rsgain or create a write probe.
2. **Sync Now** runs skip-existing per-track ReplayGain first, checks the phone
   again, obtains and validates the mount, tests write/delete capability, and
   calculates a fresh preview. ReplayGain can change the preview by changing tags.
3. Large deletions require a specific confirmation with a file list. The default
   is to cancel. Small changes proceed after clicking Sync Now.
4. Sync runs only after final validation. A final dry-run must show no remaining
   changes before success is recorded.
5. Cancel stops the current command and then cleans up app-created resources.
   Closing the window during an operation follows the same cancellation path.

Use **Show Log** for incremental utility output and detailed errors. Settings
allow selecting an available device or entering its ID, PC/phone directories,
ReplayGain enablement/preset/worker count, and mirror versus update-only mode.

## First run

No device is selected by default. Qt's `QStandardPaths.MusicLocation` supplies
the initial PC library suggestion, honoring the standard XDG music-directory
configuration on Linux (including localized folders). If Qt returns no suitable
location, or the home directory itself, the source remains unset and you must
choose it in Settings. The app does not create the suggested directory. A missing
or empty library cannot be synchronized; choose an existing library in Settings.

1. Pair your phone using KDE Connect and ensure it is connected. Allow Android
   file access, and create the intended Music directory on the phone yourself.
2. Click **Choose Device…**. Select your connected phone from **Available devices**,
   choose the PC library, and verify the phone directory and ReplayGain preset.
   If the list is empty, connect the phone, close Settings, click **Refresh** and
   reopen Settings. Device selection is explicit even when only one is available.
3. Save settings. Preview and Sync are enabled only after a device is configured.
   Start with **Preview Changes** and inspect the result before using **Sync Now**.

Existing saved settings remain in use. An unavailable configured device is shown
as disconnected and is never silently replaced with another phone.

## AppImage build (x86_64)

On the `appimage-packaging` work, the supported build entry point is:

```fish
python3 scripts/build_appimage.py
```

The host needs Python 3 for this **build script** and working rootless Podman.
It does not use the project's `.venv`, request sudo, install host packages or run
Git commands. The builder pulls a digest-pinned Ubuntu 24.04 image, installs pinned
PySide6/pyside6-deploy and Nuitka, and freezes the app in **standalone** mode.
It assembles an AppDir, collects third-party notices/corresponding sources, then
uses checksum-pinned official appimagetool/type-2-runtime binaries. It does not
use linuxdeploy-plugin-python or place an inner onefile executable in the image.

Outputs are ignored: staging/downloads/logs under `build/appimage/`, and the image,
source archive and manifests under `dist/`. Network access and several GB of free
space are needed. `--skip-container-build` reuses the builder; `--stage assemble`
reuses an existing standalone freeze. Use the default full build after application
code changes. The release-test source-copy fixture excludes these generated trees.

The AppImage bundles Python, PySide6/Qt Widgets and Wayland client plugins, MusicSync,
rsync, rsgain 3.6, the independent-track preset, and compatible qt6ct theme/style
plugins with their KDE color-scheme/icon dependencies. Bundled tools are selected by
absolute AppDir-relative paths, without replacing the host PATH. Native/source
runs still use host utilities. The default system preset setting maps to the
bundled preset at runtime; custom preset paths are retained, and temporary mount
paths are never saved into settings.

Users still need **KDE Connect and its configured desktop session, kdeconnect-cli,
SSHFS, fusermount3, findmnt, mountpoint, D-Bus and kernel FUSE support**. The host
also supplies glibc and graphics-driver entry points. No KDE Connect daemon,
pairing data or independent service stack is packaged. The finished image does
not need host Python, PySide6, Qt, rsync or rsgain. Startup reports missing host
integration tools; healthy source/native operation is unchanged.

Settings and logs retain the normal user XDG locations outside the image. Close
an existing MusicSync instance before testing. Explicit packaged diagnostics:

```fish
./dist/MusicSync-0.1.0-x86_64.AppImage --runtime-info
./dist/MusicSync-0.1.0-x86_64.AppImage --tool-version rsync
./dist/MusicSync-0.1.0-x86_64.AppImage --tool-version rsgain
./dist/MusicSync-0.1.0-x86_64.AppImage --smoke-test
# Uses saved configuration; clicks Preview only, then closes after cleanup:
./dist/MusicSync-0.1.0-x86_64.AppImage --preview-test
# Repeatable artifact tests; ffmpeg/ffprobe are needed only to create/inspect
# temporary test audio. --preview is explicit and uses saved phone settings:
python3 scripts/test_appimage.py dist/MusicSync-0.1.0-x86_64.AppImage --gui --preview
```

The diagnostic flags are opt-in; a normal launch never starts synchronization.
The artifact test restricts PATH to host integration tools, checks actual loaded
Qt libraries, moves an extracted AppDir to a Unicode/metacharacter path, and
tests private ReplayGain and rsync only against temporary music directories.
Omit `--preview` to avoid contacting the configured phone's filesystem. GUI tests
expect a native Wayland session. Normal AppImage mounting itself needs a working
host `fusermount3`; `--appimage-extract` and `squashfs-root/AppRun` provide a
manual extraction fallback when AppImage FUSE mounting is unavailable.
Diagnostic output can contain private paths/device information: keep it out of
public commits. Build/runtime results and portability boundaries are documented
in [the AppImage build report](docs/appimage-build-report.md).

The image does not install a launcher into the host desktop automatically. A
desktop portal may log that the application ID is not installed until desktop
integration is supplied. When the desktop selects `QT_QPA_PLATFORMTHEME=qt6ct`,
the bundled plugins read the user's normal external qt6ct/XDG configuration.
The build uses current [qt6ct upstream](https://www.opencode.net/trialuser/qt6ct)
with its pinned KDE integration patch, matching Qt 6.11.2 SDK headers, and links
against the actual PySide6 wheel runtime. KDE Frameworks are also built against
that runtime. No host Qt plugin search path is added and no second Qt is shipped.
Inherited theme/style variables are preserved. Other platform-theme plugins are
supported only when bundled; otherwise Qt falls back normally. MusicSync does not
force a theme, palette or stylesheet. Optional Qt Quick bridges are disabled;
KDE `.colors` and icon-engine support, including Breeze fallback icons, are kept.

On GNOME, the image also supplies Qt's GTK3 platform-theme plugin from the same
PySide6 6.11.2 wheel as its Qt runtime. With `QT_QPA_PLATFORMTHEME` unset, Qt
naturally tries `gtk3` before its built-in `gnome` fallback. This bridges GTK
appearance settings into Qt Widgets; the application UI remains Qt. GTK3 is not
forced on other desktops and explicit qt6ct selection takes precedence.
GTK3/GDK and their non-base library closure are private, as are a matching dconf
GSettings backend and GTK schemas. The user settings database, D-Bus session,
fonts and selected external themes remain on the host. Host commands receive
their original GIO/schema environment, so KDE Connect is not put into a private
GTK or GSettings environment. See [the GTK3 report](docs/gtk3-appimage-report.md)
for actual GNOME dark/light tests, size and dependency details.

To repeat the GNOME appearance test in an actual GNOME Wayland session:

```fish
python3 scripts/test_appimage_gnome.py dist/MusicSync-0.1.0-x86_64.AppImage --dark-gtk-theme Yaru-dark --light-gtk-theme Yaru
```

The theme names are test inputs for Ubuntu's installed themes; choose installed
equivalents on another desktop. This harness temporarily changes GNOME's
`color-scheme` and `gtk-theme`, restores their original values in `finally`, and
captures private evidence under `build/gtk3/gnome-tests`. It never synchronizes
music. Python and `gsettings` are needed for the harness only.

From a normal qt6ct Wayland session, test the artifact's theme integration with:

```fish
python3 scripts/test_appimage_theme.py dist/MusicSync-0.1.0-x86_64.AppImage
```

This diagnostic needs host Python, `strace` and `readelf`; users launching the
application do not. It tests the existing external configuration, then changes
only a temporary external XDG copy to verify palette changes without rebuilding.
It leaves the active qt6ct configuration unchanged. See the
[qt6ct build and runtime report](docs/qt6ct-appimage-report.md) for dependency sizes,
exact build inputs and observed results.

**Binary redistribution includes license obligations.** Keep MusicSync MIT, retain
the image's bundled notices, and distribute the matching corresponding-source
archive alongside the AppImage. See [third-party notices and replacement instructions](packaging/appimage/THIRD-PARTY-NOTICES.md).
The build records package versions/hashes; apt repositories and continuous-release
download URLs are not permanent archives, so reproducing an older build may require
the retained inputs. No cross-distribution or bit-for-bit reproducibility claim is
made merely because the build succeeded.

## Development environment

The implementation was verified with Fedora's installed Python **3.14.7** and
`python3-pyside6` **6.11.2**. No global pip install, system package replacement,
or sudo was used. The project-local virtual environment reuses Fedora's installed
Qt bindings. Cached DNF package availability was inspected before choosing this
approach; see [environment and verification](docs/verification.md).

To recreate that development layout:

```fish
cd /path/to/MusicSync
python3 -m venv --system-site-packages .venv
.venv/bin/python -c 'import PySide6; print(PySide6.__version__)'
./scripts/musicsync
```

The launcher supplies `PYTHONPATH` for the `src/` layout and its worker processes.
Activation is optional; all examples select the virtual environment explicitly.
The original development environment needed no dependency download. On a new Fedora system,
first check the installed/available `python3-pyside6` package and external tools.
If system PySide6 is unavailable, an isolated venv can instead install the
`pyproject.toml` project with pip **inside that venv**, which obtains PySide6 and
the build backend from the configured Python package index. Do not mix a pip Qt
wheel into the system-site-packages environment used here.

`pyproject.toml` uses standard PEP 517/setuptools packaging and exposes a
`musicsync` GUI entry point for normal wheel/editable installations. Source-tree
launching intentionally needs no setuptools download. Python 3.11+ and PySide6
6.8+ are declared; this machine's versions above are the tested combination.

External runtime tools (all run as the user):

| Tool | Responsibility | Fedora package on this machine |
| --- | --- | --- |
| `kdeconnect-cli` | Paired/reachable discovery and SFTP mount | `kdeconnectd` |
| `sshfs` | Remote filesystem, launched by KDE Connect | `fuse-sshfs` |
| `fusermount3` | Normal unmount and stale lazy detach | FUSE 3 utilities |
| `rsync` | Dry-run comparison and file mirroring | `rsync` |
| `rsgain` | Track ReplayGain tags | `rsgain` |
| `findmnt`, `mountpoint` | Mount identity/presence checks | util-linux utilities |

The KDE Connect desktop session, pairing, Android storage permission and Android
SFTP service must work. No SSH credentials, private keys, passwords, system mount
configuration or KDE Connect settings are read or modified by this app.

## Safety model

* PC source must exist, be readable and contain regular files outside excluded
  directories. Empty source aborts even in update-only mode. Filesystem scan
  errors abort; unreadable subdirectories cannot masquerade as missing files.
* Device must be currently available. The mountpoint is always requested from
  KDE Connect, never synthesized from UID or device ID.
* Both `mountpoint` and `findmnt` must identify a `fuse.sshfs` mount sourced from
  `kdeconnect@…`. The Linux mount ID is retained for the operation.
* Actual enumeration of `/storage/emulated/0` verifies SFTP responsiveness.
  The configured Music directory must already exist; the application never
  creates it. Write and removal of an exclusive random tiny probe are tested
  only during a real operation, before invoking real rsync.
* A stale **existing** KDE SSHFS mount is detached with `fusermount3 -uz`, the
  device is rechecked, and exactly one fresh mount is attempted. Broken fresh
  storage stops with instructions to force-stop/reopen KDE Connect on the phone.
* Healthy borrowed mounts remain mounted. App-created/remounted and partial
  mounts are cleaned up with normal unmount, then lazy detach if necessary.
  Cleanup revalidates identity, refusing an unexpected filesystem or a changed
  mount ID. Cleanup failure is visible separately from synchronization results.
* Mirror flags preserve the script's `-rtv --omit-dir-times --human-readable
  --itemize-changes --info=progress2 --delete-after --exclude=/.thumbnails/`.
  Source content is copied with trailing-slash semantics. No archive mode,
  `--ignore-errors`, or `--delete-excluded` is used. Update-only omits deletion.
* Preview adds machine-readable output framing and stats. Displayed sizes come
  from exact filesystem inventories, including sizes of files to delete.
  Directories have separate rows and do not inflate file counts.
* Confirmation triggers at **more than 20%** of phone files or **50 or more**
  files/directories removed. Constants live in `settings.py`. File counts include
  any nonmusic files being mirrored; labeling them all as tracks would be misleading.
* Just before rsync, a helper verifies source/destination inventory fingerprints
  against the fresh preview and pins directory descriptors. It rejects symlink
  traversal and nested phone mounts, enters the pinned phone directory, and
  `exec`s rsync with destination `./` and a pinned `/proc/self/fd/N/` source.
  Lazy detach cannot redirect this process into an ordinary directory underneath
  the former mountpoint. `--max-delete` limits deletions to the previewed count,
  including directories. Changed inventories abort rather than silently reuse approval.
* A lock prevents concurrent Music Sync application instances. **Do not run the
  fallback script or another sync utility concurrently.** External mutations
  during rsync are not an atomic transaction. Do not deliberately edit either
  library while a synchronization is running.
* Each utility runs in its own process session. Cancellation signals that utility's
  process group with SIGTERM and escalates to SIGKILL after 3 seconds, including
  surviving descendants. Cleanup waits for cancellation handling; unrelated KDE
  daemon processes are not part of this group.
  Filesystem probes have timeouts. No UI-thread `subprocess.run`, sleep,
  `waitForFinished`, or blocking filesystem traversal is used. Killing the app
  externally, session termination, or uninterruptible kernel I/O can prevent
  cleanup; a later run revalidates the mount rather than assuming it is usable.

ReplayGain uses `rsgain easy -S -m 4 -p
/usr/share/rsgain/presets/no_album.ini SOURCE` by default. Installed preset
`Album=false` and `PreserveMtimes=false` preserve independent track treatment
and let rsync detect modified tags. Preview never tags. A ReplayGain failure
stops before syncing. Changing the preset in Settings is an advanced option;
keep `Album=false` and do not enable mtime preservation. The tool remains the
authority for analysis/tagging; the app does not implement it.

## Architecture

```text
src/musicsync/
  app.py                  Qt application, identity and single-instance lock
  main_window.py          Conventional Widgets UI, progress, confirmation, logs
  settings_dialog.py      User-editable settings
  settings.py             Validated JSON configuration and deletion thresholds
  logging.py              Rotating application log
  models/types.py         States, commands, results, changes and summaries
  backend/
    kdeconnect.py         Documented CLI command builders and discovery parser
    mounts.py             findmnt and Linux mount-table identity parsing
    replaygain.py         rsgain invocation and conservative result parsing
    rsync.py              Argument construction, itemization/progress parsing
    process.py            Incremental, cancellable QProcess execution
    filesystem.py         Blocking filesystem primitives used only in workers
    worker.py             Guarded filesystem helper / exec handoff to utilities
    workflow.py           Linear generator state machine with finally cleanup
    sync_controller.py    Qt adapter that drives the state machine and records success
    status.py             Read-only asynchronous startup/idle status service
```

The workflow yields explicit state events, command requests and deletion approval
requests. It receives results from a runner rather than importing GUI widgets.
Its control flow is ordinary readable sequential Python with `yield from` and
`try/finally`, not a callback chain. State history is inspectable on the controller;
commands are mockable without a phone. Worker processes keep even stuck FUSE
lookups outside the GUI thread. For rsync and fusermount, `os.execv` hands the
same QProcess PID to the real utility, preserving cancellation targeting.

The KDE integration deliberately uses documented CLI interfaces. Direct D-Bus
would add a second interface to verify without improving the initial workflow.
No shell command strings are constructed for utility invocation; every QProcess
receives a program and argument array. The source launcher is a static shell file
that selects the project interpreter and forwards `"$@"`. The installed command
uses Python `os.execv` with an argument array. Neither evaluates user input as shell code.

## Configuration, logs and history

Defaults: Qt/XDG Music location (or explicit selection if unavailable), no selected device, destination `/storage/emulated/0/Music`, ReplayGain enabled with
four workers, mirror enabled, `/.thumbnails/` excluded/protected.

* `$XDG_CONFIG_HOME/musicsync/settings.json`, default
  `~/.config/musicsync/settings.json`, written atomically when settings are saved.
* `$XDG_STATE_HOME/musicsync/musicsync.log`, default
  `~/.local/state/musicsync/musicsync.log`, 2 MB rotating log plus three backups.
* Same state directory: `last-sync.json`, written atomically **only after a
  successful real sync and final verification**. It records timezone-aware time,
  device/source/destination, add/update/delete counts, transferred file bytes,
  ReplayGain status, mirror setting and any cleanup warning. Transfer bytes are
  file content bytes reported by itemization, not SSH/network traffic.
  ReplayGain processed is true/false when its summary is recognized, otherwise null.

Malformed settings stop startup with a configuration error; they are never
silently replaced by defaults. Preview, failure and cancellation leave last-success
history untouched. Logs contain utility diagnostics and filenames, not credentials.

## Tests and integration checks

```fish
cd /path/to/MusicSync
env PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src tests scripts
desktop-file-validate resources/io.github.reason7322.MusicSync.desktop
```

Tests use Python's standard-library unittest, so pytest is not required. Pure
logic and mock command tests do not require a phone. Real rsync tests use only
their own temporary directories. The optional real ReplayGain test needs ffmpeg
and mutagen; it creates a synthetic MP3 in a temporary directory, checks independent
track tags and byte-for-byte skip-existing behavior. These test-only tools are
not application dependencies.

The comprehensive release suite and machine-readable per-test evidence are available via:

```fish
.venv/bin/python scripts/run_release_tests.py
```

This runs all tests, forces Qt Widgets tests offscreen, and saves
`docs/release-test-results.json`. Tests never synchronize real music directories.
Creating the temporary Unix-socket fixture requires a session that permits Unix
sockets; a restrictive sandbox may block that fixture. No linter or type checker
is configured; syntax compilation and the suite's AST process-safety audit are
the current static checks. See [the release-readiness report](docs/release-readiness-report.md)
for the exact tested scope, regressions and physical-device testing gaps.

Explicit real-phone preview through the same application controller:

```fish
.venv/bin/python scripts/integration_check.py
```

`--sync` explicitly selects a real synchronization of the configured library.
The integration harness **refuses large-deletion approvals**. It uses the same
instance lock as the app, so close Music Sync before running it.

Native UI check (opens the window, clicks only Preview, saves a window screenshot):

```fish
.venv/bin/python scripts/gui_check.py --preview --output /tmp/musicsync-preview.png
```

This check is for development, never clicks Sync, and should run with the main
application closed. `QT_QPA_PLATFORM=offscreen` can be supplied externally for
headless widget construction checks; it is not set by the normal application.

## Public application identity

The application ID is **`io.github.reason7322.MusicSync`**. The lowercased author
segment represents the GitHub namespace **Reason7322**, following the
[Desktop Entry reverse-DNS naming convention](https://specifications.freedesktop.org/desktop-entry/latest/file-naming.html).
The desktop filename is `io.github.reason7322.MusicSync.desktop`; the icon basename
and Qt desktop identity use that same ID. The Python distribution/import package
and executable remain `musicsync`; package metadata and the MIT copyright name
Reason7322. No repository URL is advertised before publication.

This replaces the private prototype ID `io.github.reason.MusicSync` before the
first public release. Historical audit artifacts retain that former ID as evidence.
Settings and history stay under their existing `musicsync` XDG directories.
Close any running prototype before using the new build, since the instance-lock
filename also follows the application ID. If the old prototype was installed,
its old desktop entry and icon may remain in the user's XDG data directory;
remove those two obsolete files after checking their contents, then run the
installer below. The installer does not silently delete files from the old ID.
No installed launch files are changed merely by editing this source tree.

## Desktop integration and removal

```fish
cd /path/to/MusicSync
.venv/bin/python scripts/install_desktop.py
```

This installs only the application entry, its custom SVG icon and the `musicsync`
launcher into the user's XDG data directory and `~/.local/bin`. No root access,
autostart entry, service, compositor config or theme setting is installed. The
desktop entry is generated for the actual installation directory with Desktop
Entry quoting; the source template does not contain a developer home path.
Spaces, Unicode and shell metacharacters in installation paths are tested.
After relocating the source directory, regenerate its desktop integration.

To remove those three launch files while keeping project/settings/history:

```fish
.venv/bin/python scripts/install_desktop.py --uninstall
```

The installer/remover refuses unrelated or modified target files. Neither mode
touches the original `syncmusic`, the music library or phone storage. To inspect
configuration manually, use `nvim ~/.config/musicsync/settings.json` after saving
Settings at least once.

## Current limitations and recovery

* Historical Android test-phone testing established healthy-mount preview, real ReplayGain skip,
  write/delete probes, no-change rsync and post-verification. Destructive changes
  and new-track tagging were verified in temporary fixtures. A real stale SFTP
  failure was not deliberately induced; one-remount and cleanup branches are
  covered by mocks. No claim is made that a mock is a physical-phone failure test.
* Symlinks and special files in synchronized trees are rejected; nested mounts
  in the phone tree are rejected. Exclusions support root directories only.
  The remote directory must be inside `/storage/emulated/0`; SD-card roots need
  a future explicitly reviewed extension.
* ReplayGain has an indeterminate progress bar and real textual output. No
  percentage or complete-library tagged fraction is invented. Rsync percentages
  come directly from progress2 and may change as rsync refines its work estimate.
* No unattended syncing, background autostart, automatic undo, content checksums
  or music-player refresh are implemented. Rsync's usual size/mtime comparison
  follows the known-working script; equal-size/equal-mtime content differences
  are not detected by this policy. Auxio may still need its normal library refresh.
* Cancellation is not rollback. Already-completed copies/deletions and ReplayGain
  metadata edits remain. Preview again after fixing a failure. The app never
  deletes PC music. It cannot recover a phone-only file that was deliberately
  removed by mirroring without an independent backup.
* If SFTP is still broken after the single remount, force-stop and reopen KDE
  Connect on the phone, confirm connection, then Preview again. Unexpected mount
  identity errors stop without unmounting that filesystem. Details are in the log.

The original native Wayland verification is preserved in
[the historical verification record](docs/verification.md). Its screenshot was
omitted from the public source tree because it displayed personal paths and
phone information.

## License and publication checks

MIT, copyright 2026 Reason7322. See [LICENSE](LICENSE).
[Publication checks](docs/publication-checks.md) record the portability changes,
current test results, privacy scan scope and remaining manual release checks.
Runtime logs, settings and live-device evidence can contain filenames and device
identifiers; review them before sharing them in issues or commits.
