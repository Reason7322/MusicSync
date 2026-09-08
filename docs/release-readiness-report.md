# MusicSync release-readiness report

> AppImage follow-up, 2026-09-08: see [the AppImage build and runtime report](appimage-build-report.md).
> The current machine-readable suite contains 128 passing test methods, including
> packaging and first-mount startup regressions. The original audit below remains
> historical; its old Git/physical-test findings are not a description of the
> current AppImage test run.
> GTK3/Ubuntu GNOME and qt6ct regression results are in the
> [GTK3 integration report](gtk3-appimage-report.md).

Audit date: **2026-09-07**, Europe/Warsaw. Project:
`MusicSync/ (repository root)`.

> Historical audit snapshot, before publication preparation. The results and
> Git failure below describe that earlier state. Publication preparation later
> found an externally initialized Git repository with no commits or tracked files;
> no Git mutations were performed by the preparation task. See
> [publication checks](publication-checks.md) for the updated test run and scope.
> Personal paths/device identifiers are redacted. The original test results,
> static results and source hashes are retained as historical evidence.

## Decision

**Ready for controlled manual testing, not signed off for release.**

The final automated suite passed **100 test methods and 99 additional parameterized
subtest records: 199 PASS records, zero failures, zero errors, zero skips**.
The full run completed at **01:02:39 CEST in 14.025 seconds**. It includes all
34 original test methods and 66 new release-audit methods. Seven genuine bugs
were reproduced, fixed and regression-tested. The interrupted continuation
inspected and reused this saved passing run; completed tests were not restarted
merely because the conversation resumed.

Release sign-off remains blocked by the absence of a Git repository/revision and
the uncompleted physical-device acceptance checks below. No known automated
safety regression remains failing in the tested cases. This does not mean all
possible filesystem races or physical failures have been exercised.

**Restart an already-running Music Sync before manual testing**, so it loads the
fixed modules. No automatic synchronization has been added.

## Evidence and boundaries

* [Complete per-test and per-subtest results](release-test-results-initial.json) — canonical
  results, individual names, durations and statuses. Every record is also listed
  in the appendix below.
* [Static checks and Git result](release-static-results.json).
* [Initial implementation verification](verification.md) — historical evidence,
  not proof that the revised code passed a new physical-phone run.
* [Original Fish script behavior](script-reference.md).

No destructive test in this audit used `~/Music` or the phone's
`/storage/emulated/0/Music`. Actual rsync deletions and ReplayGain writes used
temporary fixtures. Device/mount workflow tests used fake KDE Connect responses.
Widget tests used real Qt Widgets **offscreen**, with fake device services and
controlled Python subprocesses. They did not operate a real phone mount.

A separate, strictly read-only live check was prepared in
`scripts/release_live_readonly.py`. It requires an existing mount and cannot run
mount, unmount, write probes, rsgain or real rsync. Its invocation was interrupted
before a completion result; **no `release-live-readonly.json` evidence file was
produced**. No current-pass physical-device success is claimed. The earlier
implementation's healthy-Android test phone preview/zero-change real sync remains historical
evidence only.

The fallback `~/.local/bin/syncmusic` remained unchanged; its SHA-256
was rechecked as
`8abd5783bf9deb6b90ccaf26d79be4f900f7f0cc2ee927f6674aa643c155d434`.
The user's installed launch files were only read/validated in this audit; portable
installation, overwrite protection and uninstallation were exercised in fake homes.

## Environment and commands

Installed versions inspected: Python **3.14.7**, PySide6 **6.11.2**, KDE Connect
**26.08.0**, rsync **3.5.0**, rsgain **3.6**, fuse-sshfs **3.7.6**.
Existing Fedora bindings were reused through the project venv. No new packages,
global pip installs, sudo, compositor changes or theme changes were needed.

Commands, from the project directory:

```fish
.venv/bin/python scripts/run_release_tests.py
.venv/bin/python -m compileall -q src tests scripts
desktop-file-validate resources/io.github.reason.MusicSync.desktop
desktop-file-validate ~/.local/share/applications/io.github.reason.MusicSync.desktop
sh -n scripts/musicsync
git rev-parse --show-toplevel
```

The complete suite was run outside the restrictive sandbox because its temporary
Unix-socket fixture could not bind inside it. An initial socket test received
`EPERM`; the same test passed outside the sandbox. A separate retry initially
omitted `PYTHONPATH`, producing an import error; the source-path-corrected retry
passed. Neither was an application bug. The final suite runner sets source paths
explicitly and recorded zero skips/errors.

