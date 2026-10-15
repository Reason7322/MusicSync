"""Focused tests for musicsyncrename.tags (synthetic MP3s in tempdirs only)."""

import os
import tempfile
import unittest

from mutagen.mp3 import MP3

from musicsyncrename import tags as T

import fixtures


def _read(path) -> bytes:
    with open(str(path), "rb") as f:
        return f.read()


class TestReadTagSnapshot(unittest.TestCase):
    def test_untagged_silent_mp3_reports_no_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = fixtures.build_mp3(os.path.join(tmp, "plain.mp3"))
            snap = T.read_tag_snapshot(path)
        self.assertFalse(snap.has_tags)
        self.assertEqual(snap.artists, ())
        self.assertEqual(snap.titles, ())
        self.assertIsNone(snap.album)
        self.assertEqual(snap.replaygain_keys, ())
        self.assertEqual(snap.artwork_frames, 0)

    def test_full_synthetic_tag_set_is_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = fixtures.build_mp3(os.path.join(tmp, "tagged.mp3"))
            fixtures.add_basic_tags(path)
            snap = T.read_tag_snapshot(path)
        self.assertTrue(snap.has_tags)
        self.assertEqual(snap.artist, "Test Artist")
        self.assertEqual(
            snap.title, "Dream On - Lyrics (Official HD Video)"
        )
        self.assertEqual(snap.album, "Toys in the Attic")
        self.assertIn("RVRB", snap.replaygain_keys)
        self.assertIn("TXXX:REPLAYGAIN_TRACK_GAIN", snap.replaygain_keys)
        self.assertIn("TXXX:REPLAYGAIN_ALBUM_PEAK", snap.replaygain_keys)
        self.assertEqual(snap.artwork_frames, 1)
        self.assertGreaterEqual(snap.frame_key_count, 6)

    def test_conflicting_multi_values_yield_no_single_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = fixtures.build_mp3(os.path.join(tmp, "conflict.mp3"))
            from mutagen.id3 import TPE1
            audio = MP3(path)
            if audio.tags is None:
                audio.add_tags()
            # one frame holding two distinct values (the on-disk form of a
            # conflicting TPE1; mutagen keeps .text as a list across save+reload)
            audio.tags.add(TPE1(encoding=3, text=["Artist One", "Artist Two"]))
            audio.save()
            snap = T.read_tag_snapshot(path)
        self.assertTrue(snap.has_tags)
        self.assertEqual(tuple(sorted(snap.artists)), ("Artist One", "Artist Two"))
        self.assertIsNone(snap.artist)  # conflicting -> no single reliable value


class TestApplyTagEdits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = fixtures.build_mp3(os.path.join(self.tmp.name, "track.mp3"))
        fixtures.add_basic_tags(self.path)
        self.before_bytes = _read(self.path)
        self.png = fixtures.make_png_1x1()

    def tearDown(self):
        self.tmp.cleanup()

    def _tags_of(self, path=None):
        return MP3(path or self.path).tags

    def test_restricted_edit_changes_only_the_target_frame(self):
        T.apply_tag_edits(self.path, {"TIT2": "Dream On"})
        after_bytes = _read(self.path)
        snap = T.read_tag_snapshot(self.path)
        # the target changed...
        self.assertEqual(snap.title, "Dream On")
        # ...and everything else is preserved
        self.assertEqual(snap.artist, "Test Artist")
        self.assertEqual(snap.album, "Toys in the Attic")
        self.assertIn("RVRB", snap.replaygain_keys)
        self.assertEqual(
            sorted(k for k in snap.replaygain_keys if k.startswith("TXXX:")),
            ["TXXX:REPLAYGAIN_ALBUM_PEAK", "TXXX:REPLAYGAIN_TRACK_GAIN"],
        )
        # audio region byte-identical (verified comparison method)
        self.assertEqual(
            fixtures.audio_part(self.before_bytes), fixtures.audio_part(after_bytes)
        )

    def test_artwork_bytes_and_replaygain_frames_survive_edit(self):
        T.apply_tag_edits(self.path, {"TIT2": "Dream On", "TPE1": "The Test Band"})
        tags = self._tags_of()
        apics = fixtures.frame_frames(tags, "APIC")
        self.assertEqual(len(apics), 1)
        self.assertEqual(bytes(apics[0].data), self.png)  # artwork byte-equal
        self.assertEqual(
            len(fixtures.frame_frames(tags, "RVRB")), 1
        )  # ReplayGain block intact
        rg_track = tags.getall("TXXX:REPLAYGAIN_TRACK_GAIN")
        self.assertEqual(len(rg_track), 1)
        self.assertIn("-8.2 dB", [str(x).strip() for x in rg_track[0].text])

    def test_edit_can_delete_a_frame(self):
        T.apply_tag_edits(self.path, {"TPE1": None})
        tags = self._tags_of()
        self.assertEqual(fixtures.frame_frames(tags, "TPE1"), [])
        # sibling frame untouched; audio intact
        self.assertTrue(
            fixtures.frame_frames(tags, "TIT2")
        )
        self.assertEqual(
            fixtures.audio_part(self.before_bytes),
            fixtures.audio_part(_read(self.path)),
        )

    def test_unsupported_frames_are_refused(self):
        for bad in ({"TALB": "New Album"}, {"APIC": None}, {"TXXX:REPLAYGAIN_TRACK_GAIN": "-1.0 dB"}):
            with self.assertRaises(ValueError, msg=f"{bad} must be refused"):
                T.apply_tag_edits(self.path, bad)

    def test_empty_edits_is_a_noop(self):
        original = _read(self.path)
        T.apply_tag_edits(self.path, {})
        self.assertEqual(_read(self.path), original)


class TestParseErrors(unittest.TestCase):
    def test_malformed_file_raises_parse_error_on_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "garbage.mp3")
            with open(path, "wb") as f:  # no MPEG sync bytes anywhere
                f.write(b"NOTANMP3FILE" * 8)
            with self.assertRaises(T.ParseError):
                T.read_tag_snapshot(path)

    def test_malformed_file_raises_parse_error_on_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "garbage.mp3")
            with open(path, "wb") as f:
                f.write(b"NOTANMP3FILE" * 8)
            with self.assertRaises(T.ParseError):
                T.apply_tag_edits(path, {"TIT2": "Anything"})


if __name__ == "__main__":
    unittest.main()
