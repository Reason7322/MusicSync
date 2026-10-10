"""Deterministic Android shared-storage destination filename mapping."""
from collections import defaultdict
import hashlib
from pathlib import PurePosixPath
import re


MAX_COMPONENT_BYTES = 255
INVALID = frozenset('"*/:<>?\\|')
INVALID_RUN = re.compile(r"(?:\s*\x00\s*)+")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()


def _split_extension(name: str) -> tuple[str, str]:
    suffix = PurePosixPath(name).suffix
    return (name[:-len(suffix)], suffix) if suffix else (name, "")


def _fit(name: str, identity: str, suffix_text: str = "") -> str:
    stem, extension = _split_extension(name)
    trailer = suffix_text + extension
    available = MAX_COMPONENT_BYTES - len(trailer.encode("utf-8"))
    if available < 1:
        raise ValueError(f"Filename extension is too long for Android shared storage: {identity!r}")
    kept = []
    used = 0
    for character in stem:
        encoded = character.encode("utf-8", "surrogateescape")
        if used + len(encoded) > available:
            break
        kept.append(character)
        used += len(encoded)
    return "".join(kept) + trailer


def _candidate(name: str, identity: str) -> str:
    replaced = "".join("\x00" if ord(char) < 32 or ord(char) == 127 or char in INVALID else char
                       for char in name)
    replaced = INVALID_RUN.sub(" - ", replaced)
    if len(replaced.encode("utf-8", "surrogateescape")) <= MAX_COMPONENT_BYTES:
        return replaced
    return _fit(replaced, identity, "~" + _digest(identity)[:8])


def _siblings(names: list[str], parent: str) -> dict[str, str]:
    candidates = {name: _candidate(name, f"{parent}/{name}" if parent else name) for name in names}
    groups = defaultdict(list)
    for name, candidate in candidates.items():
        groups[candidate].append(name)
    result, used = {}, set()
    for name in names:
        if name == candidates[name]:
            result[name] = name
            used.add(name)
    for name in names:
        if name in result:
            continue
        candidate = candidates[name]
        if len(groups[candidate]) == 1 and candidate not in used:
            result[name] = candidate
            used.add(candidate)
            continue
        identity = f"{parent}/{name}" if parent else name
        digest = _digest(identity)
        for length in range(8, len(digest) + 1, 2):
            unique = _fit(candidate, identity, "~" + digest[:length])
            if unique not in used:
                result[name] = unique
                used.add(unique)
                break
        else:
            raise ValueError(f"Could not create unique Android filename for {identity!r}.")
    return result


def destination_paths(files, directories) -> dict[str, str]:
    """Map relative source paths to stable, unique Android-safe paths."""
    files = set(files)
    directories = set(directories)
    all_paths = files | directories
    children = defaultdict(set)
    for path in all_paths:
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"Unsafe source path: {path!r}")
        parent, _, name = path.rpartition("/")
        children[parent].add(name)

    mapped = {}
    pending = [""]
    while pending:
        parent = pending.pop()
        destinations = _siblings(sorted(children[parent]), parent)
        destination_parent = mapped.get(parent, "")
        for name, destination_name in destinations.items():
            source_path = f"{parent}/{name}" if parent else name
            destination_path = f"{destination_parent}/{destination_name}" if destination_parent else destination_name
            mapped[source_path] = destination_path
            if source_path in directories:
                pending.append(source_path)
    if set(mapped) != all_paths:
        raise ValueError("Source inventory contains a path without its parent directory.")
    return mapped
