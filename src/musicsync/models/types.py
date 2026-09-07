from dataclasses import dataclass, field
from enum import StrEnum


class State(StrEnum):
    IDLE = "Idle"
    CHECKING_SOURCE = "Checking source"
    CHECKING_DEVICE = "Checking device"
    REPLAYGAIN = "Checking ReplayGain"
    MOUNTING = "Mounting phone"
    VALIDATING = "Validating filesystem"
    RECONNECTING = "Reconnecting filesystem"
    PREVIEWING = "Previewing changes"
    CONFIRMING = "Waiting for deletion approval"
    SYNCING = "Synchronizing"
    VERIFYING = "Verifying synchronization"
    CANCELLING = "Cancelling"
    UNMOUNTING = "Unmounting phone"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass(frozen=True)
class Device:
    id: str
    name: str


@dataclass(frozen=True)
class Command:
    program: str
    args: list[str] = field(default_factory=list)
    timeout_ms: int = 30000
    label: str = ""


@dataclass(frozen=True)
class Result:
    code: int
    stdout: str = ""
    stderr: str = ""
    cancelled: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class Change:
    action: str
    path: str
    size: int | None
    directory: bool = False
    code: str = ""


@dataclass
class Summary:
    changes: list[Change] = field(default_factory=list)

    def count(self, action: str) -> int:
        return sum(c.action == action and not c.directory for c in self.changes)

    def size(self, action: str) -> int:
        return sum(c.size or 0 for c in self.changes if c.action == action and not c.directory)

    @property
    def deletions(self) -> int:
        # rsync --max-delete counts directories too.
        return sum(c.action == "Delete" for c in self.changes)

    def signature(self):
        return sorted((c.action, c.path, c.size, c.directory) for c in self.changes)


@dataclass
class Outcome:
    success: bool
    message: str
    preview: bool = False
    cancelled: bool = False
    summary: Summary = field(default_factory=Summary)
    transferred_bytes: int | None = None
    replaygain_processed: bool | None = None
    cleanup_warning: str = ""
