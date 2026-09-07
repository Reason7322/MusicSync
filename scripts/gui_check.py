"""Show the real Widgets window, optionally click Preview, save a Qt window grab.

Run separately from QCoreApplication-based unit tests. Never clicks Sync.
"""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ['PYTHONPATH'] = sys.path[0] + os.pathsep + os.environ.get('PYTHONPATH', '')
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from musicsync import APP_ID
from musicsync.logging import setup_logging
from musicsync.main_window import MainWindow
from musicsync.settings import Settings

parser = argparse.ArgumentParser()
parser.add_argument('--preview', action='store_true')
parser.add_argument('--output', default='/tmp/musicsync-window.png')
args = parser.parse_args()
settings = Settings.load()
if args.preview:
    settings.validate()
app = QApplication([])
app.setDesktopFileName(APP_ID)
app.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[1] / 'src/musicsync/icons' / f'{APP_ID}.svg')))
setup_logging()
window = MainWindow(settings)
window.show()
print('Qt platform:', app.platformName(), flush=True)
triggered = False


def capture():
    print('Status:', window.status_label.text(), flush=True)
    print('Device:', window.device_label.text(), flush=True)
    print('Library:', window.library_label.text(), flush=True)
    assert not window.styleSheet()
    assert window.grab().save(args.output)
    print('Screenshot:', args.output, flush=True)
    window.close()


def ready(data):
    global triggered
    if triggered:
        return
    triggered = True
    if args.preview:
        QTest.mouseClick(window.preview_button, Qt.MouseButton.LeftButton)
    else:
        QTimer.singleShot(500, capture)


window.status_service.ready.connect(ready)
window.controller.completed.connect(lambda outcome: QTimer.singleShot(500, capture))
QTimer.singleShot(180000, window.close)
raise SystemExit(app.exec())
