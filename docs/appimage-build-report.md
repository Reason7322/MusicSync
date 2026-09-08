# MusicSync x86_64 AppImage build and runtime report

> Follow-up: [GTK3 platform-theme integration](gtk3-appimage-report.md) records
> the newer artifact, Ubuntu GNOME dark/light tests and current dependency sizes.
> The measurements below remain the historical initial AppImage snapshot.

Date: **2026-09-08**, Europe/Warsaw. Branch inspected: `appimage-packaging`.

**An actual type-2 AppImage was built and tested on the current Fedora/Hyprland
Wayland desktop.** Its native GUI, private Python/Qt/tools, temporary-library
tagging/mirroring, and a non-destructive Preview against the configured physical
phone passed. No real-library ReplayGain or destructive phone synchronization
was performed. No Git initialization, staging, commits, branch changes, merges,
pushes, tags, or history changes were performed.

This is a tested build candidate for this host, not a claim of compatibility
with arbitrary distributions. The exact Alpine revisions of some permissive
libraries inside the upstream AppImage mount runtime remain a provenance gap.

## Build procedure and outputs

From the repository root, with Python 3, rootless Podman, networking and several
GB of free disk space:

```fish
python3 scripts/build_appimage.py
```

The script uses the official Qt for Python `pyside6-deploy` wrapper, explicitly
selects Nuitka **standalone** mode, assembles an AppDir, gathers notices and
corresponding sources, and invokes official appimagetool with an explicitly
pinned type-2 runtime. There is no Python deployment plugin or inner onefile
executable. Build steps run inside a rootless container; host packages and
configuration are not modified. The source mount is read-only.

The builder uses a digest-pinned Ubuntu 24.04 base, Python 3.12.3 with Ubuntu
patches, PySide6 6.11.2, Nuitka 4.2.1, ordered-set 4.1.0, zstandard 0.25.0 and
patchelf 0.19.1.0. The exact base digest is in `Containerfile`; official
appimagetool/runtime source commits and SHA-256 hashes are in `tools.json`.
The independently built rsgain 3.6 input is also checksum-pinned.

`--skip-container-build` reuses the local builder. `--stage assemble` reuses an
existing successful freeze; **use a full build after changing application code**.
All generated content is under ignored `build/` or `dist/`. Nothing assumes an
existing project venv, a developer home directory, or Fedora paths in the image.
Absolute `/source`, `/work`, `/out` and `/opt/build-python` paths are internal
container paths, not installed-runtime paths.

Artifacts:

* `dist/MusicSync-0.1.0-x86_64.AppImage`: executable application image.
* `dist/MusicSync-0.1.0-x86_64-sources.tar.gz`: accompanying corresponding source.
* `dist/appimage-build-manifest.json`: AppDir file hashes, architecture and tooling.
* `dist/bundled-components.json`: binary/resource provenance, versions and licenses.
* `dist/SHA256SUMS`: final artifact checksums.
* `dist/artifact-sizes.json`: exact byte sizes from the final artifact check.

Final image: **110,381,560 bytes (105.27 MiB)**. Matching source archive:
**616,493,556 bytes (587.93 MiB)**. Both the type-2 header and complete gzip
archive integrity passed. The final image was retested after source/notice
assembly, including the physical-phone Preview and cleanup.

Final file sizes are also recorded with the checksums alongside the artifacts.
The source archive is a build-time snapshot. Final post-build test results,
checksums and this report are supplied separately; documentation within the
source archive can describe the preceding verification run. The application's
23 Python source files match the frozen build inputs.
Keep retained inputs if reproducing a historical build: apt repositories change,
and continuous-release URLs can move. Hash mismatches fail the build instead of
silently accepting new tools. This is version-recorded, not bit-for-bit reproducible.

## Bundled versus host components

