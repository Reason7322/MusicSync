"""Mission 02B focused tests: apply_changes / undo_session / list_sessions.

Everything runs on synthetic fixtures inside disposable tempdirs - no live
library, no MusicSync installation, no historical data is ever touched.

Import note (house convention, do not break): ``musicsyncrename.engine`` is
imported lazily inside test bodies via ``_engine()``. The package __init__
deliberately does not export engine, and tests/test_imports.py asserts that in
this shared unittest process; this file also sorts alphabetically AFTER
test_imports.py, so both facts hold at once.

Covers the mandated apply/undo matrix: roundtrip byte-exactness (names AND
bytes), tags-only changes with APIC/ReplayGain/audio preservation, chains and
cycles through the verified planner, case-insensitive + Unicode collision
rejection, changed-since-preview independence, invalid/ambiguous/unapproved
rejections, cancellation and injected failures at mutation stages, journal
replay of interrupted operations, no-change undo validation failures, session
introspection, concurrency protection, idempotent recovery.
"""

import json
import os
import shutil
import tempfile
import unittest

import fixtures  # local tests package (no engine involvement)
from musicsyncrename import Override  # package surface; does not touch engine


def _engine():
    from musicsyncrename import engine  # noqa: deferred, see module docstring
    return engine


# ---------------------------------------------------------------------------
# Helpers (synthetic trees only)
# ---------------------------------------------------------------------------


class ApplyUndoTestBase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._td.name, "library")
        os.makedirs(self.root)

    def tearDown(self):
        self._td.cleanup()

    # -- tree building -------------------------------------------------------

    def add_mp3(self, rel: str, frames: int = 8, artist=None, title=None) -> str:
        """Build a synthetic silent MP3 at ``rel`` under root.

        Different ``frames`` counts give different sizes (content markers for
        pure-rename identity checks); optional TPE1/TIT2 attach reliable tags.
        """
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fixtures.build_mp3(path, frames=frames)
        if artist is not None or title is not None:
            fixtures.set_tags(path, artist=artist, title=title)
        return path

    def write_raw(self, rel: str, data: bytes) -> str:
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    # -- snapshots -----------------------------------------------------------

    def tree_snapshot(self) -> dict:
        """rel path -> (bytes | 'symlink' | dir-marker, mtime_ns); whole-tree."""
        out = {}
        for dirpath, dirnames, filenames in os.walk(self.root):
            for name in sorted(filenames + [d for d in dirnames]):
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, self.root).replace(os.sep, "/")
                if os.path.islink(full):
                    out[rel] = ("symlink", os.lstat(full).st_mtime_ns)
                elif os.path.isdir(full):
                    continue  # directory entries themselves need no byte copy
                else:
                    with open(full, "rb") as handle:
                        out[rel] = (handle.read(), os.stat(full).st_mtime_ns)
        return out

    def tree_bytes(self) -> dict:
        """rel path -> bytes for plain files only (identity checks)."""
        return {k: v[0] for k, v in self.tree_snapshot().items() if isinstance(v[0], bytes)}

    def public_tree(self):
        """tree_snapshot() minus the journal dir (journals legitimately grow).

        Used to prove zero-mutation / exact-restore on the LIBRARY files while
        ignoring ``.musicsyncrename`` bookkeeping that is allowed to change.
        """
        return {
            k: v
            for k, v in self.tree_snapshot().items()
            if not k.startswith(".musicsyncrename")
        }

    def craft_journal(self, session_id: str, events: list) -> str:
        """Hand-write a raw journal file (crash simulation). Returns its path."""
        sessions = _sessions_dir(self.root)
        os.makedirs(sessions, exist_ok=True)
        path = os.path.join(sessions, session_id + ".jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")
        return path

    @staticmethod
    def read_bytes(path) -> bytes:
        with open(path, "rb") as handle:
            return handle.read()



def _read_events(path) -> list:
    """Parse a journal file into event dicts (tests' read-only view)."""
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _sessions_dir(root: str) -> str:
    return os.path.join(root, ".musicsyncrename", "sessions")


def _id3_frames(path):
    """Open a synthetic MP3 and return (ID3 tags or None, audio bytes)."""
    from mutagen.mp3 import MP3

    audio = MP3(str(path))
    with open(str(path), "rb") as handle:
        blob = handle.read()
    return (audio.tags if audio.tags is not None else {}), blob


# ---------------------------------------------------------------------------
# A. Single rename + journal structure; tagged roundtrip with byte-exact undo
# ---------------------------------------------------------------------------


class TestApplySingleRename(ApplyUndoTestBase):
    def test_plain_rename_applies_and_writes_full_journal(self):
        eng = _engine()
        path = self.add_mp3("b.mp3")
        original_blob = self.read_bytes(path)

        preview = eng.build_preview(self.root, overrides=[Override("b.mp3", "B - Renamed")])

        item = {i.rel_path: i for i in preview.items}["b.mp3"]
        self.assertEqual(item.status, "ok")
        self.assertEqual(item.proposed_name, "B - Renamed.mp3")

        report = eng.apply_changes(self.root, preview, ["b.mp3"])
        self.assertTrue(report.ok, msg=f"report={report!r}")
        self.assertEqual(report.applied, (("b.mp3", "B - Renamed.mp3"),))
        self.assertEqual(report.rejected, ())
        self.assertEqual(report.partial, ())
        self.assertEqual(report.canceled, ())

        # Filesystem: renamed, bytes identical.
        self.assertEqual(
            self.read_bytes(os.path.join(self.root, "B - Renamed.mp3")), original_blob
        )
        self.assertFalse(os.path.exists(path))

        # Journal: header/op/done/closed, one line per event, fsynced JSON.
        sessions = os.path.join(self.root, ".musicsyncrename", "sessions")
        files = os.listdir(sessions)
        self.assertEqual(files, [report.session_id + ".jsonl"])
        events = _read_events(os.path.join(sessions, files[0]))
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds, ["header", "op", "done", "closed"])
        self.assertEqual(events[0]["id"], report.session_id)
        self.assertEqual(
            (events[1]["content"], events[1]["from"], events[1]["to"], events[1]["kind"]),
            ("b.mp3", "b.mp3", "B - Renamed.mp3", "rename"),
        )
        self.assertEqual(events[2], {"type": "done", "content": "b.mp3", "kind": "rename"})


