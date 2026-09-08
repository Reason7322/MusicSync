# GTK3 platform-theme integration

Audit date: 2026-09-08. This follow-up preserves the earlier
[AppImage](appimage-build-report.md) and [qt6ct](qt6ct-appimage-report.md) reports
as historical evidence. MusicSync remains a native Qt Widgets application.

## Implementation and provenance

The packaging bug was an explicit exclusion of `libqgtk3.so` from the AppDir.
The exact PySide6 **6.11.2** wheel already supplies this plugin built with its
Qt **6.11.2** runtime. Assembly now copies that matching plugin directly from the
wheel, records its provenance, and adjusts its RPATH for Nuitka's flattened
library layout. A separately compiled host Qt plugin is neither needed nor used.
No host Qt search path or second Qt runtime was introduced.

The final platform-theme plugin set is:

* `platformthemes/libqt6ct.so`
* `platformthemes/libqgtk3.so`
* `platformthemes/libqxdgdesktopportal.so`

Qt's observed automatic GNOME candidate order is `ubuntu`, `gtk3`, `gnome`,
`generic`. With no explicit platform theme, `ubuntu` has no plugin and `gtk3`
now succeeds through `QPlatformThemeFactory`. It obtains the external GTK
palette/settings rather than using the built-in Gnome fallback. Explicit
`QT_QPA_PLATFORMTHEME=qt6ct` still wins. No palette, GTK theme, icon theme,
stylesheet or desktop-specific theme environment is forced by MusicSync.

GTK3/GDK and their recursively resolved non-base ELF dependencies are bundled.
A matching private GIO dconf backend and compiled GTK schemas are included, so
GTK does not depend on host binary modules compiled for a different GLib.
AppRun sets private `GIO_MODULE_DIR` and `GSETTINGS_SCHEMA_DIR` and clears the
inherited extra GIO module search path for its private process. Original values
are restored when invoking host integration tools. User Qt/GTK theme variables,
XDG directories, dconf settings, fonts and external theme resources remain
external. No private dconf daemon or settings database is shipped.

The builder is the existing pinned Ubuntu 24.04 container. Additional runtime
package inputs include GTK **3.24.41-4ubuntu1.3**, GLib **2.80.0-6ubuntu3.8**,
dconf **0.40.0-4ubuntu0.1**, Pango **1.52.1+ds-1build1** and AT-SPI
**2.52.0-1build1**. `glib-compile-schemas` is build-only. Full exact ownership,
versions, source URLs and hashes are in `dist/bundled-components.json` and the
notices inside the image. These build-input versions are not runtime host paths.

## Size and additional ELF inventory

The preserved qt6ct-only baseline was **118,159,864 bytes (112.686 MiB)**.
The GTK3 candidate is **124,967,416 bytes (119.178 MiB)**: an increase of
**6,807,552 bytes (6.492 MiB, 5.761%)**. Final published file sizes and hashes
are recorded in `dist/artifact-sizes.json` and `dist/SHA256SUMS`.

There are **36 added ELF objects**, totaling **20,454,052 uncompressed bytes**
before AppImage compression. Some support libraries already existed in the
separate private audio-tool directory; the table identifies additions to the
Qt application closure. No additional KDE Frameworks were needed beyond the
existing qt6ct bundle. The extra objects are:

