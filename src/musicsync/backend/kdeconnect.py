"""Only documented CLI interfaces; no translated human-readable status parsing."""
from musicsync.models import Command, Device


def parse_devices(output: str) -> list[Device]:
    devices = []
    for line in output.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and all(c.isalnum() or c in "_-" for c in parts[0]):
            devices.append(Device(parts[0], parts[1]))
    return devices


def discover(available=True):
    return Command("kdeconnect-cli", ["--list-available" if available else "--list-devices", "--id-name-only"], label="Discover KDE Connect devices")


def mountpoint(device_id):
    return Command("kdeconnect-cli", ["-d", device_id, "--get-mount-point"], label="Get KDE Connect mountpoint")


def mount(device_id):
    return Command("kdeconnect-cli", ["-d", device_id, "--mount"], 45000, "Mount KDE Connect filesystem")