class TestApplyUndoRoundtrip(ApplyUndoTestBase):
    def test_tagged_rename_undo_restores_names_and_bytes_exactly(self):
        from pathlib import Path

        eng = _engine()
        self.add_mp3("track one.mp3", artist="Test Artist", title="Dream On - Lyrics (Official HD Video)")
        original_path = os.path.join(self.root, "track one.mp3")
        original_bytes = self.read_bytes(original_path)

        preview = eng.build_preview(self.root)
        item = {i.rel_path: i for i in preview.items}["track one.mp3"]
        self.assertEqual(item.status, "ok")
        self.assertEqual(item.proposed_name, "Test Artist - Dream On.mp3")
        self.assertTrue(
            any(frame == "TIT2" and new == "Dream On" for frame, _old, new in item.tag_edits),
            msg=f"tag_edits={item.tag_edits!r}",
        )

        report = eng.apply_changes(self.root, preview, ["track one.mp3"])
        self.assertTrue(report.ok, msg=f"report={report!r}")
        self.assertEqual(report.applied, (("track one.mp3", "Test Artist - Dream On.mp3"),))

        moved = Path(self.root) / "Test Artist - Dream On.mp3"
        self.assertTrue(moved.is_file())
        self.assertFalse(os.path.exists(original_path))
        # The tag edit landed on the MOVED file.
        snap = eng.read_tag_snapshot(moved)
        self.assertEqual(snap.title, "Dream On")
        self.assertEqual(snap.artist, "Test Artist")
        # Full-file backup taken BEFORE mutation equals the original blob.
        backups_root = os.path.join(self.root, ".musicsyncrename", "backups", report.session_id)
        self.assertTrue(os.path.isdir(backups_root), msg="backup dir missing")
        backup_files = [f for f in os.listdir(backups_root) if not f.startswith(".")]
        self.assertEqual(len(backup_files), 1)
        with open(os.path.join(backups_root, backup_files[0]), "rb") as handle:
            self.assertEqual(handle.read(), original_bytes)

        # Undo: name AND bytes restored exactly; journal closed with 'undone'.
        undo = eng.undo_session(self.root, report.session_id)
        self.assertTrue(undo.ok, msg=f"undo={undo!r}")
        self.assertEqual(undo.restored, ("track one.mp3",))
        with open(original_path, "rb") as handle:
            self.assertEqual(handle.read(), original_bytes)
        self.assertFalse(moved.exists())

        session_file = os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl")
        event_kinds = [e["type"] for e in _read_events(session_file)]
        self.assertIn("undo_begin", event_kinds)
        self.assertTrue(event_kinds[-1] == "undone")

        # list_sessions reflects the terminal state.
        states = {s["session_id"]: s for s in eng.list_sessions(self.root)}
        self.assertEqual(states[report.session_id]["state"], "undone")

        # Repeated undo is a no-op that cannot damage restored files.
        snapshot_before_repeat = self.tree_bytes()
        repeat = eng.undo_session(self.root, report.session_id)
        self.assertTrue(repeat.ok, msg=f"repeat={repeat!r}")
        self.assertEqual(repeat.restored, ())
        self.assertEqual(repeat.anomalies, ())
        self.assertEqual(self.tree_bytes(), snapshot_before_repeat)

# ---------------------------------------------------------------------------
# B. Tags-only changes; chains, swaps and cycles through the verified planner
# ---------------------------------------------------------------------------


def _frame_text(frame):
    text = frame.text
    return text[0] if isinstance(text, (list, tuple)) else text


class TestTagsOnlyApply(ApplyUndoTestBase):
    def test_tags_only_edit_preserves_apic_replaygain_and_audio(self):
        eng = _engine()
        path = self.add_mp3("song.mp3")
        fixtures.add_basic_tags(path)  # TPE1/TIT2(junk)/TALB/RVRB/APIC PNG/2x TXXX RG
        pre_apply_blob = self.read_bytes(path)

        # Override to a CASE VARIANT of its own name: same normalized slot, so
        # the item carries tag edits but NO rename (tags-only content).
        preview = eng.build_preview(self.root, overrides=[Override("song.mp3", "Song")])
        item = {i.rel_path: i for i in preview.items}["song.mp3"]
        self.assertEqual(item.status, "ok")
        self.assertTrue(item.tag_edits)

        report = eng.apply_changes(self.root, preview, ["song.mp3"])
        self.assertTrue(report.ok, msg=f"report={report!r}")
        self.assertEqual(report.applied, (("song.mp3", None),))  # None == tags-only
        self.assertNotIn("Song.mp3", self.tree_bytes())  # no case rename happened

        tags_after, blob_after = _id3_frames(path)
        apic = fixtures.frame_frames(tags_after, "APIC:")
        self.assertEqual(len(apic), 1)
        self.assertEqual(apic[0].data, fixtures.make_png_1x1())  # artwork bytes intact
        self.assertTrue(fixtures.frame_frames(tags_after, "RVRB"))
        gain = {f.desc: _frame_text(f) for f in fixtures.frame_frames(tags_after, "TXXX:REPLAYGAIN")}
        self.assertEqual(gain.get("REPLAYGAIN_TRACK_GAIN"), "-8.2 dB")
        self.assertEqual(gain.get("REPLAYGAIN_ALBUM_PEAK"), "0.987654")
        snap = eng.read_tag_snapshot(path)
        self.assertEqual(snap.title, "Dream On")  # the tag edit itself landed
        self.assertTrue(
            fixtures.audio_part(blob_after) == fixtures.audio_part(pre_apply_blob),
            msg="audio region changed by a tags-only apply",
        )

        undo = eng.undo_session(self.root, report.session_id)
        self.assertTrue(undo.ok, msg=f"undo={undo!r}")
        self.assertEqual(undo.restored, ("song.mp3",))
        # Bytes restored EXACTLY from the pre-mutation backup (junk title back).
        self.assertEqual(self.read_bytes(path), pre_apply_blob)


