"""Qt adapter: execute yielded commands and forward semantic events to widgets."""
from datetime import datetime
import logging

from PySide6.QtCore import QObject, QTimer, Signal
from musicsync.backend.process import ProcessRunner
from musicsync.backend.rsync import parse_change, parse_progress
from musicsync.backend.workflow import Approval, Event, Workflow
from musicsync.logging import clean
from musicsync.models import Command, Outcome, Result, State
from musicsync.settings import atomic_json, state_dir


class SyncController(QObject):
    state_changed = Signal(object, str)
    library_changed = Signal(object)
    preview_ready = Signal(object)
    approval_needed = Signal(object)
    progress = Signal(object)
    change = Signal(object)
    log_line = Signal(str)
    completed = Signal(object)

    def __init__(self, parent=None, runner=None, record_success=True):
        super().__init__(parent)
        self.runner = runner or ProcessRunner(self)
        self.runner.finished.connect(self._resume)
        self.runner.line.connect(self._line)
        self.runner.started.connect(self._started)
        self.state = State.IDLE
        self.history = [State.IDLE]
        self.active = False
        self.generator = None
        self.waiting = False
        self.cancel_requested = False
        self.record_success = record_success
        self.logger = logging.getLogger("musicsync")

    def _set_state(self, state, message):
        self.state = state
        self.history.append(state)
        self.logger.info("State: %s: %s", state, message)
        self.state_changed.emit(state, message)

    def start(self, settings, preview=False):
        if self.active:
            return
        self.workflow = Workflow(settings, preview)
        self.history = [State.IDLE]
        self.generator = self.workflow.run()
        self.active = True
        self.cancel_requested = self.waiting = False
        self._resume(None)

    def _resume(self, result):
        if isinstance(result, Result):
            self.logger.info("Command exit=%s cancelled=%s timeout=%s", result.code, result.cancelled, result.timed_out)
        try:
            item = self.generator.send(result)
            while isinstance(item, Event):
                self._set_state(item.state, item.message)
                if item.data is not None:
                    if item.state == State.CHECKING_SOURCE:
                        self.library_changed.emit(item.data)
                    elif item.state == State.PREVIEWING:
                        self.preview_ready.emit(item.data)
                item = self.generator.send(None)
            if isinstance(item, Approval):
                self.waiting = True
                if self.cancel_requested:
                    QTimer.singleShot(0, lambda: self.approve(False))
                else:
                    self.approval_needed.emit(item)
            elif isinstance(item, Command):
                if self.cancel_requested and self.state != State.UNMOUNTING:
                    QTimer.singleShot(0, lambda: self._resume(Result(-1, cancelled=True)))
                else:
                    self.runner.start(item)
            else:
                raise RuntimeError("Unknown workflow instruction.")
        except StopIteration as done:
            self._finish(done.value)

    def approve(self, approved):
        if self.waiting:
            self.waiting = False
            self._resume(bool(approved) and not self.cancel_requested)

    def cancel(self):
        if not self.active or self.state == State.UNMOUNTING:
            return
        self.cancel_requested = True
        self._set_state(State.CANCELLING, "Stopping the active operation, then cleaning up…")
        if self.waiting:
            self.approve(False)
        else:
            self.runner.cancel()

    def _started(self, command):
        # Helper payloads may contain full inventories; log labels, not arbitrary
        # process argument dumps. Neither credentials nor SSH configuration queried.
        self.logger.info("Command: %s", command.label or command.program)
        if command.program == 'rsgain':
            self.logger.info('ReplayGain arguments: %r', command.args)
        self.log_line.emit(command.label or command.program)

    def _line(self, stream, line):
        if self.state in {State.SYNCING, State.PREVIEWING, State.VERIFYING, State.REPLAYGAIN}:
            # JSON helpers contain inventories: keep them out of the UI and log.
            if line.startswith('{"'):
                return
            self.log_line.emit(clean(line))
            self.logger.info("%s: %s", stream, clean(line))
        elif stream == "stderr":
            self.log_line.emit(clean(line))
            self.logger.warning("%s", clean(line))
        if self.state == State.SYNCING and stream == "stdout":
            progress = parse_progress(line)
            if progress:
                self.progress.emit(progress)
            try:
                change = parse_change(line)
                if change:
                    self.change.emit(change)
            except ValueError:
                # Full output is strictly parsed by the workflow at process exit.
                pass

    def _finish(self, outcome: Outcome):
        self.active = False
        self.generator = None
        if outcome.success and not outcome.preview and self.record_success:
            settings = self.workflow.settings
            record = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "source": settings.source,
                      "device_id": settings.device_id, "device_name": settings.device_name, "destination": settings.remote_dir,
                      "added": outcome.summary.count("Add"), "updated": outcome.summary.count("Update"), "removed": outcome.summary.count("Delete"),
                      "transferred_file_bytes": outcome.transferred_bytes, "replaygain_enabled": settings.replaygain,
                      "replaygain_processed": outcome.replaygain_processed, "mirror": settings.mirror,
                      "cleanup_warning": outcome.cleanup_warning}
            try:
                atomic_json(state_dir() / "last-sync.json", record)
            except OSError as error:
                outcome.cleanup_warning += f" Last-sync history could not be saved: {error}"
        state = State.COMPLETED if outcome.success else State.CANCELLED if outcome.cancelled else State.FAILED
        self._set_state(state, outcome.message)
        self.logger.info("Result success=%s preview=%s add=%d update=%d delete=%d cleanup=%s", outcome.success, outcome.preview,
                         outcome.summary.count("Add"), outcome.summary.count("Update"), outcome.summary.count("Delete"), outcome.cleanup_warning)
        self.completed.emit(outcome)
