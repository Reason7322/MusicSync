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
    session_id: str
    applied: tuple[tuple[str, Optional[str]], ...]  # (rel_path, new_name|None=tags-only)
    rejected: tuple[tuple[str, str], ...]  # (rel_path, reason_code)
    canceled: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.canceled


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
    scan: ScanResult = scan_root(root)
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

_SAFE_NAME_RE = re.compile(r"^[^\x00/\\]+$")


def apply_changes(
    root: os.PathLike | str,
    preview: Preview,
    approved: Iterable[str],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> ApplyReport:
    """Apply ONLY explicitly approved items from ``preview``.

    Each approval is a rel_path present in the preview. Validation happens
    against live state at call time (the preview may be stale). On any failure
    the remaining work stops and an undoable session id is returned; nothing
    after the failing step is attempted.
    """
    root_abs = Path(os.path.abspath(os.fspath(root)))
    if not root_abs.is_dir():
        raise EngineError(f"root is not a directory: {root}")

    items_by_rel = {item.rel_path: item for item in preview.items}
    approved_list = list(dict.fromkeys(approved))  # de-duplicate, keep order

    rejected: list[tuple[str, str]] = []
    candidates: dict[str, ItemPlan] = {}
    for rel in approved_list:
        item = items_by_rel.get(rel)
        if item is None:
            rejected.append((rel, "not_in_preview"))
            continue
        has_rename = bool(item.proposed_name and item.proposed_name != item.current_name)
        if not has_rename and not item.tag_edits:
            rejected.append((rel, "nothing_to_do"))
            continue
        if item.status in ("ambiguous", "error"):
            rejected.append((rel, f"status_{item.status}_not_applicable"))
            continue
        candidates[rel] = item

    # --- per-item live validation -------------------------------------------
    validated: dict[str, ItemPlan] = {}
    for rel in sorted(candidates):
        code = _validate_item(root_abs, candidates[rel])
        if code is None:
            validated[rel] = candidates[rel]
        else:
            rejected.append((rel, code))

    # --- cross-item checks with LIVE directory listings ----------------------
    final_items: dict[str, ItemPlan] = {}
    grouped: dict[str, list[ItemPlan]] = {}
    for rel in sorted(validated):
        grouped.setdefault(validated[rel].rel_dir, []).append(validated[rel])

    for rel_dir, group in grouped.items():
        dir_path = root_abs / rel_dir if rel_dir else root_abs
        try:
            live_keys = {name_key(n) for n in os.listdir(dir_path)}
        except OSError as exc:
            for item in group:
                rejected.append((item.rel_path, f"dir_unreadable:{exc.strerror or exc}"))
            continue

        # target key uniqueness within this directory batch
        by_target_key: dict[str, list[ItemPlan]] = {}
        moving_away_keys: set[str] = {name_key(i.current_name) for i in group}
        for item in group:
            if not item.proposed_name or name_key(item.proposed_name) == name_key(item.current_name):
                continue  # tags-only content
            by_target_key.setdefault(name_key(item.proposed_name), []).append(item)

        colliding_items = []
        for key, owners in by_target_key.items():
            if len(owners) > 1:
                colliding_items.extend(owners)
        for item in group:
            rel_ = item.rel_path
            if any(i is item for i in colliding_items):
                rejected.append((rel_, "proposal_collision"))
                continue
            if (
                item.proposed_name
                and name_key(item.proposed_name) != name_key(item.current_name)
                and name_key(item.proposed_name) in live_keys
                and not _target_freed_by_batch(live_keys, name_key(item.proposed_name), group, item)
            ):
                rejected.append((rel_, "target_exists"))
                continue
            final_items[rel_] = item

    if not final_items:
        return ApplyReport(str(uuid.uuid4())[:32], (), tuple(rejected))

    # --- session setup + backups BEFORE any mutation --------------------------
    session_id = uuid.uuid4().hex
    sessions_dir = journal_root(root_abs) / "sessions"
    backups_dir = journal_root(root_abs) / "backups" / session_id
    try:
        sessions_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EngineError(f"cannot create journal dir: {exc}") from exc

    for rel in sorted(final_items):
        item = final_items[rel]
        if not item.tag_edits:
            continue
        backup_file = _backup_path(root_abs, session_id, rel)
        try:
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root_abs / rel, backup_file)
            with open(backup_file, "rb") as handle:
                os.fsync(handle.fileno())
        except OSError as exc:
            _safe_unlink(backup_file)
            raise EngineError(f"failed to back up {rel} before editing tags: {exc}") from exc

    session_file = sessions_dir / f"{session_id}.jsonl"
    try:
        _append_event(session_file, {"type": "header", "id": session_id, "root": str(root_abs), "started": _utc_now_iso()})
    except OSError as exc:
        raise EngineError(f"cannot write journal: {exc}") from exc

    # --- plan moves per directory --------------------------------------------
    all_steps: list[_Step] = []
    steps_by_dir: dict[str, list[_Step]] = {}
    for rel_dir in sorted(grouped):
        if rel_dir not in _dirs_of(final_items):
            continue
        ops = [
            (rel_, (rel_, _join(rel_dir, final_items[rel_].proposed_name)))  # type: ignore[arg-type]
            for rel_ in sorted(final_items)
            if final_items[rel_].rel_dir == rel_dir
            and final_items[rel_].proposed_name
            and name_key(final_items[rel_].proposed_name) != name_key(final_items[rel_].current_name)
        ]
        tags_only_here = [
            rel_ for rel_ in sorted(final_items)
            if final_items[rel_].rel_dir == rel_dir
            and (not final_items[rel_].proposed_name
                 or name_key(final_items[rel_].proposed_name) == name_key(final_items[rel_].current_name))
        ]
        try:
            steps = plan_moves(ops)
        except EngineError as exc:
            for rel_ in [r for r in final_items if _dirs_of_one(rel_, rel_dir)]:
                rejected.append((rel_, "planning_failed"))
            continue
        for step in steps:
            all_steps.append(step)
        # tags-only pseudo steps execute after the moves of their directory
        for rel_ in tags_only_here:
            item = final_items[rel_]
            if item.tag_edits or (item.proposed_name and item.proposed_name != item.current_name):
                steps.append(_Step(rel_, item.rel_path, item.rel_path, "tag_edit"))
        steps_by_dir[rel_dir] = steps

    # --- execute -------------------------------------------------------------
    applied: list[tuple[str, Optional[str]]] = []
    canceled: list[str] = []
    aborted_reason: Optional[str] = None
    done_contents: set[str] = set()
    final_name_for: dict[str, str] = {rel_: (final_items[rel_].proposed_name or final_items[rel_].current_name) for rel_ in final_items}

    ordered_steps: list[_Step] = []
    for rel_dir in sorted(steps_by_dir):
        ordered_steps.extend(steps_by_dir[rel_dir])

    content_final_step: dict[str, _Step] = {}
    for step in ordered_steps:
        if step.kind == "rename":
            content_final_step[step.content] = step  # last rename per content wins (chains end at target)

    try:
        for step in ordered_steps:
            if cancel_check is not None and cancel_check():
                aborted_reason = "canceled"
                break
            item = final_items.get(step.content)
            if item is None:
                continue  # already rejected/aborted bookkeeping elsewhere
            _append_event(session_file, {
                "type": "op", "content": step.content,
                "from": step.from_rel, "to": step.to_rel, "kind": step.kind,
            })
            try:
                if step.kind == "temp" or step.kind == "rename":
                    os.rename(root_abs / step.from_rel, root_abs / step.to_rel)
                if step.kind == "rename" and step in content_final_step.values() and item.tag_edits:
                    apply_tag_edits(root_abs / step.to_rel, {frame: new for frame, _old, new in item.tag_edits})
                elif step.kind == "tag_edit" and item.tag_edits:
                    apply_tag_edits(root_abs / step.from_rel, {frame: new for frame, _old, new in item.tag_edits})
            except (OSError, ParseError, ValueError) as exc:
                aborted_reason = f"{step.kind}_failed:{exc.strerror if isinstance(exc, OSError) else str(exc)}"
                break
            _append_event(session_file, {"type": "done", "content": step.content, "kind": step.kind})
            if step.kind == "tag_edit" or (step.kind == "rename" and step is content_final_step.get(step.content)):
                done_contents.add(step.content)
        else:
            aborted_reason = None

        for rel_ in sorted(final_items):
            if rel_ not in done_contents and canceled or aborted_reason:
                pass  # bookkeeping below
    finally:
        if aborted_reason is None:
            try:
                _append_event(session_file, {"type": "closed"})
            except OSError as exc:
                raise EngineError(f"cannot close journal: {exc}") from exc
        else:
            try:
                _append_event(session_file, {"type": "aborted", "reason": aborted_reason})
            except OSError:
                pass  # journal fs is broken; caller still gets the session id

    for rel_ in sorted(final_items):
        if rel_ not in done_contents:
            canceled.append(rel_)
        else:
            applied.append((rel_, None if final_name_for[rel_] == items_by_rel[rel_].current_name and not _has_rename(final_items[rel_]) else final_name_for[rel_]))

    return ApplyReport(session_id, tuple(applied), tuple(rejected), tuple(canceled))


