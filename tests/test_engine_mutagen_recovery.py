"""Focused regression: MutagenError recovery in the vendored journaled engine.

Mission 18 — a real mid-item ID3 tag-write failure raises mutagen's
``MutagenError`` (mutagen wraps the low-level write error; Mission 17A
demonstrated exactly this escape on this host with an unwritable fixture
file). Before the fix, ``engine.apply_changes``'s step handler caught only
``(OSError, ParseError, ValueError)``. The vendored tags module's own
``ParseError`` is a plain Exception and mutagen's ``MutagenError`` has MRO
``[MutagenError, Exception]`` — neither relates to OSError — so the exception
escaped apply_changes entirely: RenameWorker surfaced a generic "internal
error" payload and the session journal was left OPEN with no aborted event.

These tests drive the REAL ``apply_changes`` execution path (real journal
header/op/done events with fsync, real pre-mutation backup, real rename step)
on disposable synthetic MP3s, injecting a deterministic MutagenError from the
tag-writing operation — the exact call (``engine.apply_tag_edits``) that mutagen's
own save() raises out of. They then verify recovery through the EXISTING
undo_session() path: bytes, filename and mtime restored exactly.

Honest scope: an injected exception proves this specific failure class is
classified as partial, journaled aborted and undoable. It does NOT prove that
every possible filesystem failure mid-mutation is recoverable.

Fixture design is identical to the F1 entry of tests/test_bulk_rename.py
``build_library`` (8 silent 417-byte MPEG frames + TPE1/TIT2/TALB/ReplayGain
TXXX tags; 'untagged junk' title triggers rename + TIT2 cleanup edit), so the
preview shape is proven-identical to the established suite. No Qt here: pure
engine, no GUI state, fast.
"""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')

from musicsync.vendored import engine  # noqa: E402
from mutagen import MutagenError  # noqa: E402
from musicsync.vendored.tags import read_tag_snapshot  # noqa: E402

JOURNAL_DIRNAME = '.musicsyncrename'
REL = 'song_junk.mp3'                      # F1-pattern fixture name (disposable)
PROPOSED = 'Junk Artist - Dream On.mp3'    # expected proposal, same as established F1
INJECTED_MESSAGE = 'injected deterministic mid-write failure'


def _mpeg_frame() -> bytes:
    return b'\xff\xfb\x90\xc0' + b'\x00' * 413


def _build_mp3(path: Path):
    with open(str(path), 'wb') as handle:
        for _ in range(8):
            handle.write(_mpeg_frame())


