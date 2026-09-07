import json
import logging
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from musicsync.backend.status import StatusService
from musicsync.backend.sync_controller import SyncController
from musicsync.logging import clean
from musicsync.models import State
from musicsync.settings import state_dir
from musicsync.settings_dialog import SettingsDialog


def size_text(size):
    if size is None:
        return '—'
    value = float(size)
    for suffix in ['B', 'KB', 'MB', 'GB', 'TB']:
        if value < 1000 or suffix == 'TB':
            return f'{value:,.1f} {suffix}' if suffix != 'B' else f'{int(value)} B'
        value /= 1000


def label(text=''):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.devices = []
        self.closing = False
        self.setWindowTitle('Music Sync')
        self.resize(850, 710)
        self.controller = SyncController(self)
        self.status_service = StatusService(self)
        self.controller.state_changed.connect(self._state)
        self.controller.library_changed.connect(self._library)
        self.controller.preview_ready.connect(self._preview)
        self.controller.approval_needed.connect(self._approve)
        self.controller.progress.connect(self._progress)
        self.controller.change.connect(self._change)
        self.controller.log_line.connect(self._log)
        self.controller.completed.connect(self._complete)
        self.status_service.ready.connect(self._status)
        center = QWidget()
        self.setCentralWidget(center)
        layout = QVBoxLayout(center)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        title = label('Music Sync')
        font = title.font()
        font.setPointSize(font.pointSize() + 7)
        font.setBold(True)
        title.setFont(font)
        heading.addWidget(title)
        heading.addStretch()
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(lambda: self.refresh(True))
        self.settings_button = QPushButton('Settings…')
        self.settings_button.clicked.connect(self._settings)
        heading.addWidget(self.refresh_button)
        heading.addWidget(self.settings_button)
        layout.addLayout(heading)
        paths = QHBoxLayout()
        pc = QGroupBox('PC Library')
        pc_layout = QVBoxLayout(pc)
        self.source_label = label(settings.source)
        self.library_label = label('Inspecting library…')
        pc_layout.addWidget(self.source_label)
        pc_layout.addWidget(self.library_label)
        self.phone_group = QGroupBox(settings.device_name)
        phone_layout = QVBoxLayout(self.phone_group)
        self.device_label = label('Checking connection…')
        self.remote_label = label(settings.remote_dir)
        self.filesystem_label = label('')
        phone_layout.addWidget(self.device_label)
        phone_layout.addWidget(self.remote_label)
        phone_layout.addWidget(self.filesystem_label)
        paths.addWidget(pc, 1)
        paths.addWidget(self.phone_group, 1)
        layout.addLayout(paths)
        self.gain_label = label()
        layout.addWidget(self.gain_label)
        self.sync_group = QGroupBox('Synchronization')
        sync_layout = QVBoxLayout(self.sync_group)
        self.status_label = label('Preview changes to compare your libraries.')
        sync_layout.addWidget(self.status_label)
        self.summary_label = label('')
        sync_layout.addWidget(self.summary_label)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Action', 'File', 'Size'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        sync_layout.addWidget(self.table)
        self.ignored_label = label('Ignored and protected: Music/.thumbnails/')
        sync_layout.addWidget(self.ignored_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        sync_layout.addWidget(self.progress_bar)
        self.transfer_label = label('')
        sync_layout.addWidget(self.transfer_label)
        layout.addWidget(self.sync_group, 1)
        actions = QHBoxLayout()
        self.details_button = QCheckBox('Show Log')
        actions.addWidget(self.details_button)
        actions.addStretch()
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.controller.cancel)
        self.cancel_button.hide()
        self.preview_button = QPushButton('Preview Changes')
        self.preview_button.clicked.connect(lambda: self._start(True))
        self.sync_button = QPushButton('Sync Now')
        self.sync_button.clicked.connect(lambda: self._start(False))
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.sync_button)
        layout.addLayout(actions)
        self.last_label = label()
        layout.addWidget(self.last_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2500)
        self.log.setMaximumHeight(200)
        self.log.hide()
        self.details_button.toggled.connect(self.log.setVisible)
        layout.addWidget(self.log)
        self._paths()
        self._last()
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(lambda: self.refresh(False))
        self.timer.start()
        QTimer.singleShot(0, lambda: self.refresh(True))

    def _paths(self):
        self.source_label.setText(self.settings.source or 'Choose a PC library in Settings')
        self.phone_group.setTitle(self.settings.device_name or 'Phone · setup required')
        self.settings_button.setText('Settings…' if self.settings.configured else
                                     ('Choose Library…' if self.settings.device_id else 'Choose Device…'))
        if not self.settings.configured:
            self.status_label.setText('Choose your PC library and a KDE Connect device in Settings to get started.')
        self._buttons(True)
        self.remote_label.setText(self.settings.remote_dir)
        self.gain_label.setText(f'ReplayGain: {"Enabled · independent tracks · skip existing tags · " + str(self.settings.threads) + " workers" if self.settings.replaygain else "Disabled"}')
        self.sync_group.setTitle('Synchronization · ' + ('Mirror PC → Phone' if self.settings.mirror else 'Update only · PC → Phone'))
        self.ignored_label.setText('Ignored and protected: ' + ', '.join(self.settings.exclusions))

    def _last(self):
        try:
            record = json.loads((state_dir() / 'last-sync.json').read_text())
            self.last_label.setText(f'Last successful sync: {record["at"]} · {record["device_name"]}')
            self.last_label.setToolTip(f'{record["source"]} → {record["destination"]}\nAdded {record["added"]} · Updated {record["updated"]} · Removed {record["removed"]}')
        except FileNotFoundError:
            self.last_label.setText('Last successful sync: not yet synchronized with this app')
        except (OSError, ValueError, KeyError, TypeError):
            self.last_label.setText('Last successful sync: history unavailable')

    def refresh(self, scan):
        if not self.controller.active and not self.status_service.active:
            self._buttons(False)
            self.status_service.refresh(self.settings, scan)

    def _status(self, data):
        self.devices = data.get('devices', self.devices)
        self.device_label.setText(data.get('device_status', 'Unknown connection state'))
        self.filesystem_label.setText(data.get('filesystem', ''))
        if 'library' in data:
            self._library(data['library'])
        if 'library_error' in data:
            self.library_label.setText('Library unavailable or empty')
            self._log(data['library_error'])
        if 'error' in data:
            self._log(data['error'])
        logging.getLogger('musicsync').info('Device status: %s; filesystem: %s', data.get('device_status'), data.get('filesystem'))
        self._buttons(True)
        if self.closing:
            self.close()

    def _buttons(self, enabled):
        for button in [self.settings_button, self.refresh_button]:
            button.setEnabled(enabled)
        for button in [self.preview_button, self.sync_button]:
            button.setEnabled(enabled and self.settings.configured)

    def _library(self, data):
        self.library_label.setText(f'{data["tracks"]:,} tracks · {size_text(data["bytes"])}' + (f' · {data["count"]:,} total files' if data['count'] != data['tracks'] else ''))

    def _start(self, preview):
        self._buttons(False)
        self.cancel_button.show()
        self.cancel_button.setEnabled(True)
        self.counts = {'Add': 0, 'Update': 0, 'Delete': 0}
        self.transfer_label.setText('')
        self.table.setRowCount(0)
        self.summary_label.setText('')
        self.controller.start(self.settings, preview)

    def _state(self, state, message):
        self.status_label.setText(message)
        active = self.controller.active
        self.progress_bar.setVisible(active)
        self.progress_bar.setRange(0, 0)
        if state == State.RECONNECTING:
            self.filesystem_label.setText('Filesystem stale · reconnecting once')
        elif state == State.MOUNTING:
            self.filesystem_label.setText('Mounting filesystem…')
        elif state in {State.PREVIEWING, State.SYNCING}:
            self.device_label.setText('Connected')
            self.filesystem_label.setText('Filesystem mounted and validated')
        elif state == State.UNMOUNTING:
            self.cancel_button.setEnabled(False)
            self.filesystem_label.setText('Unmounting app-created filesystem…')

    def _preview(self, summary):
        self.table.setRowCount(len(summary.changes))
        for row, change in enumerate(summary.changes):
            for col, text in enumerate([change.action, clean(change.path), 'Folder' if change.directory else size_text(change.size)]):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.summary_label.setText('    '.join(f'{action}: {summary.count(action)} files · {size_text(summary.size(action))}' for action in ['Add', 'Update', 'Delete']))

    def _approve(self, approval):
        count = approval.summary.count('Delete')
        box = self.approval_dialog = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle('Large deletion from phone')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f'This synchronization will remove {count} files from {self.settings.device_name}.')
        box.setInformativeText(f'{count} of {approval.phone_files} phone-side files will be removed, plus {approval.summary.deletions - count} folders.\n\nThe PC library is authoritative. Review the Delete rows before proceeding. Local files will not be deleted.')
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText(f'Remove {count} files and sync')
        box.button(QMessageBox.StandardButton.No).setText('Cancel synchronization')
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setDetailedText('\n'.join(clean(change.path) for change in approval.summary.changes if change.action == 'Delete'))
        box.finished.connect(lambda result: self.controller.approve(result == QMessageBox.StandardButton.Yes))
        box.open()

    def _progress(self, progress):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(progress['percent'])
        self.progress_bar.setFormat(f'{progress["percent"]}% · {progress["bytes_display"]} transferred · {progress["speed"]}')

    def _change(self, change):
        if not change.directory:
            self.counts[change.action] += 1
        self.transfer_label.setText(f'{change.action}: {clean(change.path)}\nAdded {self.counts["Add"]} · Updated {self.counts["Update"]} · Removed {self.counts["Delete"]}')

    def _complete(self, outcome):
        # Closing the main window while approval is pending cancels the workflow;
        # its independent modal dialog must also close after cleanup completes.
        if hasattr(self, 'approval_dialog') and self.approval_dialog.isVisible():
            self.approval_dialog.reject()
        self.cancel_button.hide()
        self.progress_bar.hide()
        self._buttons(True)
        if outcome.success:
            self._preview(outcome.summary)
            if not outcome.summary.changes:
                comparison = 'Libraries match.' if self.settings.mirror else 'Phone copies are up to date; extra phone files are retained in update-only mode.'
                self.status_label.setText(comparison + (' Preview only; ReplayGain was not run.' if outcome.preview else ' Synchronization complete and verified.'))
            self._last()
        elif not outcome.cancelled:
            self.filesystem_label.setText('Operation stopped · see error below')
            if 'is not connected' in outcome.message:
                self.device_label.setText('Disconnected')
            elif 'remote filesystem is not responding' in outcome.message:
                self.filesystem_label.setText('Filesystem unavailable · restart KDE Connect on phone')
            self._log(outcome.message)
        if outcome.cleanup_warning:
            self.status_label.setText(self.status_label.text() + '\nCleanup/history warning: ' + outcome.cleanup_warning)
            self._log(outcome.cleanup_warning)
        if not outcome.cleanup_warning and self.controller.workflow.mount is not None:
            if State.UNMOUNTING in self.controller.history and not self.controller.workflow.owned:
                self.filesystem_label.setText('Not mounted · app-created filesystem cleaned up')
            elif outcome.success:
                self.filesystem_label.setText('Existing filesystem left mounted')
        if self.closing:
            self.close()

    def _log(self, text):
        self.log.appendPlainText(clean(text))

    def _settings(self):
        dialog = SettingsDialog(self.settings, self.devices, self)
        if dialog.exec() and dialog.value:
            self.settings = dialog.value
            self._paths()
            self.table.setRowCount(0)
            self.summary_label.setText('')
            self.status_label.setText('Settings changed. Preview to compare these libraries.')
            self.refresh(True)

    def closeEvent(self, event):
        if self.controller.active:
            self.closing = True
            self.controller.cancel()
            event.ignore()
        elif self.status_service.active:
            self.closing = True
            self.status_service.runner.cancel()
            event.ignore()
        else:
            self.timer.stop()
            event.accept()
