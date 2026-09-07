"""Install/remove Music Sync's three user-local launch files. Never requests sudo."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from musicsync import APP_ID


def desktop_argument(value):
    # Exec quoting followed by Desktop Entry string escaping (two layers).
    # https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html
    escaped = ''.join('\\' + c if c in '\\"`$' else c for c in str(value))
    return '"' + escaped.replace('\\', '\\\\').replace('%', '%%') + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if any(ord(c) < 32 for c in str(ROOT)):
        parser.error('The installation directory must not contain control characters.')
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    launcher = ROOT / 'scripts/musicsync'
    template = (ROOT / 'resources' / f'{APP_ID}.desktop').read_text()
    desktop = template.replace('Exec=musicsync\n', 'Exec=' + desktop_argument(launcher) + '\n').encode()
    # This is a Python argument array, never shell interpolation. repr preserves
    # quotes, dollar signs and other literal characters in the installation path.
    wrapper = f'#!/usr/bin/env python3\nimport os, sys\nos.execv({str(launcher)!r}, [{str(launcher)!r}, *sys.argv[1:]])\n'.encode()
    files = {
        data / 'applications' / f'{APP_ID}.desktop': (desktop, 0o644),
        data / 'icons/hicolor/scalable/apps' / f'{APP_ID}.svg': ((ROOT / 'src/musicsync/icons' / f'{APP_ID}.svg').read_bytes(), 0o644),
        Path.home() / '.local/bin/musicsync': (wrapper, 0o755),
    }
    # Recognize only exact artifacts emitted by the original installer at this
    # same root; this permits upgrading it without overwriting unrelated files.
    legacy = {
        data / 'applications' / f'{APP_ID}.desktop': template.replace('Exec=musicsync\n', f'Exec={launcher}\n').encode(),
        Path.home() / '.local/bin/musicsync': f'#!/bin/sh\nexec {launcher} "$@"\n'.encode(),
    }
    # Preflight all targets so a conflict never causes a partial install.
    for target, (content, _) in files.items():
        if target.is_symlink() or (target.exists() and target.read_bytes() not in (content, legacy.get(target, content))):
            parser.error(f'Refusing to replace/remove an unrelated or modified file: {target}')
    for target, (content, mode) in files.items():
        if args.uninstall:
            if target.exists():
                target.unlink()
                print(f'Removed {target}')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(mode)
            print(f'Installed {target}')


if __name__ == '__main__':
    main()
