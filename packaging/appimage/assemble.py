"""Assemble an auditable AppDir; use explicit RPATHs, never a global private PATH."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

SOURCE, WORK, OUT = Path('/source'), Path('/work'), Path('/out')
APP_ID = 'io.github.reason7322.MusicSync'
APPDIR = WORK / 'MusicSync.AppDir'
# System ABI / driver entry points belong to the desktop, not a private libc stack.
SYSTEM_LIBS = {'libc.so.6', 'libm.so.6', 'libdl.so.2', 'libpthread.so.0', 'librt.so.1',
               'libresolv.so.2', 'ld-linux-x86-64.so.2', 'libEGL.so.1', 'libGL.so.1',
               'libGLX.so.0', 'libGLdispatch.so.0', 'libOpenGL.so.0'}


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, text=True, **kwargs)


def sha(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def download(url, destination, digest=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        print('Download', url, flush=True)
        temporary = destination.with_suffix(destination.suffix + '.part')
        with urllib.request.urlopen(url, timeout=180) as source, temporary.open('wb') as target:
            shutil.copyfileobj(source, target)
        temporary.replace(destination)
    if digest and sha(destination) != digest:
        raise RuntimeError(f'Checksum mismatch: {destination.name}. Refusing updated or corrupt build input.')
    return destination


def elf(path):
    return path.is_file() and path.open('rb').read(4) == b'\x7fELF'


def dependencies(path):
    result = run(['ldd', path], capture_output=True).stdout
    for line in result.splitlines():
        name = line.strip().split(' ')[0]
        if name in SYSTEM_LIBS:
            continue
        if '=> not found' in line:
            raise RuntimeError(f'Unresolved dependency in {path}: {line}')
        match = re.search(r'=> (/\S+)', line)
        if match:
            yield name, Path(match[1])


def assemble():
    from licenses import collect_licenses
    if APPDIR.exists():
        shutil.rmtree(APPDIR)  # Fixed, generated AppDir only.
    private = APPDIR / 'usr/lib/musicsync'
    shutil.copytree(WORK / 'frozen/MusicSync.dist', private)
    # No PDF viewer: excluding the unused image plugin also avoids shipping QtPdf
    # and Chromium-derived QtWebEngine code solely to decode PDF artwork.
    for name in ('PySide6/qt-plugins/imageformats/libqpdf.so', 'libQt6Pdf.so.6', 'libQt6PrintSupport.so.6',
                 'PySide6/qt-plugins/platforms/libqeglfs.so',
                 'libQt6EglFSDeviceIntegration.so.6', 'libQt6EglFsKmsSupport.so.6'):
        (private / name).unlink(missing_ok=True)
    shutil.rmtree(private / 'PySide6/qt-plugins/egldeviceintegrations', ignore_errors=True)
    shutil.rmtree(private / 'PySide6/qt-plugins/printsupport', ignore_errors=True)
    provenance = {}
    report = ET.parse(WORK / 'nuitka-report.xml')
    for item in list(report.findall('included_dll')) + list(report.findall('included_extension')):
        attrs = item.attrib
        target = private / attrs.get('dest_path', '')
        original = (attrs.get('source_path', '').replace('${sys.prefix}', sys.prefix)
                    .replace('${sys.real_prefix}', sys.base_prefix).replace('${sys.base_prefix}', sys.base_prefix))
        if target.is_file() and original:
            provenance[str(target.relative_to(APPDIR))] = original
    # Retain Qt's GTK3 plugin from the exact wheel supplying the Qt runtime.
    # Never substitute a distribution's Qt platform-theme binary.
    from PySide6 import __file__ as pyside_file
    gtk_plugin = Path(pyside_file).parent / 'Qt/plugins/platformthemes/libqgtk3.so'
    target = private / 'PySide6/qt-plugins/platformthemes/libqgtk3.so'
    shutil.copy2(gtk_plugin, target)
    provenance[str(target.relative_to(APPDIR))] = str(gtk_plugin)
    run(['patchelf', '--force-rpath', '--set-rpath', '$ORIGIN/../../..', target])
    # GSettings must read the user's dconf using a backend compatible with our
    # private GLib, not an arbitrary newer host GIO module. No dconf service or
    # user database is bundled. GTK's own schemas make file dialogs self-contained.
    gio = private / 'gio/modules'
    gio.mkdir(parents=True)
    backend = Path('/usr/lib/x86_64-linux-gnu/gio/modules/libdconfsettings.so')
    shutil.copy2(backend, gio / backend.name)
    provenance[str((gio / backend.name).relative_to(APPDIR))] = str(backend)
    schemas = APPDIR / 'usr/share/musicsync/gtk-schemas'
    schemas.mkdir(parents=True)
    for schema in Path('/usr/share/glib-2.0/schemas').glob('org.gtk.*.gschema.xml'):
        shutil.copy2(schema, schemas / schema.name)
        provenance[str((schemas / schema.name).relative_to(APPDIR))] = str(schema)
    if not list(schemas.glob('*.xml')):
        raise RuntimeError('GTK GSettings schemas are missing')
    run(['glib-compile-schemas', schemas])
    tools = APPDIR / 'usr/libexec/musicsync'
    tool_libs = APPDIR / 'usr/lib/musicsync-tools'
    tools.mkdir(parents=True); tool_libs.mkdir(parents=True)
    for name in ('rsync', 'rsgain'):
        program = Path('/usr/local/bin/rsgain') if name == 'rsgain' else Path('/usr/bin/rsync')
        shutil.copy2(program, tools / name)
        provenance[str((tools / name).relative_to(APPDIR))] = str(program)
        for libname, original in dependencies(program):
            shutil.copy2(original, tool_libs / libname)
            provenance[str((tool_libs / libname).relative_to(APPDIR))] = str(original)
    from theme_build import PREFIX
    for kind, name in (('platformthemes', 'libqt6ct.so'), ('styles', 'libqt6ct-style.so')):
        original = PREFIX / 'plugins' / kind / name
        target = private / 'PySide6/qt-plugins' / kind / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        provenance[str(target.relative_to(APPDIR))] = str(original)
        for libname, origin in dependencies(original):
            target_lib = private / libname
            if not target_lib.exists():
                # SDK Qt entries are symlinks to the exact PySide wheel runtime.
                resolved = origin.resolve()
                if libname.startswith('libQt6') and '/site-packages/PySide6/Qt/lib/' not in str(resolved):
                    raise RuntimeError('Refusing a second Qt runtime: ' + str(origin))
                shutil.copy2(resolved, target_lib)
                provenance[str(target_lib.relative_to(APPDIR))] = str(resolved)
    # Complete the standalone's non-driver dependency closure. Nuitka deliberately
    # omits several libraries expected on conventional desktops; record ours too.
    for path in list(private.rglob('*')):
        if elf(path):
            for libname, original in dependencies(path):
                if not original.is_relative_to(APPDIR):
                    target = private / libname
                    if not target.exists():
                        shutil.copy2(original, target)
                        provenance[str(target.relative_to(APPDIR))] = str(original)
    for path in [*tool_libs.iterdir(), *tools.iterdir()]:
        rpath = '$ORIGIN' if path.parent == tool_libs else '$ORIGIN/../../lib/musicsync-tools'
        run(['patchelf', '--force-rpath', '--set-rpath', rpath, path])
    # Keep Nuitka's relative RPATHs; add the private root for nested Qt plugins.
    for path in private.rglob('*'):
        if elf(path):
            relative = os.path.relpath(private, path.parent)
            previous = run(['patchelf', '--print-rpath', path], capture_output=True).stdout.strip()
            # Theme build staging paths must not survive into the relocatable image.
            previous = ':'.join(entry for entry in previous.split(':') if entry.startswith('$ORIGIN'))
            rpath = ':'.join(filter(None, (f'$ORIGIN/{relative}', previous)))
            run(['patchelf', '--force-rpath', '--set-rpath', rpath, path])
    share = APPDIR / 'usr/share/musicsync'
    (share / 'presets').mkdir(parents=True)
    (share / APP_ID).write_text(APP_ID + '\n')
    preset = Path('/usr/local/share/rsgain/presets/no_album.ini')
    text = preset.read_text()
    if 'Album=false' not in text or 'PreserveMtimes=false' not in text:
        raise RuntimeError('Bundled preset does not preserve independent-track / mtime behavior.')
    shutil.copy2(preset, share / 'presets/no_album.ini')
    provenance[str((share / 'presets/no_album.ini').relative_to(APPDIR))] = str(preset)
    desktop = APPDIR / 'usr/share/applications' / f'{APP_ID}.desktop'
    desktop.parent.mkdir(parents=True)
    shutil.copy2(SOURCE / 'resources' / desktop.name, desktop)
    run(['desktop-file-validate', desktop])
    icon = APPDIR / 'usr/share/icons/hicolor/scalable/apps' / f'{APP_ID}.svg'
    icon.parent.mkdir(parents=True)
    shutil.copy2(SOURCE / 'src/musicsync/icons' / icon.name, icon)
    (APPDIR / desktop.name).symlink_to(desktop.relative_to(APPDIR))
    (APPDIR / icon.name).symlink_to(icon.relative_to(APPDIR))
    (APPDIR / '.DirIcon').symlink_to(icon.name)
    (APPDIR / 'usr/bin').mkdir(parents=True)
    (APPDIR / 'usr/bin/musicsync').symlink_to('../../AppRun')
    run(['gcc', '-O2', '-s', '-o', APPDIR / 'AppRun', SOURCE / 'packaging/appimage/AppRun.c'])
    pins = json.loads((SOURCE / 'packaging/appimage/tools.json').read_text())
    downloaded = {}
    for name, item in pins.items():
        downloaded[name] = download(item['url'], WORK / 'downloads' / name, item['sha256'])
        downloaded[name].chmod(0o755)
    collect_licenses(APPDIR, provenance, pins)
    # Appimagetool runs extracted; no build-host FUSE privilege required.
    tool_dir = WORK / 'appimagetool-extracted'
    tool_dir.mkdir(exist_ok=True)
    if not (tool_dir / 'squashfs-root/AppRun').exists():
        run([downloaded['appimagetool'], '--appimage-extract'], cwd=tool_dir, stdout=subprocess.DEVNULL)
    env = dict(os.environ, ARCH='x86_64', VERSION='0.1.0')
    run([tool_dir / 'squashfs-root/AppRun', '--no-appstream', '--runtime-file', downloaded['runtime'],
         APPDIR, OUT / 'MusicSync-0.1.0-x86_64.AppImage'], env=env)
    # appimagetool adds X-AppImage-Version to the root desktop file. Hash the
    # final tree after that mutation, so the manifest describes the actual image.
    manifest = {'application_id': APP_ID, 'architecture': 'x86_64', 'inner_mode': 'standalone',
                'tools': pins, 'system_libraries': sorted(SYSTEM_LIBS),
                'files': {str(p.relative_to(APPDIR)): sha(p) for p in sorted(APPDIR.rglob('*')) if p.is_file()}}
    (OUT / 'appimage-build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    artifacts = [OUT / name for name in ('MusicSync-0.1.0-x86_64.AppImage',
                 'MusicSync-0.1.0-x86_64-sources.tar.gz', 'appimage-build-manifest.json',
                 'bundled-components.json')]
    (OUT / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in artifacts))
    (OUT / 'artifact-sizes.json').write_text(json.dumps({p.name: p.stat().st_size for p in artifacts}, indent=2) + '\n')
