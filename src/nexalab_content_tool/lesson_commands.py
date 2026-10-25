"""CLI entry points for the one-lesson slice: resolve-lesson and export-lesson-contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .manifest import _validate_evidence, _validate_reviews
from .resolved_lesson import LessonContractError, _digest, canonical_to_pack, load_resolved, resolve_lesson
from .workspace import ContentToolError, Workspace


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_resolve_lesson(workspace: Workspace, lesson_id: str, lesson_dir: str, report: str | None, apply: bool) -> int:
    folder = workspace.inside(*Path(lesson_dir).parts)
    try:
        result = resolve_lesson(workspace.root, lesson_id, folder, apply=apply)
    except LessonContractError as error:
        print(json.dumps({"contentResolved": False, "code": error.code, "detail": error.detail}, ensure_ascii=False))
        return 2
    if not result["resolved"]:
        target = workspace.inside(*Path(report).parts) if report else folder / "blocked-report.json"
        _write(target, result["report"])
        codes = sorted({p["code"] for p in result["report"]["problems"]})
        print(json.dumps({"contentResolved": False, "problems": len(result["report"]["problems"]), "codes": codes, "report": str(target)}, ensure_ascii=False))
        return 2
    canonical = result["canonical"]
    print(json.dumps({"contentResolved": True, "contentHash": canonical["contentHash"], "canonical": result["canonicalPath"], "applied": apply}, ensure_ascii=False))
    return 0


def run_export_lesson_contract(workspace: Workspace, lesson_id: str, out: str) -> int:
    folder = workspace.inside(*Path(out).parts)
    try:
        canonical, lesson = load_resolved(workspace.root, lesson_id)
        converted = canonical_to_pack(canonical, lesson["sourceBlocks"])
    except LessonContractError as error:
        _write(folder / "blocked-report.json", {"kind": "blocked-report", "lessonId": lesson_id, "contentResolved": False, "code": error.code, "detail": error.detail, "problems": error.items})
        print(json.dumps({"contentResolved": False, "code": error.code, "report": str(folder / "blocked-report.json")}, ensure_ascii=False))
        return 2
    pack, evidence = converted["pack"], converted["evidence"]
    tool_gates: list[str] = []
    try:
        _validate_evidence(workspace, "baseline", pack, evidence, folder / "pack.authoring.json")
    except ContentToolError as error:
        raise ContentToolError(f"evidence does not validate against the workspace: {error}") from error
    try:
        _validate_reviews("baseline", pack, converted["reviewLog"], folder / "pack.authoring.json")
    except ContentToolError as error:
        tool_gates.append(f"export_manifest review gate: {error}")
    manifest = {"name": f"{canonical['packKey']}-contract", "namespace": "baseline", "sources": [], "packs": [pack]}
    digest = converted["packDigest"]
    _write(folder / "canonical.json", canonical)
    _write(folder / "candidate.json", {
        "kind": "lesson-candidate", "targetSchema": "releaseManifestSchema", "lessonId": lesson_id, "ready": False,
        "contentResolved": True, "canonicalContentHash": canonical["contentHash"], "packDigest": digest,
        "releaseManifestCandidate": manifest, "blockers": canonical["releaseBlockers"],
    })
    _write(folder / "pack.authoring.json", {"pack": pack, "evidence": evidence, "reviewLog": converted["reviewLog"], "canonicalContentHash": canonical["contentHash"], "packDigest": digest})
    _write(folder / "release-contract.json", manifest)
    _write(folder / "release-blockers.json", {
        "lessonId": lesson_id, "contentResolved": True, "schemaValid": None, "releaseReady": False,
        "blockers": canonical["releaseBlockers"], "toolGates": tool_gates,
        "note": "schemaValid is filled by the BE validator report (be-schema-report.json); releaseReady stays false while any blocker remains",
    })
    print(json.dumps({"contentResolved": True, "packDigest": digest, "releaseReady": False, "blockers": [b["code"] for b in canonical["releaseBlockers"]], "out": str(folder)}, ensure_ascii=False))
    return 0