| Bundled | Details |
| --- | --- |
| Python | Nuitka standalone runtime/standard library, Ubuntu Python 3.12.3 |
| PySide6/Shiboken6/Qt | 6.11.2; Core, Gui, Widgets, DBus, Network, OpenGL, SVG, Wayland client and required plugins/dependencies |
| MusicSync | Modules, native launcher, application ID marker, desktop entry and SVG icon |
| rsync | Ubuntu 3.2.7 with distribution patches; explicit private executable |
| rsgain | 3.6, built from checksum-verified upstream source; explicit private executable |
| ReplayGain preset | rsgain 3.6 `no_album.ini`, `Album=false`, `PreserveMtimes=false` |
| Shared dependencies | Audio/codec, compression, crypto, fonts, X11/Wayland and other required libraries; full inventory supplied |
| AppImage mounting runtime | Checksum-pinned official static type-2 runtime; separate from phone SSHFS |

Host requirements remain KDE Connect/kdeconnectd and pairing/session state,
`kdeconnect-cli`, `sshfs`, `fusermount3`, `findmnt`, `mountpoint`, session D-Bus,
FUSE kernel support, glibc, graphics drivers and normal desktop/font configuration.
No KDE Connect daemon, credentials, private keys or pairing database is bundled.
QtPdf, QtWaylandCompositor, GTK platform-theme integration and unused printing/
EGLFS plugins are not shipped. Wayland client support is retained; XWayland is
not required by the tested GUI.

AppDir markers and executable-relative discovery select private rsync/rsgain
without PATH fallback. Source/native installs keep host utilities. Only the
logical default system preset maps to the bundled preset; custom presets retain
their paths. A temporary AppImage mount path is never persisted in settings.
QProcess continues to receive argument arrays. Host integration commands receive
the original host loader/Qt environment rather than Nuitka's private library
environment. The launcher neither replaces PATH nor overrides XDG directories.

## Tests and observed results

The complete release suite passed **125 test methods, zero failures, zero errors,
zero skips** in **16.467 seconds**. All per-test/subtest records are in
[`release-test-results.json`](release-test-results.json). Existing safety tests
remain included; no test uses destructive access to the physical music library.

```fish
env QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/run_release_tests.py
python3 -m compileall -q src tests scripts packaging
git diff --check
desktop-file-validate resources/io.github.reason7322.MusicSync.desktop
python3 scripts/test_appimage.py dist/MusicSync-0.1.0-x86_64.AppImage --gui --preview
```

Only the artifact test's explicit `--preview` option uses saved phone settings.
It never invokes real synchronization. The test orchestrator needs host Python
and ffmpeg/ffprobe for disposable fixtures; the application does not.

