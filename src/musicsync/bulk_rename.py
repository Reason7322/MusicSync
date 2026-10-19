"""Bulk Rename dialog: preview, explicit approval, journaled apply and undo.

Operates only on the selected PC music library through the verified vendored
engine (musicsync.vendored). Never touches phone files; works without any
connected device. Long-running engine calls run in worker QThreads; all widget
updates happen on the GUI thread via queued signals.
"""
import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QTabWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from musicsync.logging import clean
from musicsync.manual_edit import ManualEditDialog  # noqa: E402 - no cycle: manual_edit imports bulk_rename lazily only
from musicsync.vendored.engine import EngineError, apply_changes, build_preview, list_sessions, undo_session

TAG_FRAME_NAMES = {'TIT2': 'Title', 'TPE1': 'Artist'}


def _human_reasons(reasons):
    return [f'{r.code} — {r.detail}' if r.detail else f'{r.code}' for r in reasons]


def row_details(item):
    """Human-readable detail text for one preview item (reasons, flags, tag edits)."""
    lines = []
    if item.reasons:
        lines.append('Reasons: ' + '; '.join(_human_reasons(item.reasons)))
    if item.flags:
        lines.append('Warnings/flags: ' + ', '.join(r.code for r in item.flags))
    for frame, old, new in item.tag_edits:
        name = TAG_FRAME_NAMES.get(frame, frame)
        lines.append(f'{name}: {old} → {new}')
    return '\n'.join(lines)


def list_sessions_safe(root):
    try:
        return list_sessions(root)
    except OSError as error:
        logging.getLogger('musicsync').warning('Bulk rename sessions unavailable: %s', clean(error))
        return []


class RenameWorker(QThread):
    """Runs one engine operation off the GUI thread; emits exactly one result."""

    finished_payload = Signal(object)  # {'kind': str, 'ok': bool, 'data': object | None, 'error': str}

    def __init__(self, kind, root, data=None, parent=None):
        super().__init__(parent)
        self.kind = kind          # 'preview' | 'apply' | 'undo'
        self.root = str(root)
        self.data = data
        self.cancel_requested = False  # cooperative cancellation for apply only

    def run(self):
        result = None
        try:
            if self.kind == 'preview':
                result = build_preview(self.root)
            elif self.kind == 'apply':
                preview, approved = self.data
                result = apply_changes(self.root, preview, approved,
                                       cancel_check=lambda: self.cancel_requested)
            elif self.kind == 'undo':
                result = undo_session(self.root, str(self.data))
            else:  # pragma: no cover - guarded by callers
                raise ValueError(f'unknown rename operation {self.kind!r}')
        except (EngineError, OSError, ValueError) as error:
            payload_error = f'{type(error).__name__}: {clean(str(error))}'
        except Exception as error:  # never leave the GUI thread stuck busy
            logging.getLogger('musicsync').exception('Bulk rename %s crashed', self.kind)
            payload_error = f'Internal error in {self.kind} operation: {type(error).__name__}. See log.'
        else:
            payload_error = ''
        self.finished_payload.emit({'kind': self.kind, 'ok': not payload_error,
                                   'data': result if not payload_error else None, 'error': payload_error})