class TestChainNestedDirectory(ApplyUndoTestBase):
    def test_chain_executes_dependency_first_and_undo_restores(self):
        eng = _engine()
        path_x = self.add_mp3("sub/x.mp3", frames=5)
        path_y = self.add_mp3("sub/y.mp3", frames=6)
        pre_map = {"sub/x.mp3": self.read_bytes(path_x), "sub/y.mp3": self.read_bytes(path_y)}

        # x takes y's slot; y moves to a FREE name -> dependency order: y first.
        preview = eng.build_preview(
            self.root, overrides=[Override("sub/x.mp3", "y"), Override("sub/y.mp3", "z clean")]
        )
        report = eng.apply_changes(self.root, preview, ["sub/x.mp3", "sub/y.mp3"])
        self.assertTrue(report.ok, msg=f"report={report!r}")
        self.assertEqual(
            sorted(r for r, _ in report.applied), ["sub/x.mp3", "sub/y.mp3"]  # sorted() yields a list
        )

        after = self.tree_bytes()
        self.assertEqual(after["sub/y.mp3"], pre_map["sub/x.mp3"])  # x landed on y's slot
        self.assertEqual(after["sub/z clean.mp3"], pre_map["sub/y.mp3"])
        self.assertNotIn("sub/x.mp3", after)

        events = _read_events(os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl"))
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds, ["header", "op", "done", "op", "done", "closed"])
        # Dependency-first ordering: y (the one freeing a slot) moved before x.
        self.assertEqual(events[1]["content"], "sub/y.mp3")
        self.assertEqual(events[3]["content"], "sub/x.mp3")

        undo = eng.undo_session(self.root, report.session_id)
        self.assertTrue(undo.ok, msg=f"undo={undo!r}")
        after_undo = self.tree_bytes()
        self.assertEqual(after_undo["sub/x.mp3"], pre_map["sub/x.mp3"])
        self.assertEqual(after_undo["sub/y.mp3"], pre_map["sub/y.mp3"])
        self.assertNotIn("sub/z clean.mp3", after_undo)


class TestSwapRootDirectory(ApplyUndoTestBase):
    def test_two_file_swap_uses_single_temp_step_and_undo_restores(self):
        eng = _engine()
        path_a = self.add_mp3("a.mp3", frames=4)
        path_b = self.add_mp3("b.mp3", frames=9)
        pre_map = {"a.mp3": self.read_bytes(path_a), "b.mp3": self.read_bytes(path_b)}

        preview = eng.build_preview(self.root, overrides=[Override("a.mp3", "b"), Override("b.mp3", "a")])
        report = eng.apply_changes(self.root, preview, ["a.mp3", "b.mp3"])
        self.assertTrue(report.ok, msg=f"report={report!r}")  # freed-by-batch targets succeed

        after = self.tree_bytes()
        self.assertEqual(after["a.mp3"], pre_map["b.mp3"])
        self.assertEqual(after["b.mp3"], pre_map["a.mp3"])

        events = _read_events(os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl"))
        op_events = [e for e in events if e["type"] == "op"]
        done_events = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(op_events), 3)  # temp break + two final renames
        self.assertEqual(len(done_events), 3)
        temps = [e for e in op_events if e["kind"] == "temp"]
        self.assertEqual(len(temps), 1)  # exactly ONE cycle-break temp step
        self.assertIn(".tmp-musicsync-rename-", temps[0]["to"])
        self.assertEqual(temps[0]["content"], "a.mp3")  # deterministic: lexicographic min
        self.assertEqual([e["type"] for e in events], ["header", "op", "done", "op", "done", "op", "done", "closed"])

        undo = eng.undo_session(self.root, report.session_id)
        self.assertTrue(undo.ok, msg=f"undo={undo!r}")  # undo of a swap is itself a cycle
        after_undo = self.tree_bytes()
        self.assertEqual(after_undo["a.mp3"], pre_map["a.mp3"])
        self.assertEqual(after_undo["b.mp3"], pre_map["b.mp3"])


