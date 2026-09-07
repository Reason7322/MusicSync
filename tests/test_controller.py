from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QObject, QEventLoop, QTimer, Signal

from musicsync.backend.sync_controller import SyncController
from musicsync.models import State
from fixtures import ConfiguredSettings as Settings
from test_process import APP
from test_workflow import Simulation


class FakeRunner(QObject):
    line = Signal(str, str)
    finished = Signal(object)
    started = Signal(object)

    def __init__(self, simulation):
        super().__init__()
        self.simulation = simulation

    def start(self, command):
        self.started.emit(command)
        result = self.simulation.reply(command)
        QTimer.singleShot(0, lambda: self.finished.emit(result))

    def cancel(self):
        pass


class ControllerTests(unittest.TestCase):
    def test_terminal_states_and_last_success_rules(self):
        for mode in ['preview', 'success', 'failure', 'cancel']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                simulation = Simulation()
                if mode == 'failure':
                    simulation.failure = 'rsync mirror'
                if mode == 'cancel':
                    simulation.cancel_at = 'rsync preview'
                runner = FakeRunner(simulation)
                controller = SyncController(runner=runner)
                loop = QEventLoop()
                controller.completed.connect(loop.quit)
                with patch('musicsync.backend.sync_controller.state_dir', return_value=Path(root)):
                    controller.start(Settings(), preview=mode == 'preview')
                    loop.exec()
                expected = State.CANCELLED if mode == 'cancel' else State.FAILED if mode == 'failure' else State.COMPLETED
                self.assertEqual(controller.state, expected)
                self.assertFalse(controller.active)
                self.assertEqual((Path(root) / 'last-sync.json').exists(), mode == 'success')
                self.assertIn(State.UNMOUNTING, controller.history)
