import re
from musicsync.models import Command
from musicsync.runtime import effective_preset


def command(settings, scan_root=None):
    # Production passes a replaygain_stage() symlink view so recovery backups in
    # .musicsyncrename/ are never scanned or tagged. The default (the raw library
    # root) is kept for callers that manage exclusions themselves.
    target = str(scan_root) if scan_root is not None else settings.source
    return Command("rsgain", ["easy", "-S", "-m", str(settings.threads), "-p", effective_preset(settings.preset), target], 0, "Check per-track ReplayGain")


def processed_tracks(output: str) -> bool | None:
    # Only report a count when the tool explicitly provides one. No guessed percentages.
    output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
    if 'No files were scanned' in output:
        return False
    match = re.search(r"(?im)^\s*(?:Tracks|Files) scanned:\s*(\d+)", output)
    return bool(int(match[1])) if match else None
