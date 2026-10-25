from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import webbrowser
import zipfile
from email import policy
from email.parser import BytesParser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .workspace import ContentToolError, Workspace, read_json, sha256_file, write_json


_PAGE = re.compile(r"^/(?:api/page|source)/(\d+)$")


def _multipart_text(part: Any) -> str:
    """Decode browser FormData text fields as UTF-8 when no charset is sent."""
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    return payload.decode(part.get_content_charset() or "utf-8").strip()


_HTML = r'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NexaLab · OCR Review</title>
<style>
:root{font:15px/1.45 system-ui,sans-serif;color:#17212d;background:#f4f6f8}*{box-sizing:border-box}body{margin:0}header{height:64px;background:white;border-bottom:1px solid #d8dee7;display:flex;align-items:center;gap:18px;padding:0 20px;position:sticky;top:0;z-index:2}h1{font-size:18px;margin:0}.muted{color:#687386;font-size:13px}.toolbar{display:flex;gap:8px;align-items:center;margin-left:auto}button,select,input{font:inherit;border:1px solid #cbd3df;border-radius:7px;background:white;padding:8px 11px;color:inherit}button{cursor:pointer}button.primary{background:#176b55;color:white;border-color:#176b55}button.reject{color:#a11b28}.layout{display:grid;grid-template-columns:245px minmax(360px,1fr) minmax(420px,1fr);gap:12px;padding:12px;height:calc(100vh - 64px)}aside,.panel{background:#fff;border:1px solid #d8dee7;border-radius:10px;min-height:0}.sidebar{overflow:auto;padding:12px}.sidebar h2,.panel h2{font-size:14px;margin:0 0 10px}.page-item{display:block;width:100%;text-align:left;margin:5px 0;padding:8px}.page-item.active{outline:2px solid #176b55}.status{font-size:12px;color:#687386;display:block}.source{overflow:auto;display:flex;align-items:flex-start;justify-content:center;padding:10px;background:#e9edf2}.source img{width:100%;height:auto;object-fit:contain;box-shadow:0 1px 5px #8090a044}.panel{overflow:auto;padding:14px}.block{border:1px solid #e0e5ec;border-radius:8px;margin:8px 0;padding:8px}.block label{display:flex;justify-content:space-between;color:#586577;font-size:12px;margin-bottom:6px}.block textarea{display:block;width:100%;min-height:70px;resize:vertical;border:1px solid #d5dbe4;border-radius:5px;padding:8px;font:14px/1.5 ui-monospace,monospace}.empty{color:#687386;padding:20px;text-align:center}.notice{background:#fff6d9;padding:8px 10px;border-radius:6px;font-size:12px;margin:8px 0}.count{font-variant-numeric:tabular-nums}@media(max-width:1100px){.layout{grid-template-columns:190px 1fr;height:auto;min-height:calc(100vh - 64px)}.source{grid-column:2;grid-row:1;max-height:55vh}.panel{grid-column:2}.sidebar{grid-row:1 / span 2}}@media(max-width:700px){header{height:auto;min-height:64px;flex-wrap:wrap;padding:10px}.toolbar{margin-left:0;width:100%;flex-wrap:wrap}.layout{display:flex;flex-direction:column;height:auto}.sidebar{max-height:220px}.source{max-height:60vh}.panel{min-height:400px}}
</style></head><body>
<header><h1>NexaLab · OCR Workbench</h1><span id="source" class="muted"></span></header>
<section id="importBox" class="panel" style="max-width:720px;margin:28px auto;padding:22px"><h2>Import sách PDF</h2><p>Chọn PDF để OCR hoàn toàn trên máy này. Chạy mẫu phân tầng trước để kiểm tra chất lượng; chạy toàn bộ sách sau khi đã chọn cấu hình.</p><form id="importForm"><p><input type="file" name="pdf" accept="application/pdf" required></p><p><label>Chất lượng OCR <select name="tier"><option value="standard">Standard · khuyến nghị cho nội dung học tập</option><option value="basic">Basic · nhanh hơn</option><option value="flash">Flash · xem trước</option></select></label></p><p><label>Phạm vi <select name="scope"><option value="sample">Mẫu 20 trang phân tầng</option><option value="full">Toàn bộ sách</option></select></label></p><p><label><input type="checkbox" name="localRights" required> Tôi xác nhận được phép xử lý bản PDF này trên máy cục bộ.</label></p><button class="primary">Bắt đầu OCR cục bộ</button></form><p id="jobStatus" class="muted"></p></section>
<main id="reviewLayout" class="layout" hidden><aside class="sidebar"><h2>Trang mẫu <span id="count" class="count"></span></h2><div id="pages"></div></aside><section class="source"><img id="pageImage" alt="Trang PDF gốc"></section><section class="panel"><h2 id="title">Chọn trang để bắt đầu</h2><div class="notice">Review OCR này chỉ lưu quyết định và thời gian cục bộ; không phải duyệt nội dung chuyên môn hay quyền xuất bản.</div><div id="blocks" class="empty">Chọn một trang mẫu ở danh sách.</div><label class="muted">Lọc <select id="filter"><option value="all">Tất cả</option><option value="pending">Chưa review</option><option value="accepted">Đã chấp nhận</option><option value="needs-correction">Cần sửa</option><option value="rejected">Từ chối</option></select></label><div class="toolbar" style="margin:14px 0"><button id="prev">← Trang trước</button><button id="next">Trang sau →</button><button class="primary" data-action="accepted">Chấp nhận OCR</button><button data-action="needs-correction">Cần sửa</button><button class="reject" data-action="rejected">Từ chối OCR</button><span id="saved" class="muted"></span></div></section></main>
<script>
let state, current=null, started=0, dwellByPage={}, edits={};
const $=id=>document.getElementById(id);
async function get(url){const r=await fetch(url);if(!r.ok)throw Error(await r.text());return r.json()}
async function init(){state=await get('/api/state');if(!state.ready){$('source').textContent='Chỉ xử lý cục bộ · không gửi PDF lên dịch vụ bên ngoài';return}$('importBox').hidden=true;$('reviewLayout').hidden=false;$('source').textContent=`${state.pageCount} trang PDF · ${state.pages.length} trang OCR · source ${state.sourceHash.slice(0,8)} · OCR ${state.resultHash.slice(0,8)}`;$('filter').onchange=drawList;drawList();if(state.pages.length)await loadPage(state.pages[0].pageIndex)}
function drawList(){const filter=$('filter').value, items=state.pages.filter(p=>filter==='all'||(filter==='pending'?!p.status:p.status===filter));$('count').textContent=`${items.length}/${state.pages.length}`;$('pages').replaceChildren(...items.map(p=>{const b=document.createElement('button');b.className='page-item'+(p.pageIndex===current?' active':'');b.innerHTML=`Trang PDF ${p.pageIndex}<span class="status">${p.status||'Chưa review'} · ${p.blockCount} blocks</span>`;b.onclick=()=>loadPage(p.pageIndex);return b}))}
async function loadPage(page){if(current!==null)dwellByPage[current]=(dwellByPage[current]||0)+Math.max(0,(Date.now()-started)/1000);current=page;started=Date.now();const data=await get(`/api/page/${page}`);edits=data.review?.edits||{};$('title').textContent=`Trang PDF ${page} · ${data.blocks.length} blocks`;$('pageImage').src=`/source/${page}`;$('blocks').className='';$('blocks').replaceChildren(...data.blocks.map((b,i)=>{const card=document.createElement('div');card.className='block';const label=document.createElement('label');label.textContent=`${b.type||'text'} · block ${i+1}`;if(b.bbox)label.title=`bbox: ${b.bbox.join(', ')}`;const area=document.createElement('textarea');area.value=edits[String(i)]??(b.text||'');area.dataset.index=i;area.oninput=()=>{if(area.value===(b.text||''))delete edits[String(i)];else edits[String(i)]=area.value};card.append(label,area);return card}));$('saved').textContent=data.review?`Đã lưu ${data.review.savedAt}`:'';drawList()}
for(const button of document.querySelectorAll('[data-action]'))button.onclick=async()=>{if(current===null)return;const duration=Math.round((dwellByPage[current]||0)+(Date.now()-started)/1000);const body={pageIndex:current,action:button.dataset.action,edits,durationSeconds:duration};const r=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok){alert(await r.text());return}dwellByPage[current]=0;state=await get('/api/state');await loadPage(current);$('saved').textContent='Đã lưu review OCR cục bộ.'};
$('prev').onclick=()=>step(-1);$('next').onclick=()=>step(1);async function step(delta){if(current===null)return;const pages=state.pages.map(p=>p.pageIndex),i=pages.indexOf(current);if(pages[i+delta]!==undefined)await loadPage(pages[i+delta])}init().catch(e=>alert(e.message));
document.getElementById('importForm').onsubmit=async e=>{e.preventDefault();const status=$('jobStatus');status.textContent='Đang tải PDF vào workspace cục bộ…';const r=await fetch('/api/import',{method:'POST',body:new FormData(e.target)});if(!r.ok){status.textContent=await r.text();return}status.textContent='Đang chạy OCR cục bộ…';const poll=setInterval(async()=>{try{const j=await get('/api/import/status');status.textContent=j.message;if(j.status==='done'){clearInterval(poll);location.reload()}if(j.status==='error'){clearInterval(poll)}}catch(err){clearInterval(poll);status.textContent=err.message}},1500)};
</script></body></html>'''


class _ReviewServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, workspace: Workspace, pdf_path: Path | None, pages: dict[int, dict[str, Any]], page_count: int, source_hash: str, result_hash: str, port: int, mineru_bin: str | None = None, studio: bool = False):
        self.workspace = workspace
        self.pdf_path = pdf_path
        self.pages = pages
        self.page_count = page_count
        self.source_hash = source_hash
        self.result_hash = result_hash
        self.mineru_bin = mineru_bin or os.environ.get("NEXALAB_MINERU_KIT") or shutil.which("mineru-kit")
        self.job: dict[str, str] = {"status": "idle", "message": ""}
        self.studio = studio
        self.review_path = workspace.inside(".local", "m0a-review", f"{source_hash}-{result_hash}.json")
        self.lock = threading.Lock()
        self.review_state = self._load_reviews()
        super().__init__(("127.0.0.1", port), _Handler)

    def _load_reviews(self) -> dict[str, Any]:
        if self.review_path.exists():
            saved = read_json(self.review_path)
            if isinstance(saved, dict) and saved.get("sourceSha256") == self.source_hash and saved.get("resultSha256") == self.result_hash:
                return saved
        return {"history": [], "pages": {}, "resultSha256": self.result_hash, "schemaVersion": 1, "sourceSha256": self.source_hash}

    def page_image(self, page_index: int) -> Path:
        if self.pdf_path is None:
            raise ContentToolError("No PDF is loaded")
        path = self.workspace.inside(".local", "m0a-review", self.source_hash, f"page-{page_index:04d}.png")
        if not path.exists():
            try:
                import pymupdf
            except ImportError as error:
                raise ContentToolError("PyMuPDF is required to render review pages; run uv sync") from error
            document = pymupdf.open(self.pdf_path)
            try:
                if page_index < 1 or page_index > document.page_count:
                    raise ContentToolError(f"PDF page is out of range: {page_index}")
                path.parent.mkdir(parents=True, exist_ok=True)
                document[page_index - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(path)
            finally:
                document.close()
        return path


def _outcome_review_payload(workspace: Workspace, name: str) -> dict[str, Any]:
    from .outcome_normalization import _proposal_digest

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "proposal"
    path = workspace.inside(".local", "outcomes", f"{safe_name}.json")
    if not path.is_file():
        raise ContentToolError(f"Outcome proposal not found: {safe_name}")
    proposal = read_json(path)
    version = proposal.get("proposalVersion")
    immutable = workspace.inside(".local", "outcomes", "versions", safe_name, f"{version}.json") if isinstance(version, str) else None
    if not immutable or not immutable.is_file() or _proposal_digest(read_json(immutable)) != version:
        raise ContentToolError("The outcome proposal version is missing or does not match its immutable snapshot")

    outcomes = {item["id"]: item for item in proposal.get("outcomes", [])}
    concepts = {item["id"]: item for item in proposal.get("sourceConcepts", [])}
    block_refs: dict[str, dict[str, Any]] = {}
    for item in [*proposal.get("outcomes", []), *proposal.get("sourceConcepts", [])]:
        for evidence in item.get("evidence", []):
            digest = evidence.get("bookSha256")
            for page in evidence.get("pages", []):
                block_id = page.get("sourceBlockId")
                if block_id:
                    block_refs[block_id] = {
                        "pdfPage": page.get("physicalPageIndex"),
                        "printedPage": page.get("printedPageLabel"),
                        "sourceDigest": page.get("sourceSha256") or digest,
                    }
            for block_id in evidence.get("sourceBlockIds", []):
                block_refs.setdefault(block_id, {"pdfPage": None, "printedPage": None, "sourceDigest": digest})

    groups: dict[str, dict[str, Any]] = {}

    def group_for(source_lesson_id: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        group = groups.setdefault(
            source_lesson_id,
            {
                "chapterTitle": (evidence or {}).get("chapterTitle") or "Chapter not set",
                "lessonIdentity": (evidence or {}).get("lessonIdentity") or source_lesson_id,
                "sourceLessonId": source_lesson_id,
                "lessonTitle": (evidence or {}).get("sourceLessonTitle") or source_lesson_id,
                "outcomes": {},
                "lessonMappings": [],
                "knowledgeUnitMappings": [],
            },
        )
        if evidence:
            if group["chapterTitle"] == "Chapter not set" and evidence.get("chapterTitle"):
                group["chapterTitle"] = evidence["chapterTitle"]
            if group["lessonTitle"] == source_lesson_id and evidence.get("sourceLessonTitle"):
                group["lessonTitle"] = evidence["sourceLessonTitle"]
        return group

    for candidate in proposal.get("outcomes", []):
        all_evidence = candidate.get("evidence", []) or [{}]
        all_source_blocks = candidate.get("evidenceSourceBlockIds") or sorted({block_id for row in all_evidence for block_id in row.get("sourceBlockIds", [])})
        all_pages = [page for row in all_evidence for page in row.get("pages", [])]
        all_digests = sorted({row.get("bookSha256") for row in all_evidence if row.get("bookSha256")})
        for evidence in all_evidence:
            source_lesson_id = evidence.get("sourceLessonId") or candidate.get("sourceLessonId") or "unassigned"
            group = group_for(source_lesson_id, evidence)
            group["outcomes"][candidate["id"]] = {
                "id": candidate["id"],
                "statement": candidate.get("statement"),
                "sourcePhrase": evidence.get("sourcePhrase"),
                "sourceBlockIds": all_source_blocks,
                "sourceDigest": evidence.get("bookSha256"),
                "sourceDigests": all_digests,
                "pages": all_pages,
                "ambiguity": candidate.get("ambiguity", []),
                "qualityGate": candidate.get("qualityGate", {}),
                "confidence": candidate.get("confidence"),
                "status": candidate.get("status"),
            }

    def mapping_view(mapping: dict[str, Any], is_unit: bool) -> dict[str, Any]:
        candidate = outcomes.get(mapping.get("outcomeId"), {})
        concept = concepts.get(mapping.get("sourceConceptId"), {})
        block_ids = mapping.get("sourceBlockIds", [])
        pages: dict[tuple[Any, Any], dict[str, Any]] = {}
        digests: set[str] = set()
        for block_id in block_ids:
            ref = block_refs.get(block_id, {})
            if ref.get("sourceDigest"):
                digests.add(ref["sourceDigest"])
            if ref.get("pdfPage") is not None:
                pages[(ref["pdfPage"], block_id)] = {
                    "pdfPage": ref["pdfPage"],
                    "printedPage": ref.get("printedPage"),
                    "sourceBlockId": block_id,
                }
        for evidence in concept.get("evidence", []):
            if evidence.get("bookSha256"):
                digests.add(evidence["bookSha256"])
        return {
            "mappingId": mapping["mappingId"],
            "knowledgeUnitId": mapping.get("knowledgeUnitId"),
            "sourceConceptId": mapping.get("sourceConceptId"),
            "sourceConceptStatement": concept.get("statement"),
            "outcomeId": mapping.get("outcomeId"),
            "outcomeStatement": candidate.get("statement"),
            "status": mapping.get("status"),
            "mappingConfidence": mapping.get("mappingConfidence"),
            "ambiguity": mapping.get("ambiguity", []),
            "sharedTerms": mapping.get("sharedTerms", []),
            "sourceBlockIds": block_ids,
            "pages": list(pages.values()),
            "sourceDigests": sorted(digests),
        }

    for mapping in proposal.get("lessonMappings", []):
        group_for(mapping.get("sourceLessonId") or "unassigned")["lessonMappings"].append(mapping_view(mapping, False))
    for mapping in proposal.get("knowledgeUnitMappings", []):
        group_for(mapping.get("sourceLessonId") or "unassigned")["knowledgeUnitMappings"].append(mapping_view(mapping, True))

    priorities = {item.get("sourceLessonId"): item.get("priority", 99) for item in proposal.get("reviewQueue", [])}
    ordered = sorted(groups.values(), key=lambda item: (priorities.get(item["sourceLessonId"], 99), item["chapterTitle"], item["lessonTitle"]))
    for group in ordered:
        group["outcomes"] = list(group["outcomes"].values())
    return {
        "name": safe_name,
        "proposalVersion": version,
        "coverage": proposal.get("coverage", {}),
        "reviewHistory": proposal.get("reviewHistory", []),
        "outcomeOptions": [{"id": item["id"], "statement": item.get("statement"), "status": item.get("status")} for item in proposal.get("outcomes", [])],
        "groups": ordered,
    }


class _Handler(BaseHTTPRequestHandler):
    server: _ReviewServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            page = Path(__file__).with_name("m1_ui.html").read_text(encoding="utf-8") if self.server.studio else _HTML
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.server.studio and path.startswith("/api/m1/"):
            self._m1_get(path, parse_qs(parsed.query))
            return
        if path == "/api/state":
            if self.server.pdf_path is None:
                self._json(200, {"ready": False})
                return
            with self.server.lock:
                saved = self.server.review_state["pages"]
                pages = [
                    {
                        "blockCount": len(data.get("blocks", [])),
                        "pageIndex": page_index,
                        "status": saved.get(str(page_index), {}).get("status"),
                    }
                    for page_index, data in sorted(self.server.pages.items())
                ]
            self._json(200, {"ready": True, "pageCount": self.server.page_count, "pages": pages, "resultHash": self.server.result_hash, "sourceHash": self.server.source_hash})
            return
        if path == "/api/import/status":
            self._json(200, self.server.job)
            return
        match = _PAGE.fullmatch(path)
        if match:
            page_index = int(match.group(1))
            if page_index not in self.server.pages:
                self._json(404, {"error": "Page is not in the OCR sample"})
                return
            if path.startswith("/source/"):
                try:
                    image_path = self.server.page_image(page_index)
                    self._send(200, image_path.read_bytes(), "image/png")
                except ContentToolError as error:
                    self._json(400, {"error": str(error)})
                return
            with self.server.lock:
                review = self.server.review_state["pages"].get(str(page_index))
            self._json(200, {"blocks": self.server.pages[page_index].get("blocks", []), "pageIndex": page_index, "review": review})
            return
        self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        origin = self.headers.get("Origin")
        expected_origin = f"http://{self.headers.get('Host', '')}"
        if host not in {"127.0.0.1", "localhost"} or (origin and origin != expected_origin):
            self._json(403, {"error": "Workbench accepts same-origin requests from loopback only"})
            return
        route = urlparse(self.path).path
        if self.server.studio and route.startswith("/api/m1/"):
            self._m1_post(route)
            return
        if route == "/api/import":
            self._start_import()
            return
        if route != "/api/review":
            self._json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 2_000_000:
                raise ValueError("Invalid review payload size")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Review payload must be an object")
            page_index = body.get("pageIndex")
            action = body.get("action")
            edits = body.get("edits", {})
            duration = body.get("durationSeconds", 0)
            if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index not in self.server.pages:
                raise ValueError("Review page is not in the OCR sample")
            if not isinstance(action, str) or action not in {"accepted", "needs-correction", "rejected"}:
                raise ValueError("Invalid OCR review action")
            if not isinstance(edits, dict) or any(not str(key).isdigit() or not isinstance(value, str) for key, value in edits.items()):
                raise ValueError("Edits must map block indexes to text")
            if any(int(key) >= len(self.server.pages[page_index].get("blocks", [])) for key in edits):
                raise ValueError("Edit references a block outside the page")
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0 or duration > 86400:
                raise ValueError("Review duration is invalid")
            now = datetime.now(timezone.utc).isoformat()
            event = {"action": action, "durationSeconds": round(duration), "edits": edits, "pageIndex": page_index, "savedAt": now}
            with self.server.lock:
                previous = self.server.review_state["pages"].get(str(page_index), {})
                total_seconds = int(previous.get("totalReviewSeconds", 0)) + round(duration)
                self.server.review_state["pages"][str(page_index)] = {
                    "action": action,
                    "edits": edits,
                    "savedAt": now,
                    "status": action,
                    "totalReviewSeconds": total_seconds,
                }
                self.server.review_state["history"].append(event)
                write_json(self.server.review_path, self.server.review_state)
            self._json(200, {"saved": True})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._json(400, {"error": str(error)})

    def _m1_get(self, route: str, query: dict[str, list[str]]) -> None:
        from .m1_workflow import _book, _pdf, books, chapter_state, detect_toc, page_record, whole_book_report

        try:
            book_key = query.get("book", [""])[0]
            if route == "/api/m1/outcomes":
                self._json(200, _outcome_review_payload(self.server.workspace, query.get("name", ["proposal"])[0]))
                return
            if route == "/api/m1/books":
                self._json(200, {"books": books(self.server.workspace), "job": self.server.job})
                return
            if route == "/api/m1/structured-status":
                book = _book(self.server.workspace, book_key)
                lessons = []
                from .structured import _lesson_artifact_path
                checkpoint_path = self.server.workspace.inside(".local", "books", book_key, "processing.json")
                checkpoint = read_json(checkpoint_path) if checkpoint_path.is_file() else None
                for chapter in sorted(book.get("chapters", []), key=lambda item: item.get("start", 0)):
                    for lesson in chapter.get("lessons", []):
                        path = _lesson_artifact_path(self.server.workspace, lesson["id"])
                        artifact = read_json(path) if path.is_file() else None
                        review = artifact.get("contentReview") if artifact and isinstance(artifact.get("contentReview"), dict) else {}
                        status = review.get("status") if review.get("status") in {"accepted", "needs_review"} else "needs_review" if artifact else "not_generated"
                        lessons.append({"id": lesson["id"], "chapterId": chapter["id"], "title": lesson["title"], "pdfPageRange": {"start": lesson["start"], "end": lesson["end"]}, "status": status, "path": str(path) if artifact else None})
                self._json(200, {"bookKey": book_key, "lessons": lessons, "report": whole_book_report(self.server.workspace, book_key, processing=checkpoint)})
                return
            if route == "/api/m1/toc":
                book = _book(self.server.workspace, book_key)
                self._json(200, {"bookKey": book_key, "tree": [{key: chapter.get(key) for key in ("id", "title", "start", "end", "lessons", "tocConfirmedAt", "tocProvenance")} for chapter in book.get("chapters", []) if chapter.get("lessons")], "status": "confirmed" if any(chapter.get("lessons") for chapter in book.get("chapters", [])) else "empty"})
                return
            if route == "/api/m1/chapter":
                self._json(200, chapter_state(self.server.workspace, book_key, query.get("chapter", [""])[0]))
                return
            if route == "/api/m1/page":
                from .enrichment import normalize_text
                page = int(query.get("page", ["0"])[0])
                record = page_record(self.server.workspace, book_key, page)
                if record is None:
                    raise ContentToolError("Page has not been extracted")
                edits = record.get("review", {}).get("edits", {})
                for index, block in enumerate(record.get("blocks", [])):
                    reviewed = edits.get(str(index), block.get("text", ""))
                    kind = str(block.get("type", "text")).lower()
                    block["displayType"] = "formula" if kind in {"equation", "formula", "latex"} else "table" if "table" in kind else "image" if kind in {"image", "figure"} else "text"
                    block["normalizedText"] = normalize_text(reviewed)
                    block["provenance"] = {key: block.get(key) for key in ("physicalPageIndex", "printedPageLabel", "sourceSha256", "sourceVersion", "extractionMethod", "bbox")}
                self._json(200, record)
                return
            if route == "/api/m1/source":
                page = int(query.get("page", ["0"])[0])
                book = _book(self.server.workspace, book_key)
                if page < 1 or page > book["pageCount"]:
                    raise ContentToolError("PDF page is outside the book")
                image = self.server.workspace.inside(".local", "books", book_key, "images", f"{page:04d}.png")
                if not image.exists():
                    import pymupdf
                    with pymupdf.open(_pdf(self.server.workspace, book)) as document:
                        image.parent.mkdir(parents=True, exist_ok=True)
                        document[page - 1].get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3), alpha=False).save(image)
                self._send(200, image.read_bytes(), "image/png")
                return
            if route == "/api/m1/draft":
                from .m1_workflow import draft_path
                path = draft_path(self.server.workspace, query.get("pack", [""])[0])
                self._json(200, read_json(path))
                return
            if route == "/api/m1/structured":
                from .structured import load_structured_lesson
                self._json(200, load_structured_lesson(self.server.workspace, book_key, query.get("chapter", [""])[0], query.get("lesson", [""])[0]))
                return
            if route == "/api/m1/lab-candidates":
                pack = query.get("pack", [""])[0]
                path = self.server.workspace.inside(".local", "lab-candidates", f"{pack}.json")
                self._json(200, read_json(path) if path.exists() else {"packKey": pack, "status": "proposed", "candidates": []})
                return
            if route == "/api/m1/authoring-verification":
                from .authoring_contract import verification_path
                pack = query.get("pack", [""])[0]
                path = verification_path(self.server.workspace, pack)
                self._json(200, read_json(path) if path.exists() else {"packKey": pack, "status": "unverified"})
                return
            self._json(404, {"error": "Not found"})
        except (ContentToolError, ValueError) as error:
            self._json(400, {"error": str(error)})

    def _m1_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 2_000_000:
            raise ContentToolError("Invalid request body size")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ContentToolError("Request body must be an object")
        return value

    def _m1_post(self, route: str) -> None:
        from .m1_workflow import import_book, process_chapter, process_lesson, process_pdf_pages, save_chapter, save_draft, save_formal_reviews, save_review, save_toc_tree, detect_toc, export_status

        try:
            if route == "/api/m1/import":
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 300_500_000:
                    raise ContentToolError("PDF upload must be below 300 MB")
                message = BytesParser(policy=policy.default).parsebytes(
                    f"Content-Type: {self.headers.get('Content-Type')}\r\nMIME-Version: 1.0\r\n\r\n".encode() + self.rfile.read(length)
                )
                parts = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
                value = lambda key: _multipart_text(parts[key]) if key in parts else ""
                pdf = parts.get("pdf")
                if pdf is None:
                    raise ContentToolError("Choose a PDF")
                start = value("printedStart")
                result = import_book(self.server.workspace, pdf.get_payload(decode=True), key=value("key"), version=value("version"), title=value("title"), author=value("author"), local_rights=value("localRights").lower() in {"on", "yes", "true"}, printed_start=int(start) if start else None)
                self._json(200, result)
                return
            body = self._m1_body()
            if route == "/api/m1/outcomes/review":
                from .outcome_normalization import export_outcome_sync_bundle, review_outcome_proposal

                name = str(body.get("name", ""))
                state = _outcome_review_payload(self.server.workspace, name)
                if body.get("proposalVersion") != state["proposalVersion"]:
                    self._json(409, {"error": "The proposal changed since it was loaded. Reload before saving decisions."})
                    return
                result = review_outcome_proposal(
                    self.server.workspace,
                    name,
                    outcome_decisions=body.get("outcomeDecisions", {}),
                    mapping_decisions=body.get("mappingDecisions", {}),
                    reviewer_name=str(body.get("reviewerName", "")),
                    reviewer_email=str(body.get("reviewerEmail", "")),
                    reason=str(body.get("reason", "")),
                    source_text_verified=body.get("sourceTextVerified") is True,
                )
                bundle = export_outcome_sync_bundle(self.server.workspace, name)["bundle"]
                self._json(
                    200,
                    {
                        "saved": True,
                        "reviewId": result["reviewEvent"]["reviewId"],
                        "proposalVersion": result["reviewEvent"]["proposalVersion"],
                        "reviewedAt": result["reviewEvent"]["reviewedAt"],
                        "approvedOutcomes": bundle["registrySyncPreflight"]["approvedOutcomeCount"],
                        "pendingOutcomes": bundle["registrySyncPreflight"]["unapprovedOutcomeCount"],
                        "pendingMappings": bundle["registrySyncPreflight"]["unapprovedMappingCount"],
                    },
                )
                return
            if route == "/api/m1/toc/ocr":
                if self.server.job["status"] == "running":
                    raise ContentToolError("Another OCR job is already running")
                pages, book_key = body.get("pages"), body.get("bookKey")
                if not isinstance(pages, list) or not pages or any(isinstance(page, bool) or not isinstance(page, int) or page > 40 for page in pages):
                    raise ContentToolError("TOC OCR accepts selected pages in the first 40 PDF pages")
                self.server.job = {"status": "running", "message": "Đang OCR trang mục lục bằng MinerU cục bộ…"}
                def toc_worker() -> None:
                    try:
                        result = process_pdf_pages(self.server.workspace, book_key, pages, self.server.mineru_bin, body.get("tier", "standard"), lambda page, end: self.server.job.update({"status": "running", "message": f"Đang OCR PDF {page}/{end}"}), body.get("rerun") is True)
                        self.server.job = {"status": "done", "message": f"Đã OCR {result['completed']}/{result['total']} trang mục lục; chạy phát hiện TOC để review cây."}
                    except Exception as error:
                        self.server.job = {"status": "error", "message": str(error)}
                threading.Thread(target=toc_worker, daemon=True).start()
                self._json(202, {"started": True})
                return
            if route == "/api/m1/toc/detect":
                self._json(200, detect_toc(self.server.workspace, body["bookKey"], pages=body.get("pages")))
                return
            if route == "/api/m1/toc/confirm":
                self._json(200, save_toc_tree(self.server.workspace, body["bookKey"], body["tree"], body.get("provenance", {})))
                return
            if route == "/api/m1/toc/propose":
                self._json(200, save_toc_tree(self.server.workspace, body["bookKey"], body["tree"], body.get("provenance", {}), confirmed=False))
                return
            if route == "/api/m1/chapter":
                self._json(200, save_chapter(self.server.workspace, body["bookKey"], chapter_id=body["id"], title=body["title"], start=body["start"], end=body["end"], printed_start=body.get("printedStart")))
                return
            if route == "/api/m1/ocr":
                if self.server.job["status"] == "running":
                    raise ContentToolError("OCR is already running")
                book_key, chapter_id = body["bookKey"], body.get("chapterId")
                lesson_id = body.get("lessonId")
                tier = body.get("tier", "standard")
                rerun = body.get("rerun") is True
                self.server.job = {"status": "running", "message": "Đang trích xuất chương…"}

                def worker() -> None:
                    try:
                        def progress(page: int, end: int) -> None:
                            self.server.job = {"status": "running", "message": f"Đang xử lý trang PDF {page}/{end}"}
                        state = process_lesson(self.server.workspace, book_key, lesson_id, self.server.mineru_bin, tier, progress, rerun) if lesson_id else process_chapter(self.server.workspace, book_key, chapter_id, self.server.mineru_bin, tier, progress, rerun)
                        self.server.job = {"status": "done", "message": f"Đã lưu {state['completed']}/{state['total']} trang; mở Review để kiểm tra."}
                    except Exception as error:
                        self.server.job = {"status": "error", "message": str(error)}
                threading.Thread(target=worker, daemon=True).start()
                self._json(202, {"started": True})
                return
            if route == "/api/m1/process-book":
                if self.server.job["status"] == "running":
                    raise ContentToolError("An OCR job is already running")
                book_key, tier = body["bookKey"], body.get("tier", "standard")
                self.server.job = {"status": "running", "message": "Đang chuẩn bị tiếp tục các Lesson có mapping…"}

                def book_worker() -> None:
                    try:
                        from .m1_workflow import process_book
                        from .structured import export_book_candidates, validate_book_outputs
                        def progress(page: int, total: int) -> None:
                            self.server.job = {"status": "running", "message": f"Đang OCR/tiếp tục trang PDF {page}/{total}"}
                        result = process_book(self.server.workspace, book_key, self.server.mineru_bin, tier, progress)
                        exports = export_book_candidates(self.server.workspace, book_key)
                        validation = validate_book_outputs(self.server.workspace, book_key)
                        report = result["report"]
                        self.server.job = {"status": "done" if report["status"] == "complete" and validation["status"] == "valid" else "partial", "message": f"Lesson OCR hoàn tất: {report['completedPageCount']}/{report['mappedPageCount']} trang; {report['failedPageCount']} lỗi, {report['unmappedPageCount']} trang ngoài vùng Lesson. Candidate: {exports['candidatePath']}"}
                    except Exception as error:
                        self.server.job = {"status": "error", "message": str(error)}
                threading.Thread(target=book_worker, daemon=True).start()
                self._json(202, {"started": True})
                return
            if route == "/api/m1/review":
                self._json(200, save_review(self.server.workspace, body["bookKey"], body["pageIndex"], body["action"], body.get("edits", {}), body.get("durationSeconds", 0)))
                return
            if route == "/api/m1/draft":
                self._json(200, save_draft(self.server.workspace, body))
                return
            if route == "/api/m1/enrichment":
                from .enrichment import build_enrichment_proposal
                self._json(200, build_enrichment_proposal(self.server.workspace, body["bookKey"], body["chapterId"], body["pages"]))
                return
            if route == "/api/m1/gemini":
                from .enrichment import gemini_proposal
                self._json(200, gemini_proposal(self.server.workspace, body["bookKey"], body["chapterId"], body["pages"], provider_confirmed=body.get("providerConfirmed") is True, transmission_allowed=body.get("transmissionAllowed") is True))
                return
            if route == "/api/m1/lab-candidates":
                from .authoring_contract import validate_lab_blueprint
                from .enrichment import save_lab_candidates, suggest_lab_candidates
                if body.get("action") == "suggest":
                    self._json(200, {"candidates": suggest_lab_candidates(self.server.workspace, body["draft"])})
                elif body.get("action") == "save":
                    self._json(200, save_lab_candidates(self.server.workspace, body["packKey"], body.get("candidates", [])))
                elif body.get("action") == "validate":
                    self._json(200, validate_lab_blueprint(body["backend"], body["blueprint"]))
                else:
                    raise ContentToolError("Choose suggest, save or validate for Lab candidates")
                return
            if route == "/api/m1/authoring-verification":
                from .authoring_contract import fetch_authoring_context, save_verification, verify_authoring_context
                context = fetch_authoring_context(str(body.get("apiBase", "")), str(body.get("accessToken", "")))
                verification = verify_authoring_context(body["draft"], context, str(body.get("apiBase", "")))
                self._json(200, save_verification(self.server.workspace, verification))
                return
            if route == "/api/m1/formal-reviews":
                save_formal_reviews(self.server.workspace, body["packKey"], body["reviews"])
                self._json(200, {"saved": True})
                return
            if route == "/api/m1/export":
                self._json(200, export_status(self.server.workspace))
                return
            if route == "/api/m1/export-structured":
                from .structured import export_chapter_candidates
                self._json(200, export_chapter_candidates(self.server.workspace, body["bookKey"], body["chapterId"]))
                return
            if route == "/api/m1/export-book":
                from .structured import export_book_candidates, validate_book_outputs
                self._json(200, {**export_book_candidates(self.server.workspace, body["bookKey"]), "validation": validate_book_outputs(self.server.workspace, body["bookKey"])})
                return
            if route == "/api/m1/structured-review":
                from .structured import accept_structured_content, save_structured_content
                if body.get("action") == "save":
                    result = save_structured_content(self.server.workspace, body["bookKey"], body["chapterId"], body["lessonId"], body["learningContent"])
                elif body.get("action") == "accept":
                    result = accept_structured_content(
                        self.server.workspace,
                        body["bookKey"],
                        body["chapterId"],
                        body["lessonId"],
                        human_review_confirmed=body.get("humanReviewConfirmed") is True,
                        reviewer_name=str(body.get("reviewerName", "")),
                        reviewer_email=str(body.get("reviewerEmail", "")),
                        reason=str(body.get("reason", "")),
                    )
                else:
                    raise ContentToolError("Choose save or accept for local Lesson content review")
                self._json(200, result)
                return
            if route == "/api/m1/export-approved":
                from .structured import export_approved_lesson
                self._json(200, export_approved_lesson(self.server.workspace, body["bookKey"], body["chapterId"], body["lessonId"]))
                return
            if route == "/api/m1/plan":
                from .backend import TARGET_PATTERN
                from .m1_workflow import export_status
                import os
                status = export_status(self.server.workspace)
                if not status["ready"]:
                    self._json(200, status)
                    return
                backend = Path(str(body.get("backend", ""))).resolve()
                target = str(body.get("target", ""))
                if not TARGET_PATTERN.fullmatch(target) or not (backend / "scripts" / "content-release.ts").is_file():
                    raise ContentToolError("Configure a valid BE checkout and explicit target before plan")
                command = ["npm.cmd" if os.name == "nt" else "npm", "run", "content:release", "--", "--manifest", status["manifest"], "--target", target]
                run = subprocess.run(command, cwd=backend, capture_output=True, text=True, timeout=300, check=False)
                self._json(200, {"exitCode": run.returncode, "output": run.stdout, "error": run.stderr})
                return
            self._json(404, {"error": "Not found"})
        except (ContentToolError, ValueError, TypeError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
            self._json(400, {"error": str(error)})

    def _start_import(self) -> None:
        if not self.server.mineru_bin:
            self._json(400, {"error": "Không tìm thấy mineru-kit. Cài MinerU 4.x và đặt NEXALAB_MINERU_KIT trỏ tới executable."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 300_000_000:
                raise ValueError("PDF upload must be under 300 MB")
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {self.headers.get('Content-Type')}\r\nMIME-Version: 1.0\r\n\r\n".encode() + self.rfile.read(length)
            )
            parts = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
            pdf_part = parts.get("pdf")
            tier = str(parts.get("tier").get_content()) if parts.get("tier") else "standard"
            scope = str(parts.get("scope").get_content()) if parts.get("scope") else "sample"
            rights = str(parts.get("localRights").get_content()) if parts.get("localRights") else ""
            if tier not in {"standard", "basic", "flash"} or scope not in {"sample", "full"}:
                raise ValueError("Invalid OCR tier or scope")
            if rights.lower() not in {"on", "true", "yes"}:
                raise ValueError("Confirm local processing rights before upload")
            if pdf_part is None or not pdf_part.get_payload(decode=True).startswith(b"%PDF-"):
                raise ValueError("Choose a valid PDF file")
            if self.server.job.get("status") == "running":
                raise ValueError("An OCR job is already running")
            payload = pdf_part.get_payload(decode=True)
            source_hash = __import__("hashlib").sha256(payload).hexdigest()
            root = self.server.workspace.root / ".local" / "imports" / source_hash
            root.mkdir(parents=True, exist_ok=True)
            pdf = root / "source.pdf"
            pdf.write_bytes(payload)
            with self.server.lock:
                self.server.job = {"status": "running", "message": "MinerU đang xử lý PDF trên máy này…"}
            threading.Thread(target=self._run_import, args=(pdf, root, tier, scope), daemon=True).start()
            self._json(202, {"started": True})
        except (ValueError, TypeError, AttributeError) as error:
            self._json(400, {"error": str(error)})

    def _run_import(self, pdf: Path, root: Path, tier: str, scope: str) -> None:
        try:
            import pymupdf
            with pymupdf.open(pdf) as document:
                count = document.page_count
            command = [self.server.mineru_bin, "parse", str(pdf)]
            if scope == "sample":
                selected = sorted({p for i in range(10) for p in (max(1, round((i + .35) * count / 10)), max(1, round((i + .4) * count / 10)))})
                selected = [p for p in selected if p <= count]
                command += ["--pages", ",".join(map(str, selected))]
            output = root / "mineru"
            command += ["--output", str(output), "--format", "zip", "--tier", tier, "--ocr-mode", "ocr"]
            run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=6 * 60 * 60, check=False)
            if run.returncode:
                raise RuntimeError((run.stderr or run.stdout)[-3000:] or f"MinerU exited {run.returncode}")
            archives = list(output.rglob("*.zip"))
            if not archives:
                raise RuntimeError("MinerU completed but did not create an OCR ZIP")
            pages, page_count, source_hash, result_hash = _load_result(self.server.workspace, pdf, archives[0])
            with self.server.lock:
                self.server.pdf_path, self.server.pages, self.server.page_count = pdf, pages, page_count
                self.server.source_hash, self.server.result_hash = source_hash, result_hash
                self.server.review_path = self.server.workspace.inside(".local", "m0a-review", f"{source_hash}-{result_hash}.json")
                self.server.review_state = self.server._load_reviews()
                self.server.job = {"status": "done", "message": "OCR hoàn tất. Đang mở màn hình review…"}
        except Exception as error:
            with self.server.lock:
                self.server.job = {"status": "error", "message": f"OCR thất bại: {error}"}


def _load_result(workspace: Workspace, pdf_path: str | Path, ocr_zip: str | Path):
    pdf = Path(pdf_path).resolve()
    archive = Path(ocr_zip).resolve()
    if not pdf.is_file() or not archive.is_file():
        raise ContentToolError("PDF and MinerU ZIP must both exist")
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            member = "structured_content.json" if "structured_content.json" in names else "middle_json.json"
            if member not in names:
                raise ContentToolError("MinerU ZIP must contain structured_content.json or middle_json.json")
            if bundle.getinfo(member).file_size > 100_000_000:
                raise ContentToolError("MinerU structured output is larger than 100 MB")
            payload = json.loads(bundle.read(member))
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as error:
        raise ContentToolError(f"Cannot read MinerU ZIP: {error}") from error
    pages_value = payload.get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages_value, list) or not pages_value:
        raise ContentToolError("MinerU result has no pages to review")
    pages: dict[int, dict[str, Any]] = {}
    for item in pages_value:
        if not isinstance(item, dict) or isinstance(item.get("page_idx"), bool) or not isinstance(item.get("page_idx"), int):
            raise ContentToolError("MinerU result contains an invalid page index")
        page_index = item["page_idx"] + 1
        if page_index < 1 or page_index in pages or not isinstance(item.get("blocks", []), list):
            raise ContentToolError("MinerU result contains duplicate pages or invalid blocks")
        pages[page_index] = item
    try:
        import pymupdf
        document = pymupdf.open(pdf)
        try:
            if not document.is_pdf:
                raise ContentToolError(f"Source is not a PDF: {pdf}")
            page_count = document.page_count
        finally:
            document.close()
    except ContentToolError:
        raise
    except Exception as error:
        raise ContentToolError(f"Cannot read source PDF {pdf}: {error}") from error
    if any(page > page_count for page in pages):
        raise ContentToolError("MinerU result contains a page outside the source PDF")
    source_hash = sha256_file(pdf)
    result_hash = sha256_file(archive)
    return pages, page_count, source_hash, result_hash


def launch_review(workspace: Workspace, pdf_path: str | Path, ocr_zip: str | Path, port: int = 0) -> None:
    pdf = Path(pdf_path).resolve()
    archive = Path(ocr_zip).resolve()
    pages, page_count, source_hash, result_hash = _load_result(workspace, pdf, archive)
    server = _ReviewServer(workspace, pdf, pages, page_count, source_hash, result_hash, port)
    _serve(server)


def launch_studio(workspace: Workspace, port: int = 0, mineru_bin: str | None = None) -> None:
    if port < 0 or port > 65535:
        raise ContentToolError("Port must be between 0 and 65535")
    cached = sorted((workspace.root / ".local" / "imports").glob("*/mineru/*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
    source = None
    pages: dict[int, dict[str, Any]] = {}
    page_count = 0
    source_hash = result_hash = ""
    for archive in cached:
        candidate = archive.parent.parent / "source.pdf"
        if not candidate.is_file():
            continue
        try:
            pages, page_count, source_hash, result_hash = _load_result(workspace, candidate, archive)
            source = candidate
            break
        except ContentToolError:
            continue
    server = _ReviewServer(workspace, source, pages, page_count, source_hash, result_hash, port, mineru_bin, studio=True)
    _serve(server)


def _serve(server: _ReviewServer) -> None:
    print(f"OCR review is local at http://127.0.0.1:{server.server_port}")
    if server.pdf_path:
        print(f"Review history: {server.review_path}")
    try:
        threading.Thread(target=webbrowser.open, args=(f"http://127.0.0.1:{server.server_port}",), daemon=True).start()
        server.serve_forever()
    except KeyboardInterrupt:
        print("OCR review stopped.")
    finally:
        server.server_close()
