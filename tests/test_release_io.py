import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest

from PySide6.QtCore import QEventLoop, QTimer
from musicsync.backend.filesystem import inventory
from musicsync.backend.process import ProcessRunner
from musicsync.backend.rsync import arguments
from musicsync.backend.workflow import Workflow, helper
from musicsync.models import Command
from musicsync.settings import Settings
from test_process import APP, run


def snapshot(path):
    return {str(p.relative_to(path)): (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in Path(path).rglob('*') if p.is_file()}


class RealTemporaryRsyncReleaseTests(unittest.TestCase):
    def test_update_only_keeps_extra_files_and_updates_changed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, phone = Path(tmp) / 'pc', Path(tmp) / 'phone'
            source.mkdir(); phone.mkdir()
            (source / 'changed.mp3').write_text('new version')
            (phone / 'changed.mp3').write_text('old')
            (phone / 'extra.mp3').write_text('keep')
            (source / 'added.mp3').write_text('add')
            result, _ = run(Command('rsync', arguments(Settings(mirror=False), str(source), str(phone), False)))
            self.assertEqual(result.code, 0, result.stderr)
            self.assertEqual((phone / 'extra.mp3').read_text(), 'keep')
            self.assertEqual((phone / 'changed.mp3').read_text(), 'new version')
            self.assertTrue((phone / 'added.mp3').exists())

    def test_root_thumbnails_protected_but_nested_thumbnails_follow_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, phone = Path(tmp) / 'pc', Path(tmp) / 'phone'
            source.mkdir(); phone.mkdir()
            (source / 'keep.mp3').write_text('music')
            (phone / '.thumbnails/sub').mkdir(parents=True)
            (phone / '.thumbnails/sub/cache').write_text('protected')
            (phone / 'album/.thumbnails').mkdir(parents=True)
            (phone / 'album/.thumbnails/cache').write_text('not root')
            result, _ = run(Command('rsync', arguments(Settings(), str(source), str(phone), False)))
            self.assertEqual(result.code, 0, result.stderr)
            self.assertTrue((phone / '.thumbnails/sub/cache').exists())
            self.assertFalse((phone / 'album').exists())

    def test_real_preview_is_byte_and_mtime_unchanged_with_unusual_names(self):
        names = ['space name.mp3', 'Zażółć 日本語 🎵.mp3', 'quote\"\'song.mp3', '$(touch PWNED);`id`&|<>*.mp3', '-leading-option.mp3', 'tab\tand\nnewline.mp3', 'unicode\u2028separator.mp3', 'literal\\#012.mp3', 'percent%f.mp3']
        with tempfile.TemporaryDirectory() as tmp:
            source, phone = Path(tmp) / 'pc', Path(tmp) / 'phone'
            source.mkdir(); phone.mkdir()
            for name in names:
                (source / name).write_text('new')
            (phone / 'remove.mp3').write_text('remove')
            before = snapshot(source), snapshot(phone)
            config = Settings(source=str(source))
            result, _ = run(Command('rsync', arguments(config, str(source), str(phone), True)))
            self.assertEqual(result.code, 0, result.stderr)
            self.assertEqual((snapshot(source), snapshot(phone)), before)
            workflow = Workflow(config, True)
            workflow.source_inventory, workflow.destination_inventory = inventory(source), inventory(phone)
            summary = workflow._parse(result.stdout)
            self.assertEqual({c.path for c in summary.changes if c.action == 'Add'}, set(names))
            self.assertEqual(summary.count('Delete'), 1)
            actual, _ = run(Command('rsync', arguments(config, str(source), str(phone), False, 1)))
            self.assertEqual(actual.code, 0, actual.stderr)
            self.assertEqual({p.name for p in phone.iterdir()}, set(names))
            self.assertFalse((source / 'PWNED').exists())
            self.assertFalse((phone / 'PWNED').exists())

    def test_failed_sender_io_does_not_delete_phone_only_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, phone = Path(tmp) / 'pc', Path(tmp) / 'phone'
            source.mkdir(); phone.mkdir()
            secret = source / 'unreadable.mp3'
            secret.write_text('music'); secret.chmod(0)
            (phone / 'extra.mp3').write_text('must survive')
            try:
                result, _ = run(Command('rsync', arguments(Settings(), str(source), str(phone), False)))
                self.assertNotEqual(result.code, 0)
                self.assertTrue((phone / 'extra.mp3').exists())
            finally:
                secret.chmod(0o600)

    def test_actual_rsync_cancel_before_delete_after_keeps_extra_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, phone = Path(tmp) / 'pc', Path(tmp) / 'phone'
            source.mkdir(); phone.mkdir()
            (source / 'large.bin').write_bytes(b'x' * 2_000_000)
            (phone / 'extra.mp3').write_text('survives cancelled transfer')
            args = arguments(Settings(), str(source), str(phone), False)
            args.insert(1, '--bwlimit=64')
            result, _ = run(Command('rsync', args), cancel_after=200)
            self.assertTrue(result.cancelled)
            self.assertNotEqual(result.code, 0)
            self.assertTrue((phone / 'extra.mp3').exists())

    def test_large_library_worker_and_parser_10000_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(10000):
                (root / f'track-{i:05}.mp3').touch()
            started = time.monotonic()
            result, _ = run(helper('source', 'Large-library scan', timeout=120000, source=tmp, exclusions=['/.thumbnails/']))
            self.assertEqual(result.code, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data['count'], 10000)
            workflow = Workflow(Settings(), True)
            workflow.source_inventory, workflow.destination_inventory = data, {'files': {}}
            output = ''.join(f'MUSICSYNC|>f+++++++++|0|track-{i:05}.mp3\n' for i in range(10000))
            self.assertEqual(workflow._parse(output).count('Add'), 10000)
            elapsed = time.monotonic() - started
            print(f'\nLarge-library scan + parse (10,000 files): {elapsed:.3f}s', flush=True)
            self.assertLess(elapsed, 15)


class ProcessLifecycleReleaseTests(unittest.TestCase):
    def test_cancel_does_not_leave_a_child_process_running(self):
        child_code = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'
        parent_code = f'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c",{child_code!r}]); print(p.pid,flush=True); time.sleep(30)'
        result, _ = run(Command(sys.executable, ['-c', parent_code]), cancel_after=250)
        pid = int(result.stdout.strip())
        try:
            try:
                state = Path(f'/proc/{pid}/stat').read_text().split()[2]
                alive = state not in {'Z', 'X'}
            except FileNotFoundError:
                alive = False
            self.assertFalse(alive, 'Cancellation left a utility descendant alive')
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_cancel_from_started_signal_does_not_launch_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'must-not-exist'
            runner, loop, results = ProcessRunner(), QEventLoop(), []
            runner.started.connect(lambda command: runner.cancel())
            runner.finished.connect(lambda result: (results.append(result), loop.quit()))
            runner.start(Command(sys.executable, ['-c', f'from pathlib import Path; Path({str(marker)!r}).touch()']))
            if not results:
                loop.exec()
            self.assertTrue(results[0].cancelled)
            self.assertFalse(marker.exists(), 'A command started after its cancellation was requested')
