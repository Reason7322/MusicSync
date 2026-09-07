# Behavioral reference read before implementation

Reference: `~/.local/bin/syncmusic`, SHA-256
`8abd5783bf9deb6b90ccaf26d79be4f900f7f0cc2ee927f6674aa643c155d434`.
The application never invokes or edits this fallback.

1. Fish accepts `-n` / `--dry-run` and help, rejects other arguments.
2. Require KDE Connect, rsync, findmnt, mountpoint, fusermount3 and find;
   additionally rsgain and its preset for real runs.
3. Require a source directory containing at least one regular file (`find`).
4. Discover available paired/reachable devices with `--list-available --id-name-only`.
5. Real runs execute `rsgain easy -S -m 4 -p no_album.ini SOURCE` and stop on
   failure. Preview skips rsgain completely. Recheck connectivity afterward.
6. Get mountpoint from KDE Connect, construct Android shared-storage and Music paths.
7. Existing mounts must pass mountpoint plus findmnt `fuse.sshfs` and
   `kdeconnect@*` checks. Unexpected mounts must never be detached.
8. Probe existing storage with `ls -d`. If stale, lazily detach with
   `fusermount3 -uz`, verify detached and still connected, mount exactly once,
   revalidate. An initially absent mount is mounted once. Failed partial mounts
   are cleaned up. A still-broken replacement stops with phone restart advice.
9. Repeat mount identity and storage access checks. Require the existing Music
   directory; never create it. Real runs create/remove a write probe; previews do not.
10. rsync uses `-rtv --omit-dir-times --human-readable --itemize-changes
    --info=progress2 --delete-after --exclude=/.thumbnails/`, with source and
    destination trailing slashes, plus `--dry-run` for previews. No archive mode,
    ignore-errors or delete-excluded. Fail on nonzero exit.
11. Leave healthy preexisting mounts alone. For app-created/remounted mounts,
    normal unmount followed by lazy detach on failure, including exit cleanup.

## Deliberate application improvements

* All commands and potentially blocking filesystem operations run through QProcess.
* Directory accessibility uses actual enumeration, stronger than `ls -d` metadata.
* Cleanup rechecks mount ID and KDE SSHFS identity, including partial-mount failures.
  The script's partial-mount cleanup did not repeat that identity check.
* Fresh post-ReplayGain preview and deletion approval; final source and destination
  inventories detect changes while approving. A deletion cap also counts directories.
* Guarded rsync pins open source/destination directories and verifies Linux mount IDs
  before exec, so lazy unmount cannot redirect rsync into an ordinary local directory.
* Reject source symlinks/special files and remote directory symlinks/nested mounts
  rather than silently skip or follow them. This is intentionally more conservative.
* Recheck with a dry-run after successful rsync before recording success.

## Interfaces checked during implementation

Installed Python 3.14.7, PySide6 6.11.2, KDE Connect 26.08.0, rsync 3.5.0,
rsgain 3.6 and sshfs 3.7.6. Fedora cached repository metadata was inspected;
the already-installed PySide6 is reused. Cached availability is not fresh repo state.

* [Qt QProcess](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html)
* [KDE Connect CLI source](https://github.com/KDE/kdeconnect-kde/blob/master/cli/kdeconnect-cli.cpp)
* [rsgain upstream](https://github.com/complexlogic/rsgain)
* Installed `kdeconnect-cli --help`, `rsgain easy --help`, `man rsync`, and the
  installed `no_album.ini` (Album=false, PreserveMtimes=false).
