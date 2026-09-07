"""QProcess helper entrypoint. For rsync/unmount, validate then exec the utility.

exec keeps the QProcess PID, so terminate/kill targets the actual utility, without
a shell or an orphan child process. No alternate unguarded real-phone code path.
"""
import json
import os
from pathlib import Path
import shutil
import sys

from musicsync.backend.filesystem import current_mount, fd_mount_id, inventory, remote_directory, write_probe, DIR_FLAGS
from musicsync.backend.rsync import arguments
from musicsync.settings import PHONE_STORAGE, Settings


def execute(payload):
    action = payload["action"]
    if action == "mount_path":
        path = Path(payload['path'])
        try:
            info = path.lstat()
        except FileNotFoundError:
            return {'exists': False}
        import stat
        if not stat.S_ISDIR(info.st_mode):
            raise OSError('The KDE Connect mountpoint is not an ordinary directory.')
        return {'exists': True}
    if action == "source":
        return inventory(payload["source"], payload.get("exclusions", []), True)
    if action == "dependencies":
        missing = [name for name in payload["programs"] if shutil.which(name) is None]
        if missing:
            raise OSError("Missing runtime tools: " + ", ".join(missing))
        if payload.get("preset") and not Path(payload["preset"]).is_file():
            raise OSError("ReplayGain preset does not exist: " + payload["preset"])
        return {}
    target, mount_id = payload["mountpoint"], payload["mount_id"]
    if action == "unmount":
        current_mount(target, mount_id)
        program = shutil.which("fusermount3")
        os.execv(program, [program, "-uz" if payload.get("lazy") else "-u", target])
    remote = PHONE_STORAGE if action == "storage" else payload["remote"]
    with remote_directory(target, remote, mount_id) as destination:
        if action == "storage":
            # Actual readdir, not just stat; stale EIO must be detected.
            with os.scandir(destination) as entries:
                next(entries, None)
            return {}
        if action == "destination":
            return inventory(destination, payload["exclusions"], mount_id=mount_id)
        if action == "probe":
            write_probe(destination)
            return {}
        if action == "rsync":
            settings = Settings(**payload["settings"])
            settings.validate()
            source = os.open(settings.source, DIR_FLAGS)
            try:
                if fd_mount_id(source) == mount_id:
                    raise OSError("Source must not be inside the phone mount.")
                source_inventory = inventory(source, settings.exclusions, True)
                destination_inventory = inventory(destination, settings.exclusions, mount_id=mount_id)
                for kind, value in [("source", source_inventory), ("destination", destination_inventory)]:
                    if payload.get(kind + "_digest") and value["digest"] != payload[kind + "_digest"]:
                        raise OSError(f"The {kind} changed since preview. Nothing synchronized; preview again.")
                current_mount(target, mount_id)
                os.fchdir(destination)
                os.set_inheritable(source, True)
                program = shutil.which("rsync")
                args = arguments(settings, f"/proc/self/fd/{source}", ".", payload["dry_run"], payload.get("max_delete"))
                os.execv(program, [program, *args])
            finally:
                os.close(source)
    raise ValueError("Unknown filesystem operation: " + action)


def main():
    try:
        print(json.dumps(execute(json.loads(sys.argv[1])), ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
