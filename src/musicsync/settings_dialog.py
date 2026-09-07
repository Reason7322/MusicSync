from dataclasses import replace
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)


class SettingsDialog(QDialog):
    def __init__(self, settings, devices, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Music Sync Settings')
        self.setMinimumWidth(570)
        self.original = settings
        self.value = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.source = QLineEdit(settings.source)
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source)
        source_row.addWidget(browse)
        form.addRow('PC library', source_row)
        self.devices = QComboBox()
        if settings.device_id:
            self.devices.addItem(f'{settings.device_name} (configured)', (settings.device_id, settings.device_name))
        else:
            self.devices.addItem('Select a connected device…', None)
        for device in devices:
            if device.id != settings.device_id:
                self.devices.addItem(device.name, (device.id, device.name))
        self.devices.currentIndexChanged.connect(self._device)
        form.addRow('Available devices', self.devices)
        self.device_id = QLineEdit(settings.device_id)
        self.device_name = QLineEdit(settings.device_name)
        form.addRow('Device ID', self.device_id)
        form.addRow('Device name', self.device_name)
        self.remote = QLineEdit(settings.remote_dir)
        form.addRow('Phone directory', self.remote)
        self.gain = QCheckBox('Normalize tracks independently; skip existing tags')
        self.gain.setChecked(settings.replaygain)
        form.addRow('ReplayGain', self.gain)
        self.preset = QLineEdit(settings.preset)
        form.addRow('ReplayGain preset', self.preset)
        self.threads = QSpinBox()
        self.threads.setRange(1, 32)
        self.threads.setValue(settings.threads)
        form.addRow('ReplayGain workers', self.threads)
        self.mirror = QCheckBox('Mirror PC library (remove files that exist only on phone)')
        self.mirror.setChecked(settings.mirror)
        form.addRow('Synchronization', self.mirror)
        layout.addLayout(form)
        note = QLabel('Pair and connect your phone using KDE Connect. If it is missing from the list,\nclose Settings and click Refresh, then open Settings again.\nWith mirror disabled, files are added and updated only.\nAndroid’s .thumbnails/ directory is always protected.\nThe selected phone directory must already exist inside /storage/emulated/0.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose PC music library', self.source.text())
        if path:
            self.source.setText(path)

    def _device(self, index):
        device_id, name = self.devices.itemData(index) or ('', '')
        self.device_id.setText(device_id)
        self.device_name.setText(name)

    def _save(self):
        try:
            settings = replace(self.original, source=self.source.text(), device_id=self.device_id.text().strip(),
                               device_name=self.device_name.text().strip(), remote_dir=self.remote.text(),
                               replaygain=self.gain.isChecked(), preset=self.preset.text(), threads=self.threads.value(), mirror=self.mirror.isChecked())
            settings.save()
            self.value = settings
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, 'Settings could not be saved', str(error))
            return
        self.accept()
