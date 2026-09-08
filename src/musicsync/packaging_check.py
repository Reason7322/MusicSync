"""Explicit packaged-runtime checks. Never initiates a real synchronization."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import shutil

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QLibraryInfo, QTimer
from PySide6.QtGui import QIcon, QPalette
from musicsync import APP_ID
from musicsync.runtime import HOST_TOOLS, PRIVATE_TOOLS, appdir, compiled_directory, effective_preset, tool_program
from musicsync.settings import Settings, config_dir, state_dir


def runtime_info():
    # QLibraryInfo reports Qt's logical layout, which may differ from Nuitka's
    # flattened library directory. Kernel mappings prove which ELF files loaded.
    qt_mappings = sorted({line.split(maxsplit=5)[5].strip()
                          for line in Path('/proc/self/maps').read_text().splitlines()
                          if '/libQt6' in line and len(line.split(maxsplit=5)) == 6})
    return dict(application_id=APP_ID, python=platform.python_version(), pyside=pyside_version,
                frozen=compiled_directory() is not None, appdir=str(appdir()),
                qt_libraries=QLibraryInfo.path(QLibraryInfo.LibraryPath.LibrariesPath),
                loaded_qt_libraries=qt_mappings,
                tools={name: shutil.which(tool_program(name)) for name in HOST_TOOLS + PRIVATE_TOOLS},
                preset=effective_preset(Settings().preset), config=str(config_dir()), state=str(state_dir()))


def install_check(app, window, mode):
    """Retained by the window; timers close through normal cancel/cleanup behavior."""
    evidence = runtime_info()
    evidence.update(qt_platform=app.platformName(), preview=mode == '--preview-test', result='FAIL')
    history = state_dir() / 'last-sync.json'
    before = history.read_bytes() if history.exists() else None
    triggered = False

    def finish(success, error=''):
        after = history.read_bytes() if history.exists() else None
        evidence.update(result='PASS' if success and before == after else 'FAIL', error=error,
                        history_unchanged=before == after, visible=window.isVisible(),
                        source=window.settings.source, configured=window.settings.configured)
        style = app.style()
        evidence['appearance'] = dict(
            platform_theme=os.environ.get('QT_QPA_PLATFORMTHEME'),
            platform_request=os.environ.get('QT_QPA_PLATFORM'),
            style_override=os.environ.get('QT_STYLE_OVERRIDE'),
            style=style.objectName(), style_class=style.metaObject().className(),
            icon_theme=QIcon.themeName(), font=app.font().toString(),
            palette={role: app.palette().color(getattr(QPalette.ColorRole, role)).name()
                     for role in ('Window', 'WindowText', 'Base', 'Text', 'Button',
                                  'ButtonText', 'Highlight', 'HighlightedText')},
            loaded_theme_libraries=sorted({line.split(maxsplit=5)[5].strip()
                for line in Path('/proc/self/maps').read_text().splitlines()
                if any(name in line for name in ('/libqt6ct', '/libKF6', '/libqgtk3',
                       '/libgtk-3', '/libgdk-3', '/libdconf')) and len(line.split(maxsplit=5)) == 6}))
        if screenshot := os.environ.get('MUSICSYNC_TEST_SCREENSHOT'):
            evidence['screenshot_saved'] = window.grab().save(screenshot)
        print('MUSICSYNC_CHECK=' + json.dumps(evidence, ensure_ascii=True), flush=True)
        window.close()

    def ready(status):
        nonlocal triggered
        if triggered:
            return
        triggered = True
        evidence['device_status'] = status.get('device_status')
        if 'error' in status:
            finish(False, status['error'])
        elif mode == '--preview-test':
            if not window.settings.configured:
                finish(False, 'Configure a library and phone in Settings before preview testing.')
                return
            window.preview_button.click()
        else:
            QTimer.singleShot(300, lambda: finish(True))

    def completed(outcome):
        evidence['outcome'] = asdict(outcome)
        finish(outcome.success and not outcome.cleanup_warning, outcome.message)

    window.status_service.ready.connect(ready)
    window.controller.completed.connect(completed)
    window.packaging_check = evidence
    QTimer.singleShot(180000, window.close)
