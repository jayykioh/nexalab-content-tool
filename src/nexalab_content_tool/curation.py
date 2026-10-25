"""Applies a person's (or agent's) checked decisions on top of a batch scaffold.

A spec is plain data written after reading the PDF pages: it accepts the auto-proposed decisions it checked, decides
the held items the rules could not settle, describes figures and verifies formulas and tables. The result is written
to the lesson's authoring.json and decisions.json and the folder is marked ``.protected`` so a later batch run
never overwrites it. Every decision records who made it and that it is an agent check, not a human review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .resolved_lesson import load_structured
from .structured_merge import build_lesson

ACTOR = "coder-agent"
REVIEW_KIND = "agent-source-check"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_curation(root: Path, number: str, spec: dict[str, Any]) -> dict[str, Any]:
    lesson_id = f"src-lesson-khtn9-{number}"
    folder = root / "release-prep" / f"bai{number}"
    authoring, decisions = _load(folder / "authoring.json"), _load(folder / "decisions.json")
    _, lesson = load_structured(root, lesson_id)
    built = build_lesson(lesson)
    items = {h["id"]: h for s in built["sections"] for h in s["held"]}
    if decisions["inputFingerprint"] != built["fingerprint"]:
        raise ValueError(f"bài {number}: scaffold is stale; run the batch scaffold again")
    pages = spec["pdfPages"]
    log: dict[str, Any] = {"autoAccepted": 0, "manual": 0, "images": 0, "formulas": 0}

    if spec.get("acceptAuto"):
        for decision in decisions["decisions"]:
            if decision.get("autoProposed"):
                decision.update({"autoProposed": False, "actor": ACTOR, "reviewKind": REVIEW_KIND, "pdfCheck": {"pdfPages": pages, "note": spec["acceptAuto"]}})
                log["autoAccepted"] += 1
    taken = {d["itemId"] for d in decisions["decisions"]}
    for rule in spec.get("manual", []):
        hits = [
            h for hid, h in items.items()
            if hid not in taken and h["kind"] == rule["kind"]
            and ((h.get("learning") or {}).get("text", "").startswith(rule["startsWith"]) or (h.get("source") or {}).get("text", "").startswith(rule["startsWith"]))
        ]
        if len(hits) != 1:
            raise ValueError(f"bài {number}: rule {rule['startsWith']!r} matched {len(hits)} held items")
        h = hits[0]
        taken.add(h["id"])
        decisions["decisions"].append({
            "itemId": h["id"], "fingerprint": h["fingerprint"], "action": rule["action"], "replacement": rule.get("replacement"),
            "sourceBlockIds": rule.get("sourceBlockIds", []), "reason": rule["reason"], "actor": ACTOR, "reviewKind": REVIEW_KIND,
            "pdfCheck": {"pdfPages": pages, "note": rule.get("observed", "")},
        })
        log["manual"] += 1

    def block_id(suffix: str) -> str:
        found = [b for b in authoring["images"] if b.endswith(suffix)] or [f["id"] for f in authoring["formulas"] if f["id"].endswith(suffix)]
        if len(found) != 1:
            raise ValueError(f"bài {number}: {suffix} matched {len(found)} ids")
        return found[0]

    for suffix, (label, description) in spec.get("figures", {}).items():
        authoring["images"][block_id(suffix)] = {"role": "content", "figureLabel": label, "description": description, "describedBy": f"{ACTOR} from PDF pages {pages}; not a human review"}
        log["images"] += 1
    for suffix, reason in spec.get("decorative", {}).items():
        authoring["images"][block_id(suffix)] = {"role": "decorative", "reason": reason}
    for suffix, latex in spec.get("formulas", {}).items():
        formula = next(f for f in authoring["formulas"] if f["id"].endswith(suffix))
        formula["latex"] = latex
        formula["verifiedBy"] = f"{ACTOR} visual check of PDF pages {pages}; not a human review"
        log["formulas"] += 1
    if authoring["formulas"] and all(f.get("verifiedBy") for f in authoring["formulas"]):
        decisions["components"]["formulas"] = {"state": "resolved", "reason": f"every equation block checked against PDF pages {pages}", "sourceBlockIds": [b for f in authoring["formulas"] for b in f["sourceBlockIds"]]}
    if authoring["tables"] and spec.get("tablesVerified"):
        decisions["components"]["tables"] = {"state": "resolved", "reason": spec["tablesVerified"], "sourceBlockIds": [b for t in authoring["tables"] for b in t["sourceBlockIds"]]}
    if spec.get("importanceFromCue"):
        for key, cfg in authoring["claims"].items():
            if cfg.get("importanceCue"):
                cfg.update({"important": True, "basis": "claim states a definition, law or formula (rule cue; classified by coder-agent, not a human reviewer)"})
    for key, text in spec.get("claimImportance", {}).items():
        authoring["claims"][key] = {"important": True, "basis": text}
    _save(folder / "authoring.json", authoring)
    _save(folder / "decisions.json", decisions)
    (folder / ".protected").write_text("curated by coder-agent; scaffold must not overwrite\n", encoding="utf-8")
    return log
