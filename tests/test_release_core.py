"""Release matrix: real temporary files plus explicit mount/command simulations."""
from dataclasses import asdict, replace
import errno
import json
import logging
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch

from musicsync.backend import filesystem as fs
from musicsync.backend.mounts import Mount, parse_findmnt, validate_mountpoint
from musicsync.backend.replaygain import processed_tracks
from musicsync.backend.rsync import parse_change, parse_progress
from musicsync.backend.worker import execute
from musicsync.backend.workflow import Workflow
from musicsync.logging import clean, setup_logging
from musicsync.models import Result, State
from fixtures import ConfiguredSettings as Settings
from musicsync.settings import atomic_json, suspicious_deletions
from test_workflow import Simulation


class SourceDestinationReleaseTests(unittest.TestCase):
    def test_source_zero_byte_file_is_a_file_but_directories_and_exclusions_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'empty-dir').mkdir()
            (root / '.thumbnails').mkdir()
            (root / '.thumbnails/cache').write_text('cache')
            with self.assertRaisesRegex(OSError, 'zero files'):
                fs.inventory(root, ['/.thumbnails/'], True)
            (root / 'zero.mp3').touch()
            self.assertEqual(fs.inventory(root, ['/.thumbnails/'], True)['count'], 1)

    def test_unreadable_subtree_aborts_instead_of_becoming_deletions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'good.mp3').write_text('music')
            hidden = root / 'unreadable'
            hidden.mkdir()
            (hidden / 'song').write_text('music')
            hidden.chmod(0)
            try:
                with self.assertRaises(PermissionError):
                    fs.inventory(root, require_files=True)
            finally:
                hidden.chmod(0o700)

    def test_symlink_roots_files_directories_and_dangling_links_rejected(self):
        for target in ['file', 'directory', 'missing']:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'file').touch()
                (root / 'directory').mkdir()
                (root / 'link').symlink_to(root / target)
                with self.assertRaises(OSError):
                    fs.inventory(root)
                with self.assertRaises(OSError):
                    fs.inventory(root / 'link')

    def test_fifo_and_unix_socket_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkfifo(tmp + '/fifo')
            with self.assertRaisesRegex(OSError, 'special file'):
                fs.inventory(tmp)
            os.unlink(tmp + '/fifo')
            with socket.socket(socket.AF_UNIX) as sock:
                sock.bind(tmp + '/socket')
                with self.assertRaisesRegex(OSError, 'special file'):
                    fs.inventory(tmp)

    def test_remote_missing_not_created_and_symlink_components_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            fd = os.open(tmp, os.O_DIRECTORY)
            identity = Mount(tmp, 'fuse.sshfs', 'kdeconnect@host:/', fs.fd_mount_id(fd))
            os.close(fd)
            with patch.object(fs, 'current_mount', return_value=identity):
                with self.assertRaises(FileNotFoundError):
                    with fs.remote_directory(tmp, '/storage/emulated/0/Music', identity.id):
                        self.fail('missing destination accepted')
                self.assertFalse((target / 'storage').exists())
                (target / 'storage').symlink_to('/tmp')
                with self.assertRaises(OSError):
                    with fs.remote_directory(tmp, '/storage', identity.id):
                        self.fail('symlink destination accepted')

    def test_remote_identity_and_nested_mount_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'storage').mkdir()
            mount = Mount(tmp, 'fuse.sshfs', 'kdeconnect@host:/', 123)
            for ids in [[124], [123, 124]]:
                with self.subTest(ids=ids), patch.object(fs, 'current_mount', return_value=mount), patch.object(fs, 'fd_mount_id', side_effect=ids):
                    with self.assertRaises(OSError):
                        with fs.remote_directory(tmp, '/storage', 123):
                            self.fail('mount identity mismatch accepted')

    def test_remote_readonly_and_delete_denied_probe_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            fd = os.open(tmp, os.O_DIRECTORY)
            try:
                with patch.object(fs.os, 'open', side_effect=OSError(errno.EROFS, 'read-only')):
                    with self.assertRaisesRegex(OSError, 'write/delete test'):
                        fs.write_probe(fd)
                with patch.object(fs.os, 'unlink', side_effect=PermissionError('delete denied')):
                    with self.assertRaisesRegex(OSError, 'delete denied'):
                        fs.write_probe(fd)
                self.assertEqual(len(list(Path(tmp).iterdir())), 1)  # documented orphan on delete denial
            finally:
                os.close(fd)

    def test_current_mount_requires_unique_identity_and_matching_id(self):
        good = '42 1 0:2 / /run/user/1000/device rw - fuse.sshfs kdeconnect@host:/ rw\n'
        cases = ['', good + good, good.replace('fuse.sshfs', 'ext4'), good.replace('kdeconnect@', 'other@')]
        for text in cases:
            with self.subTest(text=text), patch.object(Path, 'read_text', return_value=text):
                with self.assertRaises(OSError):
                    fs.current_mount('/run/user/1000/device', 42)
        with patch.object(Path, 'read_text', return_value=good):
            self.assertEqual(fs.current_mount('/run/user/1000/device', 42).id, 42)
            with self.assertRaises(OSError):
                fs.current_mount('/run/user/1000/device', 43)

    def test_findmnt_malformed_empty_duplicate_wrong_target_fails_closed(self):
        row = {'target': '/run/user/1000/device', 'fstype': 'fuse.sshfs', 'source': 'kdeconnect@host:/', 'id': 42}
        for text in ['bad json', '{}', '{"filesystems": []}', json.dumps({'filesystems': [row, row]}), json.dumps({'filesystems': [dict(row, target='/other')]}), json.dumps({'filesystems': [dict(row, id='bad')]})]:
            with self.subTest(text=text), self.assertRaises((ValueError, KeyError, TypeError)):
                parse_findmnt(text, row['target'])


