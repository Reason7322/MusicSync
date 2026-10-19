"""Focused V12 tests for the single-track manual filename / ID3 metadata editor.

Synthetic silent-MP3 fixtures in a tempdir; Qt offscreen via the shared test
application; no phone, no KDE Connect, no network. The message-box responder is
the SAME one used by the bulk-rename suite (answers explicit Yes|No boxes so the
confirmation workflow can be exercised deterministically).

Phase 1 of this file (ManualEditorSmokeTests) proves the core loop:
open -> edit -> confirm (explicit Yes) -> journaled apply -> byte-exact undo.
"""
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest

# Shared offscreen application; must be imported before any widget use.
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from test_process import APP  # noqa: E402,F401 - shared QApplication, imports first

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from test_bulk_rename import (BoxAutoResponder, assert_same_tree, find_row, pump_until,  # noqa: E402
                              snapshot_tree)
from musicsync.bulk_rename import BulkRenameDialog  # noqa: E402
from musicsync.manual_edit import ManualEditDialog, MANUAL_FIELDS  # noqa: E402
from musicsync.vendored.engine import list_sessions, undo_session  # noqa: E402

JOURNAL_DIR = '.musicsyncrename'

_MPEG_FRAME = b'\xff\xfb\x90\xc0' + b'\x00' * 413
ARTWORK_BYTES = b'\x89PNG-fake-artwork-' + bytes(range(64))


def build_manual_fixture(root: Path):
    """One rich MP3 holding every supported field plus preserved-frame decoys.

    Returns the relative filename of the created file.
    """
    from mutagen.id3 import APIC, COMM, TALB, TCOM, TDRC, TIT2, TPE1, TPE2, TCON, TRCK, TXXX
    from mutagen.mp3 import MP3

    name = 'original name.mp3'
    with open(str(root / name), 'wb') as handle:
        for _ in range(8):
            handle.write(_MPEG_FRAME)
    audio = MP3(str(root / name))
    audio.add_tags()
    tags = audio.tags
    tags.add(TIT2(encoding=3, text=['Old Title']))
    tags.add(TPE1(encoding=3, text=['Old Artist']))
    tags.add(TALB(encoding=3, text=['Old Album']))
    tags.add(TPE2(encoding=3, text=['Old Album Artist']))
    tags.add(TCON(encoding=3, text=['Old Genre']))
    tags.add(TRCK(encoding=3, text=['1/10']))
    tags.add(TDRC(encoding=3, text=['2020']))
    tags.add(TCOM(encoding=3, text=['Old Composer']))
    # Decoy frames that MUST survive a metadata edit byte-for-byte:
    tags.add(APIC(encoding=3, mime='image/png', type=3, desc='', data=ARTWORK_BYTES))
    tags.add(TXXX(encoding=3, desc='REPLAYGAIN_TRACK_GAIN', text=['-6.5 dB']))
    tags.add(COMM(encoding=3, lang='eng', description='note', text=['keep me']))
    audio.save()
    return name


def frame_text(path, frame_id):
    """(values tuple) of one editable frame; [] when absent."""
    from mutagen.mp3 import MP3
    from musicsync.manual_edit import _frame_values
    try:
        audio = MP3(str(path))
    except Exception:
        return None
    if audio.tags is None:
        return ()
    return _frame_values(audio.tags, frame_id)


#: Original single stored value of every supported field in build_manual_fixture.
ORIGINAL_VALUES = {
    'title': 'Old Title',
    'artist': 'Old Artist',
    'album': 'Old Album',
    'album_artist': 'Old Album Artist',
    'genre': 'Old Genre',
    'track_number': '1/10',
    'date_year': '2020',
    'composer': 'Old Composer',
}

AUDIO_TAIL_LEN = 8 * len(_MPEG_FRAME)  # the fixture's entire audio portion


