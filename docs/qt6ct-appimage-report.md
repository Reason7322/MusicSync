# qt6ct AppImage integration

> Follow-up: [GTK3 platform-theme integration](gtk3-appimage-report.md) records
> the newer artifact and the passing qt6ct regression run with GTK3 included.

This follows the historical [AppImage build report](appimage-build-report.md).
The integration was verified on the existing Fedora/Hyprland Wayland host;
it does not establish portability across arbitrary Linux distributions.

## Build inputs and compatibility

The maintained upstream is [trialuser/qt6ct on OpenCode](https://www.opencode.net/trialuser/qt6ct).
This build uses qt6ct **0.11**, commit
`00823e41aa60e8fe266d5aee328e82ad1ad94348`, plus the checksum-pinned
[upstream KDE integration merge request 9](https://www.opencode.net/trialuser/qt6ct/-/merge_requests/9).
The patch is required for KDE `.colors` files and the KDE icon engine; these
features are not present in the unpatched upstream revision. The patch and its
exact sources accompany the image. It is not represented as an upstream release
that already merged the patch.

`packaging/appimage/theme-inputs.json` records every download URL and SHA-256:
the matching official Qt 6.11.2 SDK archives, qt6ct source/patch, and KDE Frameworks
6.29.0 sources. Qt SDK public/private headers and build tools are used only in
the builder. Before configuring qt6ct or KDE, SDK Qt library entries are replaced
with symlinks to the **actual PySide6 6.11.2 wheel libraries**. Missing wheel
libraries cannot fall back to SDK binaries. Build subprocesses also resolve Qt
against that wheel. The cache key incorporates hashes of those wheel libraries.
`qt-link-inputs.json` records the link inputs. Assembly rejects Qt dependencies
from outside the wheel and removes absolute build RPATHs from the final ELFs.

The local diagnostic first tried Fedora qt6ct binaries in an isolated copy of
the old AppDir. Qt rejected them: Fedora's plugin required
`Qt_6.11_PRIVATE_API`, which the wheel's Qt does not export under that version
name. Both installations reporting Qt 6.11.2 was insufficient for compatibility.
Native/source MusicSync with Fedora's matching Qt successfully loaded the host
qt6ct/style and provided the palette/font/icon reference. These diagnostic host
binaries and paths are not used in production packaging.

## KDE dependency decisions

KConfig, KArchive, KI18n, KGuiAddons, KColorScheme, KIconThemes and BreezeIcons
are built from KDE Frameworks 6.29.0 sources against the same wheel Qt.
Extra CMake Modules and KWidgetsAddons are build dependencies. The qt6ct settings
editor, KWidgetsAddons/IconWidgets libraries, Qt Designer integration and KDE
command-line tools are not copied into the application.

The optional KIconThemes Qt Quick module and qt6ct Quick Controls bridge are
disabled, as are KConfig/KI18n QML, Python bindings, tests and developer docs.
These are not used by this Qt Widgets application. KGuiAddons' separate Wayland
clipboard/shortcut helper integration is disabled; its color utilities remain.
**Qt's Wayland platform plugin and native Wayland operation remain enabled.**

`USE_BreezeIcons=ON` is retained. Removing it could reduce the bundle but would
remove KDE's built-in icon fallback. KDE color-scheme and icon-engine libraries
are retained to support normal qt6ct configuration. The host's analogous eight
KF libraries totalled 28,487,096 uncompressed bytes; most was embedded Breeze
artwork. Final artifact sizes and the exact additional ELF inventory are recorded below.

## Configuration and fallback

MusicSync does not select a personal palette, style, icon theme or font. AppRun
preserves inherited `QT_QPA_PLATFORMTHEME`, `QT_QPA_PLATFORM`,
`QT_STYLE_OVERRIDE` (including an empty value), and external XDG locations. It
does not add host Qt plugin directories. The bundled plugin reads normal
external qt6ct configuration and the user's selected external color/icon data.
The user must have external themes/fonts referenced by their configuration
available; bundling a theme selector does not bundle every possible user theme.
With qt6ct unselected or an unsupported platform theme selected, Qt's ordinary
fallback is used.

## Reproduction

From the repository root, with rootless Podman and build-host Python 3:

```fish
python3 scripts/build_appimage.py
.venv/bin/python scripts/run_release_tests.py
.venv/bin/python -m compileall -q src tests scripts packaging/appimage
desktop-file-validate resources/io.github.reason7322.MusicSync.desktop
python3 scripts/test_appimage.py dist/MusicSync-0.1.0-x86_64.AppImage --gui
python3 scripts/test_appimage_theme.py dist/MusicSync-0.1.0-x86_64.AppImage
```

The last command expects the normal qt6ct Wayland session and needs `strace` and
`readelf` as diagnostic tools. Normal users do not need those tools or Python.
For an optional native Qt reference, capture source MusicSync's `--smoke-test`
stdout and pass that log with `--reference PATH`. Diagnostics stay under ignored
`build/` because they may contain private paths, device details and screenshots.
The theme test changes only temporary XDG configuration, never the active
desktop configuration. No real synchronization is performed by these commands;
the artifact suite's tagging/deletion fixtures use temporary test directories.

The builder adds pinned CMake 3.31.6 and lxml 6.1.3 for KDE/Qt build tools. These
are not runtime dependencies. No host package installation, sudo or Git mutation
is part of the build. Apt binary/source versions are recorded; bit-for-bit
reproducibility and perpetual availability of upstream download URLs are not
claimed.

## Licensing

MusicSync remains MIT. qt6ct is BSD-2-Clause. KDE code has LGPL and additional
per-file notices; Breeze artwork includes LGPL-3.0-or-later and the upstream
artwork clarification. All component license files and corresponding source
archives, including the applied qt6ct patch and build instructions, are supplied.
The added dependencies remain dynamically replaceable in an extracted AppDir.
See [third-party notices](../packaging/appimage/THIRD-PARTY-NOTICES.md), the image's
`usr/share/licenses/musicsync/theme/`, and `dist/bundled-components.json`.

Distribute the matching `MusicSync-0.1.0-x86_64-sources.tar.gz` alongside the image.
The earlier upstream static AppImage runtime provenance limitation remains:
its release does not enumerate all exact Alpine package revisions. This work
does not claim to resolve that pre-existing audit boundary.

## Final artifact and runtime evidence

The new AppImage is `dist/MusicSync-0.1.0-x86_64.AppImage`:

| Artifact measurement | Bytes | MiB |
|---|---:|---:|
| Before qt6ct | 110,381,560 | 105.27 |
| With qt6ct | 118,159,864 | 112.69 |
| Increase | 7,778,304 | 7.42 |

The compressed increase is **7.05%**, including new notices and small diagnostic
changes. The additional ELF files total **29,271,616 uncompressed bytes**. No new
Qt library or additional system shared-library package was needed: the non-KDE
closure already existed in the previous image. The dependency resolver still
checks the complete closure and fails on unresolved entries.

| Additional bundled library/plugin | Uncompressed bytes |
|---|---:|

| `PySide6/qt-plugins/platformthemes/libqt6ct.so` | 77,400 |
| `PySide6/qt-plugins/styles/libqt6ct-style.so` | 39,008 |
| `libKF6Archive.so.6` | 389,512 |
| `libKF6BreezeIcons.so.6` | 26,083,824 |
| `libKF6ColorScheme.so.6` | 138,856 |
| `libKF6ConfigCore.so.6` | 814,904 |
| `libKF6ConfigGui.so.6` | 334,776 |
| `libKF6GuiAddons.so.6` | 397,496 |
| `libKF6I18n.so.6` | 616,528 |
| `libKF6IconThemes.so.6` | 318,464 |
| `libqt6ct-common.so.0.11` | 60,848 |

All eight KF libraries are version 6.29.0. The qt6ct common library's actual SONAME
is `libqt6ct-common.so.0.11`; the plugin resolves that name inside the private
library directory. The unversioned development link is unnecessary at runtime.

| Check | Result | Actual evidence / boundary |
|---|---|---|
| Host plugin diagnostic | PASS (expected rejection) | Isolated old AppDir rejected Fedora private Qt ABI; native Fedora Qt loaded it successfully. |
| Inherited qt6ct environment | PASS | Actual direct type-2 launch reported inherited platform-theme and Wayland request; explicit empty style override remained empty. |
| Bundled platform-theme plugin | PASS | `QT_DEBUG_PLUGINS` and kernel mappings locate `platformthemes/libqt6ct.so` inside the mounted AppImage. |
| Bundled style/common libraries | PASS | `styles/libqt6ct-style.so`, common library and all eight KF libraries loaded inside the same image. |
| Normal external configuration | PASS | `strace openat` on the extracted artifact proved successful opens of the existing qt6ct config and selected external scheme. |
| Configured appearance | PASS | Eight palette roles, font, icon theme, style and style class matched native/source Qt exactly; screenshots were visually inspected. |
| External theme change | PASS | The same image followed a changed KDE `.colors` file via a temporary external XDG config. Active desktop config remained byte-identical. |
| qt6ct unselected | PASS | Direct image launch with platform-theme unset used Qt fallback and started successfully. |
| Unsupported platform theme | PASS | Direct image launch with an unknown theme used Qt fallback and started successfully. |
| Native Wayland | PASS | All seven GUI/theme scenarios reported `wayland`; no XWayland fallback was used. |
| No host Qt injection / second Qt | PASS | Loaded Qt and theme library mappings all point inside the image; debug logs contain no Fedora plugin lookup. |
| Relocatability / private data | PASS | 279 ELF search-path checks were relative; extracted files contained neither the local home path nor Fedora qt6ct runtime/plugin paths. |
| Release suite | PASS | 127 tests, zero failures/errors/skips. Initial sandbox denial for the Unix-socket fixture was resolved by running outside the sandbox. |
| Existing artifact suite | PASS | All 702 extracted manifest hashes; private Python/Qt/rsync/rsgain under restricted PATH; missing host requirements; Unicode relocation; temporary ReplayGain tagging/skip and rsync mirror with thumbnail preservation; first-run and configured Wayland startup. |
| Static checks | PASS | `compileall`, `git diff --check`, desktop-file validation. Desktop validator emits only the pre-existing multiple-main-category hint. No separate lint/type checker is configured. |
| Active configuration and history | PASS | Active qt6ct config unchanged; smoke checks preserved last-successful-sync state. |
| Physical phone sync | NOT TESTED | No real sync, ReplayGain, destination probe or phone filesystem Preview was performed in this theme follow-up. Earlier physical Preview evidence remains in the historical report. |
| Cross-distribution portability | NOT TESTED | Builder is Ubuntu 24.04; live desktop testing is Fedora/Hyprland only. |
| Theme changes while the window stays open | NOT TESTED | External A/B was verified by restarting the identical image, not by editing the active desktop configuration. |

The new artifact test script initially depended on an unavailable host `patchelf`;
it now uses the installed `readelf` for read-only RPATH auditing. No application
feature or sync behavior was changed to make a test pass.

Private evidence is retained in `build/qt6ct/`: `host-diagnostic.log`,
`host-reference.log`, native/AppImage screenshots, `runtime/results.json`,
`runtime/config-access.strace`, `theme-tests.log`, `release-tests.log`, and
`artifact-tests.json`. These files can contain personal data and remain ignored.

## Files changed for this follow-up

* `packaging/appimage/theme-inputs.json` (new): source/SDK/patch pins.
* `packaging/appimage/theme_build.py` (new): compatible Qt/KDE/qt6ct build.
* `packaging/appimage/Containerfile`: isolated build dependencies and pinned tools.
* `packaging/appimage/build.py`: theme build stage before freeze/assembly.
* `packaging/appimage/assemble.py`: plugins, private dependency closure and relative RPATHs.
* `packaging/appimage/licenses.py`: theme provenance, notices and corresponding source.
* `packaging/appimage/THIRD-PARTY-NOTICES.md`: redistribution and dependency notices.
* `src/musicsync/packaging_check.py`: opt-in appearance/mapping/screenshot diagnostics only.
* `tests/test_appimage.py`: launcher environment preservation and build-input checks.
* `scripts/test_appimage_theme.py` (new): actual image theme/external-config/fallback audit.
* `README.md`: theme behavior, build decisions and test instructions.
* `docs/appimage-build-report.md`: historical report follow-up link.
* `docs/release-test-results.json`: refreshed per-test evidence.
* `docs/release-readiness-report.md`: link to the 127-test and theme follow-up results.
* `docs/qt6ct-appimage-report.md` (new): this report.

Other uncommitted AppImage work predates this follow-up and has been preserved.
No Git staging, commits, branch changes or history operations were performed.