There is **no configured lint or type-check command** in `pyproject.toml`, and no
ruff/mypy/pylint installation was assumed. Syntax compilation, shell syntax,
desktop validation and the automated Python AST process-safety audit passed.
A linter/type-checker run is **NOT TESTED (not configured)**; it is not disguised
as a passing lint run.

## Requirement coverage

PASS below refers to the described test level. A simulated mount result is never
a physical mount verification. PARTIAL means a stated portion remains unverified.

| Requirement | Status | How tested / boundary |
| --- | --- | --- |
| Source exists and contains files | PASS | Real temporary missing/empty directories, directory-only trees, zero-byte regular files, exclusions-only trees; source scan failures block rsync. |
| Empty-source deletion protection | PASS | Empty source fails before device/mount work; guard detects a source emptied after its preview. No real library deletion test. |
| Unreadable source subtree | PASS | Actual chmod-000 temporary directory and sender file; scan fails, and actual rsync sender I/O failure leaves a phone-only fixture file intact. |
| Destination validation | PASS | Real descriptor walking with mocked mount identity: missing destination is not created, symlink components fail; mocked inaccessible destinations block progression. |
| Phone write/delete capability | PASS | Tiny probes in temporary directories; injected read-only create failure and delete denial, including retry and visible orphan filename. No real phone write probe this pass. |
| Expected SSHFS/KDE mount | PASS | FSTYPE/source/target/ID parsing; absent, duplicated, malformed, wrong source/type/ID and nested-mount cases fail closed. Linux `/proc` mount identity is simulated for these cases. |
| Stale-mount workflow | PASS | Simulated EIO/timeout, single recovery, failed detach, unsuccessful detach, disconnected device, and broken fresh mount. No infinite remount loop. |
| Borrowed versus app-created mounts | PASS | Healthy borrowed mounts survive success/failure; owned/partial mounts clean up after failure/cancel; changed/unexpected identity is left alone. |
| Cleanup fallback | PASS | Normal unmount failure invokes one lazy fallback; failures remain visible; timeout cannot be treated as successful cleanup. All mount mutations mocked. |
| rsync preview parsing | PASS | Actual temporary rsync output plus malformed-record fixtures; filename escaping and Unicode record-boundary regression. |
| Add / Update / Delete | PASS | New files, changed file data, metadata-only updates, deleted files and directories; exact sizes enriched from inventories. |
| Mirror versus update-only | PASS | Actual temporary rsync: mirror removes extras; update-only retains extras while copying new/changed files. |
| `.thumbnails/` | PASS | Actual nested thumbnail fixture is preserved at sync root; non-root `.thumbnails` follows ordinary mirror rules, confirming the anchored exclusion. |
| Suspicious deletion thresholds | PASS | Zero/unknown totals, exact 20%, above 20%, 49/50 files, directory-inclusive cap, accept/refuse paths; real Widgets dialog defaults to cancellation and lists deletion names. |
| Source/destination changed after preview | PASS | Real temporary snapshots modified/emptied after preview never reach guarded exec; final verification detects remaining changes. Uses size/mtime/name fingerprints, not content checksums. |
| ReplayGain enabled/disabled | PASS | Workflow invocation/order checked; disabling omits both dependency and invocation; post-tag source rescan and connectivity recheck covered. |
| ReplayGain new/existing tracks | PASS | Real generated MP3 and rsgain: track gain/peak present, album gain absent; second skip-existing pass is byte-for-byte unchanged. |
| ReplayGain failure | PASS | Injected nonzero process outcome stops before mounting/syncing; missing executable/preset handled by dependency checks. |
| Genuine Preview | PASS | No rsgain or write probe in generated workflow; all rsync commands dry-run; real temporary PC/phone file hashes and mtimes remain identical. |
| rsync failure/cancellation | PASS | Nonzero exit, failed verification, actual throttled temporary rsync cancellation; `--delete-after` preserves the extra fixture file when transfer is interrupted. |
| ReplayGain cancellation | PASS | Cancellation at ReplayGain workflow state and window close during a controlled subprocess in that state. **This is not an actual rsgain-in-progress cancellation test.** |
| Subprocess cancellation | PASS | SIGTERM, timeout, SIGTERM-resistant leader/child, process-group escalation, and cancellation before process launch. Descendant liveness checked via `/proc`. |
| Shutdown during active operation | PASS | Real offscreen window closed during mounting, ReplayGain, rsync, approval and cleanup; controlled subprocess termination and simulated mount cleanup verified. |
| Repeated button presses/concurrency | PASS | Twenty repeated Preview/Sync clicks plus direct repeated controller starts produce one operation; Settings disabled while active. Other external sync utilities are outside this lock/protection. |
| Settings persistence/validation | PASS | All fields roundtrip, malformed/unknown input rejected, strict boolean/thread validation, mode 0600, atomic replace failure preserves previous content; actual settings dialog saves to isolated XDG home. |
| Unicode/whitespace/shell metacharacters | PASS | Actual rsync with Unicode, spaces, tabs/newlines, leading dash, quotes, pipes, dollar/backtick expressions, percent and backslash escapes; no injected marker created. Relocated launcher tested separately. |
| Symlinks/special files | PASS | Source-root/file/directory/dangling links, FIFO and Unix socket rejected; destination symlink component and nested-mount rejection tested. |
| Remote normalization/traversal | PASS | Storage root, parent traversal, dot/repeated/trailing slashes, wrong prefix, double leading slash and NUL rejected. |
| Logs | PASS | Isolated XDG location, rotation and handler de-duplication, ANSI cleanup, process diagnostics/progress routed to Widgets log. App never requests credential/key data. |
| Last-success semantics | PASS | Preview/failure/cancel preserve an existing history file byte-for-byte; success records timezone, paths/device, counts/bytes/ReplayGain; history write error visible and preserves prior record. |
| Missing dependencies | PASS | Every runtime program checked via missing-tool fixtures; actual nonexistent executable exercises QProcess FailedToStart; missing preset handled. |
| Progress parsing | PASS | Bytes/human units/percent/speed/time, CR-separated incremental output, unknown lines ignored; live offscreen widgets update while a controlled process runs. |
| Large library | PASS | 10,000 real temporary files scanned through a worker and parsed; 10,000-row Qt table, event-loop return and timing bound checked. Larger/network libraries are not benchmarked. |
| Desktop file | PASS | Source template, generated relocated file and user's existing installed desktop entry pass desktop-file-validate. |
| Portable launcher/installer | PASS | Fresh source copy with spaces, quotes, Unicode, `$`, backticks, `%`, `&` and `;`; dynamic install path, exact argv forwarding, idempotence, protected overwrite, uninstall in fake home. No fixed developer root in shipped launcher/template/installer. |
| Unsafe shell invocation | PASS | AST inspection of all application Python code rejects shell execution/waits; manual launcher/installer review and shell syntax validation. Controlled test subprocesses use argument arrays. |
| Configured static checks | PASS | compileall, desktop validation, sh syntax and AST process audit. |
| Lint/type checker | NOT TESTED | None configured; no lint/type-check success claimed. |
| Clean Git release state | FAIL | Project is not a Git repository; `git rev-parse` returns 128. No commit hash, staged/unstaged baseline or clean-state assertion exists. |
| Fresh checkout/setup | PARTIAL | Fresh **source snapshot copy** with a newly created system-site-packages venv launched from unrelated cwd under fake HOME, fake KDE CLI and isolated XDG directories. A real Git checkout cannot be tested without a repository. |
| Wheel/isolated-PyPI installation | NOT TESTED | README's source-tree/Fedora-Qt path tested; no wheel built or downloaded dependency environment validated. Not required for using the local source launcher. |
| Current live Android test phone read-only pass | NOT TESTED | Invocation interrupted without saved result. Historical phone evidence is explicitly separate. |
| Physical stale recovery / real owned mount lifecycle | NOT TESTED | No stale SFTP server, unmount, remount or real phone mutation was forced. |

