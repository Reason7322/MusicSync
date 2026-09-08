# MusicSync AppImage third-party software

MusicSync itself is MIT licensed, copyright 2026 Reason7322. This does not
relicense the other programs or libraries in this image.

`BUNDLED-COMPONENTS.json` maps packaged ELF files to their provenance and records
Ubuntu package/source versions and source URLs/hashes. `ubuntu/` contains the
distribution's complete copyright notices; `common-licenses/` contains referenced
license texts. `upstream/` contains Qt/PySide and embedded third-party notices,
attributions, AppImage runtime and its dependency notices. `python-packages/`
preserves wheel metadata and Nuitka's runtime license/exception.
`theme/` contains qt6ct and KDE Frameworks notices, including icon artwork terms.
`qt-link-inputs.json` records the exact wheel Qt libraries used to link the theme.

* Qt/PySide6/Shiboken6: LGPLv3 selection for the included Core/Gui/Widgets/DBus/
  Network/OpenGL/SVG/Wayland client/image-format components, with
  their separate third-party licenses. No QtWayland compositor or QtPdf is shipped.
* Python: PSF/Python licensing and additional standard-library component notices.
* qt6ct 0.11: BSD-2-Clause, with the checksum-pinned upstream KDE integration patch.
* Qt's GTK3 platform theme: part of the matching Qt 6.11.2 LGPLv3 distribution.
  GTK3/GDK, GLib/GIO, dconf's GSettings backend, Pango and accessibility libraries
  have LGPL and additional per-file notices. Cairo, HarfBuzz, font/rendering and
  X11 support bring their own licenses. The exact Ubuntu package copyrights and
  corresponding source packages accompany the image, including GTK schemas.
  Package inventories include licenses for source-package files beyond the
  particular shared libraries shipped; consult their complete per-file notices.
* KDE Frameworks 6.29: KConfig, KArchive, KI18n, KGuiAddons, KColorScheme,
  KIconThemes and BreezeIcons carry LGPL and additional per-file license notices.
  Breeze artwork includes its supplied LGPL icon licensing terms. The complete
  component notices and sources are supplied; MusicSync's MIT license does not
  replace them. Build-only Extra CMake Modules and KWidgetsAddons sources/notices
  are included for reproducibility, although their libraries/tools are not shipped.
* Nuitka generated runtime: Apache-2.0 with the supplied runtime exception.
* rsync: GPLv3-or-later. Its independently invoked executable remains GPL software.
* rsgain/preset: BSD-2-Clause; CRC++ BSD-3-Clause. The linked distribution FFmpeg
  and codec libraries carry additional GPL/LGPL and permissive obligations;
  rsgain's BSD license does not erase those obligations.
* Ubuntu libraries: see the per-package copyright files, including FFmpeg/codec,
  GNU runtime, OpenSSL, compression, audio, font, X11 and Wayland dependencies.
* AppImage type-2 runtime: MIT runtime code, statically linked LGPL libfuse and
  permissive squashfuse/musl/compression dependencies; source and upstream build
  scripts/patches accompany the image. This FUSE mounting layer is separate from
  the host KDE Connect/SSHFS service used for music access.

## Redistribution and replacement

Distribute `MusicSync-0.1.0-x86_64-sources.tar.gz` alongside the matching AppImage
with equally accessible download links and no extra charge. It contains the
application/build scripts, exact Ubuntu source packages including patches/build
rules, Qt/PySide module sources, qt6ct/KDE sources and the applied patch,
Nuitka source and AppImage-runtime/dependency
sources. Preserve both notices and source material in downstream redistribution;
a link to an upstream project alone is not a replacement for corresponding source.
No promise to fulfill a future written source offer is made on the owner's behalf.

LGPL libraries are dynamically linked in the extracted AppDir and can be replaced
with compatible modified versions. Run `./MusicSync-0.1.0-x86_64.AppImage
--appimage-extract`, replace the relevant libraries in `squashfs-root/usr/lib/`,
then run `squashfs-root/AppRun`. Rebuild using the accompanying source to change
ABI or the statically linked AppImage mount runtime. MusicSync imposes no
restriction on modification or reverse engineering to debug such modifications.
The AppImage is not signed or locked against modified libraries.

## Audit boundary

The downloaded upstream runtime pins libfuse and squashfuse in its source recipe.
Binary strings identify zstd 1.5.6 and zlib 1.3.2. Its binary release does not
enumerate exact Alpine APK revisions for every permissive static dependency
(including musl/mimalloc). The source/notice set includes those components;
this provenance limitation is recorded in the manifest and build report. Review
the recorded inventory/source bundle before publishing a binary release. No
claim of blanket legal certification is made.
