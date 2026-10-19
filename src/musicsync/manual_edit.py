"""Manual single-track editor: filename + supported ID3 text metadata.

Integrated with the Bulk Rename dialog (one "Manual Edit…" action per selected
row). Everything here is read-only until the user explicitly confirms an apply;
the mutation itself goes through the SAME journaled engine used by bulk rename
(``apply_changes`` with a one-item :class:`ItemPlan`), so:

- opening/editing/cancelling never touches the file (bytes + mtime verifiable);
- live re-validation happens at apply time in the engine (source changed since
  this dialog was opened is rejected as ``changed_since_preview``, targets that
  now exist are rejected as ``target_exists``, unresolved sessions block the
  whole operation);
- every applied step is journaled with a pre-mutation byte backup wherever tags
  were edited, and undo from the Rename Sessions tab restores original name AND
  exact original bytes.

Supported editable fields (Milestone V12): filename plus TIT2/TPE1/TALB/TPE2/
TCON/TRCK/TDRC/TCOM via :mod:`musicsync.vendored.tags.apply_tag_edits`. All
other ID3 frames (artwork, ReplayGain, comments, unknown) are preserved; they
are listed read-only in the inspection pane. Frames that currently hold more
than one stored value are shown but locked: replacing several values with a
single guessed one is not something this editor will do silently.

Clearing semantics (documented in the UI): clearing a field and applying
DELETES that ID3 frame from the file; undo restores it exactly. Fields left at
their original value produce no edit at all.
"""
import logging
import os
import stat
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QPlainTextEdit, QVBoxLayout)

from musicsync.logging import clean
from musicsync.vendored.cleaning import MAX_NAME_BYTES, name_key
from musicsync.vendored.engine import ItemPlan, Preview  # dataclasses only; no I/O here

#: (form key, frame id, human label) — the editable ID3 fields of this milestone.
MANUAL_FIELDS = (
    ('title', 'TIT2', 'Title'),
    ('artist', 'TPE1', 'Artist'),
    ('album', 'TALB', 'Album'),
    ('album_artist', 'TPE2', 'Album Artist'),
    ('genre', 'TCON', 'Genre'),
    ('track_number', 'TRCK', 'Track number'),
    ('date_year', 'TDRC', 'Date / Year'),
    ('composer', 'TCOM', 'Composer'),
)


def _frame_values(tags, frame_id):
    """Stored (stripped, non-empty) text values of one frame id, in order."""
    out = []
    for frame in tags.getall(frame_id):
        for part in getattr(frame, 'text', []) or ():
            text = str(part).strip()
            if text:
                out.append(text)
    return tuple(out)


