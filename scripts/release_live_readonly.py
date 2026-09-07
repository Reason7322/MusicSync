"""Read-only configured-device release check. NEVER mounts, unmounts, probes writes or tags.

Requires an already healthy mounted device; otherwise reports PARTIAL and stops.
All actual rsync invocations are guarded dry-runs. Evidence is written only in docs.
"""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + os.environ.get('PYTHONPATH', '')
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from musicsync.backend.kdeconnect import discover, mountpoint, parse_devices
from musicsync.backend.mounts import mount_query, parse_findmnt, validate_mountpoint
from musicsync.backend.process import ProcessRunner
from musicsync.backend.workflow import helper
from musicsync.models import Command
from musicsync.settings import Settings, state_dir

app = QCoreApplication([])
evidence = {'at': datetime.now().astimezone().isoformat(timespec='seconds'), 'scope': 'Real configured device, read-only; no mount/unmount/ReplayGain/write probe/real sync', 'checks': []}


def run(command):
    runner, loop, results = ProcessRunner(), QEventLoop(), []
    runner.finished.connect(lambda result: (results.append(result), loop.quit()))
    runner.start(command)
    loop.exec()
    result = results[0]
    entry = {'check': command.label, 'status': 'PASS' if result.code == 0 and not result.timed_out else 'FAIL', 'exit_code': result.code}
    if result.stderr:
        entry['stderr'] = result.stderr
    evidence['checks'].append(entry)
    if result.code != 0 or result.timed_out:
        raise RuntimeError(command.label + ': ' + result.stderr)
    return result.stdout


def main():
    settings = Settings.load()
    settings.validate()
    last = state_dir() / 'last-sync.json'
    previous = last.read_bytes() if last.exists() else None
    connected = parse_devices(run(discover()))
    if settings.device_id not in {d.id for d in connected}:
        raise RuntimeError('Configured device is disconnected; no recovery attempted.')
    evidence['device'] = settings.device_name
    target = validate_mountpoint(run(mountpoint(settings.device_id)).strip())
    run(Command('mountpoint', ['-q', target], label='Require an already mounted device'))
    mount = parse_findmnt(run(mount_query(target)), target)
    if not mount.expected:
        raise RuntimeError('Unexpected filesystem; left untouched.')
    remote = dict(mountpoint=target, mount_id=mount.id, remote=settings.remote_dir, exclusions=settings.exclusions)
    run(helper('storage', 'Read Android shared storage', **remote))
    before_source = json.loads(run(helper('source', 'Read PC inventory before preview', timeout=120000, source=settings.source, exclusions=settings.exclusions)))
    before_phone = json.loads(run(helper('destination', 'Read phone inventory before preview', timeout=120000, **remote)))
    output = run(helper('rsync', 'Guarded real-phone DRY RUN', timeout=120000, settings=asdict(settings), dry_run=True, source_digest=before_source['digest'], destination_digest=before_phone['digest'], **remote))
    evidence['rsync_dry_run_output'] = output
    after_source = json.loads(run(helper('source', 'Read PC inventory after preview', timeout=120000, source=settings.source, exclusions=settings.exclusions)))
    after_phone = json.loads(run(helper('destination', 'Read phone inventory after preview', timeout=120000, **remote)))
    after_mount = parse_findmnt(run(mount_query(target)), target)
    for name, passed in [('PC inventory unchanged', before_source == after_source), ('Phone inventory unchanged', before_phone == after_phone), ('Borrowed mount identity unchanged', mount == after_mount), ('Last-success history bytes unchanged', previous == (last.read_bytes() if last.exists() else None))]:
        evidence['checks'].append({'check': name, 'status': 'PASS' if passed else 'FAIL'})
        if not passed:
            raise RuntimeError(name + ': external change detected during read-only test')
    evidence.update(status='PASS', source_files=before_source['count'], phone_files=before_phone['count'], source_bytes=before_source['bytes'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        evidence.update(status='PARTIAL', reason=str(error))
    path = ROOT / 'docs/release-live-readonly.json'
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=True) + '\n')
    print(json.dumps(evidence, indent=2, ensure_ascii=True))
    raise SystemExit(0 if evidence['status'] == 'PASS' else 1)