class BulkRenameDialog(QDialog):
    """Settings entry point for renaming files in the selected PC library."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = str(source)
        self.preview = None       # Preview of the last completed scan
        self.report = None        # ApplyReport of the last apply attempt
        self.undo_report = None   # UndoReport of the last undo attempt
        self.sessions = []        # list_sessions() dicts, refreshed after operations
        self.busy = False         # a worker QThread owns the engine right now
        self.applied_changed = False  # True when the last apply/undo touched files
        self.logger = logging.getLogger('musicsync')
        self._active_worker = None

        self.setWindowTitle(f'Bulk Rename · {self.source}')
        self.resize(980, 640)
        layout = QVBoxLayout(self)
        self.status_label = QLabel('Scanning library…')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.preview_table = self._make_item_table()
        preview_actions = QHBoxLayout()
        self.preview_button = QPushButton('Preview Changes')
        self.preview_button.setToolTip('Rescan the library; never modifies files.')
        self.preview_button.clicked.connect(self._start_preview)
        self.manual_edit_button = QPushButton('Manual Edit…')
        self.manual_edit_button.setObjectName('manual_edit_button')
        self.manual_edit_button.setToolTip('Open the single-track manual editor for the selected row: '
                                           'filename and supported ID3 fields. Nothing changes until you confirm inside.')
        self.manual_edit_button.clicked.connect(self._on_manual_edit)
        self.select_all_button = QPushButton('Approve All Safe')
        self.select_all_button.setToolTip('Select every change that can be applied safely. Ambiguous and error rows are never selected.')
        self.select_all_button.clicked.connect(lambda: self._select_all(True))
        self.clear_selection_button = QPushButton('Clear Selection')
        self.clear_selection_button.clicked.connect(lambda: self._select_all(False))
        preview_actions.addWidget(self.preview_button)
        preview_actions.addStretch()
        preview_actions.addWidget(self.select_all_button)
        preview_actions.addWidget(self.clear_selection_button)
        self.collisions_label = QLabel('')
        self.collisions_label.setWordWrap(True)
        preview_tab_widget = QWidget()
        preview_tab_layout = QVBoxLayout(preview_tab_widget)
        preview_tab_layout.addLayout(preview_actions)
        preview_tab_layout.addWidget(self.preview_table, 1)
        preview_tab_layout.addWidget(self.collisions_label)
        self.tabs.addTab(preview_tab_widget, 'Rename Preview')

        self.sessions_table = self._make_session_table()
        session_actions = QHBoxLayout()
        self.refresh_sessions_button = QPushButton('Refresh Sessions')
        self.refresh_sessions_button.clicked.connect(self._refresh_sessions_sync)
        self.undo_button = QPushButton('Undo Selected Session…')
        self.undo_button.setToolTip('Restore original filenames and bytes for the selected rename session.')
        self.undo_button.clicked.connect(self._on_undo)
        sessions_tab_widget = QWidget()
        sessions_tab_layout = QVBoxLayout(sessions_tab_widget)
        sessions_tab_layout.addWidget(self.sessions_table, 1)
        sessions_tab_layout.addLayout(session_actions)
        sessions_tab_layout.addWidget(self.refresh_sessions_button)
        self.tabs.addTab(sessions_tab_widget, 'Rename Sessions')
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        bottom.addWidget(self.progress_bar, 1)
        self.cancel_button = QPushButton('Cancel Operation')
        self.cancel_button.setToolTip('Ask the engine to stop between rename steps. Completed steps stay applied; undo is available afterwards.')
        self.cancel_button.clicked.connect(self._cancel_operation)
        self.cancel_button.hide()
        bottom.addWidget(self.cancel_button)
        self.apply_button = QPushButton('Apply Selected…')
        self.apply_button.setObjectName('apply_selected_button')
        self.apply_button.setToolTip('Show the confirmation for the changes you ticked in the Apply column. '
                                     'Only selected rows are applied; nothing happens without your explicit Yes.')
        self.apply_button.clicked.connect(self._on_apply)
        bottom.addWidget(self.apply_button)
        close_button = QPushButton('Close')
        close_button.clicked.connect(self.close)
        bottom.addWidget(close_button)
        layout.addLayout(bottom)

        # Initial state: journal headers are a small synchronous read; the first
        # scan is read-only and runs in the background immediately.
        self.sessions = list_sessions_safe(self.source)
        self._fill_sessions()
        self._start_preview()

    # ------------------------------------------------------------ table build

    def _make_item_table(self):
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(['Apply', 'Path', 'Current name', 'Proposed name', 'Status', 'Details'])
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(5, 260)
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return table

    def _make_session_table(self):
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(['Session', 'Started (UTC)', 'State', 'Completed steps'])
        for index in range(3):
            table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return table

    def _fill_items(self):
        preview = self.preview
        rows = sorted(preview.items, key=lambda item: (item.rel_dir or '.', item.current_name))
        self.preview_table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            approvable = False
            if item.status == 'ok':
                renamed = bool(item.proposed_name and item.proposed_name != item.current_name)
                approvable = renamed or bool(item.tag_edits)
            checkbox_item = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if approvable:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            checkbox_item.setFlags(flags)
            checkbox_item.setData(Qt.ItemDataRole.UserRole, item.rel_path)
            self.preview_table.setItem(row, 0, checkbox_item)
            path_text = f'{item.rel_dir}/' if item.rel_dir else ''
            self.preview_table.setItem(row, 1, QTableWidgetItem(path_text))
            self.preview_table.setItem(row, 2, QTableWidgetItem(item.current_name))
            proposed = item.proposed_name or (item.current_name if item.status == 'no_change' else '')
            self.preview_table.setItem(row, 3, QTableWidgetItem(proposed or '—'))
            status_text = {'ok': 'Proposed', 'no_change': 'No change',
                           'ambiguous': 'Needs review', 'error': 'Error'}[item.status]
            self.preview_table.setItem(row, 4, QTableWidgetItem(status_text))
            details = row_details(item)
            details_item = QTableWidgetItem(details or '—')
            details_item.setToolTip(details)
            self.preview_table.setItem(row, 5, details_item)

    def _fill_sessions(self):
        table = self.sessions_table
        ordered = list(reversed(self.sessions))
        table.setRowCount(len(ordered))
        for row, session in enumerate(ordered):
            if session.get('corrupt'):
                values = [session['session_id'], '', 'CORRUPT JOURNAL', '']
            else:
                done, total = session.get('done_ops', 0), session.get('ops', 0)
                state = (session.get('state') or 'open').upper()
                values = [str(session['session_id']), str(session.get('started') or ''), state, f'{done}/{total}']
            for col, text in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(text))

    # --------------------------------------------------------------- preview

    def _start_preview(self):
        if self.busy:
            return
        self._set_busy(True, 'Scanning library… (read-only; no files are modified)', cancellable=False)
        self._launch('preview')

    def _refresh_sessions_sync(self):
        # Journal headers only — a small read, safe on the GUI thread.
        self.sessions = list_sessions_safe(self.source)
        self._fill_sessions()
        self._session_status_line()

    def _on_manual_edit(self):
        """Open the single-track manual editor for the selected preview row."""
        if self.busy:
            return
        row = self.preview_table.currentRow()
        item = self.preview_table.item(row, 0) if row >= 0 else None
        rel = str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ''
        if not rel:
            QMessageBox.information(self, 'No file selected',
                                    'Select a single file in the Rename Preview table first.')
            return
        editor = ManualEditDialog(str(self.source), rel, self)
        editor.exec()  # modal; returns after Cancel or after Apply and its result box
        if editor.changes_applied:
            # The engine journaled a session: surface it and re-scan the table so
            # names/rows reflect the on-disk state.
            self._refresh_sessions_sync()
            self._start_preview()

    def _checked_rels(self):
        approved = []
        for row in range(self.preview_table.rowCount()):
            item = self.preview_table.item(row, 0)
            if item is not None and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable) \
                    and item.checkState() == Qt.CheckState.Checked:
                approved.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return approved

    def _select_all(self, value):
        for row in range(self.preview_table.rowCount()):
            item = self.preview_table.item(row, 0)
            if item is not None and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                item.setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)

    def _apply_line(self, item):
        line = f'{item.rel_path}'
        if item.proposed_name and item.proposed_name != item.current_name:
            line += f': {item.current_name} → {item.proposed_name}'
        for frame, old, new in item.tag_edits:
            line += f'  [{TAG_FRAME_NAMES.get(frame, frame)}: {old} → {new}]'
        return line

    def _counts_line(self):
        counts = self.preview.counts_by_status
        parts = [f'{label}: {counts.get(status, 0)}' for status, label in
                 (('ok', 'proposed'), ('no_change', 'unchanged'), ('ambiguous', 'needs review'), ('error', 'errors'))]
        line = f'{self.preview.item_count} file(s) scanned · ' + ' · '.join(parts) \
               + f' · {self.preview.other_file_count} non-audio file(s)'
        if self.preview.symlinks_skipped:
            line += f' · {len(self.preview.symlinks_skipped)} symlink(s) skipped'
        return line

    def _collision_lines(self):
        lines = []
        for collision in self.preview.collisions:
            where = collision.directory or '(library root)'
            names = ', '.join(collision.involved)
            if collision.kind == 'proposed_vs_proposed':
                lines.append(f'{where}: several files propose the same normalized name — {names}')
            else:
                lines.append(f'{where}: proposed name already exists on disk — {names}')
        return lines

    # ----------------------------------------------------------------- apply

    def _on_apply(self):
        if self.busy:
            return
        approved = self._checked_rels()
        if not approved:
            QMessageBox.information(
                self, 'Nothing approved',
                'No changes are currently selected.\n'
                'Tick the "Apply" column for each change you accept; nothing is applied until you confirm.')
            return
        items_by_rel = {item.rel_path: item for item in (self.preview.items if self.preview else ())}
        lines = [self._apply_line(items_by_rel[rel]) for rel in approved if rel in items_by_rel]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle('Apply bulk rename')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f'Apply {len(approved)} selected change(s) to your PC music library?')
        box.setInformativeText('Files keep their content; metadata edits are limited to Title/Artist. '
                               'Every step is journaled and can be undone from the Rename Sessions tab.')
        box.setDetailedText('\n'.join(lines))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            self.logger.info('Bulk rename apply cancelled by user before confirmation (%d selected)', len(approved))
            return
        self.begin_apply(list(approved))

    def begin_apply(self, approved):
        """Start a journaled apply of exactly ``approved`` rel paths (explicit call)."""
        if self.busy:
            return
        if not isinstance(approved, list) or not approved:
            return
        if self.preview is None:
            QMessageBox.warning(self, 'No preview available', 'Preview the library before applying changes.')
            return
        self.logger.info('Bulk rename apply started for %d approved item(s)', len(approved))
        self._set_busy(True, f'Applying {len(approved)} approved change(s)… Cancel stops between steps.', cancellable=True)
        self._launch('apply', data=(self.preview, tuple(approved)))

    # ------------------------------------------------------------------ undo

    def _selected_session(self):
        row = self.sessions_table.currentRow()
        if row < 0 or row >= self.sessions_table.rowCount():
            return None
        session_id = str(self.sessions_table.item(row, 0).text())
        for session in self.sessions:
            if session.get('session_id') == session_id:
                return session
        return None

    def _on_undo(self):
        if self.busy:
            return
        session = self._selected_session()
        if session is None or session.get('corrupt'):
            QMessageBox.information(self, 'No undoable session selected',
                                    'Select a rename session in the Rename Sessions tab first.\n'
                                    'Corrupt journals cannot be undone automatically; they are shown here so nothing is hidden.')
            return
        state = session.get('state') or 'open'
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if state != 'closed' else QMessageBox.Icon.Question)
        box.setWindowTitle('Undo rename session')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"Undo session {session['session_id']}?")
        informative = 'Original filenames and file bytes are restored exactly.'
        if state == 'aborted':
            informative += '\nThis session was interrupted; undo completes recovery of its partial work.'
        elif state == 'open':
            informative += ('\nThis session has no terminal record (possible crash); the engine probes the live '
                            'files and restores only what it can verify.')
        box.setInformativeText(informative)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            self.logger.info('Bulk rename undo cancelled by user for session %s', session['session_id'])
            return
        self.begin_undo(session['session_id'])

    def begin_undo(self, session_id):
        """Start a byte-exact undo of ``session_id`` (explicit call)."""
        if self.busy:
            QMessageBox.warning(self, 'Operation in progress', 'Wait for the current rename operation to finish.')
            return
        if not isinstance(session_id, str) or not session_id:
            return
        self.logger.info('Bulk rename undo started for session %s', session_id)
        self._set_busy(True, f'Undoing session {session_id}…', cancellable=False)
        self._launch('undo', data=session_id)

    # ------------------------------------------------------------- machinery

    def _launch(self, kind, data=None):
        # A fresh thread per operation: the engine must never run twice in parallel.
        worker = RenameWorker(kind, self.source, data=data)
        worker.finished_payload.connect(self._on_worker_finished)
        self._active_worker = worker
        worker.start()

    def _cancel_operation(self):
        worker = self._active_worker
        if worker is not None and worker.kind == 'apply':
            worker.cancel_requested = True
            self.status_label.setText('Stopping between rename steps… Completed steps stay applied; undo is available afterwards.')

    def _set_busy(self, busy, text='', cancellable=False):
        self.busy = busy
        if text:
            self.status_label.setText(text)
        for button in (self.preview_button, self.manual_edit_button,
                       self.select_all_button, self.clear_selection_button,
                       self.apply_button, self.undo_button, self.refresh_sessions_button):
            button.setEnabled(not busy)
        self.progress_bar.setVisible(busy)
        self.cancel_button.setVisible(cancellable and busy)

    def _session_status_line(self):
        unresolved = [s for s in self.sessions if s.get('corrupt') or (s.get('state') not in ('closed', 'undone'))]
        if self.sessions:
            extra = f' · {len(unresolved)} unresolved — undo them before a new apply' if unresolved else ''
            self.tabs.setTabText(1, f'Rename Sessions ({len(self.sessions)}){extra}')
        else:
            self.tabs.setTabText(1, 'Rename Sessions')

    def _on_worker_finished(self, payload):
        kind = payload['kind']
        if not payload['ok']:
            message = payload['error'] or f'{kind} failed with an unknown error'
            self.logger.error('Bulk rename %s failed: %s', kind, message)
            status_text = {'preview': 'Preview scan failed — the library was not modified.',
                           'apply': 'Apply stopped by the engine. Completed steps stay journaled; use Rename Sessions to recover.',
                           'undo': 'Undo could not be completed without touching files.'}[kind]
            self._set_busy(False)
            self.status_label.setText(status_text)
            self._refresh_sessions_sync()
            if kind in ('apply', 'undo'):
                # Re-scan so the table shows the true post-failure state.
                self._start_preview()
            QMessageBox.critical(self, f'Bulk rename {kind} failed', message +
                                 ('\n\nSee the Rename Sessions tab; nothing is hidden.' if kind != 'preview' else ''))
            return

        result = payload['data']
        if kind == 'preview':
            self.preview = result
            self._fill_items()
            collision_lines = self._collision_lines()
            lines = [self._counts_line()]
            if collision_lines:
                lines.append(f'{len(collision_lines)} name collision(s) detected:')
                lines.extend(collision_lines)
            self.status_label.setText(lines[0])
            self.collisions_label.setText('\n'.join(lines[1:]) if len(lines) > 1 else '')
            self._set_busy(False)
        elif kind == 'apply':
            self.report = result
            self.applied_changed = bool(result.session_id) or bool(result.partial)
            self._refresh_sessions_sync()
            self._set_busy(False)
            self._start_preview()  # re-scan while the result dialog is shown
            self._show_apply_result(result)
        elif kind == 'undo':
            self.undo_report = result
            self.applied_changed = True
            self._refresh_sessions_sync()
            lines = [f'Restored {len(result.restored)} file(s):'] + list(result.restored)
            if result.anomalies:
                box_style = QMessageBox.Icon.Warning
                lines.append('')
                lines.append(f'{len(result.anomalies)} anomaly(ies) — review required:')
                for rel, code in result.anomalies:
                    lines.append(f'  {rel}: {code}')
            else:
                box_style = QMessageBox.Icon.Information
                lines.append('Filenames and bytes are back to exactly the pre-rename state.')
            self._set_busy(False)
            self._start_preview()  # re-scan while the result dialog is shown
            box = QMessageBox(self)
            box.setIcon(box_style)
            box.setWindowTitle('Rename undo result')
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText(f'Undid session {result.session_id}.')
            box.setDetailedText('\n'.join(lines))
            box.exec()

    def _show_apply_result(self, report):
        lines = []
        for rel, new_name in report.applied:
            lines.append(f'Applied: {rel}' + (f' → {new_name}' if new_name else ' (tags only)'))
        for rel, code in report.rejected:
            lines.append(f'Rejected before mutation: {rel} ({code})')
        for rel, code in report.partial:
            lines.append(f'Started but incomplete: {rel} ({code}) — recover via undo')
        for rel in report.canceled:
            lines.append(f'Canceled (never started, untouched on disk): {rel}')
        summary = [f'{len(report.applied)} applied', f'{len(report.rejected)} rejected',
                   f'{len(report.partial)} partial', f'{len(report.canceled)} canceled']
        if report.session_id:
            lines.append('')
            lines.append(f'Session {report.session_id} recorded; undo is available in Rename Sessions.')
        else:
            lines.append('')
            lines.append('Nothing was applied and no journal session was created.')
        box = QMessageBox(self)
        icon = QMessageBox.Icon.Information if report.ok else (QMessageBox.Icon.Warning)
        box.setIcon(icon)
        box.setWindowTitle('Rename apply result' if report.ok else 'Rename apply finished with problems')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(' · '.join(summary))
        box.setDetailedText('\n'.join(lines))
        box.exec()
