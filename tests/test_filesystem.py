import os
from pathlib import Path
import tempfile
import unittest

from musicsync.backend.filesystem import inventory, remote_directory, write_probe


class FilesystemTests(unittest.TestCase):
    def test_empty_and_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError):
                inventory(tmp, require_files=True)
            with self.assertRaises(OSError):
                inventory(tmp + '/missing', require_files=True)

    def test_inventory_snapshot_and_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'song.mp3').write_bytes(b'music')
            (root / '.thumbnails').mkdir()
            (root / '.thumbnails' / 'cache').write_bytes(b'cache')
            first = inventory(tmp, ['/.thumbnails/'], True)
            self.assertEqual((first['count'], first['tracks'], first['bytes']), (1, 1, 5))
            (root / 'song.mp3').write_bytes(b'changed')
            self.assertNotEqual(first['digest'], inventory(tmp, ['/.thumbnails/'], True)['digest'])

    def test_no_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink('/etc', tmp + '/escape')
            with self.assertRaises(OSError):
                inventory(tmp)

    def test_local_directory_cannot_pass_remote_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError):
                with remote_directory(tmp, '/storage/emulated/0/Music', 123):
                    self.fail('unguarded destination accepted')

    def test_probe_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            fd = os.open(tmp, os.O_DIRECTORY)
            try:
                write_probe(fd)
            finally:
                os.close(fd)
            self.assertEqual(os.listdir(tmp), [])
