#!/usr/bin/env python3
"""Read-only GUI theme checks against an actual AppImage on a Wayland desktop.

Never edits the active qt6ct configuration. A/B uses a temporary external XDG
configuration and palette, with the same image. Evidence can contain personal
paths and screenshots: keep the output under ignored build/.
"""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--reference', type=Path, help='Native matching-Qt --smoke-test log')
    parser.add_argument('--output', type=Path, default=Path('build/qt6ct/runtime'))
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'qt6ct/qt6ct.conf'
    original = config.read_bytes()
    results = {'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest()}

    def record(name, command, env):
        env = dict(env, QT_DEBUG_PLUGINS='1', MUSICSYNC_TEST_SCREENSHOT=str(output / (name + '.png')))
        result = subprocess.run([str(a) for a in command], env=env, capture_output=True,
                                text=True, timeout=240)
        (output / (name + '.log')).write_text(result.stdout + '\n' + result.stderr)
        assert '/usr/lib64/qt6/plugins' not in result.stderr, 'Host Qt plugin lookup leaked into the artifact'
        line = next((line for line in result.stdout.splitlines() if line.startswith('MUSICSYNC_CHECK=')), None)
        assert result.returncode == 0 and line, name + ': startup failed; inspect log'
        evidence = json.loads(line.split('=', 1)[1])
        results[name] = evidence
        assert evidence['result'] == 'PASS' and evidence['qt_platform'] == 'wayland', evidence
        assert evidence['history_unchanged'] and evidence['visible'] and evidence['screenshot_saved']
        assert all(p.startswith(evidence['appdir'] + '/') for p in evidence['loaded_qt_libraries'])
        return evidence

    try:
        assert os.environ.get('QT_QPA_PLATFORMTHEME') == 'qt6ct', 'Run from your normal qt6ct session'
        normal = record('normal', [image, '--smoke-test'], os.environ)
        appearance = normal['appearance']
        assert appearance['platform_theme'] == os.environ['QT_QPA_PLATFORMTHEME']
        assert appearance['platform_request'] == os.environ.get('QT_QPA_PLATFORM')
        assert appearance['style_override'] == os.environ.get('QT_STYLE_OVERRIDE')
        libraries = appearance['loaded_theme_libraries']
        assert all(p.startswith(normal['appdir'] + '/') for p in libraries), libraries
        for suffix in ('/platformthemes/libqt6ct.so', '/styles/libqt6ct-style.so'):
            assert any(p.endswith(suffix) for p in libraries), (suffix, libraries)
        assert any('/libqt6ct-common.so' in p for p in libraries)
        assert appearance['style_class'] == 'Qt6CTProxyStyle', appearance
        # A proxy style can pass every qt6ct/palette assertion while silently
        # falling back to Fusion when its configured rendering plugin is absent.
        # Require the *actual* Kvantum shared library to be mapped by Qt.
        selected = configparser.ConfigParser(interpolation=None)
        selected.read_string(original.decode())
        if selected.get('Appearance', 'style', fallback='').lower() == 'kvantum':
            assert any(p.endswith('/styles/libkvantum.so') and p.startswith(normal['appdir'] + '/')
                       for p in libraries), 'Kvantum selected by qt6ct but absent from running AppImage'
            results['bundled_kvantum_loaded'] = True
        if args.reference:
            line = next(line for line in args.reference.read_text().splitlines()
                        if line.startswith('MUSICSYNC_CHECK='))
            reference = json.loads(line.split('=', 1)[1])['appearance']
            for key in ('palette', 'font', 'icon_theme', 'style', 'style_class'):
                assert appearance[key] == reference[key], (key, appearance[key], reference[key])
            results['native_reference_match'] = True
        # Explicit empty override remains empty, rather than being replaced.
        empty = record('empty-style-override', [image, '--smoke-test'],
                       dict(os.environ, QT_STYLE_OVERRIDE=''))
        assert empty['appearance']['style_override'] == ''
        with tempfile.TemporaryDirectory(prefix='musicsync-theme-') as temporary:
            root = Path(temporary)
            copied_config = root / 'config/qt6ct/qt6ct.conf'
            copied_config.parent.mkdir(parents=True)
            settings = configparser.ConfigParser(interpolation=None)
            settings.optionxform = str
            settings.read_string(original.decode())
            external = dict(os.environ, XDG_CONFIG_HOME=str(root / 'config'),
                            XDG_STATE_HOME=str(root / 'state'))
            selected_style = settings.get('Appearance', 'style', fallback='').lower()
            kvantum_style = None
            if selected_style == 'kvantum':
                # The Kvantum engine owns the palette. Copy the actual external
                # theme into a temporary XDG tree; never edit the user's files.
                source = Path.home() / '.config/Kvantum'
                assert (source / 'kvantum.kvconfig').is_file()
                shutil.copytree(source, root / 'config/Kvantum')
                theme = (source / 'kvantum.kvconfig').read_text().split('theme=', 1)[1].splitlines()[0].strip()
                kvantum_style = root / 'config/Kvantum' / theme / (theme + '.kvconfig')
                assert kvantum_style.is_file(), kvantum_style
            with copied_config.open('w') as stream:
                settings.write(stream)
            first = record('external-before', [image, '--smoke-test'], external)
            # KDE .colors support is intentional: a plain qt6ct build loses it.
            scheme = configparser.ConfigParser(interpolation=None)
            scheme.optionxform = str
            scheme['Colors:Window'] = {'BackgroundNormal': '236,240,245', 'ForegroundNormal': '21,32,43'}
            scheme['Colors:View'] = {'BackgroundNormal': '250,247,232', 'ForegroundNormal': '21,32,43'}
            scheme['Colors:Button'] = {'BackgroundNormal': '225,230,235', 'ForegroundNormal': '21,32,43'}
            scheme['General'] = {'Name': 'MusicSync isolated test palette'}
            colors = root / 'external.colors'
            with colors.open('w') as stream:
                scheme.write(stream)
            settings['Appearance']['custom_palette'] = 'true'
            settings['Appearance']['color_scheme_path'] = str(colors)
            with copied_config.open('w') as stream:
                settings.write(stream)
            if kvantum_style:
                text = kvantum_style.read_text()
                edited, changed = re.subn(r'(?m)^window\.color=[^\n]*$',
                                          'window.color=#ecf0f5', text, count=1)
                assert changed == 1
                kvantum_style.write_text(edited)
            second = record('external-after', [image, '--smoke-test'], external)
            assert first['appearance']['palette'] != second['appearance']['palette'], (
                'External Qt/Kvantum theme change was ignored by the AppImage')
            assert second['appearance']['palette']['Window'] == '#ecf0f5', second['appearance']
            results['external_palette_change_without_rebuild'] = True
            for label, theme in (('unset-theme', None), ('unsupported-theme', 'musicsync-unsupported-test')):
                env = dict(external)
                if theme is None:
                    env.pop('QT_QPA_PLATFORMTHEME', None)
                else:
                    env['QT_QPA_PLATFORMTHEME'] = theme
                fallback = record(label, [image, '--smoke-test'], env)
                assert fallback['appearance']['platform_theme'] == theme
            # Trace the extracted *artifact* to avoid ptrace/setuid FUSE helper
            # interactions. Direct type-2 launches are separately tested above.
            subprocess.run([str(image), '--appimage-extract'], cwd=root, check=True,
                           stdout=subprocess.DEVNULL, timeout=120)
            trace = output / 'config-access.strace'
            record('traced-artifact', ['strace', '-f', '-e', 'trace=openat', '-o', trace,
                   root / 'squashfs-root/AppRun', '--smoke-test'], os.environ)
            lines = trace.read_text().splitlines()
            assert any(str(config) in line and '= -1' not in line for line in lines)
            results['normal_external_config_opened'] = True
            source_settings = configparser.ConfigParser(interpolation=None)
            source_settings.read_string(original.decode())
            scheme_path = source_settings.get('Appearance', 'color_scheme_path', fallback='')
            if scheme_path:
                assert any(scheme_path in line and '= -1' not in line for line in lines)
                results['normal_external_scheme_opened'] = True
            appdir = root / 'squashfs-root'
            audited = 0
            for path in appdir.rglob('*'):
                if not path.is_file():
                    continue
                data = path.read_bytes()
                assert str(Path.home()).encode() not in data, path
                for forbidden in (b'/usr/lib64/qt6/plugins', b'/usr/lib64/libqt6ct'):
                    assert forbidden not in data, (path, forbidden)
                if data[:4] == b'\x7fELF' and path.name != 'AppRun':
                    dynamic = subprocess.run(['readelf', '-d', str(path)],
                                             check=True, text=True, capture_output=True).stdout
                    for rpath in re.findall(r'\((?:RUNPATH|RPATH)\).*?\[(.*?)\]', dynamic):
                        assert all(p.startswith('$ORIGIN') for p in rpath.split(':') if p), (path, rpath)
                    audited += 1
            results['relative_elf_search_paths'] = audited
    finally:
        results['active_config_unchanged'] = config.read_bytes() == original
        (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    assert results['active_config_unchanged']
    print('PASS: bundled qt6ct/Kvantum, external config and palette A/B, fallback, Wayland, relative ELF paths.')
    print('Private evidence:', output / 'results.json')


if __name__ == '__main__':
    main()
