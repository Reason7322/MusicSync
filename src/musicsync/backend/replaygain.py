import re
from musicsync.models import Command


def command(settings):
    return Command("rsgain", ["easy", "-S", "-m", str(settings.threads), "-p", settings.preset, settings.source], 0, "Check per-track ReplayGain")


def processed_tracks(output: str) -> bool | None:
    # Only report a count when the tool explicitly provides one. No guessed percentages.
    output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
    if 'No files were scanned' in output:
        return False
    match = re.search(r"(?im)^\s*(?:Tracks|Files) scanned:\s*(\d+)", output)
    return bool(int(match[1])) if match else None