class WorkflowReleaseTests(unittest.TestCase):
    def simulation(self, **kwargs):
        return Simulation(**kwargs)

    def test_replaygain_disabled_does_not_require_or_invoke_it(self):
        sim = Simulation()
        sim.workflow.settings.replaygain = False
        self.assertTrue(sim.run().success)
        self.assertFalse(any(c.program == 'rsgain' for c in sim.commands))
        dep = json.loads(sim.commands[0].args[2])
        self.assertNotIn('rsgain', dep['programs'])
        self.assertIsNone(dep['preset'])

    def test_preview_does_not_require_preset_or_rsgain(self):
        sim = Simulation(preview=True)
        sim.workflow.settings.preset = '/missing/preset.ini'
        self.assertTrue(sim.run().success)
        dep = json.loads(sim.commands[0].args[2])
        self.assertIsNone(dep['preset'])
        self.assertNotIn('rsgain', dep['programs'])
        for c in sim.commands:
            if c.args[:2] == ['-m', 'musicsync.backend.worker']:
                payload = json.loads(c.args[2])
                self.assertNotEqual(payload['action'], 'probe')
                if payload['action'] == 'rsync':
                    self.assertTrue(payload['dry_run'])

    def test_device_disconnect_at_each_connectivity_gate(self):
        for gate in [1, 2, 3]:
            sim = Simulation()
            original = sim.reply
            seen = 0
            def reply(command):
                nonlocal seen
                if command.label == 'Discover KDE Connect devices':
                    seen += 1
                    if seen == gate:
                        sim.commands.append(command)
                        return Result(0, '')
                return original(command)
            sim.reply = reply
            with self.subTest(gate=gate):
                self.assertIn('not connected', sim.run().message)
                self.assertFalse(sim.sync_ran)

    def test_stale_detach_failure_no_remount_or_sync(self):
        sim = Simulation(mounted=True, stale=True, failure='Detach stale KDE SSHFS')
        self.assertFalse(sim.run().success)
        self.assertEqual(sim.mounts, 0)
        self.assertFalse(sim.sync_ran)

    def test_stale_detach_that_did_not_detach_stops(self):
        sim = Simulation(mounted=True, stale=True)
        original = sim.reply
        def reply(command):
            result = original(command)
            if command.label == 'Detach stale KDE SSHFS':
                sim.mounted = True
            return result
        sim.reply = reply
        self.assertFalse(sim.run().success)
        self.assertEqual(sim.mounts, 0)

    def test_stale_storage_timeout_uses_one_recovery(self):
        sim = Simulation(mounted=True)
        original = sim.reply
        sim.reply = lambda c: Result(-1, timed_out=True) if c.label == 'Probe Android shared storage' else original(c)
        self.assertTrue(sim.run().success)
        self.assertEqual(sim.mounts, 1)

    def test_partial_mount_on_failure_and_cancellation_is_cleaned(self):
        for cancelled in [False, True]:
            sim = Simulation()
            original = sim.reply
            def reply(command):
                result = original(command)
                if command.label == 'Mount KDE Connect filesystem':
                    return Result(-1, stderr='partial mount', cancelled=cancelled)
                return result
            sim.reply = reply
            with self.subTest(cancelled=cancelled):
                outcome = sim.run()
                self.assertFalse(outcome.success)
                self.assertEqual(outcome.cancelled, cancelled)
                self.assertEqual(sim.unmounts, 1)

    def test_partial_unexpected_mount_never_detached(self):
        sim = Simulation()
        original = sim.reply
        def reply(command):
            result = original(command)
            if command.label == 'Mount KDE Connect filesystem':
                sim.fstype = 'ext4'
                return Result(1, stderr='partial unexpected mount')
            return result
        sim.reply = reply
        self.assertFalse(sim.run().success)
        self.assertEqual(sim.unmounts, 0)

    def test_normal_unmount_failure_falls_back_once_to_lazy(self):
        sim = Simulation()
        original = sim.reply
        calls = []
        def reply(command):
            if command.label == 'Unmount app-created KDE SSHFS':
                lazy = json.loads(command.args[2])['lazy']
                calls.append(lazy)
                if not lazy:
                    return Result(1, stderr='busy')
            return original(command)
        sim.reply = reply
        self.assertTrue(sim.run().success)
        self.assertEqual(calls, [False, True])

    def test_cleanup_failure_visible_separately_and_borrowed_failure_untouched(self):
        sim = Simulation(failure='Unmount app-created KDE SSHFS')
        outcome = sim.run()
        self.assertTrue(outcome.success)
        self.assertTrue(outcome.cleanup_warning)
        for label in ['rsync preview', 'rsync mirror', 'Scan phone Music']:
            sim = Simulation(mounted=True, failure=label)
            self.assertFalse(sim.run().success)
            self.assertEqual(sim.unmounts, 0)

    def test_cancellation_at_each_operation_gate(self):
        for label in ['Scan PC library', 'Discover KDE Connect devices', 'Check per-track ReplayGain', 'Get KDE Connect mountpoint', 'Scan phone Music', 'Verify phone write and delete capability', 'rsync preview', 'Final phone write/delete check', 'rsync mirror']:
            with self.subTest(label=label):
                sim = Simulation()
                sim.cancel_at = label
                outcome = sim.run()
                self.assertTrue(outcome.cancelled)
                self.assertFalse(outcome.success)
                self.assertNotIn(State.VERIFYING, sim.states)

    def test_final_verification_detects_remaining_changes(self):
        sim = Simulation()
        original = sim.reply
        def reply(command):
            if command.label == 'rsync preview' and sim.sync_ran:
                return Result(0, 'MUSICSYNC|>f+++++++++|9|new.mp3\n')
            return original(command)
        sim.reply = reply
        outcome = sim.run()
        self.assertFalse(outcome.success)
        self.assertIn('still differ', outcome.message)

    def test_missing_mountpoint_directory_can_be_created_only_by_kdeconnect(self):
        sim = Simulation(preview=True)
        original = sim.reply
        def reply(command):
            if command.label == 'Check existing mount':
                return Result(1)
            if command.label == 'Inspect absent mountpoint':
                return Result(0, '{"exists":false}')
            return original(command)
        sim.reply = reply
        self.assertTrue(sim.run().success)
        self.assertEqual(sim.mounts, 1)

    def test_malformed_preview_aborts_real_sync(self):
        sim = Simulation()
        sim.records = 'MUSICSYNC|BAD|1|song.mp3\n'
        self.assertFalse(sim.run().success)
        self.assertFalse(sim.sync_ran)


