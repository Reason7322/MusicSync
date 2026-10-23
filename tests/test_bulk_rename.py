"""End-to-end GUI tests for Settings -> Bulk Rename (preview/select/apply/undo).

Drives the real BulkRenameDialog on top of the vendored engine with synthetic
silent MP3 fixtures built in a tempdir per test. Qt runs offscreen; no phone,
no rsync, no network. A message-box auto-responder is installed only here so
the confirmation workflow (which requires an explicit Yes) can be exercised
deterministically without a human.
"""
import faulthandler
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

# Shared offscreen application; must be imported before any widget use.
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtCore import QObject, QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QHeaderView, QMessageBox  # noqa: E402

from test_process import APP  # shared offscreen QApplication (imports first)

import musicsync.bulk_rename as bulk_rename_module  # noqa: E402
from musicsync.bulk_rename import BulkRenameDialog  # noqa: E402
from musicsync.settings import Settings, config_dir  # noqa: E402
from musicsync.vendored.engine import list_sessions  # noqa: E402
from musicsync.vendored.tags import read_tag_snapshot  # noqa: E402

JOURNAL_DIR = '.musicsyncrename'


# ---------------------------------------------------------------------------
# Synthetic MP3 fixtures (silent frames; tags via mutagen, host install)
# ---------------------------------------------------------------------------

def _mpeg_frame() -> bytes:
    return b'\xff\xfb\x90\xc0' + b'\x00' * 413


def build_mp3(path, frames: int = 8):
    with open(str(path), 'wb') as handle:
        for _ in range(frames):
            handle.write(_mpeg_frame())
    return str(path)


def set_tags(path, *, artist=None, title=None, extra=()):
    from mutagen.id3 import ID3, TIT2, TPE1
    from mutagen.mp3 import MP3

    audio = MP3(str(path))
    if not isinstance(audio.tags, ID3):
        audio.add_tags()
    tags = audio.tags
    for frame in extra:
        tags.add(frame)
    for frame_id, value in (('TPE1', artist), ('TIT2', title)):
        for key in list(tags.keys()):
            if key == frame_id or key.startswith(frame_id + ':'):
                del tags[key]
        if value is not None:
            cls = {'TPE1': TPE1, 'TIT2': TIT2}[frame_id]
            tags.add(cls(encoding=3, text=[value]))
    audio.save()


# Fixture identity facts (single source of truth for the assertions below).
F1 = 'untagged junk 1.mp3'          # ok: rename + TIT2 tag edit
F2 = 'song_b.mp3'                   # ok: rename only
F3 = 'Clean Duo - Same Name.mp3'    # no_change (name already matches tags)
F4 = 'one - two - three.mp3'        # ambiguous: multiple_separators, no ID3
F5 = 'broken.mp3'                   # error: parse_error
TWIN_A, TWIN_B = 'twin-a.mp3', 'twin-b.mp3'   # ok but proposed_vs_proposed collision
F8 = 'later-modified.mp3'           # ok; mutated after preview in one scenario

APPROVABLE_RELS = {F1, F2, TWIN_A, TWIN_B, F8}  # checkbox-eligible after a scan
EXPECTED_PROPOSALS = {
    F1: 'Junk Artist - Dream On.mp3',
    F2: 'Clean Band - Pure Title.mp3',
    TWIN_A: 'Twin Act - Same Song.mp3',
    TWIN_B: 'Twin Act - Same Song.mp3',
    F8: 'Late Band - Slow Burn.mp3',
}


def build_library(root: Path):
    """The deterministic eight-file fixture (PROJECT_STATUS.md design)."""
    from mutagen.id3 import TALB, TXXX

    build_mp3(root / F1)
    set_tags(root / F1, artist='Junk Artist', title='Dream On (Official HD Video)',
             extra=(TALB(encoding=3, text=['Toys in the Attic']),
                    TXXX(encoding=3, desc='REPLAYGAIN_TRACK_GAIN', text=['-8.2 dB'])))
    build_mp3(root / F2)
    set_tags(root / F2, artist='Clean Band', title='Pure Title')
    build_mp3(root / F3)
    set_tags(root / F3, artist='Clean Duo', title='Same Name')
    build_mp3(root / F4)  # no ID3 at all: filename-derived review only
    (root / F5).write_bytes(b'NOTMP3JUNKDATA' * 24)
    build_mp3(root / TWIN_A)
    set_tags(root / TWIN_A, artist='Twin Act', title='Same Song')
    build_mp3(root / TWIN_B)
    set_tags(root / TWIN_B, artist='Twin Act', title='Same Song')
    build_mp3(root / F8)
    set_tags(root / F8, artist='Late Band', title='Slow Burn')


# ---------------------------------------------------------------------------
# Synthetic session-journal fixtures (Mission 20 sessions-table tests)
# Engine journal format: one JSON object per line under .musicsyncrename/sessions/
# ---------------------------------------------------------------------------

def journals_dir(library: Path):
    return library / JOURNAL_DIR / 'sessions'


def make_journal(sessions_dir, session_id, *, started=None, terminal='closed', ops=0, done=None):
    """Write one minimal valid engine-format journal file.

    ``started`` is written verbatim into the header (Z-suffixed ISO UTC for a
    real timestamp; None omits the key entirely - the missing-stamp case).
    ``terminal`` in {'closed','aborted','undone'} or None for a crash-shaped
    open journal. Returns the session id."""
    lines = []
    header = {'type': 'header', 'id': session_id, 'root': str(sessions_dir)}
    if started is not None:
        header['started'] = started
    lines.append(json.dumps(header))
    for index in range(ops):
        lines.append(json.dumps({'type': 'op', 'index': index, 'rel': 'fixture.mp3'}))
    if done is None:
        done = ops
    for index in range(done):
        lines.append(json.dumps({'type': 'done', 'index': index}))
    if terminal is not None:
        lines.append(json.dumps({'type': terminal}))
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / f'{session_id}.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return session_id


