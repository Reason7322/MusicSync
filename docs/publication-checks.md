# Publication preparation — 2026-09-07

The source tree is prepared for the owner's GitHub publication step. This is not
a physical-device release sign-off. No Git initialization, staging, commits,
history rewriting or pushing was performed. A repository already existed at the
start of this task, with no commits or tracked files; the project remains untracked.

## Public identity and first run

The public application ID is **`io.github.reason7322.MusicSync`**. It represents
the intended **Reason7322** GitHub namespace. The author/domain portion is
lowercased according to the [Desktop Entry naming convention](https://specifications.freedesktop.org/desktop-entry/latest/file-naming.html);
the proposed mixed-case author segment is syntactically valid, but the lowercase
form follows that convention. The runtime constant, desktop filename, icon name,
installer, README and tests agree. The installer imports the runtime constant.
The package/import/command name remains `musicsync`, with author Reason7322 and
MIT license metadata. No unverified repository URL was invented.

The private prototype identity remains only in explicitly historical documentation
and its original source-hash manifest. No release has yet fixed that identity.
Settings/log/history directories retain `musicsync`, preserving existing user data.
Close any running prototype before launching the revised app: its instance-lock
filename changes with the ID. Installed prototype desktop/icon files were not
modified by this task. README documents removal of those obsolete entries before
installing the new identity; the installer leaves old-ID files untouched.

There is no default device ID or name, and no automatically selected device.
First run discovers available KDE Connect devices, offers explicit selection in
Settings and disables Preview/Sync until the library and device are configured.
Missing source configuration does not prevent device discovery. Saving and running
operations still require complete validated settings; configuration errors cannot
advance into source scanning, ReplayGain, mounting or rsync.

The initial source comes from [Qt `QStandardPaths.MusicLocation`](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QStandardPaths.html),
using Qt's XDG-aware lookup. No application-authored HOME/Music fallback remains.
Empty, relative, root, home-directory, traversal or control-character suggestions
are discarded, requiring user selection. Nonexistent suggested directories are
not created; normal asynchronous source validation explains the problem. Existing
saved source/device settings are retained. Tests verify an actual Qt lookup using
a temporary `user-dirs.dirs` and a localized music-directory name.

## Results

| Check | Result | Evidence and method |
| --- | --- | --- |
| Complete release suite | PASS | **112 test methods, 116 additional subtest records, 228 PASS records; 0 failures/errors/skips**, 16.755 seconds, completed 2026-09-07 18:17:50 CEST. [Every test and result](release-test-results.json). |
| Existing safety coverage | PASS | All 100 pre-publication methods rerun: source/destination/SSHFS guards, stale recovery, ownership, previews/deletions/exclusions, ReplayGain, cancellation/shutdown, history, parsing, process safety, settings and large-library fixtures. |
| New first-run coverage | PASS | Nine first-run methods plus three new packaging methods: discovery/selection/persistence, operational rejection before commands, unset-source handling, saved-source retention, malformed/unsafe defaults, fresh unconfigured launch, ID consistency and real isolated Qt/XDG lookup. |
| Fresh setup and launch | PASS at source-snapshot level | New system-site-packages venvs in relocated source copies, unrelated cwd, fake HOME/XDG/KDE CLI, both configured and unconfigured launch. Paths include Unicode, spaces and shell metacharacters. No real phone access. |
| Desktop integration | PASS in isolated homes | Desktop template validation, installed desktop validation, install/uninstall, unrelated-file protection and exact launcher argv forwarding. Public ID and icon filenames checked. |
| Python / shell / desktop static checks | PASS | `compileall`, `sh -n`, `desktop-file-validate`; suite AST audit verifies command invocation safety and absence of blocking GUI waits. [Static evidence](publication-static-results.json). |
| Lint/type checks | NOT TESTED | No linter or type checker is configured. Syntax/AST checks are not claimed as a type-check run. |
| Ignore policy | PASS | 16 representative venv, build, bytecode/cache, secret-environment, runtime-config/log/history and live-evidence paths checked with read-only `git check-ignore`. |
| Publication privacy scan | PASS within stated scope | Nonignored tracked/untracked candidates scanned; no remaining original personal home paths, original device ID/name, credential-bearing URLs, private-key material, common provider token patterns or literal secret assignments found. Manual keyword review found only ordinary code/docs and fictional fixtures. |
| Clean Git revision / actual fresh checkout | PARTIAL | Repository exists but has no commits or tracked files. No history exists to scan; a clean committed checkout cannot yet be tested. Git work is deliberately left to the owner. `git diff --check` returns 0 but is vacuous for untracked files. |
| New wheel build / dependency downloads | NOT TESTED | Existing supported source-launch setup was tested; no package installation or network dependency changes were made. PEP 517 metadata, license, entry point and packaged icon declaration were checked. |
| Physical-device acceptance | NOT TESTED in this pass | No live mount, remount, real-library tagging, write/delete probe or real sync was performed. Earlier healthy-device evidence is historical, not a new run of this revision. |

Commands from the source directory:

```fish
.venv/bin/python scripts/run_release_tests.py
.venv/bin/python -m compileall -q src tests scripts
desktop-file-validate resources/io.github.reason7322.MusicSync.desktop
sh -n scripts/musicsync
git diff --check
```

An initial 107-method run hit the sandbox's Unix-socket bind restriction (`EPERM`).
The complete suite then passed outside that restriction. After the identity/XDG
changes, the final 112-method suite also passed outside the sandbox. All actual
rsync deletions and rsgain metadata changes were restricted to temporary fixtures.
A newly written test initially accessed the patch wrapper instead of its returned
mock; that test-only error was corrected before the final run. No new sync-engine
bug or safety regression was discovered during publication preparation.

## Privacy and historical evidence

The scan used Git's nonignored candidate list, including all currently untracked
publication files; it excluded `.git`, `.venv`, generated caches and other ignored
runtime data. No remaining binary artifacts needed inspection after removal of
the private screenshot; the SVG is plain text. Pattern scans and manual review
are bounded checks, not a guarantee of finding every conceivable secret. Do not
force-add ignored logs, local settings or live-device reports: those can contain
device IDs, paths and music filenames.

The earlier report is preserved at [release-readiness-report.md](release-readiness-report.md)
with an explicit historical banner. Its 100-method results are retained separately
as [release-test-results-initial.json](release-test-results-initial.json), so the
new run does not silently overwrite its evidence. The historical static result
and `release-source.sha256` are unchanged; that manifest identifies the earlier
source snapshot, not the publication edits. The old screenshot was omitted because
it exposed personal paths and phone information; textual Wayland verification,
library counts, environment versions, test boundaries and the fallback-script
checksum remain. Personal names/identifiers in prose and fixtures were generalized.

## Remaining manual work

* Review/stage/commit/push the intended publication files yourself, then test a real
  fresh checkout. No Git mutations were made by this task.
* Close any running private prototype and reinstall the desktop entry for the new
  ID; check native Wayland launcher/window grouping and icon display manually.
* Complete the physical-device acceptance cases in the historical readiness report,
  especially app-owned mount/cleanup, natural stale recovery and interrupted real
  transfers. None is claimed as physically verified by the offline mocks.
* Validate wheel creation/install in a clean environment if distributing a wheel.

No known failing automated check blocks source publication. Full release sign-off
still needs the versioned baseline and the outstanding manual acceptance above.

## Every file changed in publication preparation

Paths are relative to the repository root. Renames list the final name; the old
desktop/icon basenames used the private prototype ID. Generated ignored bytecode
is excluded from this source-change inventory.

| File | Change |
| --- | --- |
| `.gitignore` | Ignore Python/build/test caches, environments, logs, local settings/history and private live evidence. |
| `LICENSE` | Add MIT license, copyright 2026 Reason7322. |
| `pyproject.toml` | Add README, MIT license/file and Reason7322 author metadata. |
| `README.md` | Portable setup/first-run guidance, Qt/XDG defaults, public ID/migration notes, privacy and license; remove personal paths/defaults and screenshot link. |
| `src/musicsync/__init__.py` | Set the public application ID. |
| `src/musicsync/settings.py` | Qt/XDG source suggestion, explicit unconfigured device/source support at load, strict operational/save validation. |
| `src/musicsync/backend/status.py` | Discover without a selected device; skip an unset source scan and explain setup. |
| `src/musicsync/main_window.py` | Setup guidance and button availability, including explicit library selection. |
| `src/musicsync/settings_dialog.py` | Empty selection prompt, discovered-device selection and pairing/refresh instructions. |
| `resources/io.github.reason7322.MusicSync.desktop` | Rename desktop file and update its icon ID. |
| `src/musicsync/icons/io.github.reason7322.MusicSync.svg` | Rename the existing SVG; artwork unchanged. |
| `scripts/install_desktop.py` | Import the canonical public ID for installed desktop/icon names. |
| `scripts/gui_check.py` | Load saved settings; reject unconfigured preview before starting the harness. |
| `scripts/release_live_readonly.py` | Generalize device wording and require configured settings before commands. |
| `tests/fixtures.py` | Add explicit fictional configured-app settings independent of production defaults. |
| `tests/test_first_run.py` | Add nine first-run/setup/Qt-source validation methods. |
| `tests/test_controller.py` | Use fictional configured fixture. |
| `tests/test_guards.py` | Use fictional configured fixture for guarded worker tests. |
| `tests/test_logic.py` | Use explicit fixture; replace personal device-name parsing examples. |
| `tests/test_workflow.py` | Use explicit fixture and fictional discovery response. |
| `tests/test_release_core.py` | Keep invalid-setting matrices based on a complete fictional configuration. |
| `tests/test_release_gui.py` | Use explicit configured fixture for existing operational GUI tests. |
| `tests/test_release_history_status.py` | Use fixture and generic device-name responses. |
| `tests/test_release_packaging.py` | Check public ID/license/author, portable home assertion, configured name, fresh first run and actual isolated Qt/XDG lookup. |
| `docs/script-reference.md` | Generalize the original script's home path; retain behavior and checksum. |
| `docs/verification.md` | Redact device/host specifics and explain omitted screenshot; preserve historical physical verification. |
| `docs/release-readiness-report.md` | Mark historical baseline, redact personal information and link preserved original results/current publication checks. |
| `docs/wayland-preview.png` | Remove the screenshot exposing personal paths and phone information. |
| `docs/release-test-results-initial.json` | Preserve the original 100-method evidence unchanged. |
| `docs/release-test-results.json` | Record the final 112-method publication suite and subtests. |
| `docs/publication-static-results.json` | Record current static/privacy/ignore/Git-state checks and their scope. |
| `docs/publication-checks.md` | This report and complete source-change inventory. |
