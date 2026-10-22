from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_SCHEMA_VERSION = 1
SENSITIVE_KEYS = {"api_key", "apikey", "database_url", "direct_url", "password", "secret", "token"}


class ContentToolError(RuntimeError):
    """An operator-facing error with no traceback required."""


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ContentToolError(f"Missing required file: {path}") from error
    except json.JSONDecodeError as error:
        raise ContentToolError(f"Invalid JSON in {path}: {error}") from error


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = stable_json(value)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_sensitive_key(value: Any, prefix: str = "") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            current = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in SENSITIVE_KEYS:
                return current
            found = _find_sensitive_key(child, current)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_sensitive_key(child, f"{prefix}[{index}]")
            if found:
                return found
    return None


@dataclass(frozen=True)
class Workspace:
    root: Path
    config: dict[str, Any]

    @classmethod
    def open(cls, root: str | Path) -> "Workspace":
        resolved = Path(root).resolve()
        config = read_json(resolved / "workspace.json")
        if not isinstance(config, dict) or config.get("schemaVersion") != WORKSPACE_SCHEMA_VERSION:
            raise ContentToolError(f"Unsupported workspace schema in {resolved / 'workspace.json'}")
        sensitive = _find_sensitive_key(config)
        if sensitive:
            raise ContentToolError(f"Workspace configuration must not contain credentials: {sensitive}")
        return cls(resolved, config)

    def inside(self, *parts: str) -> Path:
        candidate = self.root.joinpath(*parts).resolve()
        if not candidate.is_relative_to(self.root):
            raise ContentToolError(f"Workspace path escapes its root: {candidate}")
        return candidate

    @property
    def inventory_path(self) -> Path:
        return self.inside("source-inventory.json")

    @property
    def registry_path(self) -> Path:
        return self.inside("id-registry.json")

    def inventory(self) -> dict[str, Any]:
        inventory = read_json(self.inventory_path)
        if not isinstance(inventory, dict) or not isinstance(inventory.get("sources"), list):
            raise ContentToolError("source-inventory.json must contain a sources array")
        sensitive = _find_sensitive_key(inventory)
        if sensitive:
            raise ContentToolError(f"Source inventory must not contain credentials: {sensitive}")
        return inventory

    def source(self, key: str, version: str) -> tuple[dict[str, Any], dict[str, Any]]:
        inventory = self.inventory()
        if any(not isinstance(item, dict) for item in inventory["sources"]):
            raise ContentToolError("Every source inventory entry must be an object")
        matches = [item for item in inventory["sources"] if item.get("key") == key and item.get("version") == version]
        if len(matches) != 1:
            raise ContentToolError(f"Expected one source inventory entry for {key}@{version}; found {len(matches)}")
        return inventory, matches[0]


def init_workspace(root: str | Path, name: str) -> Path:
    target = Path(root).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ContentToolError(f"Workspace target must be an empty directory: {target}")
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.init.", dir=target.parent))
    try:
        for directory in ("packs", "extracts", "reports", "exports", ".local/sources"):
            (staging / directory).mkdir(parents=True, exist_ok=True)
        write_json(
            staging / "workspace.json",
            {
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "name": name,
                "reviewPolicy": {
                    "localSourceRightsConfirmed": False,
                    "ocrAcceptanceThreshold": None,
                },
                "schemaVersion": WORKSPACE_SCHEMA_VERSION,
            },
        )
        write_json(staging / "source-inventory.json", {"schemaVersion": 1, "sources": []})
        write_json(staging / "id-registry.json", {"schemaVersion": 1, "entries": []})
        write_json(
            staging / "release.json",
            {"name": f"{name}-fixture", "namespace": "fixture", "packFiles": [], "sources": []},
        )
        if target.exists():
            target.rmdir()
        os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target