class ManualEditDialog(QDialog):
    """Single-track manual editor. Modal; no changes without an explicit Yes."""

    def __init__(self, root, rel_path, parent=None):
        super().__init__(parent)
        self.root_abs = Path(os.path.abspath(str(root)))
        self.rel_path = str(rel_path)
        self.logger = logging.getLogger('musicsync')

        # Open-time identity snapshot. The engine compares these against the
        # live file at apply time, so a file modified while this dialog is open
        # is rejected instead of silently clobbered (changed_since_preview).
        self.path = self.root_abs / self.rel_path if not str(rel_path).startswith('/') else None
        self.open_stat = None
        self.current_name = ''
        self.original_values = {}      # frame_id -> single stored value or None (absent)
        self.locked_fields = set()     # form keys whose frames hold conflicting values
        self.tags_readable = True
        self.error_state = ''          # non-empty when the file cannot be edited at all

        self.preview_item = None       # ItemPlan used for the last apply attempt
        self.changes_applied = False   # True once an engine session touched this file
        self.busy = False
        self._worker = None
        self.applied_report = None     # ApplyReport of the last apply attempt
        self._locked_display = {}      # form key -> display text for multi-value frames
        self._inspection_lines = []    # read-only frame listing built by _load()

        self.setWindowTitle(f'Manual Edit · {self.rel_path}')
        self.resize(720, 760)
        layout = QVBoxLayout(self)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        form = QFormLayout()
        self.filename_edit = QLineEdit()
        self.filename_edit.setObjectName('filename_edit')
        self.filename_error = QLabel('')
        self.filename_error.setWordWrap(True)
        self.filename_error.setStyleSheet('color: #b00020;')
        layout.addWidget(QLabel('Filename (keep the .mp3 extension):'))
        layout.addWidget(self.filename_edit)
        layout.addWidget(self.filename_error)

        self.field_edits = {}
        for key, frame_id, label in MANUAL_FIELDS:
            edit = QLineEdit()
            edit.setObjectName(f'field_{key}')
            edit.setToolTip(f'{frame_id} text frame. Clearing the field and applying deletes the tag from the file.')
            form.addRow(f'{label}  ({frame_id}):', edit)
            self.field_edits[key] = edit

        layout.addLayout(form)
        note = QLabel('Notes: opening or editing this form never modifies the file. '
                      'Clearing a field and applying deletes that ID3 tag; Undo restores it exactly. '
                      'Only the filename and the fields above are editable in this milestone — every other '
                      'frame (artwork, ReplayGain, comments, …) and all audio bytes are preserved.')
        note.setWordWrap(True)
        layout.addWidget(note)

        self.inspection_pane = QPlainTextEdit()
        self.inspection_pane.setObjectName('inspection_pane')
        self.inspection_pane.setReadOnly(True)
        self.inspection_pane.setMaximumHeight(150)
        layout.addWidget(QLabel('ID3 frames present when opened (read-only inspection):'))
        layout.addWidget(self.inspection_pane)

        self.change_preview = QPlainTextEdit()
        self.change_preview.setObjectName('change_preview')
        self.change_preview.setReadOnly(True)
        self.change_preview.setMaximumHeight(120)
        layout.addWidget(QLabel('Changes to apply (old → new):'))
        layout.addWidget(self.change_preview)

        buttons = QHBoxLayout()
        cancel_button = QPushButton('Cancel')
        cancel_button.setObjectName('cancel_button')
        self.apply_button = QPushButton('Apply…')
        self.apply_button.setObjectName('apply_button')
        self.apply_button.setToolTip('Ask for confirmation, then apply through the journaled engine. '
                                     'The default answer is No; nothing happens without your Yes.')
        self.apply_button.clicked.connect(self._on_apply_clicked)
        cancel_button.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)

        # No keyboard shortcut is wired to Apply (this PySide build exposes no
        # default-button API either): Enter can never apply anything (fail closed).
        # The only confirmations are the explicit "Apply…" button and its Yes|No
        # box, whose default answer is No.

        for edit in list(self.field_edits.values()):
            edit.textChanged.connect(lambda _text=None: self._refresh_preview())
        self.filename_edit.textChanged.connect(lambda _text=None: self._refresh_preview())

        if self.path is None or not self._load():
            # Unreadable path / symlink / missing file: show state, disable everything.
            self.error_state = self.error_state or 'File is missing or not a regular file.'
            self.info_label.setText(self.error_state)
            for edit in list(self.field_edits.values()):
                edit.setEnabled(False)
            self.filename_edit.setEnabled(False)

    # ------------------------------------------------------------------ load

    def _load(self):
        try:
            st = os.lstat(str(self.path))
        except OSError as exc:
            self.error_state = f'Cannot access the file ({clean(str(exc))}). It may have been deleted.'
            return False
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            self.error_state = 'Refusing to edit: the selected path is not a regular file (symlink?).'
            return False
        self.open_stat = st
        self.current_name = self.path.name

        editable_ids = {frame_id for _k, frame_id, _l in MANUAL_FIELDS}
        lines = []
        try:
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3
            audio = MP3(str(self.path))
        except Exception as exc:  # assorted failure modes per format
            self.tags_readable = False
            self.error_state = (f'Note: no readable MP3/ID3 metadata ({clean(str(exc))}); '
                                'only the filename can be edited for this file.')
            lines.append('(metadata could not be read — nothing is listed)')
        else:
            tags = audio.tags if isinstance(audio.tags, ID3) else None
            if tags is None:
                self.original_values = {frame_id: None for _k, frame_id, _l in MANUAL_FIELDS}
                lines.append('(no ID3v2 metadata block — new fields can be added by applying this form)')
            else:
                # Record each editable field's original single value; frames with
                # several stored values are shown but locked (never collapsed silently).
                self.original_values = {}
                for key, frame_id, _label in MANUAL_FIELDS:
                    values = _frame_values(tags, frame_id)
                    if len(values) > 1:
                        self.locked_fields.add(key)
                        self._locked_display[key] = ' | '.join(values)
                    self.original_values[frame_id] = values[0] if values else None

                apic_count = sum(len(tags.getall(k)) for k in tags.keys() if k.startswith('APIC'))
                lines.append('ID3 frames present when this dialog opened — all preserved on save:')
                for key in sorted(tags.keys()):
                    base = key.split(':', 1)[0]
                    if key.startswith('APIC'):
                        continue  # aggregated below
                    if ':' not in key and base in editable_ids:
                        label = next(l for k2, f2, l in MANUAL_FIELDS if f2 == base)
                        stored = _frame_values(tags, key)
                        marker = '  [locked: multiple stored values]' if len(stored) > 1 else ''
                        lines.append(f'  {key} ({label}): {" | ".join(stored) if stored else "(absent)"}{marker}')
                    else:
                        texts = _frame_values(tags, key)
                        value_text = ' | '.join(texts) if texts else '(non-text frame)'
                        lines.append(f'  {key}: {value_text} — preserved')
                if apic_count:
                    lines.append(f'  APIC: {apic_count} artwork image(s) — preserved')

        self._inspection_lines = lines
        self._fill_form()
        return True

    def _fill_form(self):
        self.filename_edit.setText(self.current_name)
        for key, frame_id, _label in MANUAL_FIELDS:
            edit = self.field_edits[key]
            if key in self.locked_fields:
                edit.setText(self._locked_display.get(key, ''))
                edit.setReadOnly(True)
                edit.setToolTip(f'{frame_id}: this file stores several values; editing is locked so none are lost.')
            else:
                edit.setText(self.original_values.get(frame_id) or '')
        if not self.tags_readable:
            for edit in list(self.field_edits.values()):
                edit.setEnabled(False)  # broken/absent tags: filename-only editing
        self.inspection_pane.setPlainText('\n'.join(self._inspection_lines))
        size = int(getattr(self.open_stat, 'st_size', 0)) if self.open_stat else 0
        note = f'\n{self.error_state}' if self.error_state else ''
        self.info_label.setText(
            f'{self.rel_path} — current name: {self.current_name} ({size:,} bytes){note}\n'
            'Opening and editing this form never modifies the file. Changes apply only after you confirm.')
        self._refresh_preview()

    # ------------------------------------------------------------- validation

    def validate_filename(self, proposed):
        """Return an error message (or '' when acceptable) for a new full name."""
        if self.error_state:
            return 'File cannot be edited.'
        current = self.current_name
        if not proposed or not proposed.strip():
            return 'Filename is empty.'
        if proposed == current:
            return ''
        cur_ext = Path(current).suffix
        if Path(proposed).suffix != cur_ext:
            return f'Extension must stay {cur_ext} (only the part before it can change).'
        for ch in proposed:
            cp = ord(ch)
            if ch == '\x00' or ch == '/' or ch == '\\' or cp < 0x20:
                return 'Filename contains invalid characters (no path separators or control characters).'
        stem = Path(proposed).stem.strip()
        if not stem:
            return 'Filename has no name part before the extension.'
        if len(proposed.encode('utf-8')) > MAX_NAME_BYTES:
            return f'Filename is too long ({len(proposed.encode("utf-8"))} bytes; max {MAX_NAME_BYTES}).'
        if proposed in ('.', '..'):
            return 'That name is not allowed.'
        return ''

    def filename_collision(self, proposed):
        """Error text when the live directory already holds a colliding name."""
        current = self.current_name
        if not proposed or Path(proposed).suffix != Path(current).suffix:
            return ''  # extension problem is reported separately and more clearly
        if name_key(proposed) == name_key(current):
            return ''
        parent = str(self.path.parent)
        try:
            live = os.listdir(parent)
        except OSError as exc:
            return f'Directory is not readable ({clean(str(exc))}).'
        for other in live:
            if other != current and name_key(other) == name_key(proposed):
                return f'A file named “{other}” already exists in that folder (name collision).'
        return ''

    def pending_changes(self):
        """Compute old → new diff. Returns (lines, filename_err, edits, renamed)."""
        proposed = self.filename_edit.text() if self.filename_edit.isEnabled() else self.current_name
        file_error = self.validate_filename(proposed)
        collision = '' if file_error or proposed == self.current_name else self.filename_collision(proposed)
        lines = []
        edits = []
        renamed = bool(file_error) is False and name_key(proposed) != name_key(self.current_name)
        if file_error:
            lines.append(f'Filename: INVALID — {file_error}')
        elif renamed:
            lines.append(f'Filename: “{self.current_name}” → “{proposed}”')
            proposed_out = proposed
        else:
            proposed_out = None

        for key, frame_id, label in MANUAL_FIELDS:
            edit = self.field_edits[key]
            if key in self.locked_fields or not edit.isEnabled():
                continue
            original = self.original_values.get(frame_id)
            new_text = edit.text().strip()
            old_display = f'“{original}”' if original else '(absent)'
            if new_text == (original or ''):
                continue  # untouched → no edit, even when absent
            if not new_text:
                lines.append(f'{label}: {old_display} → deleted')
                edits.append((frame_id, original or '', ''))
            else:
                verb = 'set to' if not original else '→'
                arrow = f'{old_display} → “{new_text}”' if original else f'(absent) → “{new_text}”'
                lines.append(f'{label}: {arrow}')
                edits.append((frame_id, original or '', new_text))

        error = file_error or collision
        return (lines, error, tuple(edits), proposed_out)

    def _refresh_preview(self):
        """Update filename error label, change preview pane and Apply enabled state."""
        if not self.open_stat:
            return
        lines, error, edits, proposed_out = self.pending_changes()
        file_only_err = self.validate_filename(self.filename_edit.text())
        collision_err = ''
        if file_only_err == '':
            proposed_now = self.filename_edit.text()
            if name_key(proposed_now) != name_key(self.current_name):
                collision_err = self.filename_collision(proposed_now)
        self.filename_error.setText(file_only_err or collision_err)
        text = '\n'.join(lines) if lines else 'No changes yet — edit a field above.'
        self.change_preview.setPlainText(text)
        has_changes = proposed_out is not None or bool(edits)
        enabled = (not self.busy and not self.changes_applied and has_changes and error == '')
        self.apply_button.setEnabled(enabled)

    # ----------------------------------------------------------------- apply

    def _build_item_plan(self, proposed_name, edits):
        return ItemPlan(
            rel_path=self.rel_path,
            current_name=self.current_name,
            size=int(self.open_stat.st_size),
            mtime_ns=int(self.open_stat.st_mtime_ns),
            status='ok',
            proposed_name=proposed_name if (proposed_name and name_key(proposed_name) != name_key(self.current_name)) else None,
            reasons=(),
            flags=(),
            tag_edits=tuple((frame, old, new) for frame, old, new in edits),
        )

    def _on_apply_clicked(self):
        if self.busy or not self.open_stat:
            return
        lines, error, edits, proposed_out = self.pending_changes()
        renamed = bool(proposed_out) and name_key(proposed_out) != name_key(self.current_name)
        if not renamed and not edits:
            QMessageBox.information(self, 'No changes', 'Nothing has been changed; there is nothing to apply.')
            return
        # Re-check against the live directory one last time before asking.
        self._refresh_preview()
        lines, error, edits, proposed_out = self.pending_changes()
        if error:
            QMessageBox.information(self, 'Cannot apply', f'{error}\n\nThe file has not been modified.')
            return
        if proposed_out is None and not edits:
            return  # nothing changed; the Apply button should be disabled already

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle('Apply manual changes')
        box.setTextFormat(Qt.TextFormat.PlainText)
        parts = []
        if proposed_out is not None:
            parts.append('the filename change')
        if edits:
            parts.append(f'{len(edits)} metadata change(s)')
        box.setText('Apply ' + ' and '.join(parts) + '?')
        box.setInformativeText('Every step is journaled; the file can be restored to its exact original '
                               'name and bytes from Rename Sessions → Undo. The default answer is No.')
        box.setDetailedText('\n'.join(lines))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            self.logger.info('Manual edit apply declined by user for %s', self.rel_path)
            return

        item = self._build_item_plan(proposed_out, edits)
        preview = Preview(
            root=str(self.root_abs),
            items=(item,),
            collisions=(),
            symlinks_skipped=(),
            other_file_count=0,
        )
        # Reuse the verified journaled worker from Bulk Rename (one-item batch);
        # local import avoids a module cycle at package import time.
        from musicsync.bulk_rename import RenameWorker  # noqa: E402 - deliberate
        self._worker = RenameWorker('apply', str(self.root_abs), data=(preview, (self.rel_path,)))
        self.busy = True
        self.info_label.setText('Applying through the journaled engine…')
        for widget in [self.filename_edit, self.apply_button] + list(self.field_edits.values()):
            widget.setEnabled(False)
        self._worker.finished_payload.connect(self._on_worker_finished)
        self._worker.start()

    def _set_fields_enabled(self, enabled):
        """Re-enable the form after a failed attempt (conflicting frames stay locked)."""
        if not enabled:
            return
        self.filename_edit.setEnabled(bool(self.open_stat))
        for key, edit in self.field_edits.items():
            if key not in self.locked_fields:
                edit.setEnabled(True)
        self._refresh_preview()

    def _on_worker_finished(self, payload):
        self.busy = False
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        if not payload['ok']:
            message = payload['error'] or f'{payload["kind"]} failed with an unknown error'
            self.logger.error('Manual edit apply for %s: %s', self.rel_path, clean(message))
            self._set_fields_enabled(True)
            QMessageBox.critical(self, 'Manual edit apply failed',
                                 message + '\n\nThe file was not modified by this attempt.')
            return

        report = payload['data']  # ApplyReport from the journaled engine
        self.applied_report = report
        lines = []
        for rel, new_name in report.applied:
            lines.append(f'Applied: {rel}' + (f' → {new_name}' if new_name else ' (metadata only)'))
        for rel, code in report.rejected:
            lines.append(f'Rejected before mutation: {rel} ({code})')
        for rel, code in report.partial:
            lines.append(f'Started but incomplete: {rel} ({code}) — recover via Rename Sessions → Undo')
        if not report.session_id or (not report.applied and not report.partial):
            # Nothing passed validation; the file is untouched and stays editable.
            self._set_fields_enabled(True)
            QMessageBox.warning(self, 'Nothing applied', '\n'.join(lines))
            return

        self.changes_applied = True
        if report.session_id:
            lines.append('')
            lines.append(f'Session {report.session_id} recorded; undo is available in Bulk Rename → Rename Sessions.')
        style = (QMessageBox.Icon.Information
                 if not report.rejected and not report.partial else QMessageBox.Icon.Warning)
        for widget in [self.filename_edit, self.apply_button] + list(self.field_edits.values()):
            widget.setEnabled(False)
        self.info_label.setText('Applied — the form is now locked. '
                                'Use Bulk Rename → Rename Sessions to inspect or undo this session.')
        box = QMessageBox(self)
        box.setIcon(style)
        box.setWindowTitle('Manual edit result')
        box.setDetailedText('\n'.join(lines))
        box.exec()