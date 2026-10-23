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
from .authoring_contract import validate_materials
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


def _toc_page_number(value: str, labels: dict[str, str], page_count: int) -> int | None:
    try:
        printed = int(re.sub(r"\D", "", value))
    except ValueError:
        return None
    exact = [int(page) for page, label in labels.items() if str(label).strip() == str(printed)]
    if len(exact) == 1:
        return exact[0]
    offsets = {int(page) - int(re.sub(r"\D", "", str(label))) for page, label in labels.items() if re.sub(r"\D", "", str(label))}
    if len(offsets) == 1:
        mapped = printed + next(iter(offsets))
        return mapped if 1 <= mapped <= page_count else None
    return None


def detect_toc(workspace: Workspace, book_key: str, *, pages: list[int] | None = None) -> dict[str, Any]:
    """Build an editable TOC proposal from PDF outlines, native text, and existing local OCR pages."""
    book = _book(workspace, book_key)
    page_indexes = pages or list(range(1, min(book["pageCount"], 24) + 1))
    if not isinstance(page_indexes, list) or not page_indexes or any(isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= min(book["pageCount"], 40) for page in page_indexes):
        raise ContentToolError("TOC pages must be within the first 40 PDF pages")
    sources: list[dict[str, Any]] = []
    texts: list[tuple[int, str, str]] = []
    with pymupdf.open(_pdf(workspace, book)) as document:
        for level, title, page in document.get_toc():
            if 1 <= page <= book["pageCount"]:
                sources.append({"kind": "pdf-outline", "physicalPageIndex": page, "title": title, "level": level})
        for number in page_indexes:
            native = "\n".join(block["text"] for block in native_page_blocks(document[number - 1], number, book_key, book["version"], book["sha256"], book["printedPageLabels"].get(str(number))))
            record = page_record(workspace, book_key, number)
            ocr = "\n".join(str(record.get("review", {}).get("edits", {}).get(str(i), block.get("text", ""))) for i, block in enumerate(record.get("blocks", []))) if record else ""
            text = ocr if len(ocr.strip()) > len(native.strip()) else native
            method = record.get("method") if record and text == ocr else "native-pymupdf"
            if text.strip():
                texts.append((number, text, str(method)))
                sources.append({"kind": "page-text", "physicalPageIndex": number, "method": method, "sourceSha256": book["sha256"]})
    pattern = re.compile(r"(?:^|\|)\s*(B[aà]i\s+\d+)\s*[|.:-]?\s*(.*?)\s*(?:\|\s*(\d{1,3})\s*)?(?:\||$)", re.IGNORECASE)
    chapter_pattern = re.compile(r"(?:^|\|)\s*(?:CHƯƠNG|CHUONG|Chương|Chuong)\s+([IVXLC]+|\d+)\s*[.:-]?\s*([^|\n]+)", re.IGNORECASE)
    chapters: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    glossary_printed_start: int | None = None
    for pdf_page, content, _method in texts:
        for raw in content.splitlines():
            line = raw.strip()
            if re.search(r"giải thích một số thuật ngữ|giai thich mot so thuat ng", line, re.IGNORECASE):
                numbers = re.findall(r"(?<!\d)(\d{1,3})(?!\d)", line)
                if numbers:
                    glossary_printed_start = int(numbers[-1])
                continue
            heading = chapter_pattern.search(line)
            if heading:
                key = f"chapter-{heading.group(1).lower()}"
                current = next((item for item in chapters if item["id"] == key), None)
                if current is None:
                    current = {"id": key, "title": f"Chương {heading.group(1)}. {heading.group(2).strip()}", "lessons": []}
                    chapters.append(current)
                continue
            lesson = pattern.search(line)
            if not lesson:
                continue
            title = re.sub(r"\s+", " ", lesson.group(2)).strip(" .|:-")
            printed = lesson.group(3)
            if not title or not printed:
                continue
            if current is None:
                current = {"id": "chapter-unassigned", "title": "Bài ngoài chương", "lessons": []}
                chapters.append(current)
            start = int(printed)
            identity = hashlib.sha256(f"{book_key}:{book['version']}:{start}".encode()).hexdigest()[:12]
            current["lessons"].append({"id": f"src-lesson-{identity}", "title": title, "printedStart": start, "printedEnd": None, "start": _toc_page_number(printed, book["printedPageLabels"], book["pageCount"]), "end": None, "tocPdfPage": pdf_page})
    flat = [lesson for chapter in chapters for lesson in chapter["lessons"]]
    for index, lesson in enumerate(flat):
        next_lesson = flat[index + 1] if index + 1 < len(flat) else None
        if next_lesson:
            lesson["printedEnd"] = next_lesson["printedStart"] - 1
            if lesson["start"] is not None and next_lesson["start"] is not None:
                lesson["end"] = next_lesson["start"] - 1
    for chapter in chapters:
        lesson_list = chapter["lessons"]
        if lesson_list and lesson_list[-1]["end"] is None:
            next_chapter = next((item for item in chapters[chapters.index(chapter) + 1:] if item["lessons"]), None)
            if next_chapter and next_chapter["lessons"][0]["start"] is not None and lesson_list[-1]["start"] is not None:
                lesson_list[-1]["end"] = next_chapter["lessons"][0]["start"] - 1
                lesson_list[-1]["printedEnd"] = next_chapter["lessons"][0]["printedStart"] - 1
            elif lesson_list[-1]["start"] is not None:
                glossary_pdf_start = _toc_page_number(str(glossary_printed_start), book["printedPageLabels"], book["pageCount"]) if glossary_printed_start else None
                lesson_list[-1]["end"] = glossary_pdf_start - 1 if glossary_pdf_start else book["pageCount"]
                if glossary_printed_start:
                    lesson_list[-1]["printedEnd"] = glossary_printed_start - 1
        chapter["start"] = lesson_list[0]["start"] if lesson_list else None
        chapter["end"] = lesson_list[-1]["end"] if lesson_list else None
        for lesson in lesson_list:
            lesson["chapterId"] = chapter["id"]
    mapping_evidence = [{"pdfPage": int(page), "printedPage": int(label)} for page, label in book["printedPageLabels"].items() if str(page).isdigit() and str(label).isdigit()]
    mapping_offsets = {item["pdfPage"] - item["printedPage"] for item in mapping_evidence}
    page_mapping = {"kind": "printed-to-pdf-offset", "offset": next(iter(mapping_offsets)), "evidence": mapping_evidence} if len(mapping_offsets) == 1 else {"kind": "explicit-labels", "evidence": mapping_evidence}
    return {"bookKey": book_key, "tree": chapters, "provenance": {"method": "pdf-outline-and-local-pdf-ocr-text", "sourceSha256": book["sha256"], "pagesInspected": page_indexes, "pageMapping": page_mapping, "glossaryPrintedStart": glossary_printed_start, "sources": sources}, "warnings": [] if flat else ["Không nhận diện được dòng Bài … tiêu đề … trang; OCR thêm các trang mục lục hoặc sửa cây thủ công."], "status": "proposed"}


