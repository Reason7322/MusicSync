"""Build only the Qt6 Kvantum style plugin against this AppImage's wheel Qt.

Never copy the Fedora host plugin: its Qt binary ABI may be incompatible.
The user's theme files and Kvantum selection remain external.
"""
import json
from pathlib import Path
import os
import shutil
import tarfile

from assemble import SOURCE, WORK, download, run, sha
from theme_build import THEME, PREFIX

NAME = 'kvantum-1.1.6.tar.gz'
KWORK = THEME / 'kvantum'


def build_kvantum():
    entry = json.loads((SOURCE / 'packaging/appimage/kvantum-input.json').read_text())[NAME]
    from PySide6 import __file__ as pyside_file
    wheel = Path(pyside_file).parent / 'Qt/lib'
    expected = (sha(SOURCE / 'packaging/appimage/kvantum-input.json') + sha(Path(__file__))
                + ''.join(sha(p) for p in sorted(wheel.glob('libQt6*.so.6'))))
    output = PREFIX / 'plugins/styles/libkvantum.so'
    stamp = KWORK / 'complete'
    if output.exists() and stamp.exists() and stamp.read_text() == expected:
        return

    archive = download(entry['url'], THEME / 'inputs' / NAME, entry['sha256'])
    source_root = THEME / 'sources' / ('Kvantum-' + entry['commit'])
    if not source_root.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(THEME / 'sources', filter='data')
    source = source_root / 'Kvantum'
    if not (source / 'style/CMakeLists.txt').is_file():
        raise RuntimeError('Pinned Kvantum source archive lacks the Qt6 style directory')
    sdk = THEME / 'sdk'
    build = KWORK / 'build'
    build.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, LD_LIBRARY_PATH=f'{wheel}:{PREFIX / "lib"}')
    # Build the plugin alone; no Kvantum Manager, presets, or desktop overrides.
    run(['cmake', '-S', source, '-B', build, '-GNinja',
         '-DCMAKE_BUILD_TYPE=Release', f'-DCMAKE_PREFIX_PATH={PREFIX};{sdk}',
         '-DCMAKE_INSTALL_PREFIX=/usr', '-DWITHOUT_KF=ON',
         f'-DCMAKE_INSTALL_RPATH={PREFIX / "lib"};{wheel}'],
        env=environment)
    run(['cmake', '--build', build, '--target', 'kvantum', '-j2'], env=environment)
    candidates = list((build / 'style').rglob('libkvantum.so'))
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one built Kvantum plugin, found {candidates}')
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidates[0], output)
    stamp.write_text(expected)


if __name__ == '__main__':
    build_kvantum()
