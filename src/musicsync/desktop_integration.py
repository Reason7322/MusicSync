"""Explicit desktop installation only; normal startup never calls this module."""
import hashlib
import json
import os
from pathlib import Path

from musicsync import APP_ID


def checked_path(value):
    value = str(value)
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Desktop integration paths must not contain control characters or be empty.')
    value.encode('utf-8')
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('Desktop integration requires absolute paths.')
    return path


def desktop_argument(value):
    # Exec quoting followed by Desktop Entry string escaping (two layers).
    # https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html
    value = str(checked_path(value))
    if '=' in value:
        raise ValueError('Desktop Entry executable paths must not contain an equals sign.')
    escaped = ''.join('\\' + c if c in '\\"`$' else c for c in value)
    return '"' + escaped.replace('\\', '\\\\').replace('%', '%%') + '"'


def apply_files(files, uninstall=False, legacy=None):
    """Shared source/AppImage preflight: never replace modified launch files."""
    legacy = legacy or {}
    for target, (content, _) in files.items():
        checked_path(target)
        if target.is_symlink() or (target.exists() and target.read_bytes() not in (content, legacy.get(target, content))):
            raise ValueError(f'Refusing to replace/remove an unrelated or modified file: {target}')
    for target, (content, mode) in files.items():
        if uninstall:
            if target.exists():
                target.unlink()
                print(f'Removed {target}')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(mode)
            print(f'Installed {target}')


def integrate_appimage(uninstall=False):
    from musicsync.runtime import appdir

    root = appdir()
    if root is None or not os.environ.get('APPIMAGE'):
        raise ValueError('Run this command from the AppImage itself; its runtime must supply APPIMAGE.')
    # APPIMAGE is the runtime's absolute image path, unlike APPDIR/argv[0].
    image = checked_path(os.environ['APPIMAGE'])
    # GIO checks the executable's existence before expanding %% in Exec. A
    # spec-escaped percent path therefore cannot be registered with the portal.
    if '%' in str(image):
        raise ValueError('Desktop integration does not support % in the AppImage path: GIO cannot resolve its escaped Exec entry.')
    if image.is_relative_to(root.resolve()) or image.resolve().is_relative_to(root.resolve()):
        raise ValueError('APPIMAGE must refer to the original image, not its temporary AppDir.')
    if not image.is_file() or not os.access(image, os.X_OK):
        raise ValueError('APPIMAGE must refer to an existing executable AppImage file.')
    quoted = desktop_argument(image)
    data = checked_path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    desktop = data / 'applications' / f'{APP_ID}.desktop'
    icon = data / 'icons/hicolor/scalable/apps' / f'{APP_ID}.svg'
    receipt = data / 'musicsync/appimage-desktop.json'
    template = (root / 'usr/share/applications' / desktop.name).read_text()
    if template.count('Exec=musicsync\n') != 1:
        raise ValueError('The bundled desktop template has an unexpected Exec entry.')
    files = {
        desktop: (template.replace('Exec=musicsync\n', 'Exec=' + quoted + '\n').encode(), 0o644),
        icon: ((root / 'usr/share/icons/hicolor/scalable/apps' / icon.name).read_bytes(), 0o644),
    }
    # A receipt prevents taking ownership of a pre-existing identical icon (for
    # example from a native installation). Exact bytes identify both artifacts;
    # the receipt never supplies deletion paths, which are fixed above.
    if not receipt.exists() and not receipt.is_symlink():
        for target in files:
            if target.exists() or target.is_symlink():
                raise ValueError(f'Refusing to claim a file without an AppImage installation receipt: {target}')
        if uninstall:
            print('No MusicSync AppImage desktop integration is installed.')
            return
    record = {'version': 1, 'application_id': APP_ID, 'appimage': str(image),
              'files': {str(p.relative_to(data)): hashlib.sha256(content).hexdigest()
                        for p, (content, _) in files.items()}}
    files[receipt] = ((json.dumps(record, indent=2, ensure_ascii=True) + '\n').encode(), 0o600)
    apply_files(files, uninstall=uninstall)
