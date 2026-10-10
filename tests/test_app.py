from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtGui import QIcon
from musicsync import APP_ID, app as application
from test_process import APP


class ApplicationIconTests(unittest.TestCase):
    def test_theme_lookup_uses_app_id_and_bundled_svg_fallback(self):
        themed_icon = QIcon()
        with patch.object(application, 'QApplication') as constructor, \
                patch.object(application, 'QIcon', wraps=QIcon) as icons, \
                patch.object(application, 'QLockFile') as lock, \
                patch.object(application, 'QMessageBox'):
            # Stop after icon setup, before settings, logging or device access.
            lock.return_value.tryLock.return_value = False
            icons.fromTheme.return_value = themed_icon
            self.assertEqual(application.main(), 1)
            bundled_path = Path(application.__file__).parent / 'icons' / f'{APP_ID}.svg'
            icons.assert_called_once_with(str(bundled_path))
            icons.fromTheme.assert_called_once()
            name, fallback = icons.fromTheme.call_args.args
            self.assertEqual(name, APP_ID)
            self.assertIsInstance(fallback, QIcon)
            self.assertFalse(fallback.isNull())
            constructor.return_value.setWindowIcon.assert_called_once_with(themed_icon)
