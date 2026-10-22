from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .identity import ID_PATTERN
from .workspace import ContentToolError, Workspace, read_json, write_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(value: str) -> str:
    """Normalize presentation only; keep symbols and scientific wording unchanged."""
    text = unicodedata.normalize("NFC", str(value)).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _reviewed_blocks(workspace: Workspace, book_key: str, pages: list[int]) -> list[dict[str, Any]]:
    from .m1_workflow import page_record

    result: list[dict[str, Any]] = []
    for number in pages:
        page = page_record(workspace, book_key, number)
        if not page or page.get("review", {}).get("status") != "accepted":
            raise ContentToolError(f"PDF page {number} must be accepted before enrichment")
        edits = page.get("review", {}).get("edits", {})
        for index, block in enumerate(page.get("blocks", [])):
            original = str(block.get("text", ""))
            reviewed = str(edits.get(str(index), original))
            result.append({
                "id": block["id"],
                "type": block.get("type", "text"),
                "originalText": original,
                "reviewedText": reviewed,
                "normalizedText": normalize_text(reviewed),
                "physicalPageIndex": number,
                "printedPageLabel": block.get("printedPageLabel"),
                "bbox": block.get("bbox"),
                "sourceSha256": block.get("sourceSha256") or page.get("sourceSha256"),
                "extractionMethod": block.get("extractionMethod") or page.get("method"),
            })
    return result


def _stable_id(prefix: str, seed: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-")[:36] or "content"
    return f"{prefix}-{clean}-{hashlib.sha256(seed.encode()).hexdigest()[:8]}"


def build_enrichment_proposal(workspace: Workspace, book_key: str, chapter_id: str, pages: list[int]) -> dict[str, Any]:
    blocks = _reviewed_blocks(workspace, book_key, pages)
    sections: list[dict[str, Any]] = []
    current = {"id": _stable_id("section", f"{chapter_id}-intro"), "heading": "Nội dung bài học", "content": [], "sourceBlockIds": []}
    for block in blocks:
        text = block["normalizedText"]
        kind = str(block["type"]).lower()
        if not text and kind == "image":
            text = f"[Hình từ PDF trang {block['physicalPageIndex']}; cần mô tả thủ công]"
        if not text:
            continue
        if kind in {"title", "paragraph_title", "heading", "section_title"}:
            if current["content"]:
                current["content"] = "\n\n".join(current["content"])
                sections.append(current)
            current = {"id": _stable_id("section", block["id"]), "heading": text, "content": [], "sourceBlockIds": [block["id"]]}
        else:
            current["content"].append(text)
            current["sourceBlockIds"].append(block["id"])
    if current["content"]:
        current["content"] = "\n\n".join(current["content"])
        sections.append(current)
    if not sections:
        raise ContentToolError("Accepted pages contain no usable text")
    claims = []
    for section in sections:
        sentence = next((part.strip() for part in re.split(r"(?<=[.!?])\s+", section["content"]) if len(part.strip()) >= 20), "")
        if sentence:
            claims.append({"id": _stable_id("claim", section["id"]), "text": sentence, "sourceBlockIds": section["sourceBlockIds"]})
    if not claims:
        claims.append({"id": _stable_id("claim", sections[0]["id"]), "text": sections[0]["content"][:1000], "sourceBlockIds": sections[0]["sourceBlockIds"]})
    unit = {"id": _stable_id("unit", chapter_id), "title": sections[0]["heading"], "claims": claims, "terms": [], "misconceptions": [], "sourceBlockIds": sorted({item for section in sections for item in section["sourceBlockIds"]})}
    proposal = {"schemaVersion": 1, "kind": "local", "status": "proposed", "bookKey": book_key, "chapterId": chapter_id, "pages": sorted(set(pages)), "sections": sections, "knowledgeUnits": [unit], "blocks": blocks, "createdAt": _now()}
    path = workspace.inside(".local", "proposals", f"{book_key}-{chapter_id}-local.json")
    write_json(path, proposal)
    return proposal


def gemini_proposal(workspace: Workspace, book_key: str, chapter_id: str, pages: list[int], *, provider_confirmed: bool, transmission_allowed: bool) -> dict[str, Any]:
    if not provider_confirmed or not transmission_allowed:
        raise ContentToolError("Confirm provider policy and permission to transmit reviewed source text")
    key = os.environ.get("GOOGLE_GEMINI_API") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ContentToolError("Configure GOOGLE_GEMINI_API or GEMINI_API_KEY before using Gemini")
    base = build_enrichment_proposal(workspace, book_key, chapter_id, pages)
    source = [{"id": block["id"], "type": block["type"], "text": block["normalizedText"], "page": block["physicalPageIndex"]} for block in base["blocks"]]
    prompt = """Return JSON only. You are proposing, never approving, a Vietnamese KHTN lesson from reviewed OCR. Preserve scientific meaning and sourceBlockIds. Correct LaTeX only when certain. Schema: {\"summary\":string,\"title\":string,\"learningObjective\":string,\"outcomeSuggestions\":[{\"code\":string,\"reason\":string}],\"sections\":[{\"id\":string,\"heading\":string,\"content\":string,\"sourceBlockIds\":[string]}],\"knowledgeUnits\":[{\"id\":string,\"title\":string,\"claims\":[{\"id\":string,\"text\":string,\"sourceBlockIds\":[string]}],\"terms\":[string],\"misconceptions\":[string],\"sourceBlockIds\":[string]}],\"latexCorrections\":[{\"blockId\":string,\"original\":string,\"proposed\":string,\"reason\":string}]}\nOCR:\n""" + json.dumps(source, ensure_ascii=False)
    model = os.environ.get("NEXALAB_GEMINI_MODEL", "gemini-3.5-flash")
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read())
        content = payload["candidates"][0]["content"]["parts"][0]["text"].strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        suggestion = json.loads(content)
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as error:
        raise ContentToolError(f"Gemini proposal failed: {error}") from error
    proposal = {"schemaVersion": 1, "kind": "gemini", "status": "proposed", "provider": "google-gemini", "model": model, "bookKey": book_key, "chapterId": chapter_id, "pages": sorted(set(pages)), "sourceBlockIds": [block["id"] for block in base["blocks"]], "proposal": suggestion, "createdAt": _now()}
    write_json(workspace.inside(".local", "proposals", f"{book_key}-{chapter_id}-gemini.json"), proposal)
    return proposal