| Check | Status | Evidence/method |
| --- | --- | --- |
| All previous source/deletion/mount/state/cancel/settings/filename/history safeguards | PASS | Full 125-method offline suite; simulated phone and temporary filesystem/process fixtures |
| Source/native setup and launch contracts | PASS | Existing relocated-tree/fresh-environment launcher and installation tests |
| Packaged first run | PASS | Actual image with temporary HOME/XDG directories: no device configured, explicit device-selection status, config/state outside the image |
| Private versus host executable resolution | PASS | Unit tests, real QProcess literal arguments, then actual image with only integration tools on PATH |
| No host Python/PySide6/Qt/rsync/rsgain selected | PASS | Restricted PATH; frozen Python 3.12.3; `/proc/self/maps` shows loaded Qt ELF libraries inside the image; private tool paths and versions |
| Relocatable resources and custom presets | PASS | Unit tests plus extracted actual AppDir moved to a Unicode/space/metacharacter directory |
| Missing host dependencies | PASS | Simulated startup and actual frozen worker with KDE CLI/SSHFS removed from PATH; useful missing-tools error |
| Native Qt GUI from directly launched image | PASS | `--smoke-test`, normal launch screenshot, compositor reports mapped window with `xwayland=false`; Qt reports `wayland` |
| Bundled ReplayGain processing | PASS | Synthetic temporary MP3: track gain/peak, no album gain; second `-S` run leaves bytes identical |
| Bundled rsync preview | PASS | Temporary Add/Delete fixtures unchanged by `--dry-run` |
| Bundled rsync mirror and thumbnails | PASS | Actual extracted private rsync copies exact bytes, deletes only temporary extra file, preserves `.thumbnails/keep` |
| Actual host KDE Connect discovery | PASS | Physical configured phone reported connected from the AppImage |
| Actual phone Preview | PASS | After user reopened Android KDE Connect: 150-file library, approximately 814.4 MB, zero Add/Update/Delete changes |
| Actual app-created mount cleanup | PASS | Preview log verifies SSHFS identity, dry-run, normal unmount and final mountpoint exit 32; no cleanup warning |
| XDG state/log/history | PASS | Image uses normal external XDG directories; startup/preview logs appended there; last-successful-sync bytes unchanged |
| Existing stale-mount automatic recovery | PASS (simulation) / NOT TESTED (physical) | State-machine regression cases; no stale mounted filesystem was deliberately induced on the real phone |
| Healthy borrowed mount ownership | PASS (simulation) / NOT TESTED (physical in this run) | Existing state-machine tests; real run used an app-created mount |
| Real destructive sync/cancellation/deletion | NOT TESTED | Explicitly outside authorization; tested with mocks/temporary fixtures instead |
| AppDir ELF closure | PASS | 269 ELF entries, no unresolved `ldd` dependency on the tested host |
| Actual image file manifest | PASS | Artifact test extracts the finished image and checks all 621 file hashes and the complete file inventory, including desktop metadata changed by appimagetool |
| Desktop entry/icon/ID/layout | PASS | Public ID `io.github.reason7322.MusicSync`, root desktop/icon links, executable AppRun, Utility category; desktop validator exit 0 |
| Source/command safety and syntax | PASS | Full-suite AST guard and compileall; no configured linter/type checker; `git diff --check` clean |
| Personal-path/device-identifier scan | PASS | Repository and AppDir contents scanned, including binary bytes; no developer home path, private ID or device-name defaults |
| Source/license collection | PASS | Exact Ubuntu source-package versions and patches; Qt/PySide/Nuitka/rsgain/runtime sources, notices, component mapping |
| Complete upstream static-runtime build provenance | PARTIAL | Exact Alpine APK revisions are not enumerated by its upstream binary release; see below |
| Other distributions / older glibc / other CPUs | NOT TESTED | No portability claim beyond this x86_64 Fedora/Hyprland session |

Raw image-test JSON, stderr, build logs and the visual capture remain in ignored
`build/appimage/`, because they contain user paths/device information. They are
not copied into public documentation or the source bundle. The desktop validator
prints a nonfatal hint about both AudioVideo and Utility being main categories.

## Failures investigated and fixes

1. **Frozen worker location:** Nuitka's `__compiled__.containing_dir` did not
   identify the nested installed executable reliably. Linux `/proc/self/exe`
   now supplies the frozen worker directory. Native `python -m` workers remain
   unchanged. Regression coverage checks the executable identity and relocation.
2. **Absent initial mount directory:** the GUI status service treated mountpoint
   exit 1 as a generic error even when KDE had not created its directory yet.
   It now uses the same bounded `mount_path` worker as the sync workflow. Only
   confirmed absence means unmounted; permissions, existing paths and timeouts
   still fail closed. Added missing-directory and timeout/existing-path tests,
   and strengthened the permission test. This was reproduced on the live host.
3. **Deployment failure handling:** the official deploy wrapper can return zero
   after a failed Nuitka run. The build checks fatal output and the required
   artifact. The executable is `musicsync.bin` to avoid colliding with the package
   resource directory; generated staging is cleaned before a new freeze.
4. **Incomplete Qt library closure:** missing Wayland/XCB support libraries caused
   assembly to stop. The isolated builder and dependency collector now supply
   them; unused PDF/GTK/printing/EGLFS components were removed from the package.
