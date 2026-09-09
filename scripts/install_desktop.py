"""Install/remove Music Sync's three user-local launch files. Never requests sudo."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from musicsync import APP_ID
from musicsync.desktop_integration import apply_files, desktop_argument


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
    try:
        apply_files(files, uninstall=args.uninstall, legacy=legacy)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