def save_toc_tree(workspace: Workspace, book_key: str, tree: list[dict[str, Any]], provenance: dict[str, Any], *, confirmed: bool = True) -> dict[str, Any]:
    book = _book(workspace, book_key)
    if not isinstance(provenance, dict) or provenance.get("sourceSha256") != book["sha256"]:
        raise ContentToolError("TOC provenance must reference the imported PDF version")
    if not isinstance(tree, list) or not tree:
        raise ContentToolError("TOC tree must contain at least one chapter")
    seen_chapters: set[str] = set()
    seen_lessons: set[str] = set()
    clean_tree = []
    for chapter in tree:
        if not isinstance(chapter, dict):
            raise ContentToolError("Invalid TOC chapter")
        chapter_id, title = str(chapter.get("id", "")), str(chapter.get("title", "")).strip()
        start, end, lessons = chapter.get("start"), chapter.get("end"), chapter.get("lessons")
        if not ID_PATTERN.fullmatch(chapter_id) or chapter_id in seen_chapters or not title or isinstance(start, bool) or not isinstance(start, int) or isinstance(end, bool) or not isinstance(end, int) or start < 1 or end < start or end > book["pageCount"] or not isinstance(lessons, list) or not lessons:
            raise ContentToolError("Each TOC chapter needs a unique ID, title, PDF range, and Lessons")
        seen_chapters.add(chapter_id)
        clean_lessons = []
        prior_lesson_end = start - 1
        for lesson in lessons:
            if not isinstance(lesson, dict):
                raise ContentToolError("Invalid source Lesson")
            lesson_id, lesson_title = str(lesson.get("id", "")), str(lesson.get("title", "")).strip()
            lesson_start, lesson_end = lesson.get("start"), lesson.get("end")
            if not ID_PATTERN.fullmatch(lesson_id) or lesson_id in seen_lessons or not lesson_title or isinstance(lesson_start, bool) or not isinstance(lesson_start, int) or isinstance(lesson_end, bool) or not isinstance(lesson_end, int) or lesson_start < start or lesson_start <= prior_lesson_end or lesson_end < lesson_start or lesson_end > end:
                raise ContentToolError("Each source Lesson needs a unique stable ID and a PDF range inside its chapter")
            prior_lesson_end = lesson_end
            seen_lessons.add(lesson_id)
            clean_lessons.append({**lesson, "id": lesson_id, "title": lesson_title, "chapterId": chapter_id})
        normalized = {**chapter, "id": chapter_id, "title": title, "start": start, "end": end, "lessons": clean_lessons, "tocProvenance": provenance, "tocStatus": "confirmed" if confirmed else "proposed"}
        if confirmed:
            normalized["tocConfirmedAt"] = _now()
        else:
            normalized.pop("tocConfirmedAt", None)
        clean_tree.append(normalized)
    items = books(workspace)
    target = next(item for item in items if item["key"] == book_key)
    for chapter in clean_tree:
        existing = next((item for item in target["chapters"] if item["id"] == chapter["id"]), None)
        if existing and (existing["start"], existing["end"]) != (chapter["start"], chapter["end"]):
            raise ContentToolError("A confirmed chapter range is immutable; use a new chapter ID for changed PDF pages")
        if existing:
            old_lessons = {lesson["id"]: lesson for lesson in existing.get("lessons", [])}
            new_lessons = {lesson["id"]: lesson for lesson in chapter["lessons"]}
            if old_lessons and set(old_lessons) != set(new_lessons):
                raise ContentToolError("Confirmed source Lesson IDs are stable; use a new chapter ID for a changed TOC")
            if any((old_lessons[key].get("start"), old_lessons[key].get("end")) != (new_lessons[key]["start"], new_lessons[key]["end"]) for key in old_lessons):
                raise ContentToolError("A confirmed source Lesson range is immutable")
            if confirmed:
                existing.update(chapter)
        else:
            target["chapters"].append(chapter)
    _save_books(workspace, items)
    return {"book": target, "tree": clean_tree}


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
        has_text = bool(record and any(str(block.get("text", "")).strip() for block in record.get("blocks", [])))
        pages.append({"pageIndex": number, "status": record.get("review", {}).get("status", "pending") if has_text else "empty" if record else "missing", "method": record.get("method") if record else None, "blockCount": len(record.get("blocks", [])) if record else 0, "flags": record.get("flags", []) if record else ["Chưa trích xuất"]})
    lesson_drafts = []
    for path in workspace.inside(".local", "lessons").glob("*.json"):
        draft = read_json(path)
        if draft.get("bookKey") == book_key and draft.get("chapterId") == chapter_id:
            lesson_drafts.append(str(draft.get("packKey") or path.stem))
    return {
        "book": book,
        "chapter": chapter,
        "pages": pages,
        "completed": sum(page["status"] not in {"missing", "empty"} for page in pages),
        "total": len(pages),
        "lessonDrafts": sorted(lesson_drafts),
    }


