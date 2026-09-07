"""Blocking filesystem primitives, called only in short-lived helper processes.

Directory descriptors pin mount references across lazy detach. No symlink traversal
is permitted in the destination; fdinfo mount IDs also reject nested mounts.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid
from contextlib import contextmanager

from musicsync.backend.mounts import proc_mounts

TRACK_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wav", ".aiff", ".aif", ".wv", ".ape", ".mp2", ".wma", ".mka"}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def fd_mount_id(fd):
    for line in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines():
        if line.startswith("mnt_id:"):
            return int(line.split()[1])
    raise OSError("Linux did not expose the open directory's mount ID.")


def current_mount(target, expected_id=None):
    found = [m for m in proc_mounts(Path("/proc/self/mountinfo").read_text()) if m.target == target]
    if len(found) != 1 or not found[0].expected:
        raise OSError("The expected KDE Connect SSHFS mount is absent or has an unexpected identity.")
    mount = found[0]
    if expected_id is not None and mount.id != expected_id:
        raise OSError("The phone mount changed during this operation. Please preview again.")
    return mount


@contextmanager
def remote_directory(target, remote, expected_id):
    mount = current_mount(target, expected_id)
    fd = os.open(target, DIR_FLAGS)
    try:
        if fd_mount_id(fd) != mount.id:
            raise OSError("Mount identity changed while opening the phone.")
        for part in remote.split("/"):
            if not part:
                continue
            if part in {".", ".."}:
                raise OSError("Unsafe remote directory component.")
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
            if fd_mount_id(fd) != mount.id:
                raise OSError("Unexpected nested mount inside the phone directory.")
        current_mount(target, mount.id)
        yield fd
    finally:
        os.close(fd)


def inventory(root, exclusions=(), require_files=False, mount_id=None):
    files, directories, tracks, size = {}, [], 0, 0
    excluded = {e.strip("/") for e in exclusions}
    # fwalk accepts a pinned fd through dir_fd and does not follow directory symlinks.
    base_fd = root if isinstance(root, int) else os.open(root, DIR_FLAGS)
    try:
        def fail(error):
            raise error
        for directory, dirs, names, fd in os.fwalk(".", topdown=True, onerror=fail, follow_symlinks=False, dir_fd=base_fd):
            if mount_id is not None and fd_mount_id(fd) != mount_id:
                raise OSError("Unexpected nested mount in the music library.")
            relative = directory.removeprefix("./")
            if relative == ".":
                dirs[:] = [d for d in dirs if d not in excluded]
                relative = ""
            for name in dirs + names:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                path = f"{relative}/{name}" if relative else name
                if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise OSError(f"Unsupported symlink or special file: {path!r}. Resolve it before syncing.")
                if stat.S_ISREG(info.st_mode):
                    files[path] = [info.st_size, info.st_mtime_ns]
                    size += info.st_size
                    tracks += Path(name).suffix.lower() in TRACK_EXTENSIONS
                else:
                    directories.append(path)
        if require_files and not files:
            raise OSError("The source library contains zero files. Refusing to mirror an empty source.")
        digest = hashlib.sha256(json.dumps([files, sorted(directories)], sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        return {"files": files, "count": len(files), "tracks": tracks, "bytes": size, "digest": digest}
    finally:
        if not isinstance(root, int):
            os.close(base_fd)


def write_probe(fd):
    name = ".musicsync-write-test-" + uuid.uuid4().hex
    created = False
    try:
        probe = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        created = True
        try:
            os.write(probe, b"MusicSync\n")
        finally:
            os.close(probe)
        os.unlink(name, dir_fd=fd)
        created = False
    except OSError as error:
        raise OSError(f"Phone Music directory failed its write/delete test: {error}. Probe name: {name}") from error
    finally:
        if created:
            try:
                os.unlink(name, dir_fd=fd)
            except OSError:
                pass
