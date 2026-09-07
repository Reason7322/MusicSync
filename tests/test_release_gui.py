import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from musicsync.backend.process import ProcessRunner
from musicsync.backend.sync_controller import SyncController
from musicsync.main_window import MainWindow
from musicsync.models import Change, Command, State, Summary
from fixtures import ConfiguredSettings as Settings
from musicsync.settings_dialog import SettingsDialog
from test_process import APP
from test_workflow import Simulation


def until(condition, timeout=8000):
    deadline = time.monotonic() + timeout / 1000
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)
    if not condition():
        raise AssertionError('Qt condition not reached before test deadline')


class SafeStatus(QObject):
    ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False
        self.runner = self

    def refresh(self, settings, scan=True):
        self.active = True
        QTimer.singleShot(0, self.complete)

    def complete(self):
        self.active = False
        self.ready.emit({'device_status': 'Connected', 'connected': True, 'devices': [], 'library': {'count': 1, 'tracks': 1, 'bytes': 5}})

    def cancel(self):
        self.complete()


class ControlledRunner(QObject):
    started = Signal(object)
    finished = Signal(object)
    line = Signal(str, str)

    def __init__(self, sim, pause_label=None, duration=30):
        super().__init__()
        self.sim = sim
        self.pause_label = pause_label
        self.duration = duration
        self.process = ProcessRunner(self)
        self.process.finished.connect(self.finished)
        self.process.line.connect(self.line)
        self.paused = False
        self.cancelled = False

    def start(self, command):
        self.started.emit(command)
        result = self.sim.reply(command)
        if command.label == self.pause_label and not self.paused:
            self.paused = True
            self.process.start(Command(sys.executable, ['-c', f'import time; print("controlled fixture ready",flush=True); time.sleep({self.duration})']))
        else:
            QTimer.singleShot(0, lambda: self.finished.emit(result))

    def cancel(self):
        self.cancelled = True
        self.process.cancel()


class GUIReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='musicsync-gui-release-')
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'XDG_STATE_HOME': str(self.root / 'state'), 'XDG_CONFIG_HOME': str(self.root / 'config')})
        self.env.start()
        self.windows = []
        self.controllers = []

    def tearDown(self):
        for window in self.windows:
            window.close()
            if window.controller.active:
                until(lambda: not window.controller.active)
            window.timer.stop()
            window.deleteLater()
        QTest.qWait(30)
        self.env.stop()
        self.tmp.cleanup()

    def window(self, pause=None, sim=None, duration=30):
        sim = sim or Simulation()
        runner = ControlledRunner(sim, pause, duration)
        controller = SyncController(runner=runner)
        self.controllers.append((controller, runner))
        with patch('musicsync.main_window.StatusService', SafeStatus), patch('musicsync.main_window.SyncController', return_value=controller):
            window = MainWindow(Settings(source=str(self.root / 'fixture-library')))
        self.windows.append(window)
        window.show()
        QTest.qWait(30)
        return window, sim, runner

    def test_startup_is_idle_and_does_not_begin_sync(self):
        window, sim, runner = self.window()
        self.assertFalse(window.controller.active)
        self.assertEqual(window.controller.state, State.IDLE)
        self.assertEqual(sim.commands, [])
        self.assertEqual(window.styleSheet(), '')
        self.assertTrue(window.preview_button.isEnabled())

    def test_repeated_clicks_and_controller_starts_cannot_overlap(self):
        window, sim, runner = self.window('rsync preview')
        QTest.mouseClick(window.preview_button, Qt.MouseButton.LeftButton)
        until(lambda: runner.paused)
        for _ in range(20):
            QTest.mouseClick(window.preview_button, Qt.MouseButton.LeftButton)
            QTest.mouseClick(window.sync_button, Qt.MouseButton.LeftButton)
            window.controller.start(Settings(), preview=False)
        self.assertEqual(sim.mounts, 1)
        self.assertFalse(sim.sync_ran)
        self.assertFalse(window.settings_button.isEnabled())
        QTest.mouseClick(window.cancel_button, Qt.MouseButton.LeftButton)
        until(lambda: not window.controller.active)
        self.assertEqual(window.controller.state, State.CANCELLED)

    def test_close_during_replaygain_cancels_process_and_never_mounts(self):
        window, sim, runner = self.window('Check per-track ReplayGain')
        QTest.mouseClick(window.sync_button, Qt.MouseButton.LeftButton)
        until(lambda: runner.paused)
        window.close()
        until(lambda: not window.controller.active)
        self.assertFalse(window.isVisible())
        self.assertFalse(runner.process.busy)
        self.assertEqual(sim.mounts, 0)
        self.assertEqual(window.controller.state, State.CANCELLED)
        self.assertFalse((self.root / 'state/musicsync/last-sync.json').exists())

    def test_close_during_rsync_cancels_and_cleans_owned_mount(self):
        window, sim, runner = self.window('rsync mirror')
        QTest.mouseClick(window.sync_button, Qt.MouseButton.LeftButton)
        until(lambda: runner.paused)
        window.close()
        until(lambda: not window.controller.active)
        self.assertFalse(window.isVisible())
        self.assertEqual(sim.unmounts, 1)
        self.assertEqual(window.controller.state, State.CANCELLED)
        self.assertFalse((self.root / 'state/musicsync/last-sync.json').exists())

    def test_close_during_mount_cleans_partial_mount(self):
        window, sim, runner = self.window('Mount KDE Connect filesystem')
        QTest.mouseClick(window.preview_button, Qt.MouseButton.LeftButton)
        until(lambda: runner.paused)
        window.close()
        until(lambda: not window.controller.active)
        self.assertFalse(window.isVisible())
        self.assertEqual(sim.unmounts, 1)

    def test_close_during_cleanup_waits_for_unmount(self):
        window, sim, runner = self.window('Unmount app-created KDE SSHFS', duration=.2)
        QTest.mouseClick(window.preview_button, Qt.MouseButton.LeftButton)
        until(lambda: runner.paused)
        window.close()
        self.assertTrue(window.controller.active)
        self.assertFalse(runner.cancelled)
        until(lambda: not window.controller.active)
        self.assertFalse(window.isVisible())
        self.assertEqual(sim.unmounts, 1)

    def test_large_delete_dialog_defaults_to_cancel_and_lists_files(self):
        sim = Simulation()
        sim.records = ''.join(f'MUSICSYNC|*deleting  |0|old{i}.mp3\n' for i in range(21))
        window, sim, runner = self.window(sim=sim)
        QTest.mouseClick(window.sync_button, Qt.MouseButton.LeftButton)
        until(lambda: window.controller.waiting)
        box = window.approval_dialog
        self.assertIn('21 files', box.text())
        self.assertEqual(box.defaultButton(), box.button(QMessageBox.StandardButton.No))
        self.assertIn('old20.mp3', box.detailedText())
        QTest.mouseClick(box.button(QMessageBox.StandardButton.No), Qt.MouseButton.LeftButton)
        until(lambda: not window.controller.active)
        self.assertFalse(sim.sync_ran)
        self.assertEqual(window.controller.state, State.CANCELLED)

    def test_close_while_approval_pending_stops_without_sync(self):
        sim = Simulation()
        sim.records = ''.join(f'MUSICSYNC|*deleting  |0|old{i}.mp3\n' for i in range(21))
        window, sim, runner = self.window(sim=sim)
        QTest.mouseClick(window.sync_button, Qt.MouseButton.LeftButton)
        until(lambda: window.controller.waiting)
        window.close()
        until(lambda: not window.controller.active)
        self.assertFalse(sim.sync_ran)
        self.assertFalse(window.isVisible())
        self.assertFalse(window.approval_dialog.isVisible())

    def test_progress_and_log_widgets_update_while_subprocess_runs(self):
        window, sim, runner = self.window('rsync mirror')
        QTest.mouseClick(window.sync_button, Qt.MouseButton.LeftButton)
        until(lambda: runner.paused)
        runner.line.emit('stdout', '123.45M 42% 8.90MB/s 0:00:02')
        runner.line.emit('stdout', 'MUSICSYNC|>f+++++++++|123|new song.mp3')
        runner.line.emit('stderr', 'readable diagnostic')
        self.assertEqual(window.progress_bar.value(), 42)
        self.assertIn('8.90MB/s', window.progress_bar.format())
        self.assertIn('new song.mp3', window.transfer_label.text())
        self.assertIn('readable diagnostic', window.log.toPlainText())
        ticks = []
        QTimer.singleShot(30, lambda: ticks.append(True))
        until(lambda: bool(ticks))
        self.assertTrue(window.controller.active)
        window.controller.cancel()
        until(lambda: not window.controller.active)

    def test_settings_dialog_saves_all_controls_to_isolated_xdg(self):
        window, _, _ = self.window()
        dialog = SettingsDialog(window.settings, [], window)
        dialog.source.setText(str(self.root / 'My Music'))
        dialog.remote.setText('/storage/emulated/0/Other Music')
        dialog.threads.setValue(7)
        dialog.gain.setChecked(False)
        dialog.mirror.setChecked(False)
        dialog._save()
        loaded = Settings.load()
        self.assertEqual(loaded.threads, 7)
        self.assertFalse(loaded.replaygain)
        self.assertFalse(loaded.mirror)
        self.assertEqual(loaded.remote_dir, '/storage/emulated/0/Other Music')
        dialog.deleteLater()

    def test_large_preview_table_10000_rows_and_return_to_event_loop(self):
        window, _, _ = self.window()
        summary = Summary([Change('Add', f'track-{i:05}.mp3', 1000) for i in range(10000)])
        start = time.monotonic()
        window._preview(summary)
        elapsed = time.monotonic() - start
        self.assertEqual(window.table.rowCount(), 10000)
        self.assertIn('10000 files', window.summary_label.text())
        self.assertLess(elapsed, 1.5, 'Preview population stalled GUI for over 1.5 seconds')
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        until(lambda: bool(ticks))
        print(f'\nQt 10,000-row preview population: {elapsed:.3f}s', flush=True)