| Relative to `usr/lib/musicsync/` | Uncompressed bytes |
| --- | ---: |
| `libgtk-3.so.0` | 8,381,185 |
| `libgdk-3.so.0` | 1,074,073 |
| `libpangocairo-1.0.so.0` | 78,049 |
| `libpango-1.0.so.0` | 462,249 |
| `libharfbuzz.so.0` | 1,125,849 |
| `libatk-1.0.so.0` | 187,329 |
| `libcairo-gobject.so.2` | 49,617 |
| `libcairo.so.2` | 1,350,081 |
| `libgdk_pixbuf-2.0.so.0` | 201,297 |
| `libgio-2.0.so.0` | 1,985,161 |
| `libgobject-2.0.so.0` | 425,193 |
| `libgmodule-2.0.so.0` | 28,033 |
| `libpangoft2-1.0.so.0` | 123,625 |
| `libfribidi.so.0` | 127,169 |
| `libepoxy.so.0` | 1,318,521 |
| `libXi.so.6` | 83,233 |
| `libatk-bridge-2.0.so.0` | 261,945 |
| `libXfixes.so.3` | 32,673 |
| `libXext.so.6` | 84,825 |
| `libXcursor.so.1` | 50,177 |
| `libXdamage.so.1` | 20,001 |
| `libXcomposite.so.1` | 19,521 |
| `libXrandr.so.2` | 54,057 |
| `libXinerama.so.1` | 20,009 |
| `libthai.so.0` | 49,841 |
| `libgraphite2.so.3` | 156,209 |
| `libXrender.so.1` | 49,449 |
| `libpixman-1.so.0` | 720,833 |
| `libjpeg.so.8` | 542,889 |
| `libmount.so.1` | 325,113 |
| `libselinux.so.1` | 187,857 |
| `libatspi.so.0` | 260,425 |
| `libdatrie.so.1` | 36,457 |
| `libblkid.so.1` | 245,089 |
| `gio/modules/libdconfsettings.so` | 71,337 |
| `PySide6/qt-plugins/platformthemes/libqgtk3.so` | 264,681 |

## Actual runtime and release tests

| Test | Result | Evidence / scope |
| --- | --- | --- |
| Fedora/Hyprland, explicit qt6ct | PASS | Actual AppImage, inherited selection, bundled theme/style loaded, normal external qt6ct config and scheme opened, native reference palette/font/icons matched. |
| External qt6ct configuration A/B | PASS | Temporary XDG config palette changed the same image without rebuilding; active config unchanged. |
| Unset/unsupported theme on Hyprland | PASS | Actual image starts with Qt fallback; no global GTK override. |
| Ubuntu 26.04.1 LTS GNOME dark | PASS | Actual libvirt VM, `ubuntu:GNOME`, external `prefer-dark` + installed `Yaru-dark`; Window `#2a2a2a`, text `#ffffff`; screenshot inspected. |
| Ubuntu GNOME light | PASS | Same VM and image, external `default` + installed `Yaru`; Window `#fcfcfc`, text `#000000`; screenshot inspected. |
| Automatic GTK3 selection | PASS | Both VM logs show successful `gtk3` factory selection with platform-theme variable unset, and the bundled plugin loaded. |
| Native Wayland | PASS | Actual Fedora and VM runtime reports `wayland`; all loaded Qt libraries are under the mounted image. |
| Private GTK runtime | PASS | VM mappings contain private `libqgtk3.so`, `libgtk-3.so.0`, `libgdk-3.so.0`, `gio/modules/libdconfsettings.so`; no host Qt library. |
| Missing host integration | PASS | VM has no KDE Connect/SSHFS; visible GUI gives `Host setup incomplete` and names missing tools. Diagnostic exit 1 is expected, not a GUI crash. |
| Private Python/tools | PASS | VM runs bundled Python 3.12.3/PySide6 6.11.2 despite no host PySide6; rsync/rsgain resolve inside AppImage. Restricted-PATH artifact test also passes. |
| XDG and history | PASS | VM uses external user config/state; last-success history unchanged. Original GNOME appearance values restored. |
| Full release suite | PASS | 128 test methods, no failures/errors/skips; individual results in `release-test-results.json`. |
| Actual artifact suite | PASS | 756 manifest hashes, relocation to Unicode/metacharacter path, private runtime/tools, first-run/configured GUI, isolated ReplayGain tag/skip and rsync mirror/thumbnail fixtures. |
| Artifact path/RPATH audit | PASS | Whole extracted tree scanned for development home and Fedora Qt paths; ELF library search paths are relative to `$ORIGIN`. |
| Static checks | PASS | Python compileall and Git diff whitespace checks; no linter/type checker is configured. Desktop/checksum/source-archive final checks recorded with final artifacts. |
| Physical-phone destructive sync | NOT TESTED | Not authorized; no real-library ReplayGain, write probe or destructive rsync was performed. |
| Other distributions/desktops | NOT TESTED | No general distribution portability claim. |

The VM harness changes both GNOME `color-scheme` and its legacy `gtk-theme`
setting, using themes already installed in that desktop. These are test inputs,
not shipped defaults. This verifies GTK3 appearance on this Ubuntu installation;
a custom desktop that changes only a portal preference while leaving GTK3
settings unchanged may behave differently. The test restores both values in
`finally`. It tests theme changes across launches, not every live-update path in
an already-open window. GNOME's own Settings UI was not automated.

