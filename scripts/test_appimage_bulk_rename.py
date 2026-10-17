#!/usr/bin/env python3
"""Packaged end-to-end Bulk Rename verification for a built AppImage.

Builds the deterministic eight-file synthetic MP3 fixture (same design as
tests/test_bulk_rename.py) under a tempdir, then launches the image with
--bulk-rename-test in isolated HOME/XDG/runtime paths. The APP itself drives
the real Settings -> Bulk Rename GUI entry points: preview, explicit
selection, confirmation, apply, session inspection and undo on that fixture;
this orchestrator only sets it up and checks the evidence afterwards, plus a
final out-of-process re-verification that the library tree is byte-exact.

No phone synchronization, no rsync, no real library access anywhere in this
flow. The auto-answer of confirmation boxes lives ONLY inside the packaged
--bulk-rename-test harness (packaging_check.py); production code never does it.

Usage: python3 scripts/test_appimage_bulk_rename.py <AppImage> [--output PATH]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


FRAME = b'\xff\xfb\x90\xc0' + b'\x00' * 413

F1 = 'untagged junk 1.mp3'          # ok: rename + TIT2 tag edit
F2 = 'song_b.mp3'                   # ok: rename only
F3 = 'Clean Duo - Same Name.mp3'    # no_change
F4 = 'one - two - three.mp3'        # ambiguous (no ID3, multiple separators)
F5 = 'broken.mp3'                   # parse_error
TWIN_A, TWIN_B = 'twin-a.mp3', 'twin-b.mp3'   # proposed_vs_proposed collision
F8 = 'later-modified.mp3'           # ok: rename only

APPLIED_RELS = [F1, F2, F8]
CHECKABLE_RELS = [F1, F2, TWIN_A, TWIN_B, F8]
REJECTED_CODES = {TWIN_A: 'proposal_collision', TWIN_B: 'proposal_collision'}
PROPOSALS = {
    F1: 'Junk Artist - Dream On.mp3',
    F2: 'Clean Band - Pure Title.mp3',
    TWIN_A: 'Twin Act - Same Song.mp3',
    TWIN_B: 'Twin Act - Same Song.mp3',
    F8: 'Late Band - Slow Burn.mp3',
}

JOURNAL_DIRNAME = '.musicsyncrename'


def build_mp3(path):
    with open(str(path), 'wb') as handle:
        for _ in range(8):
            handle.write(FRAME)


def set_tags(path, artist=None, title=None, extra=()):
    from mutagen.id3 import ID3, TIT2, TPE1
    from mutagen.mp3 import MP3

    audio = MP3(str(path))
    if not isinstance(audio.tags, ID3):
        audio.add_tags()
    tags = audio.tags
    for frame in extra:
        tags.add(frame)
    for frame_id, value in (('TPE1', artist), ('TIT2', title)):
        for key in list(tags.keys()):
            if key == frame_id or key.startswith(frame_id + ':'):
                del tags[key]
        if value is not None:
            cls = {'TPE1': TPE1, 'TIT2': TIT2}[frame_id]
            tags.add(cls(encoding=3, text=[value]))
    audio.save()


def build_library(root: Path):
    from mutagen.id3 import TALB, TXXX

    build_mp3(root / F1)
    set_tags(root / F1, artist='Junk Artist', title='Dream On (Official HD Video)',
             extra=(TALB(encoding=3, text=['Toys in the Attic']),
                    TXXX(encoding=3, desc='REPLAYGAIN_TRACK_GAIN', text=['-8.2 dB'])))
    build_mp3(root / F2)
    set_tags(root / F2, artist='Clean Band', title='Pure Title')
    build_mp3(root / F3)
    set_tags(root / F3, artist='Clean Duo', title='Same Name')
    build_mp3(root / F4)  # no ID3 at all
    (root / F5).write_bytes(b'NOTMP3JUNKDATA' * 24)
    build_mp3(root / TWIN_A)
    set_tags(root / TWIN_A, artist='Twin Act', title='Same Song')
    build_mp3(root / TWIN_B)
    set_tags(root / TWIN_B, artist='Twin Act', title='Same Song')
    build_mp3(root / F8)
    set_tags(root / F8, artist='Late Band', title='Slow Burn')


def snapshot_tree(root: Path):
    out = {}
    for dirpath, _dirs, filenames in os.walk(str(root)):
        rel_dir = os.path.relpath(dirpath, str(root))
        rel_dir = '' if rel_dir == '.' else rel_dir.replace(os.sep, '/')
        for name in sorted(filenames):
            path = Path(dirpath) / name
            data = path.read_bytes()
            stat_result = os.lstat(path)
            rel = f'{rel_dir}/{name}' if rel_dir else name
            out[rel] = (hashlib.sha256(data).hexdigest(), len(data), int(stat_result.st_mtime_ns))
    return out


def diff_excluding_journal(before, after):
    prefix = JOURNAL_DIRNAME + '/'  # journals/backups are preserved by design
    a = {k: v for k, v in before.items() if not k.startswith(prefix)}
    b = {k: v for k, v in after.items() if not k.startswith(prefix)}
    return (sorted(set(a) - set(b)), sorted(set(b) - set(a)),
            [rel for rel in a.keys() & set(b) if a[rel] != b[rel]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, default=Path('build/appimage/bulk-rename-tests.json'))
    args = parser.parse_args()
    image = args.image.resolve(strict=True)

    with tempfile.TemporaryDirectory(prefix='musicsync-bulkrename-image-') as temporary:
        root = Path(temporary)
        library = root / 'library'
        library.mkdir()
        build_library(library)
        pre = snapshot_tree(library)

        # Isolated identity + XDG state for the packaged process.
        home = root / 'home'
        home.mkdir(mode=0o700)
        for name in ('config', 'state', 'data'):
            (home / name).mkdir()
        runtime_dir = home / 'runtime'
        runtime_dir.mkdir(mode=0o700)

        host_bin = root / 'host-tools'
        host_bin.mkdir()
        for name in ('kdeconnect-cli', 'sshfs', 'fusermount3', 'findmnt', 'mountpoint'):
            found = shutil.which(name)
            if found:
                (host_bin / name).symlink_to(found)

        env = {
            'PATH': str(host_bin),
            'HOME': str(home),
            'XDG_CONFIG_HOME': str(home / 'config'),
            'XDG_STATE_HOME': str(home / 'state'),
            'XDG_DATA_HOME': str(home / 'data'),
            'XDG_RUNTIME_DIR': str(runtime_dir),
            'QT_QPA_PLATFORM': 'offscreen',
            'MUSICSYNC_BULK_RENAME_LIBRARY': str(library),
            'MUSICSYNC_BULK_EXPECT_JSON': json.dumps({
                'applied': APPLIED_RELS,
                'checkable': CHECKABLE_RELS,
                'rejected_codes': REJECTED_CODES,
                'proposals': PROPOSALS,
            }),
        }

        results = {'image': str(image),
                   'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest()}

        completed = subprocess.run([str(image), '--bulk-rename-test'], env=env,
                                   capture_output=True, text=True, timeout=300)
        results['returncode'] = completed.returncode
        line = next((line for line in completed.stdout.splitlines()
                     if line.startswith('MUSICSYNC_CHECK=')), None)
        if line is None:
            results['stdout_tail'] = completed.stdout[-4000:]
            results['stderr_tail'] = completed.stderr[-4000:]
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2, ensure_ascii=True) + '\n')
            raise RuntimeError('no MUSICSYNC_CHECK line; see ' + str(args.output))

        evidence = json.loads(line.split('=', 1)[1])
        results['evidence'] = evidence
        br = evidence.get('bulk_rename', {})
        results['flow'] = {
            'result': evidence.get('result'),
            'error': evidence.get('error'),
            'history_unchanged': evidence.get('history_unchanged'),
            'device_status': evidence.get('device_status'),
            'item_count': br.get('item_count'),
            'counts_by_status': br.get('counts_by_status'),
            'default_checked': br.get('default_checked'),
            'applied': br.get('applied'),
            'rejected': br.get('rejected'),
            'partial': br.get('partial'),
            'canceled': br.get('canceled'),
            'session_state_after_undo': br.get('session_state_after_undo'),
            'undo_restored': br.get('undo_restored'),
        }

        # Out-of-process re-verification of the final library state.
        post = snapshot_tree(library)
        missing, extra, changed = diff_excluding_journal(pre, post)
        results['final_tree'] = {'missing': missing, 'extra': extra, 'changed': changed}
        journal_dir = library / JOURNAL_DIRNAME
        results['journal_preserved'] = (sorted(p.name for p in (journal_dir / 'sessions').glob('*.jsonl'))
                                        if (journal_dir / 'sessions').is_dir() else [])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=True) + '\n')

    failures = []
    evidence = results['evidence']
    br = evidence.get('bulk_rename', {})
    if completed.returncode != 0:
        failures.append(f'image exited {completed.returncode}')
    if evidence.get('result') != 'PASS':
        failures.append(f"flow result is not PASS: {evidence.get('error')}")
    if evidence.get('history_unchanged') is not True:
        failures.append('last-sync history changed (must stay untouched)')
    for key in ('tree_missing', 'tree_extra', 'tree_changed'):
        if br.get(key):
            failures.append(f'in-process tree restore mismatch: {key}={br[key]}')
    missing, extra, changed = results['final_tree']['missing'], results['final_tree']['extra'], results['final_tree']['changed']
    for label, values in (('missing', missing), ('extra', extra), ('changed', changed)):
        if values:
            failures.append(f'out-of-process tree mismatch after undo ({label}): {values}')

    # No host-Python borrowing: the runtime must be the frozen (Nuitka
    # standalone) image, and the engine module must resolve to our vendored
    # copy. Nuitka keeps original source paths for __file__, so absolute host
    # site-packages locations are rejected while compiled-bundle paths pass.
    if evidence.get('frozen') is not True:
        failures.append('runtime is not frozen (host Python may be borrowed)')
    engine_file = str(evidence.get('vendored_engine_file', '') or '')
    if engine_file in ('', 'None'):
        results['engine_note'] = 'compiled module exposes no __file__; frozen runtime proves bundling'
    elif not engine_file.endswith('musicsync/vendored/engine.py'):
        failures.append(f'unexpected vendored engine location: {engine_file!r}')
    elif '/site-packages/' in engine_file or '/dist-packages/' in engine_file:
        failures.append(f'vendored engine appears to come from host Python: {engine_file!r}')

    print(json.dumps(results['flow'], indent=2, ensure_ascii=True))
    print('Engine module:', engine_file)
    print('Journal sessions preserved after undo:', results['journal_preserved'])
    if failures:
        for failure in failures:
            print('FAIL:', failure)
        print('Evidence:', args.output)
        raise SystemExit(1)
    print(f'PASS: packaged Bulk Rename workflow on synthetic fixture; tree byte-exact after undo. Evidence: {args.output}')


if __name__ == '__main__':
    main()
