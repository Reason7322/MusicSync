"""Build qt6ct/KF against PySide's actual Qt ELF files, never distribution Qt.

The official matching SDK provides private/public headers and build tools only.
Its Qt library entries are replaced with links to the wheel's runtime before
configuring any component. No SDK Qt library is shipped in place of PySide Qt.
"""
import json
import os
from pathlib import Path
import shutil
import tarfile

from assemble import SOURCE, WORK, download, run, sha

THEME = WORK / 'theme'
PREFIX = THEME / 'prefix'
QT_COMMIT = '00823e41aa60e8fe266d5aee328e82ad1ad94348'
KF_VERSION = '6.29.0'
MODULES = ['extra-cmake-modules', 'kconfig', 'karchive', 'ki18n', 'kguiaddons',
           'kcolorscheme', 'kwidgetsaddons', 'breeze-icons', 'kiconthemes']


def build_theme():
    inputs = json.loads((SOURCE / 'packaging/appimage/theme-inputs.json').read_text())
    inputs_dir = THEME / 'inputs'
    sources = THEME / 'sources'
    sdk = THEME / 'sdk'
    sources.mkdir(parents=True, exist_ok=True)
    sdk.mkdir(exist_ok=True)
    from PySide6 import __version__, __file__ as pyside_file
    if __version__ != '6.11.2':
        raise RuntimeError('qt6ct headers and wheel must have the exact same Qt version')
    wheel = Path(pyside_file).parent / 'Qt/lib'
    fingerprint = (sha(SOURCE / 'packaging/appimage/theme-inputs.json') + sha(Path(__file__))
                   + ''.join(sha(p) for p in sorted(wheel.glob('libQt6*.so.6'))))
    stamp = THEME / 'complete'
    if stamp.exists() and stamp.read_text() == fingerprint:
        return
    # Do not extract archives over symlinks to the immutable wheel runtime.
    shutil.rmtree(sdk)
    sdk.mkdir()
    for name, item in inputs.items():
        archive = download(item['url'], inputs_dir / name, item['sha256'])
        if name.endswith('.7z'):
            run(['7z', 'x', '-y', f'-o{sdk}', archive], capture_output=True)
        elif name.endswith(('.tar.xz', '.tar.gz')):
            with tarfile.open(archive) as tar:
                tar.extractall(sources, filter='data')
    qt = sdk
    linked = {}
    for path in list((qt / 'lib').glob('libQt6*.so*')):
        name = path.name.split('.so')[0] + '.so.6'
        runtime = wheel / name
        if not runtime.is_file():
            # SDK-only optional integrations (for example EGLFS) must never
            # become fallback link targets. CMake will fail if one is requested.
            path.unlink()
            continue
        path.unlink()
        path.symlink_to(runtime)
        linked[name] = sha(runtime)
    for runtime in wheel.glob('libicu*.so*'):
        target = qt / 'lib' / runtime.name
        target.unlink(missing_ok=True)
        target.symlink_to(runtime)
    # Generated executables (moc, qtpaths, KConfig compiler) also use this Qt.
    (qt / 'bin/qt.conf').write_text('[Paths]\nPrefix=..\n')
    tool_env = dict(os.environ, LD_LIBRARY_PATH=f'{wheel}:{PREFIX / "lib"}')

    def build_run(args, **kwargs):
        # Build tools such as lrelease may use additional wheel Qt modules. This
        # environment is confined to build subprocesses, never AppRun or users.
        return run(args, env=tool_env, **kwargs)
    common = ['-GNinja', '-DCMAKE_BUILD_TYPE=Release', f'-DCMAKE_PREFIX_PATH={PREFIX};{qt}',
              f'-DCMAKE_INSTALL_PREFIX={PREFIX}', '-DCMAKE_INSTALL_LIBDIR=lib',
              f'-DCMAKE_INSTALL_RPATH={PREFIX / "lib"};{wheel}',
              '-DKDE_INSTALL_LIBDIR=lib', '-DBUILD_TESTING=OFF', '-DBUILD_QCH=OFF',
              '-DBUILD_DESIGNERPLUGIN=OFF', '-DBUILD_DOC=OFF', '-DKCONFIG_USE_QML=OFF',
              '-DBUILD_WITH_QML=OFF', '-DBUILD_PYTHON_BINDINGS=OFF',
              '-DCMAKE_DISABLE_FIND_PACKAGE_Qt6Qml=ON',
              '-DCMAKE_DISABLE_FIND_PACKAGE_Qt6Quick=ON',
              '-DCMAKE_DISABLE_FIND_PACKAGE_Qt6QuickControls2=ON']
    for module in MODULES:
        build = THEME / ('build-' + module)
        options = ['-DKICONTHEMES_USE_QTQUICK=OFF'] if module == 'kiconthemes' else []
        if module == 'kguiaddons':
            # Only color utilities are used by KColorScheme. KDE global shortcut
            # and clipboard helpers are unrelated to Qt's native Wayland QPA.
            options += ['-DWITH_WAYLAND=OFF']
        build_run(['cmake', '-S', sources / f'{module}-{KF_VERSION}', '-B', build, *common, *options])
        build_run(['cmake', '--build', build, '-j8'])
        build_run(['cmake', '--install', build])
    source = sources / ('qt6ct-' + QT_COMMIT)
    run(['patch', '-p1', '-i', inputs_dir / 'qt6ct-kde.patch'], cwd=source)
    # No Qt Quick bridge: the optional package is explicitly disabled above.
    build = THEME / 'build-qt6ct'
    build_run(['cmake', '-S', source, '-B', build, *common,
         f'-DPLUGINDIR={PREFIX}/plugins', '-DCMAKE_REQUIRE_FIND_PACKAGE_KF6Config=ON',
         '-DCMAKE_REQUIRE_FIND_PACKAGE_KF6ColorScheme=ON', '-DCMAKE_REQUIRE_FIND_PACKAGE_KF6IconThemes=ON'])
    build_run(['cmake', '--build', build, '--target', 'qt6ct-qtplugin', 'qt6ct-style', '-j8'])
    # Install only the shared runtime/plugins; not another settings application.
    for subdir in ('qt6ct-common', 'qt6ct-qtplugin', 'qt6ct-style'):
        build_run(['cmake', '--install', build / 'src' / subdir])
    (THEME / 'qt-link-inputs.json').write_text(json.dumps(linked, indent=2) + '\n')
    stamp.write_text(fingerprint)


if __name__ == '__main__':
    build_theme()
