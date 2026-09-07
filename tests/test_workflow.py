from dataclasses import replace
import json
import unittest

from musicsync.backend.workflow import Approval, Event, Workflow
from musicsync.models import Result, State
from fixtures import ConfiguredSettings as Settings


class Simulation:
    def __init__(self, preview=False, mounted=False, stale=False, failure=None, approve=True):
        self.workflow = Workflow(Settings(replaygain=True), preview)
        self.mounted = mounted
        self.stale = stale
        self.failure = failure
        self.approve = approve
        self.commands = []
        self.states = []
        self.mounts = 0
        self.unmounts = 0
        self.mount_id = 42
        self.fstype = "fuse.sshfs"
        self.source = "kdeconnect@host:/"
        self.records = ""
        self.sync_ran = False
        self.cancel_at = None

    def reply(self, command):
        self.commands.append(command)
        label = command.label
        if self.cancel_at == label:
            self.cancel_at = None
            return Result(-1, cancelled=True)
        if self.failure == label:
            return Result(1, stderr="injected failure")
        if command.program == "kdeconnect-cli":
            if "--list-available" in command.args:
                return Result(0, "test-device Test phone\n")
            if "--get-mount-point" in command.args:
                return Result(0, "/run/user/1000/phone\n")
            if "--mount" in command.args:
                self.mounts += 1
                self.mounted = True
                self.stale = False
                return Result(0)
        if command.program == "mountpoint":
            return Result(0 if self.mounted else 32)
        if command.program == "findmnt":
            return Result(0, json.dumps({"filesystems": [{"target": "/run/user/1000/phone", "fstype": self.fstype, "source": self.source, "id": self.mount_id}]}))
        if command.program == "rsgain":
            return Result(0, "Tracks scanned: 0\n")
        if command.args[:2] == ["-m", "musicsync.backend.worker"]:
            payload = json.loads(command.args[2])
            action = payload['action']
            if action in {"source", "destination"}:
                return Result(0, json.dumps({"count": 100, "tracks": 100, "bytes": 1000, "files": {}, "digest": "same"}))
            if action == "storage" and self.stale:
                return Result(1, stderr="Input/output error")
            if action == "unmount":
                self.unmounts += 1
                self.mounted = False
            if action == "rsync":
                if not payload['dry_run']:
                    self.sync_ran = True
                    return Result(0, self.records)
                return Result(0, "" if self.sync_ran else self.records)
            return Result(0, "{}")
        raise AssertionError(command)

    def run(self):
        generator = self.workflow.run()
        result = None
        for _ in range(200):
            try:
                item = generator.send(result)
            except StopIteration as done:
                return done.value
            if isinstance(item, Event):
                self.states.append(item.state)
                result = None
            elif isinstance(item, Approval):
                result = self.approve
            else:
                result = self.reply(item)
        self.fail("Infinite workflow loop")


class WorkflowTests(unittest.TestCase):
    def test_preview_no_tagging_probe_or_real_rsync(self):
        simulation = Simulation(preview=True)
        outcome = simulation.run()
        self.assertTrue(outcome.success)
        self.assertEqual((simulation.mounts, simulation.unmounts), (1, 1))
        self.assertFalse(simulation.sync_ran)
        self.assertFalse(any(c.program == 'rsgain' or 'write' in c.label for c in simulation.commands))

    def test_real_order(self):
        simulation = Simulation()
        outcome = simulation.run()
        self.assertTrue(outcome.success)
        labels = [c.label for c in simulation.commands]
        self.assertLess(labels.index('Check per-track ReplayGain'), labels.index('Mount KDE Connect filesystem'))
        self.assertLess(labels.index('rsync preview'), labels.index('rsync mirror'))
        self.assertIn(State.VERIFYING, simulation.states)
        self.assertEqual((simulation.mounts, simulation.unmounts), (1, 1))

    def test_healthy_borrowed_mount_left_alone(self):
        simulation = Simulation(mounted=True)
        self.assertTrue(simulation.run().success)
        self.assertEqual((simulation.mounts, simulation.unmounts), (0, 0))

    def test_stale_recovered_once(self):
        simulation = Simulation(mounted=True, stale=True)
        self.assertTrue(simulation.run().success)
        self.assertEqual((simulation.mounts, simulation.unmounts), (1, 2))
        self.assertIn(State.RECONNECTING, simulation.states)

    def test_broken_replacement_stops(self):
        simulation = Simulation(mounted=True, stale=True, failure='Validate Android shared storage')
        outcome = simulation.run()
        self.assertFalse(outcome.success)
        self.assertIn('Force-stop', outcome.message)
        self.assertEqual(simulation.mounts, 1)
        self.assertFalse(simulation.sync_ran)

    def test_unexpected_filesystem_never_unmounted(self):
        for key, value in [('fstype', 'ext4'), ('source', 'someone@host:/')]:
            simulation = Simulation(mounted=True)
            setattr(simulation, key, value)
            self.assertFalse(simulation.run().success)
            self.assertEqual(simulation.unmounts, 0)
            self.assertFalse(simulation.sync_ran)

    def test_failures_block_sync(self):
        for label in ['Scan PC library', 'Discover KDE Connect devices', 'Check per-track ReplayGain', 'Get KDE Connect mountpoint', 'Mount KDE Connect filesystem', 'Verify SSHFS identity', 'Scan phone Music', 'Verify phone write and delete capability', 'rsync preview', 'Final phone write/delete check']:
            with self.subTest(label=label):
                simulation = Simulation(failure=label)
                self.assertFalse(simulation.run().success)
                self.assertFalse(simulation.sync_ran)

    def test_cancel_cleans_owned_mount(self):
        simulation = Simulation()
        simulation.cancel_at = 'rsync preview'
        self.assertTrue(simulation.run().cancelled)
        self.assertFalse(simulation.sync_ran)
        self.assertEqual(simulation.unmounts, 1)

    def test_cancel_replaygain_never_mounts(self):
        simulation = Simulation()
        simulation.cancel_at = 'Check per-track ReplayGain'
        self.assertTrue(simulation.run().cancelled)
        self.assertEqual(simulation.mounts, 0)

    def test_delete_approval_and_cap(self):
        for approved in [True, False]:
            simulation = Simulation(approve=approved)
            simulation.records = ''.join(f'MUSICSYNC|*deleting  |0|old{i}.mp3\n' for i in range(21))
            outcome = simulation.run()
            self.assertEqual(outcome.success, approved)
            self.assertEqual(simulation.sync_ran, approved)
            self.assertIn(State.CONFIRMING, simulation.states)
            if approved:
                payload = next(json.loads(c.args[2]) for c in simulation.commands if c.label == 'rsync mirror')
                self.assertEqual(payload['max_delete'], 21)

    def test_rsync_error_does_not_verify_success(self):
        simulation = Simulation(failure='rsync mirror')
        self.assertFalse(simulation.run().success)
        self.assertNotIn(State.VERIFYING, simulation.states)
        self.assertEqual(simulation.unmounts, 1)

    def test_changed_cleanup_mount_left_untouched(self):
        simulation = Simulation()
        original = simulation.reply
        def reply(command):
            if command.label == 'Check cleanup mount':
                simulation.mount_id += 1
            return original(command)
        simulation.reply = reply
        outcome = simulation.run()
        self.assertTrue(outcome.success)
        self.assertIn('identity changed', outcome.cleanup_warning)
        self.assertEqual(simulation.unmounts, 0)
