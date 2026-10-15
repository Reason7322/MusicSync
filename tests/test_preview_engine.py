"""Mission 02A focused tests: preview engine (build_preview) + move planning.

Covers the mandated targets with synthetic tempdir fixtures only:
- deterministic, read-only previews (byte/mtime snapshot comparison),
- ambiguity and collision detection (proposed_vs_proposed / proposed_vs_live_file),
- unicode-safe name comparisons (NFC/NFKC + casefold via cleaning.name_key),
- malformed-file handling (status "error", parse_error reason),
- empty-stem rejection,
- plan_moves chain/swap/cycle planning verified by ACTUALLY EXECUTING the
  returned os.rename steps against a real tempdir tree and checking that no
  content is ever overwritten.

Import note: ``musicsyncrename.engine`` is imported lazily inside test bodies.
The package __init__ deliberately does not export engine yet (apply/undo are
not tested this mission), and tests/test_imports.py asserts in this shared
unittest process that the 'engine' attribute is absent from the package after a
plain ``import musicsyncrename``. This file sorts alphabetically AFTER
test_imports.py, so deferring the import keeps both facts true at once.
"""

import os
import stat
import struct
import tempfile
import unittest
import zlib

from musicsyncrename import Override  # package surface; does not touch engine
from musicsyncrename.cleaning import name_key

import fixtures


def _engine():
    from musicsyncrename import engine  # noqa: deferred, see module docstring
    return engine


NFC_E = "\u00e9"       # é composed (used for on-disk live filename)
NFD_E = "e\u0301"      # e + combining acute (written into a TIT2 frame)

CORRUPT_BYTES = b"\x00\x01\x02NOTANMP3FILE" * 5


# ---------------------------------------------------------------------------
# Tree builders / helpers
# ---------------------------------------------------------------------------


def build_main_tree(root: str) -> None:
    """The canonical preview tree. Layout (track files marked *):

    tagged/track one.mp3*        reliable tags with junk in TIT2   -> ok + tag edit
    junk/(Official HD Video)*    whole stem is recognized junk     -> ambiguous empty_stem
    garbage/corrupt.mp3          not a readable MP3                -> error parse_error
    plain/K - Song.mp3*          already clean single separator    -> no_change
    multi/A - B - C.mp3*         two separators                    -> ambiguous
    duppair/6. Artist - Title*   leading track number              -> ok (collision A)
    duppair/Artist - Title [Lyrics]*  bracket junk                -> ok (collision A)
    unicode/src.mp3*             NFD title in TIT2                 -> ok (live coll.)
    unicode/K - Cafe Song.mp3*   NFC live occupant, clean          -> no_change
    casedir/a.mp3*               tagged "Kasey" / "Song"           -> ok (case coll.)
    casedir/kasey - song.mp3*    untagged lowercase twin           -> no_change (live)
    notes.txt                    non-MP3                          -> other_file_count
    link.mp3                     symlink to tagged track           -> skipped
    loop                         dir symlink                       -> skipped
    """

    def add(rel: str) -> str:
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fixtures.build_mp3(path)
        return path

    def write_raw(rel: str, data: bytes) -> str:
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    tagged = add("tagged/track one.mp3")
    fixtures.set_tags(tagged, artist="Test Artist", title="Dream On - Lyrics (Official HD Video)")

    add("junk/(Official HD Video).mp3")  # untagged: whole stem is junk

    write_raw("garbage/corrupt.mp3", CORRUPT_BYTES)

    add("plain/K - Song.mp3")
    add("multi/A - B - C.mp3")

    add("duppair/6. Artist - Title.mp3")
    add("duppair/Artist - Title [Lyrics].mp3")

    src = add("unicode/src.mp3")
    fixtures.set_tags(src, artist="K", title=f"Caf{NFD_E} Song")  # NFD in tags
    nfc_live = "unicode/K - Caf" + NFC_E + " Song.mp3"
    write_raw_safe_nfc(root, nfc_live)

    a = add("casedir/a.mp3")
    fixtures.set_tags(a, artist="Kasey", title="Song")

    # untagged lowercase twin: its own proposal equals its current name
    # (no_change), but its live slot casefold-collides with a's proposal key
    add("casedir/kasey - song.mp3")

    write_raw("notes.txt", b"notes")

    os.symlink(tagged, os.path.join(root, "link.mp3"))
    os.symlink(os.path.join(root, "tagged"), os.path.join(root, "loop"))


