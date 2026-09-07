import json
from pathlib import Path
import tempfile
import unittest

from musicsync.backend.kdeconnect import parse_devices
from musicsync.backend.mounts import parse_findmnt, proc_mounts, validate_mountpoint
from musicsync.backend.replaygain import command
from musicsync.backend.rsync import arguments, parse_change, parse_progress
from musicsync.models import Summary
from fixtures import ConfiguredSettings as Settings
from musicsync.settings import suspicious_deletions


class LogicTests(unittest.TestCase):
    def test_devices(self):
        self.assertEqual([(d.id, d.name) for d in parse_devices("abc-12 Test phone\ndef My phone\n\n")], [("abc-12", "Test phone"), ("def", "My phone")])
        self.assertEqual(parse_devices(""), [])

    def test_itemization(self):
        lines = ["MUSICSYNC|>f+++++++++|123|a song.mp3", "MUSICSYNC|>f.st......|50|x|y.mp3", "MUSICSYNC|*deleting  |0|old.mp3", "MUSICSYNC|cd+++++++++|0|folder/"]
        summary = Summary([parse_change(line) for line in lines])
        self.assertEqual([summary.count(a) for a in ("Add", "Update", "Delete")], [1, 1, 1])
        self.assertEqual(summary.size("Add"), 123)
        self.assertEqual(summary.deletions, 1)
        self.assertEqual(parse_change("MUSICSYNC|>f+++++++++|9|x\\#012z\\#134.mp3").path, "x\nz\\.mp3")
        self.assertIsNone(parse_change("sending incremental file list"))
        with self.assertRaises(ValueError):
            parse_change("MUSICSYNC|>f+++++++++|1|../wrong")
        with self.assertRaises(ValueError):
            parse_change("MUSICSYNC|bad|1|file")

    def test_progress(self):
        self.assertEqual(parse_progress("  12.30M  42%  5.12MB/s 0:00:03")['percent'], 42)

    def test_threshold(self):
        for deleted, total, expected in [(0, 0, False), (20, 100, False), (21, 100, True), (50, 1000, True), (1, 0, True)]:
            self.assertEqual(suspicious_deletions(deleted, total), expected)

    def test_mount_validation(self):
        row = {"target": "/run/user/1000/phone", "fstype": "fuse.sshfs", "source": "kdeconnect@host:/", "id": 42}
        self.assertTrue(parse_findmnt(json.dumps({"filesystems": [row]}), row['target']).expected)
        for key, val in [("fstype", "ext4"), ("source", "someone@host:/")]:
            bad = dict(row, **{key: val})
            self.assertFalse(parse_findmnt(json.dumps({"filesystems": [bad]}), row['target']).expected)
        with self.assertRaises(ValueError):
            parse_findmnt(json.dumps({"filesystems": [row]}), "/another")
        with self.assertRaises(ValueError):
            validate_mountpoint("/")
        mount = proc_mounts("42 1 0:2 / /run/user/1000/phone rw - fuse.sshfs kdeconnect@host:/ rw")[0]
        self.assertEqual(mount.id, 42)

    def test_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            config = Settings(source="/tmp/My music")
            config.save(path)
            self.assertEqual(Settings.load(path), config)
        for remote in ["/storage/emulated/0", "/storage/emulated/0/../Music", "/tmp/Music", "/storage/emulated/0/Music/"]:
            with self.assertRaises(ValueError):
                Settings(remote_dir=remote).validate()

    def test_arguments(self):
        settings = Settings()
        args = arguments(settings, "/tmp/a b", "/tmp/dest", True)
        self.assertEqual(args[-3:], ["--", "/tmp/a b/", "/tmp/dest/"])
        self.assertIn("--dry-run", args)
        self.assertIn("--exclude=/.thumbnails/", args)
        self.assertFalse({"-a", "--ignore-errors", "--delete-excluded"} & set(args))
        self.assertNotIn("--delete-after", arguments(Settings(mirror=False), "/tmp/a", "/tmp/b", False))
        self.assertEqual(command(settings).args[:7], ["easy", "-S", "-m", "4", "-p", settings.preset, settings.source])


if __name__ == "__main__":
    unittest.main()
