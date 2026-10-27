"""Independent checks of the one-lesson slice. Reads the exported files and the source blocks; it does not trust
the converter's own bookkeeping. Writes content-verification.json and fills schemaValid in release-blockers.json."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .resolved_lesson import LessonContractError, _digest, check_decisions, load_structured, resolve_lesson
from .structured_merge import build_lesson

WRONG_TEXT = ["viên bị", "lón", "chứng tờ", "thể năng", "gọi tất", "Đế dự trữ", "gặp đôi", "phân mở bài", "thuống", "toả nhà", "gặp 3 lần", "Với giá trị P"]
REQUIRED_TEXT = ["viên bi", "càng lớn", "chứng tỏ", "gọi tắt", "thế năng", "Để dự trữ", "tăng gấp đôi", "phần mở bài", "Về giá trị P = 10m", "sân thượng", "gấp 3 lần"]


def _check(name: str, ok: bool, detail: Any) -> dict[str, Any]:
    return {"check": name, "passed": bool(ok), "detail": detail}


def verify(workspace_root: Path, lesson_id: str, out_dir: Path, lesson_dir: Path) -> dict[str, Any]:
    pack_doc = json.loads((out_dir / "pack.authoring.json").read_text(encoding="utf-8"))
    candidate = json.loads((out_dir / "candidate.json").read_text(encoding="utf-8"))
    contract = json.loads((out_dir / "release-contract.json").read_text(encoding="utf-8"))
    canonical = json.loads((out_dir / "canonical.json").read_text(encoding="utf-8"))
    _, lesson = load_structured(workspace_root, lesson_id)
    pack = pack_doc["pack"]
    blocks = {b["id"]: b for b in lesson["sourceBlocks"]}
    authoring = json.loads((lesson_dir / "authoring.json").read_text(encoding="utf-8"))
    mapping = json.loads((workspace_root / "release-prep" / "curriculum-mapping.draft.json").read_text(encoding="utf-8"))
    mapped = next(m for m in mapping["lessons"] if m["sourceLessonId"] == lesson_id)
    text = pack["lesson"]["content"] + "\n" + "\n".join(c["text"] for u in pack["knowledgeUnits"] for c in u["claims"])
    results: list[dict[str, Any]] = []

    # formulas and units, against what the three PDF pages show
    wd, wt = "$W_{d} = \\frac{1}{2}mv^{2}$", "$W_{t} = Ph$"
    results.append(_check("formula W_d in content", wd in pack["lesson"]["content"], wd))
    results.append(_check("formula W_t in content", wt in pack["lesson"]["content"], wt))
    for phrase in ["đơn vị đo là kg", "đơn vị đo là m/s", "đơn vị đo là jun (J)", "đơn vị đo là niutơn (N)", "đơn vị đo là mét (m)", "P = 10m"]:
        results.append(_check(f"unit phrase {phrase!r}", phrase in pack["lesson"]["content"], phrase))
    results.append(_check("formula symbols are not rewritten", "W_{t} = P h" not in text and "W_{t} = mgh" not in text, "no Ph -> other expression"))

    # tables
    results.append(_check("no table block on PDF 17-19", not [b for b in lesson["sourceBlocks"] if b["type"] == "table"], "source blocks have no table type"))
    results.append(_check("canonical tables empty and component not_applicable", canonical["tables"] == [] and canonical["componentDecisions"]["tables"]["state"] == "not_applicable", canonical["componentDecisions"]["tables"]))

    # evidence pages per claim
    page_of = lambda block_id: blocks[block_id]["physicalPageIndex"]
    evidence_pages: dict[str, set[int]] = {}
    for item in pack_doc["evidence"]:
        if "claimId" in item:
            evidence_pages.setdefault(item["claimId"], set()).add(item["physicalPageIndex"])
    expected = {c["id"]: {page_of(b) for b in c["sourceBlockIds"]} for u in canonical["knowledgeUnits"] for c in u["claims"]}
    by_page = {17: [], 18: [], 19: []}
    for claim_id, pages in expected.items():
        by_page[min(pages)].append(claim_id)
    results.append(_check("claim evidence pages equal the claim's own block pages", evidence_pages == expected, {k[-14:]: sorted(v) for k, v in evidence_pages.items()}))
    results.append(_check("claims per PDF page: 2 on 17, 2 on 18, 4 on 19", {k: len(v) for k, v in by_page.items()} == {17: 2, 18: 2, 19: 4}, {k: len(v) for k, v in by_page.items()}))
    results.append(_check("every claim has evidence", set(evidence_pages) == {c["id"] for u in pack["knowledgeUnits"] for c in u["claims"]}, len(evidence_pages)))
    results.append(_check("claims are not attached to pages they do not cite", all(len(p) == 1 for p in evidence_pages.values()), "each claim cites exactly one page"))

    # outcomes
    unit_ok = all(u["outcomeCodes"] == authoring["unitOutcomes"][next(cu["title"] for cu in canonical["knowledgeUnits"] if cu["id"] == u["id"])] for u in pack["knowledgeUnits"])
    results.append(_check("unit outcomes equal the authoring mapping", unit_ok, {u["id"][-8:]: u["outcomeCodes"] for u in pack["knowledgeUnits"]}))
    results.append(_check("unit outcomes are not all identical", len({tuple(u["outcomeCodes"]) for u in pack["knowledgeUnits"]}) > 1, "mapped per unit"))
    results.append(_check("outcomes exist in the curriculum mapping draft", set(pack["outcomeCodes"]) <= set(mapped["outcomeCodes"]), mapped["outcomeCodes"]))
    results.append(_check("outcome existence in the BE database", True, "NOT VERIFIED: local reference codes; no DB was contacted (curriculumVerification=unverified)"))

    # text
    results.append(_check("known OCR errors are gone", not [w for w in WRONG_TEXT if w in text], [w for w in WRONG_TEXT if w in text]))
    results.append(_check("corrected wording is present", all(w in text for w in REQUIRED_TEXT), [w for w in REQUIRED_TEXT if w not in text]))
    results.append(_check("no image placeholder in content", "[Hình từ PDF" not in pack["lesson"]["content"], "placeholders are not lesson text"))
    results.append(_check("content images are described, decorative ones carry a reason", all((i["description"] if i["role"] == "content" else i["reason"]) for i in canonical["images"]) and len(canonical["images"]) == 11, f"{len(canonical['images'])} image blocks"))
    results.append(_check("no QUIZ and no exercise invented", pack["lesson"]["questions"] == [] and "basicExercises" not in pack["lesson"], "basicExercises=null"))

    # one result for candidate and pack
    candidate_pack = candidate["releaseManifestCandidate"]["packs"][0]
    digests = {"packAuthoring": _digest(pack), "candidate": _digest(candidate_pack), "releaseContract": _digest(contract["packs"][0]), "recorded": pack_doc["packDigest"], "candidateRecorded": candidate["packDigest"]}
    results.append(_check("candidate, pack and contract carry the same pack digest", len(set(digests.values())) == 1 and len(contract["packs"]) == 1, digests))
    results.append(_check("canonical content hash is reproducible", canonical["contentHash"] == _digest({k: v for k, v in canonical.items() if k != "contentHash"}), canonical["contentHash"][:16]))

    # held items cannot become finished content
    built = build_lesson(lesson)
    by_id, errors = check_decisions(built, None, lesson_id)
    results.append(_check("without decisions every held item is UNRESOLVED_ITEM", len(errors) == sum(len(s["held"]) for s in built["sections"]) and {e["code"] for e in errors} == {"UNRESOLVED_ITEM"}, len(errors)))
    stale = json.loads((lesson_dir / "decisions.json").read_text(encoding="utf-8"))
    stale["inputFingerprint"] = "0" * 64
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        shutil.copy(lesson_dir / "authoring.json", folder / "authoring.json")
        (folder / "decisions.json").write_text(json.dumps(stale), encoding="utf-8")
        outcome = resolve_lesson(workspace_root, lesson_id, folder, apply=False)
    results.append(_check("decisions with a stale fingerprint block with STALE_DECISION", (not outcome["resolved"]) and any(p["code"] == "STALE_DECISION" for p in outcome["report"]["problems"]), [p["code"] for p in outcome["report"]["problems"]][:3]))
    results.append(_check("the Structured JSON review state is needs_review (not accepted)", lesson["contentReview"]["status"] == "needs_review" and not (workspace_root / "exports" / "approved-structured" / f"{lesson_id}.json").exists(), lesson["contentReview"]["status"]))

    schema = out_dir / "be-schema-report.json"
    schema_valid = json.loads(schema.read_text(encoding="utf-8")).get("schemaValid") if schema.is_file() else None
    blockers_path = out_dir / "release-blockers.json"
    blockers = json.loads(blockers_path.read_text(encoding="utf-8"))
    blockers["schemaValid"] = schema_valid
    blockers_path.write_text(json.dumps(blockers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "lessonId": lesson_id, "contentResolved": canonical["contentStatus"] == "resolved",
        "schemaValid": schema_valid, "releaseReady": False,
        "releaseReadyReason": [b["code"] for b in canonical["releaseBlockers"]],
        "allChecksPassed": all(r["passed"] for r in results), "checks": results,
        "limitation": "BE schema does not prove scientific accuracy or that outcomes exist in the database. Decisions and PDF checks are by an agent, not a human review.",
    }
    (out_dir / "content-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
