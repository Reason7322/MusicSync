#!/usr/bin/env python3
"""Test an actual image; writes music only under a temporary test directory.

GUI/phone checks are explicit options. --preview uses the saved user settings,
never performs a real sync, never tags the real library or writes a phone probe.
The JSON output can contain personal paths: keep it in ignored build/.
Host Python orchestrates these tests; the image itself must work with a PATH
containing only its host integration tools, without Python/Qt/rsync/rsgain.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(args, **kwargs):
    result = subprocess.run([str(a) for a in args], capture_output=True,
                            text=True, timeout=240, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args[0]} exited {result.returncode}:\n{result.stdout}\n{result.stderr}')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('build/appimage/runtime-tests.json'))
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    results = {}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2, ensure_ascii=True) + '\n')

    with tempfile.TemporaryDirectory(prefix='musicsync-appimage-test-') as temporary:
        root = Path(temporary)
        host_bin = root / 'host-tools'
        host_bin.mkdir()
        for name in ('kdeconnect-cli', 'sshfs', 'fusermount3', 'findmnt', 'mountpoint'):
            found = shutil.which(name)
            if found:
                (host_bin / name).symlink_to(found)
        env = dict(os.environ, PATH=str(host_bin))
        results['runtime'] = json.loads(run([image, '--runtime-info'], env=env))
        assert results['runtime']['frozen']
        assert results['runtime']['appdir'] != 'None'
        loaded = results['runtime']['loaded_qt_libraries']
        assert loaded and all(path.startswith(results['runtime']['appdir'] + '/') for path in loaded)
        empty_bin = root / 'empty-path'
        empty_bin.mkdir()
        # The outer type-2 mount runtime needs fusermount3 before MusicSync can
        # report absent KDE Connect/SSHFS tools. Keep that one host prerequisite.
        (empty_bin / 'fusermount3').symlink_to(shutil.which('fusermount3'))
        missing = subprocess.run([str(image), '--musicsync-worker', json.dumps({
            'action': 'dependencies', 'programs': ['kdeconnect-cli', 'sshfs']})],
            env=dict(env, PATH=str(empty_bin)), capture_output=True, text=True, timeout=30)
        assert missing.returncode == 1 and 'kdeconnect-cli' in missing.stderr and 'sshfs' in missing.stderr
        results['missing_host_dependencies'] = missing.stderr.strip()
        for name in ('rsync', 'rsgain'):
            assert '/usr/libexec/musicsync/' in results['runtime']['tools'][name]
            results[name + '_version'] = run([image, '--tool-version', name], env=env)
        run([image, '--appimage-extract'], cwd=root)
        appdir = root / 'AppDir Ω ; $literal'
        (root / 'squashfs-root').rename(appdir)
        manifest_path = image.parent / 'appimage-build-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        actual_files = {str(p.relative_to(appdir)) for p in appdir.rglob('*') if p.is_file()}
        assert actual_files == set(manifest['files']), 'Manifest file inventory differs from extracted image'
        for name, digest in manifest['files'].items():
            data = (appdir / name).read_bytes()
            assert hashlib.sha256(data).hexdigest() == digest, name
            assert str(Path.home()).encode() not in data, f'Personal home path in {name}'
        results['verified_manifest_files'] = len(manifest['files'])
        results['relocated_appdir'] = json.loads(run([appdir / 'AppRun', '--runtime-info'], env=env))
        assert results['relocated_appdir']['appdir'] == str(appdir)
        tools = appdir / 'usr/libexec/musicsync'
        source, dest = root / 'source Ω ; $literal', root / 'destination Ω'
        source.mkdir(); dest.mkdir()
        song = source / 'track Ω ; $(literal).mp3'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
             '-c:a', 'libmp3lame', song])
        before = hashlib.sha256(song.read_bytes()).hexdigest()
        preset = appdir / 'usr/share/musicsync/presets/no_album.ini'
        gain_args = [tools / 'rsgain', 'easy', '-S', '-m', '4', '-p', preset, source]
        results['tagging'] = run(gain_args)
        tagged = hashlib.sha256(song.read_bytes()).hexdigest()
        assert before != tagged
        tags = json.loads(run(['ffprobe', '-v', 'error', '-show_entries', 'format_tags', '-of', 'json', song]))
        names = {name.lower() for name in tags['format']['tags']}
        assert 'replaygain_track_gain' in names and 'replaygain_album_gain' not in names
        results['skip_existing'] = run(gain_args)
        assert hashlib.sha256(song.read_bytes()).hexdigest() == tagged
        results['track_only_tags'] = True
        (dest / 'extra.mp3').write_bytes(b'isolated deletion fixture')
        thumbnails = dest / '.thumbnails'
        thumbnails.mkdir()
        (thumbnails / 'keep').write_bytes(b'preserve')
        sync_args = [tools / 'rsync', '-rtv', '--omit-dir-times', '--human-readable',
                     '--itemize-changes', '--info=progress2', '--delete-after',
                     '--exclude=/.thumbnails/', str(source) + '/', str(dest) + '/']
        results['temporary_preview'] = run(sync_args[:1] + ['--dry-run'] + sync_args[1:])
        assert (dest / 'extra.mp3').exists() and not (dest / song.name).exists()
        assert hashlib.sha256(song.read_bytes()).hexdigest() == tagged
        results['temporary_mirror'] = run(sync_args)
        assert not (dest / 'extra.mp3').exists()
        assert (dest / song.name).read_bytes() == song.read_bytes()
        assert (thumbnails / 'keep').read_bytes() == b'preserve'
        results['temporary_mirror_verified'] = True
        save()
        if args.gui:
            fresh = root / 'first-run-home'
            fresh.mkdir()
            fresh_env = dict(env, HOME=str(fresh), XDG_CONFIG_HOME=str(fresh / 'config'),
                             XDG_STATE_HOME=str(fresh / 'state'), XDG_DATA_HOME=str(fresh / 'data'))
            output = run([image, '--smoke-test'], env=fresh_env)
            line = next(line for line in output.splitlines() if line.startswith('MUSICSYNC_CHECK='))
            first_run = json.loads(line.split('=', 1)[1])
            results['first_run'] = first_run
            save()
            assert first_run['result'] == 'PASS' and not first_run['configured'], first_run
            assert first_run['device_status'] == 'Choose a device in Settings', first_run
            assert first_run['config'] == str(fresh / 'config/musicsync')
            assert first_run['state'] == str(fresh / 'state/musicsync')
        for flag, enabled in (('--smoke-test', args.gui), ('--preview-test', args.preview)):
            if enabled:
                completed = subprocess.run([str(image), flag], env=env, capture_output=True,
                                           text=True, timeout=240)
                line = next((line for line in completed.stdout.splitlines()
                             if line.startswith('MUSICSYNC_CHECK=')), None)
                if line is None:
                    results[flag] = dict(result='FAIL', stdout=completed.stdout, stderr=completed.stderr)
                    save()
                    raise RuntimeError(f'{flag}: no diagnostic result; see {args.output}')
                evidence = json.loads(line.split('=', 1)[1])
                evidence['stderr'] = completed.stderr
                results[flag] = evidence
                save()
                assert completed.returncode == 0 and evidence['result'] == 'PASS', evidence
                assert evidence['qt_platform'] == 'wayland', evidence
    save()
    print('PASS: actual image, private runtime/tools, isolated tagging/mirror; requested GUI/preview checks.')
    print('Evidence:', args.output)


if __name__ == '__main__':
    main()
