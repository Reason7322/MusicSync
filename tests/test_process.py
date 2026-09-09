import os
from pathlib import Path
import sys
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from musicsync.backend.process import ProcessRunner
from musicsync.backend.rsync import arguments, parse_change
from musicsync.models import Command
from musicsync.settings import Settings

# Tests construct real widgets without opening windows on the user's desktop.
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
APP = QCoreApplication.instance() or QApplication([])


def run(command, cancel_after=None):
    runner, loop, results, lines = ProcessRunner(), QEventLoop(), [], []
    runner.line.connect(lambda stream, line: lines.append((stream, line)))
    runner.finished.connect(lambda result: (results.append(result), loop.quit()))
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(15000)
    runner.start(command)
    if cancel_after is not None:
        QTimer.singleShot(cancel_after, runner.cancel)
    loop.exec()
    guard.stop()
    if not results:
        runner.cancel()
        raise AssertionError('QProcess did not complete within the test deadline')
    return results[0], lines


class ProcessTests(unittest.TestCase):
    def test_incremental_channels_and_cr(self):
        result, lines = run(Command(sys.executable, ['-c', 'import os,time; os.write(1,b"first\\r"); time.sleep(.05); os.write(2,b"error\\n"); os.write(1,"Zażółć\\n".encode())']))
        self.assertEqual(result.code, 0)
        self.assertIn(('stdout', 'first'), lines)
        self.assertIn(('stdout', 'Zażółć'), lines)
        self.assertIn(('stderr', 'error'), lines)

    def test_failed_to_start(self):
        result, _ = run(Command('/does/not/exist'))
        self.assertNotEqual(result.code, 0)

    def test_cancel_and_kill_escalation(self):
        result, _ = run(Command(sys.executable, ['-c', 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(20)']), 150)
        self.assertTrue(result.cancelled)
        self.assertNotEqual(result.code, 0)

    def test_timeout(self):
        result, _ = run(Command(sys.executable, ['-c', 'import time; time.sleep(20)'], timeout_ms=100))
        self.assertTrue(result.timed_out)

    def test_real_rsync_in_temporary_directories(self):
        # The only destructive test uses directories allocated right here, never settings defaults.
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as temporary:
            source, destination = Path(temporary) / 'PC library', Path(temporary) / 'phone'
            source.mkdir()
            destination.mkdir()
            names = ['new | song.mp3', 'line\nbreak.mp3', 'Zażółć.mp3', 'slash\\#012.mp3']
            for name in names:
                (source / name).write_bytes(b'new song')
            (source / 'update.mp3').write_bytes(b'updated music')
            (destination / 'update.mp3').write_bytes(b'old')
            (destination / 'delete.mp3').write_bytes(b'old song')
            (destination / '.thumbnails').mkdir()
            (destination / '.thumbnails' / 'keep').write_bytes(b'Android cache')
            settings = Settings(source=str(source), mirror=True)
            preview, _ = run(Command('rsync', arguments(settings, str(source), str(destination), True)))
            self.assertEqual(preview.code, 0, preview.stderr)
            changes = [parse_change(line) for line in preview.stdout.splitlines()]
            changes = [c for c in changes if c]
            self.assertEqual({c.path for c in changes if c.action == 'Add'}, set(names))
            self.assertEqual({c.path for c in changes if c.action == 'Delete'}, {'delete.mp3'})
            self.assertTrue((destination / 'delete.mp3').exists())
            actual, _ = run(Command('rsync', arguments(settings, str(source), str(destination), False, 1)))
            self.assertEqual(actual.code, 0, actual.stderr)
            self.assertFalse((destination / 'delete.mp3').exists())
            self.assertEqual((destination / '.thumbnails' / 'keep').read_bytes(), b'Android cache')
            self.assertEqual((destination / 'update.mp3').stat().st_mtime_ns // 10**9, (source / 'update.mp3').stat().st_mtime_ns // 10**9)
            matched, _ = run(Command('rsync', arguments(settings, str(source), str(destination), True)))
            self.assertEqual(matched.code, 0)
            self.assertFalse(any(parse_change(line) for line in matched.stdout.splitlines()))

    def test_delete_cap_blocks_unpreviewed_deletion(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as tmp:
            src, dst = Path(tmp) / 'source', Path(tmp) / 'destination'
            src.mkdir()
            dst.mkdir()
            (src / 'keep').write_text('keep')
            (dst / 'extra').write_text('extra')
            result, _ = run(Command('rsync', arguments(Settings(mirror=True), str(src), str(dst), False, 0)))
            self.assertEqual(result.code, 25)
            self.assertTrue((dst / 'extra').exists())
