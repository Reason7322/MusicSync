"""Explicit packaged-runtime checks. Never initiates a real synchronization."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import time

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QLibraryInfo, QObject, Qt, QTimer
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QMessageBox
from musicsync import APP_ID
from musicsync.runtime import HOST_TOOLS, PRIVATE_TOOLS, appdir, compiled_directory, effective_preset, tool_program
from musicsync.settings import Settings, config_dir, state_dir


class _HarnessBoxResponder(QObject):
    """Auto-closes QMessageBoxes while a --bulk-rename-test run is in progress.

    Instantiated ONLY by install_check in that mode. Production code paths never
    auto-answer confirmations; this harness exists so the packaged self-test can
    drive the real explicit Yes/No workflow unattended, offscreen.
    """

    def __init__(self, app, interval_ms: int = 25):
        super().__init__()
        self._app = app
        self.boxes = []           # [{'title', 'text', 'chosen'}]
        self._handled = set()     # ids of boxes already recorded and clicked
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.scan_and_respond)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def scan_and_respond(self):
        for obj in self._app.allWidgets():
            try:
                if not isinstance(obj, QMessageBox) or id(obj) in self._handled \
                        or not obj.isVisible():
                    continue
                title = obj.windowTitle()
                target = None
                chosen = ''
                for standard in (QMessageBox.StandardButton.Yes,
                                 QMessageBox.StandardButton.Ok):
                    button = obj.button(standard)
                    if button is not None and button.isVisible():
                        target = button
                        chosen = 'Yes' if standard == QMessageBox.StandardButton.Yes else 'Ok'
                        break
                if target is None:  # unknown shape: first visible button wins
                    buttons = [b for b in obj.buttons() if b.isVisible()]
                    if buttons:
                        target, chosen = buttons[0], (buttons[0].text() or '?').strip()
                self._handled.add(id(obj))
                self.boxes.append({'title': title, 'text': obj.text()[:500], 'chosen': chosen})
                if target is not None:
                    target.click()
            except RuntimeError:  # C++ object deleted mid-iteration
                continue


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
    flow_scheduled = False

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
                if any(name in line for name in ('/libqt6ct', '/libkvantum', '/libKF6', '/libqgtk3',
                       '/libgtk-3', '/libgdk-3', '/libdconf')) and len(line.split(maxsplit=5)) == 6}))
        if screenshot := os.environ.get('MUSICSYNC_TEST_SCREENSHOT'):
            evidence['screenshot_saved'] = window.grab().save(screenshot)
        print('MUSICSYNC_CHECK=' + json.dumps(evidence, ensure_ascii=True), flush=True)
        window.close()

    def run_bulk_rename_flow():
        """Drive the REAL Settings -> Bulk Rename GUI on an isolated fixture.

        Exists only for --bulk-rename-test (orchestrator-owned process). The
        auto-answering box responder below is part of this harness: production
        code paths never auto-confirm; here the explicit Yes/No workflow is
        exercised unattended exactly as a user would drive it.
        """
        from musicsync.bulk_rename import BulkRenameDialog
        from musicsync.settings_dialog import SettingsDialog
        import musicsync.vendored.engine as engine_module
        from musicsync.vendored.engine import JOURNAL_DIRNAME, list_sessions

        evidence['vendored_engine_file'] = str(getattr(engine_module, '__file__', ''))
        br: dict = {}
        failures: list = []
        st: dict = {'stage': 'open_settings', 'dialog': None, 't0': time.monotonic(),
                    'report_before': None, 'undo_before': None, 'raw': {}}

        library_env = os.environ.get('MUSICSYNC_BULK_RENAME_LIBRARY', '').strip()
        lib = Path(library_env) if library_env else None
        try:
            expect = json.loads(os.environ.get('MUSICSYNC_BULK_EXPECT_JSON', '{}') or '{}')
        except ValueError:
            finish(False, 'MUSICSYNC_BULK_EXPECT_JSON is not valid JSON')
            return
        if lib is None or not lib.is_dir():
            finish(False, 'MUSICSYNC_BULK_RENAME_LIBRARY is missing or not a directory')
            return

        def snapshot_tree(root):
            out = {}
            for dirpath, _dirs, filenames in os.walk(str(root)):
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

        def tree_diff(before, after):
            prefix = JOURNAL_DIRNAME + '/'  # journals/backups preserved by design
            a = {k: v for k, v in before.items() if not k.startswith(prefix)}
            b = {k: v for k, v in after.items() if not k.startswith(prefix)}
            return (sorted(set(a) - set(b)), sorted(set(b) - set(a)),
                    [rel for rel in a.keys() & set(b) if a[rel] != b[rel]])

        def find_widget(cls):
            for widget in app.allWidgets():
                if isinstance(widget, cls):
                    return widget
            return None

        pre = snapshot_tree(lib)
        responder = _HarnessBoxResponder(app)
        responder.start()
        timer = QTimer(window)
        done_flag = {'closed': False}

        def conclude():
            if done_flag['closed']:
                return False
            done_flag['closed'] = True
            timer.stop()
            responder.stop()
            evidence['bulk_rename'] = br
            error = '' if not failures else ('; '.join(failures))[:1000]
            dialog = st.get('dialog')
            if dialog is not None:
                try:
                    dialog.close()  # unwind the rename/settings exec chain
                except RuntimeError:
                    pass
            finish(not failures, error)
            return True

        def verify_on_disk_after_apply(report):
            applied = dict(report.applied)
            items_by_rel = {item.rel_path: item for item in st['preview_items']}
            problems = []
            for rel, new_name in sorted(applied.items()):
                item = items_by_rel.get(rel)
                if item is None:
                    problems.append(f'applied rel not in preview: {rel}')
                    continue
                old_path = lib / rel
                new_path = lib / (new_name or rel) if new_name else old_path
                if not new_path.is_file():
                    problems.append(f'missing after apply: {new_name or rel}')
                    continue
                if new_name and new_name != item.current_name:
                    expected = expect.get('proposals', {}).get(rel)
                    if expected is not None and new_name != expected:
                        problems.append(f'{rel}: renamed to {new_name!r}, expected {expected!r}')
                    if old_path.exists():
                        problems.append(f'old name still present: {rel}')
                if item.tag_edits:
                    from musicsync.vendored.tags import read_tag_snapshot
                    snap = read_tag_snapshot(new_path)
                    for frame, _old, new in item.tag_edits:
                        if frame == 'TIT2' and (not snap.titles or snap.titles[0] != new):
                            problems.append(f'{rel}: TIT2 not {new!r} on disk')
                        elif frame == 'TPE1' and (not snap.artists or snap.artists[0] != new):
                            problems.append(f'{rel}: TPE1 not {new!r} on disk')
                    raw_before = st['raw'].get(rel)
                    if raw_before is not None:
                        frame_bytes = 8 * 417
                        if not new_path.read_bytes().endswith(raw_before[-frame_bytes:]):
                            problems.append(f'{rel}: audio frames changed by tag edit')
                else:
                    digest = hashlib.sha256(new_path.read_bytes()).hexdigest()
                    if pre.get(rel) is None or digest != pre[rel][0]:
                        problems.append(f'{rel}: rename-only file bytes changed')
            for rel, code in sorted(dict(report.rejected).items()):
                want = expect.get('rejected_codes', {}).get(rel)
                if want is not None and code != want:
                    problems.append(f'rejected code for {rel} is {code!r}, expected {want!r}')
            return problems

        def tick():
            stage = st['stage']
            dialog = st.get('dialog')
            if time.monotonic() - st['t0'] > 150 and not done_flag['closed']:
                failures.append(f'flow timed out in stage {stage!r} (boxes: {[b["title"] for b in responder.boxes]})')
                conclude()
                return
            try:
                if stage == 'open_settings':
                    st['stage'] = 'find_settings'
                    if not window.settings_button.isEnabled():
                        failures.append('settings button is disabled')
                        conclude()
                        return
                    # Enter the modal chain from an idle event-loop slot, NOT from this
                    # timer callback: on PySide6 6.11.2 (offscreen) a QTimer whose timeout
                    # handler synchronously enters QDialog.exec() gets no further timeouts
                    # dispatched for its whole nested-exec lifetime, freezing every later
                    # stage. Deferred via singleShot(0): the click still blocks until the
                    # Settings -> Bulk Rename chain closes, but tick() has returned first,
                    # so this timer keeps firing inside each nested event loop.
                    def _open_settings_chain():
                        try:
                            window.settings_button.click()  # blocks until the whole chain closes
                        except RuntimeError as error:
                            failures.append(f'settings click failed: {error}')
                            conclude()
                    QTimer.singleShot(0, _open_settings_chain)
                elif stage == 'find_settings':
                    settings_dialog = find_widget(SettingsDialog)
                    if settings_dialog is not None and not st.get('settings_done'):
                        if str(settings_dialog.source.text()) != str(lib):
                            settings_dialog.source.setText(str(lib))
                        if not settings_dialog.bulk_rename_button.isEnabled():
                            failures.append('Bulk Rename button disabled for library ' + str(lib))
                            conclude()
                            return
                        settings_dialog.bulk_rename_button.click()  # saves phone-free, accepts
                        st['settings_done'] = True
                        st['stage'] = 'find_rename'
                elif stage == 'find_rename':
                    if dialog is None:
                        candidate = find_widget(BulkRenameDialog)
                        if candidate is not None and str(candidate.source) == str(lib):
                            st['dialog'] = candidate
                            st['report_before'] = candidate.report
                            st['stage'] = 'wait_scan'
                elif stage == 'wait_scan':
                    if dialog.busy:
                        return
                    if dialog.preview is None:
                        failures.append('initial scan finished without a preview')
                        conclude()
                        return
                    preview = dialog.preview
                    st['preview_items'] = list(preview.items)
                    for rel in [i.rel_path for i in preview.items if i.tag_edits]:
                        try:
                            raw = (lib / rel).read_bytes()
                            if sum(len(v) for v in st['raw'].values()) + len(raw) <= 20 * 1024 * 1024:
                                st['raw'][rel] = raw
                        except OSError:
                            pass
                    defaults = dialog._checked_rels()
                    br.update(counts_by_status=dict(preview.counts_by_status),
                              item_count=preview.item_count,
                              collisions=[{'kind': c.kind, 'directory': c.directory,
                                           'involved': sorted(c.involved)} for c in preview.collisions],
                              default_checked=list(defaults))
                    if defaults:
                        failures.append(f'rows pre-approved by default: {defaults}')
                    dialog.select_all_button.click()
                    approved = set(dialog._checked_rels())
                    br['approved_after_select_all'] = sorted(approved)
                    want_checkable = expect.get('checkable')
                    if want_checkable is not None and approved != set(want_checkable):
                        failures.append(f'approvable set {sorted(approved)} != expected {sorted(set(want_checkable))}')
                    st['report_before'] = dialog.report
                    st['stage'] = 'apply'
                elif stage == 'apply':
                    dialog.apply_button.click()  # confirmation auto-Yes via responder
                    st['stage'] = 'wait_apply'
                elif stage == 'wait_apply':
                    if dialog.busy or dialog.report is None or dialog.report is st['report_before']:
                        return
                    report = dialog.report
                    br.update(applied=dict(report.applied), rejected=dict(report.rejected),
                              partial=dict(report.partial), canceled=list(report.canceled),
                              session_id=report.session_id, ok=report.ok)
                    want_applied = expect.get('applied')
                    if want_applied is not None and set(dict(report.applied)) != set(want_applied):
                        failures.append(f"applied set {sorted(dict(report.applied))} != expected {sorted(set(want_applied))}")
                    problems = verify_on_disk_after_apply(report)
                    failures.extend(problems)
                    if report.session_id:
                        sessions_table = dialog.sessions_table
                        row = -1
                        # Row cells show a display number; the real session id
                        # is stored as item data (Mission 20 UI change).
                        for r in range(sessions_table.rowCount()):
                            cell = sessions_table.item(r, 0)
                            if cell is not None and str(cell.data(Qt.ItemDataRole.UserRole)) == report.session_id:
                                row = r
                                break
                        if row < 0:
                            failures.append(f'session {report.session_id} missing from Sessions tab')
                            conclude()
                            return
                        sessions_table.selectRow(row)
                        dialog.undo_button.click()  # undo confirmation auto-Yes via responder
                        st['undo_before'] = dialog.undo_report
                        st['stage'] = 'wait_undo'
                    else:
                        br['session_id'] = ''
                        conclude()
                elif stage == 'wait_undo':
                    if dialog.busy or dialog.undo_report is None or dialog.undo_report is st['undo_before']:
                        return
                    undo = dialog.undo_report
                    after = snapshot_tree(lib)
                    missing, extra, changed = tree_diff(pre, after)
                    states = {s.get('session_id'): s.get('state') for s in list_sessions(str(lib))}
                    br.update(undo_restored=list(undo.restored), undo_anomalies=[list(a) for a in undo.anomalies],
                              session_state_after_undo=states.get(st['dialog'].report.session_id),
                              tree_missing=missing, tree_extra=extra, tree_changed=changed)
                    if missing or extra or changed:
                        failures.append(f'tree not restored exactly: missing={missing} extra={extra} changed={changed}')
                    if states.get(dialog.report.session_id) != 'undone':
                        failures.append('session is not marked undone after undo')
                    conclude()
            except RuntimeError as error:  # C++ object deleted mid-flow
                failures.append(f'flow crashed in stage {stage!r}: {error}')
                conclude()
                return
            except Exception as error:
                failures.append(f'flow failed in stage {stage!r}: {type(error).__name__}: {error}')
                conclude()
                return

        timer.timeout.connect(tick)
        timer.setInterval(25)
        timer.start()

    def ready(status):
        nonlocal triggered, flow_scheduled
        if mode == '--bulk-rename-test':
            # The bulk rename flow is phone-independent; it drives its own timers.
            evidence.setdefault('device_status', status.get('device_status'))
            if not flow_scheduled:
                flow_scheduled = True
                QTimer.singleShot(150, run_bulk_rename_flow)
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
