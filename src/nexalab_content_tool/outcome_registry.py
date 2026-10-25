"""Unique outcome registry for KHTN 9, built from the AI mapping draft.

The draft numbers outcomes by position inside each lesson, so one code such as ``nang-luong-co-hoc/1`` names a
different "yêu cầu cần đạt" in every lesson that uses it (30 of its 44 codes are ambiguous). A code must name one
statement. This module issues one code per distinct (topic, statement) and rewrites each lesson's mapping to those
codes. The scheme stays ``local-reference-not-official``: the CT GDPT 2018 has no numeric outcome codes, and the
mapping is an agent match that no human has verified.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

DOMAIN = {"PHYSICS": "ENERGY", "CHEMISTRY": "MATTER", "BIOLOGY": "LIVING"}
SUBJECT = {"PHYSICS": "physics", "CHEMISTRY": "chemistry", "BIOLOGY": "biology"}
# Statements whose text is visibly damaged in the draft (words from two sentences interleaved).
KNOWN_DEFECTS = {
    "src-lesson-khtn9-33": "statement 3 mixes two sentences ('...vỏ Trái Đất (nhiên Đất và khai thác tài nguyên liệu...'); needs the official wording",
}


DAMAGED_MARKERS = ["(nhiên Đất và khai thác"]  # interleaved words from two sentences; never seeded
# Statements restored from the textbook's own MỤC TIÊU box after reading the PDF page (not from the official programme text).
RESTORED = {
    ("src-lesson-khtn9-33", 2): {
        "statement": "Trình bày được những lợi ích cơ bản về kinh tế, xã hội từ việc khai thác vỏ Trái Đất (nhiên liệu, vật liệu, nguyên liệu); lợi ích của sự tiết kiệm và bảo vệ nguồn tài nguyên, sử dụng vật liệu tái chế,... phục vụ cho sự phát triển bền vững.",
        "restoredFrom": "PDF page 148 (printed 146), MỤC TIÊU third bullet; the draft text was damaged. Checked against the page image by an agent, not by a human reviewer.",
    }
}


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", str(text)).split())


def _slug(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


MAX_CODE = 40  # BE packManifestSchema: outcome code at most 40 characters
MAX_TOPIC = MAX_CODE - len("KHTN-L9/") - len("/99")


def _topic_slug(text: str, taken: dict[str, str]) -> str:
    full = _slug(text) or "khac"
    if full in taken.values():
        return next(k for k, v in taken.items() if v == full)
    short = full
    while len(short) > MAX_TOPIC:
        short = short.rsplit("-", 1)[0] if "-" in short else short[:MAX_TOPIC]
    candidate, n = short, 1
    while candidate in taken and taken[candidate] != full:
        n += 1
        candidate = f"{short[:MAX_TOPIC - 2].rstrip('-')}-{n}"
    taken[candidate] = full
    return candidate


def build_registry(mapping_path: Path) -> dict[str, Any]:
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    outcomes: dict[tuple[str, str], dict[str, Any]] = {}
    counters: dict[str, int] = {}
    lessons: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    topics: dict[str, str] = {}
    for lesson in mapping["lessons"]:
        domain = DOMAIN.get(lesson["proposedDomain"])
        if not domain:
            problems.append(f"{lesson['sourceLessonId']}: unknown domain {lesson['proposedDomain']}")
            continue
        topic = _topic_slug(str(lesson.get("curriculumTopic") or "khac"), topics)
        codes = []
        statements = lesson.get("outcomeText") or []
        if len(statements) != len(lesson.get("outcomeCodes") or []):
            problems.append(f"{lesson['sourceLessonId']}: {len(lesson.get('outcomeCodes') or [])} codes but {len(statements)} statements")
        for index, statement in enumerate(statements):
            restored = RESTORED.get((lesson["sourceLessonId"], index))
            if restored:
                statement = restored["statement"]
            key = (topic, _norm(statement))
            if key not in outcomes:
                counters[topic] = counters.get(topic, 0) + 1
                outcomes[key] = {"code": f"KHTN-L9/{topic}/{counters[topic]}", "grade": 9, "domain": domain, "chapter": str(lesson.get("curriculumTopic") or ""), "statement": _norm(statement), "lessons": [], "verified": False}
            elif outcomes[key]["domain"] != domain:
                problems.append(f"{outcomes[key]['code']}: statement used with two domains")
            if restored:
                outcomes[key]["restoredFrom"] = restored["restoredFrom"]
            outcomes[key]["lessons"].append(lesson["sourceLessonId"])
            codes.append(outcomes[key]["code"])
        lessons[lesson["sourceLessonId"]] = {
            "title": lesson["title"], "domain": domain, "subjectId": SUBJECT[lesson["proposedDomain"]], "topic": lesson.get("curriculumTopic"),
            "outcomeCodes": codes, "domainVerified": bool(lesson.get("domainVerified")), "chapter": lesson.get("chapter"),
            "note": lesson.get("chapterNote"),
        }
    return {
        "scheme": "local-reference-not-official",
        "status": "AI-agent mapping, not verified by a human subject reviewer",
        "derivedFrom": mapping_path.name,
        "outcomes": sorted(({**o, **({"defect": "statement text is damaged in the draft; not seeded"} if any(m in o["statement"] for m in DAMAGED_MARKERS) else {})} for o in outcomes.values()), key=lambda o: o["code"]),
        "lessons": lessons,
        "defects": [{"detail": p} for p in problems],
        "draftAmbiguity": {"distinctDraftCodes": len({c for l in mapping["lessons"] for c in l["outcomeCodes"]}), "distinctStatements": len(outcomes)},
    }


def write_registry(workspace_root: Path) -> Path:
    registry = build_registry(workspace_root / "release-prep" / "curriculum-mapping.draft.json")
    target = workspace_root / "release-prep" / "outcome-registry.json"
    target.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    import sys

    print(write_registry(Path(sys.argv[1])))