Measured examples from targeted runs: the 10,000-file scan-plus-parse completed in
**0.128 s**, and 10,000-row table population in **0.067–0.072 s**. These are local
cached/temporary-fixture observations, not phone-network performance claims.

## Bugs discovered and fixes

Each code change below addressed a reproduced defect. No feature was removed or
weakened to make a test pass. Initial FAIL results are described here; the final
per-test evidence records their passing post-fix outcomes.

| ID | Reproduced defect | Fix | Regression evidence |
| --- | --- | --- | --- |
| B1 | Python `splitlines()` treated valid Unicode filename characters NEL/U+2028/U+2029 as record boundaries, returning truncated filenames such as `left`. | Workflow parser now splits only protocol CR/LF boundaries. | `test_unicode_line_separator_is_a_filename_not_a_record_boundary`; actual unusual-name rsync test. |
| B2 | Cancelling a utility leader left a SIGTERM-resistant descendant alive. | QProcess creates a separate session; SIGTERM/SIGKILL target that utility process group. Completion/cleanup waits for descendant escalation when the leader exits first. | `test_cancel_does_not_leave_a_child_process_running` initially failed, then passed; actual temporary rsync cancellation and existing escalation tests pass. |
| B3 | Cancellation received through the pre-launch `started` signal still launched the command, which created a marker. | Honour pending cancellation before QProcess.start; cancel a process that finishes startup after cancellation via its actual started signal. | `test_cancel_from_started_signal_does_not_launch_command` initially created a marker; now no marker exists. |
| B4 | Desktop installation failed from any source directory except the development machine's original absolute path. | Generate desktop Exec from the actual install root with specification-compliant quoting; installed launcher uses Python execv argument arrays. Recognize only exact legacy artifacts for safe upgrade. | Relocated installer test initially exited 2; final relocation, quoting, forwarding, overwrite protection and fake-home uninstall pass. |
| B5 | Closing while deletion approval was pending cancelled the workflow but left its modal dialog visible. | Reject any remaining approval dialog when the operation completes, including cancellation after cleanup. | `test_close_while_approval_pending_stops_without_sync` initially failed visibility assertion; now both windows close and no sync starts. |
| B6 | Some mount presence/cleanup paths trusted an exit code even when the result carried a timeout. A mocked zero-exit timeout allowed progression; a 32-exit timeout falsely claimed cleanup. | Timeout is authoritative on mount identity, cleanup probes and presence; startup source/findmnt checks also reject timed-out success. | `test_mount_presence_timeout_never_authorizes_sync_even_exit_zero` and `test_cleanup_presence_timeout_does_not_claim_unmounted` initially failed; now pass. |
| B7 | Startup permission errors were labelled “Not mounted,” concealing a failed inspection. | Unexpected mountpoint exit codes/timeouts report filesystem status unavailable and retain error details. | `test_mount_status_permission_error_is_not_reported_as_unmounted` initially failed; now reports an error. |

