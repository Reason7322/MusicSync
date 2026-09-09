# Explicit AppImage desktop integration

Verified 2026-09-09 on the current Fedora/Hyprland Wayland desktop, with
Qt 6.11.2 and host xdg-desktop-portal 1.22.1. No Git staging, commits, branch
changes or history operations were performed.

## Cause and implementation

The host had no `io.github.reason7322.MusicSync.desktop` in its XDG application
directories. Qt registers `QGuiApplication::desktopFileName()` with the host
portal. The portal requires GIO to resolve that desktop ID in its own application
search directories; the matching entry inside the mounted AppImage does not
install it into the host's database.

`--install-desktop` and `--uninstall-desktop` now dispatch before GUI startup.
They use the runtime's absolute `APPIMAGE` value, not `APPDIR`, `argv[0]` or the
frozen executable. The installer does not modify or relocate the AppImage.

The existing source installer's Desktop Entry quoting and file preflight/write
code were moved into a shared module and reused. AppImage installation adds a
receipt to distinguish its files from native integration or pre-existing icons.
It writes only the desktop entry, SVG and receipt under the user's XDG data
directory. The receipt records the image path and exact generated-content hashes;
it never supplies arbitrary deletion paths. Conflicting/modified files and
symlink targets are refused before integration files change. Uninstall requires
the matching receipt and generated content and leaves directories intact.

No cache/database tools, shell commands, root privileges, extra packaging
dependencies, changed application ID or warning filters were introduced. The
synchronization workflow, settings and GUI layout were not edited in this task.
The previously requested `mirror=False` working-tree change was preserved and
is included in the rebuilt image.

References:

