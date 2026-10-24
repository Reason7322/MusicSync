%define pkgname musicsync

# Pure-Python payload: no ELF objects exist to attach debuginfo/debugsource
# data to. rpm 6 (FC44) otherwise auto-generates an empty *-debugsource
# subpackage whose -f file list fails the build, so disable debug packages.
%define debug_package %{nil}

# Native Fedora packaging for MusicSync 0.2.0 (pure-Python PySide6 app).
# The standalone Nuitka AppImage is a separate distribution path
# (packaging/appimage/) and is NOT what this RPM installs: the real Python
# package ships next to the system site-packages and runs on Fedora's own
# python3 + PySide6 + Mutagen, with rsync/rsgain as system utilities.

Name:           %{pkgname}
Version:        0.2.0
Release:        1%{?dist}
Summary:        Safe KDE Connect music mirroring for Linux with bulk rename and undo

License:        MIT
URL:            https://github.com/Reason7322/MusicSyncSettingsIntegration
Source0:        %{name}-%{version}.tar.gz

# Native x86_64 build of the 0.2.0 release (BuildArch pinned for this artifact).
BuildArch:      x86_64

# Build-time only. No compilation step: sources are pure Python and installed
# by file copy; desktop-file-utils validates/normalizes the .desktop entry;
# python3 is needed for the %check syntax pass.
BuildRequires:  desktop-file-utils
BuildRequires:  python3

# Runtime dependencies (verified Fedora 44 package names):
#   python3-pyside6  — Qt bindings (FC44 ships 6.11.x)
#   python3-mutagen  — ID3 tag read/write for manual editing and replay gain
#   rsync, rsgain    — mirror/synchronize + replay-gain staging utilities
Requires:       python3
Requires:       python3-pyside6 >= 6.8
Requires:       python3-mutagen >= 1.47
Requires:       rsync
Requires:       rsgain

%description
MusicSync is a personal desktop utility for previewing and synchronizing a
phone music library (via KDE Connect) to a Linux folder, with replay-gain
staging on import. Version 0.2.0 adds the Bulk Rename workflow inside
Settings: preview proposed renames, selectively approve them, apply, track
sessions, and undo byte-exactly — plus manual filename/ID3 metadata editing.
All music operations are explicit user actions; there is no automatic or
default-approved change.

%prep
%setup -q -n %{name}-%{version}

%build
# Nothing to compile: the AppImage path alone uses Nuitka (pyside6-deploy).

%install
rm -rf %{buildroot}

# Real Python package, installed into the system site-packages.
install -d 0755 "%{buildroot}%{python3_sitelib}/musicsync"
cp -a src/musicsync/. "%{buildroot}%{python3_sitelib}/musicsync/"

# Executable: same entry point as `python3 -m musicsync` (entry.main dispatches
# CLI flags and starts the GUI otherwise). Desktop file uses Exec=musicsync.
install -d 0755 "%{buildroot}%{_bindir}"
cat > "%{buildroot}%{_bindir}/musicsync" <<'PYEOF'
#!/usr/bin/python3
"""Fedora package launcher for MusicSync (see python3 -m musicsync)."""
from musicsync.entry import main

raise SystemExit(main())
PYEOF
chmod 0755 "%{buildroot}%{_bindir}/musicsync"

# XDG integration: keep the established application ID and normal paths.
install -d 0755 "%{buildroot}%{_datadir}/applications"
install -m 0644 resources/io.github.reason7322.MusicSync.desktop \
    "%{buildroot}%{_datadir}/applications/io.github.reason7322.MusicSync.desktop"

# Application icon (scalable SVG), hicolor theme.
install -d 0755 "%{buildroot}%{_datadir}/icons/hicolor/scalable/apps"
install -m 0644 src/musicsync/icons/io.github.reason7322.MusicSync.svg \
    "%{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.reason7322.MusicSync.svg"

# Never ship bytecode: FC44 has no brp-python-bytecompile and the interpreter
# compiles on demand. Strip any __pycache__ trees that leaked into buildroot.
find "%{buildroot}" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || :

%check
desktop-file-validate "%{buildroot}%{_datadir}/applications/io.github.reason7322.MusicSync.desktop"
# Syntax-check every shipped module without importing Qt (no display needed).
python3 -m compileall -q src/musicsync && echo "compileall OK"
# Second net: ensure no bytecode reaches the payload from any build step.
find "%{buildroot}" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || :

%files
%license LICENSE
%doc README.md
%{python3_sitelib}/musicsync
%{_bindir}/musicsync
%{_datadir}/applications/io.github.reason7322.MusicSync.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.reason7322.MusicSync.svg

%post
touch --no-create "%{_datadir}/icons/hicolor" 2>/dev/null || :
update-desktop-database -q "%{_datadir}/applications" >/dev/null 2>&1 || :
gtk-update-icon-cache -f "%{_datadir}/icons/hicolor" >/dev/null 2>&1 || :

%preun
if [ $1 -eq 0 ]; then
    update-desktop-database -q "%{_datadir}/applications" >/dev/null 2>&1 || :
    gtk-update-icon-cache -f "%{_datadir}/icons/hicolor" >/dev/null 2>&1 || :
fi

%changelog
* Sat Oct 24 2026 Reason7322 <reason7322@users.noreply.github.com> - 0.2.0-1
- First native Fedora RPM: real Python app (PySide6 + Mutagen system deps),
  musicsync executable, desktop entry and icon under the established
  io.github.reason7322.MusicSync application ID; built from source commit
  aaa391470d57a2e13a384cfca2058df8529a4034 (Mission 22 state).
