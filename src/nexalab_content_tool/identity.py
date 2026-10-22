from __future__ import annotations

import re
from typing import Any

from .workspace import ContentToolError, Workspace, read_json, write_json


ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
ID_KINDS = {"pack", "source", "unit", "claim", "step", "question", "option"}


def registry_entries(workspace: Workspace) -> list[dict[str, Any]]:
    registry = read_json(workspace.registry_path)
    if not isinstance(registry, dict) or registry.get("schemaVersion") != 1 or not isinstance(registry.get("entries"), list):
        raise ContentToolError("id-registry.json must use schemaVersion 1 and contain an entries array")
    if any(not isinstance(entry, dict) for entry in registry["entries"]):
        raise ContentToolError("Every ID registry entry must be an object")
    return registry["entries"]


def reserve_id(workspace: Workspace, kind: str, identifier: str, owner: str) -> bool:
    if kind not in ID_KINDS:
        raise ContentToolError(f"Unsupported ID kind {kind}; choose from {', '.join(sorted(ID_KINDS))}")
    if not ID_PATTERN.fullmatch(identifier):
        raise ContentToolError("ID must match ^[a-z0-9][a-z0-9._-]{1,79}$")
    if not owner.strip():
        raise ContentToolError("ID owner is required")
    entries = registry_entries(workspace)
    existing = next((entry for entry in entries if entry.get("kind") == kind and entry.get("id") == identifier), None)
    if existing:
        if existing.get("owner") != owner:
            raise ContentToolError(
                f"{kind} ID {identifier} is already owned by {existing.get('owner')}; registry was not changed"
            )
        return False
    entries.append({"id": identifier, "kind": kind, "owner": owner})
    write_json(
        workspace.registry_path,
        {"schemaVersion": 1, "entries": sorted(entries, key=lambda item: (item["kind"], item["id"]))},
    )
    return True


def require_registered(workspace: Workspace, expected: list[tuple[str, str, str]]) -> None:
    index = {(entry.get("kind"), entry.get("id")): entry.get("owner") for entry in registry_entries(workspace)}
    problems = []
    for kind, identifier, owner in expected:
        registered_owner = index.get((kind, identifier))
        if registered_owner is None:
            problems.append(f"unregistered {kind} ID {identifier} (owner {owner})")
        elif registered_owner != owner:
            problems.append(f"{kind} ID {identifier} belongs to {registered_owner}, not {owner}")
    if problems:
        raise ContentToolError("Stable ID check failed:\n- " + "\n- ".join(problems))
