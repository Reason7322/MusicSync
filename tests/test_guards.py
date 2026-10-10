from contextlib import contextmanager
from dataclasses import asdict
import os
from pathlib import Path
import shutil
import signal
import tempfile
import unittest
from unittest.mock import patch

from musicsync.backend.filesystem import inventory, source_inventory
from musicsync.backend.worker import execute
from fixtures import ConfiguredSettings as Settings


class ExecReached(Exception):
    pass


class GuardTests(unittest.TestCase):
    def setup_paths(self, root):
        source, destination = Path(root) / 'source', Path(root) / 'phone'
        source.mkdir()
        destination.mkdir()
        (source / 'song.mp3').write_bytes(b'music')
        (destination / 'old.mp3').write_bytes(b'old')
        return source, destination

    @contextmanager
    def fake_remote(self, destination):
        @contextmanager
        def opened(*args):
            fd = os.open(destination, os.O_DIRECTORY)
            try:
                yield fd
            finally:
                os.close(fd)
        # Only the mount identity is faked; scans and snapshot comparisons use real
        # temp files. exec is always intercepted below, so no destructive command runs.
        with patch('musicsync.backend.worker.remote_directory', opened), patch('musicsync.backend.worker.current_mount'), patch('musicsync.backend.worker.fd_mount_id', return_value=-2), patch('musicsync.backend.filesystem.fd_mount_id', return_value=-1):
            yield

    def payload(self, source, destination):
        source_snapshot = source_inventory(source, require_files=True)
        return {'action': 'rsync', 'mountpoint': str(destination), 'mount_id': -1, 'remote': '/storage/emulated/0/Music',
                'settings': asdict(Settings(source=str(source))), 'dry_run': False, 'max_delete': 1,
                'source_digest': source_snapshot['digest'], 'mapping_digest': source_snapshot['mapping_digest'],
                'destination_digest': inventory(destination)['digest']}

    def test_changed_or_empty_source_never_executes(self):
        for mode in ['changed', 'empty', 'phone_changed']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                source, destination = self.setup_paths(root)
                payload = self.payload(source, destination)
                if mode == 'changed':
                    (source / 'song.mp3').write_bytes(b'changed')
                elif mode == 'empty':
                    (source / 'song.mp3').unlink()
                else:
                    (destination / 'new.mp3').write_bytes(b'new')
                with self.fake_remote(destination), patch('os.execv') as execute_utility:
                    with self.assertRaises(OSError):
                        execute(payload)
                    execute_utility.assert_not_called()

    def test_rsync_uses_pinned_directories_and_delete_cap(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = self.setup_paths(root)
            payload = self.payload(source, destination)
            old_cwd = os.open('.', os.O_DIRECTORY)
            def inspect(program, args):
                self.assertEqual(Path.cwd(), destination)
                self.assertIn('--max-delete=1', args)
                self.assertEqual(args[-1], './')
                self.assertTrue(args[-2].startswith('/proc/self/fd/'))
                self.assertEqual((Path(args[-2]) / 'song.mp3').read_bytes(), b'music')
                fd = int(args[-2].rstrip('/').split('/')[-1])
                self.assertTrue(os.get_inheritable(fd))
                raise ExecReached
            try:
                with self.fake_remote(destination), patch('os.execv', side_effect=inspect):
                    with self.assertRaises(ExecReached):
                        execute(payload)
            finally:
                os.fchdir(old_cwd)
                os.close(old_cwd)

    def test_mapping_change_never_starts_rsync(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = self.setup_paths(root)
            payload = self.payload(source, destination)
            payload['mapping_digest'] = 'not-the-previewed-map'
            with self.fake_remote(destination), patch('os.execv') as execute_utility:
                with self.assertRaisesRegex(OSError, 'filename mapping changed'):
                    execute(payload)
                execute_utility.assert_not_called()

    def test_translated_source_uses_copy_links_and_pinned_file_descriptors(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = self.setup_paths(root)
            (source / 'song.mp3').unlink()
            (source / 'song:name.mp3').write_bytes(b'music')
            payload = self.payload(source, destination)

            def inspect(program, command, environment):
                self.assertIn('--copy-links', command)
                staged = Path(command[-2])
                self.assertTrue(staged.name.startswith('musicsync-stage-'))
                self.assertEqual((staged / 'song - name.mp3').read_bytes(), b'music')
                targets = [os.readlink(path) for path in staged.iterdir() if path.is_symlink()]
                self.assertTrue(targets)
                self.assertTrue(all(os.get_inheritable(int(target.rsplit('/', 1)[1])) for target in targets))
                return 12345

            old_cwd = os.open('.', os.O_DIRECTORY)
            try:
                with self.fake_remote(destination), \
                        patch('musicsync.backend.worker.os.posix_spawn', side_effect=inspect) as spawn, \
                        patch('musicsync.backend.worker.os.waitpid', return_value=(12345, 0)):
                    self.assertEqual(execute(payload), 0)
                    spawn.assert_called_once()
            finally:
                os.fchdir(old_cwd)
                os.close(old_cwd)

    def test_cancelled_translated_rsync_cleans_stage_before_returning(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = self.setup_paths(root)
            (source / 'song.mp3').rename(source / 'song:name.mp3')
            payload = self.payload(source, destination)
            staged = []

            def cancel(program, command, environment):
                staged.append(Path(command[-2]))
                os.kill(os.getpid(), signal.SIGTERM)
                return 12345

            old_cwd = os.open('.', os.O_DIRECTORY)
            try:
                with self.fake_remote(destination), \
                        patch('musicsync.backend.worker.os.posix_spawn', side_effect=cancel), \
                        patch('musicsync.backend.worker.os.waitpid', return_value=(12345, signal.SIGTERM)):
                    self.assertEqual(execute(payload), -signal.SIGTERM)
            finally:
                os.fchdir(old_cwd)
                os.close(old_cwd)
            self.assertEqual(len(staged), 1)
            self.assertFalse(staged[0].exists())

    @unittest.skipUnless(shutil.which('rsync'), 'real staging integration needs rsync')
    def test_real_translated_mirror_is_repeatable_and_stable_after_unrelated_add(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / 'source', Path(root) / 'phone'
            source.mkdir()
            destination.mkdir()
            names = ['Bloodborne: OST.mp3', 'A:B.mp3', 'A - B.mp3', 'Zażółć 日本語 🎵.flac']
            for index, name in enumerate(names):
                (source / name).write_bytes(f'track-{index}'.encode())
            (destination / 'phone-only.mp3').write_bytes(b'delete me')
            before = {name: (source / name).read_bytes() for name in names}
            initial_mapping = source_inventory(source, require_files=True)['destination_paths']
            old_cwd = os.open('.', os.O_DIRECTORY)
            try:
                with self.fake_remote(destination):
                    self.assertEqual(execute(self.payload(source, destination)), 0)
                    repeated = self.payload(source, destination)
                    repeated['max_delete'] = 0
                    self.assertEqual(execute(repeated), 0)
                    (source / 'unrelated?.opus').write_bytes(b'unrelated')
                    changed = source_inventory(source, require_files=True)
                    for name in names:
                        self.assertEqual(changed['destination_paths'][name], initial_mapping[name])
                    added = self.payload(source, destination)
                    added['max_delete'] = 0
                    self.assertEqual(execute(added), 0)
            finally:
                os.fchdir(old_cwd)
                os.close(old_cwd)

            self.assertEqual({name: (source / name).read_bytes() for name in names}, before)
            self.assertFalse((destination / 'phone-only.mp3').exists())
            expected = set(initial_mapping.values()) | {source_inventory(source)['destination_paths']['unrelated?.opus']}
            self.assertEqual({path.name for path in destination.iterdir()}, expected)