def _run_mineru(mineru_bin: str, args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    entry = "import sys; from mineru.kit.main import main; main()"
    executable = Path(mineru_bin)
    if executable.name.lower() in {"python.exe", "python"}:
        command = [mineru_bin, "-c", entry, *args]
    else:
        command = [mineru_bin, *args]
    run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    if run.returncode and "uv trampoline failed to canonicalize script path" in (run.stderr + run.stdout).lower():
        python = executable.with_name("python.exe")
        if python.is_file():
            run = subprocess.run([str(python), "-c", entry, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    return run


def _page_batches(numbers: list[int], limit: int = 20) -> list[list[int]]:
    batches: list[list[int]] = []
    for number in sorted(set(numbers)):
        if not batches or number != batches[-1][-1] + 1 or len(batches[-1]) >= limit:
            batches.append([])
        batches[-1].append(number)
    return batches


def process_chapter(workspace: Workspace, book_key: str, chapter_id: str, mineru_bin: str | None, tier: str = "standard", progress: Any = None, rerun: bool = False, page_range: tuple[int, int] | None = None) -> dict[str, Any]:
    from .m0a_review import _load_result

    if tier not in {"standard", "basic", "flash"}:
        raise ContentToolError("Invalid OCR tier")
    if chapter_id == "__pdf_pages__":
        book = _book(workspace, book_key)
        chapter = {"id": chapter_id, "title": "Selected PDF pages", "start": 1, "end": book["pageCount"]}
        state = None
    else:
        state = chapter_state(workspace, book_key, chapter_id)
        book, chapter = state["book"], state["chapter"]
    start, end = page_range or (chapter["start"], chapter["end"])
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or start < chapter["start"] or end > chapter["end"] or end < start:
        raise ContentToolError("OCR page range is outside the selected chapter")
    pdf = _pdf(workspace, book)
    mineru_version = None
    if mineru_bin:
        version = _run_mineru(mineru_bin, ["--version"], timeout=30)
        if version.returncode or "MinerU version: 4.0.12" not in version.stdout:
            raise ContentToolError("This workflow requires the tested local MinerU 4.0.12 runtime")
        mineru_version = "4.0.12"
    pending_ocr: list[int] = []
    native_records: dict[int, dict[str, Any]] = {}
    with pymupdf.open(pdf) as document:
        for number in range(start, end + 1):
            old = page_record(workspace, book_key, number)
            if old and old.get("method") == "mineru" and old.get("blocks") and not any(block.get("text") for block in old["blocks"]) and not old.get("review", {}).get("edits"):
                old = None  # Repair cached MinerU pages created before content-to-text normalization.
            missing_ocr = bool(mineru_bin and old and old.get("method") == "native-pymupdf" and not old.get("blocks") and not old.get("review", {}).get("edits"))
            if old and not missing_ocr and (not rerun or old.get("review", {}).get("status") == "accepted" or old.get("review", {}).get("edits")):
                continue  # Manual edits always win over a later OCR run.
            if progress:
                progress(number, chapter["end"])
            native = native_page_blocks(document[number - 1], number, book_key, book["version"], book["sha256"], book["printedPageLabels"].get(str(number)))
            native_text = " ".join(block["text"] for block in native)
            flags: list[str] = []
            if len(native_text.strip()) < 50 and mineru_bin:
                pending_ocr.append(number)
                continue
            if len(native_text.strip()) < 50:
                flags.append("Ít native text; cần MinerU hoặc kiểm tra thủ công")
            if not native or len(native_text.strip()) < 50:
                flags.append("Thiếu hoặc rất ít text; đối chiếu trang PDF")
            native_records[number] = {"schemaVersion": 1, "bookKey": book_key, "pageIndex": number, "sourceSha256": book["sha256"], "method": "native-pymupdf", "mineruVersion": None, "tier": None, "resultSha256": None, "blocks": native, "flags": flags, "review": {"status": "pending", "edits": {}}, "extractedAt": _now()}
    for number, record in native_records.items():
        write_json(page_path(workspace, book_key, number), record)
    if native_records:
        _write_extraction_artifact(workspace, book)
    # Batch contiguous missing OCR pages, capped so a crash loses at most one small batch.
    for batch in _page_batches(pending_ocr, limit=20):
        if progress:
            progress(batch[0], chapter["end"])
        batch_key = hashlib.sha256(",".join(map(str, batch)).encode()).hexdigest()[:8]
        output = workspace.inside(".local", "books", book_key, "mineru", f"batch-{batch[0]:04d}-{batch[-1]:04d}-{batch_key}")
        archives = [] if rerun else sorted(output.rglob("*.zip"))
        parsed: dict[int, dict[str, Any]] = {}
        result_hash = ""
        source_hash = ""
        for archive in archives:
            try:
                candidate, _, candidate_source_hash, candidate_result_hash = _load_result(workspace, pdf, archive)
                if candidate_source_hash == book["sha256"] and set(batch).issubset(candidate):
                    parsed, source_hash, result_hash = candidate, candidate_source_hash, candidate_result_hash
                    break
            except ContentToolError:
                continue
        if not parsed:
            if output.exists():
                output = output.with_name(output.name + f"-retry-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}")
            command = [str(pdf), "--pages", ",".join(map(str, batch)), "--output", str(output), "--format", "zip", "--tier", tier, "--ocr-mode", "ocr"]
            run = _run_mineru(mineru_bin or "", ["parse", *command], timeout=6 * 60 * 60)
            if run.returncode:
                raise ContentToolError(f"MinerU pages {batch[0]}–{batch[-1]} failed: {(run.stderr or run.stdout)[-1000:]}")
            archives = sorted(output.rglob("*.zip"))
            if not archives:
                raise ContentToolError(f"MinerU pages {batch[0]}–{batch[-1]} did not produce a ZIP")
            parsed, _, source_hash, result_hash = _load_result(workspace, pdf, archives[0])
        if source_hash != book["sha256"] or not set(batch).issubset(parsed):
            raise ContentToolError(f"MinerU batch {batch[0]}–{batch[-1]} is incomplete or its source changed")
        for number in batch:
            blocks = []
            for index, block in enumerate(parsed[number].get("blocks", []), start=1):
                text = _mineru_text(block)
                blocks.append({"id": f"{book_key}-{book['version']}-p{number:04d}-b{index:04d}", "text": text, "bbox": block.get("bbox"), "type": block.get("type", "text"), "physicalPageIndex": number, "printedPageLabel": book["printedPageLabels"].get(str(number)), "sourceSha256": book["sha256"], "sourceVersion": book["version"], "extractionMethod": "mineru", "textSha256": hashlib.sha256(text.encode()).hexdigest()})
            flags = []
            if not blocks:
                flags.append("MinerU trả về trang không có block")
            if not blocks or sum(len(block.get("text", "")) for block in blocks) < 50:
                flags.append("Thiếu hoặc rất ít text; đối chiếu trang PDF")
            write_json(page_path(workspace, book_key, number), {"schemaVersion": 1, "bookKey": book_key, "pageIndex": number, "sourceSha256": book["sha256"], "method": "mineru", "mineruVersion": mineru_version, "tier": tier, "resultSha256": result_hash, "blocks": blocks, "flags": flags, "review": {"status": "pending", "edits": {}}, "extractedAt": _now()})
        _write_extraction_artifact(workspace, book)
    if state is None:
        records = [page_record(workspace, book_key, number) for number in range(start, end + 1)]
        return {"book": book, "chapter": chapter, "completed": sum(bool(record and any(str(block.get("text", "")).strip() for block in record.get("blocks", []))) for record in records), "total": end - start + 1, "pages": records}
    return chapter_state(workspace, book_key, chapter_id)


def process_pdf_pages(workspace: Workspace, book_key: str, pages: list[int], mineru_bin: str | None, tier: str = "standard", progress: Any = None, rerun: bool = False) -> dict[str, Any]:
    if not isinstance(pages, list) or not pages or any(isinstance(page, bool) or not isinstance(page, int) for page in pages):
        raise ContentToolError("Select one or more PDF pages")
    selected = sorted(set(pages))
    book = _book(workspace, book_key)
    if selected[0] < 1 or selected[-1] > book["pageCount"] or len(selected) != selected[-1] - selected[0] + 1:
        raise ContentToolError("PDF page OCR range must be contiguous and inside the book")
    return process_chapter(workspace, book_key, "__pdf_pages__", mineru_bin, tier, progress, rerun, (selected[0], selected[-1]))


def process_lesson(workspace: Workspace, book_key: str, lesson_id: str, mineru_bin: str | None, tier: str = "standard", progress: Any = None, rerun: bool = False) -> dict[str, Any]:
    book = _book(workspace, book_key)
    for chapter in book.get("chapters", []):
        lesson = next((item for item in chapter.get("lessons", []) if item.get("id") == lesson_id), None)
        if lesson:
            state = process_chapter(workspace, book_key, chapter["id"], mineru_bin, tier, progress, rerun, (lesson["start"], lesson["end"]))
            state["pages"] = [page for page in state["pages"] if lesson["start"] <= page["pageIndex"] <= lesson["end"]]
            state["completed"] = sum(page["status"] not in {"missing", "empty"} for page in state["pages"])
            state["total"] = len(state["pages"])
            state["lesson"] = lesson
            return state
    raise ContentToolError(f"Unknown source Lesson {lesson_id}")


def _page_text_characters(record: dict[str, Any] | None) -> int:
    if not isinstance(record, dict):
        return 0
    edits = record.get("review", {}).get("edits", {})
    return sum(len(str(edits.get(str(index), block.get("text", ""))).strip()) for index, block in enumerate(record.get("blocks", [])) if isinstance(block, dict))


def whole_book_report(workspace: Workspace, book_key: str, *, processing: dict[str, Any] | None = None, save: bool = True) -> dict[str, Any]:
    """Report page mapping and extraction coverage without treating OCR as reviewed content."""
    book = _book(workspace, book_key)
    page_owners: dict[int, list[str]] = {}
    lesson_items: list[dict[str, Any]] = []
    chapters: list[dict[str, Any]] = []
    seen_lessons: set[str] = set()
    for chapter in sorted(book.get("chapters", []), key=lambda item: (item.get("start", 0), item.get("id", ""))):
        if not chapter.get("lessons"):
            continue
        chapter_lessons = []
        for lesson in chapter.get("lessons", []):
            lesson_id = str(lesson.get("id", ""))
            if lesson_id in seen_lessons:
                continue
            seen_lessons.add(lesson_id)
            start, end = lesson.get("start"), lesson.get("end")
            valid = isinstance(start, int) and not isinstance(start, bool) and isinstance(end, int) and not isinstance(end, bool) and 1 <= start <= end <= book["pageCount"]
            pages = list(range(start, end + 1)) if valid else []
            for number in pages:
                page_owners.setdefault(number, []).append(lesson_id)
            item = {
                "id": lesson_id, "title": lesson.get("title", ""), "chapterId": chapter["id"],
                "chapterTitle": chapter["title"], "pdfPageRange": {"start": start, "end": end},
                "printedPageRange": {"start": lesson.get("printedStart"), "end": lesson.get("printedEnd")},
                "tocStatus": "confirmed" if chapter.get("tocConfirmedAt") else chapter.get("tocStatus", "proposed"),
                "mappingValid": valid,
            }
            lesson_items.append(item)
            chapter_lessons.append(item)
        if chapter_lessons:
            chapters.append({"id": chapter["id"], "title": chapter["title"], "pdfPageRange": {"start": chapter.get("start"), "end": chapter.get("end")}, "tocStatus": "confirmed" if chapter.get("tocConfirmedAt") else chapter.get("tocStatus", "proposed"), "lessonCount": len(chapter_lessons), "lessons": chapter_lessons})
    mapped = set(page_owners)
    overlaps = {number: owners for number, owners in page_owners.items() if len(owners) > 1}
    standalone_ranges = []
    standalone_overlaps = []
    for chapter in book.get("chapters", []):
        if chapter.get("lessons"):
            continue
        start, end = chapter.get("start"), chapter.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end <= book["pageCount"]:
            continue
        page_set = set(range(start, end + 1))
        standalone_ranges.append({"id": chapter["id"], "title": chapter["title"], "pdfPageRange": {"start": start, "end": end}, "includedInWholeBookLessonMap": False})
        intersecting = sorted(page_set & mapped)
        if intersecting:
            standalone_overlaps.append({"chapterId": chapter["id"], "pdfPages": intersecting, "lessonIds": sorted({owner for page in intersecting for owner in page_owners[page]})})
    records = {number: page_record(workspace, book_key, number) for number in range(1, book["pageCount"] + 1)}
    text_characters = {number: _page_text_characters(record) for number, record in records.items()}
    has_text = {number for number, length in text_characters.items() if length > 0}
    low_text = sorted(number for number in mapped if 0 < text_characters[number] < 50)
    mapped_text = mapped & has_text
    failed_lessons = (processing or {}).get("lessons", {})
    failed_lesson_ids = {lesson_id for lesson_id, entry in failed_lessons.items() if entry.get("status") in {"failed", "blocked", "partial"} and entry.get("error")}
    no_text = mapped - has_text
    failed_pages = sorted(number for number in no_text if any(owner in failed_lesson_ids for owner in page_owners[number]) or (records[number] is not None))
    pending_pages = sorted(no_text - set(failed_pages))
    unmapped = sorted(set(range(1, book["pageCount"] + 1)) - mapped)
    ranges = lambda values: _compress_pages(values)
    errors = [{"lessonId": lesson_id, "error": entry.get("error"), "status": entry.get("status")} for lesson_id, entry in failed_lessons.items() if entry.get("status") in {"failed", "blocked", "partial"} and entry.get("error")]
    incomplete_lesson_ids = sorted({owner for number in mapped if text_characters[number] < 50 for owner in page_owners[number]})
    all_mapped_text = mapped.issubset(has_text) and not low_text and not overlaps and all(item["mappingValid"] for item in lesson_items)
    for item in lesson_items:
        item_pages = range(item["pdfPageRange"]["start"], item["pdfPageRange"]["end"] + 1) if item["mappingValid"] else []
        item["extractionStatus"] = "complete" if item["mappingValid"] and all(text_characters[number] >= 50 for number in item_pages) else "incomplete"
    report = {
        "schemaVersion": 1, "kind": "whole-book-processing-report",
        "book": {"key": book_key, "title": book["title"], "version": book["version"], "sha256": book["sha256"]},
        "status": "complete" if all_mapped_text and not errors else "partial" if mapped_text or lesson_items else "not_started",
        "totalPdfPages": book["pageCount"], "formalChapterCount": sum(chapter["id"] != "chapter-unassigned" for chapter in chapters),
        "unassignedLessonCount": sum(chapter["id"] == "chapter-unassigned" for chapter in chapters for _ in chapter["lessons"]),
        "lessonCount": len(lesson_items), "mappedPageCount": len(mapped), "completedPageCount": len(mapped_text),
        "failedPageCount": len(failed_pages), "failedPages": failed_pages, "failedPageRanges": ranges(failed_pages),
        "pendingPageCount": len(pending_pages), "pendingPages": pending_pages, "pendingPageRanges": ranges(pending_pages),
        "lowTextPageCount": len(low_text), "lowTextPages": low_text, "lowTextPageRanges": ranges(low_text),
        "incompletePageCount": len(set(pending_pages) | set(failed_pages) | set(low_text)), "incompleteLessonIds": incomplete_lesson_ids,
        "unmappedPageCount": len(unmapped), "unmappedPages": unmapped, "unmappedPageRanges": ranges(unmapped),
        "overlaps": [{"pdfPage": number, "lessonIds": owners} for number, owners in sorted(overlaps.items())],
        "standaloneRangesExcluded": standalone_ranges, "standaloneRangeOverlaps": standalone_overlaps,
        "chapters": chapters, "lessons": lesson_items, "processingErrors": errors,
        "unconfirmedLessonIds": [item["id"] for item in lesson_items if item["tocStatus"] != "confirmed"],
        "updatedAt": _now(),
    }
    if save:
        path = workspace.inside("reports", f"{book_key}-whole-book-processing.json")
        report["reportPath"] = str(path)
        write_json(path, report)
    return report


def _compress_pages(numbers: list[int]) -> list[dict[str, int]]:
    if not numbers:
        return []
    result = []
    start = prior = numbers[0]
    for number in numbers[1:]:
        if number == prior + 1:
            prior = number
            continue
        result.append({"start": start, "end": prior})
        start = prior = number
    result.append({"start": start, "end": prior})
    return result


def process_book(workspace: Workspace, book_key: str, mineru_bin: str | None, tier: str = "standard", progress: Any = None, rerun: bool = False) -> dict[str, Any]:
    """Process mapped Lesson pages in resumable chapter batches; every page is a checkpoint."""
    book = _book(workspace, book_key)
    checkpoint_path = workspace.inside(".local", "books", book_key, "processing.json")
    checkpoint = read_json(checkpoint_path) if checkpoint_path.exists() else {}
    if checkpoint.get("sourceSha256") != book["sha256"]:
        checkpoint = {"schemaVersion": 1, "bookKey": book_key, "sourceSha256": book["sha256"], "lessons": {}}
    checkpoint["status"] = "running"
    checkpoint["startedAt"] = checkpoint.get("startedAt") or _now()
    checkpoint["updatedAt"] = _now()
    write_json(checkpoint_path, checkpoint)
    claimed: dict[int, list[str]] = {}
    lesson_rows: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for chapter in sorted(book.get("chapters", []), key=lambda item: (item.get("start", 0), item.get("id", ""))):
        for lesson in chapter.get("lessons", []):
            lesson_id, start, end = lesson.get("id"), lesson.get("start"), lesson.get("end")
            entry = checkpoint["lessons"].setdefault(lesson_id, {"status": "pending", "attempts": 0})
            lesson_rows.append((chapter, lesson, entry))
            if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or not 1 <= start <= end <= book["pageCount"]:
                entry.update({"status": "blocked", "error": "Invalid or out-of-book PDF page range", "updatedAt": _now()})
                continue
            entry["pdfPageRange"] = {"start": start, "end": end}
            for number in range(start, end + 1):
                claimed.setdefault(number, []).append(lesson_id)
    conflicted = {number for number, owners in claimed.items() if len(owners) > 1}
    for chapter, lesson, entry in lesson_rows:
        start, end = lesson.get("start"), lesson.get("end")
        if isinstance(start, int) and isinstance(end, int):
            overlap_pages = [number for number in range(start, end + 1) if number in conflicted]
            if overlap_pages:
                entry.update({"status": "blocked", "error": f"Overlapping Lesson ranges at PDF pages {overlap_pages}", "updatedAt": _now()})
            elif entry.get("status") == "blocked" and entry.get("error") == "Invalid or out-of-book PDF page range":
                continue
            else:
                entry.update({"status": "running", "attempts": entry.get("attempts", 0) + 1, "updatedAt": _now()})
                entry.pop("error", None)
                entry.pop("failedAt", None)
    write_json(checkpoint_path, checkpoint)

    def refresh_lesson(chapter: dict[str, Any], lesson: dict[str, Any], entry: dict[str, Any]) -> None:
        start, end = lesson["start"], lesson["end"]
        records = [page_record(workspace, book_key, number) for number in range(start, end + 1)]
        completed = sum(_page_text_characters(record) >= 50 for record in records)
        entry.update({"completedPages": completed, "totalPages": end - start + 1, "updatedAt": _now()})
        if entry.get("status") != "blocked":
            if completed == end - start + 1:
                entry["status"] = "completed"
                entry["finishedAt"] = _now()
                entry.pop("error", None)
                entry.pop("failedAt", None)
                entry.pop("currentPdfPage", None)
            elif not entry.get("error"):
                entry["status"] = "partial" if completed else "running"

    # Process only mapped pages, in <=20-page contiguous chunks. A single failed
    # chunk does not prevent later chapters from being attempted on this run.
    for chapter in sorted(book.get("chapters", []), key=lambda item: (item.get("start", 0), item.get("id", ""))):
        chapter_rows = [(lesson, entry) for row_chapter, lesson, entry in lesson_rows if row_chapter["id"] == chapter["id"] and entry.get("status") != "blocked"]
        mapped_pages = sorted({number for lesson, _ in chapter_rows for number in range(lesson["start"], lesson["end"] + 1) if number not in conflicted})
        for contiguous in _page_batches(mapped_pages, limit=20):
            for lesson, entry in chapter_rows:
                if lesson["start"] <= contiguous[-1] and contiguous[0] <= lesson["end"]:
                    entry["currentPdfPage"] = contiguous[0]
                    entry["updatedAt"] = _now()
            write_json(checkpoint_path, checkpoint)
            try:
                def on_page(number: int, _chapter_end: int) -> None:
                    for lesson, entry in chapter_rows:
                        if lesson["start"] <= number <= lesson["end"]:
                            entry["currentPdfPage"] = number
                            entry["updatedAt"] = _now()
                    write_json(checkpoint_path, checkpoint)
                    if progress:
                        progress(number, book["pageCount"])
                process_chapter(workspace, book_key, chapter["id"], mineru_bin, tier, on_page, rerun, (contiguous[0], contiguous[-1]))
            except Exception as error:
                affected = [(lesson, entry) for lesson, entry in chapter_rows if lesson["start"] <= contiguous[-1] and contiguous[0] <= lesson["end"]]
                for lesson, entry in affected:
                    refresh_lesson(chapter, lesson, entry)
                    if entry.get("status") != "completed":
                        entry.update({"status": "partial" if entry.get("completedPages", 0) else "failed", "error": str(error), "failedAt": _now()})
                if progress:
                    progress(contiguous[-1], book["pageCount"])
            for lesson, entry in chapter_rows:
                refresh_lesson(chapter, lesson, entry)
            checkpoint["updatedAt"] = _now()
            write_json(checkpoint_path, checkpoint)
    for chapter, lesson, entry in lesson_rows:
        if entry.get("status") in {"blocked", "completed"}:
            continue
        refresh_lesson(chapter, lesson, entry)
        if entry.get("status") != "completed":
            entry["status"] = "partial" if entry.get("completedPages", 0) else "failed"
            start, end = lesson["start"], lesson["end"]
            insufficient = [number for number in range(start, end + 1) if _page_text_characters(page_record(workspace, book_key, number)) < 50]
            entry.setdefault("error", f"Extraction incomplete; pages with under 50 text characters: {insufficient}")
            entry.setdefault("failedAt", _now())
            entry["updatedAt"] = _now()
    checkpoint["status"] = "complete" if lesson_rows and all(entry.get("status") == "completed" for _, _, entry in lesson_rows) else "partial"
    checkpoint["finishedAt"] = _now()
    checkpoint["updatedAt"] = _now()
    write_json(checkpoint_path, checkpoint)
    report = whole_book_report(workspace, book_key, processing=checkpoint)
    return {"checkpoint": checkpoint, "report": report}


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
    if existing and existing.get("sourceLessonId") and existing["sourceLessonId"] != data.get("sourceLessonId"):
        raise ContentToolError("A saved draft's source Lesson identity is immutable")
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
    source_lesson_id = data.get("sourceLessonId")
    source_lesson = next((lesson for item in book.get("chapters", []) if item["id"] == chapter["id"] for lesson in item.get("lessons", []) if lesson.get("id") == source_lesson_id), None) if source_lesson_id else None
    if source_lesson_id and source_lesson is None:
        raise ContentToolError("Draft source Lesson does not belong to the selected chapter")
    if source_lesson and any(number < source_lesson["start"] or number > source_lesson["end"] for number in selected):
        raise ContentToolError("Draft pages must stay inside the selected source Lesson range")
    if source_lesson and sorted(set(selected)) != list(range(source_lesson["start"], source_lesson["end"] + 1)):
        raise ContentToolError("A source Lesson draft must include every accepted page in its confirmed range")
    for number in selected:
        record = page_record(workspace, book["key"], number)
        if not record or record.get("review", {}).get("status") != "accepted":
            raise ContentToolError(f"PDF page {number} must be accepted after OCR review")
    sections = data.get("sections", [])
    if not isinstance(sections, list) or not sections or any(not isinstance(s, dict) or not str(s.get("heading", "")).strip() or not str(s.get("content", "")).strip() for s in sections):
        raise ContentToolError("Add at least one titled Lesson section with content")
    units = data.get("knowledgeUnits", [])
    if not isinstance(units, list) or any(
        not isinstance(unit, dict)
        or not ID_PATTERN.fullmatch(str(unit.get("id", "")))
        or not str(unit.get("title", "")).strip()
        or not isinstance(unit.get("claims", []), list)
        or not unit.get("claims")
        or any(not ID_PATTERN.fullmatch(str(claim.get("id", ""))) or not str(claim.get("text", "")).strip() for claim in unit.get("claims", []))
        for unit in units
    ):
        raise ContentToolError("Knowledge units need stable IDs, a title and valid claims")
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
    materials = validate_materials(data.get("materials", []))
    source_artifact = str(data.get("sourceArtifactVersionId", "")).strip()
    if source_artifact and not re.fullmatch(r"[a-z0-9]{20,40}", source_artifact):
        raise ContentToolError("Source artifact must be a pinned AssetVersion ID")
    clean = {**data, "title": title, "learningObjective": objective, "claim": claim, "outcomeCode": outcome, "pages": sorted(set(selected)), "materials": materials, "sourceArtifactVersionId": source_artifact, "savedAt": _now()}
    if source_lesson:
        clean["sourceLesson"] = {"id": source_lesson["id"], "title": source_lesson["title"], "chapterId": chapter["id"], "pdfPageRange": {"start": source_lesson["start"], "end": source_lesson["end"]}, "printedPageRange": {"start": source_lesson.get("printedStart"), "end": source_lesson.get("printedEnd")}, "tocProvenance": source_lesson.get("tocProvenance") or chapter.get("tocProvenance"), "sourceSha256": book["sha256"], "sourceVersion": book["version"]}
    if outcome and str(data.get("subjectId", "")).strip():
        _write_pack(workspace, clean)
    if existing and any(existing.get(key) != clean.get(key) for key in ("outcomeCode", "grade", "domain", "materials", "sourceArtifactVersionId")):
        from .authoring_contract import verification_path
        verification_path(workspace, pack_key).unlink(missing_ok=True)
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
    if draft.get("sourceArtifactVersionId"):
        source["artifactVersionId"] = draft["sourceArtifactVersionId"]
    old = existing_pack
    authored_units = draft.get("knowledgeUnits") or [{"id": unit_id, "claims": [{"id": claim_id, "text": draft["claim"]}], "terms": [], "misconceptions": []}]
    knowledge_units = [{"id": unit["id"], "outcomeCodes": [draft["outcomeCode"]], "claims": [{"id": claim["id"], "text": claim["text"], "important": False, "sourceIds": [source_id]} for claim in unit.get("claims", [])], "terms": unit.get("terms", []), "misconceptions": unit.get("misconceptions", [])} for unit in authored_units]
    pack = {"key": pack_key, "title": draft["title"], "grade": draft["grade"], "domain": draft["domain"], "chapter": chapter["title"], "topic": str(draft.get("topic", chapter["title"])).strip(), "subjectId": draft["subjectId"], "outcomeCodes": [draft["outcomeCode"]], "synthetic": False, "sources": [source], "knowledgeUnits": knowledge_units, "lesson": {"learningObjective": draft["learningObjective"], "prerequisites": str(draft.get("prerequisites", "")), "content": sections, "materials": draft.get("materials", []), "questions": [], "labId": None}, "reviews": {}}
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
        for unit in knowledge_units:
            for claim in unit["claims"]:
                evidence.append({**marker, "claimId": claim["id"]})
    if old.get("evidence") != evidence:
        pack["reviews"] = {}
        content_unchanged = False
    expected_ids = [("pack", pack_key, f"{relative}#pack"), ("source", source_id, f"source-inventory.json#source:{source_id}")]
    for unit in knowledge_units:
        expected_ids.append(("unit", unit["id"], f"{relative}#unit:{unit['id']}"))
        for claim in unit["claims"]:
            expected_ids.append(("claim", claim["id"], f"{relative}#claim:{claim['id']}"))
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


def export_status(workspace: Workspace, *, write_manifest: bool = True) -> dict[str, Any]:
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
        if not write_manifest:
            return {"ready": True, "blockers": []}
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
