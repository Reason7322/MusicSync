import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from musicsync.models import Command


@dataclass(frozen=True)
class Mount:
    target: str
    fstype: str
    source: str
    id: int

    @property
    def expected(self):
        return self.fstype == "fuse.sshfs" and self.source.startswith("kdeconnect@")


def parse_findmnt(output: str, target: str) -> Mount:
    rows = json.loads(output).get("filesystems", [])
    if len(rows) != 1 or rows[0].get("target") != target:
        raise ValueError("Mount table does not identify exactly the requested mountpoint.")
    row = rows[0]
    return Mount(row["target"], row["fstype"], row["source"], int(row["id"]))


def mount_query(path):
    return Command("findmnt", ["--json", "--mountpoint", path, "--output", "TARGET,FSTYPE,SOURCE,ID"], label="Verify SSHFS identity")


def validate_mountpoint(path):
    # KDE supplies this path. Reject roots and traversal, rather than trust arbitrary output.
    p = PurePosixPath(path)
    if not p.is_absolute() or len(p.parts) < 4 or ".." in p.parts or str(p) != path or any(ord(c) < 32 for c in path):
        raise ValueError("KDE Connect returned an unsafe or invalid mountpoint.")
    return path


def unescape_mount(value):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)


def proc_mounts(text):
    result = []
    for line in text.splitlines():
        left, right = line.split(" - ", 1)
        before, after = left.split(), right.split()
        result.append(Mount(unescape_mount(before[4]), after[0], unescape_mount(after[1]), int(before[0])))
    return result
