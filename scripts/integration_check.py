"""Explicit developer integration check. Defaults to read-only music preview.

--sync uses the configured real library; never approves a large deletion prompt.
It runs exactly the same QProcess controller as the GUI. No fallback shell script.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ['PYTHONPATH'] = sys.path[0] + os.pathsep + os.environ.get('PYTHONPATH', '')

from PySide6.QtCore import QCoreApplication, QLockFile, QStandardPaths, QTimer
from musicsync import APP_ID
from musicsync.backend.sync_controller import SyncController
from musicsync.logging import setup_logging
from musicsync.settings import Settings

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sync', action='store_true')
args = parser.parse_args()
app = QCoreApplication([])
lock = QLockFile(str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)) / f'{APP_ID}.lock'))
lock.setStaleLockTime(0)
if not lock.tryLock(0):
    raise SystemExit('Close the running Music Sync instance first.')
setup_logging()
controller = SyncController()
controller.state_changed.connect(lambda state, text: print(f'{state}: {text}', flush=True))
controller.log_line.connect(lambda text: print(text, flush=True))
controller.approval_needed.connect(lambda approval: controller.approve(False))
result_code = 1


def complete(outcome):
    global result_code
    print(json.dumps(asdict(outcome), indent=2, ensure_ascii=True), flush=True)
    result_code = 0 if outcome.success and not outcome.cleanup_warning else 1
    app.quit()


controller.completed.connect(complete)
QTimer.singleShot(0, lambda: controller.start(Settings.load(), preview=not args.sync))
QTimer.singleShot(180000, controller.cancel)
app.exec()
raise SystemExit(result_code)
