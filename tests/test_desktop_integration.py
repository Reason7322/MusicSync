"""Explicit integration in temporary XDG directories; never touches a real image."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from musicsync import APP_ID, entry
from musicsync.desktop_integration import desktop_argument, integrate_appimage

ROOT = Path(__file__).resolve().parents[1]


class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='musicsync-desktop-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / 'mounted AppDir'
        self.image = self.root / 'Music Sync Zażółć 日本語 $cash `literal` "quote" ;.AppImage'
        self.image.write_text(f'#!{sys.executable}\nimport sys,json\nfrom pathlib import Path\nPath({str(self.root / "launched.json")!r}).write_text(json.dumps(sys.argv))\n')
        self.image.chmod(0o755)
        self.image_bytes = self.image.read_bytes()
        self.data = self.root / 'data Ω'
        self.desktop = self.data / 'applications' / f'{APP_ID}.desktop'
        self.icon = self.data / 'icons/hicolor/scalable/apps' / f'{APP_ID}.svg'
        self.receipt = self.data / 'musicsync/appimage-desktop.json'
        for source, destination in [
            (ROOT / 'resources' / self.desktop.name, self.bundle / 'usr/share/applications' / self.desktop.name),
            (ROOT / 'src/musicsync/icons' / self.icon.name, self.bundle / 'usr/share/icons/hicolor/scalable/apps' / self.icon.name),
        ]:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self.env = dict(HOME=str(self.root), XDG_DATA_HOME=str(self.data), APPIMAGE=str(self.image))
        self.enterContext(patch.dict(os.environ, self.env))
        self.enterContext(patch('musicsync.runtime.appdir', return_value=self.bundle))
        self.enterContext(redirect_stdout(io.StringIO()))

    def snapshot(self):
        return {str(p.relative_to(self.data)): p.read_bytes() for p in self.data.rglob('*') if p.is_file()}

    def test_install_repeat_uninstall_uses_image_path_and_preserves_image(self):
        integrate_appimage()
        self.assertIn('Exec=' + desktop_argument(self.image) + '\n', self.desktop.read_text())
        self.assertNotIn(str(self.bundle), self.desktop.read_text())
        self.assertEqual(json.loads(self.receipt.read_text())['appimage'], str(self.image))
        before = self.snapshot()
        integrate_appimage()
        self.assertEqual(self.snapshot(), before)
        integrate_appimage(uninstall=True)
        self.assertEqual(self.snapshot(), {})
        integrate_appimage(uninstall=True)
        self.assertEqual(self.image.read_bytes(), self.image_bytes)

    def test_desktop_spec_validation_and_gio_launch_preserve_literal_unicode_path(self):
        integrate_appimage()
        validation = subprocess.run(['desktop-file-validate', str(self.desktop)], capture_output=True, text=True)
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
        # GIO actually parses/expands Exec; shlex would test shell rules instead.
        launch = subprocess.run(['gio', 'launch', str(self.desktop)], capture_output=True, text=True, timeout=10)
        self.assertEqual(launch.returncode, 0, launch.stderr)
        result = self.root / 'launched.json'
        deadline = time.monotonic() + 5
        while not result.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(json.loads(result.read_text()), [str(self.image)])

    def test_rejects_unsafe_and_nonabsolute_paths_without_writes(self):
        for value in ['', 'relative.AppImage', '/tmp/bad\nfile', '/tmp/bad\0file', '/tmp/bad\rfile',
                      '/tmp/bad\tfile', '/tmp/bad\x7ffile', '/tmp/a=b']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                desktop_argument(value)
        for name in ('APPIMAGE', 'XDG_DATA_HOME'):
            for value in ('relative', '/tmp/bad\npath'):
                with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                    with self.assertRaises(ValueError):
                        integrate_appimage()
        self.assertFalse(self.data.exists())

    def test_missing_runtime_or_appdir_target_never_installs(self):
        with patch('musicsync.runtime.appdir', return_value=None), self.assertRaises(ValueError):
            integrate_appimage()
        for value in ('', str(self.bundle), str(self.root / 'missing.AppImage'), '/tmp/percent%.AppImage'):
            with patch.dict(os.environ, APPIMAGE=value), self.assertRaises(ValueError):
                integrate_appimage()
        self.assertFalse(self.data.exists())

    def test_xdg_default_and_empty_value_use_user_data_directory(self):
        for value in (None, ''):
            with self.subTest(value=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop('XDG_DATA_HOME', None)
                else:
                    os.environ['XDG_DATA_HOME'] = value
                integrate_appimage()
                desktop = self.root / '.local/share/applications' / self.desktop.name
                self.assertTrue(desktop.exists())
                integrate_appimage(uninstall=True)
                self.assertFalse(desktop.exists())

    def test_preexisting_desktop_or_identical_icon_is_not_claimed(self):
        for target, content in [(self.desktop, b'unrelated'), (self.icon, b'unrelated'),
                (self.icon, (ROOT / 'src/musicsync/icons' / self.icon.name).read_bytes())]:
            with self.subTest(target=target, content=content[:12]):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                before = self.snapshot()
                for uninstall in (False, True):
                    with self.assertRaises(ValueError):
                        integrate_appimage(uninstall=uninstall)
                    self.assertEqual(self.snapshot(), before)
                target.unlink()

    def test_modified_artifacts_or_receipt_block_all_writes_and_removals(self):
        integrate_appimage()
        for target in (self.desktop, self.icon, self.receipt):
            original = target.read_bytes()
            target.write_bytes(original + b'changed')
            before = self.snapshot()
            for uninstall in (False, True):
                with self.subTest(target=target, uninstall=uninstall), self.assertRaises(ValueError):
                    integrate_appimage(uninstall=uninstall)
                self.assertEqual(self.snapshot(), before)
            target.write_bytes(original)

    def test_symlink_artifacts_are_never_followed(self):
        victim = self.root / 'unrelated'
        victim.write_text('keep')
        for target in (self.desktop, self.icon, self.receipt):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(victim)
            for uninstall in (False, True):
                with self.assertRaises(ValueError):
                    integrate_appimage(uninstall=uninstall)
            self.assertEqual(victim.read_text(), 'keep')
            target.unlink()

    def test_entry_dispatch_is_explicit_and_does_not_initialize_gui(self):
        for flag, uninstall in [('--install-desktop', False), ('--uninstall-desktop', True)]:
            with patch.object(sys, 'argv', ['musicsync', flag]), patch('musicsync.desktop_integration.integrate_appimage') as install:
                self.assertEqual(entry.main(), 0)
                install.assert_called_once_with(uninstall=uninstall)
        with patch.object(sys, 'argv', ['musicsync', '--install-desktop', 'extra']):
            self.assertEqual(entry.main(), 2)
        with patch.object(sys, 'argv', ['musicsync']), patch('musicsync.app.main', return_value=0), patch('musicsync.desktop_integration.integrate_appimage') as install:
            self.assertEqual(entry.main(), 0)
            install.assert_not_called()
        self.assertFalse(self.data.exists())