class TestThreeCycleNestedDirectory(ApplyUndoTestBase):
    def test_three_cycle_applies_and_undo_restores_exactly(self):
        eng = _engine()
        path_p = self.add_mp3("sub/p.mp3", frames=10)
        path_q = self.add_mp3("sub/q.mp3", frames=11)
        path_r = self.add_mp3("sub/r.mp3", frames=12)
        pre_map = {
            "sub/p.mp3": self.read_bytes(path_p),
            "sub/q.mp3": self.read_bytes(path_q),
            "sub/r.mp3": self.read_bytes(path_r),
        }

        preview = eng.build_preview(
            self.root,
            overrides=[Override("sub/p.mp3", "q"), Override("sub/q.mp3", "r"), Override("sub/r.mp3", "p")],
        )
        report = eng.apply_changes(self.root, preview, ["sub/p.mp3", "sub/q.mp3", "sub/r.mp3"])
        self.assertTrue(report.ok, msg=f"report={report!r}")

        after = self.tree_bytes()
        self.assertEqual(after["sub/p.mp3"], pre_map["sub/r.mp3"])
        self.assertEqual(after["sub/q.mp3"], pre_map["sub/p.mp3"])
        self.assertEqual(after["sub/r.mp3"], pre_map["sub/q.mp3"])

        events = _read_events(os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl"))
        # Only count OP events: the matching done record also carries kind="temp".
        temps = [e for e in events if e["type"] == "op" and e.get("kind") == "temp"]
        self.assertEqual(len(temps), 1)
        self.assertEqual(temps[0]["content"], "sub/p.mp3")

        undo = eng.undo_session(self.root, report.session_id)
        self.assertTrue(undo.ok, msg=f"undo={undo!r}")
        after_undo = self.tree_bytes()
        for rel in pre_map:
            self.assertEqual(after_undo[rel], pre_map[rel])


# ---------------------------------------------------------------------------
# C(A). Rejection and validation matrix
# ---------------------------------------------------------------------------


class TestRejectionBasics(ApplyUndoTestBase):
    def test_unapproved_rel_and_nothing_to_do_rejected(self):
        eng = _engine()
        path_a = self.add_mp3("a.mp3", frames=5)
        bytes_a = self.read_bytes(path_a)
        self.add_mp3("b.mp3", frames=6)  # untagged: case-variant override has nothing to do

        preview = eng.build_preview(
            self.root, overrides=[Override("a.mp3", "A2"), Override("b.mp3", "B")]
        )
        report = eng.apply_changes(self.root, preview, ["a.mp3", "ghost.mp3", "b.mp3"])
        # ghost is not in the preview; b's case-variant proposal needs no rename
        # and carries no tag edits -> nothing_to_do. a proceeds.
        self.assertEqual(
            sorted(report.rejected),
            [("b.mp3", "nothing_to_do"), ("ghost.mp3", "not_in_preview")],
        )
        self.assertFalse(report.ok)
        self.assertEqual(report.applied, (("a.mp3", "A2.mp3"),))
        self.assertEqual(report.partial, ())
        self.assertEqual(report.canceled, ())

        # a was applied; the rejected items were never touched.
        after = self.public_tree()
        self.assertEqual(after["A2.mp3"][0], bytes_a)
        self.assertIn("b.mp3", after)

    def test_ambiguous_and_error_items_all_rejected_create_no_session(self):
        eng = _engine()
        self.add_mp3("m1 - m2 - m3.mp3")  # two separators -> ambiguous, no proposal
        junk_path = self.write_raw("junk.mp3", b"definitely not an mp3\x00\xff" * 4)
        bytes_junk = self.read_bytes(junk_path)

        preview = eng.build_preview(self.root)
        items = {i.rel_path: i for i in preview.items}
        amb = items["m1 - m2 - m3.mp3"]
        err = items["junk.mp3"]
        self.assertEqual(amb.status, "ambiguous")
        self.assertIsNone(amb.proposed_name)  # ambiguous items carry NO proposal
        self.assertEqual(err.status, "error")

        report = eng.apply_changes(self.root, preview, ["m1 - m2 - m3.mp3", "junk.mp3"])
        self.assertFalse(report.ok)
        self.assertEqual(
            sorted(report.rejected),
            [
                ("junk.mp3", "status_error_not_applicable"),
                ("m1 - m2 - m3.mp3", "status_ambiguous_not_applicable"),
            ],
        )
        self.assertEqual(report.applied, ())
        # EVERYTHING rejected -> no journal session may be created at all.
        self.assertEqual(report.session_id, "")
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".musicsyncrename")))
        # Rejected items are untouched on disk.
        self.assertEqual(self.read_bytes(junk_path), bytes_junk)


class TestSourceSideRejection(ApplyUndoTestBase):
    """Sources that stop being what the preview saw: each gets a stable code."""

    def test_source_missing_rejected(self):
        eng = _engine()
        path = self.add_mp3("a.mp3", frames=5)
        bytes_a = self.read_bytes(path)
        preview = eng.build_preview(self.root, overrides=[Override("a.mp3", "A2")])
        os.remove(path)  # vanished between preview and apply
        report = eng.apply_changes(self.root, preview, ["a.mp3"])
        self.assertEqual(report.rejected, (("a.mp3", "source_missing"),))
        self.assertEqual(report.applied, ())
        self.assertEqual(report.session_id, "")  # all-rejected: no session
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".musicsyncrename")))

    def test_symlink_source_rejected(self):
        eng = _engine()
        path = self.add_mp3("a.mp3", frames=5)
        target = self.add_mp3("b.mp3", frames=6)  # symlink points at real content
        bytes_b = self.read_bytes(target)
        preview = eng.build_preview(self.root, overrides=[Override("a.mp3", "A2")])
        os.remove(path)
        os.symlink(os.path.join(self.root, "b.mp3"), path)  # source is now a link
        report = eng.apply_changes(self.root, preview, ["a.mp3"])
        self.assertEqual(report.rejected, (("a.mp3", "is_symlink"),))
        self.assertEqual(report.applied, ())
        self.assertEqual(report.session_id, "")
        # Symlinks are never followed: the target file is intact.
        self.assertTrue(os.path.islink(path))
        self.assertEqual(self.read_bytes(target), bytes_b)

    def test_fifo_source_rejected_not_regular_file(self):
        eng = _engine()
        path = self.add_mp3("a.mp3", frames=5)
        preview = eng.build_preview(self.root, overrides=[Override("a.mp3", "A2")])
        os.remove(path)
        os.mkfifo(path)  # a FIFO is not a regular file
        report = eng.apply_changes(self.root, preview, ["a.mp3"])
        self.assertEqual(report.rejected, (("a.mp3", "not_regular_file"),))
        self.assertEqual(report.applied, ())
        self.assertEqual(report.session_id, "")
        import stat as stat_mod

        self.assertTrue(stat_mod.S_ISFIFO(os.lstat(path).st_mode))  # still a FIFO, untouched

    def test_parent_missing_rejected(self):
        eng = _engine()
        path = self.add_mp3("sub/p.mp3", frames=5)
        preview = eng.build_preview(self.root, overrides=[Override("sub/p.mp3", "P2")])
        shutil.rmtree(os.path.join(self.root, "sub"))  # whole parent dir gone
        report = eng.apply_changes(self.root, preview, ["sub/p.mp3"])
        self.assertEqual(report.rejected, (("sub/p.mp3", "parent_missing"),))
        self.assertEqual(report.applied, ())
        self.assertEqual(report.session_id, "")


