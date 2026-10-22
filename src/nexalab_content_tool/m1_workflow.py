from __future__ import annotations

import hashlib
import html
import re
import subprocess
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pymupdf

from .extract import native_page_blocks
from .identity import ID_PATTERN, reserve_ids
from .manifest import REVIEW_KINDS, build_manifest, export_manifest
from .workspace import ContentToolError, Workspace, read_json, sha256_file, write_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _ReadableHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"tr", "p", "br", "li"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _mineru_text(block: dict[str, Any]) -> str:
    value = str(block.get("text") or block.get("content") or "")
    if "<" not in value:
        return value.strip()
    parser = _ReadableHtml()
    parser.feed(value)
    return html.unescape("".join(parser.parts)).strip()


def _books_path(workspace: Workspace) -> Path:
    return workspace.inside(".local", "books.json")


def books(workspace: Workspace) -> list[dict[str, Any]]:
    path = _books_path(workspace)
    value = read_json(path) if path.exists() else {"schemaVersion": 1, "books": []}
    if not isinstance(value, dict) or not isinstance(value.get("books"), list):
        raise ContentToolError("Invalid local books index")
    return value["books"]


def _save_books(workspace: Workspace, items: list[dict[str, Any]]) -> None:
    write_json(_books_path(workspace), {"schemaVersion": 1, "books": items})


def _book(workspace: Workspace, key: str) -> dict[str, Any]:
    found = next((item for item in books(workspace) if item.get("key") == key), None)
    if found is None:
        raise ContentToolError(f"Unknown book {key}")
    return found


def _chapter(book: dict[str, Any], chapter_id: str) -> dict[str, Any]:
    found = next((item for item in book.get("chapters", []) if item.get("id") == chapter_id), None)
    if found is None:
        raise ContentToolError(f"Unknown chapter {chapter_id}")
    return found


def _pdf(workspace: Workspace, book: dict[str, Any]) -> Path:
    path = workspace.inside(".local", "books", book["key"], "source.pdf")
    if not path.is_file() or sha256_file(path) != book["sha256"]:
        raise ContentToolError("Book PDF is missing or changed")
    return path


def import_book(workspace: Workspace, payload: bytes, *, key: str, version: str, title: str, author: str, local_rights: bool, printed_start: int | None = None) -> dict[str, Any]:
    if not ID_PATTERN.fullmatch(key) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", version):
        raise ContentToolError("Book key or version is invalid")
    if not title.strip() or not author.strip() or not local_rights:
        raise ContentToolError("Book title, author and local processing rights are required")
    if not payload.startswith(b"%PDF-") or len(payload) > 300_000_000:
        raise ContentToolError("Choose a valid PDF below 300 MB")
    try:
        with pymupdf.open(stream=payload, filetype="pdf") as document:
            if not document.is_pdf or document.page_count < 1:
                raise ContentToolError("PDF has no pages")
            page_count = document.page_count
    except ContentToolError:
        raise
    except Exception as error:
        raise ContentToolError(f"Cannot open PDF: {error}") from error
    digest = hashlib.sha256(payload).hexdigest()
    items = books(workspace)
    if any(item["key"] == key for item in items):
        existing = next(item for item in items if item["key"] == key)
        if existing["sha256"] != digest or existing["version"] != version:
            raise ContentToolError("Book key already belongs to a different PDF or version")
        if existing["title"] != title.strip() or existing["author"] != author.strip():
            existing["title"], existing["author"] = title.strip(), author.strip()
            _save_books(workspace, items)
        return existing
    pdf = workspace.inside(".local", "books", key, "source.pdf")
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(payload)
    labels = {str(page): str(printed_start + page - 1) for page in range(1, page_count + 1)} if printed_start is not None else {}
    item = {"key": key, "version": version, "title": title.strip(), "author": author.strip(), "sha256": digest, "pageCount": page_count, "printedPageLabels": labels, "chapters": [], "importedAt": _now()}
    inventory = workspace.inventory()
    inventory["sources"].append({"key": key, "version": version, "sha256": digest, "rights": {"localProcessingConfirmed": True}, "printedPageLabels": labels})
    write_json(workspace.inventory_path, inventory)
    config = dict(workspace.config)
    config["reviewPolicy"] = {**config.get("reviewPolicy", {}), "localSourceRightsConfirmed": True}
    write_json(workspace.inside("workspace.json"), config)
    items.append(item)
    _save_books(workspace, items)
    return item


