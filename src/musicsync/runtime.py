"""Relocatable private tools, frozen workers and host integration isolation."""
import os
from pathlib import Path
import shutil
import sys

from musicsync import APP_ID

HOST_TOOLS = ('kdeconnect-cli', 'sshfs', 'fusermount3', 'findmnt', 'mountpoint')
PRIVATE_TOOLS = ('rsync', 'rsgain')
SYSTEM_PRESET = '/usr/share/rsgain/presets/no_album.ini'
HOST_VARIABLES = ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'QT_PLUGIN_PATH',
                  'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'QML_IMPORT_PATH',
                  'PYTHONHOME', 'PYTHONPATH', 'GIO_MODULE_DIR', 'GIO_EXTRA_MODULES',
                  'GSETTINGS_SCHEMA_DIR')


def compiled_directory():
    compiled = globals().get('__compiled__')
    # Linux kernel identity avoids launcher argv/cwd and compiler-specific
    # containing_dir behavior. MusicSync already requires Linux /proc mount IDs.
    return Path(os.readlink('/proc/self/exe')).parent if compiled is not None else None


def appdir():
    # APPDIR can belong to another application's launcher. Require our marker.
    value = os.environ.get('APPDIR')
    root = Path(value) if value else None
    if root is None and (directory := compiled_directory()) is not None:
        root = directory.parents[2] if len(directory.parents) >= 3 else None
    if root is not None and (root / 'usr/share/musicsync' / APP_ID).is_file():
        return root
    return None


def tool_program(name):
    root = appdir()
    if name in PRIVATE_TOOLS and root is not None:
        # Never fall back to PATH if the bundle is damaged or incomplete.
        return str(root / 'usr/libexec/musicsync' / name)
    return name


def executable(name):
    program = tool_program(name)
    found = shutil.which(program)
    if found is None:
        kind = 'host integration tool' if name in HOST_TOOLS else 'runtime tool'
        raise OSError(f'Missing {kind}: {name} ({program}).')
    return found


def effective_preset(configured):
    root = appdir()
    if configured == SYSTEM_PRESET and root is not None:
        return str(root / 'usr/share/musicsync/presets/no_album.ini')
    return configured  # Preserve custom paths; never persist a temporary APPDIR.


def worker_invocation(payload):
    directory = compiled_directory()
    if directory is not None:
        return str(directory / 'musicsync.bin'), ['--musicsync-worker', payload]
    return sys.executable, ['-m', 'musicsync.backend.worker', payload]


def host_environment():
    env = dict(os.environ)
    if appdir() is not None and env.get('MUSICSYNC_HOST_ENV_SAVED') == '1':
        for name in HOST_VARIABLES:
            saved = 'MUSICSYNC_HOST_' + name
            if saved in env:
                env[name] = env[saved]
            else:
                env.pop(name, None)
    return env
