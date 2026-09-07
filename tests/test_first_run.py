"""First-run behavior uses production defaults, with no live device access."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtCore import QStandardPaths
from musicsync.backend.status import StatusService
from musicsync.backend.workflow import Workflow
from musicsync.main_window import MainWindow
from musicsync.models import Command, Device, Result
from musicsync.settings import Settings
from musicsync.settings_dialog import SettingsDialog
from test_process import APP
from test_release_gui import SafeStatus


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='musicsync-first-run-')
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'HOME': str(self.root),
            'XDG_CONFIG_HOME': str(self.root / 'config'), 'XDG_STATE_HOME': str(self.root / 'state')})
        self.env.start()
        self.music = self.root / 'Música'
        self.qt_path = patch('musicsync.settings.QStandardPaths.writableLocation', return_value=str(self.music))
        self.qt_mock = self.qt_path.start()

    def tearDown(self):
        QTest.qWait(10)
        self.qt_path.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_missing_config_uses_qt_music_location_without_inventing_device_or_writing(self):
        settings = Settings.load()
        self.qt_mock.assert_called_once_with(QStandardPaths.StandardLocation.MusicLocation)
        self.assertEqual(settings.source, str(self.music))
        self.assertEqual((settings.device_id, settings.device_name), ('', ''))
        self.assertFalse(settings.configured)
        self.assertFalse((self.root / 'config').exists())
        self.assertFalse(self.music.exists())
        settings.validate(require_configured=False)
        with self.assertRaisesRegex(ValueError, 'Choose a KDE Connect device'):
            settings.validate()
        with self.assertRaises(ValueError):
            settings.save()

    def test_unconfigured_workflow_stops_before_any_external_command(self):
        for preview in (True, False):
            with self.subTest(preview=preview):
                generator = Workflow(Settings(), preview).run()
                while True:
                    try:
                        item = next(generator)
                        self.assertNotIsInstance(item, Command)
                    except StopIteration as done:
                        self.assertFalse(done.value.success)
                        self.assertIn('Choose a KDE Connect device', done.value.message)
                        break

    def test_unavailable_or_unsafe_qt_suggestion_requires_explicit_source(self):
        for value in ('', '/', str(self.root), str(self.root) + '/', 'relative', '/tmp/../music', '/tmp/bad\npath'):
            with self.subTest(value=value), patch('musicsync.settings.QStandardPaths.writableLocation', return_value=value):
                settings = Settings.load()
                self.assertEqual(settings.source, '')
                self.assertFalse(settings.configured)
                settings.validate(require_configured=False)
                with self.assertRaisesRegex(ValueError, 'Choose a PC music library'):
                    settings.validate()
                chosen_device = replace(settings, device_id='test-phone', device_name='Example phone')
                self.assertFalse(chosen_device.configured)
                with self.assertRaises(ValueError):
                    chosen_device.save()

    def test_unset_source_is_not_scanned_and_does_not_stop_device_discovery(self):
        service = StatusService()
        generator = service._read(Settings(source=''), scan=True)
        self.assertEqual(next(generator).args, ['--list-available', '--id-name-only'])
        with self.assertRaises(StopIteration) as done:
            generator.send(Result(0, 'test-phone Example phone\n'))
        self.assertIn('Choose a PC music library', done.exception.value['library_error'])
        self.assertEqual(len(done.exception.value['devices']), 1)
        service.deleteLater()

    def test_saved_source_is_not_replaced_by_qt_suggestion(self):
        explicit = Settings(source=str(self.root / 'Selected library'), device_id='test-phone', device_name='Example phone')
        explicit.save()
        with patch('musicsync.settings.QStandardPaths.writableLocation', return_value='') as discovery:
            loaded = Settings.load()
            discovery.assert_not_called()
        self.assertEqual(loaded, explicit)

    def test_discovery_without_selection_never_queries_or_mounts_a_device(self):
        for listing in ('', 'test-phone Example phone\nother-phone Other phone\n'):
            with self.subTest(listing=listing):
                service = StatusService()
                generator = service._read(Settings(), scan=False)
                self.assertEqual(next(generator).args, ['--list-available', '--id-name-only'])
                with self.assertRaises(StopIteration) as done:
                    generator.send(Result(0, listing))
                status = done.exception.value
                self.assertEqual(len(status['devices']), 2 if listing else 0)
                self.assertFalse(status['connected'])
                self.assertIn('Settings', status['device_status'])
                service.deleteLater()

    def test_unconfigured_load_still_rejects_malformed_paths_and_partial_devices(self):
        path = self.root / 'settings.json'
        for payload in ({'source': '/'}, {'remote_dir': '/storage/emulated/0/../Music'},
                        {'device_id': 'test-phone'}, {'device_name': 'Phone'},
                        {'threads': 0}, {'exclusions': []}):
            with self.subTest(payload=payload):
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    Settings.load(path)

    def test_first_run_widgets_require_selection_then_enable_operations(self):
        with patch('musicsync.main_window.StatusService', SafeStatus):
            window = MainWindow(Settings.load())
        try:
            window.show()
            QTest.qWait(30)
            self.assertTrue(window.settings_button.isEnabled())
            self.assertTrue(window.refresh_button.isEnabled())
            self.assertFalse(window.preview_button.isEnabled())
            self.assertFalse(window.sync_button.isEnabled())
            self.assertIn('get started', window.status_label.text())
            self.assertFalse(window.controller.active)
            window.settings = replace(window.settings, device_id='test-phone', device_name='Example phone')
            window._paths()
            self.assertTrue(window.preview_button.isEnabled())
            self.assertTrue(window.sync_button.isEnabled())
        finally:
            window.timer.stop()
            window.close()
            window.deleteLater()

    def test_discovered_device_selection_saves_real_selection_and_retains_it(self):
        dialog = SettingsDialog(Settings(), [Device('test-phone', 'Example phone')])
        try:
            self.assertIsNone(dialog.devices.currentData())
            self.assertEqual(dialog.device_id.text(), '')
            with patch('musicsync.settings_dialog.QMessageBox.warning') as warning:
                dialog._save()
                warning.assert_called_once()
            self.assertIsNone(dialog.value)
            dialog.devices.setCurrentIndex(1)
            self.assertEqual(dialog.device_id.text(), 'test-phone')
            dialog.devices.setCurrentIndex(0)
            self.assertEqual(dialog.device_id.text(), '')
            dialog.devices.setCurrentIndex(1)
            dialog._save()
            saved = Settings.load()
            self.assertEqual((saved.device_id, saved.device_name), ('test-phone', 'Example phone'))
            saved.validate()
            # A configured but currently unavailable phone remains selected.
            offline = SettingsDialog(saved, [])
            self.assertEqual(offline.devices.currentData(), ('test-phone', 'Example phone'))
            offline.deleteLater()
        finally:
            dialog.deleteLater()
