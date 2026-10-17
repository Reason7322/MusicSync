"""Library cleanup engine: read-only previews, journaled applies, safe undo.

Pipeline (documented in docs/USAGE.md):

    scan_root(root)                       # safe inventory, no symlink traversal
    build_preview(root, ...)              # pure/read-only proposals + collisions
    apply_changes(root, preview, approved)# explicit per-item approval only
    undo_session(root, session_id)        # byte-exact restore from journal

Safety invariants enforced at APPLY time (revalidated against live state):
- never overwrites: targets must be free of case/normalization-insensitive
  collisions against the *live* directory listing;
- sources changed since preview are rejected per item, never guessed about;
- symlinks, special files and path escapes are refused;
- every rename is an atomic same-directory ``os.rename``; chains/cycles are
  reordered with temporary names instead of overwriting;
- a durable JSON-lines journal (fsync after each event) records every step
  before it happens; undo replays the journal backwards, restoring original
  filenames and - where metadata was edited - original file bytes from the
  per-session backup store. Previews never write anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from .cleaning import MAX_NAME_BYTES, Reason, clean_text, name_key
from .naming import NameProposal, Override, make_ost_name, propose_name  # noqa: F401 (re-exported)
from .scanner import ScanResult, scan_root
from .tags import ParseError, TagSnapshot, apply_tag_edits, read_tag_snapshot

__all__ = [
    "JOURNAL_DIRNAME",
    "EngineError",
    "ItemPlan",
    "CollisionReport",
    "Preview",
    "ApplyReport",
    "UndoReport",
    "build_preview",
    "apply_changes",
    "undo_session",
    "list_sessions",
]

JOURNAL_DIRNAME = ".musicsyncrename"


class EngineError(Exception):
    """Structural safety failure (planning, journaling) - nothing half-applied."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemPlan:
    rel_path: str  # relative to root, "/" separated
    current_name: str
    size: int
    mtime_ns: int
    status: str  # ok | no_change | ambiguous | error
    proposed_name: Optional[str] = None  # full filename incl. extension
    reasons: tuple[Reason, ...] = field(default=())
    flags: tuple[Reason, ...] = field(default=())
    tag_edits: tuple[tuple[str, str, str], ...] = field(default=())  # (frame, old, new)

    @property
    def rel_dir(self) -> str:
        return self.rel_path.rpartition("/")[0]


@dataclass(frozen=True)
class CollisionReport:
    directory: str  # "" == root; relative dir
    normalized_key: str  # NFC/NFKC+casefold key the targets collide on
    kind: str  # "proposed_vs_proposed" | "proposed_vs_live_file"
    involved: tuple[str, ...]  # rel paths of proposing items (+ "live:<name>")


