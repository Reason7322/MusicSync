"""Explicit fictional configuration for tests of an already configured app.

Keep it separate from production defaults: first run must have no selected device.
"""
from dataclasses import dataclass
from musicsync.settings import Settings


@dataclass
class ConfiguredSettings(Settings):
    source: str = '/tmp/musicsync-test-library'
    device_id: str = 'test-device'
    device_name: str = 'Test phone'
