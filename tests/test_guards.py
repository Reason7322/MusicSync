from contextlib import contextmanager
from dataclasses import asdict
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from musicsync.backend.filesystem import inventory
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
        return {'action': 'rsync', 'mountpoint': str(destination), 'mount_id': -1, 'remote': '/storage/emulated/0/Music',
                'settings': asdict(Settings(source=str(source))), 'dry_run': False, 'max_delete': 1,
                'source_digest': inventory(source, require_files=True)['digest'], 'destination_digest': inventory(destination)['digest']}

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
