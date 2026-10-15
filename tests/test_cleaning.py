"""Focused tests for musicsyncrename.cleaning (pure, no I/O)."""

import unittest

from musicsyncrename import cleaning as C


class TestJunkRemoval(unittest.TestCase):
    def test_trailing_lyrics_suffix(self):
        ct = C.clean_text("Dream On - Lyrics")
        self.assertEqual(ct.value, "Dream On")
        self.assertIn("removed_junk_suffix", [r.code for r in ct.reasons])

    def test_official_hd_video_paren_group(self):
        ct = C.clean_text("(Official HD Video)")
        self.assertEqual(ct.value, "")
        self.assertTrue(any(r.code == "removed_junk_group" for r in ct.reasons))

    def test_bracket_lyrics_group_and_trailing_audio_kbps(self):
        ct = C.clean_text("Song Title [Lyrics]")
        self.assertEqual(ct.value, "Song Title")
        ct2 = C.clean_text("Song Title audio 320 kbps original")
        self.assertEqual(ct2.value, "Song Title")
        self.assertTrue(any(r.code == "removed_junk_suffix" for r in ct2.reasons))

    def test_fullwidth_colon_normalized_then_trailing_lyrics(self):
        ct = C.clean_text("Dream On\uff1aLyrics")  # ： fullwidth colon
        self.assertEqual(ct.value, "Dream On")
        codes = [r.code for r in ct.reasons]
        self.assertIn("replaced_broken_punctuation", codes)

    def test_leading_track_number_removed_only_for_filename_stems(self):
        stem = C.clean_filename_stem("6. Dream On")
        self.assertEqual(stem.value, "Dream On")
        self.assertTrue(any(r.code == "removed_track_number" for r in stem.reasons))
        # the tag-value path must NOT strip leading numbering
        tag = C.clean_text("6. Dream On")
        self.assertEqual(tag.value, "6. Dream On")


class TestDescriptorPreservation(unittest.TestCase):
    def test_genuine_version_descriptors_untouched(self):
        for text in (
            "Dream On (Remastered)",
            "Song (Game Version)",
            "Theme [Explicit]",
            "DmC: Devil May Cry OST",
        ):
            with self.subTest(text=text):
                ct = C.clean_text(text)
                self.assertEqual(ct.value, text, f"descriptor was altered in {text!r}")

    def test_fullwidth_bar_is_not_a_separator(self):
        # "Game｜DLC｜Track" must stay a single whole identifier.
        ct = C.clean_text("Game\uff5cDLC\uff5cTrack")  # ｜ fullwidth bar
        self.assertEqual(ct.value, "Game\uff5cDLC\uff5cTrack")


class TestNormalizationAndDeterminism(unittest.TestCase):
    def test_whitespace_finalize(self):
        ct = C.clean_text("  Song   Title ")
        self.assertEqual(ct.value, "Song Title")

    def test_quote_unwrap_and_negative_case(self):
        ct = C.clean_text('"Dream On"')
        self.assertEqual(ct.value, "Dream On")
        # mid-word apostrophes must never be unwrapped
        neg = C.clean_text("O'Brien - Song")
        self.assertEqual(neg.value, "O'Brien - Song")

    def test_name_key_collision_semantics(self):
        # NFD and NFC forms of the same name collide...
        nfd = "Cafe\u0301 - Title.mp3"  # e + combining acute
        nfc = "Caf\u00e9 - Title.mp3"  # precomposed é
        self.assertEqual(C.name_key(nfd), C.name_key(nfc))
        # ...as do case variants...
        self.assertEqual(
            C.name_key("Artist - Title.MP3"), C.name_key("artist - title.mp3")
        )
        # ...but distinct names do not collide.
        self.assertNotEqual(C.name_key("a.mp3"), C.name_key("b.mp3"))

    def test_clean_text_is_deterministic(self):
        sample = "6. Dream On (Official HD Video) - Lyrics"
        for cleaner in (C.clean_text, C.clean_filename_stem):
            a, b = cleaner(sample), cleaner(sample)
            self.assertEqual(a.value, b.value)
            self.assertEqual(
                tuple(r.code for r in a.reasons), tuple(r.code for r in b.reasons)
            )


if __name__ == "__main__":
    unittest.main()
