from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .identity import ID_PATTERN, require_registered
from .workspace import ContentToolError, Workspace, read_json, stable_json, write_json


RELEASE_KEYS = {"name", "namespace", "sources", "packs"}
PACK_KEYS = {
    "key",
    "title",
    "grade",
    "domain",
    "chapter",
    "topic",
    "subjectId",
    "outcomeCodes",
    "synthetic",
    "sources",
    "knowledgeUnits",
    "lesson",
    "reviews",
}
REVIEW_KINDS = ("editorial", "subject", "rights", "accessibility")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def load_authoring(workspace: Workspace) -> tuple[dict[str, Any], list[tuple[Path, dict[str, Any]]]]:
    release = read_json(workspace.inside("release.json"))
    if not isinstance(release, dict):
        raise ContentToolError("release.json must contain an object")
    allowed = {"name", "namespace", "sources", "packFiles"}
    unknown = sorted(set(release) - allowed)
    if unknown:
        raise ContentToolError(f"Unknown release.json fields: {', '.join(unknown)}")
    if release.get("namespace") not in {"fixture", "baseline"}:
        raise ContentToolError("release namespace must be fixture or baseline")
    if not isinstance(release.get("sources"), list) or not isinstance(release.get("packFiles"), list):
        raise ContentToolError("release.json sources and packFiles must be arrays")
    duplicate_files = _duplicates([item for item in release["packFiles"] if isinstance(item, str)])
    if duplicate_files:
        raise ContentToolError(f"Duplicate packFiles entries: {', '.join(duplicate_files)}")
    wrappers: list[tuple[Path, dict[str, Any]]] = []
    for relative in release["packFiles"]:
        if not isinstance(relative, str):
            raise ContentToolError("Every packFiles entry must be a relative path")
        path = workspace.inside(relative)
        wrapper = read_json(path)
        if not isinstance(wrapper, dict) or set(wrapper) - {"pack", "evidence", "reviewLog"}:
            raise ContentToolError(f"Pack authoring file has unknown fields: {path}")
        wrappers.append((path, wrapper))
    return release, wrappers


def _stable_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ContentToolError(f"{label} must be an authored stable ID")
    return value


def _expected_ids(relative: str, pack: dict[str, Any]) -> list[tuple[str, str, str]]:
    result = [("pack", _stable_id(pack.get("key"), "pack.key"), f"{relative}#pack")]
    for source in pack.get("sources", []):
        identifier = _stable_id(source.get("id"), "pack source.id")
        result.append(("source", identifier, f"{relative}#source:{identifier}"))
    for unit in pack.get("knowledgeUnits", []):
        unit_id = _stable_id(unit.get("id"), "knowledge unit.id")
        result.append(("unit", unit_id, f"{relative}#unit:{unit_id}"))
        for claim in unit.get("claims", []):
            claim_id = _stable_id(claim.get("id"), "claim.id")
            result.append(("claim", claim_id, f"{relative}#claim:{claim_id}"))
    for question in pack.get("lesson", {}).get("questions", []):
        question_id = _stable_id(question.get("id"), "question.id")
        result.append(("question", question_id, f"{relative}#question:{question_id}"))
        for option in question.get("options", []):
            option_id = _stable_id(option.get("id"), "option.id")
            result.append(("option", option_id, f"{relative}#question:{question_id}/option:{option_id}"))
    return result