Desktop quoting was checked against the primary
[Desktop Entry specification](https://specifications.freedesktop.org/desktop-entry/latest-single/).
Process-group support was confirmed in installed PySide6's `UnixProcessFlag.CreateNewSession`
and `setUnixProcessParameters` APIs. The application still uses external tools,
argument arrays, the original mirror flags, and explicit mount ownership.

## Files changed by this audit

Application bug fixes: `backend/process.py`, `backend/workflow.py`,
`backend/status.py`, `main_window.py`, `scripts/install_desktop.py`, and the
desktop template. README updated for cancellation/portable installation and tests.

New suites: `test_release_core.py`, `test_release_io.py`,
`test_release_packaging.py`, `test_release_gui.py`, and
`test_release_history_status.py`. Existing `test_process.py` now creates an
offscreen QApplication for widget tests; this does not change normal app theming.
New tools: `scripts/run_release_tests.py` and the opt-in read-only live-check script.
Original test suites remain and were run together with the new suites.

## Manual acceptance and remaining release blockers

1. **Release blocker: version-control baseline.** Establish the intended Git
   repository and review/commit the candidate; then repeat setup from that exact
   checkout and record its commit and clean status. This audit did not invent a
   repository, stage files, commit, or claim a clean tree.
2. **Release sign-off gate: real Wayland interaction after the fixes.** Restart the
   app; inspect theme/layout, status, file table, keyboard navigation, Settings,
   error details and deletion approval on a safe fixture. Automated GUI tests
   are offscreen, not a new Hyprland/Wayland acceptance run.
3. **Release sign-off gate: safe physical phone lifecycle.** First run the provided
   read-only check while the phone is already healthy/mounted. On a later session
   when no other workflow owns its mount, test app-created mounting and cleanup
   with Preview. Do not detach a healthy borrowed mount merely for coverage.
4. **Release sign-off gate: physical interruption/recovery.** With an explicitly
   isolated phone test destination and suitable authorization, verify real
   disconnection/stale-SFTP recovery, failed replacement, and cancellation during
   transfer. These were simulated here; no destructive real-Music test is authorized.
5. **Additional acceptance:** observe actual rsgain cancellation on a disposable
   music fixture; verify Auxio playback/refresh and real newly tagged tracks using
   an isolated or explicitly approved phone integration. No listening claim is made.
6. If distributing wheels rather than this local source launcher, build and test
   that package artifact and its isolated dependency installation first.

No blanket claim of race-free or transactional synchronization is made. The guard
checks snapshots immediately before exec and pins directory references, but
external edits during rsync are outside an atomic transaction. Existing
same-size/same-mtime content comparison, special-file exclusions, supported remote
root and no-rollback limitations remain documented in README.

## Complete executed test inventory

The following appendix is generated directly from the final evidence JSON. Parent
methods and parameterized subtests are both listed so each performed check has an
explicit status. Group methods above explain the fixture/automation level; the
names retain exact regression and parameter identifiers for reproduction.

| Test or parameterized subtest | Status |
| --- | --- |
| `test_controller.ControllerTests.test_terminal_states_and_last_success_rules (mode='preview')` | PASS |
| `test_controller.ControllerTests.test_terminal_states_and_last_success_rules (mode='success')` | PASS |
| `test_controller.ControllerTests.test_terminal_states_and_last_success_rules (mode='failure')` | PASS |
| `test_controller.ControllerTests.test_terminal_states_and_last_success_rules (mode='cancel')` | PASS |
| `test_controller.ControllerTests.test_terminal_states_and_last_success_rules` | PASS |
| `test_filesystem.FilesystemTests.test_empty_and_missing_source` | PASS |
| `test_filesystem.FilesystemTests.test_inventory_snapshot_and_protection` | PASS |
| `test_filesystem.FilesystemTests.test_local_directory_cannot_pass_remote_guard` | PASS |
| `test_filesystem.FilesystemTests.test_no_symlinks` | PASS |
| `test_filesystem.FilesystemTests.test_probe_cleanup` | PASS |
| `test_guards.GuardTests.test_changed_or_empty_source_never_executes (mode='changed')` | PASS |
| `test_guards.GuardTests.test_changed_or_empty_source_never_executes (mode='empty')` | PASS |
| `test_guards.GuardTests.test_changed_or_empty_source_never_executes (mode='phone_changed')` | PASS |
| `test_guards.GuardTests.test_changed_or_empty_source_never_executes` | PASS |
| `test_guards.GuardTests.test_rsync_uses_pinned_directories_and_delete_cap` | PASS |
| `test_logic.LogicTests.test_arguments` | PASS |
| `test_logic.LogicTests.test_devices` | PASS |
| `test_logic.LogicTests.test_itemization` | PASS |
| `test_logic.LogicTests.test_mount_validation` | PASS |
| `test_logic.LogicTests.test_progress` | PASS |
| `test_logic.LogicTests.test_settings` | PASS |
| `test_logic.LogicTests.test_threshold` | PASS |
| `test_process.ProcessTests.test_cancel_and_kill_escalation` | PASS |
| `test_process.ProcessTests.test_delete_cap_blocks_unpreviewed_deletion` | PASS |
| `test_process.ProcessTests.test_failed_to_start` | PASS |
| `test_process.ProcessTests.test_incremental_channels_and_cr` | PASS |
| `test_process.ProcessTests.test_real_rsync_in_temporary_directories` | PASS |
| `test_process.ProcessTests.test_timeout` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_atomic_settings_failure_preserves_previous_content` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_corrupt_settings_do_not_fall_back_to_defaults (data='{')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_corrupt_settings_do_not_fall_back_to_defaults (data='[]')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_corrupt_settings_do_not_fall_back_to_defaults (data='{"unknown":1}')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_corrupt_settings_do_not_fall_back_to_defaults (data='{"threads":0}')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_corrupt_settings_do_not_fall_back_to_defaults` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_deletion_boundary_matrix (deleted=0, total=0)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_deletion_boundary_matrix (deleted=1, total=1)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_deletion_boundary_matrix (deleted=1, total=5)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_deletion_boundary_matrix (deleted=2, total=5)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_deletion_boundary_matrix (deleted=49, total=1000)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_deletion_boundary_matrix (deleted=50, total=1000)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_deletion_boundary_matrix (deleted=20, total=100)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_deletion_boundary_matrix (deleted=21, total=100)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_deletion_boundary_matrix` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='source', value='')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='source', value='/')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='source', value='relative')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='source', value='/tmp/../Music')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='source', value=None)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='device_id', value='')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='device_id', value='-flag')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='device_id', value='a/b')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='device_id', value='a b')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='remote_dir', value='/storage/emulated/0')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='remote_dir', value='/storage/emulated/0/')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='remote_dir', value='/storage/emulated/0/../Music')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='remote_dir', value='/storage/emulated/0/./Music')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='remote_dir', value='/storage/emulated/0//Music')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='remote_dir', value='//storage/emulated/0/Music')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='remote_dir', value='/storage/emulated/0/Music/')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='remote_dir', value='/storage/emulated/0/Music\x00')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='threads', value=0)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='threads', value=33)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='threads', value=True)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='threads', value='4')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='mirror', value='true')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='mirror', value=1)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='replaygain', value=None)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='replaygain', value=1)` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='exclusions', value=[])` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='exclusions', value=['*.mp3'])` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal (key='exclusions', value=['/.thumbnails/', '/a/b/'])` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_invalid_settings_matrix_and_remote_traversal` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_itemized_directory_delete_metadata_only_update_and_file_size (code='cd+++++++++')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_itemized_directory_delete_metadata_only_update_and_file_size (code='*deleting  ')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_itemized_directory_delete_metadata_only_update_and_file_size (code='.f..t......')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_itemized_directory_delete_metadata_only_update_and_file_size` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_log_location_rotation_and_ansi_cleanup` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_missing_tools_and_missing_replaygain_preset (tool='kdeconnect-cli')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_missing_tools_and_missing_replaygain_preset (tool='sshfs')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_missing_tools_and_missing_replaygain_preset (tool='rsync')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_missing_tools_and_missing_replaygain_preset (tool='rsgain')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_missing_tools_and_missing_replaygain_preset (tool='findmnt')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_missing_tools_and_missing_replaygain_preset (tool='mountpoint')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_missing_tools_and_missing_replaygain_preset (tool='fusermount3')` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_missing_tools_and_missing_replaygain_preset` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_progress_units_and_unrecognized_lines` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_replaygain_summary_recognized_or_explicitly_unknown` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_roundtrip_all_settings_and_config_file_permissions` | PASS |
| `test_release_core.ParsingSettingsReleaseTests.test_unicode_line_separator_is_a_filename_not_a_record_boundary` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_current_mount_requires_unique_identity_and_matching_id (text='')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_current_mount_requires_unique_identity_and_matching_id (text='42 1 0:2 / /run/user/1000/device rw - fuse.sshfs kdeconnect@host:/ rw\n42 1 0:2 / /run/user/1000/device rw - fuse.sshfs kdeconnect@host:/ rw\n')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_current_mount_requires_unique_identity_and_matching_id (text='42 1 0:2 / /run/user/1000/device rw - ext4 kdeconnect@host:/ rw\n')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_current_mount_requires_unique_identity_and_matching_id (text='42 1 0:2 / /run/user/1000/device rw - fuse.sshfs other@host:/ rw\n')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_current_mount_requires_unique_identity_and_matching_id` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_fifo_and_unix_socket_rejected_without_blocking` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_findmnt_malformed_empty_duplicate_wrong_target_fails_closed (text='bad json')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_findmnt_malformed_empty_duplicate_wrong_target_fails_closed (text='{}')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_findmnt_malformed_empty_duplicate_wrong_target_fails_closed (text='{"filesystems": []}')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_findmnt_malformed_empty_duplicate_wrong_target_fails_closed (text='{"filesystems": [{"target": "/run/user/1000/device", "fstype": "fuse.sshfs", "source": "kdeconnect@host:/", "id": 42}, {"target": "/run/user/1000/device", "fstype": "fuse.sshfs", "source": "kdeconnect@host:/", "id": 42}]}')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_findmnt_malformed_empty_duplicate_wrong_target_fails_closed (text='{"filesystems": [{"target": "/other", "fstype": "fuse.sshfs", "source": "kdeconnect@host:/", "id": 42}]}')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_findmnt_malformed_empty_duplicate_wrong_target_fails_closed (text='{"filesystems": [{"target": "/run/user/1000/device", "fstype": "fuse.sshfs", "source": "kdeconnect@host:/", "id": "bad"}]}')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_findmnt_malformed_empty_duplicate_wrong_target_fails_closed` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_remote_identity_and_nested_mount_rejected (ids=[124])` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_remote_identity_and_nested_mount_rejected (ids=[123, 124])` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_remote_identity_and_nested_mount_rejected` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_remote_missing_not_created_and_symlink_components_rejected` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_remote_readonly_and_delete_denied_probe_errors` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_source_zero_byte_file_is_a_file_but_directories_and_exclusions_are_not` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_symlink_roots_files_directories_and_dangling_links_rejected (target='file')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_symlink_roots_files_directories_and_dangling_links_rejected (target='directory')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_symlink_roots_files_directories_and_dangling_links_rejected (target='missing')` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_symlink_roots_files_directories_and_dangling_links_rejected` | PASS |
| `test_release_core.SourceDestinationReleaseTests.test_unreadable_subtree_aborts_instead_of_becoming_deletions` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate (label='Scan PC library')` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate (label='Discover KDE Connect devices')` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate (label='Check per-track ReplayGain')` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate (label='Get KDE Connect mountpoint')` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate (label='Scan phone Music')` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate (label='Verify phone write and delete capability')` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate (label='rsync preview')` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate (label='Final phone write/delete check')` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate (label='rsync mirror')` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cancellation_at_each_operation_gate` | PASS |
| `test_release_core.WorkflowReleaseTests.test_cleanup_failure_visible_separately_and_borrowed_failure_untouched` | PASS |
| `test_release_core.WorkflowReleaseTests.test_device_disconnect_at_each_connectivity_gate (gate=1)` | PASS |
| `test_release_core.WorkflowReleaseTests.test_device_disconnect_at_each_connectivity_gate (gate=2)` | PASS |
| `test_release_core.WorkflowReleaseTests.test_device_disconnect_at_each_connectivity_gate (gate=3)` | PASS |
| `test_release_core.WorkflowReleaseTests.test_device_disconnect_at_each_connectivity_gate` | PASS |
| `test_release_core.WorkflowReleaseTests.test_final_verification_detects_remaining_changes` | PASS |
| `test_release_core.WorkflowReleaseTests.test_malformed_preview_aborts_real_sync` | PASS |
| `test_release_core.WorkflowReleaseTests.test_missing_mountpoint_directory_can_be_created_only_by_kdeconnect` | PASS |
| `test_release_core.WorkflowReleaseTests.test_normal_unmount_failure_falls_back_once_to_lazy` | PASS |
| `test_release_core.WorkflowReleaseTests.test_partial_mount_on_failure_and_cancellation_is_cleaned (cancelled=False)` | PASS |
| `test_release_core.WorkflowReleaseTests.test_partial_mount_on_failure_and_cancellation_is_cleaned (cancelled=True)` | PASS |
| `test_release_core.WorkflowReleaseTests.test_partial_mount_on_failure_and_cancellation_is_cleaned` | PASS |
| `test_release_core.WorkflowReleaseTests.test_partial_unexpected_mount_never_detached` | PASS |
| `test_release_core.WorkflowReleaseTests.test_preview_does_not_require_preset_or_rsgain` | PASS |
| `test_release_core.WorkflowReleaseTests.test_replaygain_disabled_does_not_require_or_invoke_it` | PASS |
| `test_release_core.WorkflowReleaseTests.test_stale_detach_failure_no_remount_or_sync` | PASS |
| `test_release_core.WorkflowReleaseTests.test_stale_detach_that_did_not_detach_stops` | PASS |
| `test_release_core.WorkflowReleaseTests.test_stale_storage_timeout_uses_one_recovery` | PASS |
| `test_release_gui.GUIReleaseTests.test_close_during_cleanup_waits_for_unmount` | PASS |
| `test_release_gui.GUIReleaseTests.test_close_during_mount_cleans_partial_mount` | PASS |
| `test_release_gui.GUIReleaseTests.test_close_during_replaygain_cancels_process_and_never_mounts` | PASS |
| `test_release_gui.GUIReleaseTests.test_close_during_rsync_cancels_and_cleans_owned_mount` | PASS |
| `test_release_gui.GUIReleaseTests.test_close_while_approval_pending_stops_without_sync` | PASS |
| `test_release_gui.GUIReleaseTests.test_large_delete_dialog_defaults_to_cancel_and_lists_files` | PASS |
| `test_release_gui.GUIReleaseTests.test_large_preview_table_10000_rows_and_return_to_event_loop` | PASS |
| `test_release_gui.GUIReleaseTests.test_progress_and_log_widgets_update_while_subprocess_runs` | PASS |
| `test_release_gui.GUIReleaseTests.test_repeated_clicks_and_controller_starts_cannot_overlap` | PASS |
| `test_release_gui.GUIReleaseTests.test_settings_dialog_saves_all_controls_to_isolated_xdg` | PASS |
| `test_release_gui.GUIReleaseTests.test_startup_is_idle_and_does_not_begin_sync` | PASS |
| `test_release_history_status.HistoryReleaseTests.test_history_write_failure_is_visible_and_does_not_erase_prior_success` | PASS |
| `test_release_history_status.HistoryReleaseTests.test_preview_failure_and_cancel_preserve_existing_success_bytes (mode='preview')` | PASS |
| `test_release_history_status.HistoryReleaseTests.test_preview_failure_and_cancel_preserve_existing_success_bytes (mode='failure')` | PASS |
| `test_release_history_status.HistoryReleaseTests.test_preview_failure_and_cancel_preserve_existing_success_bytes (mode='cancel')` | PASS |
| `test_release_history_status.HistoryReleaseTests.test_preview_failure_and_cancel_preserve_existing_success_bytes` | PASS |
| `test_release_history_status.HistoryReleaseTests.test_success_fields_counts_timezone_and_cleanup_warning` | PASS |
| `test_release_history_status.TimeoutStatusReleaseTests.test_cancelled_startup_stops_without_followup_commands` | PASS |
| `test_release_history_status.TimeoutStatusReleaseTests.test_cleanup_presence_timeout_does_not_claim_unmounted` | PASS |
| `test_release_history_status.TimeoutStatusReleaseTests.test_mount_presence_timeout_never_authorizes_sync_even_exit_zero` | PASS |
| `test_release_history_status.TimeoutStatusReleaseTests.test_mount_status_permission_error_is_not_reported_as_unmounted` | PASS |
| `test_release_history_status.TimeoutStatusReleaseTests.test_startup_status_checks_do_not_mount_or_sync` | PASS |
| `test_release_io.ProcessLifecycleReleaseTests.test_cancel_does_not_leave_a_child_process_running` | PASS |
| `test_release_io.ProcessLifecycleReleaseTests.test_cancel_from_started_signal_does_not_launch_command` | PASS |
| `test_release_io.RealTemporaryRsyncReleaseTests.test_actual_rsync_cancel_before_delete_after_keeps_extra_file` | PASS |
| `test_release_io.RealTemporaryRsyncReleaseTests.test_failed_sender_io_does_not_delete_phone_only_file` | PASS |
| `test_release_io.RealTemporaryRsyncReleaseTests.test_large_library_worker_and_parser_10000_files` | PASS |
| `test_release_io.RealTemporaryRsyncReleaseTests.test_real_preview_is_byte_and_mtime_unchanged_with_unusual_names` | PASS |
| `test_release_io.RealTemporaryRsyncReleaseTests.test_root_thumbnails_protected_but_nested_thumbnails_follow_mirror` | PASS |
| `test_release_io.RealTemporaryRsyncReleaseTests.test_update_only_keeps_extra_files_and_updates_changed_files` | PASS |
| `test_release_packaging.PackagingReleaseTests.test_desktop_template_and_pyproject_metadata` | PASS |
| `test_release_packaging.PackagingReleaseTests.test_external_command_ast_has_no_shell_interpolation_or_gui_waits` | PASS |
| `test_release_packaging.PackagingReleaseTests.test_fresh_source_copy_setup_and_launch_from_unrelated_cwd` | PASS |
| `test_release_packaging.PackagingReleaseTests.test_installer_is_relocatable_and_does_not_modify_real_home` | PASS |
| `test_release_packaging.PackagingReleaseTests.test_installer_refuses_unrelated_existing_files_before_any_write` | PASS |
| `test_replaygain_integration.ReplayGainIntegrationTests.test_new_track_tagged_then_skipped_byte_for_byte` | PASS |
| `test_workflow.WorkflowTests.test_broken_replacement_stops` | PASS |
| `test_workflow.WorkflowTests.test_cancel_cleans_owned_mount` | PASS |
| `test_workflow.WorkflowTests.test_cancel_replaygain_never_mounts` | PASS |
| `test_workflow.WorkflowTests.test_changed_cleanup_mount_left_untouched` | PASS |
| `test_workflow.WorkflowTests.test_delete_approval_and_cap` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='Scan PC library')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='Discover KDE Connect devices')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='Check per-track ReplayGain')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='Get KDE Connect mountpoint')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='Mount KDE Connect filesystem')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='Verify SSHFS identity')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='Scan phone Music')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='Verify phone write and delete capability')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='rsync preview')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync (label='Final phone write/delete check')` | PASS |
| `test_workflow.WorkflowTests.test_failures_block_sync` | PASS |
| `test_workflow.WorkflowTests.test_healthy_borrowed_mount_left_alone` | PASS |
| `test_workflow.WorkflowTests.test_preview_no_tagging_probe_or_real_rsync` | PASS |
| `test_workflow.WorkflowTests.test_real_order` | PASS |
| `test_workflow.WorkflowTests.test_rsync_error_does_not_verify_success` | PASS |
| `test_workflow.WorkflowTests.test_stale_recovered_once` | PASS |
| `test_workflow.WorkflowTests.test_unexpected_filesystem_never_unmounted` | PASS |

Subtest timing values in the JSON are elapsed time within the parent method, not independent subtest runtimes.

[Exact audited source manifest](release-source.sha256) records the application, tests, scripts, resources and README at the historical audit baseline; it does not match the later publication edits. This is a source snapshot identifier, not a Git commit or clean-checkout substitute.

## qt6ct packaging follow-up

The subsequent qt6ct AppImage integration passed all **127** current release
tests and actual artifact/theme tests. See [the qt6ct report](qt6ct-appimage-report.md)
and refreshed `release-test-results.json`. The historical audit tables above are
retained; no destructive physical-phone test was added by the theme follow-up.
