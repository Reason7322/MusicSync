import ast
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP_ID = 'io.github.reason7322.MusicSync'


def installer_module():
    spec = importlib.util.spec_from_file_location('release_installer', ROOT / 'scripts/install_desktop.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def relocated_tree():
    with tempfile.TemporaryDirectory(prefix='musicsync-release-') as tmp:
        base = Path(tmp)
        root = base / 'Music Sync $cash `literal` "quote" \'apostrophe\' %percent & semi; Ω'
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.venv', '__pycache__', '.git', '*.pyc', 'build', 'dist'))
        home = base / 'isolated-home'
        home.mkdir()
        yield root, home


class PackagingReleaseTests(unittest.TestCase):
    def test_installer_is_relocatable_and_does_not_modify_real_home(self):
        with relocated_tree() as (root, home):
            env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home / 'data'))
            result = subprocess.run([sys.executable, str(root / 'scripts/install_desktop.py')], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            desktop = home / 'data/applications' / f'{APP_ID}.desktop'
            self.assertTrue(desktop.exists())
            self.assertNotIn(str(Path.home()), desktop.read_text())
            validation = subprocess.run(['desktop-file-validate', str(desktop)], capture_output=True, text=True, timeout=10)
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
            wrapper = home / '.local/bin/musicsync'
            self.assertTrue(os.access(wrapper, os.X_OK))
            # Harmless fake interpreter validates exact launcher path/argv without
            # opening any UI or invoking tools against the real phone.
            (root / '.venv/bin').mkdir(parents=True)
            fake = root / '.venv/bin/python'
            marker = home / 'argv.json'
            fake.write_text(f'#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\nPath({str(marker)!r}).write_text(json.dumps(sys.argv[1:]))\n')
            fake.chmod(0o755)
            forwarded = '$(touch PWNED); "quotes" and spaces'
            launch = subprocess.run([str(wrapper), forwarded], env=env, capture_output=True, timeout=10, cwd=home)
            self.assertEqual(launch.returncode, 0, launch.stderr)
            self.assertEqual(json.loads(marker.read_text()), ['-m', 'musicsync', forwarded])
            self.assertFalse((home / 'PWNED').exists())
            again = subprocess.run([sys.executable, str(root / 'scripts/install_desktop.py')], env=env, capture_output=True, timeout=10)
            self.assertEqual(again.returncode, 0, again.stderr)
            removed = subprocess.run([sys.executable, str(root / 'scripts/install_desktop.py'), '--uninstall'], env=env, capture_output=True, timeout=10)
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertFalse(desktop.exists())
            self.assertFalse(wrapper.exists())

    def test_installer_refuses_unrelated_existing_files_before_any_write(self):
        module = installer_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            conflict = home / '.local/bin/musicsync'
            conflict.parent.mkdir(parents=True)
            conflict.write_text('unrelated executable')
            with patch.dict(os.environ, {'HOME': tmp, 'XDG_DATA_HOME': str(home / 'data')}), patch.object(sys, 'argv', ['install_desktop.py']):
                with self.assertRaises(SystemExit):
                    module.main()
            self.assertEqual(conflict.read_text(), 'unrelated executable')
            self.assertFalse((home / 'data/applications').exists())

    def test_desktop_template_and_pyproject_metadata(self):
        result = subprocess.run(['desktop-file-validate', str(ROOT / 'resources' / f'{APP_ID}.desktop')], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        self.assertEqual(data['project']['gui-scripts']['musicsync'], 'musicsync.app:main')
        self.assertIn('icons/*.svg', data['tool']['setuptools']['package-data']['musicsync'])
        self.assertEqual(data['project']['license'], 'MIT')
        self.assertEqual(data['project']['license-files'], ['LICENSE'])
        self.assertIn('Copyright (c) 2026 Reason7322', (ROOT / 'LICENSE').read_text())
        self.assertEqual(data['project']['authors'], [{'name': 'Reason7322'}])

    def test_application_identity_is_consistent(self):
        from musicsync import APP_ID as runtime_id
        self.assertEqual(runtime_id, APP_ID)
        self.assertEqual(installer_module().APP_ID, runtime_id)
        self.assertEqual([p.name for p in (ROOT / 'resources').glob('*.desktop')], [runtime_id + '.desktop'])
        self.assertEqual([p.name for p in (ROOT / 'src/musicsync/icons').glob('*.svg')], [runtime_id + '.svg'])
        desktop = (ROOT / 'resources' / f'{runtime_id}.desktop').read_text()
        self.assertIn(f'Icon={runtime_id}\n', desktop)
        self.assertIn(f'**`{runtime_id}`**', (ROOT / 'README.md').read_text())

    def test_real_qt_honors_isolated_xdg_music_directory(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-xdg-') as tmp:
            home = Path(tmp)
            config = home / 'config'
            config.mkdir()
            (config / 'user-dirs.dirs').write_text('XDG_MUSIC_DIR="$HOME/Música & audio"\n')
            env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=str(config), PYTHONPATH=str(ROOT / 'src'))
            code = 'import json; from musicsync.settings import Settings; s=Settings.load(); print(json.dumps([s.source,s.device_id]))'
            result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [str(home / 'Música & audio'), ''])
            self.assertFalse((home / 'Música & audio').exists())
            self.assertFalse((config / 'musicsync').exists())

    def test_external_command_ast_has_no_shell_interpolation_or_gui_waits(self):
        violations = []
        for path in (ROOT / 'src').rglob('*.py'):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    if name in {'os.system', 'os.popen', 'subprocess.run', 'subprocess.call', 'subprocess.Popen', 'subprocess.check_call'} or name.endswith('.waitForFinished'):
                        violations.append(f'{path.name}:{node.lineno}: {name}')
                    if any(k.arg == 'shell' and not (isinstance(k.value, ast.Constant) and k.value.value is False) for k in node.keywords):
                        violations.append(f'{path.name}:{node.lineno}: shell keyword')
                if isinstance(node, (ast.List, ast.Tuple)):
                    items = [n.value if isinstance(n, ast.Constant) else None for n in node.elts]
                    if len(items) >= 2 and items[0] in ['sh', '/bin/sh', 'bash', '/bin/bash', 'fish'] and items[1] == '-c':
                        violations.append(f'{path.name}:{node.lineno}: shell -c')
        self.assertEqual(violations, [])

    def test_fresh_source_copy_setup_and_launch_from_unrelated_cwd(self):
        self.fresh_source_launch(configured=True)

    def test_fresh_source_copy_first_run_without_saved_config(self):
        self.fresh_source_launch(configured=False)

    def fresh_source_launch(self, configured):
        # A relocated source snapshot is NOT claimed to be a real Git checkout.
        with relocated_tree() as (root, home):
            setup = subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages', str(root / '.venv')], capture_output=True, text=True, timeout=60)
            self.assertEqual(setup.returncode, 0, setup.stderr)
            python = root / '.venv/bin/python'
            probe = subprocess.run([str(python), '-c', 'import PySide6; print(PySide6.__version__)'], capture_output=True, text=True, timeout=20)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            library = home / 'Music'
            library.mkdir(); (library / 'fixture.mp3').write_text('fixture, not decoded')
            config = home / 'config/musicsync'
            if configured:
                config.mkdir(parents=True)
                (config / 'settings.json').write_text(json.dumps({'source': str(library), 'device_id': 'release-fixture', 'device_name': 'Fixture phone'}))
            expected = 'Device status: ' + ('Disconnected' if configured else 'Choose a device in Settings')
            fakebin = home / 'bin'; fakebin.mkdir()
            cli = fakebin / 'kdeconnect-cli'
            cli.write_text(f'#!{sys.executable}\n# No real D-Bus/device access in the setup smoke test.\nraise SystemExit(0)\n')
            cli.chmod(0o755)
            runtime = home / 'runtime'; runtime.mkdir(mode=0o700)
            env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'), XDG_STATE_HOME=str(home / 'state'), XDG_RUNTIME_DIR=str(runtime), QT_QPA_PLATFORM='offscreen', PATH=str(fakebin) + os.pathsep + os.environ['PATH'])
            process = subprocess.Popen([str(root / 'scripts/musicsync')], env=env, cwd=home, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                log = home / 'state/musicsync/musicsync.log'
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and process.poll() is None:
                    if log.exists() and expected in log.read_text():
                        break
                    time.sleep(.05)
                self.assertIsNone(process.poll(), process.stderr.read().decode() if process.poll() is not None else '')
                self.assertIn('Qt platform=offscreen', log.read_text())
                self.assertIn(expected, log.read_text())
                if not configured:
                    self.assertFalse(config.exists())
                self.assertFalse((home / 'state/musicsync/last-sync.json').exists())
            finally:
                process.terminate()
                process.communicate(timeout=10)
