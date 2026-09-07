# Verification record — 2026-09-07

## Environment

* Fedora installed RPMs: Python 3.14.7-1.fc44, PySide6 6.11.2-1.fc44,
  kdeconnectd 26.08.0-1.fc44, rsync 3.5.0-1.fc44, rsgain 3.6-5.fc44,
  fuse-sshfs 3.7.6-1.fc44.
* Existing system PySide6 reused by `.venv --system-site-packages`.
* `python3-pytest` and setuptools were not installed; standard-library unittest
  and source-tree launching avoid dependency downloads.
* Cached Fedora repositories listed PySide6 and pytest, but cache versions did
  not fully match installed PySide6. Installed/current runtime was the authority.

## Automated checks

34 test methods passed at this stage, including parametrized subcases:

* Device and mount parsing, normalized settings, serialization, deletion thresholds.
* Itemized Add/Update/Delete parsing, directories, spaces, pipes, newlines,
  backslashes and Unicode filenames; progress2 parsing.
* Mock lifecycle: real and preview ordering, fail-closed checks, cancellation,
  healthy borrowed mount, one stale remount, broken replacement, unexpected
  filesystem, ownership cleanup and changed cleanup mount.
* QProcess: incremental stdout/stderr and CR output, missing executable,
  timeout, SIGTERM resistance and kill escalation.
* Real temporary-directory rsync: copy/update/delete, timestamp preservation,
  dry-run nonmutation, deletion cap and `.thumbnails/` preservation.
* Real synthetic MP3: rsgain writes track gain and peak without album gain;
  second skip-existing pass preserves identical file bytes.
* Guarded exec: changed/empty source or changed destination never reaches exec;
  successful guard uses pinned descriptors and the approved deletion cap.
* Controller terminal states and last-success history persistence rules.

Syntax compilation and desktop-file validation also pass. No configured type
checker is claimed. The initial PySide6 lifetime crash in a test was corrected
by keeping one persistent QProcess per runner; subsequent suites pass.

## Real Android test phone evidence

* Discovered the connected Android test phone with the installed CLI.
  Personal device identifiers and host paths in this historical record are redacted.
* KDE Connect supplied `/run/user/1000/<device-id>`.
  This is an observation, not a configured constant.
* Existing mount had type `fuse.sshfs` and source `kdeconnect@…:/`.
  Mount IDs are namespace-local and are compared only within the application's
  process namespace, not to unrelated diagnostic-session IDs.
* Application preview: 150 regular music files, 814.44 MB; zero changes.
* Native Widgets window reported Qt platform **wayland**, displayed Connected
  and 150 tracks / 814.4 MB, and performed Preview via Qt's button-click API.
  A grab of that actual window confirmed the absence of a custom stylesheet.
  The screenshot was omitted from the public tree because it exposed personal data;
  this historical result is retained, not claimed as a new test of current code.
* Real application controller run: rsgain skipped all 150 existing tagged files,
  no files scanned; phone write/delete probes succeeded; rsync returned 0;
  post-sync dry-run returned 0 and no changes. Success recorded in the user's
  XDG state directory. No music copies/deletions were needed in this run.
* Healthy preexisting mount was left in place by all these tests.
* The original Fish script's SHA-256 still matched
  `8abd5783bf9deb6b90ccaf26d79be4f900f7f0cc2ee927f6674aa643c155d434`.
* Desktop entry, SVG icon and separate `~/.local/bin/musicsync` launcher installed.
  Installed desktop/icon bytes matched the project artifacts; desktop validation
  passed. The installed command opened the application at 00:30 CEST, logged
  `Qt platform=wayland`, and detected the connected phone without mounting/syncing.

## Boundaries

No actual stale SFTP failure, unexpected mount replacement, interrupted physical
transfer or app-owned real remount was forced on the user's phone. Those cases
have logic tests, not physical-phone proof. Do not unmount a healthy borrowed
mount simply to manufacture test coverage. A future naturally-unmounted session
can verify real app-owned mounting/cleanup without disturbing another workflow.
