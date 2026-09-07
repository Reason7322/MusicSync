import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEventLoop
from musicsync.backend.status import StatusService
from musicsync.backend.sync_controller import SyncController
from musicsync.models import Result, State
from fixtures import ConfiguredSettings as Settings
from test_controller import FakeRunner
from test_process import APP
from test_workflow import Simulation


class HistoryReleaseTests(unittest.TestCase):
    def drive(self, sim, folder, preview=False, write_error=False):
        runner = FakeRunner(sim)
        controller = SyncController(runner=runner)
        loop = QEventLoop()
        outcomes = []
        controller.completed.connect(lambda outcome: (outcomes.append(outcome), loop.quit()))
        with patch('musicsync.backend.sync_controller.state_dir', return_value=Path(folder)):
            if write_error:
                with patch('musicsync.backend.sync_controller.atomic_json', side_effect=OSError('disk full')):
                    controller.start(Settings(), preview)
                    loop.exec()
            else:
                controller.start(Settings(), preview)
                loop.exec()
        return controller, outcomes[0]

    def test_preview_failure_and_cancel_preserve_existing_success_bytes(self):
        for mode in ['preview', 'failure', 'cancel']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'last-sync.json'
                sentinel = b'{"old_success":"must survive"}\n'
                path.write_bytes(sentinel)
                sim = Simulation()
                if mode == 'failure':
                    sim.failure = 'rsync mirror'
                if mode == 'cancel':
                    sim.cancel_at = 'Check per-track ReplayGain'
                self.drive(sim, tmp, preview=mode == 'preview')
                self.assertEqual(path.read_bytes(), sentinel)

    def test_success_fields_counts_timezone_and_cleanup_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim = Simulation(failure='Unmount app-created KDE SSHFS')
            sim.records = 'MUSICSYNC|>f+++++++++|5|add.mp3\nMUSICSYNC|>f.st......|8|update.mp3\nMUSICSYNC|*deleting  |3|remove.mp3\n'
            controller, outcome = self.drive(sim, tmp)
            data = json.loads((Path(tmp) / 'last-sync.json').read_text())
            self.assertEqual((data['added'], data['updated'], data['removed']), (1, 1, 1))
            self.assertEqual(data['transferred_file_bytes'], 13)
            self.assertFalse(data['replaygain_processed'])
            self.assertEqual(data['device_id'], Settings().device_id)
            self.assertEqual(data['source'], Settings().source)
            self.assertTrue(data['cleanup_warning'])
            self.assertRegex(data['at'], r'[+-]\d\d:\d\d$')
            self.assertEqual(controller.state, State.COMPLETED)

    def test_history_write_failure_is_visible_and_does_not_erase_prior_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'last-sync.json'
            path.write_text('{"prior":true}')
            _, outcome = self.drive(Simulation(), tmp, write_error=True)
            self.assertTrue(outcome.success)
            self.assertIn('disk full', outcome.cleanup_warning)
            self.assertEqual(path.read_text(), '{"prior":true}')


class TimeoutStatusReleaseTests(unittest.TestCase):
    def test_mount_presence_timeout_never_authorizes_sync_even_exit_zero(self):
        sim = Simulation()
        original = sim.reply
        sim.reply = lambda c: Result(0, timed_out=True) if c.label == 'Check mount presence' else original(c)
        self.assertFalse(sim.run().success)
        self.assertFalse(sim.sync_ran)

    def test_cleanup_presence_timeout_does_not_claim_unmounted(self):
        sim = Simulation()
        original = sim.reply
        sim.reply = lambda c: Result(32, timed_out=True) if c.label == 'Check cleanup mount' else original(c)
        self.assertTrue(sim.run().cleanup_warning)

    def test_startup_status_checks_do_not_mount_or_sync(self):
        service = StatusService()
        generator = service._read(Settings(), scan=False)
        commands = []
        result = None
        while True:
            try:
                command = generator.send(result)
            except StopIteration as done:
                self.assertEqual(done.value['device_status'], 'Connected')
                break
            commands.append(command)
            if '--list-available' in command.args:
                result = Result(0, Settings().device_id + ' Test phone\n')
            elif '--get-mount-point' in command.args:
                result = Result(0, '/run/user/1000/device')
            else:
                result = Result(32)
        self.assertFalse(any('--mount' in c.args or c.program == 'rsync' for c in commands))

    def test_mount_status_permission_error_is_not_reported_as_unmounted(self):
        service = StatusService()
        generator = service._read(Settings(), scan=False)
        next(generator)
        generator.send(Result(0, Settings().device_id + ' Phone\n'))
        generator.send(Result(0, '/run/user/1000/device'))
        try:
            generator.send(Result(1, stderr='Permission denied'))
        except StopIteration as done:
            self.assertNotIn('Not mounted', done.value.get('filesystem', ''))
            self.assertIn('error', done.value)

    def test_cancelled_startup_stops_without_followup_commands(self):
        service = StatusService()
        service.generator = service._read(Settings(), scan=True)
        next(service.generator)
        service.active = True
        results = []
        service.ready.connect(results.append)
        with patch.object(service.runner, 'start') as start:
            service._next(Result(-1, cancelled=True))
            start.assert_not_called()
        self.assertFalse(service.active)
        self.assertIn('cancelled', results[0]['device_status'])