def make_corrupt_journal(sessions_dir, session_id):
    """A journal the engine cannot parse: surfaced as corrupt=True."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / f'{session_id}.jsonl').write_text('not json at all\n{broken line', encoding='utf-8')
    return session_id


# ---------------------------------------------------------------------------
# Qt helpers
# ---------------------------------------------------------------------------

class BoxAutoResponder(QObject):
    """Closes every QMessageBox shown while running, recording each one.

    Implemented as a short-interval GUI-thread timer instead of an event
    filter on show events: top-level windows receive different show-related
    event types depending on Qt build/platform (and some enum members are not
    even bound in PySide6), so polling visible boxes is the portable way to do
    this. The timer's timeout is processed by ANY active event loop - including
    the nested exec() loops of the modal boxes themselves.

    Default choice is Yes (apply/undo confirmation) or Ok (result boxes),
    falling back to the box's first visible button for unknown shapes. Titles
    in ``reject_titles`` are answered with No instead - used to test that a
    declined confirmation applies nothing.
    """

    def __init__(self, interval_ms: int = 25):
        super().__init__()
        self.boxes = []           # [{'title','text','chosen'}]
        self.reject_titles = set()
        self._handled = set()     # ids of boxes already recorded and clicked
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.scan_and_respond)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def scan_and_respond(self):
        for obj in APP.allWidgets():
            try:
                if not isinstance(obj, QMessageBox) or id(obj) in self._handled \
                        or not obj.isVisible():
                    continue
                title = obj.windowTitle()
                target = None
                chosen = ''
                if title in self.reject_titles:
                    for standard in (QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.Cancel):
                        button = obj.button(standard)
                        if button is not None and button.isVisible():
                            target, chosen = button, 'No'
                            break
                if target is None:
                    for standard in (QMessageBox.StandardButton.Yes,
                                     QMessageBox.StandardButton.Ok):
                        button = obj.button(standard)
                        if button is not None and button.isVisible():
                            target = button
                            chosen = 'Yes' if standard == QMessageBox.StandardButton.Yes else 'Ok'
                            break
                if target is None:  # unknown box shape: first visible button wins
                    buttons = [b for b in obj.buttons() if b.isVisible()]
                    if buttons:
                        target, chosen = buttons[0], (buttons[0].text() or '?').strip()
                self._handled.add(id(obj))
                self.boxes.append({'title': title, 'text': obj.text()[:500], 'chosen': chosen})
                if target is not None:
                    target.click()
            except RuntimeError:  # C++ object deleted mid-iteration
                continue

    def titles(self):
        return [box['title'] for box in self.boxes]

    def box_with(self, substring):
        return next((b for b in self.boxes if substring in b['title']), None)


def pump_until(condition, timeout_ms=30000):
    """Pump the shared event loop until ``condition()`` is truthy or deadline."""
    loop = QEventLoop()
    state = {'ok': False}
    deadline = time.monotonic() + timeout_ms / 1000.0

    def tick():
        if not state['ok']:
            try:
                state['ok'] = bool(condition())
            except Exception:
                pass
        if state['ok'] or time.monotonic() > deadline:
            loop.quit()

    timer = QTimer()
    timer.setInterval(25)
    timer.timeout.connect(tick)
    tick()  # short-circuit when already true without entering the loop
    guard = None
    if not state['ok'] and time.monotonic() <= deadline:
        guard = QTimer()
        guard.setSingleShot(True)
        guard.start(timeout_ms + 5000)
        guard.timeout.connect(loop.quit)
        timer.start()
        loop.exec()
    timer.stop()
    if guard is not None:
        guard.stop()
    return state['ok']


def wait_idle(dialog, timeout_ms=30000):
    return pump_until(lambda: not dialog.busy, timeout_ms)


def wait_operation(dialog, attr, timeout_ms=30000):
    """Wait until ``dialog.attr`` is a NEW object (operation finished) and the
    follow-up re-scan has returned to idle."""
    old = getattr(dialog, attr)

    def condition():
        return getattr(dialog, attr) is not old and not dialog.busy

    return pump_until(condition, timeout_ms)


# ---------------------------------------------------------------------------
# Filesystem snapshot helpers (byte-exact, mtime-aware)
# ---------------------------------------------------------------------------

def snapshot_tree(root: Path):
    out = {}
    for dirpath, _dirnames, filenames in os.walk(str(root)):
        rel_dir = os.path.relpath(dirpath, str(root))
        rel_dir = '' if rel_dir == '.' else rel_dir.replace(os.sep, '/')
        for name in sorted(filenames):
            path = Path(dirpath) / name
            data = path.read_bytes()
            stat_result = os.lstat(path)
            rel = f'{rel_dir}/{name}' if rel_dir else name
            out[rel] = (hashlib.sha256(data).hexdigest(), len(data),
                        int(stat_result.st_mtime_ns))
    return out


def assert_same_tree(testcase, before, after, *, include_mtimes=True, label=''):
    """Compare two snapshots; journal content (.musicsyncrename/) is excluded
    by design (journals/backups are preserved for audit after undo)."""
    prefix = JOURNAL_DIR + '/'
    a = {k: v for k, v in before.items() if not k.startswith(prefix)}
    b = {k: v for k, v in after.items() if not k.startswith(prefix)}
    testcase.assertEqual(sorted(a), sorted(b), f'missing/extra files ({label})')
    for rel in a:
        if include_mtimes:
            testcase.assertEqual(a[rel], b[rel], f'content/mtime differs for {rel} ({label})')
        else:
            testcase.assertEqual(a[rel][:2], b[rel][:2], f'bytes differ for {rel} ({label})')


def find_row(dialog, rel):
    table = dialog.preview_table
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is not None and str(item.data(Qt.ItemDataRole.UserRole)) == rel:
            return row
    raise AssertionError(f'row for {rel!r} not found in preview table')


def check_all_checkable(dialog):
    """Re-check every approvable row (table state resets after each re-scan)."""
    table = dialog.preview_table
    checked = []
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is not None and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            item.setCheckState(Qt.CheckState.Checked)
            checked.append(str(item.data(Qt.ItemDataRole.UserRole)))
    return set(checked)


def session_row(table, session_id):
    """Find a Sessions-tab row by its REAL engine session id (Mission 20).

    The visible cell holds a sequential display number; the actual session id
    is stored as item data on column 0."""
    for row in range(table.rowCount()):
        cell = table.item(row, 0)
        if cell is not None and str(cell.data(Qt.ItemDataRole.UserRole)) == str(session_id):
            return row
    raise AssertionError(f'session {session_id!r} not listed in Sessions tab')


def session_number(table, number):
    """Find a Sessions-tab row by its visible 1-based display number."""
    wanted = str(number)
    for row in range(table.rowCount()):
        cell = table.item(row, 0)
        if cell is not None and str(cell.text()) == wanted:
            return row
    raise AssertionError(f'session number {wanted!r} not listed in Sessions tab')


def session_row_id(table, row):
    """The real engine session id stored on a Sessions-tab row."""
    cell = table.item(row, 0)
    if cell is None:
        return ''
    return str(cell.data(Qt.ItemDataRole.UserRole))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class BulkRenameDialogTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory(prefix='musicsync-bulkrename-')
        self.library = Path(self._tempdir.name) / 'library'
        self.library.mkdir()
        build_library(self.library)
        self.pre_snapshot = snapshot_tree(self.library)
        self.responder = BoxAutoResponder()
        self.responder.start()
        self.dialog = None

    def tearDown(self):
        if self.dialog is not None:
            try:
                wait_idle(self.dialog, 10000)
                self.dialog.close()
            except Exception:
                pass
        self.responder.stop()
        self._tempdir.cleanup()

    def open_dialog(self):
        self.dialog = BulkRenameDialog(str(self.library), None)
        return self.dialog

    # 1 ------------------------------------------------------------------

    def test_preview_is_read_only_with_deterministic_statuses_and_no_default_approval(self):
        dialog = self.open_dialog()
        self.assertTrue(wait_idle(dialog), 'initial scan did not finish')

        preview = dialog.preview
        self.assertIsNotNone(preview)
        counts = dict(preview.counts_by_status)
        self.assertEqual(counts.get('ok', 0), 5, f'statuses: {counts}')
        self.assertEqual(counts.get('no_change', 0), 1, f'statuses: {counts}')
        self.assertEqual(counts.get('ambiguous', 0), 1, f'statuses: {counts}')
        self.assertEqual(counts.get('error', 0), 1, f'statuses: {counts}')
        self.assertEqual(preview.item_count, 8)

        items = {item.rel_path: item for item in preview.items}
        # Reasons/details are surfaced per row.
        self.assertEqual(items[F4].status, 'ambiguous')
        self.assertIn('multiple_separators', [f.code for f in items[F4].flags])
        self.assertEqual(items[F5].status, 'error')
        self.assertIn('parse_error', [r.code for r in items[F5].reasons])
        self.assertEqual(items[F3].status, 'no_change')
        for rel, proposed in EXPECTED_PROPOSALS.items():
            self.assertEqual(items[rel].proposed_name, proposed, f'{rel} proposal')
        # The title junk removal is reported as a tag edit with old and new text.
        self.assertIn(('TIT2', 'Dream On (Official HD Video)', 'Dream On'), items[F1].tag_edits)

        # Collision: twins propose the same normalized name.
        self.assertEqual(len(preview.collisions), 1)
        collision = preview.collisions[0]
        self.assertEqual(collision.kind, 'proposed_vs_proposed')
        self.assertEqual(set(collision.involved), {TWIN_A, TWIN_B})
        for rel in (TWIN_A, TWIN_B):
            self.assertIn('preview_collision', [f.code for f in items[rel].flags])
        self.assertTrue(dialog.collisions_label.text().strip(), 'collision label empty')

        # Defaults: nothing approved; unapprovable rows are not checkable.
        self.assertEqual(dialog._checked_rels(), [])
        for rel, checkable in ((F1, True), (TWIN_A, True), (F3, False), (F4, False), (F5, False)):
            item = dialog.preview_table.item(find_row(dialog, rel), 0)
            self.assertEqual(bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable), checkable,
                             f'{rel} checkability')

        # Read-only proof: bytes AND mtimes unchanged; no journal created.
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library),
                         label='after read-only preview')
        self.assertFalse((self.library / JOURNAL_DIR).exists(), 'preview created a journal dir')

    # 2 ------------------------------------------------------------------

    def test_apply_with_nothing_approved_is_a_noop(self):
        dialog = self.open_dialog()
        self.assertTrue(wait_idle(dialog))
        dialog.apply_button.click()   # real button path; expect the info box only
        self.assertTrue(pump_until(lambda: 'Nothing approved' in self.responder.titles(), 5000),
                        f'missing Nothing-approved box: {self.responder.boxes}')
        self.assertFalse(dialog.busy, 'a worker started although nothing was approved')
        self.assertIsNone(dialog.report, 'a report exists although nothing was approved')
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library),
                         label='after no-op apply')
        self.assertEqual(list_sessions(str(self.library)), [])
        self.assertNotIn('Rename apply result', self.responder.titles())

    # 3 ------------------------------------------------------------------

    def test_select_apply_verify_undo_restores_bytes_exactly(self):
        dialog = self.open_dialog()
        self.assertTrue(wait_idle(dialog), 'initial scan did not finish')
        orig_f1 = (self.library / F1).read_bytes()  # audio-tail reference for f1

        dialog.select_all_button.click()
        self.assertEqual(set(dialog._checked_rels()), set(APPROVABLE_RELS))

        # Real user path: the Apply button, then an explicit Yes.
        dialog.apply_button.click()
        confirm = self.responder.box_with('Apply bulk rename')
        self.assertIsNotNone(confirm, f'no confirmation box raised: {self.responder.boxes}')
        self.assertEqual(confirm['chosen'], 'Yes', 'confirmation must require an explicit Yes')

        self.assertTrue(wait_operation(dialog, 'report'), 'apply report missing or stuck busy')
        report = dialog.report

        # Partition accuracy: twins collide at apply time; f1/f2/f8 apply.
        applied = dict(report.applied)
        self.assertEqual(set(applied), {F1, F2, F8}, f'applied={report.applied}')
        for rel in (F1, F2, F8):
            self.assertEqual(applied[rel], EXPECTED_PROPOSALS[rel])
        rejected = dict(report.rejected)
        self.assertEqual(rejected.get(TWIN_A), 'proposal_collision')
        self.assertEqual(rejected.get(TWIN_B), 'proposal_collision')
        self.assertEqual(len(report.partial), 0, f'partial: {report.partial}')
        self.assertEqual(len(report.canceled), 0, f'canceled: {report.canceled}')
        self.assertTrue(report.session_id)

        # On-disk state after apply. f1 also received its TIT2 tag edit, so its
        # ID3 area legitimately differs from the original; audio frames intact.
        new_f1 = self.library / EXPECTED_PROPOSALS[F1]
        self.assertTrue(new_f1.is_file(), 'f1 not renamed on disk')
        self.assertTrue(
            new_f1.read_bytes().endswith(orig_f1[-8 * len(_mpeg_frame()):]),
            'f1 audio frames changed by rename/tag edit')
        snapshot = read_tag_snapshot(new_f1)
        self.assertEqual(snapshot.titles, ('Dream On',), 'TIT2 not cleaned on disk')
        self.assertEqual(snapshot.artists, ('Junk Artist',))
        self.assertIn('TXXX:REPLAYGAIN_TRACK_GAIN', snapshot.replaygain_keys,
                      'ReplayGain TXXX frame lost by tag edit')
        for rel in (F2, F8):
            self.assertTrue((self.library / EXPECTED_PROPOSALS[rel]).is_file())
            self.assertFalse((self.library / rel).exists(), f'{rel} still present after apply')
        mid = snapshot_tree(self.library)
        for rel in (TWIN_A, TWIN_B):
            self.assertEqual(mid[rel][0], self.pre_snapshot[rel][0])

        # Journal: one closed session covering all journaled steps
        # (f1 = rename + tag_edit, f2/f8 = renames).
        sessions = list_sessions(str(self.library))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['session_id'], report.session_id)
        self.assertEqual(sessions[0]['state'], 'closed')
        self.assertEqual((sessions[0]['done_ops'], sessions[0]['ops']), (4, 4))

        # Undo the exact session through the Sessions tab UI path.
        table = dialog.sessions_table
        table.selectRow(session_row(table, report.session_id))
        dialog.undo_button.click()
        confirm_undo = self.responder.box_with('Undo rename session')
        self.assertEqual(confirm_undo['chosen'], 'Yes', 'undo confirmation must require a Yes')
        self.assertTrue(wait_operation(dialog, 'undo_report'), 'undo did not finish')

        undo = dialog.undo_report
        self.assertEqual(set(undo.restored), {F1, F2, F8})
        self.assertEqual(len(undo.anomalies), 0, f'anomalies: {undo.anomalies}')

        # Byte-exact restore of names AND bytes (mtimes via rename/copy2).
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library), label='after undo')
        restored_f1 = read_tag_snapshot(self.library / F1)
        self.assertEqual(restored_f1.titles, ('Dream On (Official HD Video)',),
                         'original tag bytes not restored after undo')

        # Session state is now terminal-undone; a repeated undo restores nothing.
        sessions_after = {s['session_id']: s for s in list_sessions(str(self.library))}
        self.assertEqual(sessions_after[report.session_id]['state'], 'undone')
        before_repeat = snapshot_tree(self.library)
        dialog.begin_undo(report.session_id)   # explicit post-confirmation seam
        self.assertTrue(wait_operation(dialog, 'undo_report'), 'repeat undo did not finish')
        self.assertEqual(tuple(dialog.undo_report.restored), (), 'repeat undo touched files')
        assert_same_tree(self, before_repeat, snapshot_tree(self.library), label='after repeat undo')

    # 4 ------------------------------------------------------------------

    def test_declined_confirmation_applies_nothing(self):
        dialog = self.open_dialog()
        self.assertTrue(wait_idle(dialog))
        dialog.select_all_button.click()
        self.responder.reject_titles.add('Apply bulk rename')
        dialog.apply_button.click()
        confirm = self.responder.box_with('Apply bulk rename')
        self.assertIsNotNone(confirm, f'boxes: {self.responder.boxes}')
        self.assertEqual(confirm['chosen'], 'No', 'test intent: decline the confirmation')
        self.assertFalse(dialog.busy)
        self.assertIsNone(dialog.report, 'declined confirmation still applied changes')
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library),
                         label='after declined apply')
        self.assertEqual(list_sessions(str(self.library)), [])

    # 5 ------------------------------------------------------------------

    def test_mid_apply_cancellation_keeps_files_and_aborted_session_is_recoverable(self):
        dialog = self.open_dialog()
        self.assertTrue(wait_idle(dialog))
        dialog.select_all_button.click()
        checked = list(set(dialog._checked_rels()))
        self.assertEqual(set(checked), set(APPROVABLE_RELS))

        # Deterministic mid-apply stop: the worker starts already told to cancel.
        real_worker = bulk_rename_module.RenameWorker

        class CancelingWorker(real_worker):
            def start(self):
                self.cancel_requested = True
                super().start()

        with mock.patch.object(bulk_rename_module, 'RenameWorker', CancelingWorker):
            dialog.begin_apply(checked)
        self.assertTrue(wait_operation(dialog, 'report'), 'canceled apply did not finish')
        report = dialog.report

        # Canceled before any step: nothing mutated, but the aborted journal exists.
        self.assertEqual(set(report.canceled), {F1, F2, F8}, f'canceled={report.canceled}')
        rejected = dict(report.rejected)
        self.assertEqual(rejected.get(TWIN_A), 'proposal_collision')
        self.assertEqual(rejected.get(TWIN_B), 'proposal_collision')
        self.assertEqual(len(report.applied), 0, f'applied on cancel: {report.applied}')
        self.assertEqual(len(report.partial), 0, f'partial on cancel: {report.partial}')
        self.assertTrue(report.session_id)
        mid = snapshot_tree(self.library)
        assert_same_tree(self, self.pre_snapshot, mid, label='after canceled apply')

        sessions = list_sessions(str(self.library))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['state'], 'aborted', f'sessions={sessions}')

        # A new apply must be refused while the aborted session is unresolved.
        self.assertEqual(check_all_checkable(dialog), set(APPROVABLE_RELS))
        self.responder.boxes.clear()
        stale_report = dialog.report
        dialog.apply_button.click()   # auto-Yes, then the engine refuses
        self.assertTrue(pump_until(lambda: 'Bulk rename apply failed' in self.responder.titles(), 30000),
                        f'unresolved-session refusal not surfaced: {self.responder.boxes}')
        wait_idle(dialog)
        box = self.responder.box_with('Bulk rename apply failed')
        self.assertIn(report.session_id, box['text'], 'error must name the blocking session')
        self.assertIs(dialog.report, stale_report, 'refused apply overwrote the previous report')
        assert_same_tree(self, mid, snapshot_tree(self.library), label='after refused apply')

        # Undoing the aborted (header-only) session frees the library again.
        sessions_table = dialog.sessions_table
        sessions_table.selectRow(session_row(sessions_table, report.session_id))
        dialog.undo_button.click()
        self.assertTrue(wait_operation(dialog, 'undo_report'), 'abort-session undo did not finish')
        self.assertEqual(tuple(dialog.undo_report.restored), (), 'no files expected to restore')
        states = {s['session_id']: s.get('state') for s in list_sessions(str(self.library))}
        self.assertEqual(states[report.session_id], 'undone')
        assert_same_tree(self, mid, snapshot_tree(self.library), label='after abort undo')

    # 6 ------------------------------------------------------------------

    def test_file_changed_after_preview_is_rejected_while_others_apply(self):
        dialog = self.open_dialog()
        self.assertTrue(wait_idle(dialog))
        orig_f1 = (self.library / F1).read_bytes()  # audio-tail reference for f1

        # Mutate f8 after the scan but before apply (size + mtime both change).
        with open(self.library / F8, 'ab') as handle:
            handle.write(_mpeg_frame())
        mid = snapshot_tree(self.library)   # expected final state: f8 stays mutated

        dialog.select_all_button.click()
        self.assertIn(F8, set(dialog._checked_rels()), 'f8 must still be checkable from stale row')
        dialog.apply_button.click()
        self.assertTrue(wait_operation(dialog, 'report'), 'apply did not finish')
        report = dialog.report

        rejected = dict(report.rejected)
        self.assertEqual(rejected.get(F8), 'changed_since_preview', f'rejected={rejected}')
        applied = dict(report.applied)
        self.assertIn(F1, applied)
        self.assertIn(F2, applied)
        for rel in (TWIN_A, TWIN_B):
            self.assertEqual(rejected.get(rel), 'proposal_collision')
        self.assertNotIn(F8, applied, f'f8 must not apply after preview change: {report.applied}')
        self.assertTrue(report.session_id)

        # f8 stays in its mutated form; the rename-only file keeps exact bytes,
        # and f1's tag edit touches only its ID3 area.
        post = snapshot_tree(self.library)
        self.assertEqual(post[F8], mid[F8], 'f8 bytes changed despite rejection')
        for rel in (F1, F2):
            self.assertTrue((self.library / EXPECTED_PROPOSALS[rel]).is_file())
        f2_new = (self.library / EXPECTED_PROPOSALS[F2]).read_bytes()
        self.assertEqual(hashlib.sha256(f2_new).hexdigest(), mid[F2][0],
                         'rename-only file changed bytes')
        snap_f1 = read_tag_snapshot(self.library / EXPECTED_PROPOSALS[F1])
        self.assertEqual(snap_f1.titles, ('Dream On',), 'TIT2 not cleaned on disk')
        self.assertEqual(snap_f1.artists, ('Junk Artist',))
        self.assertTrue(
            (self.library / EXPECTED_PROPOSALS[F1]).read_bytes().endswith(
                orig_f1[-8 * len(_mpeg_frame()):]),
            'f1 audio frames changed by rename/tag edit')

        # Undo brings f1/f2 back; f8 stays in its mutated (pre-apply) state.
        sessions = list_sessions(str(self.library))
        self.assertEqual(len(sessions), 1)
        table = dialog.sessions_table
        table.selectRow(session_row(table, report.session_id))
        dialog.undo_button.click()
        self.assertTrue(wait_operation(dialog, 'undo_report'), 'undo did not finish')
        self.assertEqual(set(dialog.undo_report.restored), {F1, F2})
        assert_same_tree(self, mid, snapshot_tree(self.library), label='after undo with stale f8')

    # 7 ------------------------------------------------------------------

    def test_collision_pair_rejected_together_but_single_side_applies(self):
        root = Path(tempfile.mkdtemp(prefix='musicsync-twins-'))
        try:
            build_mp3(root / TWIN_A)
            set_tags(root / TWIN_A, artist='Twin Act', title='Same Song')
            build_mp3(root / TWIN_B)
            set_tags(root / TWIN_B, artist='Twin Act', title='Same Song')
            pre = snapshot_tree(root)

            self.dialog = BulkRenameDialog(str(root), None)
            dialog = self.dialog
            self.assertTrue(wait_idle(dialog))

            # Both approved -> both rejected; nothing passed validation so no journal.
            dialog.select_all_button.click()
            dialog.apply_button.click()
            self.assertTrue(wait_operation(dialog, 'report'), 'apply did not finish')
            report = dialog.report
            self.assertEqual(dict(report.rejected),
                             {TWIN_A: 'proposal_collision', TWIN_B: 'proposal_collision'})
            self.assertEqual(len(report.applied), 0)
            self.assertEqual(report.session_id, '', 'no journal expected when nothing applied')
            self.assertFalse((root / JOURNAL_DIR).exists(), 'journal dir created for no-op apply')
            assert_same_tree(self, pre, snapshot_tree(root), label='after rejected collision apply')

            # One side only -> the target slot is free; that file renames.
            # The re-scan after an operation resets checkbox state, so select again.
            row_a = find_row(dialog, TWIN_A)
            dialog.preview_table.item(row_a, 0).setCheckState(Qt.CheckState.Checked)
            self.assertEqual(set(dialog._checked_rels()), {TWIN_A})
            dialog.apply_button.click()
            self.assertTrue(wait_operation(dialog, 'report'), 'second apply did not finish')
            report = dialog.report
            applied = dict(report.applied)
            self.assertEqual(applied.get(TWIN_A), 'Twin Act - Same Song.mp3')
            self.assertFalse((root / TWIN_A).exists())
            target = root / 'Twin Act - Same Song.mp3'
            self.assertTrue(target.is_file())
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), pre[TWIN_A][0])

            # Undo restores the original name and bytes.
            sessions_table = dialog.sessions_table
            sessions_table.selectRow(session_row(sessions_table, report.session_id))
            dialog.undo_button.click()
            self.assertTrue(wait_operation(dialog, 'undo_report'), 'undo did not finish')
            assert_same_tree(self, pre, snapshot_tree(root), label='after undo single twin')
        finally:
            shutil.rmtree(str(root), ignore_errors=True)

    # 8 ------------------------------------------------------------------

    def test_programmatic_approval_of_ambiguous_row_is_rejected(self):
        dialog = self.open_dialog()
        self.assertTrue(wait_idle(dialog))
        dialog.begin_apply([F4])   # bypasses the checkbox; engine must still refuse
        self.assertTrue(wait_operation(dialog, 'report'), 'apply did not finish')
        report = dialog.report
        self.assertEqual(dict(report.rejected), {F4: 'status_ambiguous_not_applicable'}, f'{report}')
        self.assertEqual(len(report.applied), 0)
        self.assertEqual(len(report.partial), 0)
        self.assertEqual(len(report.canceled), 0)
        self.assertEqual(report.session_id, '')
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library),
                         label='after ambiguous apply')

    # 9 ------------------------------------------------------------------

    def test_unresolved_crash_journal_blocks_apply_and_undo_recovers_it(self):
        crash_id = 'deadbeef' * 4
        journal_dir = self.library / JOURNAL_DIR / 'sessions'
        journal_dir.mkdir(parents=True)
        (journal_dir / f'{crash_id}.jsonl').write_text(
            '{"type": "header", "id": "%s", "root": "%s", "started": "2026-10-16T00:00:00Z"}\n'
            % (crash_id, str(self.library)), encoding='utf-8')

        dialog = self.open_dialog()
        self.assertTrue(wait_idle(dialog))

        # The unresolved session is visible in the Sessions tab (never hidden),
        # numbered like every other row and mapped to its real journal id.
        sessions_table = dialog.sessions_table
        crash_row = session_row(sessions_table, crash_id)  # raises when not listed
        self.assertEqual(session_number(sessions_table, 1), crash_row, 'only session must be numbered 1')
        self.assertEqual(str(sessions_table.item(crash_row, 2).text()), '❌ Incomplete')

        # A new apply is refused while it exists.
        dialog.select_all_button.click()
        dialog.apply_button.click()
        self.assertTrue(pump_until(lambda: 'Bulk rename apply failed' in self.responder.titles(), 30000),
                        f'crash-journal refusal not surfaced: {self.responder.boxes}')
        box = self.responder.box_with('Bulk rename apply failed')
        self.assertIn(crash_id, box['text'])
        self.assertIsNone(dialog.report)
        wait_idle(dialog)
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library), label='after refused apply')

        # Undo the crash journal: no ops recorded -> nothing to restore; terminal.
        sessions_table.selectRow(crash_row)
        dialog.undo_button.click()
        self.assertTrue(wait_operation(dialog, 'undo_report'), 'crash-session undo did not finish')
        self.assertEqual(tuple(dialog.undo_report.restored), ())
        states = {s['session_id']: s.get('state') for s in list_sessions(str(self.library))}
        self.assertEqual(states[crash_id], 'undone')

        # The library is now free: the same selection applies cleanly.
        wait_idle(dialog)
        self.assertEqual(check_all_checkable(dialog), set(APPROVABLE_RELS))
        dialog.apply_button.click()
        self.assertTrue(wait_operation(dialog, 'report'), 'post-recovery apply did not finish')
        applied = dict(dialog.report.applied)
        self.assertEqual(set(applied), {F1, F2, F8})

    # 10 -----------------------------------------------------------------

    def test_busy_guard_blocks_overlapping_operations(self):
        dialog = self.open_dialog()
        # The initial scan is running right after construction (queued signal).
        self.assertTrue(dialog.busy)
        worker = dialog._active_worker
        self.assertIsNotNone(worker)
        dialog.begin_apply(['song_b.mp3'])     # refused: a worker owns the engine
        self.assertIs(dialog._active_worker, worker, 'overlap guard let a second op start')
        dialog.preview_button.click()          # same guard on re-scan
        self.assertIs(dialog._active_worker, worker)
        wait_idle(dialog)

    # 11 -----------------------------------------------------------------

    def test_settings_bulk_rename_save_works_without_configured_phone(self):
        from musicsync.settings_dialog import SettingsDialog

        with tempfile.TemporaryDirectory(prefix='musicsync-cfg-') as cfg_home:
            settings = Settings(source=str(self.library), device_id='', device_name='')
            self.assertFalse(settings.configured)
            dialog = None
            with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(cfg_home)}):
                self.assertEqual(config_dir(), Path(cfg_home) / 'musicsync')
                dialog = SettingsDialog(settings, [], None)
                self.assertTrue(dialog.bulk_rename_button.isEnabled())
                dialog.bulk_rename_button.click()

            # Phone-independent save: accepted with first-run-level validation.
            self.assertTrue(dialog.bulk_rename_requested)
            self.assertIsNotNone(dialog.value)
            self.assertEqual(dialog.value.source, str(self.library))
            self.assertFalse(dialog.value.configured, 'test must not configure a phone')
            saved = Path(cfg_home) / 'musicsync' / 'settings.json'
            data = json.loads(saved.read_text())
            self.assertEqual(data['source'], str(self.library))
            self.assertEqual(data['device_id'], '')


class ResponderBoxHandlingTests(unittest.TestCase):
    """Focused BoxAutoResponder coverage for production box shapes (offscreen).

    The dialog is never .show()ed here - exactly like the rest of this suite -
    so every box is parented to a hidden top-level window, which is the shape
    BoxAutoResponder must reliably dismiss. Each blocking interaction runs under
    a bounded watchdog: if the responder fails to close a box the process exits
    non-zero with the stuck stack printed instead of hanging indefinitely.
    """

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory(prefix='musicsync-responder-')
        library = Path(self._tempdir.name) / 'library'
        library.mkdir()
        build_library(library)
        self.dialog = BulkRenameDialog(str(library), None)
        self.assertTrue(wait_idle(self.dialog), 'initial scan did not finish')
        self.responder = BoxAutoResponder(interval_ms=25)
        self.responder.start()
        self._watchdog = threading.Timer(20.0, self._hang_failure)
        self._watchdog.daemon = True

    def tearDown(self):
        if getattr(self, '_watchdog', None) is not None:
            self._watchdog.cancel()
        self.responder.stop()
        try:
            if self.dialog is not None:
                self.dialog.close()
        except Exception:  # noqa: BLE001 - teardown must never mask the verdict
            pass
        self._tempdir.cleanup()

    def _hang_failure(self):
        faulthandler.dump_traceback()
        print(f'RESPONDER WATCHDOG TIMEOUT - BoxAutoResponder did not close a box; '
              f'recorded so far: {self.responder.boxes}', flush=True)
        os._exit(2)

    def _confirmation_box(self):
        # Exactly the shape BulkRenameDialog._on_apply builds (default button No).
        box = QMessageBox(self.dialog)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle('Apply bulk rename')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText('Apply 1 selected change(s) to your PC music library?')
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box

    def test_responder_dismisses_info_box_and_yes_no_confirmations(self):
        self._watchdog.start()

        # 1. Informational message box (static convenience shape, the no-approved path).
        QMessageBox.information(
            self.dialog, 'Nothing approved',
            'No changes are currently selected.\n'
            'Tick the "Apply" column for each change you accept; nothing is applied until you confirm.')
        entry = self.responder.box_with('Nothing approved')
        self.assertIsNotNone(entry, f'missing info box record: {self.responder.boxes}')
        self.assertEqual(entry['chosen'], 'Ok', f'info box not dismissed with Ok: {entry}')

        # 2. Yes/No confirmation whose default is No: the responder must pick Yes explicitly.
        code = self._confirmation_box().exec()
        self.assertEqual(code, QMessageBox.StandardButton.Yes)
        entries = [b for b in self.responder.boxes if b['title'] == 'Apply bulk rename']
        self.assertEqual(len(entries), 1, f'confirm box not recorded: {self.responder.boxes}')
        self.assertEqual(entries[0]['chosen'], 'Yes')

        # 3. A deliberately declined confirmation picks No; a repeated title must be
        #    treated as a NEW box, never deduped against the previous one.
        self.responder.reject_titles.add('Apply bulk rename')
        code = self._confirmation_box().exec()
        self.assertEqual(code, QMessageBox.StandardButton.No)
        entries = [b for b in self.responder.boxes if b['title'] == 'Apply bulk rename']
        self.assertEqual(len(entries), 2, f'expected two recorded confirmations: {self.responder.boxes}')
        self.assertEqual([e['chosen'] for e in entries], ['Yes', 'No'])

        # Nothing left busy on the dialog side.
        self.assertFalse(self.dialog.busy)


class SessionTablePresentationTests(unittest.TestCase):
    """Mission 20 focused coverage of the Rename Sessions table (offscreen).

    Numbered rows in true newest-first timestamp order; DD-MM-YYYY | HH:MM local
    timestamps with safe handling of missing/invalid stamps; human state labels
    while the engine's raw values stay intact internally; manually resizable
    columns; and numbered-row -> real session id resolution through the actual
    Undo path. Fixtures are hand-written journal files (established shape, see
    test #9) plus at most one REAL engine apply for the undo-mapping proof."""

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory(prefix='musicsync-sessionsui-')
        self.library = Path(self._tempdir.name) / 'library'
        self.library.mkdir()
        build_library(self.library)
        self.pre_snapshot = snapshot_tree(self.library)
        self.responder = BoxAutoResponder()
        self.responder.start()
        self.dialogs = []
        self._old_tz = os.environ.get('TZ')

    def tearDown(self):
        if self._old_tz is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = self._old_tz
        if hasattr(time, 'tzset'):
            try:
                time.tzset()  # restore the host timezone for later tests
            except Exception:  # noqa: BLE001 - teardown must never mask a verdict
                pass
        for dialog in reversed(self.dialogs):
            try:
                wait_idle(dialog, 10000)
                dialog.close()
            except Exception:  # noqa: BLE001
                pass
        self.responder.stop()
        self._tempdir.cleanup()

    def open_dialog_on(self, library=None):
        dialog = BulkRenameDialog(str(library if library is not None else self.library), None)
        self.dialogs.append(dialog)
        return dialog

    # A ------------------------------------------------------------------

    def test_sessions_sort_newest_first_with_sequential_numbers(self):
        sessions = journals_dir(self.library)
        # Chosen so that neither the engine's name-sorted list order nor its
        # reverse equals the true timestamp order: newest must come from the
        # parsed stamps, not from ids or filenames.
        new_id = make_journal(sessions, 'bbbb11112222333344445555666677aa',
                              started='2026-10-21T06:30:00Z', terminal='aborted', ops=1, done=0)
        mid_id = make_journal(sessions, 'aaaa11112222333344445555666677bb',
                              started='2026-10-20T05:00:00Z', terminal='closed')
        old_id = make_journal(sessions, 'cccc11112222333344445555666677cc',
                              started='2026-10-19T04:15:00Z', terminal='closed')

        dialog = self.open_dialog_on()
        self.assertTrue(wait_idle(dialog), 'initial scan did not finish')

        table = dialog.sessions_table
        self.assertEqual(table.rowCount(), 3)
        # Visible sequential numbers, consistent with displayed order.
        self.assertEqual([str(table.item(row, 0).text()) for row in range(3)], ['1', '2', '3'])
        # Newest first by actual start timestamp (NOT name order [mid,new,old]
        # and NOT its reverse [old,new,mid]).
        ids = [session_row_id(table, row) for row in range(3)]
        self.assertEqual(ids, [new_id, mid_id, old_id])
        self.assertEqual([str(table.item(row, 2).text()) for row in range(3)],
                         ['❌ Failed', '✅ Finished', '✅ Finished'])

        # Original engine values preserved internally.
        raw = {s['session_id']: s.get('state') for s in dialog.sessions}
        self.assertEqual(raw, {new_id: 'aborted', mid_id: 'closed', old_id: 'closed'})
        # Diagnostics: the real identifier stays available via tooltip.
        self.assertIn(new_id, str(table.item(0, 0).toolTip()))
        self.assertIn(mid_id, str(table.item(1, 3).toolTip()))

    # B ------------------------------------------------------------------

    def test_started_column_shows_local_time_dd_mm_yyyy_hh_mm(self):
        stamp_a = '2026-10-19T04:15:00Z'
        id_a = make_journal(journals_dir(self.library),
                            'aaaa00001111222233334444555566ee',
                            started=stamp_a, terminal='closed')

        dialog = self.open_dialog_on()
        self.assertTrue(wait_idle(dialog), 'initial scan did not finish')
        table = dialog.sessions_table
        row = session_row(table, id_a)
        cell_text = str(table.item(row, 1).text())
        # Exact shape plus an independent stdlib UTC->local conversion mirror.
        self.assertRegex(cell_text, r'^\d{2}-\d{2}-\d{4} \| \d{2}:\d{2}$')
        expected_local = datetime.fromisoformat(stamp_a.replace('Z', '+00:00')) \
            .astimezone().strftime('%d-%m-%Y | %H:%M')
        self.assertEqual(cell_text, expected_local)
        self.assertNotEqual(cell_text, stamp_a, 'raw stored string leaked into the table')

        # Phase B: force a known non-UTC offset (UTC+2 via POSIX TZ format; a
        # year-end UTC stamp must roll over to the next local day).
        if not hasattr(time, 'tzset'):  # Linux host assumption of this suite
            self.skipTest('time.tzset unavailable')
        os.environ['TZ'] = 'FOO-2'  # POSIX: negative offset == east of UTC -> UTC+2
        time.tzset()
        try:
            self.assertEqual(time.timezone, -7200, 'phase-B environment must be UTC+2')
            lib2 = Path(self._tempdir.name) / 'library-tz'
            lib2.mkdir()  # empty library: the scan is read-only and trivial here
            stamp_b = '2026-12-31T23:30:00Z'
            id_b = make_journal(journals_dir(lib2),
                                'bbbb00001111222233334444555566ff',
                                started=stamp_b, terminal='closed')
            dialog2 = self.open_dialog_on(lib2)
            self.assertTrue(wait_idle(dialog2), 'initial scan did not finish (tz phase)')
            row_b = session_row(dialog2.sessions_table, id_b)
            cell_b = str(dialog2.sessions_table.item(row_b, 1).text())
            # Hand-computed under UTC+2: 23:30Z + 2h crosses midnight.
            self.assertEqual(cell_b, '01-01-2027 | 01:30')
            self.assertNotEqual(cell_b, '31-12-2026 | 23:30', 'no local conversion happened')
        finally:
            os.environ['TZ'] = self._old_tz if self._old_tz is not None else ''
            time.tzset()

    # C ------------------------------------------------------------------

    def test_all_five_state_presentations_and_corrupt_stays_visible(self):
        sessions = journals_dir(self.library)
        fin_id = make_journal(sessions, 'f1n100000000000000000000000000aa',
                              started='2026-03-01T10:00:00Z', terminal='closed')
        fail_id = make_journal(sessions, 'f4il000000000000000000000000bb',
                               started='2026-03-01T11:00:00Z', terminal='aborted', ops=1, done=0)
        inc_id = make_journal(sessions, 'inc0000000000000000000000000cc',
                              started='2026-03-01T12:00:00Z', terminal=None)  # crash-shaped open
        und_id = make_journal(sessions, 'und0000000000000000000000000dd',
                              started='2026-03-01T13:00:00Z', terminal='undone', ops=1)
        corrupt_id = make_corrupt_journal(sessions, 'corruptjournal00000000000000ee')

        dialog = self.open_dialog_on()
        self.assertTrue(wait_idle(dialog), 'initial scan did not finish')
        table = dialog.sessions_table
        # Nothing is hidden: all five sessions are visible rows.
        self.assertEqual(table.rowCount(), 5)
        # Newest-first by stamp; the corrupt journal (no parseable header at
        # all) remains visible - here with no time, i.e. after timed rows it
        # lands wherever its (absent) timestamp sorts: at the bottom.
        expected_ids = [und_id, inc_id, fail_id, fin_id]  # newest -> oldest among timed
        self.assertEqual([session_row_id(table, r) for r in range(4)], expected_ids)
        self.assertEqual(session_row_id(table, 4), corrupt_id, 'corrupt journal must stay visible')
        self.assertEqual([str(table.item(row, 2).text()) for row in range(5)],
                         ['↩ Undone', '❌ Incomplete', '❌ Failed', '✅ Finished',
                          '❌ Corrupt journal'])
        # Interrupted/undone rows keep their step counters; corrupt shows none.
        self.assertEqual(str(table.item(session_row(table, fail_id), 3).text()), '0/1')
        self.assertEqual(str(table.item(session_row(table, und_id), 3).text()), '1/1')
        self.assertEqual(str(table.item(4, 3).text()), '')
        # Internal engine values are untouched by the presentation layer.
        raw = {s['session_id']: (s.get('state'), bool(s.get('corrupt'))) for s in dialog.sessions}
        self.assertEqual(raw[fin_id], ('closed', False))
        self.assertEqual(raw[fail_id], ('aborted', False))
        self.assertEqual(raw[inc_id], ('open', False))
        self.assertEqual(raw[und_id], ('undone', False))
        self.assertTrue(raw[corrupt_id][1])

        # Recovery semantics unchanged: a corrupt journal is NOT undoable -
        # selecting it must surface the info box and start no worker.
        table.selectRow(session_row(table, corrupt_id))
        dialog.undo_button.click()
        self.assertTrue(pump_until(lambda: 'No undoable session selected' in self.responder.titles(), 5000),
                        f'expected refusal for corrupt journal: {self.responder.boxes}')
        self.assertFalse(dialog.busy)
        self.assertIsNone(dialog.undo_report, 'undo worker started for a corrupt journal')

    # D ------------------------------------------------------------------

    def test_session_and_preview_tables_are_interactively_resizable(self):
        dialog = self.open_dialog_on()
        self.assertTrue(wait_idle(dialog), 'initial scan did not finish')
        table = dialog.sessions_table
        header = table.horizontalHeader()
        labels = []
        for col in range(4):  # horizontalHeaderItem(): QHeaderView.item unbound here
            item = table.horizontalHeaderItem(col)
            labels.append(item.text() if item is not None else '')
        self.assertEqual(labels, ['Session', 'Started (local)', 'State', 'Completed steps'])

        # All four columns: Interactive mode + useful initial widths.
        interactive = QHeaderView.ResizeMode.Interactive
        for col in range(4):
            self.assertEqual(header.sectionResizeMode(col), interactive, f'col {col} not user-resizable')
        self.assertGreaterEqual(table.columnWidth(0), 50)
        self.assertGreaterEqual(table.columnWidth(1), 130)  # full 'DD-MM-YYYY | HH:MM' string
        self.assertGreaterEqual(table.columnWidth(2), 90)
        self.assertGreaterEqual(table.columnWidth(3), 60)

        # Programmatic drag-equivalent resize round-trip on every column.
        for col, new_width in enumerate((96, 210, 88, 74)):
            table.setColumnWidth(col, new_width)
        widths = [table.columnWidth(c) for c in range(4)]
        self.assertEqual(widths, [96, 210, 88, 74], 'manual resize must stick (no forced mode)')

        # The Rename Preview table has the same manual-resize contract:
        # all six columns Interactive with useful initial widths.
        p_table = dialog.preview_table
        p_header = p_table.horizontalHeader()
        p_labels = []
        for col in range(6):  # horizontalHeaderItem(): QHeaderView.item unbound here
            item = p_table.horizontalHeaderItem(col)
            p_labels.append(item.text() if item is not None else '')
        self.assertEqual(p_labels, ['Apply', 'Path', 'Current name', 'Proposed name',
                                    'Status', 'Details'])
        for col in range(6):
            self.assertEqual(p_header.sectionResizeMode(col), interactive,
                             f'preview col {col} not user-resizable')
        # Useful initial widths: no column starts unusably narrow.
        self.assertGreaterEqual(p_table.columnWidth(0), 40)   # Apply checkbox
        for col in range(1, 6):
            self.assertGreaterEqual(p_table.columnWidth(col), 90)

        # Programmatic drag-equivalent resize round-trip on every preview column:
        # each width must stick independently (no forced mode).
        new_widths = [84, 230, 160, 300, 70, 420]
        for col, new_width in enumerate(new_widths):
            p_table.setColumnWidth(col, new_width)
        widths = [p_table.columnWidth(c) for c in range(6)]
        self.assertEqual(widths, new_widths, 'manual resize must stick on all six preview columns')

        # Horizontal scrolling covers what does not fit the dialog.
        self.assertEqual(p_table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    # E ------------------------------------------------------------------

    def test_numbered_rows_resolve_to_real_ids_and_undo_uses_them(self):
        sessions = journals_dir(self.library)
        # Resolved (closed) old session: visible but never blocks a new apply,
        # and it will NOT be undone - only its row-number -> id mapping is used.
        old_id = make_journal(sessions, 'oldd0000000000000000000000000ff',
                              started='1970-01-01T00:00:01Z', terminal='closed', ops=1)

        dialog = self.open_dialog_on()
        self.assertTrue(wait_idle(dialog), 'initial scan did not finish')
        dialog.select_all_button.click()
        dialog.apply_button.click()  # explicit Yes auto-answered by the responder
        self.assertTrue(wait_operation(dialog, 'report'), 'apply report missing or stuck busy')
        report = dialog.report
        self.assertEqual(set(dict(report.applied)), {F1, F2, F8})

        table = dialog.sessions_table
        self.assertEqual(table.rowCount(), 2)
        row_newest = session_number(table, 1)
        row_older = session_number(table, 2)
        # Selecting by visible number must resolve to the correct real ids.
        self.assertEqual(session_row_id(table, row_newest), report.session_id)
        self.assertEqual(session_row_id(table, row_older), old_id)

        # Drive the REAL Undo control from the numbered selection.
        table.selectRow(row_newest)
        dialog.undo_button.click()
        undo_box = self.responder.box_with('Undo rename session')
        self.assertIsNotNone(undo_box, f'no undo confirmation: {self.responder.boxes}')
        self.assertIn(report.session_id, undo_box['text'], 'wrong session id reached the confirm box')
        self.assertTrue(wait_operation(dialog, 'undo_report'), 'undo did not finish')
        undo = dialog.undo_report
        self.assertEqual(undo.session_id, report.session_id)  # correct original id used
        self.assertEqual(set(undo.restored), {F1, F2, F8})
        self.assertEqual(len(undo.anomalies), 0)
        assert_same_tree(self, self.pre_snapshot, snapshot_tree(self.library), label='after numbered-row undo')

        # Mapping stays stable across the post-undo table refresh.
        wait_idle(dialog)
        self.assertEqual(session_row_id(table, session_number(table, 1)), report.session_id)
        self.assertEqual(str(table.item(session_number(table, 1), 2).text()), '↩ Undone')
        self.assertEqual(session_row_id(table, session_number(table, 2)), old_id)

    # F ------------------------------------------------------------------

    def test_sessions_without_valid_timestamps_stay_visible_at_bottom(self):
        sessions = journals_dir(self.library)
        timed_id = make_journal(sessions, 't1m3d000000000000000000000aaa',
                                started='2026-07-04T12:34:56Z', terminal='closed')
        missing_id = make_journal(sessions, 'm1ss1ngstamp000000000000000bbb',
                                  started=None, terminal='closed')  # key omitted entirely
        invalid_id = make_journal(sessions, 'n0ts4st4mp0000000000000000ccc',
                                  started='not-a-timestamp', terminal='closed')

        dialog = self.open_dialog_on()
        self.assertTrue(wait_idle(dialog), 'initial scan did not finish')
        table = dialog.sessions_table
        # Nothing hidden: all three sessions remain visible rows.
        self.assertEqual(table.rowCount(), 3)
        # The timed session sorts first (newest-first among valid stamps);
        # the two without usable timestamps stay visible below it...
        row_timed = session_row(table, timed_id)
        self.assertEqual(row_timed, session_number(table, 1))
        expected_local = datetime.fromisoformat('2026-07-04T12:34:56+00:00') \
            .astimezone().strftime('%d-%m-%Y | %H:%M')
        self.assertEqual(str(table.item(row_timed, 1).text()), expected_local)
        # ...and each degrades to a safe 'Unknown' label instead of crashing.
        bottom = {session_row_id(table, r): str(table.item(r, 1).text()) for r in range(3)}
        self.assertEqual(bottom[missing_id], 'Unknown')
        self.assertEqual(bottom[invalid_id], 'Unknown')
        visible_ids = {session_row_id(table, r) for r in range(3)}
        self.assertEqual(visible_ids, {timed_id, missing_id, invalid_id})


if __name__ == '__main__':
    unittest.main(verbosity=2)