def save_chapter(workspace: Workspace, book_key: str, *, chapter_id: str, title: str, start: int, end: int, printed_start: int | None = None) -> dict[str, Any]:
    items = books(workspace)
    book = next((item for item in items if item["key"] == book_key), None)
    if book is None:
        raise ContentToolError("Unknown book")
    if not ID_PATTERN.fullmatch(chapter_id) or not title.strip():
        raise ContentToolError("Chapter ID or title is invalid")
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > book["pageCount"]:
        raise ContentToolError("Chapter page range is outside the PDF")
    existing = next((chapter for chapter in book["chapters"] if chapter["id"] == chapter_id), None)
    if existing and (existing["start"], existing["end"]) != (start, end):
        raise ContentToolError("An existing chapter's page range cannot change; create a new chapter ID")
    chapter = existing or {"id": chapter_id, "title": title.strip(), "start": start, "end": end, "createdAt": _now()}
    chapter["title"] = title.strip()
    if not existing:
        book["chapters"].append(chapter)
    if printed_start is not None:
        if isinstance(printed_start, bool) or not isinstance(printed_start, int) or printed_start < 1:
            raise ContentToolError("Printed page label must start at 1 or be left blank")
        labels = {str(page): str(printed_start + page - start) for page in range(start, end + 1)}
        book["printedPageLabels"].update(labels)
        inventory = workspace.inventory()
        source = next(item for item in inventory["sources"] if item["key"] == book_key and item["version"] == book["version"])
        source.setdefault("printedPageLabels", {}).update(labels)
        write_json(workspace.inventory_path, inventory)
        for page in range(start, end + 1):
            record = page_record(workspace, book_key, page)
            if record:
                for block in record["blocks"]:
                    block["printedPageLabel"] = labels[str(page)]
                write_json(page_path(workspace, book_key, page), record)
        _write_extraction_artifact(workspace, book)
    _save_books(workspace, items)
    return chapter


def page_path(workspace: Workspace, book_key: str, page: int) -> Path:
    return workspace.inside(".local", "books", book_key, "pages", f"{page:04d}.json")


def page_record(workspace: Workspace, book_key: str, page: int) -> dict[str, Any] | None:
    path = page_path(workspace, book_key, page)
    if not path.exists():
        return None
    record = read_json(path)
    flags = record.get("flags", [])
    if any(flag.startswith("MinerU result ") for flag in flags):
        record["resultPrefix"] = next(flag.removeprefix("MinerU result ") for flag in flags if flag.startswith("MinerU result "))
        record["flags"] = [flag for flag in flags if not flag.startswith("MinerU result ")]
        write_json(path, record)
    return record


def chapter_state(workspace: Workspace, book_key: str, chapter_id: str) -> dict[str, Any]:
    book = _book(workspace, book_key)
    chapter = _chapter(book, chapter_id)
    pages = []
    for number in range(chapter["start"], chapter["end"] + 1):
        record = page_record(workspace, book_key, number)
        pages.append({"pageIndex": number, "status": record.get("review", {}).get("status", "pending") if record else "missing", "method": record.get("method") if record else None, "blockCount": len(record.get("blocks", [])) if record else 0, "flags": record.get("flags", []) if record else ["Chưa trích xuất"]})
    return {"book": book, "chapter": chapter, "pages": pages, "completed": sum(page["status"] != "missing" for page in pages), "total": len(pages)}