5. **Old ReplayGain preset:** the distribution's older preset lacked the explicit
   current mtime behavior. rsgain 3.6 and its matching independent-track preset
   are built privately; no host rsgain or library metadata was changed.
6. **Superseded source package:** an inherited libgcrypt binary's exact source
   version was no longer indexed. The isolated builder upgrades inherited
   packages, then freezes again and requires matching source versions. It never
   substitutes a different source version for an existing binary.
7. **Invalid source response:** a zlib site returned HTML instead of an archive.
   Archive parsing rejected it. The collector uses the official GitHub archive;
   binary strings also corrected the runtime zlib source selection to 1.3.2.
8. **Test-environment restrictions:** the offline Unix-socket fixture required
   running outside the execution sandbox. The actual-image missing-tools fixture
   must retain fusermount3 for the outer image to start. Both were test setup
   issues, not reasons to weaken application safeguards.
9. **Physical phone mount failure:** KDE Connect initially reported mount command
   success without creating a mount. Both restricted and ordinary PATH attempts
   stopped safely. The user force-stopped/reopened Android KDE Connect; the next
   actual-image Preview and cleanup passed. This is evidence of recovery after
   manual Android intervention, not proof of automatic stale-mount recovery.
10. **Manifest timing:** appimagetool adds `X-AppImage-Version` to the root desktop
    entry. Recording hashes before that operation produced a stale desktop hash.
    Manifests/checksums are now generated after image assembly; the actual-image
    test verifies the entire extracted file manifest as a regression check.

## Licenses and redistribution

MusicSync remains **MIT**, copyright 2026 Reason7322. Packaging does not relicense
Qt/PySide, rsync or FFmpeg. Read the included
[`THIRD-PARTY-NOTICES.md`](../packaging/appimage/THIRD-PARTY-NOTICES.md).

The inventory maps **270 ELF/resource entries**, includes **154 Ubuntu binary
packages from 120 distinct source-package versions**, and retains complete
distribution copyright files. Qt/PySide/Shiboken use the LGPLv3 option for the
included components, Python uses PSF/Python notices, Nuitka retains its runtime
exception, rsync carries GPLv3-or-later obligations, and rsgain's BSD-2-Clause
code links FFmpeg/codec libraries with additional GPL/LGPL obligations. The
source archive includes the exact Ubuntu source packages/patches/build rules,
Qt module and PySide sources, Nuitka, rsgain and the static runtime build recipe.

**Publish the matching source archive alongside the AppImage with equally
accessible download links.** Notices alone or upstream links alone are not the
chosen means of meeting source obligations. No future source-offer promise is
made on the publisher's behalf. Compatible modified LGPL libraries can replace
the extracted AppDir libraries; sources/build instructions also permit rebuilds.
There is no signature lock or restriction on reverse engineering for debugging
such modifications.

The official static runtime pins libfuse 3.15.0 and squashfuse 0.5.2, whose
sources/checksums and libfuse patch are supplied. Its binary strings identify
zstd 1.5.6 and zlib 1.3.2. Its recipe uses Alpine 3.21, but its binary release
does not enumerate exact musl/mimalloc and other APK revisions. Their sources
and notices are included, but exact distributor patch provenance is **partial**.
Do not describe this as a complete reproducible audit of that upstream runtime.

## Remaining limitations and release sign-off

* The current Fedora/Hyprland machine is the only physical desktop tested. The
  build baseline is Ubuntu 24.04/glibc 2.39; older systems and alternate graphics
  drivers need their own tests. This is not a universal Linux binary guarantee.
* Cross-distribution release sign-off and complete static-runtime provenance
  remain open. No known functional blocker remains on the tested desktop after
  the phone's KDE Connect service was restarted.
* No destructive real-phone test, induced Wi-Fi loss, forced stale SSHFS mount,
  physical read-only destination, or active-transfer shutdown was attempted.
  Automated simulation/temporary tests cover those logic paths, not hardware.
* A standalone launch logs a nonfatal desktop-portal registration warning if
  the public desktop ID is not installed on the host. The AppImage does not
  silently install desktop integration. Native Widgets still work.