class ParsingSettingsReleaseTests(unittest.TestCase):
    def test_unicode_line_separator_is_a_filename_not_a_record_boundary(self):
        workflow = Workflow(Settings(), True)
        names = ['left\u2028right.mp3', 'left\u2029right.mp3', 'left\x85right.mp3']
        workflow.source_inventory = {'files': {name: [8, 0] for name in names}}
        workflow.destination_inventory = {'files': {}}
        records = ''.join(f'MUSICSYNC|>f+++++++++|8|{name}\n' for name in names)
        self.assertEqual([c.path for c in workflow._parse(records).changes], names)

    def test_itemized_directory_delete_metadata_only_update_and_file_size(self):
        records = [('cd+++++++++', 'folder/', 'Add', True), ('*deleting  ', 'folder/', 'Delete', True), ('.f..t......', 'track.mp3', 'Update', False)]
        for code, path, action, directory in records:
            with self.subTest(code=code):
                c = parse_change(f'MUSICSYNC|{code}|123|{path}')
                self.assertEqual((c.action, c.directory, c.size), (action, directory, 123))

    def test_progress_units_and_unrecognized_lines(self):
        for amount, percent, speed in [('1,234', 0, '0.00kB/s'), ('814.44M', 100, '12.5MB/s'), ('1.20G', 42, '1.01GB/s')]:
            data = parse_progress(f' {amount} {percent}% {speed} 0:00:01 (xfr#2, to-chk=1/4)')
            self.assertEqual((data['bytes_display'], data['percent'], data['speed']), (amount, percent, speed))
        for line in ['building file list', '12 MB remaining', '']:
            self.assertIsNone(parse_progress(line))

    def test_deletion_boundary_matrix(self):
        for deleted, total, expected in [(0, 0, False), (1, 1, True), (1, 5, False), (2, 5, True), (49, 1000, False), (50, 1000, True), (20, 100, False), (21, 100, True)]:
            with self.subTest(deleted=deleted, total=total):
                self.assertEqual(suspicious_deletions(deleted, total), expected)

    def test_invalid_settings_matrix_and_remote_traversal(self):
        values = {'source': ['', '/', 'relative', '/tmp/../Music', None], 'device_id': ['', '-flag', 'a/b', 'a b'], 'remote_dir': ['/storage/emulated/0', '/storage/emulated/0/', '/storage/emulated/0/../Music', '/storage/emulated/0/./Music', '/storage/emulated/0//Music', '//storage/emulated/0/Music', '/storage/emulated/0/Music/', '/storage/emulated/0/Music\x00'], 'threads': [0, 33, True, '4'], 'mirror': ['true', 1], 'replaygain': [None, 1], 'exclusions': [[], ['*.mp3'], ['/.thumbnails/', '/a/b/']]}
        for key, items in values.items():
            for value in items:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    replace(Settings(), **{key: value}).validate()

    def test_corrupt_settings_do_not_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            for data in ['{', '[]', '{"unknown":1}', '{"threads":0}']:
                path.write_text(data)
                with self.subTest(data=data), self.assertRaises((ValueError, TypeError)):
                    Settings.load(path)

    def test_atomic_settings_failure_preserves_previous_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text('{"old":true}')
            with patch('musicsync.settings.os.replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    atomic_json(path, {'new': True})
            self.assertEqual(path.read_text(), '{"old":true}')
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_roundtrip_all_settings_and_config_file_permissions(self):
        settings = Settings(source='/tmp/Música and spaces', device_id='test-id', device_name='Test device', remote_dir='/storage/emulated/0/Test music', replaygain=False, threads=8, mirror=False, exclusions=['/.thumbnails/', '/cache/'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config/settings.json'
            settings.save(path)
            self.assertEqual(Settings.load(path), settings)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_missing_tools_and_missing_replaygain_preset(self):
        for tool in ['kdeconnect-cli', 'sshfs', 'rsync', 'rsgain', 'findmnt', 'mountpoint', 'fusermount3']:
            with self.subTest(tool=tool), patch('musicsync.backend.worker.shutil.which', return_value=None):
                with self.assertRaisesRegex(OSError, tool):
                    execute({'action': 'dependencies', 'programs': [tool]})
        with self.assertRaisesRegex(OSError, 'preset does not exist'):
            execute({'action': 'dependencies', 'programs': [], 'preset': '/definitely-missing/preset.ini'})

    def test_replaygain_summary_recognized_or_explicitly_unknown(self):
        for text, expected in [('No files were scanned', False), ('Files Scanned: 3', True), ('\x1b[32mFiles Scanned:\x1b[0m 0', False), ('unrecognized future output', None)]:
            self.assertIs(processed_tracks(text), expected)

    def test_log_location_rotation_and_ansi_cleanup(self):
        logger = logging.getLogger('musicsync')
        original = logger.handlers[:]
        logger.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp, patch('musicsync.logging.state_dir', return_value=Path(tmp)):
            try:
                self.assertIs(setup_logging(), logger)
                self.assertEqual(len(setup_logging().handlers), 1)
                handler = logger.handlers[0]
                handler.maxBytes = 80
                for i in range(10):
                    logger.info('rotation test %d %s', i, 'x' * 30)
                handler.flush()
                self.assertTrue((Path(tmp) / 'musicsync.log.1').exists())
                self.assertLessEqual(len(list(Path(tmp).glob('musicsync.log*'))), 4)
                self.assertEqual(clean('\x1b[31merror\x1b[0m'), 'error')
            finally:
                for handler in logger.handlers:
                    handler.close()
                logger.handlers = original
