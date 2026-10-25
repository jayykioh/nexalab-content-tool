from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .workspace import ContentToolError, Workspace


def load_catalog_registry(workspace: Workspace) -> dict[str, Any]:
    path = workspace.inside("catalog-registry.json")
    if not path.exists():
        raise ContentToolError("CATALOG_REGISTRY_MISSING: export catalog-registry.json from BE before standard export")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContentToolError(f"CATALOG_REGISTRY_INVALID: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise ContentToolError("CATALOG_REGISTRY_INVALID: schemaVersion must be 1")
    for key in ("chapters", "topics", "outcomes"):
        if not isinstance(data.get(key), list):
            raise ContentToolError(f"CATALOG_REGISTRY_INVALID: {key} must be an array")
    return data


def suggested_curriculum(registry: dict[str, Any], *, chapter_code: str | None = None, topic_code: str | None = None, order: int | None = None, outcome_codes: list[str] | None = None) -> dict[str, Any]:
    return {
        "chapterCode": chapter_code,
        "topicCode": topic_code,
        "order": order,
        "outcomeCodes": outcome_codes or [],
        "confirmed": False,
    }


def validate_confirmed_curriculum(workspace: Workspace, pack: dict[str, Any]) -> None:
    registry = load_catalog_registry(workspace)
    taxonomy = pack.get("curriculum")
    if not isinstance(taxonomy, dict) or taxonomy.get("confirmed") is not True:
        raise ContentToolError("CURRICULUM_CONFIRMATION_REQUIRED: operator must confirm Chapter, Topic and Order")
    chapters = {item.get("code") for item in registry["chapters"] if isinstance(item, dict)}
    topics = {item.get("code") for item in registry["topics"] if isinstance(item, dict)}
    outcomes = {item.get("code") for item in registry["outcomes"] if isinstance(item, dict)}
    if taxonomy.get("chapterCode") not in chapters or taxonomy.get("topicCode") not in topics:
        raise ContentToolError("CURRICULUM_CODE_INVALID: selected Chapter/Topic is absent from BE catalog registry")
    selected = pack.get("outcomeCodes") or []
    if not selected or any(code not in outcomes for code in selected):
        raise ContentToolError("OUTCOME_CODE_INVALID: every outcome code must exist in BE catalog registry")
    if taxonomy.get("outcomeCodes") != selected:
        raise ContentToolError("OUTCOME_CONFIRMATION_REQUIRED: confirmed outcome selection differs from pack outcomes")
