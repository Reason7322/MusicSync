"""Collect notices plus corresponding source, and map every packaged ELF file.

Source archives accompany the AppImage; this is not an unenforceable web-link-only
source offer. Do not distribute the image without the matching source archive.
"""
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

from assemble import SOURCE, WORK, OUT, download, elf, run, sha


def package_for(path):
    path = str(Path(path).resolve())
    for candidate in (path, path.removeprefix('/usr') if path.startswith('/usr/lib/') else '/usr' + path):
        result = subprocess.run(['dpkg-query', '-S', candidate], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.splitlines()[0].rsplit(': ', 1)[0]
    raise RuntimeError('Cannot identify binary provenance: ' + path)


def extract_notices(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        for member in tar:
            name = Path(member.name)
            if not member.isfile() or name.is_absolute() or '..' in name.parts:
                continue
            base = name.name.lower()
            if ('licenses' in [p.lower() for p in name.parts] or
                    base.startswith(('license', 'copying', 'copyright', 'notice')) or base == 'qt_attributions.json'):
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)


def collect_licenses(appdir, provenance, pins):
    notices = appdir / 'usr/share/licenses/musicsync'
    notices.mkdir(parents=True)
    shutil.copy2(SOURCE / 'LICENSE', notices / 'MusicSync-MIT.txt')
    shutil.copytree('/usr/share/common-licenses', notices / 'common-licenses', dirs_exist_ok=True)
    sources = WORK / 'corresponding-source'
    sources.mkdir(exist_ok=True)
    ubuntu = sources / 'ubuntu'
    ubuntu.mkdir(exist_ok=True)
    components, files = {}, {}
    packages = {'python3.12'}  # Nuitka's static Python runtime and stdlib.
    for relative, original in provenance.items():
        if original.startswith(str(WORK / 'theme/prefix') + '/'):
            name = Path(relative).name
            module = {'Archive': 'karchive', 'BreezeIcons': 'breeze-icons', 'ColorScheme': 'kcolorscheme',
                      'ConfigCore': 'kconfig', 'ConfigGui': 'kconfig', 'GuiAddons': 'kguiaddons',
                      'I18n': 'ki18n', 'IconThemes': 'kiconthemes'}.get(name.removeprefix('libKF6').split('.so')[0])
            owner = module or ('qt6ct' if name.startswith('libqt6ct') else None)
            if owner is None:
                raise RuntimeError('Unknown theme-library provenance: ' + original)
        elif original.startswith('/usr/local/') and 'rsgain' in original:
            owner = 'rsgain-3.6'
        elif '/site-packages/' in original:
            owner = 'ICU-73' if Path(relative).name.startswith('libicu') else 'Qt-PySide6-Shiboken6'
        else:
            owner = package_for(original)
            packages.add(owner)
        files[relative] = owner
    for path in appdir.rglob('*'):
        if not elf(path):
            continue
        relative = str(path.relative_to(appdir))
        if relative in files:
            continue
        if path.resolve().name in ('AppRun', 'musicsync.bin'):
            files[relative] = 'MusicSync + Python3.12 + Nuitka-runtime'
        elif path.name.startswith('_') and path.suffix == '.so':
            files[relative] = 'python3.12'
        elif '/PySide6/' in relative or '/shiboken6/' in relative:
            files[relative] = 'Qt-PySide6-Shiboken6'
        else:
            raise RuntimeError('Unaudited ELF file: ' + relative)
    for package in sorted(packages):
        values = run(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}', package], capture_output=True).stdout.split('\t')
        binary, version, source, source_version = values
        copyright_file = Path('/usr/share/doc') / package.split(':')[0] / 'copyright'
        if not copyright_file.is_file():
            raise RuntimeError('Missing package copyright: ' + package)
        text = copyright_file.read_text()
        target = notices / 'ubuntu' / (package.replace(':', '_') + '.copyright')
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(copyright_file, target)
        components[package] = dict(version=version, source=source, source_version=source_version,
                                   licenses=sorted(set(re.findall(r'^License: (.+)$', text, re.M))),
                                   notice=str(target.relative_to(appdir)))
    # Fetch exact Ubuntu source-package versions, including distributor patches
    # and build rules, not just a possibly different upstream tarball.
    unique_sources = sorted({(v['source'], v['source_version']) for v in components.values()})
    for source, version in unique_sources:
        print('Corresponding source:', source, version, flush=True)
        run(['apt-get', 'source', '--download-only', source + '=' + version], cwd=ubuntu,
            stdout=subprocess.DEVNULL)
    upstream = sources / 'upstream'
    upstream.mkdir(exist_ok=True)
    qt_version = '6.11.2'
    urls = {}
    for module in ('qtbase', 'qtsvg', 'qtwayland', 'qtimageformats'):
        name = f'{module}-everywhere-src-{qt_version}.tar.xz'
        urls[name] = f'https://download.qt.io/official_releases/qt/6.11/{qt_version}/submodules/{name}'
    pyside = f'pyside-setup-everywhere-src-{qt_version}.tar.xz'
    urls[pyside] = f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{qt_version}-src/{pyside}'
    urls.update({
        'rsgain-3.6.tar.gz': 'https://codeload.github.com/complexlogic/rsgain/tar.gz/refs/tags/v3.6',
        'icu4c-73_2-src.tgz': 'https://github.com/unicode-org/icu/releases/download/release-73-2/icu4c-73_2-src.tgz',
        'type2-runtime.tar.gz': f'https://codeload.github.com/AppImage/type2-runtime/tar.gz/{pins["runtime"]["commit"]}',
        'fuse-3.15.0.tar.xz': 'https://github.com/libfuse/libfuse/releases/download/fuse-3.15.0/fuse-3.15.0.tar.xz',
        'squashfuse-0.5.2.tar.gz': 'https://codeload.github.com/vasi/squashfuse/tar.gz/0.5.2',
        'musl-1.2.5.tar.gz': 'https://musl.libc.org/releases/musl-1.2.5.tar.gz',
        'zstd-1.5.6.tar.gz': 'https://codeload.github.com/facebook/zstd/tar.gz/v1.5.6',
        'zlib-1.3.2.tar.gz': 'https://codeload.github.com/madler/zlib/tar.gz/refs/tags/v1.3.2',
        'mimalloc-2.1.7.tar.gz': 'https://codeload.github.com/microsoft/mimalloc/tar.gz/v2.1.7',
    })
    def fetch(item):
        name, url = item
        digest = {
            'rsgain-3.6.tar.gz': '26f7acd1ba0851929dc756c93b3b1a6d66d7f2f36b31f744c8181f14d7b5c8a7',
            'fuse-3.15.0.tar.xz': '70589cfd5e1cff7ccd6ac91c86c01be340b227285c5e200baa284e401eea2ca0',
            'squashfuse-0.5.2.tar.gz': 'db0238c5981dabbd80ee09ae15387f390091668ca060a7bc38047912491443d3',
        }.get(name)
        path = download(url, upstream / name, digest)
        extract_notices(path, notices / 'upstream' / name)
        return name, dict(url=url, sha256=sha(path))
    with ThreadPoolExecutor(max_workers=4) as pool:
        upstream_inputs = dict(pool.map(fetch, urls.items()))
    # Include the exact qt6ct/KF sources and upstream patch used by the theme
    # build, plus SDK provenance. SDK binaries are build-only, not redistributed.
    theme_inputs = json.loads((SOURCE / 'packaging/appimage/theme-inputs.json').read_text())
    for name, metadata in theme_inputs.items():
        original = WORK / 'theme/inputs' / name
        if sha(original) != metadata['sha256']:
            raise RuntimeError('Theme source input changed: ' + name)
        if name.endswith('.7z'):
            continue
        shutil.copy2(original, upstream / name)
        if name.endswith(('.tar.xz', '.tar.gz')):
            extract_notices(original, notices / 'theme' / name)
        upstream_inputs[name] = metadata
    shutil.copy2(SOURCE / 'packaging/appimage/theme-inputs.json', sources / 'theme-inputs.json')
    shutil.copy2(WORK / 'theme/qt-link-inputs.json', notices / 'qt-link-inputs.json')
    # Nuitka's runtime has its own runtime exception; preserve it, not just the
    # compiler's Apache license. Wheel licensing metadata is copied verbatim.
    for distribution in ('nuitka', 'PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6'):
        metadata = importlib.metadata.distribution(distribution)
        dest = notices / 'python-packages' / distribution
        dest.mkdir(parents=True)
        (dest / 'METADATA').write_text(metadata.read_text('METADATA') or '')
        for file in metadata.files or ():
            if any(p.lower().startswith(('license', 'copying', 'notice')) for p in file.parts):
                original = metadata.locate_file(file)
                if original.is_file():
                    shutil.copy2(original, dest / file.name)
    run(['python', '-m', 'pip', 'download', '--no-deps', '--no-binary=:all:', 'Nuitka==4.2.1', '-d', upstream], stdout=subprocess.DEVNULL)
    application = sources / 'MusicSync'
    application.mkdir(exist_ok=True)
    for name in ('src', 'scripts', 'packaging', 'tests', 'resources', 'docs'):
        shutil.copytree(SOURCE / name, application / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'release-live-readonly.json'))
    for name in ('README.md', 'LICENSE', 'pyproject.toml'):
        shutil.copy2(SOURCE / name, application / name)
    dpkg = run(['dpkg-query', '-W'], capture_output=True).stdout
    (sources / 'builder-packages.txt').write_text(dpkg)
    (sources / 'python-packages.txt').write_text(run(['python', '-m', 'pip', 'freeze'], capture_output=True).stdout)
    (sources / 'upstream-inputs.json').write_text(json.dumps(upstream_inputs, indent=2) + '\n')
    inventory = dict(ubuntu_components=components, upstream_sources=upstream_inputs, files=files,
                     runtime=dict(**pins['runtime'], note='Official static runtime: libfuse 3.15.0 and squashfuse 0.5.2 are pinned in its recipe. Binary strings identify zstd 1.5.6 and zlib 1.3.2. musl/mimalloc sources follow the Alpine 3.21 recipe; exact APK revisions are not provided in the binary release.'),
                     qt='6.11.2 LGPL-3.0-only plus third-party notices; QtPdf excluded',
                     python='3.12.3 Ubuntu patched build; PSF and bundled notices',
                     musicsync='MIT', nuitka='4.2.1 Apache-2.0 with runtime exception')
    for target in (notices / 'BUNDLED-COMPONENTS.json', OUT / 'bundled-components.json'):
        target.write_text(json.dumps(inventory, indent=2) + '\n')
    shutil.copy2(SOURCE / 'packaging/appimage/THIRD-PARTY-NOTICES.md', notices / 'README.md')
    shutil.copy2(notices / 'BUNDLED-COMPONENTS.json', sources / 'BUNDLED-COMPONENTS.json')
    with tarfile.open(OUT / 'MusicSync-0.1.0-x86_64-sources.tar.gz', 'w:gz', compresslevel=1) as tar:
        tar.add(sources, arcname='MusicSync-corresponding-source')
