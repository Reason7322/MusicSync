"""Inspectable, deterministic generator state machine, independent of Qt.

Yielded Command values are executed by the Qt adapter. Tests send mock Results.
All resource cleanup lives in the generator's finally block, including cancellation.
"""
from dataclasses import asdict, dataclass, replace
import json

from musicsync.backend import kdeconnect, replaygain, rsync
from musicsync.backend.mounts import mount_query, parse_findmnt, validate_mountpoint
from musicsync.models import Command, Outcome, State, Summary
from musicsync.settings import DELETE_ABSOLUTE, suspicious_deletions
from musicsync.runtime import effective_preset, worker_invocation


@dataclass(frozen=True)
class Event:
    state: State
    message: str
    data: object = None


@dataclass(frozen=True)
class Approval:
    summary: Summary
    phone_files: int


class Failure(Exception):
    pass


class Cancelled(Failure):
    pass


def helper(action, label, timeout=30000, **payload):
    program, args = worker_invocation(json.dumps(dict(action=action, **payload), ensure_ascii=True))
    return Command(program, args, timeout, label)


class Workflow:
    def __init__(self, settings, preview):
        self.settings = settings
        self.preview = preview
        self.mountpoint = None
        self.mount = None
        self.owned = False
        self.summary = Summary()
        self.source_inventory = None
        self.destination_inventory = None
        self.replaygain_processed = None
        self.transferred_bytes = None
        self.rsync_started = False
        self.cleanup_warning = ""

    def _call(self, command, message, allow_failure=False):
        result = yield command
        if result.cancelled:
            raise Cancelled("Synchronization was interrupted. Completed changes have not been undone." if self.rsync_started else "Operation cancelled before synchronization. ReplayGain may have updated tags if it had started.")
        if not allow_failure and (result.code != 0 or result.timed_out):
            detail = " The command stopped responding (timeout)." if result.timed_out else ""
            raise Failure(message + detail + ("\n" + result.stderr.strip() if result.stderr.strip() else ""))
        return result

    def _device(self):
        yield Event(State.CHECKING_DEVICE, f"Checking {self.settings.device_name}…")
        result = yield from self._call(kdeconnect.discover(), "Could not query KDE Connect. Check that it is running in your desktop session.")
        if self.settings.device_id not in {d.id for d in kdeconnect.parse_devices(result.stdout)}:
            raise Failure(f"{self.settings.device_name} is not connected.")

    def _identity(self):
        mounted = yield from self._call(Command("mountpoint", ["-q", self.mountpoint], label="Check mount presence"), "Cannot check phone mount.", True)
        if mounted.code != 0 or mounted.timed_out:
            raise Failure("The expected phone filesystem is not mounted.")
        result = yield from self._call(mount_query(self.mountpoint), "Cannot read the mount identity.")
        try:
            mount = parse_findmnt(result.stdout, self.mountpoint)
        except (ValueError, KeyError, TypeError) as error:
            raise Failure("Could not verify the phone mount identity.") from error
        if not mount.expected:
            raise Failure("An unexpected non-KDE filesystem is mounted at the phone mountpoint. Refusing to use or unmount it.")
        if self.mount is not None and mount != self.mount:
            raise Failure("The phone mount changed during this operation. Preview again.")
        self.mount = mount
        return mount

    def _remote(self, action, label, **extra):
        return helper(action, label, mountpoint=self.mountpoint, mount_id=self.mount.id,
                      remote=self.settings.remote_dir, exclusions=self.settings.exclusions, **extra)

    def _fresh_mount(self):
        yield Event(State.MOUNTING, f"Mounting {self.settings.device_name}…")
        # Ownership is recorded before starting so a failed/ cancelled partial mount
        # is still eligible for identity-checked cleanup.
        self.owned = True
        yield from self._call(kdeconnect.mount(self.settings.device_id), self.restart_advice)
        yield from self._identity()

    @property
    def restart_advice(self):
        return f"KDE Connect's remote filesystem is not responding. Force-stop and reopen KDE Connect on {self.settings.device_name}, then try again."

    def _prepare_mount(self):
        result = yield from self._call(kdeconnect.mountpoint(self.settings.device_id), "KDE Connect did not provide a mountpoint.")
        self.mountpoint = validate_mountpoint(result.stdout.strip())
        yield Event(State.VALIDATING, "Checking phone filesystem…")
        presence = yield from self._call(Command("mountpoint", ["-q", self.mountpoint], label="Check existing mount"), "Could not check mountpoint.", True)
        if presence.code == 1 and not presence.timed_out:
            probe = yield from self._call(helper('mount_path', 'Inspect absent mountpoint', path=self.mountpoint), 'Could not inspect the mountpoint.')
            if not json.loads(probe.stdout)['exists']:
                presence = replace(presence, code=32)
        if presence.timed_out or presence.code not in (0, 32):
            raise Failure("Could not reliably determine whether the phone filesystem is mounted.")
        if presence.code == 0:
            yield from self._identity()
            alive = yield from self._call(self._remote("storage", "Probe Android shared storage"), self.restart_advice, True)
            if alive.code or alive.timed_out:
                yield Event(State.RECONNECTING, "KDE Connect is connected, but its filesystem stopped responding. Attempting one remount…")
                yield from self._call(self._remote("unmount", "Detach stale KDE SSHFS", lazy=True), "Could not safely detach the stale mount.")
                check = yield from self._call(Command("mountpoint", ["-q", self.mountpoint], label="Confirm stale mount detached"), "Could not confirm stale mount detach.", True)
                if check.code != 32 or check.timed_out:
                    raise Failure("The stale mount did not detach. " + self.restart_advice)
                self.mount = None
                yield from self._device()
                yield from self._fresh_mount()
        else:
            yield from self._fresh_mount()
        yield Event(State.VALIDATING, "Validating Android storage and Music directory…")
        yield from self._identity()
        yield from self._call(self._remote("storage", "Validate Android shared storage"), self.restart_advice)
        yield from self._destination()

    def _source(self):
        result = yield from self._call(helper("source", "Scan PC library", timeout=120000, source=self.settings.source, exclusions=self.settings.exclusions), "The PC library is unavailable or unsafe. Synchronization was stopped before any files were deleted.")
        self.source_inventory = json.loads(result.stdout)
        return self.source_inventory

    def _destination(self):
        result = yield from self._call(self._remote("destination", "Scan phone Music", timeout=120000), "The phone Music directory is unavailable. It must already exist and be accessible; it will not be created automatically.")
        self.destination_inventory = json.loads(result.stdout)

    def _rsync_command(self, dry_run, max_delete=None):
        return self._remote("rsync", "rsync preview" if dry_run else "rsync mirror" if self.settings.mirror else "rsync update", timeout=0,
                            settings=asdict(self.settings), dry_run=dry_run, max_delete=max_delete,
                            source_digest=self.source_inventory["digest"], destination_digest=self.destination_inventory["digest"])

    def _parse(self, output):
        changes = []
        # The process protocol uses CR/LF only. str.splitlines also treats valid
        # Unicode filename characters (NEL, U+2028/U+2029) as record boundaries.
        for line in output.replace("\r", "\n").split("\n"):
            change = rsync.parse_change(line)
            if change:
                files = self.destination_inventory["files"] if change.action == "Delete" else self.source_inventory["files"]
                info = files.get(change.path)
                if info and not change.directory:
                    change = replace(change, size=info[0])
                changes.append(change)
        return Summary(changes)

    def _core(self):
        self.settings.validate()
        yield Event(State.CHECKING_SOURCE, "Checking tools and local library…")
        programs = ["kdeconnect-cli", "rsync", "findmnt", "mountpoint", "fusermount3", "sshfs"]
        tagging = not self.preview and self.settings.replaygain
        if tagging:
            programs.append("rsgain")
        yield from self._call(helper("dependencies", "Validate runtime dependencies", programs=programs, preset=effective_preset(self.settings.preset) if tagging else None), "Configuration error.")
        inventory = yield from self._source()
        yield Event(State.CHECKING_SOURCE, "Local library checked.", inventory)
        yield from self._device()
        if tagging:
            yield Event(State.REPLAYGAIN, "Checking independent per-track ReplayGain tags…")
            result = yield from self._call(replaygain.command(self.settings), "ReplayGain processing failed. The phone will not be synchronized.")
            self.replaygain_processed = replaygain.processed_tracks(result.stdout + result.stderr)
            yield from self._source()
        yield from self._device()
        yield from self._prepare_mount()
        if not self.preview:
            yield from self._call(self._remote("probe", "Verify phone write and delete capability"), "Phone Music directory is not writable or does not allow deletion. Synchronization was stopped before any library files were deleted.")
        yield Event(State.PREVIEWING, "Calculating synchronization changes…")
        result = yield from self._call(self._rsync_command(True), "Could not preview synchronization.")
        self.summary = self._parse(result.stdout)
        yield Event(State.PREVIEWING, "Preview ready.", self.summary)
        if self.preview:
            return
        deleted = self.summary.count("Delete")
        if suspicious_deletions(deleted, self.destination_inventory["count"]) or self.summary.deletions >= DELETE_ABSOLUTE:
            yield Event(State.CONFIRMING, "Review the files that will be removed from the phone.")
            approved = yield Approval(self.summary, self.destination_inventory["count"])
            if not approved:
                raise Cancelled("Synchronization was stopped before any library files were deleted. ReplayGain may already have updated local tags.")
        yield from self._device()
        yield Event(State.VALIDATING, "Rechecking mount identity and approved library snapshots…")
        yield from self._identity()
        yield from self._call(self._remote("probe", "Final phone write/delete check"), "Phone Music directory failed the final write/delete check.")
        yield Event(State.SYNCING, "Synchronizing music…")
        self.rsync_started = True
        result = yield from self._call(self._rsync_command(False, self.summary.deletions), "rsync failed. The libraries may be only partially synchronized. See details for the utility's error.")
        actual = self._parse(result.stdout)
        # Stats uses human-readable units. Record exact transferred file bytes from
        # the inventory for reported transfers; do not confuse these with wire bytes.
        self.transferred_bytes = sum(c.size or 0 for c in actual.changes if c.code.startswith((">f", "<f")))
        self.summary = actual
        yield Event(State.VERIFYING, "Checking that no synchronization changes remain…")
        yield from self._identity()
        yield from self._source()
        yield from self._destination()
        verification = yield from self._call(self._rsync_command(True), "Files were copied, but final verification failed. A successful sync has not been recorded.")
        if self._parse(verification.stdout).changes:
            raise Failure("Files still differ after synchronization, possibly because a library changed during the operation. Preview again; a successful sync has not been recorded.")

    def _cleanup(self):
        if not self.owned or not self.mountpoint:
            return
        yield Event(State.UNMOUNTING, "Cleaning up the phone mount created by Music Sync…")
        # Cleanup must proceed even if cancellation was requested. Never unmount an
        # unexpected filesystem, or a replacement of an already-observed mount ID.
        presence = yield Command("mountpoint", ["-q", self.mountpoint], label="Check cleanup mount")
        if presence.code == 1 and not presence.timed_out:
            probe = yield helper('mount_path', 'Inspect cleanup mountpoint', path=self.mountpoint)
            if probe.code == 0 and not probe.timed_out and not json.loads(probe.stdout)['exists']:
                self.owned = False
                return
        if presence.code == 32 and not presence.timed_out:
            self.owned = False
            return
        if presence.code != 0 or presence.timed_out:
            raise Failure("Could not determine whether the app-created mount needs cleanup.")
        result = yield mount_query(self.mountpoint)
        if result.code != 0 or result.timed_out:
            raise Failure("Could not verify cleanup mount identity; mount left untouched.")
        mount = parse_findmnt(result.stdout, self.mountpoint)
        if not mount.expected or (self.mount is not None and mount != self.mount):
            raise Failure("Mount identity changed; cleanup left it untouched.")
        self.mount = mount
        for lazy in (False, True):
            result = yield self._remote("unmount", "Unmount app-created KDE SSHFS", lazy=lazy)
            check = yield Command("mountpoint", ["-q", self.mountpoint], label="Verify cleanup")
            if check.code == 1 and not check.timed_out:
                probe = yield helper('mount_path', 'Inspect cleanup mountpoint', path=self.mountpoint)
                if probe.code == 0 and not probe.timed_out and not json.loads(probe.stdout)['exists']:
                    self.owned = False
                    return
            if check.code == 32 and not check.timed_out:
                self.owned = False
                return
            if result.timed_out:
                continue
        raise Failure("Automatic cleanup could not unmount the phone. Close other users of its filesystem and unmount through KDE Connect.")

    def run(self):
        outcome = None
        try:
            yield from self._core()
            outcome = Outcome(True, "Preview complete. No music files or tags were changed." if self.preview else "Music synchronization complete and verified.", self.preview, summary=self.summary,
                              transferred_bytes=self.transferred_bytes, replaygain_processed=self.replaygain_processed)
        except Cancelled as error:
            outcome = Outcome(False, str(error), self.preview, True, self.summary)
        except (Failure, ValueError, OSError, KeyError, TypeError) as error:
            outcome = Outcome(False, str(error), self.preview, summary=self.summary)
        finally:
            try:
                yield from self._cleanup()
            except (Failure, ValueError, OSError, KeyError, TypeError) as error:
                self.cleanup_warning = str(error)
        outcome.cleanup_warning = self.cleanup_warning
        return outcome
