"""One cancellable QProcess at a time, with incremental UTF-8/CR framing."""
import codecs
import os
import re
import signal
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal, Slot
from musicsync.models import Result


class ProcessRunner(QObject):
    line = Signal(str, str)
    finished = Signal(object)
    started = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        # Isolate only our utility descendants, never the desktop/KDE daemon.
        self.process.setUnixProcessParameters(QProcess.UnixProcessFlag.CreateNewSession)
        self.process.started.connect(self._process_started)
        self.busy = False
        self.process.readyReadStandardOutput.connect(self._stdout)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self._kill)

    def start(self, command):
        if self.busy:
            raise RuntimeError("A command is already running.")
        self.cancelled = self.timed_out = False
        self.group_id = 0
        self.killed = False
        self.pending_result = None
        self.buffers = {"stdout": "", "stderr": ""}
        self.outputs = {"stdout": "", "stderr": ""}
        self.decoders = {key: codecs.getincrementaldecoder("utf-8")("surrogateescape") for key in self.buffers}
        process = self.process
        self.busy = True
        env = QProcessEnvironment.systemEnvironment()
        env.insert("LC_ALL", "C.UTF-8")
        process.setProcessEnvironment(env)
        self.started.emit(command)
        if self.cancelled:
            self.pending_result = Result(-1, cancelled=True)
            QTimer.singleShot(0, self._deliver)
            return
        process.start(command.program, command.args)
        if command.timeout_ms:
            self.deadline.start(command.timeout_ms)

    @Slot()
    def _stdout(self):
        self._read("stdout")

    @Slot()
    def _stderr(self):
        self._read("stderr")

    def _read(self, stream, final=False):
        if not self.busy:
            return
        raw = self.process.readAllStandardOutput() if stream == "stdout" else self.process.readAllStandardError()
        decoded = self.decoders[stream].decode(bytes(raw), final=final)
        self.outputs[stream] += decoded
        if len(self.outputs[stream]) > 32 * 1024 * 1024:
            self._timeout()  # fail closed rather than silently lose preview/inventory records
            self.outputs[stream] = self.outputs[stream][-32 * 1024 * 1024:]
        parts = re.split(r"[\r\n]", self.buffers[stream] + decoded)
        self.buffers[stream] = parts.pop()
        for line in parts:
            if line:
                self.line.emit(stream, line)
        if final and self.buffers[stream]:
            self.line.emit(stream, self.buffers[stream])
            self.buffers[stream] = ""

    def cancel(self):
        if self.busy:
            self.cancelled = True
            self._signal_group(signal.SIGTERM)
            if not self.kill_timer.isActive():
                self.kill_timer.start(3000)

    def _timeout(self):
        self.timed_out = True
        if self.busy:
            self._signal_group(signal.SIGTERM)
            if not self.kill_timer.isActive():
                self.kill_timer.start(3000)

    @Slot()
    def _process_started(self):
        self.group_id = self.process.processId()
        if self.cancelled or self.timed_out:
            self._signal_group(signal.SIGTERM)

    def _signal_group(self, sig):
        if self.group_id:
            try:
                os.killpg(self.group_id, sig)
                return True
            except ProcessLookupError:
                pass
        return False

    def _kill(self):
        if self.busy:
            self.killed = True
            self._signal_group(signal.SIGKILL)
            if self.process.state() != QProcess.ProcessState.NotRunning:
                self.process.kill()
            elif self.pending_result is not None:
                # Give killed descendants a scheduling turn before releasing the
                # workflow to unmount its filesystem. The UI remains responsive.
                QTimer.singleShot(50, self._deliver)

    def _error(self, error):
        if self.busy and error == QProcess.ProcessError.FailedToStart:
            self.outputs["stderr"] += self.process.errorString()
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def _finished(self, code, status):
        if not self.busy:
            return
        self.deadline.stop()
        self._read("stdout", final=True)
        self._read("stderr", final=True)
        self.pending_result = Result(code if status == QProcess.ExitStatus.NormalExit else -1,
                        self.outputs["stdout"], self.outputs["stderr"], self.cancelled, self.timed_out)
        if (self.cancelled or self.timed_out) and not self.killed and self._signal_group(0):
            # The leader can exit before a SIGTERM-resistant receiver/helper.
            # Keep the grace timer and defer mount cleanup until group escalation.
            if not self.kill_timer.isActive():
                self.kill_timer.start(3000)
            return
        self._deliver()

    def _deliver(self):
        if self.pending_result is None:
            return
        result, self.pending_result = self.pending_result, None
        self.deadline.stop()
        self.kill_timer.stop()
        self.group_id = 0
        self.busy = False
        self.finished.emit(result)