def assert_decoys_intact(testcase, path):
    """Artwork / ReplayGain / comment frames must survive any manual edit byte-for-byte."""
    from mutagen.mp3 import MP3
    tags = MP3(str(path)).tags
    apic_frames = []
    for key in list(tags.keys()):
        if key.startswith('APIC'):
            apic_frames.extend(tags.getall(key))
    testcase.assertTrue(apic_frames, 'artwork frame lost by metadata edit')
    testcase.assertEqual(bytes(apic_frames[0].data), ARTWORK_BYTES, 'artwork bytes altered by metadata edit')
    testcase.assertEqual(frame_text(path, 'TXXX:REPLAYGAIN_TRACK_GAIN'), ('-6.5 dB',),
                         'ReplayGain frame lost or altered by metadata edit')
    comm_keys = [k for k in tags.keys() if k.startswith('COMM')]
    testcase.assertTrue(comm_keys, 'comment frame lost by metadata edit')


def assert_other_fields_unchanged(testcase, path, changed_keys=()):
    """Every supported field not listed in ``changed_keys`` still holds the fixture original."""
    for key, frame_id, _label in MANUAL_FIELDS:
        if key in changed_keys:
            continue
        testcase.assertEqual(frame_text(path, frame_id), (ORIGINAL_VALUES[key],),
                             f'untouched field {key} ({frame_id}) changed on disk')


def wait_no_visible_boxes(timeout_ms=8000):
    """Pump until the responder has drained every open message box."""
    deadline = time.monotonic() + timeout_ms / 1000.0

    def no_boxes():
        try:
            return not [w for w in APP.allWidgets()
                        if isinstance(w, QMessageBox) and w.isVisible()]
        except RuntimeError:  # C++ objects deleted mid-iteration
            return True

    loop = QEventLoop()

    def tick():
        if no_boxes() or time.monotonic() > deadline:
            loop.quit()

    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(tick)
    guard = QTimer()
    guard.setSingleShot(True)
    guard.start(timeout_ms + 5000)
    guard.timeout.connect(loop.quit)
    tick()  # short-circuit when nothing is open
    if not no_boxes():
        timer.start()
        loop.exec()
    timer.stop()
    guard.stop()


