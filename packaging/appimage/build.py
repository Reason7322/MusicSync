"""Inside-container build steps. Source is read-only; outputs live under /work, /out."""
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path('/source')
WORK = Path('/work')


def freeze():
    project = WORK / 'project'
    # Only our generated staging directories; never remove source or user files.
    if project.exists():
        shutil.rmtree(project)
    if (WORK / 'frozen').exists():
        shutil.rmtree(WORK / 'frozen')
    project.mkdir(exist_ok=True)
    shutil.copytree(SOURCE / 'src/musicsync', project / 'musicsync', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(SOURCE / 'packaging/appimage/main.py', project / 'main.py')
    shutil.copy2(SOURCE / 'packaging/appimage/pysidedeploy.spec', project / 'pysidedeploy.spec')
    (WORK / 'frozen').mkdir(exist_ok=True)
    result = subprocess.run(['pyside6-deploy', '-c', str(project / 'pysidedeploy.spec'), '--keep-deployment-files', '-f'],
                            cwd=project, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, flush=True)
    result.check_returncode()
    # pyside6-deploy can return zero even after Nuitka reported a failure.
    if 'FATAL:' in result.stdout or '[DEPLOY] Exception occurred' in result.stdout:
        raise RuntimeError('pyside6-deploy reported a failed freeze; refusing to package a partial deployment.')
    if not (WORK / 'frozen/MusicSync.dist/musicsync.bin').is_file():
        raise RuntimeError('pyside6-deploy did not produce the required standalone executable.')


if __name__ == '__main__':
    from theme_build import build_theme
    build_theme()
    if sys.argv[1] in ('all', 'freeze'):
        freeze()
    if sys.argv[1] in ('all', 'assemble'):
        from assemble import assemble
        assemble()