class TestChangedSincePreview(ApplyUndoTestBase):
    def test_changed_item_rejected_while_independent_item_applies(self):
        eng = _engine()
        path_a = self.add_mp3("a.mp3", frames=5)
        path_b = self.add_mp3("b.mp3", frames=6)
        bytes_b = self.read_bytes(path_b)

        preview = eng.build_preview(
            self.root, overrides=[Override("a.mp3", "A2"), Override("b.mp3", "B2")]
        )
        # Mutate a AFTER the snapshot: size (and mtime) no longer match.
        with open(path_a, "ab") as handle:
            handle.write(b"\x00" * 128)
        bytes_a_mutated = self.read_bytes(path_a)

        report = eng.apply_changes(self.root, preview, ["a.mp3", "b.mp3"])
        # The changed item is rejected... (exact rejection set: only a).
        self.assertEqual(report.rejected, (("a.mp3", "changed_since_preview"),))
        self.assertFalse(report.ok)  # ...but the unrelated approved item STILL succeeds.
        self.assertEqual(report.applied, (("b.mp3", "B2.mp3"),))
        self.assertEqual(report.partial, ())
        self.assertEqual(report.canceled, ()  )
        self.assertTrue(report.session_id)

        after = self.public_tree()
        # a is untouched (still holds its mutated bytes); b moved with exact bytes.
        self.assertEqual(after["a.mp3"][0], bytes_a_mutated)
        self.assertEqual(after["B2.mp3"][0], bytes_b)
        self.assertNotIn("A2.mp3", after)

        # Journal records exactly one completed op/done pair (b's rename).
        events = _read_events(os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl"))
        self.assertEqual([e["type"] for e in events], ["header", "op", "done", "closed"])


class TestCollisionProtection(ApplyUndoTestBase):
    def test_case_insensitive_live_occupant_rejected(self):
        eng = _engine()
        self.add_mp3("a.mp3", frames=5)
        path_b = self.add_mp3("B.mp3", frames=6)  # live occupant, case variant of target
        bytes_b = self.read_bytes(path_b)

        preview = eng.build_preview(self.root, overrides=[Override("a.mp3", "b")])
        report = eng.apply_changes(self.root, preview, ["a.mp3"])
        self.assertEqual(report.rejected, (("a.mp3", "target_exists"),))
        self.assertEqual(report.applied, ())
        self.assertEqual(report.session_id, "")  # all-rejected: no session
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".musicsyncrename")))
        after = self.public_tree()
        self.assertIn("a.mp3", after)  # never touched
        self.assertEqual(after["B.mp3"][0], bytes_b)

    def test_unicode_nfd_nfc_live_occupant_rejected(self):
        eng = _engine()
        nfc_e, nfd_e = "\u00e9", "e\u0301"  # é precomposed vs decomposed
        self.add_mp3("a.mp3", frames=5)
        live_nfd = f"Cafe{nfd_e}.mp3"
        path_live = self.add_mp3(live_nfd, frames=6)
        bytes_live = self.read_bytes(path_live)

        preview = eng.build_preview(self.root, overrides=[Override("a.mp3", f"Cafe{nfc_e}")])
        report = eng.apply_changes(self.root, preview, ["a.mp3"])
        # name_key is NFKC+casefold: the NFC proposal collides with the NFD live file.
        self.assertEqual(report.rejected, (("a.mp3", "target_exists"),))
        self.assertEqual(report.applied, ())
        self.assertEqual(report.session_id, "")
        after = self.public_tree()
        self.assertIn("a.mp3", after)
        self.assertEqual(after[live_nfd][0], bytes_live)  # NFD file untouched

    def test_duplicate_proposed_targets_both_rejected(self):
        eng = _engine()
        path_x = self.add_mp3("x.mp3", frames=5)
        path_y = self.add_mp3("y.mp3", frames=6)
        bytes_x, bytes_y = self.read_bytes(path_x), self.read_bytes(path_y)

        # Two items, one normalized target (case variants) -> BOTH rejected.
        preview = eng.build_preview(
            self.root, overrides=[Override("x.mp3", "dup"), Override("y.mp3", "Dup")]
        )
        report = eng.apply_changes(self.root, preview, ["x.mp3", "y.mp3"])
        self.assertEqual(
            sorted(report.rejected),
            [("x.mp3", "proposal_collision"), ("y.mp3", "proposal_collision")],
        )
        self.assertEqual(report.applied, ())
        self.assertEqual(report.session_id, "")  # all-rejected: no session
        after = self.public_tree()
        self.assertEqual(after["x.mp3"][0], bytes_x)
        self.assertEqual(after["y.mp3"][0], bytes_y)


# ---------------------------------------------------------------------------
# C(B). Failure and cancellation at mutation time
# ---------------------------------------------------------------------------