The VM was inspected directly: Ubuntu **26.04.1 LTS**, no host PySide6,
KDE Connect, SSHFS or rsgain. Contrary to the earlier user description, this
current snapshot does have host rsync and Python 3.14.4; the loaded application
still uses its private rsync and Python. The restricted-PATH test independently
checks absence of those host tools. No package was installed in the VM.

One harness bug was found: its first version required exit 0 before recognizing
the deliberately nonzero missing-host-dependency diagnostic. It was corrected to
require exit 1 with the specific warning, or exit 0 for a successful diagnostic.
Both appearance runs then passed. Initial packaging checks also caught the
missing schema compiler and wheel-layout RPATH; the build inputs and relative
RPATH were fixed before producing this candidate.

## Build, licenses and boundaries

From the repository root, with rootless Podman and network access:

```fish
python3 scripts/build_appimage.py
```

The existing Qt/Nuitka standalone freeze is used inside the type-2 AppImage.
For a notices/assembly-only refresh after a successful current freeze:

```fish
python3 scripts/build_appimage.py --skip-container-build --stage assemble
```

Run the full release suite, then the actual artifact and desktop tests:

```fish
.venv/bin/python scripts/run_release_tests.py
python3 scripts/test_appimage.py dist/MusicSync-0.1.0-x86_64.AppImage --gui
python3 scripts/test_appimage_theme.py dist/MusicSync-0.1.0-x86_64.AppImage
# In the Ubuntu GNOME Wayland session:
python3 scripts/test_appimage_gnome.py MusicSync.AppImage --dark-gtk-theme Yaru-dark --light-gtk-theme Yaru
```

MusicSync stays MIT. Qt's GTK plugin is included under LGPLv3; GTK, GLib, dconf,
Pango and accessibility components add LGPL and per-file terms. Cairo,
HarfBuzz, rendering and X11 libraries have their own notices. Exact distribution
copyright files and corresponding source packages are collected automatically,
including the GTK schemas. Distribute the matching `-sources.tar.gz` alongside
the binary, preserve notices, and retain the documented ability to replace
LGPL libraries in an extracted AppDir. See [third-party notices](../packaging/appimage/THIRD-PARTY-NOTICES.md).

The pre-existing upstream AppImage mount runtime's incomplete exact Alpine APK
revision provenance remains recorded in the earlier report. GTK integration
does not resolve that redistribution-review limitation. Host glibc, graphics
drivers, desktop session/D-Bus, fonts and selected external GTK themes remain
required. Host KDE Connect/pairing, SSHFS, fusermount3, findmnt and mountpoint
remain integration requirements. Optional arbitrary host Qt/GTK binary modules
are not promised compatible with the private runtime.

Private logs/screenshots and detailed mappings remain in ignored `build/gtk3/`:
`vm-evidence/`, `qt6ct-regression/`, `artifact-tests.json`, `release-tests.log`,
and the dependency/baseline records. They contain user paths and should not be
published. All real synchronization tests used temporary fixtures; the phone's
music directory was untouched. No Git staging/history operations were performed.

## Files changed in this GTK3 follow-up

* `packaging/appimage/Containerfile`: private GTK/dconf runtime and schema compiler.
* `packaging/appimage/assemble.py`: exact-wheel plugin, closure, schemas and RPATH.
* `packaging/appimage/AppRun.c`: private GIO/schema environment with original values saved.
* `packaging/appimage/THIRD-PARTY-NOTICES.md`: GTK dependency and licensing notices.
* `src/musicsync/runtime.py`: original GIO/schema environment restored for host tools.
* `src/musicsync/packaging_check.py`: opt-in loaded GTK/dconf mapping evidence.
* `tests/test_appimage.py`: environment preservation/restoration regression checks.
* `scripts/test_appimage_gnome.py` (new): real GNOME appearance harness.
* `README.md`: GTK behavior and test instructions.
* `docs/release-test-results.json`: refreshed complete release results.
* `docs/release-readiness-report.md`, `docs/appimage-build-report.md`,
  `docs/qt6ct-appimage-report.md`: follow-up links, historical evidence preserved.
* `docs/gtk3-appimage-report.md` (new): this report.

Other uncommitted AppImage changes predate this request and were preserved.
