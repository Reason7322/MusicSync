import re
from musicsync.models import Change

PREFIX = "MUSICSYNC|"
ESCAPE = re.compile(r"\\#([0-7]{3})")
PROGRESS = re.compile(r"^\s*([\d,.]+[kKMGT]?)\s+(\d+)%\s+(\S+/s)\s+(\S+)")


def unescape_name(value):
    # rsync escapes controls and literal backslashes as octal bytes.
    data = bytearray()
    pos = 0
    for match in ESCAPE.finditer(value):
        data.extend(value[pos:match.start()].encode("utf-8", "surrogateescape"))
        data.append(int(match[1], 8))
        pos = match.end()
    data.extend(value[pos:].encode("utf-8", "surrogateescape"))
    return bytes(data).decode("utf-8", "surrogateescape")


def parse_change(line: str) -> Change | None:
    if not line.startswith(PREFIX):
        return None
    parts = line.split("|", 3)
    if len(parts) != 4:
        raise ValueError("Malformed rsync change record.")
    _, code, size, name = parts
    path = unescape_name(name)
    if path.startswith("/") or ".." in path.split("/"):
        raise ValueError("Unsafe path in rsync output.")
    directory = path.endswith("/") or (not code.startswith("*") and len(code) > 1 and code[1] == "d")
    if code.startswith("*deleting"):
        action = "Delete"
    elif len(code) == 11 and code[0] in "<>ch." and code[1] in "fdLDS":
        action = "Add" if code[2:] == "+" * 9 else "Update"
    else:
        raise ValueError(f"Unrecognized rsync itemization: {code!r}")
    # Human-readable %l may have suffixes: caller enriches from exact inventory.
    amount = int(size.strip()) if size.strip().isdigit() else None
    return Change(action, path, amount, directory, code)


def parse_progress(line):
    match = PROGRESS.match(line)
    if match:
        return {"bytes_display": match[1], "percent": int(match[2]), "speed": match[3], "time": match[4]}
    return None


def arguments(settings, source, destination, dry_run, max_delete=None):
    args = ["-rtv", "--omit-dir-times", "--human-readable", "--itemize-changes", "--info=progress2", "--stats", f"--out-format={PREFIX}%i|%l|%n"]
    if settings.mirror:
        args.append("--delete-after")
        if max_delete is not None:
            args.append(f"--max-delete={max_delete}")
    args.extend(f"--exclude={e}" for e in settings.exclusions)
    if dry_run:
        args.append("--dry-run")
    return args + ["--", source.rstrip("/") + "/", destination.rstrip("/") + "/"]