* [Qt registration code](https://github.com/qt/qtbase/blob/v6.11.2/src/gui/platform/unix/qdesktopunixservices.cpp#L347-L370)
* [Portal application lookup](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/src/xdp-app-info.c#L95-L130)
* [Desktop Entry Exec specification](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html)
* [AppImage runtime environment](https://docs.appimage.org/packaging-guide/environment-variables.html)

## Test results

| Test | Result | Method |
| --- | --- | --- |
| New desktop-integration tests | PASS | Nine test methods using temporary image fixtures, AppDir and XDG directories. |
| Full offline release suite | PASS | 138 test methods, 16.662 seconds, no failures/errors/skips; includes the previous source installer and synchronization safety tests. |
| Spaces, Unicode, quotes and shell metacharacters | PASS | `desktop-file-validate` plus actual `gio launch` of a harmless fixture verifies exact executable/argv, without using shell parsing as the test oracle. |
| Unsafe paths | PASS | Empty/relative/control-character paths, NUL in direct path validation, `=` executable paths, missing runtime and mounted-AppDir targets rejected. |
| Ownership and removal | PASS | Repeated install/uninstall; unrelated files, identical unowned icons, changed desktop/icon/receipt and symlink targets protected. Image fixture bytes unchanged. |
| XDG defaults and override | PASS | Explicit Unicode XDG directory and missing/empty `XDG_DATA_HOME` default tested without accessing the real home. |
| Explicit dispatch only | PASS | Flags bypass GUI; malformed flag combinations fail; ordinary entry does not call integration. |
| Actual packaged installer | PASS | Install/repeat/uninstall with PATH containing only the outer AppImage's required fusermount3. No host Python, KDE Connect or cache tools available to the installer. |
| Raw image before host integration | PASS | New actual AppImage process emits the reported missing-app-info warning. GUI is visible on native Wayland. |
| After explicit host integration | PASS | New actual AppImage process emits successful portal registration, with no registration warning. |
| After explicit uninstall | PASS | New actual AppImage process still starts on native Wayland. The missing-app-info warning returns and none of the three integration files is recreated. |
| Actual artifact regression suite | PASS | 756 manifest entries, private runtime/tools, relocated AppDir, temporary ReplayGain/rsync tests, first-run and configured GUI. No real-library writes. |
| No integration writes on startup | PASS | Matching AppDir traced after uninstall; only existing application log/runtime-lock host writes were observed. No entry/icon/receipt writes. |
| Static/archive checks | PASS | compileall, diff whitespace check, artifact SHA-256 verification and source archive gzip integrity. No linter/type checker is configured. |
| Other desktop portal implementations | NOT TESTED | This follow-up's live integration test is Fedora/Hyprland; prior Ubuntu appearance testing is separate historical evidence. |

Exact Qt messages, from different AppImage processes using the same artifact:

```text
Before: Failed to register with host portal ... App info not found for 'io.github.reason7322.MusicSync'
After install: Successfully registered with host portal as "io.github.reason7322.MusicSync"
After uninstall: Failed to register with host portal ... App info not found for 'io.github.reason7322.MusicSync'
```

The automated registration checks use `--smoke-test`: normal GUI startup with
read-only status checks and automatic closure, never Preview or Sync. A separate
no-argument launch also displayed a mapped native Wayland window. Its compositor
close command failed, so the test process was terminated; normal graceful
closure is established by the smoke tests, not that attempt.

Tracing the outer AppImage prevented its FUSE helper from mounting under ptrace.
The filesystem trace therefore used the matching built AppDir, separately from
the successful direct-AppImage tests. A claim of literally zero host writes
would be incorrect: MusicSync's existing XDG state log and transient instance
lock still operate. This feature adds no automatic integration writes and does
not disable normal logging/locking. No desktop-database refresh was needed.

The test restored the host to its initially unintegrated state: entry, icon and
receipt are absent. It did not alter saved settings or last-success history,
mount the phone, process real music, or run a real synchronization.

## Artifact and review

Artifact: `dist/MusicSync-0.1.0-x86_64.AppImage`, **124,983,800 bytes**.
SHA-256:

```text
75301ed767046e20572d666c966aa401aa0e6761e47eadc0354af53fdf6cbe30
```

The existing container/dependency set was reused:

```fish
python3 scripts/build_appimage.py --skip-container-build --stage freeze
python3 scripts/build_appimage.py --skip-container-build --stage assemble
python3 scripts/test_appimage_desktop.py dist/MusicSync-0.1.0-x86_64.AppImage --host-portal
```

Files changed for this task:

* `src/musicsync/desktop_integration.py` (new): shared quoting/preflight and AppImage integration/ownership.
* `src/musicsync/entry.py`: explicit command dispatch before GUI initialization.
* `scripts/install_desktop.py`: reuse the shared implementation for source installs.
* `tests/test_desktop_integration.py` (new): isolated regression tests.
* `scripts/test_appimage_desktop.py` (new): actual packaged/host portal test harness.
* `README.md`: user-controlled installation, removal, path and ownership behavior.
* `docs/desktop-integration-report.md` (new): this report.

The earlier mirror-default edits remain uncommitted and were not rewritten by
this task. Detailed evidence stays under ignored `build/desktop-integration/`,
including `runtime/results.json`, process logs, `artifact-tests.json`,
`release-tests.log`, and `appdir-writes.strace`. Those diagnostics contain local
paths and should remain private.

## Limitations

* Install from a permanent image path; uninstall using the original image before
  relocation or a differently named replacement. The installer refuses conflicts
  instead of silently taking over another installation or erasing manual edits.
* `%` in the image path is rejected. Current GIO validates the executable before
  expanding the Desktop Entry `%%` escape, so such an entry fails lookup even
  when its syntax validates. This was reproduced and the rejection added before
  the passing test run. Source installer percent escaping remains unchanged.
* The ownership preflight prevents detected conflicts; it is not a filesystem
  transaction protecting against concurrent external edits or arbitrary I/O
  failures. Unrecognized partial installation files require manual review.
* No new third-party dependencies or licensing obligations were added. The
  existing AppImage source-distribution and runtime-provenance notes still apply.
