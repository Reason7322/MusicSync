#!/usr/bin/env python3
"""Test explicit integration on an actual image; no music synchronization.

Default: isolated XDG files only. --host-portal explicitly installs into the
current user's XDG data directory, checks new GUI processes, then uninstalls in
finally. Refuses pre-existing integration files. Requires a desktop session for
--host-portal; ordinary application logs retain their existing XDG behavior.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

APP_ID = 'io.github.reason7322.MusicSync'
WARNING = 'Failed to register with host portal'


def targets(data):
    return [data / 'applications' / (APP_ID + '.desktop'),
            data / 'icons/hicolor/scalable/apps' / (APP_ID + '.svg'),
            data / 'musicsync/appimage-desktop.json']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--host-portal', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('build/desktop-integration/runtime'))
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    original_image = hashlib.sha256(image.read_bytes()).hexdigest()
    result = {'image_sha256': original_image, 'host_test_requested': args.host_portal}

    def run(name, flag, env=None):
        process = subprocess.run([str(image), flag], env=env, capture_output=True, text=True, timeout=60)
        (output / (name + '.log')).write_text(process.stdout + '\n' + process.stderr)
        assert process.returncode == 0, (name, process.returncode, process.stderr, process.stdout)
        return process

    def gui(name):
        process = run(name, '--smoke-test', dict(os.environ, QT_LOGGING_RULES='qt.qpa.services.debug=true'))
        line = next(s for s in process.stdout.splitlines() if s.startswith('MUSICSYNC_CHECK='))
        check = json.loads(line.split('=', 1)[1])
        assert check['visible'] and check['history_unchanged'] and check['qt_platform'] == 'wayland', check
        result[name] = check
        return process

    # Only the outer AppImage mount needs fusermount3; the installer itself
    # needs no host Python, KDE Connect or cache tools.
    with tempfile.TemporaryDirectory(prefix='musicsync-integrate-') as tmp:
        data = Path(tmp) / 'XDG data Ω'
        host_bin = Path(tmp) / 'host-tools'
        host_bin.mkdir()
        (host_bin / 'fusermount3').symlink_to(shutil.which('fusermount3'))
        env = dict(os.environ, XDG_DATA_HOME=str(data), PATH=str(host_bin))
        run('isolated-install', '--install-desktop', env)
        try:
            files = targets(data)
            before = {p: p.read_bytes() for p in files}
            assert json.loads(files[2].read_text())['appimage'] == str(image)
            run('isolated-repeat', '--install-desktop', env)
            assert {p: p.read_bytes() for p in files} == before
        finally:
            run('isolated-uninstall', '--uninstall-desktop', env)
        assert not any(p.exists() for p in targets(data))
        result['isolated'] = 'PASS'

    if args.host_portal:
        data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
        files = targets(data)
        assert not any(p.exists() or p.is_symlink() for p in files), 'Host already has integration; refusing test'
        before = gui('before-install')
        assert WARNING in before.stderr and 'App info not found' in before.stderr
        try:
            run('host-install', '--install-desktop')
            installed = gui('after-install')  # New process and D-Bus connection.
            assert WARNING not in installed.stderr, installed.stderr
            assert 'Successfully registered with host portal as' in installed.stderr, installed.stderr
            result['host_registration'] = 'PASS'
        finally:
            run('host-uninstall', '--uninstall-desktop')
        assert not any(p.exists() for p in files)
        after = gui('after-uninstall')
        assert WARNING in after.stderr and 'App info not found' in after.stderr
        assert not any(p.exists() for p in files), 'Normal launch recreated integration'
        result['normal_launch_does_not_integrate'] = 'PASS'

    assert hashlib.sha256(image.read_bytes()).hexdigest() == original_image
    result['image_unchanged'] = True
    (output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: explicit integration, removal and requested portal checks; AppImage unchanged.')


if __name__ == '__main__':
    main()
