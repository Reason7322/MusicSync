"""Focused tests for musicsyncrename.naming (pure logic + one real-file path)."""

import os
import tempfile
import unittest

from musicsyncrename import naming as N
from musicsyncrename.scanner import ScannedFile, scan_root
from musicsyncrename.tags import TagSnapshot, read_tag_snapshot

import fixtures


def scanned(rel_path: str, name: str) -> ScannedFile:
    return ScannedFile(rel_path=rel_path, name=name, size=0, mtime_ns=0)


class TestTagBasedProposal(unittest.TestCase):
    def test_reliable_tags_produce_deterministic_artist_title_name(self):
        sc = scanned("Album/Song.mp3", "song (1).mp3")
        tags = TagSnapshot(has_tags=True, artists=("Test Artist",), titles=("Dream On",))
        p1 = N.propose_name(sc, tags)
        p2 = N.propose_name(sc, tags)  # determinism: same input, same output
        self.assertEqual(p1.status, "ok")
        self.assertEqual(p1.proposed_name, "Test Artist - Dream On.mp3")
        self.assertEqual(p1, p2)

    def test_junk_in_tags_is_cleaned_before_proposal(self):
        sc = scanned("a/b.mp3", "b.mp3")
        tags = TagSnapshot(
            has_tags=True, artists=("Aerosmith",), titles=("Dream On - Lyrics",)
        )
        p = N.propose_name(sc, tags)
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.proposed_name, "Aerosmith - Dream On.mp3")

    def test_legitimate_descriptor_in_title_is_preserved(self):
        sc = scanned("a/c.mp3", "c.mp3")
        tags = TagSnapshot(
            has_tags=True, artists=("Band",), titles=("Dream On (Remastered)",)
        )
        p = N.propose_name(sc, tags)
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.proposed_name, "Band - Dream On (Remastered).mp3")

    def test_real_file_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "messy name (1080p 60fps).mp3")
            fixtures.build_mp3(path)
            fixtures.set_tags(path, artist="Test Artist", title="Dream On")
            result = scan_root(tmp)
            self.assertEqual(len(result.files), 1)
            snap = read_tag_snapshot(os.path.join(tmp, result.files[0].name))
            p = N.propose_name(result.files[0], snap)
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.proposed_name, "Test Artist - Dream On.mp3")


class TestAmbiguousHandling(unittest.TestCase):
    def test_multiple_separators_is_ambiguous(self):
        sc = scanned("Album/x.mp3", "Artist - Title - Remix.mp3")
        p = N.propose_name(sc, TagSnapshot(has_tags=False))
        self.assertEqual(p.status, "ambiguous")
        self.assertIsNone(p.proposed_name)
        self.assertIn("multiple_separators", [r.code for r in p.flags])

    def test_junk_surrounding_one_separator_cleans_to_safe_structure(self):
        # NOTE: the one_side_empty_after_cleanup branch is defensive and not
        # reachable through realistic inputs with the current cleaning rules:
        # any recognized junk on a side of a single separator is either removed
        # by whole-stem cleaning first (taking the separator with it) or leaves
        # both sides non-empty. So this test pins the *actual* conservative
        # behavior instead: layered junk around a genuine Artist - Title shape
        # cleans to exactly that shape, nothing else.
        sc = scanned("Album/y.mp3", "Dream On (Official HD Video) [Lyrics] - Lyrics.mp3")
        p = N.propose_name(sc, TagSnapshot(has_tags=False))
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.proposed_name, "Dream On.mp3")

    def test_conflicting_tag_values_flagged_and_filename_used(self):
        # Two distinct TPE1 values -> no reliable artist; filename shape still
        # exists, so it is used but flagged (not guessed).
        sc = scanned("Album/z.mp3", "RealArtist - RealTitle (1080p 60fps).mp3")
        tags = TagSnapshot(has_tags=True, artists=("X", "Y"), titles=())
        p = N.propose_name(sc, tags)
        codes = [r.code for r in p.flags]
        self.assertIn("conflicting_artist_values", codes)
        self.assertIn("missing_or_empty_title_tag", codes)
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.proposed_name, "RealArtist - RealTitle.mp3")

    def test_tags_cleaning_to_empty_is_ambiguous(self):
        sc = scanned("Album/w.mp3", "w.mp3")
        tags = TagSnapshot(
            has_tags=True, artists=("Band",), titles=("Official HD Video",)
        )
        p = N.propose_name(sc, tags)
        self.assertEqual(p.status, "ambiguous")
        self.assertIsNone(p.proposed_name)


class TestConventionsAndOverrides(unittest.TestCase):
    def test_make_ost_name(self):
        self.assertEqual(
            N.make_ost_name("Elden Ring", "Main Theme"),
            "Elden Ring OST - Main Theme.mp3",
        )
        with self.assertRaises(ValueError):
            N.make_ost_name("", "Main Theme")

    def test_ost_hint_only_flags_never_renames(self):
        sc = scanned(
            "Album/ost.mp3", "My Game - Original Soundtrack (1080p 60fps).mp3"
        )
        p = N.propose_name(sc, TagSnapshot(has_tags=False))
        self.assertIn("ost_candidate", [r.code for r in p.flags])
        # the OST convention is a suggestion flag; the proposal itself stays
        # deterministic (junk group removed, no identity reordering)
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.proposed_name, "My Game - Original Soundtrack.mp3")

    def test_override_wins_when_rel_path_matches(self):
        sc = scanned("Album/song.mp3", "song.mp3")
        tags = TagSnapshot(has_tags=True, artists=("Band",), titles=("Title",))
        ov = N.Override(rel_path="Album/song.mp3", name="Final Choice")
        p = N.propose_name(sc, tags, override=ov)
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.proposed_name, "Final Choice.mp3")

    def test_override_for_other_file_is_ignored(self):
        sc = scanned("Album/song.mp3", "song.mp3")
        tags = TagSnapshot(has_tags=True, artists=("Band",), titles=("Title",))
        ov = N.Override(rel_path="elsewhere/other.mp3", name="Wrong File")
        p = N.propose_name(sc, tags, override=ov)
        self.assertEqual(p.proposed_name, "Band - Title.mp3")

    def test_propose_override_wraps_and_extends(self):
        p = N.propose_override("Final Name")
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.proposed_name, "Final Name.mp3")


if __name__ == "__main__":
    unittest.main()
