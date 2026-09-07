import hashlib
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

from musicsync.backend.replaygain import command, processed_tracks
from musicsync.models import Command
from musicsync.settings import Settings
from test_process import run


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('rsgain') and importlib.util.find_spec('mutagen'), 'optional real tagging test needs ffmpeg, rsgain and mutagen')
class ReplayGainIntegrationTests(unittest.TestCase):
    def test_new_track_tagged_then_skipped_byte_for_byte(self):
        from mutagen.id3 import ID3
        with tempfile.TemporaryDirectory(prefix='musicsync-replaygain-') as temporary:
            song = Path(temporary) / 'new track.mp3'
            generated, _ = run(Command('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-c:a', 'libmp3lame', str(song)]))
            self.assertEqual(generated.code, 0, generated.stderr)
            tagged, _ = run(command(Settings(source=temporary)))
            self.assertEqual(tagged.code, 0, tagged.stderr)
            tags = ID3(song)
            names = {frame.desc.lower() for frame in tags.getall('TXXX')}
            self.assertIn('replaygain_track_gain', names)
            self.assertIn('replaygain_track_peak', names)
            self.assertNotIn('replaygain_album_gain', names)
            before = hashlib.sha256(song.read_bytes()).hexdigest()
            skipped, _ = run(command(Settings(source=temporary)))
            self.assertEqual(skipped.code, 0, skipped.stderr)
            self.assertEqual(before, hashlib.sha256(song.read_bytes()).hexdigest())
            self.assertIn('Skipped 1 file', skipped.stdout + skipped.stderr)
            self.assertFalse(processed_tracks(skipped.stdout + skipped.stderr))
            self.assertTrue(processed_tracks(tagged.stdout + tagged.stderr))
