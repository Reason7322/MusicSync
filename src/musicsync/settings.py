"""Small, validated XDG JSON settings; no implicit fallback after malformed config."""
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
import tempfile
from PySide6.QtCore import QStandardPaths

DELETE_FRACTION = 0.20
DELETE_ABSOLUTE = 50
PHONE_STORAGE = "/storage/emulated/0"


def default_source() -> str:
    """Use Qt's XDG-aware suggestion without creating or scanning directories.

    Disabled XDG user directories may resolve to HOME: never offer the whole
    home directory as an implicit music library.
    """
    value = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
    path = Path(value)
    if (not value or not path.is_absolute() or path in (Path('/'), Path.home())
            or '..' in path.parts or any(ord(c) < 32 for c in value)):
        return ''
    return value


def suspicious_deletions(deleted: int, phone_files: int) -> bool:
    return deleted > 0 and (deleted >= DELETE_ABSOLUTE or phone_files <= 0 or deleted / phone_files > DELETE_FRACTION)


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "musicsync"


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "musicsync"


def atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".musicsync-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass
class Settings:
    source: str = field(default_factory=default_source)
    device_id: str = ""
    device_name: str = ""
    remote_dir: str = "/storage/emulated/0/Music"
    replaygain: bool = True
    preset: str = "/usr/share/rsgain/presets/no_album.ini"
    threads: int = 4
    mirror: bool = False
    exclusions: list[str] = field(default_factory=lambda: ["/.thumbnails/"])

    @property
    def configured(self) -> bool:
        return bool(self.source and self.device_id and self.device_name)

    def validate(self, *, require_configured=True):
        # Loading a first-run config is allowed; every operation and save still
        # requires an explicitly selected device before issuing any commands.
        unconfigured = self.device_id == "" and self.device_name == ""
        for name in ("source", "device_id", "device_name", "remote_dir", "preset"):
            value = getattr(self, name)
            if name == 'source' and value == '':
                if require_configured:
                    raise ValueError('Choose a PC music library in Settings before previewing or syncing.')
                continue
            if name in {"device_id", "device_name"} and unconfigured:
                if require_configured:
                    raise ValueError("Choose a KDE Connect device in Settings before previewing or syncing.")
                continue
            if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
                raise ValueError(f"Invalid {name} setting.")
        if self.source and (not Path(self.source).is_absolute() or Path(self.source) == Path("/")):
            raise ValueError("Choose an absolute local library path, other than /.")
        if '..' in Path(self.source).parts:
            raise ValueError("Choose a normalized PC library path without parent-directory traversal.")
        if not unconfigured and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_-]*', self.device_id):
            raise ValueError('Invalid KDE Connect device ID.')
        parts = PurePosixPath(self.remote_dir).parts
        if ".." in parts or not self.remote_dir.startswith(PHONE_STORAGE + "/") or len(parts) < 5:
            raise ValueError("Choose a directory inside /storage/emulated/0; the storage root cannot be mirrored.")
        if self.remote_dir != str(PurePosixPath(self.remote_dir)):
            raise ValueError("Remote path must be normalized (no repeated or trailing slashes).")
        if type(self.threads) is not int or not 1 <= self.threads <= 32:
            raise ValueError("ReplayGain worker count must be between 1 and 32.")
        if any(type(getattr(self, key)) is not bool for key in ("replaygain", "mirror")):
            raise ValueError("ReplayGain and mirror options must be booleans.")
        if not isinstance(self.exclusions, list) or any(not isinstance(e, str) or not e or "\n" in e or "\0" in e for e in self.exclusions):
            raise ValueError("Invalid exclusions.")
        if "/.thumbnails/" not in self.exclusions:
            raise ValueError("The /.thumbnails/ protection must remain enabled.")
        if any(not e.startswith('/') or not e.endswith('/') or '/' in e[1:-1] or e[1:-1] in {'', '.', '..'} or any(c in e for c in '*?[') for e in self.exclusions):
            raise ValueError("This version supports exclusions of root directories only, such as /.thumbnails/.")

    def save(self, path: Path | None = None):
        self.validate()
        atomic_json(path or config_dir() / "settings.json", asdict(self))

    @classmethod
    def load(cls, path: Path | None = None):
        path = path or config_dir() / "settings.json"
        value = cls(**json.loads(path.read_text())) if path.exists() else cls()
        value.validate(require_configured=False)
        return value