def write_raw_safe_nfc(root: str, rel: str) -> None:
    path = os.path.join(root, *rel.split("/"))
    fixtures.build_mp3(path)


def snapshot_tree(root: str) -> dict:
    """Map rel path -> (bytes | 'symlink', mtime_ns) for every entry under root."""
    out = {}
    for dirpath, _dirnames, filenames in os.walk(root):  # followlinks=False default
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            st = os.lstat(p)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if stat.S_ISREG(st.st_mode):
                with open(p, "rb") as f:
                    out[rel] = (f.read(), st.st_mtime_ns)
            else:
                out[rel] = ("symlink", st.st_mtime_ns)
    return out


def find_item(preview, rel_path: str):
    for item in preview.items:
        if item.rel_path == rel_path:
            return item
    raise AssertionError(f"no preview item for {rel_path!r}")


def flag_codes(item) -> set:
    return {f.code for f in item.flags}


# ---------------------------------------------------------------------------
# plan_moves — pure planning + execution against real tempdirs
# ---------------------------------------------------------------------------

MARKERS = {"A": b"\xa1" * 64, "B": b"\xb2" * 64, "C": b"\xc3" * 64, "D": b"\xd4" * 64}


class TestPlanMoves(unittest.TestCase):
    def _plan_and_execute(self, tmp: str, ops):
        eng = _engine()
        for ident, (from_rel, _to) in ops:
            src = os.path.join(tmp, *from_rel.split("/"))
            os.makedirs(os.path.dirname(src), exist_ok=True)
            with open(src, "wb") as f:
                f.write(MARKERS[ident])
        steps = eng.plan_moves(ops)
        for step in steps:
            os.rename(os.path.join(tmp, *step.from_rel.split("/")),
                      os.path.join(tmp, *step.to_rel.split("/")))
        final = {}
        for dirpath, _d, filenames in os.walk(tmp):
            base = os.path.relpath(dirpath, tmp)
            for name in sorted(filenames):
                with open(os.path.join(dirpath, name), "rb") as f:
                    rel = (base + "/" + name) if base != "." else name
                    final[rel.replace(os.sep, "/")] = f.read()
        return steps, final

    def _assert_final(self, final, expected):
        self.assertEqual(
            set(final), {rel for rel in expected.values()}, f"files on disk: {sorted(final)}"
        )
        for ident, rel in expected.items():
            self.assertEqual(final.get(rel), MARKERS[ident],
                             f"{rel} should hold content {ident}, got marker mismatch")

    def test_noop_ops_filtered(self):
        eng = _engine()
        self.assertEqual(eng.plan_moves([("a", ("d/a.mp3", "d/a.mp3"))]), [])
        # name_key-equal (case variant) is also a no-op by design
        self.assertEqual(eng.plan_moves([("a", ("d/a.MP3", "d/a.mp3"))]), [])

    def test_chain_dependency_order_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            steps, final = self._plan_and_execute(
                tmp, [("A", ("a.mp3", "b.mp3")), ("B", ("b.mp3", "c.mp3"))])
        # dependency-first: B (b->c) must run before A (a->b)
        self.assertEqual([s.content for s in steps], ["B", "A"])
        self.assertTrue(all(s.kind == "rename" for s in steps))
        self._assert_final(final, {"A": "b.mp3", "B": "c.mp3"})

    def test_swap_two_cycle_root_uses_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            ops = [("A", ("a.mp3", "b.mp3")), ("B", ("b.mp3", "a.mp3"))]
            steps, final = self._plan_and_execute(tmp, ops)
        self.assertEqual(sum(1 for s in steps if s.kind == "temp"), 1)
        # no temp file left behind; contents swapped intact
        self.assertFalse(any(".tmp-musicsync-rename-" in rel for rel in final))
        self._assert_final(final, {"A": "b.mp3", "B": "a.mp3"})

    def test_three_cycle_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            ops = [("A", ("a.mp3", "b.mp3")),
                   ("B", ("b.mp3", "c.mp3")),
                   ("C", ("c.mp3", "a.mp3"))]
            steps, final = self._plan_and_execute(tmp, ops)
        self.assertTrue(any(s.kind == "temp" for s in steps))
        self._assert_final(final, {"A": "b.mp3", "B": "c.mp3", "C": "a.mp3"})

    def test_mixed_swap_plus_chain_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            ops = [("A", ("a.mp3", "b.mp3")), ("B", ("b.mp3", "a.mp3")),
                   ("C", ("c.mp3", "d.mp3")), ("D", ("d.mp3", "e.mp3"))]
            _steps, final = self._plan_and_execute(tmp, ops)
        self._assert_final(final, {"A": "b.mp3", "B": "a.mp3", "C": "d.mp3", "D": "e.mp3"})

    def test_chain_nonroot_directory(self):
        # Regression: holder tracking must compare filename keys (not full
        # relative paths) or B's content is overwritten when A moves into b.
        with tempfile.TemporaryDirectory() as tmp:
            steps, final = self._plan_and_execute(
                tmp, [("A", ("sub/a.mp3", "sub/b.mp3")), ("B", ("sub/b.mp3", "sub/c.mp3"))])
        self.assertEqual([s.content for s in steps], ["B", "A"])
        self._assert_final(final, {"A": "sub/b.mp3", "B": "sub/c.mp3"})

    def test_swap_nonroot_directory(self):
        # Regression: temp moves must keep the full relative path (parent dir)
        # in the planner's current-position map; a bare name breaks execution.
        with tempfile.TemporaryDirectory() as tmp:
            ops = [("A", ("sub/a.mp3", "sub/b.mp3")), ("B", ("sub/b.mp3", "sub/a.mp3"))]
            steps, final = self._plan_and_execute(tmp, ops)
        temp_steps = [s for s in steps if s.kind == "temp"]
        self.assertEqual(len(temp_steps), 1)
        # every step must stay inside the sub/ directory (parent preserved)
        for s in steps:
            self.assertTrue(s.from_rel.startswith("sub/") and s.to_rel.startswith("sub/"),
                            f"step left its parent dir: {s}")
        self.assertFalse(any(".tmp-musicsync-rename-" in rel for rel in final))
        self._assert_final(final, {"A": "sub/b.mp3", "B": "sub/a.mp3"})

    def test_duplicate_normalized_target_raises(self):
        eng = _engine()
        ops = [("a", ("x.mp3", "y.mp3")), ("b", ("z.mp3", "Y.MP3"))]
        with self.assertRaises(eng.EngineError) as ctx:
            eng.plan_moves(ops)
        self.assertIn("y.mp3", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# build_preview — statuses, collisions, determinism, non-mutation
# ---------------------------------------------------------------------------

class TestBuildPreview(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.abspath(self._tmp.name)
        build_main_tree(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_status_matrix_and_counts(self):
        eng = _engine()
        p = eng.build_preview(self.root)
        expected = {
            "tagged/track one.mp3": "ok",
            "junk/(Official HD Video).mp3": "ambiguous",
            "garbage/corrupt.mp3": "error",
            "plain/K - Song.mp3": "no_change",
            "multi/A - B - C.mp3": "ambiguous",
            "duppair/6. Artist - Title.mp3": "ok",
            "duppair/Artist - Title [Lyrics].mp3": "ok",
            "unicode/src.mp3": "ok",
            "casedir/a.mp3": "ok",
            "casedir/kasey - song.mp3": "no_change",
        }
        self.assertEqual(len(p.items), len(expected) + 1)  # + the NFC live occupant
        for rel, status in expected.items():
            item = find_item(p, rel)
            self.assertEqual(item.status, status, f"{rel}: {item}")
        nfc_live_rel = "unicode/K - Caf" + NFC_E + " Song.mp3"
        self.assertEqual(find_item(p, nfc_live_rel).status, "no_change")
        self.assertEqual(p.counts_by_status, {"ok": 5, "no_change": 3, "ambiguous": 2, "error": 1})
        self.assertEqual(p.root, self.root)

    def test_tag_based_proposal_and_edits(self):
        eng = _engine()
        p = eng.build_preview(self.root)
        item = find_item(p, "tagged/track one.mp3")
        self.assertEqual(item.proposed_name, "Test Artist - Dream On.mp3")
        # TIT2 carried junk; TPE1 was clean -> exactly one edit tuple
        self.assertEqual(
            item.tag_edits,
            (("TIT2", "Dream On - Lyrics (Official HD Video)", "Dream On"),),
        )

    def test_empty_stem_proposal_rejected(self):
        eng = _engine()
        p = eng.build_preview(self.root)
        item = find_item(p, "junk/(Official HD Video).mp3")
        self.assertEqual(item.status, "ambiguous")
        self.assertIsNone(item.proposed_name)  # no proposal: not approvable
        self.assertIn("empty_stem", flag_codes(item))

    def test_malformed_file_is_error_not_crash(self):
        eng = _engine()
        p = eng.build_preview(self.root)
        item = find_item(p, "garbage/corrupt.mp3")
        self.assertEqual(item.status, "error")
        self.assertIsNone(item.proposed_name)
        self.assertEqual(item.reasons[0].code, "parse_error")

    def test_ambiguous_items_carry_no_proposal(self):
        eng = _engine()
        p = eng.build_preview(self.root)
        item = find_item(p, "multi/A - B - C.mp3")
        self.assertEqual(item.status, "ambiguous")
        self.assertIsNone(item.proposed_name)
        self.assertIn("multiple_separators", flag_codes(item))

    def test_collision_reports_and_flags(self):
        eng = _engine()
        p = eng.build_preview(self.root)
        by_kind = {(c.directory, c.kind) for c in p.collisions}
        self.assertEqual(
            by_kind,
            {("duppair", "proposed_vs_proposed"),
             ("unicode", "proposed_vs_live_file"),
             ("casedir", "proposed_vs_live_file")},
        )
        # proposed vs proposed: both owners listed (order-insensitive compare)
        pvp = next(c for c in p.collisions if c.kind == "proposed_vs_proposed")
        self.assertEqual(
            sorted(pvp.involved),
            ["duppair/6. Artist - Title.mp3", "duppair/Artist - Title [Lyrics].mp3"],
        )
        # unicode: NFD proposal collides with the NFC live file (NFKC+casefold)
        uni = next(c for c in p.collisions if c.directory == "unicode")
        self.assertEqual(uni.involved[0], "unicode/src.mp3")
        nfc_live_name = "K - Caf" + NFC_E + " Song.mp3"
        self.assertEqual(uni.involved[1], "live:" + nfc_live_name)
        # case: proposal "Kasey - Song.mp3" collides with live non-track file
        cas = next(c for c in p.collisions if c.directory == "casedir")
        self.assertEqual(cas.involved, ("casedir/a.mp3", "live:kasey - song.mp3"))

        for rel in ("duppair/6. Artist - Title.mp3", "duppair/Artist - Title [Lyrics].mp3",
                    "unicode/src.mp3", "casedir/a.mp3"):
            self.assertIn("preview_collision", flag_codes(find_item(p, rel)), rel)
        # clean item must NOT carry a collision flag
        self.assertNotIn("preview_collision", flag_codes(find_item(p, "tagged/track one.mp3")))

    def test_symlinks_skipped_and_not_items(self):
        eng = _engine()
        p = eng.build_preview(self.root)
        self.assertIn("link.mp3", p.symlinks_skipped)
        self.assertIn("loop", p.symlinks_skipped)
        rels = {i.rel_path for i in p.items}
        self.assertNotIn("link.mp3", rels)

    def test_preview_is_deterministic(self):
        eng = _engine()
        p1 = eng.build_preview(self.root)
        p2 = eng.build_preview(self.root)
        self.assertEqual(p1, p2)  # full dataclass equality incl. ordering
        self.assertEqual(p1.counts_by_status, p2.counts_by_status)

    def test_preview_is_read_only(self):
        before = snapshot_tree(self.root)
        eng = _engine()
        p = eng.build_preview(self.root)
        after = snapshot_tree(self.root)
        self.assertEqual(before, after, "build_preview modified the tree")
        # and it must not create journal infrastructure at all
        self.assertFalse(os.path.exists(os.path.join(self.root, eng.JOURNAL_DIRNAME)))
        # sanity: we actually previewed something
        self.assertGreater(len(p.items), 0)


# ---------------------------------------------------------------------------
# build_preview — overrides, OST hints, safety flags (small isolated trees)
# ---------------------------------------------------------------------------

class TestPreviewOverridesAndSafety(unittest.TestCase):
    def _one_track_tree(self, tmp: str):
        path = os.path.join(tmp, "s", "one.mp3")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fixtures.build_mp3(path)
        fixtures.set_tags(path, artist="X", title="T")
        return "s/one.mp3"

    def test_empty_override_name_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._one_track_tree(tmp)
            eng = _engine()
            p = eng.build_preview(tmp, overrides=[Override(rel_path=rel, name="")])
            item = find_item(p, rel)
            self.assertEqual(item.status, "error")
            self.assertEqual(item.reasons[0].code, "invalid_override")

    def test_empty_stem_override_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._one_track_tree(tmp)
            eng = _engine()
            p = eng.build_preview(tmp, overrides=[Override(rel_path=rel, name=".mp3")])
            item = find_item(p, rel)
            self.assertEqual(item.status, "ambiguous")
            self.assertIsNone(item.proposed_name)  # renaming to a hidden file is refused
            self.assertIn("empty_stem", flag_codes(item))

    def test_long_override_flagged_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._one_track_tree(tmp)
            eng = _engine()
            p = eng.build_preview(tmp, overrides=[Override(rel_path=rel, name="L" * 300)])
            item = find_item(p, rel)
            self.assertIn("name_too_long", flag_codes(item))

    def test_ost_hint_with_slash_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._one_track_tree(tmp)
            eng = _engine()
            p = eng.build_preview(tmp, ost_hints={rel: "A/B"})
            item = find_item(p, rel)
            self.assertEqual(item.status, "ok")
            self.assertEqual(item.proposed_name, "A/B OST - T.mp3")
            # the hinted name contains a path separator -> must be flagged at preview time
            self.assertIn("name_contains_unsafe_chars", flag_codes(item))


# ---------------------------------------------------------------------------
# fixtures: 1x1 RGBA PNG scanline is exactly 5 bytes (filter byte + RGBA pixel)
# ---------------------------------------------------------------------------

class TestPngScanline(unittest.TestCase):
    def _chunks(self, data: bytes) -> dict:
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"), "not a PNG")
        pos, out = 8, {}
        while pos < len(data):
            (length,), tag = struct.unpack(">I", data[pos:pos + 4]), data[pos + 4:pos + 8]
            payload = data[pos + 8:pos + 8 + length]
            (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
            self.assertEqual(crc, zlib.crc32(tag + payload) & 0xFFFFFFFF, f"bad CRC in {tag}")
            out[tag] = payload
            pos += 12 + length
        return out

    def test_1x1_rgba_scanline_is_five_bytes(self):
        data = fixtures.make_png_1x1()
        chunks = self._chunks(data)
        width, height, depth, ctype = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
        self.assertEqual((width, height, depth, ctype), (1, 1, 8, 6))
        scanline = zlib.decompress(b"".join(chunks[k] for k in (b"IDAT",) if k in chunks))
        # filter byte + 4 RGBA bytes; the previous fixture emitted only 4 total
        self.assertEqual(len(scanline), 5)
        self.assertEqual(scanline[0], 0)  # "None" filter

    def test_apic_roundtrip_keeps_five_byte_scanline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "art.mp3")
            fixtures.build_mp3(path)
            expected = fixtures.make_png_1x1()
            fixtures.add_basic_tags(path)
            from mutagen.mp3 import MP3
            tags = MP3(path).tags
            apics = fixtures.frame_frames(tags, "APIC")
            self.assertEqual(len(apics), 1)
            self.assertEqual(bytes(apics[0].data), expected)


if __name__ == "__main__":
    unittest.main()