class ManualEditorSmokeTests(unittest.TestCase):
    """Open / edit / apply (explicit Yes) / byte-exact undo on one synthetic MP3."""

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory(prefix='musicsync-manualedit-')
        self.library = Path(self._tempdir.name) / 'library'
        self.library.mkdir()
        self.track_name = build_manual_fixture(self.library)
        self.track_path = self.library / self.track_name
        self.original_bytes = self.track_path.read_bytes()
        self.pre_snapshot = snapshot_tree(self.library)
        self.responder = BoxAutoResponder()
        self.responder.start()
        self.dialogs = []

    def tearDown(self):
        wait_no_visible_boxes(5000)
        for dialog in self.dialogs:
            try:
                dialog.close()
            except Exception:
                pass
        self.responder.stop()
        self._tempdir.cleanup()

    # 1 ------------------------------------------------------------------

    def test_open_and_close_without_apply_is_byte_identical(self):
        before = snapshot_tree(self.library)
        editor = ManualEditDialog(str(self.library), self.track_name)
        self.dialogs.append(editor)
        APP.processEvents()
        try:
            # The form reflects the stored values exactly.
            self.assertEqual(editor.filename_edit.text(), 'original name.mp3')
            self.assertEqual(editor.field_edits['title'].text(), 'Old Title')
            self.assertEqual(editor.field_edits['artist'].text(), 'Old Artist')
            self.assertEqual(editor.field_edits['track_number'].text(), '1/10')
            # Inspection pane lists the decoys as preserved.
            inspection = editor.inspection_pane.toPlainText()
            self.assertIn('REPLAYGAIN_TRACK_GAIN', inspection)
            self.assertIn('APIC: 1 artwork image(s) — preserved', inspection)
            # No change yet -> Apply disabled, nothing pending.
            self.assertFalse(editor.apply_button.isEnabled())

            # Edit something in the form only (no apply): still must not touch disk.
            editor.field_edits['title'].setText('Changed In Form Only')
            APP.processEvents()
            self.assertTrue(editor.apply_button.isEnabled(), 'Apply should enable once a diff exists')
        finally:
            editor.reject()  # Cancel path; no confirmation box involved

        wait_no_visible_boxes(3000)
        after = snapshot_tree(self.library)
        assert_same_tree(self, before, after, label='after open+edit+cancel (no apply)')
        self.assertEqual(self.track_path.read_bytes(), self.original_bytes,
                         'bytes changed although nothing was applied')
        self.assertFalse((self.library / JOURNAL_DIR).exists(), 'a journal dir was created without an apply')
        self.assertEqual(list_sessions(str(self.library)), [])

    # 2 ------------------------------------------------------------------

    def test_metadata_edit_applies_and_undo_restores_exact_bytes(self):
        editor = ManualEditDialog(str(self.library), self.track_name)
        self.dialogs.append(editor)
        APP.processEvents()

        # One metadata change: Title only.
        editor.field_edits['title'].setText('New Title')
        APP.processEvents()
        preview_text = editor.change_preview.toPlainText()
        self.assertIn('Title', preview_text)
        self.assertTrue(editor.apply_button.isEnabled())

        editor.apply_button.click()  # confirmation box raised; responder answers Yes (explicit)
        self.assertTrue(pump_until(lambda: self.responder.box_with('Apply manual changes') is not None,
                                   8000), f'no confirmation box: {self.responder.boxes}')
        confirm = self.responder.box_with('Apply manual changes')
        self.assertIsNotNone(confirm)
        self.assertEqual(confirm['chosen'], 'Yes', 'confirmation must be answered explicitly')

        # Worker thread completes the journaled apply off-GUI-thread.
        self.assertTrue(pump_until(lambda: editor.applied_report is not None, 15000),
                        'apply worker did not finish')
        report = editor.applied_report
        wait_no_visible_boxes(8000)

        self.assertEqual(len(report.rejected), 0, f'rejected={report.rejected}')
        self.assertEqual(len(report.partial), 0, f'partial={report.partial}')
        self.assertTrue(report.session_id)
        applied = dict(report.applied)
        self.assertIn(self.track_name, applied)

        # On-disk verification with mutagen (actual file state, not mock).
        snapshot_title = frame_text(self.library / self.track_name, 'TIT2')
        self.assertEqual(snapshot_title, ('New Title',), 'TIT2 not updated on disk')
        from mutagen.mp3 import MP3
        tags_now = MP3(str(self.library / self.track_name)).tags
        from musicsync.manual_edit import _frame_values as fv
        apic_frames = []
        for k in list(tags_now.keys()):
            if k.startswith('APIC'):
                apic_frames.extend(tags_now.getall(k))
        self.assertTrue(apic_frames, 'artwork frame lost by metadata edit')
        self.assertEqual(bytes(apic_frames[0].data), ARTWORK_BYTES,
                         'artwork bytes altered by a text-frame edit')
        self.assertEqual(fv(tags_now, 'TPE1'), ('Old Artist',), 'untouched frame changed')
        self.assertEqual(frame_text(self.library / self.track_name, 'TXXX:REPLAYGAIN_TRACK_GAIN'),
                         ('-6.5 dB',), 'ReplayGain frame lost or altered by metadata edit')
        comm_keys = [k for k in tags_now.keys() if k.startswith('COMM')]
        self.assertTrue(comm_keys, 'comment frame lost by metadata edit')

        # The engine journaled the session; undo restores original name AND bytes.
        sessions = {s['session_id']: s for s in list_sessions(str(self.library))}
        self.assertEqual(sessions[report.session_id]['state'], 'closed',
                         f'session state: {sessions.get(report.session_id)}')
        report_undo = undo_session(str(self.library), report.session_id)
        self.assertEqual(tuple(report_undo.anomalies), (), f'anomalies={report_undo.anomalies}')

        restored_bytes = self.track_path.read_bytes()
        self.assertEqual(hashlib.sha256(restored_bytes).hexdigest(),
                         hashlib.sha256(self.original_bytes).hexdigest(),
                         'undo did not restore the exact original bytes (incl. tag area)')
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library), label='after undo')
        self.assertEqual(frame_text(self.track_path, 'TIT2'), ('Old Title',),
                         'original TIT2 text not restored after undo')
        sessions_after = {s['session_id']: s for s in list_sessions(str(self.library))}
        self.assertEqual(sessions_after[report.session_id]['state'], 'undone',
                         'session state must be undone after a byte-exact restore')

    # V13 case helpers --------------------------------------------------------

    def _fresh_track(self, subdir_name):
        """Fresh fixture in an isolated subdir of the library.

        Returns (root, rel_name, path, original_bytes, pre_snapshot, mtime_ns).
        """
        root = self.library / subdir_name
        root.mkdir()
        name = build_manual_fixture(root)
        path = root / name
        return (root, name, path, path.read_bytes(), snapshot_tree(root),
                int(os.lstat(str(path)).st_mtime_ns))

    def _apply_explicit_yes(self, editor):
        """Click Apply…, require the explicit Yes|No box answered Yes, wait for worker + result box."""
        self.assertTrue(editor.apply_button.isEnabled(), 'Apply should be enabled once a diff exists')
        prior_boxes = len(self.responder.boxes)
        editor.apply_button.click()  # confirmation box raised; responder answers Yes (explicit)
        self.assertTrue(pump_until(lambda: len(self.responder.boxes) > prior_boxes, 8000),
                        f'no new confirmation box recorded: {self.responder.boxes}')
        confirm = self.responder.boxes[prior_boxes]
        self.assertEqual(confirm['title'], 'Apply manual changes',
                         f'expected the apply-confirmation box first, got {confirm!r}')
        self.assertEqual(confirm['chosen'], 'Yes', 'the explicit confirmation must be answered Yes')
        # Worker thread completes the journaled apply off-GUI-thread.
        self.assertTrue(pump_until(lambda: editor.applied_report is not None, 15000),
                        'apply worker did not finish')
        wait_no_visible_boxes(8000)  # drain the 'Manual edit result' box
        report = editor.applied_report
        self.assertEqual(len(report.rejected), 0, f'rejected={report.rejected}')
        self.assertEqual(len(report.partial), 0, f'partial={report.partial}')
        self.assertTrue(report.session_id)
        return report

    def _undo_session_and_check_state(self, root, session_id):
        sessions = {s['session_id']: s for s in list_sessions(str(root))}
        self.assertEqual(sessions[session_id]['state'], 'closed',
                         f'session state: {sessions.get(session_id)}')
        report_undo = undo_session(str(root), session_id)
        self.assertEqual(tuple(report_undo.anomalies), (), f'anomalies={report_undo.anomalies}')
        sessions_after = {s['session_id']: s for s in list_sessions(str(root))}
        self.assertEqual(sessions_after[session_id]['state'], 'undone',
                         'session state must be undone after a byte-exact restore')

    # V13 case 1 ----------------------------------------------------------------

    def test_filename_only_rename_applies_and_undoes(self):
        root, name, path, original_bytes, pre_snapshot, orig_mtime_ns = self._fresh_track('case-filename-only')
        editor = ManualEditDialog(str(root), name)
        self.dialogs.append(editor)
        APP.processEvents()

        # Change ONLY the filename; every metadata field stays at its stored value.
        new_name = 'renamed file.mp3'
        editor.filename_edit.setText(new_name)
        APP.processEvents()
        preview_text = editor.change_preview.toPlainText()
        self.assertIn(name, preview_text)
        self.assertIn(new_name, preview_text)

        report = self._apply_explicit_yes(editor)
        applied = dict(report.applied)
        self.assertEqual(applied.get(name), new_name, 'applied must map the old name to the new one')

        # On disk: renamed file exists, old path gone, MP3 content unchanged.
        renamed_path = root / new_name
        self.assertTrue(renamed_path.is_file(), 'renamed file missing on disk')
        self.assertFalse(path.exists(), 'old path still present after rename')
        self.assertEqual(renamed_path.read_bytes(), original_bytes,
                         'MP3 content (audio + tags) changed by a pure filename change')

        # Undo: original filename, exact bytes AND mtime restored.
        self._undo_session_and_check_state(root, report.session_id)
        self.assertTrue(path.is_file(), 'original filename not restored by undo')
        self.assertFalse(renamed_path.exists(), 'renamed file still present after undo')
        restored = path.read_bytes()
        self.assertEqual(hashlib.sha256(restored).hexdigest(), hashlib.sha256(original_bytes).hexdigest(),
                         'undo did not restore the exact original bytes')
        self.assertEqual(int(os.lstat(str(path)).st_mtime_ns), orig_mtime_ns, 'mtime not restored by undo')
        assert_same_tree(self, pre_snapshot, snapshot_tree(root), label='filename-only after undo')

    # V13 case 2 -----------------------------------------------------------------

    def test_combined_filename_and_metadata_applies_and_undoes(self):
        root, name, path, original_bytes, pre_snapshot, orig_mtime_ns = self._fresh_track('case-combined')
        editor = ManualEditDialog(str(root), name)
        self.dialogs.append(editor)
        APP.processEvents()

        # Change filename + Title + Album together.
        new_name = 'combined new.mp3'
        editor.filename_edit.setText(new_name)
        editor.field_edits['title'].setText('Combined Title')
        editor.field_edits['album'].setText('Combined Album')
        APP.processEvents()
        preview_text = editor.change_preview.toPlainText()
        self.assertIn(name, preview_text)
        self.assertIn(new_name, preview_text)
        self.assertIn('Title', preview_text)
        self.assertIn('Album', preview_text)

        report = self._apply_explicit_yes(editor)
        applied = dict(report.applied)
        self.assertEqual(applied.get(name), new_name, 'applied must map the old name to the new one')

        # All three changes on disk.
        renamed_path = root / new_name
        self.assertTrue(renamed_path.is_file(), 'renamed file missing on disk')
        self.assertFalse(path.exists(), 'old path still present after apply')
        from mutagen.mp3 import MP3
        tags_now = MP3(str(renamed_path)).tags
        from musicsync.manual_edit import _frame_values as fv
        self.assertEqual(fv(tags_now, 'TIT2'), ('Combined Title',), 'Title not updated on disk')
        self.assertEqual(fv(tags_now, 'TALB'), ('Combined Album',), 'Album not updated on disk')
        # Unrelated frames and audio preserved.
        assert_other_fields_unchanged(self, renamed_path, changed_keys=('title', 'album'))
        assert_decoys_intact(self, renamed_path)
        self.assertEqual(renamed_path.read_bytes()[-AUDIO_TAIL_LEN:], original_bytes[-AUDIO_TAIL_LEN:],
                         'audio frames altered by the combined edit')

        # Undo: original name, exact bytes and mtime exactly match the pre-test snapshot.
        self._undo_session_and_check_state(root, report.session_id)
        self.assertTrue(path.is_file(), 'original filename not restored by undo')
        self.assertFalse(renamed_path.exists(), 'renamed file still present after undo')
        restored = path.read_bytes()
        self.assertEqual(hashlib.sha256(restored).hexdigest(), hashlib.sha256(original_bytes).hexdigest(),
                         'undo did not restore the exact original bytes (incl. tag area)')
        self.assertEqual(int(os.lstat(str(path)).st_mtime_ns), orig_mtime_ns, 'mtime not restored by undo')
        assert_same_tree(self, pre_snapshot, snapshot_tree(root), label='combined after undo')

    # V13 case 3 -----------------------------------------------------------------

    def test_independent_single_field_edits_all_supported_fields(self):
        cases = (
            ('title', 'TIT2', 'Edited Title'),
            ('artist', 'TPE1', 'Edited Artist'),
            ('album', 'TALB', 'Edited Album'),
            ('album_artist', 'TPE2', 'Edited Album Artist'),
            ('genre', 'TCON', 'Edited Genre'),
            ('track_number', 'TRCK', '7/12'),
            ('date_year', 'TDRC', '2024'),
            ('composer', 'TCOM', 'Edited Composer'),
        )
        for key, frame_id, new_value in cases:
            with self.subTest(field=key):
                root, name, path, original_bytes, pre_snapshot, _mtime_ns = self._fresh_track(f'field-{key}')
                editor = ManualEditDialog(str(root), name)
                self.dialogs.append(editor)
                APP.processEvents()

                # Only this field changes; every other form field keeps its stored value.
                editor.field_edits[key].setText(new_value)
                APP.processEvents()
                report = self._apply_explicit_yes(editor)
                applied = dict(report.applied)
                self.assertIn(name, applied, 'the single track must be the only applied item')

                # On disk: the intended frame changed and nothing else.
                from mutagen.mp3 import MP3
                tags_now = MP3(str(path)).tags
                from musicsync.manual_edit import _frame_values as fv
                self.assertEqual(fv(tags_now, frame_id), (new_value,), f'{frame_id} not updated on disk')
                assert_other_fields_unchanged(self, path, changed_keys=(key,))
                assert_decoys_intact(self, path)

                # Undo restores the exact original bytes.
                self._undo_session_and_check_state(root, report.session_id)
                restored = path.read_bytes()
                self.assertEqual(hashlib.sha256(restored).hexdigest(),
                                 hashlib.sha256(original_bytes).hexdigest(),
                                 'undo did not restore the exact original bytes')
                assert_same_tree(self, pre_snapshot, snapshot_tree(root), label=f'field {key} after undo')

    # V13 case 4 -----------------------------------------------------------------

    def test_deletion_of_existing_field_is_explicit_and_undoable(self):
        root, name, path, original_bytes, pre_snapshot, orig_mtime_ns = self._fresh_track('case-deletion')
        editor = ManualEditDialog(str(root), name)
        self.dialogs.append(editor)
        APP.processEvents()

        # Clear an existing supported metadata field (Composer / TCOM).
        key, frame_id = 'composer', 'TCOM'
        label = next(l for k, _f, l in MANUAL_FIELDS if k == key)
        self.assertEqual(editor.field_edits[key].text(), ORIGINAL_VALUES[key])
        editor.field_edits[key].setText('')
        APP.processEvents()

        # The preview must identify this as an explicit deletion.
        preview_text = editor.change_preview.toPlainText()
        self.assertIn(label, preview_text)
        self.assertIn(ORIGINAL_VALUES[key], preview_text)
        self.assertIn('deleted', preview_text)

        report = self._apply_explicit_yes(editor)  # Apply only after the explicit Yes confirmation

        from mutagen.mp3 import MP3
        tags_now = MP3(str(path)).tags
        self.assertEqual(tags_now.getall(frame_id), [], f'{frame_id} frame still present after deletion')
        assert_other_fields_unchanged(self, path, changed_keys=(key,))
        assert_decoys_intact(self, path)

        # Undo restores the original frame and exact original MP3 bytes.
        self._undo_session_and_check_state(root, report.session_id)
        restored = path.read_bytes()
        self.assertEqual(hashlib.sha256(restored).hexdigest(), hashlib.sha256(original_bytes).hexdigest(),
                         'undo did not restore the exact original bytes after a deletion')
        self.assertEqual(int(os.lstat(str(path)).st_mtime_ns), orig_mtime_ns, 'mtime not restored by undo')
        assert_same_tree(self, pre_snapshot, snapshot_tree(root), label='deletion after undo')
        self.assertEqual(frame_text(path, frame_id), (ORIGINAL_VALUES[key],),
                         'deleted frame not restored by undo')


if __name__ == '__main__':
    unittest.main()
