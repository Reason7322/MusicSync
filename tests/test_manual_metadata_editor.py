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


if __name__ == '__main__':
    unittest.main()
