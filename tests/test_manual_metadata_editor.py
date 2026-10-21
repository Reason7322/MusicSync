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

from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QMessageBox, QPushButton  # noqa: E402

from test_bulk_rename import (BoxAutoResponder, assert_same_tree, build_library, F4, find_row,  # noqa: E402
                              pump_until, session_row, snapshot_tree, wait_idle, wait_operation)
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


    # V14 safety cases ----------------------------------------------------------

    def test_unsafe_filenames_are_rejected_and_cannot_bypass(self):
        """Every invalid filename input is refused: error shown, Apply disabled, disk untouched."""
        root, name, path, original_bytes, pre_snapshot, orig_mtime_ns = self._fresh_track('case-unsafe-names')
        editor = ManualEditDialog(str(root), name)
        self.dialogs.append(editor)
        APP.processEvents()

        unsafe_cases = (
            ('empty filename', ''),
            ('whitespace-only filename', '     '),
            ('missing stem (.mp3)', '.mp3'),
            ('extension changed to .flac', 'renamed.flac'),
            ('forward slash / traversal', '../escape.mp3'),
            ('backslash separator', 'bad\\name.mp3'),
            ('control character', 'ctrl\x01char.mp3'),
            ('longer than 255 UTF-8 bytes', 'a' * 300 + '.mp3'),
        )
        for case_name, proposed in unsafe_cases:
            with self.subTest(name=case_name):
                editor.filename_edit.setText(proposed)
                APP.processEvents()

                # 1. Validation reports an error (direct API, live label and preview line).
                self.assertTrue(editor.validate_filename(proposed),
                                'validate_filename must reject this name')
                self.assertNotEqual(editor.filename_error.text(), '',
                                    'the filename error label must show the problem')
                lines, error, _edits, _proposed_out = editor.pending_changes()
                self.assertTrue(error, f'pending_changes must carry an error, got {error!r}')
                self.assertIn('Filename: INVALID', '\n'.join(lines))

                # 2. Apply is disabled while the name is invalid.
                self.assertFalse(editor.apply_button.isEnabled())

                # 3. The original file's bytes and mtime are unchanged; no renamed file appears.
                self.assertEqual(path.read_bytes(), original_bytes, 'bytes changed without an apply')
                self.assertEqual(int(os.lstat(str(path)).st_mtime_ns), orig_mtime_ns,
                                 'mtime changed without an apply')
                self.assertEqual(set(os.listdir(root)), {name}, 'a renamed or extra entry appeared')

                # 4. No journal and no session was created.
                self.assertFalse((root / JOURNAL_DIR).exists(), 'journal dir created by a refused edit')
                self.assertEqual(list_sessions(str(root)), [])

        with self.subTest(name='metadata change cannot bypass an invalid filename'):
            editor.filename_edit.setText('traversal/bypass.mp3')
            editor.field_edits['title'].setText('Bypass Title')  # pending metadata diff alongside
            APP.processEvents()
            lines, error, _edits, _proposed_out = editor.pending_changes()
            text_lines = '\n'.join(lines)
            self.assertIn('Filename: INVALID', text_lines, 'the invalid name must still be flagged')
            self.assertIn('Title', text_lines, 'the metadata change is pending alongside the error')
            self.assertTrue(error)
            self.assertFalse(editor.apply_button.isEnabled(),
                             'a metadata edit must not enable Apply over an invalid filename')

            # Even if the apply slot were reached directly it is fail-closed: no mutation.
            editor.apply_button.click()
            wait_no_visible_boxes(4000)  # drain any surfaced refusal box
            self.assertIsNone(editor.applied_report, 'an apply must not have run')
            self.assertEqual(path.read_bytes(), original_bytes)
            self.assertEqual(int(os.lstat(str(path)).st_mtime_ns), orig_mtime_ns)
            self.assertEqual(set(os.listdir(root)), {name})
            self.assertFalse((root / JOURNAL_DIR).exists())
            self.assertEqual(list_sessions(str(root)), [])

        assert_same_tree(self, pre_snapshot, snapshot_tree(root), label='after all unsafe-name rejections')

    def test_existing_file_collisions_are_rejected(self):
        """Renaming onto an existing file (exact or case-equivalent name_key) is refused."""
        root, name, path, original_bytes, _pre_snapshot, orig_mtime_ns = self._fresh_track('case-collision')
        # Second MP3 inside the same isolated fixture directory.
        second_name = 'target existing.mp3'
        with open(str(root / second_name), 'wb') as handle:
            for _ in range(8):
                handle.write(_MPEG_FRAME)
        second_path = root / second_name
        second_bytes = second_path.read_bytes()
        second_mtime_ns = int(os.lstat(str(second_path)).st_mtime_ns)
        pre_snapshot = snapshot_tree(root)  # both files present

        editor = ManualEditDialog(str(root), name)
        self.dialogs.append(editor)
        APP.processEvents()

        def check_collision(case_name, proposed):
            with self.subTest(name=case_name):
                editor.filename_edit.setText(proposed)
                APP.processEvents()

                # The live directory already holds a colliding name (name_key comparison).
                collision = editor.filename_collision(proposed)
                self.assertTrue(collision, 'filename_collision must identify the existing file')
                self.assertIn('already exists', collision)
                self.assertNotEqual(editor.filename_error.text(), '', 'the collision must be shown in the form')

                lines, error, _edits, proposed_out = editor.pending_changes()
                self.assertTrue(error, 'the collision must block the pending change')
                self.assertEqual(proposed_out, proposed,
                                 'the rename intent is previewed but blocked by the collision')

                # Apply is disabled; neither MP3 changes at all.
                self.assertFalse(editor.apply_button.isEnabled())
                self.assertEqual(path.read_bytes(), original_bytes)
                self.assertEqual(int(os.lstat(str(path)).st_mtime_ns), orig_mtime_ns)
                self.assertEqual(second_path.read_bytes(), second_bytes, 'the existing target file was touched')
                self.assertEqual(int(os.lstat(str(second_path)).st_mtime_ns), second_mtime_ns)
                self.assertEqual(set(os.listdir(root)), {name, second_name}, 'names on disk changed')

                # No journal and no session was created.
                self.assertFalse((root / JOURNAL_DIR).exists())
                self.assertEqual(list_sessions(str(root)), [])

        check_collision('exact existing filename', second_name)
        case_equiv = 'TARGET EXISTING.mp3'  # same name_key as the existing file (case-insensitive FS rule)
        check_collision('case-equivalent existing filename', case_equiv)

        assert_same_tree(self, pre_snapshot, snapshot_tree(root), label='after collision rejections')

    # V15 acceptance case A ---------------------------------------------------

    def test_unchanged_input_noop_changes_nothing(self):
        """No-op safety: unchanged input modifies nothing and creates no journal/session."""
        orig_mtime_ns = int(os.lstat(str(self.track_path)).st_mtime_ns)
        before_titles = list(self.responder.titles())
        editor = ManualEditDialog(str(self.library), self.track_name)
        self.dialogs.append(editor)
        APP.processEvents()

        # The form reflects the stored values; there is no pending diff at all.
        lines, error, edits, proposed_out = editor.pending_changes()
        self.assertEqual(lines, [], 'unchanged input must produce no preview lines')
        self.assertEqual(error, '')
        self.assertEqual(edits, ())
        self.assertIsNone(proposed_out)
        self.assertFalse(editor.apply_button.isEnabled(), 'Apply is disabled with an empty diff')

        # Click the (disabled) Apply control directly. Whether this Qt build forwards a
        # programmatic click to a disabled button or not, nothing may happen: the slot's
        # own zero-diff guard only surfaces a 'No changes' information box.
        editor.apply_button.click()
        wait_no_visible_boxes(4000)
        new_titles = self.responder.titles()[len(before_titles):]
        self.assertTrue(all(t == 'No changes' for t in new_titles),
                        f'unexpected boxes after a no-op Apply: {new_titles}')

        # Nothing modified; nothing journaled.
        self.assertEqual(self.track_path.read_bytes(), self.original_bytes,
                         'bytes changed although the input was unchanged')
        self.assertEqual(int(os.lstat(str(self.track_path)).st_mtime_ns), orig_mtime_ns)
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library), label='after no-op apply')
        self.assertFalse((self.library / JOURNAL_DIR).exists(), 'journal dir created by a no-op click')
        self.assertEqual(list_sessions(str(self.library)), [])
        self.assertIsNone(editor.applied_report)
        self.assertFalse(editor.changes_applied)
        self.assertFalse(editor.busy)

    # V15 acceptance case B ---------------------------------------------------

    def test_stale_file_modified_while_open_is_rejected_and_not_overwritten(self):
        """Stale-file protection: a file modified externally after the dialog's snapshot is
        rejected (changed_since_preview), never overwritten."""
        root, name, path, original_bytes, _pre_snapshot, _mtime_ns = self._fresh_track('case-stale')

        editor = ManualEditDialog(str(root), name)  # open_stat snapshot taken here
        self.dialogs.append(editor)
        APP.processEvents()

        # Pending change in the form: rename + Title edit.
        new_name = 'externally owned.mp3'
        editor.filename_edit.setText(new_name)
        editor.field_edits['title'].setText('Stale Title')
        APP.processEvents()
        self.assertTrue(editor.apply_button.isEnabled(), 'Apply must enable once a diff exists')

        # External modification AFTER the dialog's snapshot: another tool rewrote the tags.
        from mutagen.id3 import TIT2
        from mutagen.mp3 import MP3
        audio = MP3(str(path))
        for key in list(audio.tags.keys()):
            if key == 'TIT2':
                del audio.tags[key]
        audio.tags.add(TIT2(encoding=3, text=['External Owner']))
        audio.save()
        external_bytes = path.read_bytes()
        ext_mtime_ns = int(os.lstat(str(path)).st_mtime_ns)
        self.assertNotEqual(external_bytes, original_bytes, 'fixture: external edit must change bytes')

        prior_boxes = len(self.responder.boxes)
        editor.apply_button.click()  # explicit Yes|No confirmation; responder answers Yes
        self.assertTrue(pump_until(lambda: len(self.responder.boxes) > prior_boxes, 8000),
                        f'no confirmation box recorded: {self.responder.boxes}')
        confirm = self.responder.boxes[prior_boxes]
        self.assertEqual(confirm['title'], 'Apply manual changes',
                         f'expected the apply-confirmation box first, got {confirm!r}')
        self.assertEqual(confirm['chosen'], 'Yes', 'the explicit confirmation must be answered Yes')

        # The journaled worker re-validates against the live file and refuses the stale op.
        self.assertTrue(pump_until(lambda: editor.applied_report is not None, 15000),
                        'apply worker did not finish')
        report = editor.applied_report
        wait_no_visible_boxes(8000)  # drain the surfaced rejection box

        # The outdated operation is rejected with the stable code; no journal at all.
        self.assertEqual(report.session_id, '', 'an all-rejected apply must not create a session')
        self.assertEqual(tuple(report.applied), (), f'applied={report.applied}')
        self.assertEqual(tuple(report.rejected), ((name, 'changed_since_preview'),),
                         f'rejected={report.rejected}')
        self.assertEqual(tuple(report.partial), ())

        # The rejection is reported through the real GUI, not only in the report.
        notice = self.responder.box_with('Nothing applied')
        self.assertIsNotNone(notice, 'the stale apply must surface a refusal box')
        self.assertIn(name, notice['text'])
        self.assertIn('changed_since_preview', notice['text'])

        # The external modification was NOT overwritten by the stale proposal.
        final_bytes = path.read_bytes()
        self.assertEqual(hashlib.sha256(final_bytes).hexdigest(),
                         hashlib.sha256(external_bytes).hexdigest(),
                         'the externally modified file was altered despite rejection')
        self.assertEqual(int(os.lstat(str(path)).st_mtime_ns), ext_mtime_ns)
        self.assertFalse((root / new_name).exists(), 'a rejected rename must not appear on disk')
        self.assertEqual(set(os.listdir(root)), {name})

        # No journal/session anywhere; the dialog reports failure and stays editable.
        self.assertFalse((root / JOURNAL_DIR).exists())
        self.assertEqual(list_sessions(str(root)), [])
        self.assertFalse(editor.changes_applied)
        self.assertTrue(editor.filename_edit.isEnabled(), 'form must stay usable after a refused apply')


