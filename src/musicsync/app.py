from pathlib import Path
import sys
from PySide6.QtCore import QLockFile, QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from musicsync import APP_ID, __version__
from musicsync.logging import setup_logging
from musicsync.main_window import MainWindow
from musicsync.settings import Settings


def main(test_mode=None):
    app = QApplication(sys.argv)
    app.setApplicationName('Music Sync')
    app.setApplicationVersion(__version__)
    app.setOrganizationName('MusicSync')
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / 'icons' / f'{APP_ID}.svg')))
    runtime = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
    lock = QLockFile(str(Path(runtime) / f'{APP_ID}.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, 'Music Sync is already running', 'Use the existing Music Sync window. Only one instance may synchronize at a time.')
        return 1
    try:
        logger = setup_logging()
        logger.info('Music Sync %s startup; Qt platform=%s', __version__, app.platformName())
        settings = Settings.load()
    except (OSError, ValueError, TypeError) as error:
        QMessageBox.critical(None, 'Music Sync configuration error', str(error))
        return 1
    window = MainWindow(settings)
    if test_mode:
        from musicsync.packaging_check import install_check
        install_check(app, window, test_mode)
    window.show()
    code = app.exec()
    if test_mode:
        return 0 if window.packaging_check['result'] == 'PASS' else 1
    return code


if __name__ == '__main__':
    raise SystemExit(main())
