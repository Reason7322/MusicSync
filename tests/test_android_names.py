from pathlib import PurePosixPath
import unittest

from musicsync.backend.android_names import destination_paths


class AndroidFilenameTests(unittest.TestCase):
    def test_colon_translation_is_readable_and_preserves_extension(self):
        mapping = destination_paths(
            ["Bloodborne: The Old Hunters OST.mp3"],
            [],
        )

        self.assertEqual(
            mapping["Bloodborne: The Old Hunters OST.mp3"],
            "Bloodborne - The Old Hunters OST.mp3",
        )

    def test_android_invalid_characters_are_replaced_but_unicode_is_preserved(self):
        names = [
            "Zażółć 日本語 🎵.flac",
            'bad\x01name*with?chars<and>pipes|quote"slash\\.mp3',
        ]

        mapping = destination_paths(names, [])

        self.assertEqual(mapping[names[0]], names[0])
        self.assertEqual(
            mapping[names[1]],
            "bad - name - with - chars - and - pipes - quote - slash - .mp3",
        )

    def test_repeated_invalid_characters_collapse_to_one_separator(self):
        name = 'bad :*?<>|"\\ name.mp3'

        self.assertEqual(destination_paths([name], [])[name], 'bad - name.mp3')

    def test_valid_name_keeps_priority_when_translated_names_collide(self):
        names = ["A:B.mp3", "A?B.mp3", "A - B.mp3"]

        mapping = destination_paths(names, [])

        self.assertEqual(mapping["A - B.mp3"], "A - B.mp3")
        self.assertRegex(mapping["A:B.mp3"], r"^A - B~[0-9a-f]{8}\.mp3$")
        self.assertRegex(mapping["A?B.mp3"], r"^A - B~[0-9a-f]{8}\.mp3$")
        self.assertEqual(len(set(mapping.values())), len(names))

    def test_hash_suffix_collision_with_valid_name_is_resolved_deterministically(self):
        colliding = destination_paths(["A:B.mp3", "A - B.mp3"], [])["A:B.mp3"]
        names = ["A:B.mp3", "A - B.mp3", colliding]

        mapping = destination_paths(names, [])

        self.assertEqual(mapping["A - B.mp3"], "A - B.mp3")
        self.assertEqual(mapping[colliding], colliding)
        self.assertNotEqual(mapping["A:B.mp3"], colliding)
        self.assertEqual(len(set(mapping.values())), 3)

    def test_mapping_is_order_independent_and_translates_each_path_component(self):
        files = ["Album: One/Disc?1/Track: 01.opus", "Album - One/keep.mp3"]
        directories = ["Album: One", "Album: One/Disc?1", "Album - One"]

        forward = destination_paths(files, directories)
        reverse = destination_paths(reversed(files), reversed(directories))

        self.assertEqual(forward, reverse)
        self.assertEqual(forward["Album - One"], "Album - One")
        self.assertRegex(forward["Album: One"], r"^Album - One~[0-9a-f]{8}$")
        self.assertIn("Disc - 1", forward["Album: One/Disc?1"])
        self.assertTrue(forward["Album: One/Disc?1/Track: 01.opus"].endswith("/Track - 01.opus"))

    def test_unrelated_source_changes_do_not_remap_existing_paths(self):
        original_files = ["Album: One/Track: 01.mp3", "plain.mp3"]
        directories = ["Album: One"]
        before = destination_paths(original_files, directories)

        after_add = destination_paths(original_files + ["unrelated?.flac"], directories)
        after_remove = destination_paths([original_files[0]], directories)

        for path in original_files:
            self.assertEqual(after_add[path], before[path])
        self.assertEqual(after_remove[original_files[0]], before[original_files[0]])

    def test_long_translation_stays_within_component_limit_and_keeps_extension(self):
        name = ("é" * 124) + ":x.flac"

        translated = destination_paths([name], [])[name]

        self.assertLessEqual(len(translated.encode("utf-8")), 255)
        self.assertEqual(PurePosixPath(translated).suffix, ".flac")
        self.assertRegex(translated, r"~[0-9a-f]{8}\.flac$")


if __name__ == "__main__":
    unittest.main()