class TestCancellationMidBatch(ApplyUndoTestBase):
    """cancel_check flips after the first step: exact partition + undo recovery."""

    def test_cancel_after_first_step_partitions_and_undoes_exactly(self):
        eng = _engine()
        path_a = self.add_mp3("a.mp3", frames=4)
        path_b = self.add_mp3("b.mp3", frames=9)
        path_c = self.add_mp3("c.mp3", frames=7)
        pre_map = {"a.mp3": self.read_bytes(path_a), "b.mp3": self.read_bytes(path_b)}
        bytes_c = self.read_bytes(path_c)

        # Batch plan order: c->d (free target) first, then the a<->b cycle via temp.
        preview = eng.build_preview(
            self.root,
            overrides=[Override("a.mp3", "b"), Override("b.mp3", "a"), Override("c.mp3", "d")],
        )

        checks = {"n": 0}

        def cancel_check():
            checks["n"] += 1
            return checks["n"] >= 2  # allow step 1, refuse before step 2's op is written

        report = eng.apply_changes(self.root, preview, ["a.mp3", "b.mp3", "c.mp3"], cancel_check=cancel_check)
        self.assertFalse(report.ok)
        # Exact partition: c fully applied; a and b NEVER STARTED (their ops were
        # not even journaled) -> canceled, not partial.
        self.assertEqual(sorted(r for r, _ in report.applied), ["c.mp3"])
        self.assertEqual(report.applied[0][1], "d.mp3")
        self.assertEqual(report.partial, ())
        self.assertEqual(tuple(sorted(report.canceled)), ("a.mp3", "b.mp3"))
        self.assertTrue(report.session_id)

        # Journal evidence matches ONLY the operation that genuinely completed.
        events = _read_events(os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl"))
        self.assertEqual([e["type"] for e in events], ["header", "op", "done", "aborted"])
        self.assertEqual(events[-1]["reason"], "canceled")
        op_events = [e for e in events if e["type"] == "op"]
        self.assertEqual(len(op_events), 1)
        self.assertEqual((op_events[0]["content"], op_events[0]["kind"]), ("c.mp3", "rename"))

        # Live FS: only c moved; a and b untouched at their original names/bytes.
        after = self.public_tree()
        self.assertEqual(after["d.mp3"][0], bytes_c)
        self.assertEqual(after["a.mp3"][0], pre_map["a.mp3"])
        self.assertEqual(after["b.mp3"][0], pre_map["b.mp3"])

        # Undo of the aborted session restores c exactly; a and b were never moved.
        undo = eng.undo_session(self.root, report.session_id)
        self.assertTrue(undo.ok, msg=f"undo={undo!r}")
        self.assertEqual(undo.restored, ("c.mp3",))
        after_undo = self.public_tree()
        self.assertEqual(
            {k: v[0] for k, v in after_undo.items()},
            {**pre_map, "c.mp3": bytes_c},  # pre_map already holds raw bytes
        )

        # Repeated undo on the recovered session is a safe no-op.
        repeat = eng.undo_session(self.root, report.session_id)
        self.assertTrue(repeat.ok)
        self.assertEqual((repeat.restored, repeat.anomalies), ((), ()))
        self.assertEqual(self.public_tree()["c.mp3"][0], bytes_c)


class TestInjectedRenameFailure(ApplyUndoTestBase):
    """A real os.rename failure at step 3: partial reporting + full undo recovery."""

    def test_third_rename_fails_partial_reported_and_undo_recovers_exactly(self):
        import unittest.mock as mock

        eng = _engine()
        path_a = self.add_mp3("a.mp3", frames=4)
        path_b = self.add_mp3("b.mp3", frames=9)
        path_c = self.add_mp3("c.mp3", frames=7)
        pre_map = {"a.mp3": self.read_bytes(path_a), "b.mp3": self.read_bytes(path_b)}
        bytes_c = self.read_bytes(path_c)

        preview = eng.build_preview(
            self.root,
            overrides=[Override("a.mp3", "b"), Override("b.mp3", "a"), Override("c.mp3", "d")],
        )

        real_rename = os.rename
        calls = {"n": 0}

        def flaky(src, dst):
            # Let c->d and a->tmp succeed; fail on b's rename (the third call).
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("injected rename fault")
            return real_rename(src, dst)

        with mock.patch.object(os, "rename", flaky):
            report = eng.apply_changes(self.root, preview, ["a.mp3", "b.mp3", "c.mp3"])
        self.assertFalse(report.ok)
        # c completed; a (temp step done, final rename never journaled) and b
        # (op journaled, rename failed) both STARTED but did not finish -> partial.
        self.assertEqual(report.applied, (("c.mp3", "d.mp3"),))
        self.assertEqual(
            sorted(report.partial), [("a.mp3", "rename_failed"), ("b.mp3", "rename_failed")]
        )
        self.assertEqual(tuple(sorted(report.canceled)), ())  # every approved item was started
        self.assertTrue(report.session_id)

        # Journal evidence: exactly two completed op/done pairs, then b's op with NO done.
        events = _read_events(os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl"))
        self.assertEqual(
            [e["type"] for e in events],
            ["header", "op", "done", "op", "done", "op", "aborted"],
        )
        done_contents = [e["content"] for e in events if e["type"] == "done"]
        self.assertEqual(done_contents, ["c.mp3", "a.mp3"])
        last_op = events[-2]
        self.assertEqual((last_op["content"], last_op["kind"], last_op["from"], last_op["to"]), (
            "b.mp3",
            "rename",
            "b.mp3",
            "a.mp3",
        ))
        aborted_reason = events[-1]["reason"]
        self.assertTrue(aborted_reason.startswith("rename_failed:"))

        # Mid-failure FS state: c at d; a parked in the temp slot; b still original.
        after = self.public_tree()
        self.assertEqual(after["d.mp3"][0], bytes_c)
        tmp_files = [k for k in after if ".tmp-musicsync-rename-" in k]
        self.assertEqual(len(tmp_files), 1)  # exactly one cycle-break temp file
        self.assertEqual(after[tmp_files[0]][0], pre_map["a.mp3"])
        self.assertEqual(after["b.mp3"][0], pre_map["b.mp3"])  # failed rename left it in place
        self.assertNotIn("a.mp3", after)

        # Undo recovers the interrupted state: names AND bytes back to pre-apply.
        undo = eng.undo_session(self.root, report.session_id)
        self.assertTrue(undo.ok, msg=f"undo={undo!r}")
        self.assertEqual(undo.restored, ("a.mp3", "b.mp3", "c.mp3"))
        after_undo = {k: v[0] for k, v in self.public_tree().items()}
        expected = {**pre_map, "c.mp3": bytes_c}
        self.assertEqual(after_undo, expected)  # NO leftover temp file

        undo_events = [e["type"] for e in _read_events(
            os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl")
        )]
        self.assertEqual(undo_events[-1], "undone")
        self.assertIn("undo_begin", undo_events)


# ---------------------------------------------------------------------------
# C(C). Interrupted-session recovery (hand-crafted crash journals)
# ---------------------------------------------------------------------------


class TestInterruptedRecovery(ApplyUndoTestBase):
    def test_completed_op_missing_done_converges_via_live_probe(self):
        """Crash AFTER the rename landed but BEFORE its done event was written."""
        import uuid as _uuid

        eng = _engine()
        sid = _uuid.uuid4().hex
        # Live state: the file is already at its destination (rename happened on
        # disk); the journal has only header+op, no done.
        path_c = self.add_mp3("c.mp3", frames=5)
        bytes_x = self.read_bytes(path_c)
        self.craft_journal(
            sid,
            [
                {"type": "header", "id": sid, "root": os.path.abspath(self.root),
                 "started": "2026-10-15T00:00:00Z"},
                {"type": "op", "content": "b.mp3", "from": "b.mp3",
                 "to": "c.mp3", "kind": "rename"},
            ],
        )

        # Introspection sees an OPEN session with one op and zero done events.
        sess = {s["session_id"]: s for s in eng.list_sessions(self.root)}[sid]
        self.assertEqual(sess["state"], "open")
        self.assertEqual((sess["ops"], sess["done_ops"]), (1, 0))

        undo = eng.undo_session(self.root, sid)
        self.assertTrue(undo.ok, msg=f"undo={undo!r}")  # live probe: file at 'to' -> moved
        self.assertEqual(undo.restored, ("b.mp3",))

        after = self.public_tree()
        self.assertEqual(after["b.mp3"][0], bytes_x)  # name AND bytes back exactly
        self.assertNotIn("c.mp3", after)

        events = _read_events(os.path.join(_sessions_dir(self.root), sid + ".jsonl"))
        self.assertEqual(
            [e["type"] for e in events],
            ["header", "op", "undo_begin", "undo_op", "undo_done", "undone"],
        )
        # Counts now include the undo-phase events (the missing done was not imputed).
        sess2 = {s["session_id"]: s for s in eng.list_sessions(self.root)}[sid]
        self.assertEqual(sess2["state"], "undone")
        self.assertEqual((sess2["ops"], sess2["done_ops"]), (2, 1))

    def test_header_only_crash_journal_closes_as_noop_undo(self):
        """Crash before the first op: nothing displaced; undo must be a safe no-op."""
        import uuid as _uuid

        eng = _engine()
        sid = _uuid.uuid4().hex
        self.add_mp3("a.mp3", frames=4)  # an untouched bystander file
        bytes_a = self.read_bytes(os.path.join(self.root, "a.mp3"))
        self.craft_journal(
            sid,
            [{"type": "header", "id": sid, "root": os.path.abspath(self.root),
              "started": "2026-10-15T00:00:00Z"}],
        )

        sess = {s["session_id"]: s for s in eng.list_sessions(self.root)}[sid]
        self.assertEqual(sess["state"], "open")
        self.assertEqual((sess["ops"], sess["done_ops"]), (0, 0))

        pre = self.public_tree()
        undo = eng.undo_session(self.root, sid)
        self.assertTrue(undo.ok, msg=f"undo={undo!r}")
        self.assertEqual((undo.restored, undo.anomalies), ((), ()))
        # Zero mutations: tree identical byte-for-byte.
        self.assertEqual(self.public_tree(), pre)
        self.assertEqual(
            self.read_bytes(os.path.join(self.root, "a.mp3")), bytes_a
        )
        # Journal closed with the terminal 'undone' event (recovery path verified).
        events = _read_events(os.path.join(_sessions_dir(self.root), sid + ".jsonl"))
        self.assertEqual([e["type"] for e in events], ["header", "undone"])

        # Repeated undo on an already-undone session stays a no-op.
        repeat = eng.undo_session(self.root, sid)
        self.assertTrue(repeat.ok)
        self.assertEqual((repeat.restored, repeat.anomalies), ((), ()))
        self.assertEqual(self.public_tree(), pre)


class TestUndoValidationFailure(ApplyUndoTestBase):
    """A failed validation phase must make ZERO additional mutations."""

    def test_target_occupied_zero_mutations_then_retry_recovers(self):
        eng = _engine()
        path_b = self.add_mp3("b.mp3", frames=5)
        bytes_x = self.read_bytes(path_b)  # the ORIGINAL content's bytes
        report = eng.apply_changes(
            self.root, eng.build_preview(self.root, overrides=[Override("b.mp3", "c")]), ["b.mp3"]
        )
        self.assertTrue(report.ok)

        # An UNRELATED file now occupies the original slot.
        occupant = self.add_mp3("b.mp3", frames=7)
        bytes_occupant = self.read_bytes(occupant)
        journal_path = os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl")
        journal_before = self.read_bytes(journal_path)

        attempt1 = eng.undo_session(self.root, report.session_id)
        self.assertFalse(attempt1.ok)
        self.assertEqual(attempt1.anomalies, (("b.mp3", "target_occupied"),))
        self.assertEqual(attempt1.restored, ())
        # ZERO mutations: every library file byte-identical...
        after_fail = self.public_tree()
        self.assertEqual(after_fail["c.mp3"][0], bytes_x)
        self.assertEqual(after_fail["b.mp3"][0], bytes_occupant)
        self.assertEqual(set(after_fail), {"b.mp3", "c.mp3"})
        # ...and the journal gained NO events (validation precedes every write).
        self.assertEqual(self.read_bytes(journal_path), journal_before)

        # Operator removes the occupant; retrying undo resumes and completes.
        os.remove(occupant)
        attempt2 = eng.undo_session(self.root, report.session_id)
        self.assertTrue(attempt2.ok, msg=f"retry={attempt2!r}")
        self.assertEqual(attempt2.restored, ("b.mp3",))
        after_retry = self.public_tree()
        self.assertEqual(after_retry["b.mp3"][0], bytes_x)  # original content's bytes
        self.assertNotIn("c.mp3", after_retry)

    def test_current_missing_zero_mutations_and_journal_unchanged(self):
        eng = _engine()
        path_b = self.add_mp3("b.mp3", frames=5)
        report = eng.apply_changes(
            self.root, eng.build_preview(self.root, overrides=[Override("b.mp3", "c")]), ["b.mp3"]
        )
        self.assertTrue(report.ok)

        # The displaced file itself is deleted (e.g. user cleanup mid-incident).
        os.remove(os.path.join(self.root, "c.mp3"))
        pre = self.public_tree()
        journal_path = os.path.join(_sessions_dir(self.root), report.session_id + ".jsonl")
        journal_before = self.read_bytes(journal_path)

        attempt = eng.undo_session(self.root, report.session_id)
        self.assertFalse(attempt.ok)
        self.assertEqual(attempt.anomalies, (("b.mp3", "current_missing"),))
        self.assertEqual(attempt.restored, ())
        # Zero mutations: tree and journal both untouched.
        self.assertEqual(self.public_tree(), pre)
        self.assertEqual(self.read_bytes(journal_path), journal_before)


# ---------------------------------------------------------------------------
# C(D). Session introspection and the apply concurrency guard
# ---------------------------------------------------------------------------


class TestListSessions(ApplyUndoTestBase):
    def test_states_and_operation_counts(self):
        import uuid as _uuid

        eng = _engine()
        # 1) A real, fully closed session (single rename).
        self.add_mp3("s1.mp3", frames=5)
        rep_closed = eng.apply_changes(
            self.root,
            eng.build_preview(self.root, overrides=[Override("s1.mp3", "S2")]),
            ["s1.mp3"],
        )
        self.assertTrue(rep_closed.ok)

        # 2) A real aborted session: cancel before the second of two steps.
        self.add_mp3("t1.mp3", frames=6)
        self.add_mp3("t2.mp3", frames=7)

        checks = {"n": 0}

        def cancel_check():
            checks["n"] += 1
            return checks["n"] >= 2

        rep_aborted = eng.apply_changes(
            self.root,
            eng.build_preview(
                self.root,
                overrides=[Override("t1.mp3", "T2"), Override("t2.mp3", "U2")],
            ),
            ["t1.mp3", "t2.mp3"],
            cancel_check=cancel_check,
        )
        self.assertFalse(rep_aborted.ok)

        # 3) A hand-crafted crash journal (header only -> open).
        sid_open = _uuid.uuid4().hex
        self.craft_journal(
            sid_open,
            [{"type": "header", "id": sid_open, "root": os.path.abspath(self.root),
              "started": "2026-10-15T00:00:00Z"}],
        )

        # 4) A corrupt journal (unreadable lines).
        sid_corrupt = _uuid.uuid4().hex
        sessions = _sessions_dir(self.root)
        with open(os.path.join(sessions, sid_corrupt + ".jsonl"), "w") as handle:
            handle.write("{this is not json\n")

        by_id = {s["session_id"]: s for s in eng.list_sessions(self.root)}

        closed = by_id[rep_closed.session_id]
        self.assertEqual(closed["state"], "closed")
        self.assertEqual((closed["ops"], closed["done_ops"]), (1, 1))
        # Header fields are read back.
        self.assertEqual(closed["root"], os.path.abspath(self.root))
        self.assertTrue(str(closed["started"]).endswith("Z"))

        aborted = by_id[rep_aborted.session_id]
        self.assertEqual(aborted["state"], "aborted")
        self.assertEqual((aborted["ops"], aborted["done_ops"]), (1, 1))

        open_sess = by_id[sid_open]
        self.assertEqual(open_sess["state"], "open")
        self.assertEqual((open_sess["ops"], open_sess["done_ops"]), (0, 0))

        corrupt = by_id[sid_corrupt]
        self.assertIs(corrupt.get("corrupt"), True)
        self.assertNotIn("state", corrupt)  # unparseable: no state can be claimed
        self.assertEqual(len(by_id), 4)


class TestConcurrencyGuard(ApplyUndoTestBase):
    def test_unresolved_sessions_block_apply_until_resolved(self):
        import uuid as _uuid

        eng = _engine()
        self.add_mp3("a.mp3", frames=5)
        self.add_mp3("b.mp3", frames=6)
        preview1 = eng.build_preview(
            self.root, overrides=[Override("a.mp3", "A2"), Override("b.mp3", "B2")]
        )

        # Create an ABORTED session by cancelling mid-batch.
        checks = {"n": 0}

        def cancel_check():
            checks["n"] += 1
            return checks["n"] >= 2

        rep_aborted = eng.apply_changes(
            self.root, preview1, ["a.mp3", "b.mp3"], cancel_check=cancel_check
        )
        self.assertFalse(rep_aborted.ok)  # a applied, b canceled -> session stays aborted

        # A new apply must be refused while that session is unresolved.
        preview2 = eng.build_preview(self.root, overrides=[Override("b.mp3", "B2")])
        with self.assertRaises(eng.EngineError) as ctx:
            eng.apply_changes(self.root, preview2, ["b.mp3"])
        self.assertIn("unresolved", str(ctx.exception))

        # An OPEN (crash) session also blocks; so does a corrupt one.
        sid_open = _uuid.uuid4().hex
        self.craft_journal(
            sid_open,
            [{"type": "header", "id": sid_open, "root": os.path.abspath(self.root),
              "started": "2026-10-15T00:00:00Z"}],
        )
        with self.assertRaises(eng.EngineError):
            eng.apply_changes(self.root, preview2, ["b.mp3"])

        # Documented recovery path for each unresolved state:
        # open/crash session -> no-op undo closes it.
        u_open = eng.undo_session(self.root, sid_open)
        self.assertTrue(u_open.ok and (u_open.restored, u_open.anomalies) == ((), ()))
        # aborted session -> real undo restores the applied part.
        u_aborted = eng.undo_session(self.root, rep_aborted.session_id)
        self.assertTrue(u_aborted.ok, msg=f"undo={u_aborted!r}")
        self.assertEqual(u_aborted.restored, ("a.mp3",))  # b was never moved
        tree_back = {k: v[0] for k, v in self.public_tree().items() if isinstance(v[0], bytes)}
        self.assertIn("a.mp3", tree_back)  # library back to its pre-session names

        # A corrupt journal still blocks...
        sid_corrupt = _uuid.uuid4().hex
        sessions = _sessions_dir(self.root)
        corrupt_path = os.path.join(sessions, sid_corrupt + ".jsonl")
        with open(corrupt_path, "w") as handle:
            handle.write("{not json\n")
        with self.assertRaises(eng.EngineError) as ctx2:
            eng.apply_changes(self.root, preview2, ["b.mp3"])
        # ...until the operator removes/repairs it (it cannot be machine-undone).
        os.remove(corrupt_path)

        # Guard released: a fresh preview now applies cleanly.
        preview3 = eng.build_preview(
            self.root, overrides=[Override("a.mp3", "A2"), Override("b.mp3", "B2")]
        )
        final = eng.apply_changes(self.root, preview3, ["a.mp3", "b.mp3"])
        self.assertTrue(final.ok, msg=f"final={final!r}")

        by_id = {s["session_id"]: s for s in eng.list_sessions(self.root)}
        states = {sid: entry.get("state") for sid, entry in by_id.items()}
        self.assertEqual(states[rep_aborted.session_id], "undone")  # undo events counted
        self.assertEqual(states[sid_open], "undone")
        self.assertEqual(states[final.session_id], "closed")
        self.assertNotIn(sid_corrupt, by_id)  # operator removed it
        aborted_final = by_id[rep_aborted.session_id]
        self.assertEqual((aborted_final["ops"], aborted_final["done_ops"]), (2, 2))


if __name__ == "__main__":
    unittest.main()