@dataclass(frozen=True)
class Preview:
    root: str  # absolute path string
    items: tuple[ItemPlan, ...]
    collisions: tuple[CollisionReport, ...]
    symlinks_skipped: tuple[str, ...]
    other_file_count: int

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def counts_by_status(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.items:
            out[item.status] = out.get(item.status, 0) + 1
        return out


@dataclass(frozen=True)
class ApplyReport:
    session_id: str  # "" when nothing passed validation (no journal was created)
    applied: tuple[tuple[str, Optional[str]], ...]  # (rel_path, new_name|None=tags-only)
    rejected: tuple[tuple[str, str], ...]  # (rel_path, reason_code); pre-mutation rejections
    partial: tuple[tuple[str, str], ...] = ()  # (rel_path, abort_code): started, not completed
    canceled: tuple[str, ...] = ()  # approved but never started after stop; untouched on disk

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.partial and not self.canceled


@dataclass(frozen=True)
class UndoReport:
    session_id: str
    restored: tuple[str, ...]  # rel_paths returned to original name/bytes
    anomalies: tuple[tuple[str, str], ...] = ()  # (rel_path, problem_code)

    @property
    def ok(self) -> bool:
        return not self.anomalies


# ---------------------------------------------------------------------------
# Preview (read-only by construction)
# ---------------------------------------------------------------------------


def _tag_edits_for(tags: TagSnapshot) -> tuple[tuple[str, str, str], ...]:
    """Metadata cleanup limited to the filename-driving frames.

    Only TIT2/TPE1 are considered, only when they hold a single distinct value
    (conflicting values are review territory), and only where recognized junk or
    broken normalization is actually present in the stored text.
    """
    edits: list[tuple[str, str, str]] = []
    for frame, raw in (("TIT2", tags.title), ("TPE1", tags.artist)):
        if not raw:
            continue
        cleaned = clean_text(raw)
        if cleaned.value != raw and cleaned.value.strip():
            edits.append((frame, raw, cleaned.value))
    return tuple(edits)


def _detect_collisions(
    items_by_dir: dict[str, list[ItemPlan]], live_names_by_dir: dict[str, tuple[str, ...]]
) -> tuple[tuple[CollisionReport, ...], dict[str, list[Reason]]]:
    reports: list[CollisionReport] = []
    item_flags: dict[str, list[Reason]] = {}

    def flag(item: ItemPlan, code: str, detail: str) -> None:
        item_flags.setdefault(item.rel_path, []).append(Reason(code, detail))

    for rel_dir in sorted(items_by_dir):
        group = items_by_dir[rel_dir]
        live_keys: dict[str, str] = {}
        for name in live_names_by_dir.get(rel_dir, ()):
            live_keys.setdefault(name_key(name), name)
        proposed_by_key: dict[str, list[ItemPlan]] = {}
        for item in group:
            if not item.proposed_name or item.status != "ok":
                continue
            if name_key(item.proposed_name) == name_key(item.current_name):
                continue  # target is its own (current) slot
            proposed_by_key.setdefault(name_key(item.proposed_name), []).append(item)

        for key in sorted(proposed_by_key):
            owners = proposed_by_key[key]
            occupant = live_keys.get(key)
            if len(owners) > 1:
                reports.append(CollisionReport(rel_dir, key, "proposed_vs_proposed", tuple(i.rel_path for i in owners)))
                for item in owners:
                    flag(item, "preview_collision", f"{len(owners)} items propose the same normalized name")
            elif occupant is not None:
                # Honest conservative report: approval is unknown at preview time.
                reports.append(
                    CollisionReport(rel_dir, key, "proposed_vs_live_file", (owners[0].rel_path, f"live:{occupant}"))
                )
                flag(owners[0], "preview_collision", f"target exists on disk: {occupant}")

    return tuple(reports), item_flags


_PROPOSAL_EXT_RE = re.compile(r"\.(mp3|flac|ogg|m4a)$", re.I)


def _usable_stem(name: str) -> str:
    """Filename minus its audio extension, stripped. Empty for bare extensions."""
    return _PROPOSAL_EXT_RE.sub("", name or "").strip()


def _guard_empty_stem(proposal: NameProposal) -> NameProposal:
    """Reject proposals whose entire identity is extension/junk.

    The naming layer can legitimately emit e.g. ``".mp3"`` when a filename's
    stem is ALL recognized junk (e.g. ``(Official HD Video).mp3``); renaming
    onto a hidden file is not a deterministic outcome, so the preview
    downgrades such proposals to ambiguous review with an explicit flag.
    """
    if proposal.status != "ok" or not proposal.proposed_name:
        return proposal
    stem = _usable_stem(proposal.proposed_name)
    if not stem or set(stem) <= {"."}:
        return NameProposal(
            "ambiguous",
            None,
            proposal.reasons,
            tuple(proposal.flags) + (
                Reason("empty_stem", f"{proposal.proposed_name!r} has no usable stem"),
            ),
        )
    return proposal


def build_preview(
    root: os.PathLike | str,
    overrides: Optional[Sequence[Override]] = None,
    ost_hints: Optional[dict[str, str]] = None,
) -> Preview:
    """Scan ``root`` and compute read-only proposals.

    - ``overrides``: caller review decisions (rel_path -> final name). They are
      validated like any proposal downstream; they never bypass collision or
      apply-time checks.
    - ``ost_hints``: rel_path -> game name, for the explicit
      ``Game OST - Track.mp3`` convention when tags provide a reliable track.

    Performs no writes of any kind.
    """
    # Prune the engine's own journal directory so backups and session files are
    # never presented as rename candidates.
    scan: ScanResult = scan_root(root, prune_dirnames=(JOURNAL_DIRNAME,))
    override_by_rel = {o.rel_path: o for o in (overrides or ())}
    ost_hints = dict(ost_hints or {})

    raw_items: list[ItemPlan] = []
    items_by_dir: dict[str, list[ItemPlan]] = {}
    for scanned in scan.files:
        try:
            tags = read_tag_snapshot(Path(scan.root) / scanned.rel_path)
        except ParseError as exc:
            item = ItemPlan(
                rel_path=scanned.rel_path,
                current_name=scanned.name,
                size=scanned.size,
                mtime_ns=scanned.mtime_ns,
                status="error",
                reasons=(Reason("parse_error", str(exc)),),
            )
        else:
            try:
                proposal = propose_name(scanned, tags, override_by_rel.get(scanned.rel_path))
            except ValueError as exc:  # e.g. caller supplied an empty override name
                item = ItemPlan(
                    rel_path=scanned.rel_path,
                    current_name=scanned.name,
                    size=scanned.size,
                    mtime_ns=scanned.mtime_ns,
                    status="error",
                    reasons=(Reason("invalid_override", str(exc)),),
                )
            else:
                # Explicit OST convention hints (caller identity decisions).
                hint_game = ost_hints.get(scanned.rel_path)
                if hint_game is not None and tags.has_tags and tags.title:
                    try:
                        hinted = make_ost_name(hint_game, tags.title)
                    except ValueError:
                        pass
                    else:
                        proposal = _apply_hint(proposal, hinted, scanned.name)

                # A stem made entirely of recognized junk cleans to a bare
                # extension (".mp3"); renaming onto that hidden file is not a
                # deterministic outcome and must go to review instead.
                proposal = _guard_empty_stem(proposal)

                tag_edits = _tag_edits_for(tags) if tags.has_tags else ()
                safety_flags = _name_safety_flags(proposal.proposed_name)
                item = ItemPlan(
                    rel_path=scanned.rel_path,
                    current_name=scanned.name,
                    size=scanned.size,
                    mtime_ns=scanned.mtime_ns,
                    status=proposal.status,
                    proposed_name=proposal.proposed_name,
                    reasons=proposal.reasons,
                    flags=tuple(proposal.flags) + tuple(safety_flags),
                    tag_edits=tag_edits,
                )

        raw_items.append(item)
        items_by_dir.setdefault(item.rel_dir, []).append(item)

    collisions, collision_flags = _detect_collisions(items_by_dir, scan.dir_entries)
    final_items: list[ItemPlan] = []
    for item in raw_items:
        extra = collision_flags.get(item.rel_path, ())
        if extra and not any(r.code == "preview_collision" for r in item.flags):
            item = ItemPlan(
                item.rel_path,
                item.current_name,
                item.size,
                item.mtime_ns,
                item.status,
                item.proposed_name,
                item.reasons,
                tuple(item.flags) + tuple(extra),
                item.tag_edits,
            )
        final_items.append(item)

    return Preview(
        root=scan.root,
        items=tuple(final_items),
        collisions=collisions,
        symlinks_skipped=scan.symlinks_skipped,
        other_file_count=scan.other_file_count,
    )


def _apply_hint(proposal, hinted_name: str, current_name: str):
    from .naming import NameProposal  # local to avoid cycle at module top

    status = "no_change" if hinted_name == current_name else "ok"
    flags = tuple(f for f in proposal.flags if f.code != "ost_candidate") + (Reason("reviewed_by_caller"),)
    return NameProposal(
        status,
        hinted_name,
        (Reason("from_ost_hint", "caller-provided game name"),),
        flags + _name_safety_flags(hinted_name),
    )


def _name_safety_flags(name: Optional[str]) -> tuple[Reason, ...]:
    if not name:
        return ()
    flags = []
    encoded_len = len(name.encode("utf-8"))
    if encoded_len > MAX_NAME_BYTES:
        flags.append(Reason("name_too_long", f"{encoded_len} bytes > 255"))
    unsafe = [c for c in name if c == "\x00" or c == "/" or c == "\\" or ord(c) < 32]
    if unsafe:
        flags.append(Reason("name_contains_unsafe_chars", repr(sorted(set(unsafe)))))
    return tuple(flags)


# ---------------------------------------------------------------------------
# Journal primitives (durable JSON-lines event log)
# ---------------------------------------------------------------------------


def journal_root(root: os.PathLike | str) -> Path:
    return Path(os.path.abspath(os.fspath(root))) / JOURNAL_DIRNAME


def _session_path(root: os.PathLike | str, session_id: str) -> Path:
    if re.fullmatch(r"[A-Za-z0-9]{1,80}", session_id or "") is None:
        raise EngineError(f"invalid session id: {session_id!r}")
    return journal_root(root) / "sessions" / f"{session_id}.jsonl"


def _append_event(path: Path, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_session(session_file: Path) -> list[dict]:
    events = []
    with open(session_file, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    raise EngineError(f"corrupt journal at {session_file}")
    return events


def _backup_path(root: os.PathLike | str, session_id: str, rel_path: str) -> Path:
    digest = hashlib.sha1(rel_path.encode("utf-8")).hexdigest()
    suffix = ".mp3" if rel_path.lower().endswith(".mp3") else ""
    return journal_root(root) / "backups" / session_id / (digest + suffix)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Rename planning (shared by apply and undo; cycle-safe, never overwrites)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Step:
    content: str  # stable identity of the file (rel path string)
    from_rel: str
    to_rel: str
    kind: str  # "rename" | "temp"


def plan_moves(ops: Iterable[tuple[str, tuple[str, str]]]) -> list[_Step]:
    """Plan same-directory renames for one parent directory.

    ``ops`` maps identity (rel path string) to ``(from_rel, to_rel)``; all rel
    paths share ONE parent directory and are relative to the library root.
    Returns atomic os.rename steps in a safe execution order: chains run
    dependency-first; cycles are broken with unique temporary names so that no
    step ever overwrites an existing file. Raises EngineError when two contents
    target the same case/normalization-insensitive name.
    """
    by_id: dict[str, tuple[str, str]] = {}
    for ident, (from_rel, to_rel) in ops:
        if Path(from_rel).name and name_key(from_rel) != name_key(to_rel):
            by_id[ident] = (from_rel, to_rel)

    seen_targets: dict[str, str] = {}
    for ident in sorted(by_id):
        key = name_key(Path(by_id[ident][1]).name)
        if key in seen_targets:
            raise EngineError(
                f"two contents target the same normalized name ({key!r}): {seen_targets[key]} and {ident}"
            )
        seen_targets[key] = ident

    cur: dict[str, str] = {ident: by_id[ident][0] for ident in by_id}
    remaining = set(by_id)
    steps: list[_Step] = []
    guard = 0
    limit = len(remaining) * (len(remaining) + 3) + 8
    while remaining:
        guard += 1
        if guard > limit:
            raise EngineError("rename planning did not converge")
        holders_other = lambda ident: {name_key(Path(cur[o]).name) for o in remaining if o != ident}  # noqa: E731
        ready = [ident for ident in sorted(remaining) if name_key(Path(by_id[ident][1]).name) not in holders_other(ident)]
        if not ready:
            first = min(remaining)
            tmp_name = f".tmp-musicsync-rename-{uuid.uuid4().hex}"
            parent = Path(cur[first]).parent
            steps.append(_Step(first, cur[first], _join(parent, tmp_name), "temp"))
            cur[first] = _join(parent, tmp_name)  # full rel path; keeps dir parent
            continue
        for ident in ready:
            to_rel = by_id[ident][1]
            steps.append(_Step(ident, cur[ident], to_rel, "rename"))
        remaining -= set(ready)

    return steps


def _join(parent: str, name: str) -> str:
    return f"{parent}/{name}" if parent else name


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def _apply_unsafe_code(proposed: str) -> Optional[str]:
    """Apply-time name safety gate; returns a stable rejection code or None.

    Preview already flags these names (``name_contains_unsafe_chars``); apply is
    where the decision becomes a hard per-item rejection, because the preview
    may be stale and caller-provided overrides/hints are untrusted input.
    """
    if not proposed or proposed in (".", ".."):
        return "unsafe_name_chars"
    for ch in proposed:
        codepoint = ord(ch)
        if ch == "\x00" or ch == "/" or ch == "\\" or codepoint < 0x20:
            return "unsafe_name_chars"
    return None


def _is_renamed(item: ItemPlan) -> bool:
    """True when the plan moves this item (case/normalization-insensitive)."""
    return bool(
        item.proposed_name
        and name_key(item.proposed_name) != name_key(item.current_name)
    )


def _rel_parent(rel: str) -> str:
    """Directory part of a rel path ('' for root); tolerates './' prefixes."""
    parent = Path(rel).parent  # pathlib normalizes a leading './' component
    return "" if str(parent) == "." else str(parent)


def _validate_item(root_abs: Path, item: ItemPlan) -> Optional[str]:
    """Re-check one approved item against live state; stable code or None."""
    rel = item.rel_path
    parent_rel = rel.rpartition("/")[0]
    parent = root_abs / parent_rel if parent_rel else root_abs
    try:
        st_parent = os.lstat(parent)
    except OSError:
        return "parent_missing"
    if stat.S_ISLNK(st_parent.st_mode) or not stat.S_ISDIR(st_parent.st_mode):
        return "parent_not_plain_dir"

    file_path = parent / item.current_name
    try:
        st = os.lstat(file_path)
    except OSError:
        return "source_missing"
    if stat.S_ISLNK(st.st_mode):
        return "is_symlink"
    if not stat.S_ISREG(st.st_mode):
        return "not_regular_file"
    if (st.st_size, st.st_mtime_ns) != (item.size, item.mtime_ns):
        return "changed_since_preview"

    if _is_renamed(item):
        code = _apply_unsafe_code(item.proposed_name)  # type: ignore[arg-type]
        if code is not None:
            return code
        if len(item.proposed_name.encode("utf-8")) > MAX_NAME_BYTES:
            return "name_too_long"
    return None


def _target_freed_by_batch(target_key: str, group: Sequence[ItemPlan], item: ItemPlan) -> bool:
    """True only when the live occupant of ``target_key`` is ANOTHER approved
    item in this batch that is itself being renamed away (frees the slot)."""
    for other in group:
        if (
            other is not item
            and _is_renamed(other)
            and name_key(other.current_name) == target_key
        ):
            return True
    return False


def apply_changes(
    root: os.PathLike | str,
    preview: Preview,
    approved: Iterable[str],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> ApplyReport:
    """Apply ONLY the explicitly approved items from ``preview``.

    Each approval is a rel_path present in the preview; anything else is
    rejected with one of the stable reason codes and nothing is mutated for it:
    not_in_preview, status_ambiguous_not_applicable /
    status_error_not_applicable, nothing_to_do, parent_missing,
    parent_not_plain_dir, source_missing, is_symlink, not_regular_file,
    changed_since_preview (size+mtime_ns vs preview snapshot),
    unsafe_name_chars, name_too_long (>255 UTF-8 bytes), proposal_collision,
    target_exists, planning_failed.

    All validation and per-directory planning finish BEFORE any mutation. A
    session journal (``<root>/.musicsyncrename/sessions/<id>.jsonl``, fsync
    after every event) is opened first; full-file backups of every
    tag-edited item are written before any tag is touched; then renames run in
    planner order with an ``op``/``done`` pair per step. Cancellation (via
    ``cancel_check`` between steps) or a failure stops the rest of the work:
    already-completed items stay applied, started-but-unfinished items are
    reported as partial, never-started ones as canceled - and every one of
    them is recoverable via ``undo_session(root, report.session_id)``.

    A new apply is refused while any existing session is not in a terminal
    state (closed/undone), so two sessions can never mutate the same library.
    """
    root_abs = Path(os.path.abspath(os.fspath(root)))
    if not root_abs.is_dir():
        raise EngineError(f"root is not a directory: {root}")

    # Concurrency guard: an unresolved (open/aborted/corrupt) session means the
    # library may be mid-mutation; undo it before starting new work.
    for sess in list_sessions(root_abs):
        state = sess.get("state")
        if sess.get("corrupt") or state in ("open", "aborted"):
            raise EngineError(
                f"cannot start a new apply while session {sess['session_id']!r} is still "
                f"unresolved (state: {state or 'unresolvable'}); undo it first"
            )

    items_by_rel = {item.rel_path: item for item in preview.items}
    approved_list = list(dict.fromkeys(approved))  # de-duplicate, keep order

    rejected: list[tuple[str, str]] = []
    candidates: dict[str, ItemPlan] = {}
    for rel in approved_list:
        item = items_by_rel.get(rel)
        if item is None:
            rejected.append((rel, "not_in_preview"))
            continue
        if item.status in ("ambiguous", "error"):
            rejected.append((rel, f"status_{item.status}_not_applicable"))
            continue
        if not _is_renamed(item) and not item.tag_edits:
            rejected.append((rel, "nothing_to_do"))
            continue
        candidates[rel] = item

    # --- per-item live validation (no cross-item knowledge yet) ---------------
    validated: dict[str, ItemPlan] = {}
    for rel in sorted(candidates):
        code = _validate_item(root_abs, candidates[rel])
        if code is None:
            validated[rel] = candidates[rel]
        else:
            rejected.append((rel, code))

    # --- cross-item checks against LIVE directory listings --------------------
    grouped: dict[str, list[ItemPlan]] = {}
    for rel in sorted(validated):
        grouped.setdefault(validated[rel].rel_dir, []).append(validated[rel])

    final_items: dict[str, ItemPlan] = {}
    for rel_dir, group in sorted(grouped.items()):
        dir_path = root_abs / rel_dir if rel_dir else root_abs
        try:
            st_dir = os.lstat(dir_path)
        except OSError:
            for item in group:
                rejected.append((item.rel_path, "parent_missing"))
            continue
        if stat.S_ISLNK(st_dir.st_mode) or not stat.S_ISDIR(st_dir.st_mode):
            for item in group:
                rejected.append((item.rel_path, "parent_not_plain_dir"))
            continue
        try:
            live_keys = {name_key(n) for n in os.listdir(dir_path)}
        except OSError:  # dir vanished/perm race after the check above
            for item in group:
                rejected.append((item.rel_path, "planning_failed"))
            continue

        by_target_key: dict[str, list[ItemPlan]] = {}
        for item in group:
            if _is_renamed(item):
                by_target_key.setdefault(name_key(item.proposed_name), []).append(item)
        colliding = {
            item.rel_path
            for owners in by_target_key.values()
            if len(owners) > 1
            for item in owners
        }

        for item in group:
            rel_ = item.rel_path
            if rel_ in colliding:
                rejected.append((rel_, "proposal_collision"))
                continue
            target_key = name_key(item.proposed_name) if _is_renamed(item) else None
            if (
                target_key is not None
                and target_key in live_keys
                and not _target_freed_by_batch(target_key, group, item)
            ):
                rejected.append((rel_, "target_exists"))
                continue
            final_items[rel_] = item

    # --- per-directory planning through the verified planner (no journal yet) --
    planned_dirs: dict[str, list[_Step]] = {}
    for rel_dir in sorted(grouped):
        ops = [
            (rel_, (rel_, _join(rel_dir, final_items[rel_].proposed_name)))  # type: ignore[arg-type]
            for rel_ in sorted(final_items)
            if final_items[rel_].rel_dir == rel_dir and _is_renamed(final_items[rel_])
        ]
        try:
            planned_dirs[rel_dir] = plan_moves(ops)
        except EngineError:  # structural failure confined to this directory
            for rel_ in sorted(r for r, i in final_items.items() if i.rel_dir == rel_dir):
                rejected.append((rel_, "planning_failed"))

    ordered_steps: list[_Step] = []
    for rel_dir in sorted({i.rel_dir for i in final_items.values()} | set(planned_dirs)):
        # Move steps first (safe order from the planner), then this directory's
        # tag edits - each file's metadata is written only once its content has
        # reached its final slot.
        ordered_steps.extend(planned_dirs.get(rel_dir, ()))
        for rel_ in sorted(final_items):
            item = final_items[rel_]
            if item.rel_dir != rel_dir or not item.tag_edits:
                continue
            where = _join(rel_dir, item.proposed_name) if _is_renamed(item) else rel_  # type: ignore[arg-type]
            ordered_steps.append(_Step(rel_, where, where, "tag_edit"))

    if not final_items:
        return ApplyReport("", (), tuple(rejected))

    # --- session setup: journal header FIRST, backups BEFORE any mutation -----
    session_id = uuid.uuid4().hex
    sessions_dir = journal_root(root_abs) / "sessions"
    try:
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session_file = sessions_dir / f"{session_id}.jsonl"
        _append_event(
            session_file,
            {"type": "header", "id": session_id, "root": str(root_abs), "started": _utc_now_iso()},
        )
    except OSError as exc:
        raise EngineError(f"cannot write journal header: {exc}") from exc

    for rel in sorted(final_items):
        item = final_items[rel]
        if not item.tag_edits:
            continue
        backup_file = _backup_path(root_abs, session_id, rel)
        try:
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root_abs / rel, backup_file)
        except OSError as exc:
            raise EngineError(
                f"failed to back up {rel} before tag edits; journal for session "
                f"{session_id} is open (undo it or delete the file): {exc}"
            ) from exc
        with open(backup_file, "rb") as handle:  # fsync the backup itself
            os.fsync(handle.fileno())

    # --- execute ----------------------------------------------------------------
    steps_of: dict[str, list[_Step]] = {}
    for step in ordered_steps:
        steps_of.setdefault(step.content, []).append(step)
    op_journal: dict[str, int] = {c: 0 for c in steps_of}
    done_count: dict[str, int] = {c: 0 for c in steps_of}

    abort_reason: Optional[str] = None
    for step in ordered_steps:
        if cancel_check is not None and cancel_check():
            abort_reason = "canceled"
            break
        item = final_items[step.content]
        try:
            _append_event(
                session_file,
                {
                    "type": "op",
                    "content": step.content,
                    "from": step.from_rel,
                    "to": step.to_rel,
                    "kind": step.kind,
                },
            )
            op_journal[step.content] += 1
        except OSError as exc:
            abort_reason = f"journal_op_failed:{exc.strerror or exc}"
            break
        try:
            if step.kind in ("rename", "temp"):
                os.rename(root_abs / step.from_rel, root_abs / step.to_rel)
            else:  # tag_edit - file already at its final slot for this directory
                apply_tag_edits(
                    root_abs / step.from_rel,
                    {frame: new for frame, _old, new in item.tag_edits},
                )
        except (OSError, ParseError, ValueError) as exc:
            abort_reason = f"{step.kind}_failed:{getattr(exc, 'strerror', None) or str(exc)}"
            break
        try:
            _append_event(
                session_file, {"type": "done", "content": step.content, "kind": step.kind}
            )
            done_count[step.content] += 1
        except OSError as exc:
            # The mutation happened but could not be recorded; recovery probes
            # the live filesystem anyway (the op is journaled without its done).
            abort_reason = f"journal_done_failed:{exc.strerror or exc}"
            break

    try:
        if abort_reason is None:
            _append_event(session_file, {"type": "closed"})
        else:
            _append_event(session_file, {"type": "aborted", "reason": abort_reason})
    except OSError:
        pass  # journal filesystem dead; events written so far still stand

    applied: list[tuple[str, Optional[str]]] = []
    partial: list[tuple[str, str]] = []
    canceled: list[str] = []
    short_code = abort_reason.split(":", 1)[0] if abort_reason else ""
    for rel in sorted(final_items):
        total = len(steps_of[rel])
        if done_count[rel] == total:
            item = final_items[rel]
            applied.append((rel, item.proposed_name if _is_renamed(item) else None))
        elif op_journal[rel] > 0 and abort_reason is not None:
            partial.append((rel, short_code))
        elif abort_reason is not None:
            canceled.append(rel)

    return ApplyReport(session_id, tuple(applied), tuple(rejected), tuple(partial), tuple(canceled))


def _is_plain_file(path: Path) -> bool:
    """True for an existing regular file (lstat: symlinks never qualify)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode)


def _safe_unlink(path: Path) -> None:
    """Unlink ignoring absence/errors (best-effort temp-file cleanup)."""
    try:
        path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Undo / session introspection
# ---------------------------------------------------------------------------


def list_sessions(root: os.PathLike | str) -> list[dict]:
    """Introspect every journal under ``<root>/.musicsyncrename/sessions``.

    One dict per session: session_id, root, started, ops (op+undo_op events),
    done_ops, and state - the last terminal event (closed/aborted/undone) or
    "open" when none was ever written (crash). Unparseable journals are
    reported with ``corrupt=True``.
    """
    sessions_dir = journal_root(root) / "sessions"
    if not sessions_dir.is_dir():
        return []
    out: list[dict] = []
    for entry in sorted(os.listdir(sessions_dir)):
        if not entry.endswith(".jsonl"):
            continue
        session_file = sessions_dir / entry
        try:
            events = _read_session(session_file)
        except EngineError:
            out.append({"session_id": entry[:-6], "corrupt": True})
            continue
        header = next((e for e in events if e.get("type") == "header"), {})
        op_count = sum(1 for e in events if e.get("type") in ("op", "undo_op"))
        done_count = sum(1 for e in events if e.get("type") in ("done", "undo_done"))
        terminal = next(
            (e for e in reversed(events) if e.get("type") in ("closed", "aborted", "undone")),
            None,
        )
        out.append(
            {
                "session_id": entry[:-6],
                "root": header.get("root"),
                "started": header.get("started"),
                "ops": op_count,
                "done_ops": done_count,
                "state": terminal.get("type") if terminal else "open",
            }
        )
    return out


def undo_session(root: os.PathLike | str, session_id: str) -> UndoReport:
    """Restore the library to its pre-session state for ``session_id``.

    - Works on completed (closed), aborted and crash-interrupted sessions alike:
      per-content op chains are rebuilt from the journal ("done" marks the
      latest pending op; an interrupted op is resolved by probing the live
      filesystem at its from/to positions).
    - Validation phase first: every displaced file must be a regular non-symlink
      and every original slot must be free or freed by another undo move in the
      same directory batch. ANY anomaly aborts with no changes at all.
    - The per-directory undo plan goes through the SAME verified planner (the
      undo of a swap is itself a cycle), appending ``undo_begin`` /
      ``undo_op``/``undo_done`` events as it runs; then bytes are restored from
      the session backups via tmp+``os.replace`` only where they differ, so an
      already-restored file can never be clobbered by a repeated undo.
    - A session that was already undone is left untouched (idempotent).
    Backups and journals are preserved for audit after undo. If execution stops
    early the journal stays non-terminal so a later retry completes recovery.
    """
    root_abs = Path(os.path.abspath(os.fspath(root)))
    session_file = _session_path(root_abs, session_id)  # raises on malformed id
    if not session_file.is_file():
        raise EngineError(f"unknown session {session_id!r}")
    events = _read_session(session_file)

    terminal = next(
        (e for e in reversed(events) if e.get("type") in ("closed", "aborted", "undone")),
        None,
    )
    if terminal is not None and terminal.get("type") == "undone":
        # Already restored: a repeated undo must never touch the files again.
        return UndoReport(session_id, (), ())

    # Rebuild per-content op chains in journal order. Apply-phase ops and
    # undo-phase ops share one chain: an interrupted undo op resolves against
    # the live filesystem exactly like an interrupted apply op does.
    chain: dict[str, list[dict]] = {}
    for ev in events:
        etype = ev.get("type")
        if etype in ("op", "undo_op"):
            chain.setdefault(ev["content"], []).append(
                {"from": ev["from"], "to": ev["to"], "kind": ev.get("kind"), "done": False}
            )
        elif etype in ("done", "undo_done"):
            for op in reversed(chain.get(ev.get("content"), ())):
                if not op["done"]:
                    op["done"] = True
                    break

    anomalies: list[tuple[str, str]] = []
    positions: dict[str, str] = {}  # content -> resolved current rel path
    originals: dict[str, str] = {}  # content -> pre-session rel path
    for content in sorted(chain):
        ops_list = chain[content]
        original = ops_list[0]["from"]  # first apply op: the pre-session slot
        originals[content] = original
        pos = original
        consistent = True
        for op in ops_list:
            if op["done"]:
                pos = op["to"]
                continue
            # Interrupted op (apply or undo phase): probe the live filesystem.
            at_from = _is_plain_file(root_abs / op["from"])
            if op["from"] == op["to"]:  # tag edit: position unchanged either way
                continue
            at_to = _is_plain_file(root_abs / op["to"])
            if at_from and at_to:
                anomalies.append((content, "ambiguous_position"))
                consistent = False
                break
            if not at_from and not at_to:
                anomalies.append((content, "missing_after_interrupted_op"))
                consistent = False
                break
            pos = op["to"] if at_to else op["from"]
        if consistent:
            positions[content] = pos

    displaced = {c: p for c, p in positions.items() if p != originals[c]}

    # ---- validation phase (nothing below may change until this is clean) -----
    for content in sorted(displaced):
        try:
            st_cur = os.lstat(root_abs / positions[content])
        except OSError:
            anomalies.append((content, "current_missing"))
            continue
        if not stat.S_ISREG(st_cur.st_mode):  # lstat: a symlink is S_ISLNK here
            anomalies.append((content, "current_not_regular_file"))

    for content in sorted(displaced):
        target_rel = originals[content]
        try:
            os.lstat(root_abs / target_rel)
        except OSError:
            continue  # original slot free: fine
        freed_by_batch = any(
            other != content and positions.get(other) == target_rel for other in displaced
        )
        if not freed_by_batch:
            anomalies.append((content, "target_occupied"))

    if anomalies:
        return UndoReport(session_id, (), tuple(anomalies))  # NO changes made

    # ---- execution phase -------------------------------------------------------
    undo_total: dict[str, int] = {}
    undo_done_count: dict[str, int] = {}
    exec_failed = False
    if displaced:
        try:
            _append_event(session_file, {"type": "undo_begin"})
        except OSError:
            return UndoReport(
                session_id, (), (("__journal__", "undo_journal_failed"),)
            )

        per_dir: dict[str, list[tuple[str, str, str]]] = {}
        for content in sorted(displaced):
            pos = displaced[content]
            per_dir.setdefault(_rel_parent(pos), []).append((content, pos, originals[content]))

        undo_steps: list[_Step] = []
        planning_ok = True
        for rel_dir in sorted(per_dir):
            try:
                ops = [(c, (frm, to)) for c, frm, to in per_dir[rel_dir]]
                undo_steps.extend(plan_moves(ops))
            except EngineError:  # e.g. case-variant originals sharing a key
                anomalies.append(("__plan__", "planning_failed"))
                planning_ok = False
                break
        if not planning_ok:
            return UndoReport(session_id, (), tuple(anomalies))

        for step in undo_steps:
            undo_total[step.content] = undo_total.get(step.content, 0) + 1
        undo_done_count = {c: 0 for c in undo_total}

        for step in undo_steps:
            try:
                _append_event(
                    session_file,
                    {
                        "type": "undo_op",
                        "content": step.content,
                        "from": step.from_rel,
                        "to": step.to_rel,
                        "kind": step.kind,
                    },
                )
            except OSError:
                anomalies.append((step.content, "undo_journal_failed"))
                exec_failed = True
                break
            try:
                os.rename(root_abs / step.from_rel, root_abs / step.to_rel)
            except OSError:
                anomalies.append((step.content, f"undo_{step.kind}_failed"))
                exec_failed = True
                break
            try:
                _append_event(
                    session_file, {"type": "undo_done", "content": step.content, "kind": step.kind}
                )
                undo_done_count[step.content] += 1
            except OSError:
                # The rename happened but could not be recorded; a retry probes
                # the live filesystem and converges on the same state.
                anomalies.append((step.content, "undo_journal_failed"))
                exec_failed = True
                break

    final_pos: dict[str, str] = {}
    for content in positions:
        if (
            content in displaced
            and undo_done_count.get(content, 0) < undo_total.get(content, 1)
        ):
            final_pos[content] = positions[content]  # still away; retry later
        else:
            final_pos[content] = originals[content]

    # Byte-exact restore from backups for every content now at its original slot.
    restored: list[str] = []
    for content in sorted(chain):
        original = originals[content]
        if final_pos.get(content) != original:
            continue  # never write into a slot whose live file is still elsewhere
        backup = _backup_path(root_abs, session_id, original)
        target = root_abs / original
        if backup.is_file():
            try:
                st_target = os.lstat(target)
            except OSError:
                anomalies.append((content, "restore_target_missing"))
                continue
            if not stat.S_ISREG(st_target.st_mode):
                anomalies.append((content, "restore_target_not_regular"))
                continue
            if not _same_content(target, backup):  # idempotent for never-edited files
                tmp = target.parent / f".restore-musicsync-{uuid.uuid4().hex}"
                try:
                    shutil.copy2(backup, tmp)
                    with open(tmp, "rb") as handle:
                        os.fsync(handle.fileno())
                    os.replace(tmp, target)
                except OSError:
                    anomalies.append((content, "restore_failed"))
                    continue
                finally:
                    _safe_unlink(tmp)  # no-op once replaced; cleanup on failure
        restored.append(content)

    if anomalies:
        # Leave the journal non-terminal: retrying undo_session resumes here.
        return UndoReport(
            session_id, tuple(sorted(originals[c] for c in restored)), tuple(anomalies)
        )

    try:
        _append_event(session_file, {"type": "undone"})
    except OSError:
        return UndoReport(
            session_id,
            tuple(sorted(originals[c] for c in restored)),
            (("__journal__", "undo_journal_failed"),),
        )
    return UndoReport(session_id, tuple(sorted(originals[c] for c in restored)), ())


def _same_content(a: Path, b: Path) -> bool:
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            chunk_a = fa.read(1024 * 1024)
            chunk_b = fb.read(1024 * 1024)
            if chunk_a != chunk_b:
                return False
            if not chunk_a:
                return True

                return True
