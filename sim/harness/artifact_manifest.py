"""Offline schema checks for stored simulation evidence manifests.

Alongside the klt entry schema, this repository requires evidence entries
with unique canonical sim/ names and keys that name the producer's repo.
"""

from __future__ import annotations

import posixpath
import re

SCHEMA_VERSION = 1
KIND = "evidence"
REQUIRED = ("sha256", "size", "kind", "producer", "uri")
OPTIONAL = ("name", "media_type")
PRODUCER_FIELDS = ("tool", "version", "loom.repo", "commit")

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
#: The manifest ``uri`` is a logical name only the broker resolves,
#: ``artifact:<key>`` (operator ruling H1, 2AMLogic/2am#5553; klayout-tools
#: ``7e3561f``). It names no storage location; any other scheme is refused.
URI_RE = re.compile(r"^artifact:([^/\s]\S*)$")


def uri_key(uri: str) -> str | None:
    """The broker key of an ``artifact:<key>`` uri, else ``None``."""
    m = URI_RE.match(uri) if isinstance(uri, str) else None
    return m.group(1) if m else None


def repo_from_key(key: str) -> str | None:
    """``owner/name`` from an ``evidence/<owner>__<name>/...`` key."""
    parts = key.split("/")
    if len(parts) < 3 or parts[0] != "evidence" or parts[1].count("__") != 1:
        return None
    return parts[1].replace("__", "/")


def canonical_name(name) -> bool:
    return (isinstance(name, str) and name.startswith("sim/")
            and "\\" not in name and "\0" not in name
            and posixpath.normpath(name) == name
            and not {"", ".", ".."} & set(name.split("/")))


def entry_problems(entry) -> list[str]:
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    problems = []
    missing = [f for f in REQUIRED if f not in entry]
    extra = sorted(set(entry) - set(REQUIRED) - set(OPTIONAL))
    if missing:
        problems.append(f"missing {', '.join(missing)}")
    if extra:
        problems.append(f"unknown field(s) {', '.join(extra)}")
    sha = entry.get("sha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        problems.append("sha256 must be 64 lowercase hex digits")
    size = entry.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        problems.append("size must be a positive integer")
    if entry.get("kind") != KIND:
        problems.append(f"kind must be {KIND!r}")
    producer = entry.get("producer")
    if not isinstance(producer, dict) or set(producer) != set(PRODUCER_FIELDS):
        problems.append(f"producer must carry exactly {', '.join(PRODUCER_FIELDS)}")
    else:
        for f in ("tool", "version", "loom.repo"):
            if not isinstance(producer.get(f), str) or not producer[f]:
                problems.append(f"producer.{f} must be a non-empty string")
        if producer.get("commit") is not None and not isinstance(producer["commit"], str):
            problems.append("producer.commit must be a string or null")
    key = uri_key(entry.get("uri"))
    if key is None:
        problems.append("uri must be artifact:<key> (no other scheme)")
    else:
        if key.rsplit("/", 1)[-1] != sha:
            problems.append("uri key does not end in the entry's sha256")
        key_repo = repo_from_key(key)
        if key_repo is None:
            problems.append("uri key is not evidence/<owner>__<name>/...")
        elif isinstance(producer, dict) and producer.get("loom.repo") not in (None, key_repo):
            problems.append("uri key names a different repo than producer.loom.repo")
    if "name" not in entry:
        problems.append("name is required here (the logical sim/ path of the bytes)")
    elif not canonical_name(entry["name"]):
        problems.append("name must be a canonical relative sim/... path")
    if "media_type" in entry and not isinstance(entry["media_type"], str):
        problems.append("media_type must be a string")
    return problems


def manifest_problems(manifest) -> list[str]:
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "entries"} \
            or manifest.get("schema_version") != SCHEMA_VERSION \
            or not isinstance(manifest.get("entries"), list):
        return [f"not {{schema_version: {SCHEMA_VERSION}, entries: [...]}}"]
    if not manifest["entries"]:
        return ["has no entries"]
    problems = []
    seen = set()
    for i, entry in enumerate(manifest["entries"]):
        for p in entry_problems(entry):
            problems.append(f"entry {i}: {p}")
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str):
            if name in seen:
                problems.append(f"entry {i}: duplicate name {name!r}")
            seen.add(name)
    return problems
