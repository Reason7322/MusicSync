#!/usr/bin/env python3
"""Rootless standalone Qt/Nuitka -> AppDir -> type-2 AppImage; never touches Git."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-container-build', action='store_true', help='Reuse the existing local builder image')
    parser.add_argument('--stage', choices=['freeze', 'assemble', 'all'], default='all')
    args = parser.parse_args()
    work = ROOT / 'build/appimage'
    work.mkdir(parents=True, exist_ok=True)
    (ROOT / 'dist').mkdir(exist_ok=True)
    image = 'localhost/musicsync-appimage-builder'
    if not args.skip_container_build:
        subprocess.run(['podman', 'build', '-t', image, '-f', str(ROOT / 'packaging/appimage/Containerfile'),
                        str(ROOT / 'packaging/appimage')], check=True)
    subprocess.run(['podman', 'run', '--rm', '--security-opt=label=disable',
                    '-v', f'{ROOT}:/source:ro', '-v', f'{work}:/work:rw',
                    '-v', f'{ROOT / "dist"}:/out:rw', image,
                    'python', '/source/packaging/appimage/build.py', args.stage], check=True)


if __name__ == '__main__':
    main()