def _validate_evidence(
    workspace: Workspace,
    namespace: str,
    pack: dict[str, Any],
    evidence: Any,
    path: Path,
) -> None:
    if not isinstance(evidence, list):
        raise ContentToolError(f"{path}: evidence must be an array")
    sources = {item.get("id") for item in pack.get("sources", []) if isinstance(item, dict)}
    claim_ids = {
        claim.get("id")
        for unit in pack.get("knowledgeUnits", [])
        if isinstance(unit, dict)
        for claim in unit.get("claims", [])
        if isinstance(claim, dict)
    }
    inventory = workspace.inventory()
    inventory_index = {
        (item.get("key"), item.get("version")): item
        for item in inventory["sources"]
        if isinstance(item, dict)
    }
    targets: set[tuple[str, str]] = set()

    def validate_item(item: dict[str, Any]) -> None:
        if item.get("sourceId") not in sources:
            raise ContentToolError(f"{path}: evidence references unknown source {item.get('sourceId')}")
        page_index = item.get("physicalPageIndex")
        if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 1:
            raise ContentToolError(f"{path}: evidence physicalPageIndex must be 1-based")
        if not item.get("sourceVersion") or not item.get("extractionMethod"):
            raise ContentToolError(f"{path}: evidence requires sourceVersion and extractionMethod")
        if not isinstance(item.get("sourceSha256"), str) or not SHA256.fullmatch(item["sourceSha256"]):
            raise ContentToolError(f"{path}: evidence requires a lowercase SHA-256 source hash")
        locator = item.get("locator")
        if not isinstance(locator, str) or not locator.strip():
            raise ContentToolError(f"{path}: evidence requires a non-empty locator")
        has_claim = "claimId" in item
        has_content = "contentRef" in item
        if has_claim == has_content:
            raise ContentToolError(f"{path}: evidence must target exactly one claimId or contentRef")
        if has_claim:
            target = item.get("claimId")
            if target not in claim_ids:
                raise ContentToolError(f"{path}: evidence references unknown claim {target}")
            target_key = f"claim:{target}"
        else:
            target = item.get("contentRef")
            if target != "lesson.content":
                raise ContentToolError(f"{path}: unsupported contentRef {target}")
            target_key = target
        mapping = (target_key, item["sourceId"])
        if mapping in targets:
            raise ContentToolError(f"{path}: duplicate evidence mapping {target_key} -> {item['sourceId']}")
        targets.add(mapping)

        if item["extractionMethod"] == "synthetic-fixture":
            if namespace != "fixture" or pack.get("synthetic") is not True:
                raise ContentToolError(f"{path}: synthetic evidence is allowed only in a synthetic fixture pack")
            return
        inventory_source = inventory_index.get((item["sourceId"], item["sourceVersion"]))
        if not inventory_source:
            raise ContentToolError(
                f"{path}: no source inventory entry for {item['sourceId']}@{item['sourceVersion']}"
            )
        if inventory_source.get("sha256") != item["sourceSha256"]:
            raise ContentToolError(f"{path}: evidence source hash differs from source inventory")
        extraction_path = workspace.inside(
            "extracts", item["sourceId"], f"{item['sourceVersion']}.native.json"
        )
        extraction = read_json(extraction_path)
        if (
            not isinstance(extraction, dict)
            or extraction.get("sourceSha256") != item["sourceSha256"]
            or extraction.get("sourceVersion") != item["sourceVersion"]
            or extraction.get("extractionMethod") != item["extractionMethod"]
        ):
            raise ContentToolError(f"{path}: evidence does not match the extraction artifact")
        page_count = extraction.get("pageCount")
        if isinstance(page_count, bool) or not isinstance(page_count, int) or page_index > page_count:
            raise ContentToolError(f"{path}: evidence page is outside the extraction artifact")

    for item in evidence:
        if not isinstance(item, dict):
            raise ContentToolError(f"{path}: every evidence entry must be an object")
        validate_item(item)
    indexed = {(item.get("claimId"), item.get("sourceId")): item for item in evidence if isinstance(item, dict)}
    for unit in pack.get("knowledgeUnits", []):
        for claim in unit.get("claims", []):
            for source_id in claim.get("sourceIds", []):
                item = indexed.get((claim.get("id"), source_id))
                if not item:
                    raise ContentToolError(f"{path}: missing evidence for {claim.get('id')} -> {source_id}")
    if not any(item.get("contentRef") == "lesson.content" for item in evidence):
        raise ContentToolError(f"{path}: lesson.content requires at least one source evidence entry")


