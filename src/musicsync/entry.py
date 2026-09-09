"""Common source/frozen entry; worker dispatch never initializes the GUI."""
import json
import os
import sys


def main():
    args = sys.argv[1:]
    if args in (['--install-desktop'], ['--uninstall-desktop']):
        from musicsync.desktop_integration import integrate_appimage
        try:
            integrate_appimage(uninstall=args == ['--uninstall-desktop'])
        except (OSError, ValueError) as error:
            print(f'MusicSync desktop integration: {error}', file=sys.stderr)
            return 1
        return 0
    if any(arg in ('--install-desktop', '--uninstall-desktop') for arg in args):
        print('Use --install-desktop or --uninstall-desktop alone.', file=sys.stderr)
        return 2
    if len(args) == 2 and args[0] == '--musicsync-worker':
        from musicsync.backend.worker import main as worker_main
        return worker_main(args[1])
    if args == ['--runtime-info']:
        from musicsync.packaging_check import runtime_info
        print(json.dumps(runtime_info(), indent=2))
        return 0
    if len(args) == 2 and args[0] == '--tool-version' and args[1] in ('rsync', 'rsgain'):
        from musicsync.runtime import executable
        program = executable(args[1])
        os.execv(program, [program, '--version'])
    from musicsync.app import main as app_main
    return app_main(test_mode=args[0] if args in (['--smoke-test'], ['--preview-test']) else None)
