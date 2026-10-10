import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from musicsync.backend.filesystem import (inventory, remote_directory, source_inventory,
                                          staged_source, write_probe)


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

    def test_source_inventory_has_stable_android_mapping_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'A:B.mp3').write_bytes(b'one')
            (root / 'A - B.mp3').write_bytes(b'two')
            first = source_inventory(tmp, require_files=True)
            second = source_inventory(tmp, require_files=True)

            self.assertEqual(first['destination_paths'], second['destination_paths'])
            self.assertEqual(first['mapping_digest'], second['mapping_digest'])
            self.assertEqual(first['destination_paths']['A - B.mp3'], 'A - B.mp3')
            self.assertEqual(len(set(first['destination_paths'].values())), 2)

    def test_staging_pins_regular_files_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as stages:
            root = Path(tmp)
            (root / 'Album: One').mkdir()
            song = root / 'Album: One/Track: 01.mp3'
            song.write_bytes(b'music')
            snapshot = source_inventory(root, require_files=True)
            source_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with staged_source(source_fd, snapshot, stages) as (stage, file_fds):
                    translated = Path(stage) / snapshot['destination_paths']['Album: One/Track: 01.mp3']
                    self.assertTrue(translated.is_symlink())
                    self.assertEqual(translated.read_bytes(), b'music')
                    self.assertGreater(len(file_fds), 0)
                self.assertEqual(os.listdir(stages), [])
            finally:
                os.close(source_fd)

    def test_staging_rejects_source_file_or_parent_swapped_to_symlink(self):
        for swapped in ('file', 'parent'):
            with self.subTest(swapped=swapped), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as stages:
                root = Path(tmp)
                album = root / 'album'
                album.mkdir()
                song = album / 'song.mp3'
                song.write_bytes(b'music')
                outside = root / 'outside.mp3'
                outside.write_bytes(b'outside')
                snapshot = source_inventory(root, require_files=True)
                if swapped == 'file':
                    song.unlink()
                    song.symlink_to(outside)
                else:
                    song.unlink()
                    album.rmdir()
                    album.symlink_to(root)
                source_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    with self.assertRaises(OSError):
                        with staged_source(source_fd, snapshot, stages):
                            self.fail('unsafe source replacement was staged')
                    self.assertEqual(os.listdir(stages), [])
                finally:
                    os.close(source_fd)

    def test_partial_staging_failure_removes_stage_and_closes_files(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as stages:
            root = Path(tmp)
            (root / 'one.mp3').write_bytes(b'one')
            (root / 'two.mp3').write_bytes(b'two')
            snapshot = source_inventory(root, require_files=True)
            source_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            calls = 0
            real_symlink = os.symlink

            def fail_second(target, link):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('injected staging failure')
                real_symlink(target, link)

            try:
                with patch('musicsync.backend.filesystem.os.symlink', side_effect=fail_second):
                    with self.assertRaisesRegex(OSError, 'injected staging failure'):
                        with staged_source(source_fd, snapshot, stages):
                            self.fail('partial stage was accepted')
                self.assertEqual(os.listdir(stages), [])
            finally:
                os.close(source_fd)
