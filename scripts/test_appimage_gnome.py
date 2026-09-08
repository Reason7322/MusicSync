#!/usr/bin/env python3
"""Actual GNOME-session dark/light AppImage checks (no music synchronization).

Temporarily changes the two GNOME appearance preferences, restores their exact
original values in finally, and records private evidence under build/ by default.
GTK theme names must be supplied from themes installed in the test desktop; they
are test inputs, never application defaults. Requires Python/gsettings only for
the harness, not for MusicSync itself. Run in the real GNOME Wayland session.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time

SCHEMA = 'org.gnome.desktop.interface'


def command(args):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True,
                          text=True, timeout=20).stdout.strip()


def luminance(color):
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return sum(a * b for a, b in zip(rgb, (.2126, .7152, .0722)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--dark-gtk-theme', required=True)
    parser.add_argument('--light-gtk-theme', required=True)
    parser.add_argument('--output', type=Path, default=Path('build/gtk3/gnome-tests'))
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    assert 'GNOME' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':')
    assert os.environ.get('XDG_SESSION_TYPE') == 'wayland'
    original = {key: command(['gsettings', 'get', SCHEMA, key])
                for key in ('color-scheme', 'gtk-theme')}
    result = dict(original=original, image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                  os_release=platform.freedesktop_os_release(),
                  host_python=platform.python_version(), host_pyside=importlib.util.find_spec('PySide6') is not None,
                  host_tools={name: shutil.which(name) for name in ('kdeconnect-cli', 'sshfs',
                              'fusermount3', 'findmnt', 'mountpoint', 'rsync', 'rsgain')},
                  desktop=os.environ.get('XDG_CURRENT_DESKTOP'), tests={}, result='FAIL')
    try:
        for mode, preference, theme in (('dark', 'prefer-dark', args.dark_gtk_theme),
                                        ('light', 'default', args.light_gtk_theme)):
            # These are the desktop settings changed by GNOME's Appearance UI.
            command(['gsettings', 'set', SCHEMA, 'color-scheme', preference])
            command(['gsettings', 'set', SCHEMA, 'gtk-theme', theme])
            time.sleep(2)
            env = dict(os.environ, QT_DEBUG_PLUGINS='1', QT_LOGGING_RULES='qt.qpa.theme=true;qt.qpa.gtk=true',
                       MUSICSYNC_TEST_SCREENSHOT=str(output / (mode + '.png')))
            # Test the normal automatic GNOME selection, with no forced GTK/Qt theme.
            for name in ('QT_QPA_PLATFORMTHEME', 'QT_QPA_PLATFORM', 'QT_STYLE_OVERRIDE', 'GTK_THEME'):
                env.pop(name, None)
            run = subprocess.run([str(image), '--smoke-test'], env=env, capture_output=True,
                                 text=True, timeout=60)
            (output / (mode + '.log')).write_text(run.stdout + '\n' + run.stderr)
            line = next((s for s in run.stdout.splitlines() if s.startswith('MUSICSYNC_CHECK=')), None)
            assert line, mode + ': image failed to produce runtime evidence'
            check = json.loads(line.split('=', 1)[1])
            result['tests'][mode] = check
            assert check['visible'] and check['qt_platform'] == 'wayland' and check['history_unchanged']
            assert check['appearance']['platform_theme'] is None
            assert 'Successfully created platform theme "gtk3" via QPlatformThemeFactory::create' in run.stderr
            libs = check['appearance']['loaded_theme_libraries']
            assert any(p.endswith('/platformthemes/libqgtk3.so') for p in libs), libs
            assert all(p.startswith(check['appdir'] + '/') for p in libs), libs
            assert all(p.startswith(check['appdir'] + '/') for p in check['loaded_qt_libraries'])
            palette = check['appearance']['palette']
            window, text = luminance(palette['Window']), luminance(palette['WindowText'])
            assert (window < 128 and text > window) if mode == 'dark' else (window > 128 and text < window), palette
            # Missing integrations are expected on the clean test desktop. They
            # must remain a readable warning, not prevent a functional GUI.
            if check['device_status'] == 'Host setup incomplete':
                assert run.returncode == 1 and check['result'] == 'FAIL', check
                assert 'Missing runtime tools:' in check['error']
            else:
                assert run.returncode == 0 and check['result'] == 'PASS', check
        result['result'] = 'PASS'
    finally:
        for key, value in original.items():
            command(['gsettings', 'set', SCHEMA, key, value])
        result['restored'] = {key: command(['gsettings', 'get', SCHEMA, key]) for key in original}
        result['settings_restored'] = result['restored'] == original
        (output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    assert result['settings_restored']
    print('PASS: real GNOME dark/light, bundled GTK3, native Wayland, readable setup status; settings restored.')


if __name__ == '__main__':
    main()