def _dirs_of(items: dict[str, ItemPlan]) -> set[str]:
    return {i.rel_dir for i in items.values()}


def _dirs_of_one(rel_: str, rel_dir: str) -> bool:
    return Path(rel_).parent.as_posix() == rel_dir


def _has_rename(item: ItemPlan) -> bool:
    return bool(item.proposed_name and item.proposed_name != item.current_name)


def _target_freed_by_batch(
    live_keys: set[str], target_key: str, group: Sequence[ItemPlan], item: ItemPlan
) -> bool:
    """True when the only occupant of ``target_key`` in this directory is itself
    being renamed away by another approved item in the same batch."""
    for other in group:
        if other is not item and name_key(other.current_name) == target_key:
            return True
    return False


def _validate_item(root_abs: Path, item: ItemPlan) -> Optional[str]:
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

    proposed = item.proposed_name
    if proposed and proposed != item.current_name:
        if not _SAFE_NAME_RE.match(proposed) or proposed in (".", ".."):
            return "unsafe_name_chars"
        if len(proposed.encode("utf-8")) > MAX_NAME_BYTES:
            return "name_too_long"
    return None


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Undo / session introspection
# ---------------------------------------------------------------------------


def list_sessions(root: os.PathLike | str) -> list[dict]:
    sessions_dir = journal_root(root) / "sessions"
    if not sessions_dir.is_dir():
        return []
    out = []
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
        op_count = sum(1 for e in events if e.get("type") == "op")
        done_count = sum(1 for e in events if e.get("type") == "done" and e.get("kind") != "tag_edit")
        last = next((e for e in reversed(events) if e.get("type") in ("closed", "aborted", "undone")), None)
        out.append({
            "session_id": entry[:-6],
            "root": header.get("root"),
            "started": header.get("started"),
            "ops": op_count,
            "done_ops": done_count,
            "state": last.get("type") if last else "open",
        })
    return out