* Host-specific Qt theme plugins may be unavailable to the private runtime.
  The application sets neither a stylesheet nor a forced Qt theme. Exact visual
  parity with every host Qt theme is not claimed.
* The repository intentionally has reviewable uncommitted changes. Git review,
  commit selection, release signing and publication remain the user's work.

## Files changed or added

| File | Change |
| --- | --- |
| `README.md` | Build, runtime tests, dependencies, licensing and limitations |
| `docs/appimage-build-report.md` | This report |
| `docs/release-readiness-report.md` | Link to current follow-up; historical audit retained |
| `docs/release-test-results.json` | Full current test evidence |
| `resources/io.github.reason7322.MusicSync.desktop` | Utility category retained alongside audio categories |
| `src/musicsync/__main__.py` | Shared source/frozen entry dispatch |
| `src/musicsync/app.py` | Opt-in packaged GUI diagnostic hook |
| `src/musicsync/entry.py` | Frozen worker/runtime-info/tool-version/GUI-check entry |
| `src/musicsync/runtime.py` | Private tools, presets, frozen paths and host environment |
| `src/musicsync/packaging_check.py` | Runtime evidence and Preview-only checks |
| `src/musicsync/backend/process.py` | Private command resolution; host environment restoration |
| `src/musicsync/backend/replaygain.py` | Effective relocatable preset |
| `src/musicsync/backend/status.py` | Async host requirements and checked absent mountpoint |
| `src/musicsync/backend/worker.py` | Frozen payload entry and private tools, original host unmount environment |
| `src/musicsync/backend/workflow.py` | Source/frozen helper invocation and effective preset |
| `tests/test_appimage.py` | Eleven packaging boundary tests |
| `tests/test_release_history_status.py` | Absent mountpoint/error regressions |
| `tests/test_release_packaging.py` | Exclude ignored build/dist from source-copy fixtures |
| `scripts/build_appimage.py` | Rootless build entry point |
| `scripts/test_appimage.py` | Repeatable actual-artifact tests; isolated writes and explicit phone Preview |
| `packaging/appimage/Containerfile` | Pinned isolated build environment |
| `packaging/appimage/main.py` | Deployment entry |
| `packaging/appimage/pysidedeploy.spec` | Official deploy/Nuitka standalone configuration |
| `packaging/appimage/build.py` | Freeze and assembly orchestration |
| `packaging/appimage/assemble.py` | AppDir, dependency closure, private RPATHs and image creation |
| `packaging/appimage/AppRun.c` | Relocatable shell-free native launcher |
| `packaging/appimage/tools.json` | Official tool/runtime hashes and commits |
| `packaging/appimage/licenses.py` | Source and notice collector; file provenance inventory |
| `packaging/appimage/THIRD-PARTY-NOTICES.md` | Redistribution/replacement instructions and audit boundary |

Existing `pyproject.toml`, `.gitignore`, MIT `LICENSE`, application name, public
ID and SVG artwork did not require changes. Generated binaries, sources, logs,
screenshots and test music are not source-tree publication inputs.

## Primary references

* [Qt for Python deployment](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)
* [AppDir specification](https://docs.appimage.org/reference/appdir.html)
* [Official appimagetool](https://github.com/AppImage/appimagetool)
* [Pinned type-2 runtime source](https://github.com/AppImage/type2-runtime/tree/75849dce7cc37e4319b633df1f116ca895c71a12)
* [Qt licensing](https://doc.qt.io/qt-6/licensing.html)
* [rsgain 3.6 source](https://github.com/complexlogic/rsgain/tree/v3.6)
* [zlib 1.3.2 source release](https://github.com/madler/zlib/releases/tag/v1.3.2)

## qt6ct follow-up

The original results above are retained as historical verification. See the
[qt6ct integration report](qt6ct-appimage-report.md) for the subsequent compatible
platform-theme/style bundle, additional dependencies, sizes and runtime tests.