_LAB_MODELS = (
    ("chemistry@1.0.0", ("phản ứng", "hoá học", "hóa học", "chất phản ứng", "sản phẩm", "mol", "axit", "bazơ"), "Phản ứng định lượng, chất giới hạn và nhận biết axit/bazơ."),
    ("circuit@1.0.0", ("mạch điện", "điện áp", "dòng điện", "điện trở", "led"), "Mạch nối tiếp/song song với nguồn 1–24 V, điện trở và LED."),
    ("eye@1.0.0", ("mắt", "giác mạc", "võng mạc", "thể thủy tinh", "thị giác"), "Nhận diện tám bộ phận của mắt người."),
)


def suggest_lab_candidates(workspace: Workspace, draft: dict[str, Any], *, outcome_verified: bool) -> list[dict[str, Any]]:
    outcome = str(draft.get("outcomeCode", "")).strip()
    if not outcome or not outcome_verified:
        raise ContentToolError("A verified curriculum outcome is required before suggesting a Lab")
    text = normalize_text(" ".join([str(draft.get("title", "")), str(draft.get("learningObjective", "")), str(draft.get("claim", "")), *(str(section.get("content", "")) for section in draft.get("sections", []))])).lower()
    candidates = []
    for model, terms, capability in _LAB_MODELS:
        evidence = sorted(term for term in terms if term in text)
        if evidence:
            candidates.append({"id": _stable_id("lab-candidate", f"{draft['packKey']}-{model}"), "status": "proposed", "modelRef": model, "outcomeCodes": [outcome], "objective": draft.get("learningObjective", ""), "rationale": f"Nội dung khớp: {', '.join(evidence)}", "capability": capability, "sourcePages": draft.get("pages", []), "editableNotes": "", "requiresScientificReview": True})
    path = workspace.inside(".local", "lab-candidates", f"{draft['packKey']}.json")
    wrapper = {"schemaVersion": 1, "packKey": draft["packKey"], "status": "proposed", "candidates": candidates, "updatedAt": _now()}
    write_json(path, wrapper)
    return candidates


def save_lab_candidates(workspace: Workspace, pack_key: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not ID_PATTERN.fullmatch(pack_key) or not isinstance(candidates, list):
        raise ContentToolError("Invalid Lab candidate payload")
    allowed = {model for model, _, _ in _LAB_MODELS}
    if any(
        not isinstance(item, dict)
        or not ID_PATTERN.fullmatch(str(item.get("id", "")))
        or item.get("modelRef") not in allowed
        or item.get("status") != "proposed"
        or not isinstance(item.get("outcomeCodes"), list)
        or not item.get("outcomeCodes")
        or any(not str(code).strip() for code in item["outcomeCodes"])
        for item in candidates
    ):
        raise ContentToolError("Lab candidates must remain proposals for an existing simulation model")
    wrapper = {"schemaVersion": 1, "packKey": pack_key, "status": "proposed", "candidates": candidates, "updatedAt": _now()}
    write_json(workspace.inside(".local", "lab-candidates", f"{pack_key}.json"), wrapper)
    return wrapper