def undo_session(root: os.PathLike | str, session_id: str) -> UndoReport:
    """Restore the library to its pre-session state for ``session_id``.

    - Works on complete, canceled and crash-interrupted sessions alike (the
      journal plus live filesystem probes resolve every file's true position).
    - Validation phase first: nothing changes if any file is in an unexpected
      state; anomalies are reported without partial restoration.
    - Original filenames AND original bytes (for metadata-edited files, from
      the session backup) are restored. Backups and journals are preserved for
      audit after undo.
    """
    root_abs = Path(os.path.abspath(os.fspath(root)))
    session_file = _session_path(root_abs, session_id)
    if not session_file.is_file():
        raise EngineError(f"unknown session {session_id!r}")
    events = _read_session(session_file)

    # Rebuild per-content op chains in journal order.
    chain: dict[str, list[dict]] = {}
    for ev in events:
        t = ev.get("type")
        if t == "op":
            chain.setdefault(ev["content"], []).append(ev | {"done": False})
        elif t == "done":
            ops_for_content = chain.get(ev.get("content"))
            if not ops_for_content:
                continue
            for op in reversed(ops_for_content):
                if not op["done"]:
                    op["done"] = True
                    break

    tagged_contents = {ev["content"] for ev in events if ev.get("type") == "op" and False}  # refined below
    tagged_contents = set()
    # A content had metadata edits when a backup exists; that is the source of truth.
    backups_dir = journal_root(root_abs) / "backups" / session_id

    anomalies: list[tuple[str, str]] = []
    positions: dict[str, str] = {}  # content -> current rel path
    originals: dict[str, str] = {}
    for content in sorted(chain):
        ops_list = chain[content]
        original = ops_list[0]["from"]
        originals[content] = original
        pos = original
        consistent = True
        for op in ops_list:
            if not op["done"]:
                # Crashed mid-op: probe the live filesystem.
                at_to = (root_abs / op["to"]).is_file() and not os.path.islink(root_abs / op["to"])
                at_from = (root_abs / op["from"]).is_file() and not os.path.islink(root_abs / op["from"])
                if at_to:
                    pos = op["to"]
                elif at_from:
                    pass  # stays where it was
                else:
                    anomalies.append((content, "missing_after_interrupted_op"))
                    consistent = False
                    break
            else:
                pos = op["to"]
        if consistent:
            positions[content] = pos

    displaced = {c: p for c, p in positions.items() if p != originals[c]}
    byte_restore_needed = [
        c for c in sorted(positions)
        if _backup_path(root_abs, session_id, originals[c]).is_file() and c not in anomalies[0][0]  # type: ignore[index]
        or False
    ]

    # ---- validation phase (no changes yet) ---------------------------------
    moved_targets: dict[str, set[str]] = {}
    for content, pos in displaced.items():
        target_rel = originals[content]
        dir_key = Path(target_rel).parent.as_posix()
        moved_targets.setdefault(dir_key, set()).add(name_key(Path(pos).name))

    validation_ok = not anomalies
    for content in sorted(displaced):
        target_path = root_abs / originals[content]
        current_path = root_abs / positions[content]
        try:
            st_cur = os.lstat(current_path)
            if stat.S_ISLNK(st_cur.st_mode) or not stat.S_ISREG(st_cur.st_mode):
                anomalies.append((content, "current_not_regular_file"))
                validation_ok = False
                continue
        except OSError:
            anomalies.append((content, "current_missing"))
            validation_ok = False
            continue
        if target_path.exists() or os.path.islink(target_path):
            dir_key = Path(originals[content]).parent.as_posix()
            target_key = name_key(Path(originals[content]).name)
            # The slot may be freed by another undo move in this batch.
            frees_it = False
            for other_content, other_pos in displaced.items():
                if other_content == content:
                    continue
                if Path(other_pos).parent.as_posix() == dir_key and name_key(Path(other_pos).name) == target_key \
                        and name_key(Path(originals[other_content]).name) != target_key:
                    frees_it = True
                    break
            if not frees_it:
                anomalies.append((content, "target_occupied"))
                validation_ok = False
    for content in anomalies and [a[0] for a in anomalies] or []:
        pass

    restored_names: list[str] = []
    restored_bytes: list[str] = []
    if not validation_ok:
        return UndoReport(session_id, (), tuple(anomalies))

    # ---- execution phase ----------------------------------------------------
    _append_event(session_file, {"type": "undo_begin"})

    per_dir_ops: dict[str, list[tuple[str, str, str]]] = {}  # dir -> (content, from_rel, to_rel)
    for content in displaced:
        d = Path(positions[content]).parent.as_posix()
        per_dir_ops.setdefault(d, []).append((content, positions[content], originals[content]))

    undo_steps: list[_Step] = []
    try:
        for d in sorted(per_dir_ops):
            ops = [(c, (frm, to)) for c, frm, to in per_dir_ops[d]]
            undo_steps.extend(plan_moves(ops))
    except EngineError as exc:
        anomalies.append(("__plan__", str(exc)))
        return UndoReport(session_id, (), tuple(anomalies))

    try:
        for step in undo_steps:
            _append_event(session_file, {
                "type": "undo_op", "content": step.content, "from": step.from_rel, "to": step.to_rel, "kind": step.kind,
            })
            os.rename(root_abs / step.from_rel, root_abs / step.to_rel)
            _append_event(session_file, {"type": "undo_done", "content": step.content, "kind": step.kind})

        # Byte-exact restore of metadata-edited files from session backups.
        for content in sorted(positions):
            backup = _backup_path(root_abs, session_id, originals[content])
            if not backup.is_file():
                continue
            target = root_abs / originals[content]
            tmp = Path(os.path.join(str(target.parent), f".restore-{uuid.uuid4().hex}"))
            try:
                shutil.copy2(backup, tmp)
                with open(tmp, "rb") as handle:
                    os.fsync(handle.fileno())
                same_bytes = target.is_file() and _same_content(target, backup)
                if not same_bytes:
                    os.replace(tmp, target)
            finally:
                _safe_unlink(tmp)
            restored_bytes.append(content)
        _append_event(session_file, {"type": "undone"})
    except OSError as exc:
        anomalies.append(("__execute__", f"{exc.strerror or exc}"))

    restored = sorted(set(restored_names | [c for c in displaced])) if displaced else []
    return UndoReport(
        session_id,
        tuple(sorted(displaced)),
        tuple(anomalies),
    )


def _same_content(a: Path, b: Path) -> bool:
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            chunk_a = fa.read(1024 * 1024)
            chunk_b = fb.read(1024 * 1024)
            if chunk_a != chunk_b:
                return False
            if not chunk_a:
                return True