def _set_tags(path: Path):
    """F1 tag set: junk-group title + artist + decoys that must survive."""
    from mutagen.id3 import TALB, TIT2, TPE1, TXXX
    from mutagen.mp3 import MP3

    audio = MP3(str(path))
    audio.add_tags()
    tags = audio.tags
    tags.add(TPE1(encoding=3, text=['Junk Artist']))
    tags.add(TIT2(encoding=3, text=['Dream On (Official HD Video)']))
    tags.add(TALB(encoding=3, text=['Toys in the Attic']))
    tags.add(TXXX(encoding=3, desc='REPLAYGAIN_TRACK_GAIN', text=['-8.2 dB']))
    audio.save()


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class EngineMutagenErrorRecoveryTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='musicsync-m18-')
        self.root = Path(self._tmp.name)  # exists from TemporaryDirectory()
        _build_mp3(self.root / REL)
        _set_tags(self.root / REL)

        # Pre-snapshot: exact bytes, sha256 and mtime_ns are the undo contract.
        self.pre_bytes = (self.root / REL).read_bytes()
        self.pre_sha = hashlib.sha256(self.pre_bytes).hexdigest()
        self.pre_mtime_ns = os.lstat(str(self.root / REL)).st_mtime_ns

        # Guard fixture validity up front: proven-identical shape to F1.
        self.preview = engine.build_preview(str(self.root))
        item = next(i for i in self.preview.items if i.rel_path == REL)
        self.assertEqual(item.status, 'ok')
        self.assertEqual(item.proposed_name, PROPOSED)
        self.assertEqual(
            item.tag_edits, (('TIT2', 'Dream On (Official HD Video)', 'Dream On'),),
        )

    def tearDown(self):
        self._tmp.cleanup()

    # ------------------------------------------------------------------ helpers

    def _session_file(self, session_id: str) -> Path:
        return (
            self.root / JOURNAL_DIRNAME / 'sessions' / f'{session_id}.jsonl'
        )

    def _events(self, session_id: str):
        with open(str(self._session_file(session_id)), 'r', encoding='utf-8') as h:
            return [json.loads(line) for line in h if line.strip()]

    def _sessions_by_state(self, state: str):
        out = []
        for sess in engine.list_sessions(str(self.root)):
            if sess.get('state') == state:
                out.append(sess)
        return out

    # ------------------------------------------------------------------ tests

    def test_injected_mutagen_error_is_partial_journaled_aborted_and_undoable(self):
        """A MutagenError from the tag-write op must be handled, classified and
        journaled — not escape as an unexpected worker failure."""
        injected = MutagenError(INJECTED_MESSAGE)
        with mock.patch.object(
            engine, 'apply_tag_edits', side_effect=injected
        ) as stub:
            report = engine.apply_changes(str(self.root), self.preview, [REL])

        # The tag-write operation was actually reached on the real path.
        self.assertEqual(stub.call_count, 1)

        # (a) Handled: apply_changes RETURNS an ApplyReport; nothing escaped.
        self.assertIsInstance(report, engine.ApplyReport)
        self.assertTrue(len(report.session_id) == 32 and report.session_id.isalnum())
        self.assertFalse(report.ok)

        # (b) Classified: the started-but-unfinished item is in partial with the
        #     exact abort-code shape apply_changes records for a mid-tag-write
        #     failure ('tag_edit_failed').
        self.assertEqual(report.partial, ((REL, 'tag_edit_failed'),))
        self.assertEqual(report.applied, ())
        self.assertEqual(report.rejected, ())
        self.assertEqual(report.canceled, ())

        # (c) Live disk state at abort: rename step completed before the tag
        #     step; the injected failure raised before any byte was written.
        new_path = self.root / PROPOSED
        old_path = self.root / REL
        self.assertTrue(new_path.is_file(), 'renamed slot missing after apply')
        self.assertFalse(old_path.exists(), 'original name still present')
        self.assertEqual(_sha256(new_path), self.pre_sha,
                         'tag step must not have altered bytes before failing')

        # (d) Journal: the aborted event IS recorded while journal writing is
        #     functional — header/op/done sequence plus terminal aborted.
        sid = report.session_id
        events = self._events(sid)
        types_kinds = [(e['type'], e.get('kind')) for e in events]
        self.assertEqual(
            types_kinds,
            [('header', None), ('op', 'rename'), ('done', 'rename'),
             ('op', 'tag_edit'), ('aborted', None)],
        )
        aborted = events[-1]
        self.assertTrue(aborted['reason'].startswith('tag_edit_failed:'))
        self.assertIn(INJECTED_MESSAGE, aborted['reason'])
        # The tag op was journaled against the renamed (final) slot.
        tag_op = [e for e in events if e.get('kind') == 'tag_edit'][0]
        self.assertEqual(tag_op['from'], PROPOSED)
        self.assertEqual(tag_op['to'], PROPOSED)

        # Pre-mutation backup exists and is byte-exact (undo's data source).
        backups = [f for f in (self.root / JOURNAL_DIRNAME / 'backups').rglob('*')
                   if f.is_file()]
        self.assertEqual(len(backups), 1, 'exactly one backup expected')
        self.assertEqual(_sha256(backups[0]), self.pre_sha)

        # (e) Session remains inspectable: list_sessions shows it as aborted.
        sessions = engine.list_sessions(str(self.root))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['session_id'], sid)
        self.assertEqual(sessions[0]['state'], 'aborted')
        self.assertEqual(sessions[0]['ops'], 2)
        self.assertEqual(sessions[0]['done_ops'], 1)
        self.assertNotIn('corrupt', sessions[0])

        # (f) Recoverable through the EXISTING undo path: original file bytes,
        #     filename and modification time restored exactly.
        urep = engine.undo_session(str(self.root), sid)
        self.assertTrue(urep.ok, msg=f'anomalies: {urep.anomalies}')
        self.assertEqual(urep.restored, (REL,))

        st = os.lstat(str(old_path))
        self.assertTrue(old_path.is_file(), 'original name not restored')
        self.assertFalse(new_path.exists(), 'renamed slot still present after undo')
        self.assertEqual(_sha256(old_path), self.pre_sha,
                         'undo must restore the exact original bytes')
        self.assertEqual(st.st_mtime_ns, self.pre_mtime_ns,
                         'undo must restore the original modification time exactly')

        # Terminal state recorded and session now shows undone.
        types = [e['type'] for e in self._events(sid)]
        self.assertTrue(types[-1] == 'undone', f'journal tail: {types}')
        self.assertEqual(self._sessions_by_state('aborted'), [])
        self.assertEqual(len(self._sessions_by_state('undone')), 1)

        # (g) Repeat undo is a no-op and never touches the file again.
        urep2 = engine.undo_session(str(self.root), sid)
        self.assertTrue(urep2.ok, msg=f'anomalies: {urep2.anomalies}')
        self.assertEqual(urep2.restored, ())
        self.assertEqual(_sha256(old_path), self.pre_sha)
        self.assertEqual(os.lstat(str(old_path)).st_mtime_ns, self.pre_mtime_ns)

    def test_successful_apply_then_undo_still_exact_regression(self):
        """Control: the normal successful apply + undo path is unchanged by the
        patch (focused engine-level regression; no injection)."""
        report = engine.apply_changes(str(self.root), self.preview, [REL])

        self.assertIsInstance(report, engine.ApplyReport)
        self.assertTrue(report.ok)
        self.assertEqual(report.applied, ((REL, PROPOSED),))
        self.assertEqual(report.partial, ())
        self.assertEqual(report.rejected, ())
        self.assertEqual(report.canceled, ())
        sid = report.session_id
        self.assertTrue(len(sid) == 32 and sid.isalnum())

        # On disk: renamed; TIT2 cleaned to 'Dream On'; decoys preserved.
        new_path = self.root / PROPOSED
        self.assertTrue(new_path.is_file())
        self.assertFalse((self.root / REL).exists())
        snap = read_tag_snapshot(str(new_path))
        self.assertEqual(snap.title, 'Dream On')
        self.assertEqual(snap.artist, 'Junk Artist')
        self.assertEqual(snap.album, 'Toys in the Attic',
                         'album decoy must survive the tag save')
        self.assertIn('TXXX:REPLAYGAIN_TRACK_GAIN', snap.replaygain_keys)

        # Session closed with both steps done.
        sessions = engine.list_sessions(str(self.root))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['state'], 'closed')
        self.assertEqual(sessions[0]['ops'], 2)
        self.assertEqual(sessions[0]['done_ops'], 2)

        # Undo restores name + exact bytes + mtime.
        urep = engine.undo_session(str(self.root), sid)
        self.assertTrue(urep.ok, msg=f'anomalies: {urep.anomalies}')
        self.assertEqual(urep.restored, (REL,))
        old_path = self.root / REL
        self.assertTrue(old_path.is_file())
        self.assertFalse(new_path.exists())
        self.assertEqual(_sha256(old_path), self.pre_sha)
        self.assertEqual(os.lstat(str(old_path)).st_mtime_ns, self.pre_mtime_ns)
        snap_back = read_tag_snapshot(str(old_path))
        self.assertEqual(snap_back.title, 'Dream On (Official HD Video)',
                         'undo must restore the original tag bytes exactly')


if __name__ == '__main__':
    unittest.main()
