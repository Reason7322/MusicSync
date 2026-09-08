"""Read-only asynchronous startup/refresh service; never asks KDE Connect to mount."""
import json
from dataclasses import replace
from PySide6.QtCore import QObject, Signal
from musicsync.backend.kdeconnect import discover, mountpoint, parse_devices
from musicsync.backend.mounts import mount_query, parse_findmnt, validate_mountpoint
from musicsync.backend.process import ProcessRunner
from musicsync.backend.workflow import helper
from musicsync.models import Command
from musicsync.runtime import HOST_TOOLS, appdir


class StatusService(QObject):
    ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner = ProcessRunner(self)
        self.runner.finished.connect(self._next)
        self.active = False

    def refresh(self, settings, scan=True):
        if self.active:
            return
        self.active = True
        self.generator = self._read(settings, scan)
        self._next(None)

    def _read(self, settings, scan):
        status = {}
        if appdir() is not None:
            result = yield helper('dependencies', 'Check host integration requirements', programs=list(HOST_TOOLS))
            if result.code or result.timed_out:
                return {'device_status': 'Host setup incomplete', 'filesystem': result.stderr or 'Host dependency check timed out.',
                        'error': result.stderr or 'Host dependency check timed out.'}
        if scan and not settings.source:
            status['library_error'] = 'Choose a PC music library in Settings.'
        elif scan:
            result = yield helper('source', 'Inspect PC library', timeout=120000, source=settings.source, exclusions=settings.exclusions)
            if result.code == 0 and not result.timed_out:
                status['library'] = json.loads(result.stdout)
            else:
                status['library_error'] = result.stderr or 'Local library scan failed or timed out.'
        result = yield discover()
        if result.code or result.timed_out:
            status['device_status'] = 'Error querying KDE Connect'
            status['error'] = result.stderr or 'KDE Connect did not respond.'
            return status
        devices = parse_devices(result.stdout)
        status['devices'] = devices
        if not settings.device_id:
            status['connected'] = False
            status['device_status'] = 'Choose a device in Settings'
            status['filesystem'] = (f'{len(devices)} available device(s)' if devices else
                                    'Pair and connect your phone in KDE Connect, then Refresh.')
            return status
        status['connected'] = settings.device_id in {d.id for d in devices}
        status['device_status'] = 'Connected' if status['connected'] else 'Disconnected'
        if not status['connected']:
            return status
        result = yield mountpoint(settings.device_id)
        if result.code or result.timed_out:
            status['filesystem'] = 'Filesystem unavailable'
            return status
        target = validate_mountpoint(result.stdout.strip())
        result = yield Command('mountpoint', ['-q', target], label='Inspect mount status')
        if result.code == 1 and not result.timed_out:
            # KDE creates this directory on demand. As in Workflow, distinguish
            # ENOENT from inaccessible paths in a bounded asynchronous worker.
            probe = yield helper('mount_path', 'Inspect absent mountpoint', path=target)
            if probe.code or probe.timed_out:
                status['filesystem'] = 'Filesystem status unavailable'
                status['error'] = probe.stderr or 'Mount path check failed or timed out.'
                return status
            if not json.loads(probe.stdout)['exists']:
                result = replace(result, code=32)
        if result.timed_out or result.code not in (0, 32):
            status['filesystem'] = 'Filesystem status unavailable'
            status['error'] = result.stderr or 'Mount status check failed or timed out.'
            return status
        status['filesystem'] = 'Not mounted · mounted only when needed'
        if result.code == 0:
            result = yield mount_query(target)
            if result.code == 0 and not result.timed_out and parse_findmnt(result.stdout, target).expected:
                status['filesystem'] = 'Filesystem mounted · access checked before syncing'
            else:
                status['filesystem'] = 'Unexpected filesystem · synchronization blocked'
        return status

    def _next(self, result):
        if result is not None and result.cancelled:
            self.generator.close()
            self.active = False
            self.ready.emit({'device_status': 'Status check cancelled'})
            return
        try:
            self.runner.start(self.generator.send(result))
        except StopIteration as done:
            self.active = False
            self.ready.emit(done.value)
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.active = False
            self.ready.emit({'device_status': 'Filesystem status error', 'error': str(error)})
