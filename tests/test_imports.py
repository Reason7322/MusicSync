"""Mission 01 acceptance: helper modules import through the package."""

import unittest


class TestImports(unittest.TestCase):
    def test_package_and_helper_modules_import(self):
        import musicsyncrename  # noqa: F401
        from musicsyncrename import cleaning, naming, scanner, tags  # noqa: F401

    def test_engine_is_not_part_of_the_public_surface_yet(self):
        # engine.py is a known-broken mid-rewrite draft (PROJECT_STATUS.md);
        # the package must be importable without executing it.
        import musicsyncrename as m

        self.assertFalse(hasattr(m, "engine"))
        self.assertNotIn("engine", m.__all__)

    def test_reexported_names_are_valid_and_present(self):
        import musicsyncrename as m

        expected = [
            # cleaning
            "MAX_NAME_BYTES", "CleanedText", "Reason", "normalize_text",
            "name_key", "clean_text", "clean_filename_stem",
            # scanner
            "ScannedFile", "ScanResult", "scan_root",
            # tags
            "TagSnapshot", "ParseError", "read_tag_snapshot", "apply_tag_edits",
            # naming
            "OST_SUFFIX", "Override", "NameProposal", "make_ost_name",
            "propose_override", "propose_name",
        ]
        for name in expected:
            self.assertIn(name, m.__all__, f"{name} missing from __all__")
            self.assertTrue(hasattr(m, name), f"musicsyncrename.{name} missing")

        # spot-check the kinds of a few exports
        import inspect
        self.assertTrue(inspect.isfunction(m.scan_root))
        self.assertTrue(inspect.isclass(m.TagSnapshot))
        self.assertEqual(m.MAX_NAME_BYTES, 255)


if __name__ == "__main__":
    unittest.main()
