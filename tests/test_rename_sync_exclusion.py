"""Regression tests: library-root .musicsyncrename/ is protected internal recovery data.

Bulk Rename keeps its undo backups and session journals in <library>/.musicsyncrename/.
That directory must never become synchronization content: not in the PC source
inventory or destination filename map, not in update-only or mirror previews, not
copied by real rsync (update or mirror), not deleted from a phone that already has
a copy, and its files' bytes/tags must survive ReplayGain processing. Protection is
root-anchored: an album's own .musicsyncrename subfolder is ordinary content.

All fixtures are disposable synthetic trees in temporary directories. The only real
tools exercised are rsync (and ffmpeg/rsgain when available for the ReplayGain test).
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from musicsync.backend.filesystem import inventory, replaygain_stage, source_inventory
from musicsync.backend.rsync import arguments, parse_change
from musicsync.backend.replaygain import command as rg_command
from musicsync.models import Command
from musicsync.settings import PROTECTED_ROOTS, Settings, sync_exclusions
from test_process import run

OLD_EXCLUSIONS = ["/.thumbnails/"]  # exactly what settings.json files from 0.1.x contain


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recovery_tree(root: Path):
    backups, sessions = root / '.musicsyncrename' / 'backups', root / '.musicsyncrename' / 'sessions'
    backups.mkdir(parents=True)
    sessions.mkdir()
    (backups / 'Artist X - Song Y.mp3').write_bytes(b'\xff\xfb\x90\xc0' + b'\x00' * 416 * 8)
    (sessions / 's-20261018-0001.jsonl').write_text(
        '{"type": "session", "id": "s-20261018-0001", "state": "open"}\n'
        '{"type": "op", "before": "album-a/old name.mp3", "after": "Artist X - Song Y.mp3"}\n')


def build_library(base: Path):
    pc, phone = base / 'pc', base / 'phone'
    (pc / 'album-a').mkdir(parents=True)
    (pc / 'album-b/.musicsyncrename').mkdir(parents=True)  # nested decoy: ordinary content
    phone.mkdir()
    (pc / 'loose track.mp3').write_text('root-level music')
    (pc / 'album-a/01 song A.mp3').write_bytes(b'\xff\xfb\x90\xc0' + b'\x00' * 416)
    (pc / 'album-b/.musicsyncrename/fake.jsonl').write_text('{"note": "decoy, ordinary content"}\n')
    (phone / 'existing track.mp3').write_text('already on phone')
    return pc, phone


def recovery_fingerprint(root: Path) -> dict:
    rec = root / '.musicsyncrename'
    if not rec.is_dir():
        return {}
    return {str(p.relative_to(rec)): (sha(p), p.stat().st_mtime_ns) for p in rec.rglob('*') if p.is_file()}


def is_root_recovery(path: str) -> bool:
    # Root-anchored check: matches only the protected root (also with rsync's trailing slash
    # on directory records) and anything under it - never album-b/.musicsyncrename etc.
    return path == '.musicsyncrename' or path.startswith('.musicsyncrename/')


class InventoryProtectionTests(unittest.TestCase):
    def test_source_inventory_and_filename_map_exclude_root_recovery(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as tmp:
            pc, _ = build_library(Path(tmp))
            recovery_tree(pc)
            snap = source_inventory(str(pc), OLD_EXCLUSIONS, True)

            leaked_files = [p for p in snap['files'] if is_root_recovery(p)]
            leaked_dirs = [d for d in snap['directories'] if is_root_recovery(d)]
            self.assertEqual(leaked_files, [])
            self.assertEqual(leaked_dirs, [])
            # The destination filename map must not offer recovery data to Android either.
            mapped_in = set(snap['destination_paths']) | set(snap['source_paths'].values()) \
                | set(snap['destination_files'])
            self.assertFalse(any(is_root_recovery(p) for p in mapped_in), sorted(mapped_in))

            # Ordinary content, including the nested same-name decoy, is still inventoried.
            self.assertIn('loose track.mp3', snap['files'])
            self.assertIn('album-a/01 song A.mp3', snap['files'])
            self.assertIn('album-b/.musicsyncrename/fake.jsonl', snap['files'])

    def test_plain_inventory_call_with_no_exclusions_still_protects(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as tmp:
            pc, _ = build_library(Path(tmp))
            recovery_tree(pc)
            # Even a caller that forgets every exclusion (e.g. an old code path passing []) is safe:
            snap = inventory(str(pc), exclusions=(), require_files=True)
            self.assertFalse([p for p in snap['files'] if is_root_recovery(p)])

    def test_old_settings_json_without_new_exclusion_loads_and_stays_safe(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as tmp:
            base = Path(tmp)
            pc, phone = build_library(base)
            recovery_tree(pc)
            # Simulate a user's existing config directory from before this protection existed.
            (base / 'config').mkdir()
            old_json = {
                "source": str(pc), "device_id": "", "device_name": "",
                "remote_dir": "/storage/emulated/0/Music", "replaygain": True,
                "preset": "/usr/share/rsgain/presets/no_album.ini", "threads": 4,
                "mirror": False, "exclusions": ["/.thumbnails/"],
            }
            (base / 'config' / 'musicsync').mkdir()
            settings_path = base / 'config' / 'musicsync' / 'settings.json'
            settings_path.write_text(json.dumps(old_json))
            loaded = Settings.load(settings_path)  # must NOT raise: old JSON stays valid
            self.assertEqual(loaded.exclusions, ["/.thumbnails/"])

            snap = source_inventory(str(pc), loaded.exclusions, True)
            self.assertFalse([p for p in snap['files'] if is_root_recovery(p)])
            args = arguments(loaded, str(pc), str(phone), True)
            self.assertIn('--exclude=/.musicsyncrename/', args)
            self.assertIn('--exclude=/.thumbnails/', args)


class SettingsContractTests(unittest.TestCase):
    def test_protection_is_mandatory_and_cannot_be_lost_by_saving(self):
        settings = Settings(source='/tmp/library')
        settings.validate(require_configured=False)
        self.assertEqual(sync_exclusions(settings.exclusions), ["/.musicsyncrename/", "/.thumbnails/"])
        # A user may add root exclusions; protected roots stay, duplicates collapse once.
        doubled = list(settings.exclusions) + list(PROTECTED_ROOTS)
        merged = sync_exclusions(doubled)
        self.assertEqual(merged[0], '/.musicsyncrename/')
        self.assertEqual(merged.count('/.musicsyncrename/'), 1)

    def test_thumbnails_protection_still_mandatory(self):
        with self.assertRaises(ValueError):
            Settings(source='/tmp/library', exclusions=[]).validate()


class RsyncProtectionTests(unittest.TestCase):
    def _assert_no_root_recovery_changes(self, changes, label=''):
        leaked = [c.path for c in changes if is_root_recovery(c.path)]
        self.assertEqual(leaked, [], f'{label} proposes root recovery data: {leaked}')

    def test_update_only_preview_proposes_ordinary_files_but_never_recovery(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as tmp:
            base = Path(tmp)
            pc, phone = build_library(base)
            recovery_tree(pc)
            result, _ = run(Command('rsync', arguments(Settings(source=str(pc), mirror=False), str(pc), str(phone), True)))
            self.assertEqual(result.code, 0, result.stderr)
            changes = [c for c in (parse_change(ln) for ln in result.stdout.splitlines()) if c]
            self._assert_no_root_recovery_changes(changes, 'update-only preview')
            added = {c.path for c in changes if c.action == 'Add'}
            self.assertIn('loose track.mp3', added)
            self.assertIn('album-a/01 song A.mp3', added)
            self.assertIn('album-b/.musicsyncrename/fake.jsonl', added)  # nested decoy: ordinary content

    def test_update_only_transfer_never_copies_recovery(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as tmp:
            base = Path(tmp)
            pc, phone = build_library(base)
            recovery_tree(pc)
            before = recovery_fingerprint(pc)
            result, _ = run(Command('rsync', arguments(Settings(source=str(pc), mirror=False), str(pc), str(phone), False)))
            self.assertEqual(result.code, 0, result.stderr)

            self.assertFalse((phone / '.musicsyncrename').exists(), 'recovery directory was copied to the phone')
            # Ordinary music did synchronize:
            self.assertEqual((phone / 'loose track.mp3').read_text(), 'root-level music')
            self.assertEqual((phone / 'album-a/01 song A.mp3').read_bytes(), b'\xff\xfb\x90\xc0' + b'\x00' * 416)
            self.assertTrue((phone / 'existing track.mp3').exists())  # phone-only file kept in update mode
            # Nested decoy is ordinary content and must travel:
            self.assertTrue((phone / 'album-b/.musicsyncrename/fake.jsonl').exists())
            # Source recovery data untouched, byte for byte:
            self.assertEqual(before, recovery_fingerprint(pc))

    def test_mirror_protects_existing_phone_recovery_directory(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as tmp:
            base = Path(tmp)
            pc, phone = build_library(base)
            recovery_tree(pc)
            # A buggy 0.2.0 sync already left an orphaned copy on the phone; also corrupt one file in place.
            (phone / '.musicsyncrename/backups').mkdir(parents=True)
            orphan = phone / '.musicsyncrename/backups/orphan from buggy sync.mp3'
            orphan.write_bytes(b'orphan recovery data')
            mirrored_backup = phone / '.musicsyncrename/backups/Artist X - Song Y.mp3'
            mirrored_backup.parent.mkdir(parents=True, exist_ok=True)
            mirrored_backup.write_bytes(b'tampered on the phone by an old build')

            settings = Settings(source=str(pc), mirror=True)
            preview, _ = run(Command('rsync', arguments(settings, str(pc), str(phone), True)))
            self.assertEqual(preview.code, 0, preview.stderr)
            changes = [c for c in (parse_change(ln) for ln in preview.stdout.splitlines()) if c]
            # Mirror mode must not even PROPOSE touching the phone's recovery tree.
            self._assert_no_root_recovery_changes(changes, 'mirror preview')

            result, _ = run(Command('rsync', arguments(settings, str(pc), str(phone), False)))
            self.assertEqual(result.code, 0, result.stderr)
            self.assertEqual(orphan.read_bytes(), b'orphan recovery data', 'mirror mode deleted or altered phone recovery data')
            # Ordinary mirror behavior preserved: the phone-only file is removed...
            self.assertFalse((phone / 'existing track.mp3').exists())

    def test_digests_stable_between_preview_and_apply(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as tmp:
            base = Path(tmp)
            pc, _ = build_library(base)
            recovery_tree(pc)
            first = source_inventory(str(pc), OLD_EXCLUSIONS, True)
            second = source_inventory(str(pc), OLD_EXCLUSIONS, True)
            self.assertEqual(first['digest'], second['digest'])
            self.assertEqual(first['mapping_digest'], second['mapping_digest'])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('rsgain') and importlib.util.find_spec('mutagen'),
                     'optional real ReplayGain test needs ffmpeg, rsgain and mutagen')
class ReplayGainProtectionTests(unittest.TestCase):
    def _make_mp3(self, path: Path, hz: int = 440):
        result, _ = run(Command('ffmpeg', ['-v', 'error', '-f', 'lavfi', f'-i', f'sine=frequency={hz}:duration=1',
                                         '-c:a', 'libmp3lame', str(path), '-y']))
        self.assertEqual(result.code, 0, result.stderr)

    def test_staged_rsgain_tags_ordinary_files_but_never_recovery_backups(self):
        with tempfile.TemporaryDirectory(prefix='musicsync-test-') as tmp:
            lib = Path(tmp) / 'lib'
            (lib / 'album-a').mkdir(parents=True)
            backup = lib / '.musicsyncrename/backups/bk.mp3'
            backup.parent.mkdir(parents=True)
            self._make_mp3(lib / 'album-a/x.mp3', 440)
            self._make_mp3(lib / 'rootfile.mp3', 880)          # loose file directly at the library root
            self._make_mp3(backup, 660)

            backup_before = sha(backup)
            from mutagen.id3 import ID3
            inventory_result = source_inventory(str(lib), OLD_EXCLUSIONS, True)
            self.assertNotIn('.musicsyncrename/backups/bk.mp3', inventory_result['files'])

            with replaygain_stage(str(lib), inventory_result) as stage:
                # The stage links every ordinary top-level entry and NOTHING else.
                linked = sorted(os.listdir(stage))
                self.assertEqual(linked, ['album-a', 'rootfile.mp3'], linked)
                result, _ = run(rg_command(Settings(source=str(lib)), scan_root=stage))
            self.assertEqual(result.code, 0, result.stderr)

            # Ordinary content is still processed exactly as before: album track AND loose root file tagged.
            for name in ('album-a/x.mp3', 'rootfile.mp3'):
                tags = ID3(lib / name)
                self.assertIn('replaygain_track_gain', {f.desc.lower() for f in tags.getall('TXXX')}, name)
            # Recovery backup: byte-identical, no ReplayGain frames added.
            self.assertEqual(backup_before, sha(backup), 'ReplayGain altered a recovery backup file')
            backup_descs = {f.desc.lower() for f in ID3(backup).getall('TXXX')}
            self.assertNotIn('replaygain_track_gain', backup_descs)


if __name__ == '__main__':
    unittest.main()
