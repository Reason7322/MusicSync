"""Focused tests for musicsyncrename.scanner (synthetic tempdir library only)."""

import os
import shutil
import tempfile
import unittest

from musicsyncrename import scanner as S

import fixtures


class TestScanRoot(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        root = self.root.name
        # real MP3s (nested + uppercase extension)
        self.song_one = os.path.join(root, "Album A", "Song One.mp3")
        self.song_two = os.path.join(root, "Album B", "Song Two.MP3")
        os.makedirs(os.path.dirname(self.song_one))
        os.makedirs(os.path.dirname(self.song_two))
        fixtures.build_mp3(self.song_one)
        fixtures.build_mp3(self.song_two)
        # non-MP3 regular file
        self.readme = os.path.join(root, "readme.txt")
        with open(self.readme, "wb") as f:
            f.write(b"not a track")
        # symlinked directory (contains an MP3 that must NOT be scanned) and
        # symlinked file — both must be skipped, never traversed/renamed.
        self.outside = tempfile.TemporaryDirectory()
        outside_song = os.path.join(self.outside.name, "Outside Song.mp3")
        fixtures.build_mp3(outside_song)
        os.symlink(self.outside.name, os.path.join(root, "link_dir"))
        os.symlink(self.song_one, os.path.join(root, "link_song.mp3"))

    def tearDown(self):
        self.root.cleanup()
        self.outside.cleanup()

    def test_only_real_mp3s_are_tracks_and_order_is_deterministic(self):
        result = S.scan_root(self.root.name)
        rel_paths = [f.rel_path for f in result.files]
        self.assertEqual(rel_paths, ["Album A/Song One.mp3", "Album B/Song Two.MP3"])
        for f in result.files:
            self.assertGreater(f.size, 0)
            self.assertIsInstance(f.mtime_ns, int)
            self.assertTrue(os.path.isfile(os.path.join(self.root.name, *f.rel_path.split("/"))))
        # a second scan of the untouched tree is byte-for-byte identical
        again = S.scan_root(self.root.name)
        self.assertEqual(result.files, again.files)

    def test_symlinks_are_reported_and_never_traversed(self):
        result = S.scan_root(self.root.name)
        self.assertIn("link_dir", result.symlinks_skipped)
        self.assertIn("link_song.mp3", result.symlinks_skipped)
        # the MP3 behind the directory symlink is never scanned
        for f in result.files:
            self.assertFalse(f.rel_path.startswith("link_dir/"))

    def test_counts_and_entries(self):
        result = S.scan_root(self.root.name)
        self.assertEqual(result.other_file_count, 1)  # readme.txt only
        self.assertEqual(result.directory_count, 2)   # Album A, Album B
        self.assertIn("readme.txt", result.dir_entries[""])
        self.assertTrue(all(f.rel_path for f in result.files))

    def test_parent_property_and_fingerprint(self):
        result = S.scan_root(self.root.name)
        song = result.file("Album A/Song One.mp3")
        self.assertIsNotNone(song)
        self.assertEqual(song.parent, "Album A")
        fp = S.fingerprint_files(result)
        self.assertEqual(
            fp["Album A/Song One.mp3"], (song.size, song.mtime_ns)
        )
        self.assertEqual(len(fp), len(result.files))

    def test_scan_root_rejects_non_directory(self):
        with self.assertRaises(NotADirectoryError):
            S.scan_root(self.readme)


if __name__ == "__main__":
    unittest.main()