def _validate_reviews(namespace: str, pack: dict[str, Any], review_log: Any, path: Path) -> None:
    reviews = pack.get("reviews")
    if not isinstance(reviews, dict):
        raise ContentToolError(f"{path}: pack reviews must be an object")
    if not isinstance(review_log, list):
        raise ContentToolError(f"{path}: reviewLog must be an array")
    review_kinds = [item.get("kind") for item in review_log if isinstance(item, dict)]
    duplicate_review_kinds = _duplicates([kind for kind in review_kinds if isinstance(kind, str)])
    if duplicate_review_kinds:
        raise ContentToolError(f"{path}: duplicate reviewLog kinds: {', '.join(duplicate_review_kinds)}")
    by_kind = {item.get("kind"): item for item in review_log if isinstance(item, dict)}
    expected_status = "fixture-only" if namespace == "fixture" else "approved"
    for kind in REVIEW_KINDS:
        review = reviews.get(kind)
        local = by_kind.get(kind)
        if not isinstance(review, dict) or not isinstance(local, dict):
            raise ContentToolError(f"{path}: missing explicit {kind} review and local review log")
        if local.get("status") != expected_status:
            raise ContentToolError(f"{path}: {kind} review status must be {expected_status} for {namespace}")
        if local.get("email") != review.get("email"):
            raise ContentToolError(f"{path}: {kind} review email differs between pack and review log")
        if not isinstance(review.get("name"), str) or len(review["name"].strip()) < 2:
            raise ContentToolError(f"{path}: {kind} review requires a reviewer name")
        if not isinstance(review.get("email"), str) or not EMAIL.fullmatch(review["email"]):
            raise ContentToolError(f"{path}: {kind} review requires a valid email")
        try:
            reviewed_at = datetime.fromisoformat(str(review.get("at", "")).replace("Z", "+00:00"))
        except ValueError as error:
            raise ContentToolError(f"{path}: {kind} review requires an ISO timestamp") from error
        if reviewed_at.tzinfo is None:
            raise ContentToolError(f"{path}: {kind} review timestamp requires a timezone")
    if reviews["subject"].get("email") == reviews["rights"].get("email"):
        raise ContentToolError(f"{path}: subject and rights reviewers must differ")


def build_manifest(workspace: Workspace) -> dict[str, Any]:
    release, wrappers = load_authoring(workspace)
    packs = []
    expected_ids: list[tuple[str, str, str]] = []
    for path, wrapper in wrappers:
        pack = wrapper.get("pack")
        if not isinstance(pack, dict):
            raise ContentToolError(f"{path}: pack must be an object")
        unknown = sorted(set(pack) - PACK_KEYS)
        missing = sorted(PACK_KEYS - set(pack))
        if unknown or missing:
            raise ContentToolError(f"{path}: pack fields mismatch; missing={missing}, unknown={unknown}")
        lesson = pack.get("lesson")
        if not isinstance(lesson, dict):
            raise ContentToolError(f"{path}: lesson must be an object")
        if "basicExercises" in pack or "basicExercises" in lesson:
            raise ContentToolError(f"{path}: basicExercises waits for the M2a backend contract")
        if lesson.get("questions") != []:
            raise ContentToolError(f"{path}: lesson.questions must stay empty in M1 to avoid creating a public QUIZ")
        _validate_evidence(workspace, release["namespace"], pack, wrapper.get("evidence"), path)
        _validate_reviews(release["namespace"], pack, wrapper.get("reviewLog"), path)
        relative = path.relative_to(workspace.root).as_posix()
        expected_ids.extend(_expected_ids(relative, pack))
        packs.append(pack)
    duplicate_pack_keys = _duplicates([item["key"] for item in packs])
    if duplicate_pack_keys:
        raise ContentToolError(f"Duplicate pack keys: {', '.join(duplicate_pack_keys)}")
    sources = release["sources"]
    if any(not isinstance(item, dict) for item in sources):
        raise ContentToolError("release sources must be objects")
    for source in sources:
        identifier = _stable_id(source.get("key"), "release source.key")
        expected_ids.append(("source", identifier, f"release.json#source:{identifier}"))
    duplicate_source_keys = _duplicates([source["key"] for source in sources])
    if duplicate_source_keys:
        raise ContentToolError(f"Duplicate release source keys: {', '.join(duplicate_source_keys)}")
    require_registered(workspace, expected_ids)
    manifest = {
        "name": release.get("name"),
        "namespace": release["namespace"],
        "packs": sorted(packs, key=lambda item: item["key"]),
        "sources": sorted(sources, key=lambda item: item.get("key", "")),
    }
    if set(manifest) != RELEASE_KEYS or not isinstance(manifest["name"], str) or len(manifest["name"].strip()) < 3:
        raise ContentToolError("Release manifest envelope is incomplete")
    return manifest


def export_manifest(workspace: Workspace, output: str | Path | None = None) -> tuple[Path, str]:
    manifest = build_manifest(workspace)
    target = Path(output).resolve() if output else workspace.inside("exports", "release-manifest.json")
    if output and not target.is_relative_to(workspace.root):
        raise ContentToolError("Export output must stay inside the workspace")
    payload = stable_json(manifest)
    write_json(target, manifest)
    return target, hashlib.sha256(payload.encode("utf-8")).hexdigest()