def process_chapter(workspace: Workspace, book_key: str, chapter_id: str, mineru_bin: str | None, tier: str = "standard", progress: Any = None, rerun: bool = False) -> dict[str, Any]:
    from .m0a_review import _load_result

    if tier not in {"standard", "basic", "flash"}:
        raise ContentToolError("Invalid OCR tier")
    state = chapter_state(workspace, book_key, chapter_id)
    book, chapter = state["book"], state["chapter"]
    pdf = _pdf(workspace, book)
    mineru_version = None
    if mineru_bin:
        version = subprocess.run([mineru_bin, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
        if version.returncode or "MinerU version: 4.0.12" not in version.stdout:
            raise ContentToolError("This workflow requires the tested local MinerU 4.0.12 runtime")
        mineru_version = "4.0.12"
    with pymupdf.open(pdf) as document:
        for number in range(chapter["start"], chapter["end"] + 1):
            old = page_record(workspace, book_key, number)
            if old and old.get("method") == "mineru" and old.get("blocks") and not any(block.get("text") for block in old["blocks"]) and not old.get("review", {}).get("edits"):
                old = None  # Repair cached MinerU pages created before content-to-text normalization.
            if old and (not rerun or old.get("review", {}).get("edits")):
                continue  # Manual edits always win over a later OCR run.
            if progress:
                progress(number, chapter["end"])
            native = native_page_blocks(document[number - 1], number, book_key, book["version"], book["sha256"], book["printedPageLabels"].get(str(number)))
            native_text = " ".join(block["text"] for block in native)
            method = "native-pymupdf"
            blocks = native
            flags: list[str] = []
            if len(native_text.strip()) < 50:
                if not mineru_bin:
                    flags.append("Ít native text; cần MinerU hoặc kiểm tra thủ công")
                else:
                    output = workspace.inside(".local", "books", book_key, "mineru", f"page-{number:04d}")
                    archives = sorted(output.rglob("*.zip"))
                    if not archives or rerun:
                        command = [mineru_bin, "parse", str(pdf), "--pages", str(number), "--output", str(output), "--format", "zip", "--tier", tier, "--ocr-mode", "ocr"]
                        run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=6 * 60 * 60, check=False)
                        if run.returncode:
                            raise ContentToolError(f"MinerU page {number} failed: {(run.stderr or run.stdout)[-1000:]}")
                        archives = sorted(output.rglob("*.zip"))
                    if not archives:
                        raise ContentToolError(f"MinerU page {number} did not produce a ZIP")
                    parsed, _, source_hash, result_hash = _load_result(workspace, pdf, archives[0])
                    if source_hash != book["sha256"] or number not in parsed:
                        raise ContentToolError(f"MinerU page {number} is missing or source changed")
                    method = "mineru"
                    blocks = []
                    for index, block in enumerate(parsed[number].get("blocks", []), start=1):
                        text = _mineru_text(block)
                        blocks.append({"id": f"{book_key}-{book['version']}-p{number:04d}-b{index:04d}", "text": text, "bbox": block.get("bbox"), "type": block.get("type", "text"), "physicalPageIndex": number, "printedPageLabel": book["printedPageLabels"].get(str(number)), "sourceSha256": book["sha256"], "sourceVersion": book["version"], "extractionMethod": method, "textSha256": hashlib.sha256(text.encode()).hexdigest()})
                    if not blocks:
                        flags.append("MinerU trả về trang không có block")
            if not blocks or sum(len(block.get("text", "")) for block in blocks) < 50:
                flags.append("Thiếu hoặc rất ít text; đối chiếu trang PDF")
            record = {"schemaVersion": 1, "bookKey": book_key, "pageIndex": number, "sourceSha256": book["sha256"], "method": method, "mineruVersion": mineru_version if method == "mineru" else None, "tier": tier if method == "mineru" else None, "resultSha256": result_hash if method == "mineru" else None, "blocks": blocks, "flags": flags, "review": {"status": "pending", "edits": {}}, "extractedAt": _now()}
            write_json(page_path(workspace, book_key, number), record)
            _write_extraction_artifact(workspace, book)
    return chapter_state(workspace, book_key, chapter_id)


def _write_extraction_artifact(workspace: Workspace, book: dict[str, Any]) -> None:
    pages = [page_record(workspace, book["key"], number) for number in range(1, book["pageCount"] + 1)]
    ready = [page for page in pages if page]
    blocks = []
    for page in ready:
        for index, block in enumerate(page["blocks"]):
            corrected = page.get("review", {}).get("edits", {}).get(str(index))
            copy = dict(block)
            if corrected is not None:
                copy["text"] = corrected
                copy["textSha256"] = hashlib.sha256(corrected.encode()).hexdigest()
            blocks.append(copy)
    write_json(workspace.inside("extracts", book["key"], f"{book['version']}.native.json"), {
        "schemaVersion": 2, "sourceKey": book["key"], "sourceVersion": book["version"],
        "sourceSha256": book["sha256"], "pageCount": book["pageCount"],
        "pageMethods": {str(page["pageIndex"]): page["method"] for page in ready},
        "reviewedPages": [page["pageIndex"] for page in ready if page.get("review", {}).get("status") == "accepted"],
        "blocks": blocks,
    })


def save_review(workspace: Workspace, book_key: str, number: int, action: str, edits: dict[str, str], duration: int = 0) -> dict[str, Any]:
    record = page_record(workspace, book_key, number)
    if record is None:
        raise ContentToolError("Extract the page before reviewing it")
    if action not in {"accepted", "needs-correction", "rejected"} or not isinstance(edits, dict) or any(not key.isdigit() or int(key) >= len(record["blocks"]) or not isinstance(value, str) for key, value in edits.items()):
        raise ContentToolError("Invalid review action or block edits")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0 or duration > 86400:
        raise ContentToolError("Invalid review time")
    review = record["review"]
    review.update({"status": action, "edits": edits, "savedAt": _now(), "totalReviewSeconds": review.get("totalReviewSeconds", 0) + duration})
    record.setdefault("history", []).append({"status": action, "edits": edits, "durationSeconds": duration, "at": review["savedAt"]})
    write_json(page_path(workspace, book_key, number), record)
    _write_extraction_artifact(workspace, _book(workspace, book_key))
    return record


def draft_path(workspace: Workspace, pack_key: str) -> Path:
    if not ID_PATTERN.fullmatch(pack_key):
        raise ContentToolError("Lesson pack key is invalid")
    return workspace.inside(".local", "lessons", f"{pack_key}.json")


def save_draft(workspace: Workspace, data: dict[str, Any]) -> dict[str, Any]:
    book = _book(workspace, str(data.get("bookKey", "")))
    chapter = _chapter(book, str(data.get("chapterId", "")))
    pack_key = str(data.get("packKey", ""))
    path = draft_path(workspace, pack_key)
    existing = read_json(path) if path.exists() else None
    if existing and (existing["bookKey"], existing["chapterId"]) != (book["key"], chapter["id"]):
        raise ContentToolError("Pack key belongs to another book or chapter")
    title, objective, claim = (str(data.get(field, "")).strip() for field in ("title", "learningObjective", "claim"))
    if len(title) < 3 or len(objective) < 5 or len(claim) < 5:
        raise ContentToolError("Lesson title, objective and source-grounded claim are required")
    outcome = str(data.get("outcomeCode", "")).strip()
    if data.get("domain") not in {"MATTER", "ENERGY", "LIVING", "EARTH_SKY"}:
        raise ContentToolError("Choose a valid content domain")
    grade = data.get("grade")
    if grade not in {8, 9} or isinstance(grade, bool):
        raise ContentToolError("Lesson grade must be 8 or 9")
    selected = data.get("pages", [])
    if not isinstance(selected, list) or not selected or any(isinstance(p, bool) or not isinstance(p, int) or p < chapter["start"] or p > chapter["end"] for p in selected):
        raise ContentToolError("Select reviewed pages from the chapter")
    for number in selected:
        record = page_record(workspace, book["key"], number)
        if not record or record.get("review", {}).get("status") != "accepted":
            raise ContentToolError(f"PDF page {number} must be accepted after OCR review")
    sections = data.get("sections", [])
    if not isinstance(sections, list) or not sections or any(not isinstance(s, dict) or not str(s.get("heading", "")).strip() or not str(s.get("content", "")).strip() for s in sections):
        raise ContentToolError("Add at least one titled Lesson section with content")
    exercise = data.get("basicExercises")
    if exercise is not None:
        if not isinstance(exercise, dict) or not ID_PATTERN.fullmatch(str(exercise.get("id", ""))):
            raise ContentToolError("BASIC_EXERCISE needs a stable step ID")
        if not isinstance(exercise.get("questions"), list) or not exercise["questions"]:
            raise ContentToolError("BASIC_EXERCISE needs a question")
        for question in exercise["questions"]:
            if not ID_PATTERN.fullmatch(str(question.get("id", ""))) or len(str(question.get("prompt", "")).strip()) < 3:
                raise ContentToolError("Exercise question ID or prompt is invalid")
            options = question.get("options", [])
            if not isinstance(options, list) or not 2 <= len(options) <= 6 or any(not ID_PATTERN.fullmatch(str(opt.get("id", ""))) or not str(opt.get("text", "")).strip() for opt in options):
                raise ContentToolError("Exercise needs 2–6 options with stable IDs")
            if question.get("correctOptionId") not in {opt["id"] for opt in options}:
                raise ContentToolError("Exercise answer must match an option ID")
        if isinstance(exercise.get("passThreshold"), bool) or not isinstance(exercise.get("passThreshold"), int) or not 1 <= exercise["passThreshold"] <= 100:
            raise ContentToolError("Exercise pass threshold must be 1–100")
    if data.get("license") not in {"ORIGINAL", "CC0", "PUBLIC_DOMAIN", "CC_BY", "CC_BY_SA", "SCHOOL_OWNED", "REFERENCE_ONLY", "CC_BY_NC", "CC_BY_ND", "CC_BY_NC_SA", "UNKNOWN"}:
        raise ContentToolError("Select the actual source license; local-processing permission is not publication permission")
    if not str(data.get("attribution", "")).strip():
        raise ContentToolError("Source attribution is required")
    clean = {**data, "title": title, "learningObjective": objective, "claim": claim, "outcomeCode": outcome, "pages": sorted(set(selected)), "savedAt": _now()}
    if outcome and str(data.get("subjectId", "")).strip():
        _write_pack(workspace, clean)
    write_json(path, clean)
    return clean


def _write_pack(workspace: Workspace, draft: dict[str, Any]) -> None:
    book = _book(workspace, draft["bookKey"])
    chapter = _chapter(book, draft["chapterId"])
    pack_key = draft["packKey"]
    pack_path = workspace.inside("packs", f"{pack_key}.json")
    relative = pack_path.relative_to(workspace.root).as_posix()
    source_id = book["key"]
    unit_id = f"{pack_key}-unit"
    claim_id = f"{pack_key}-claim"
    sections = "\n".join(f"<section><h2>{html.escape(str(section['heading']))}</h2><p>{html.escape(str(section['content'])).replace(chr(10), '<br>')}</p></section>" for section in draft["sections"])
    first_page = draft["pages"][0]
    record = page_record(workspace, source_id, first_page)
    if record is None:
        raise ContentToolError("Source page disappeared")
    existing_pack = read_json(pack_path) if pack_path.exists() else {}
    prior_sources = existing_pack.get("pack", {}).get("sources", [])
    prior_accessed = prior_sources[0].get("accessedAt") if prior_sources else None
    source = {"id": source_id, "title": book["title"], "author": book["author"], "accessedAt": prior_accessed or date.today().isoformat(), "license": draft["license"], "attribution": draft["attribution"], "authoritative": bool(draft.get("authoritative", False))}
    if draft.get("sourceUrl"):
        source["url"] = draft["sourceUrl"]
    old = existing_pack
    pack = {"key": pack_key, "title": draft["title"], "grade": draft["grade"], "domain": draft["domain"], "chapter": chapter["title"], "topic": str(draft.get("topic", chapter["title"])).strip(), "subjectId": draft["subjectId"], "outcomeCodes": [draft["outcomeCode"]], "synthetic": False, "sources": [source], "knowledgeUnits": [{"id": unit_id, "outcomeCodes": [draft["outcomeCode"]], "claims": [{"id": claim_id, "text": draft["claim"], "important": False, "sourceIds": [source_id]}], "terms": [], "misconceptions": []}], "lesson": {"learningObjective": draft["learningObjective"], "prerequisites": str(draft.get("prerequisites", "")), "content": sections, "materials": [], "questions": [], "labId": None}, "reviews": {}}
    if draft.get("basicExercises"):
        pack["lesson"]["basicExercises"] = draft["basicExercises"]
    previous_pack = old.get("pack", {})
    content_unchanged = {key: value for key, value in previous_pack.items() if key != "reviews"} == {key: value for key, value in pack.items() if key != "reviews"}
    if content_unchanged:
        pack["reviews"] = previous_pack.get("reviews", {})
    evidence = []
    for number in draft["pages"]:
        page = page_record(workspace, source_id, number)
        if page is None:
            raise ContentToolError(f"Missing extraction for page {number}")
        block_ids = ",".join(block["id"] for block in page["blocks"])
        marker = {"sourceId": source_id, "sourceVersion": book["version"], "sourceSha256": book["sha256"], "physicalPageIndex": number, "printedPageLabel": book["printedPageLabels"].get(str(number)), "extractionMethod": page["method"], "locator": f"PDF page {number}, blocks {block_ids or 'no-text'}"}
        evidence.append({**marker, "contentRef": "lesson.content"})
        evidence.append({**marker, "claimId": claim_id})
    if old.get("evidence") != evidence:
        pack["reviews"] = {}
        content_unchanged = False
    expected_ids = [("pack", pack_key, f"{relative}#pack"), ("source", source_id, f"source-inventory.json#source:{source_id}"), ("unit", unit_id, f"{relative}#unit:{unit_id}"), ("claim", claim_id, f"{relative}#claim:{claim_id}")]
    exercise = draft.get("basicExercises")
    if exercise:
        step = exercise["id"]
        expected_ids.append(("step", step, f"{relative}#step:{step}"))
        for question in exercise["questions"]:
            qid = question["id"]
            expected_ids.append(("question", qid, f"{relative}#step:{step}/question:{qid}"))
            for option in question["options"]:
                oid = option["id"]
                expected_ids.append(("option", oid, f"{relative}#step:{step}/question:{qid}/option:{oid}"))
    reserve_ids(workspace, expected_ids)
    write_json(pack_path, {"pack": pack, "evidence": evidence, "reviewLog": old.get("reviewLog", []) if content_unchanged else []})
    release_path = workspace.inside("release.json")
    release = read_json(release_path)
    release["namespace"] = "baseline"
    release["name"] = str(draft.get("releaseName") or f"{book['key']}-release")
    if relative not in release["packFiles"]:
        release["packFiles"].append(relative)
    write_json(release_path, release)


def save_formal_reviews(workspace: Workspace, pack_key: str, reviews: dict[str, Any]) -> None:
    path = workspace.inside("packs", f"{pack_key}.json")
    wrapper = read_json(path)
    if not isinstance(reviews, dict) or set(reviews) - set(REVIEW_KINDS):
        raise ContentToolError("Invalid formal review kinds")
    for kind, person in reviews.items():
        if not isinstance(person, dict) or not all(str(person.get(field, "")).strip() for field in ("name", "email", "at")):
            raise ContentToolError(f"{kind} needs an actual reviewer's name, email and timestamp")
    wrapper["pack"]["reviews"] = reviews
    wrapper["reviewLog"] = [{"kind": kind, "email": person["email"], "status": "approved"} for kind, person in reviews.items()]
    write_json(path, wrapper)


def export_status(workspace: Workspace) -> dict[str, Any]:
    drafts = []
    for path in workspace.inside(".local", "lessons").glob("*.json"):
        draft = read_json(path)
        pack_key = draft.get("packKey", path.stem)
        if not draft.get("outcomeCode"):
            drafts.append(f"{pack_key}: thiếu mã outcome đã xác minh trong BE")
        if not draft.get("subjectId"):
            drafts.append(f"{pack_key}: thiếu subjectId đã xác minh trong BE")
        if draft.get("license") not in {"ORIGINAL", "CC0", "PUBLIC_DOMAIN", "CC_BY", "CC_BY_SA", "SCHOOL_OWNED"}:
            drafts.append(f"{pack_key}: chưa xác minh giấy phép cho nội dung Lesson")
        if draft.get("license") not in {"ORIGINAL", "SCHOOL_OWNED"} and not draft.get("sourceUrl"):
            drafts.append(f"{pack_key}: thiếu URL nguồn cho giấy phép đã chọn")
        pack_path = workspace.inside("packs", f"{pack_key}.json")
        reviews = read_json(pack_path).get("pack", {}).get("reviews", {}) if pack_path.exists() else {}
        for kind in REVIEW_KINDS:
            if kind not in reviews:
                drafts.append(f"{pack_key}: missing formal {kind} review")
    if drafts:
        return {"ready": False, "blockers": drafts}
    release = read_json(workspace.inside("release.json"))
    if not release.get("packFiles"):
        return {"ready": False, "blockers": ["Chưa có Lesson pack đủ metadata để export"]}
    try:
        build_manifest(workspace, allow_unreviewed=True)
        path, digest = export_manifest(workspace)
        return {"ready": True, "manifest": str(path), "sha256": digest, "blockers": []}
    except ContentToolError as error:
        blockers = [str(error)]
        try:
            release = read_json(workspace.inside("release.json"))
            for relative in release.get("packFiles", []):
                pack = read_json(workspace.inside(relative)).get("pack", {})
                for kind in REVIEW_KINDS:
                    if kind not in pack.get("reviews", {}):
                        blockers.append(f"{pack.get('key', relative)}: missing formal {kind} review")
        except (ContentToolError, AttributeError, TypeError):
            pass
        return {"ready": False, "blockers": list(dict.fromkeys(blockers))}