class ManualEditorGuiIntegrationTests(unittest.TestCase):
    """Real GUI acceptance (Mission 15, case C).

    Drives the ACTUAL BulkRenameDialog: preview of the synthetic library containing an
    ambiguous MP3 -> select that row -> real 'Manual Edit…' button -> correct filename and
    metadata -> Apply with explicit Yes -> verify file + journal session -> locate the
    session in the real Sessions tab -> real Undo control -> byte-exact restoration.
    """

    NEW_NAME = 'manual review fixed.mp3'
    NEW_TITLE = 'Corrected Title'
    NEW_ARTIST = 'Corrected Artist'

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory(prefix='musicsync-manualedit-gui-')
        self.library = Path(self._tempdir.name) / 'library'
        self.library.mkdir()
        build_library(self.library)  # the established deterministic 8-file fixture
        self.orig_f4_bytes = (self.library / F4).read_bytes()
        self.pre_snapshot = snapshot_tree(self.library)
        self.responder = BoxAutoResponder()
        self.responder.start()
        self.dialog = None
        self.editors = []

    def tearDown(self):
        for editor in self.editors:
            try:
                wait_no_visible_boxes(3000)
                if not editor.isHidden():
                    editor.reject()
            except Exception:
                pass
        if self.dialog is not None:
            try:
                wait_idle(self.dialog, 10000)
                self.dialog.close()
            except Exception:
                pass
        self.responder.stop()
        self._tempdir.cleanup()

    def test_manual_edit_button_fixes_ambiguous_row_and_sessions_undo_restores_exactly(self):
        dialog = BulkRenameDialog(str(self.library), None)
        self.dialog = dialog
        self.assertTrue(wait_idle(dialog), 'initial scan did not finish')

        # Mission 15 fix verification: both controls live in their intended layouts —
        # the same container as their row siblings (orphaned buttons would parent to the top level).
        self.assertIsNotNone(dialog.manual_edit_button.parent())
        self.assertEqual(dialog.manual_edit_button.parent(), dialog.preview_button.parent(),
                         'Manual Edit… button is not placed in the preview actions layout')
        self.assertIsNotNone(dialog.undo_button.parent())
        self.assertEqual(dialog.undo_button.parent(), dialog.refresh_sessions_button.parent(),
                         'Undo control is not placed in the sessions tab layout')

        # Preview a synthetic library containing an ambiguous MP3 (F4: multiple separators,
        # no ID3). It is NOT approvable in the bulk flow.
        items = {item.rel_path: item for item in dialog.preview.items}
        self.assertEqual(items[F4].status, 'ambiguous', f'status={items[F4].status}')
        self.assertIn('multiple_separators', [f.code for f in items[F4].flags])
        row_f4 = find_row(dialog, F4)
        cell0 = dialog.preview_table.item(row_f4, 0)
        self.assertFalse(cell0.flags() & Qt.ItemFlag.ItemIsUserCheckable,
                         'the ambiguous row must not be bulk-approvable')

        # Select the row and start the drive timer BEFORE clicking: the click blocks in
        # the editor's modal exec(), so only a running GUI-thread timer can drive it.
        dialog.preview_table.setCurrentCell(row_f4, 0)
        old_preview = dialog.preview
        found = {'editor': None}
        state = {'apply_clicked': False, 'cancelled': False, 'error': None}

        def drive():
            if state['error'] is not None:
                return
            try:
                if found['editor'] is None:
                    for obj in APP.allWidgets():
                        try:
                            if isinstance(obj, ManualEditDialog):
                                found['editor'] = obj
                                break
                        except RuntimeError:  # C++ object deleted mid-iteration
                            continue
                    return
                editor = found['editor']
                if not state['apply_clicked']:
                    self.assertEqual(editor.rel_path, F4)
                    self.assertEqual(editor.filename_edit.text(), F4)
                    # Correct the ambiguous track's filename and metadata in the real form.
                    editor.filename_edit.setText(self.NEW_NAME)
                    editor.field_edits['title'].setText(self.NEW_TITLE)
                    editor.field_edits['artist'].setText(self.NEW_ARTIST)
                    if not editor.apply_button.isEnabled():
                        return  # wait for the textChanged-driven refresh tick
                    state['apply_clicked'] = True
                    editor.apply_button.click()  # explicit Yes|No box; responder answers Yes
                elif editor.changes_applied and not state['cancelled']:
                    # Applied: its result box was drained by the responder. Close the still-open
                    # form through its real Cancel button so exec() can return.
                    cancel = next((b for b in editor.findChildren(QPushButton)
                                   if b.objectName() == 'cancel_button'), None)
                    if cancel is not None:
                        cancel.click()
                    else:  # structural fallback, identical to the button's own slot
                        editor.reject()
                    state['cancelled'] = True
            except Exception as exc:  # recorded and asserted after exec() returns
                state['error'] = repr(exc)

        drive_timer = QTimer()
        drive_timer.setInterval(25)
        drive_timer.timeout.connect(drive)
        drive_timer.start()
        try:
            dialog.manual_edit_button.click()  # blocks while the editor's modal exec() runs
        finally:
            drive_timer.stop()

        self.assertIsNone(state['error'], f'drive timer failed inside the modal editor: {state["error"]}')
        editor = found['editor']
        self.editors.append(editor)
        self.assertIsNotNone(editor, 'ManualEditDialog was never opened by the real button')
        self.assertTrue(state['cancelled'], 'the editor did not reach its applied-and-closed state')

        # The apply confirmation existed and was answered explicitly; a result box followed.
        confirm = self.responder.box_with('Apply manual changes')
        self.assertIsNotNone(confirm, f'missing the apply-confirmation box: {self.responder.boxes}')
        self.assertEqual(confirm['chosen'], 'Yes', 'the apply must be confirmed explicitly')
        self.assertIsNotNone(self.responder.box_with('Manual edit result'),
                             f'missing the editor result box: {self.responder.boxes}')

        report = editor.applied_report
        self.assertIsNotNone(report, 'no applied report from the manual editor')
        self.assertEqual(tuple(report.rejected), (), f'rejected={report.rejected}')
        self.assertEqual(tuple(report.partial), ())
        self.assertTrue(report.session_id)
        self.assertEqual(dict(report.applied).get(F4), self.NEW_NAME,
                         f'applied must rename the ambiguous row: {report.applied}')

        # The resulting file is verified on disk (name + corrected metadata; audio intact).
        fixed = self.library / self.NEW_NAME
        self.assertTrue(fixed.is_file(), 'renamed file missing after manual apply')
        self.assertFalse((self.library / F4).exists(), 'original name still present after apply')
        from mutagen.mp3 import MP3 as _MP3
        from musicsync.manual_edit import _frame_values as fv
        tags_now = _MP3(str(fixed)).tags
        self.assertEqual(fv(tags_now, 'TIT2'), (self.NEW_TITLE,), 'Title not corrected on disk')
        self.assertEqual(fv(tags_now, 'TPE1'), (self.NEW_ARTIST,), 'Artist not corrected on disk')
        self.assertTrue(fixed.read_bytes().endswith(self.orig_f4_bytes),
                        'audio frames altered by the manual edit')

        # The engine journaled a complete session; the dialog re-scanned back to idle.
        self.assertTrue(wait_operation(dialog, 'preview'),
                        f'post-manual-edit rescan did not finish (old preview: {old_preview is None})')
        sessions = list_sessions(str(self.library))
        self.assertEqual(len(sessions), 1, f'sessions={sessions}')
        sess = sessions[0]
        self.assertEqual(sess['session_id'], report.session_id)
        self.assertEqual(sess['state'], 'closed', f"session state: {sess}")
        self.assertEqual(sess.get('done_ops'), sess.get('ops'),
                         f"unfinished ops in closed session: {sess}")
        self.assertTrue(sess.get('ops', 0) >= 1, f"no journaled ops recorded: {sess}")

        # Locate the session through the REAL Sessions tab and click the real Undo control.
        table = dialog.sessions_table
        sess_row = session_row(table, report.session_id)  # raises when not listed in the tab
        self.assertGreaterEqual(sess_row, 0)
        table.selectRow(sess_row)
        dialog.undo_button.click()  # 'Undo rename session' Yes|No (default No); responder: Yes
        confirm_undo = self.responder.box_with('Undo rename session')
        self.assertIsNotNone(confirm_undo, f'missing the undo-confirmation box: {self.responder.boxes}')
        self.assertEqual(confirm_undo['chosen'], 'Yes', 'undo must be confirmed explicitly')

        self.assertTrue(wait_operation(dialog, 'undo_report'), 'GUI undo did not finish')
        wait_no_visible_boxes(8000)  # drain the 'Rename undo result' box
        self.assertIsNotNone(self.responder.box_with('Rename undo result'),
                             f'missing the undo result box: {self.responder.boxes}')

        undo = dialog.undo_report
        self.assertEqual(set(undo.restored), {F4}, f'restored={undo.restored}')
        self.assertEqual(tuple(undo.anomalies), (), f'anomalies={undo.anomalies}')

        # Exact original filename, bytes AND modification time restored (journal excluded).
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library), label='after GUI undo')
        self.assertTrue((self.library / F4).is_file(), 'original filename not restored by GUI undo')
        self.assertFalse((self.library / self.NEW_NAME).exists())
        self.assertEqual((self.library / F4).read_bytes(), self.orig_f4_bytes,
                         'undo did not restore the exact original bytes')

        sessions_after = {s['session_id']: s for s in list_sessions(str(self.library))}
        self.assertEqual(sessions_after[report.session_id]['state'], 'undone',
                         'the session must end terminal-undone after a byte-exact GUI undo')


if __name__ == '__main__':
    unittest.main()
