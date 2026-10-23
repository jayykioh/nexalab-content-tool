from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr
from email import policy
from email.parser import BytesParser
from io import StringIO
from pathlib import Path

import pymupdf

from nexalab_content_tool.enrichment import (
    build_enrichment_proposal, gemini_proposal, normalize_text,
    save_lab_candidates, suggest_lab_candidates,
)
from nexalab_content_tool.cli import main
from nexalab_content_tool.authoring_contract import save_verification, verify_authoring_context
from nexalab_content_tool.m1_workflow import (
    _mineru_text, _page_batches, chapter_state, detect_toc, draft_path, export_status, import_book, page_path, page_record,
    process_book, process_chapter, process_lesson, save_chapter, save_draft, save_review, save_toc_tree,
)
from nexalab_content_tool.manifest import build_manifest
from nexalab_content_tool.structured import (
    accept_structured_content, export_approved_lesson, export_book_candidates, export_chapter_candidates,
    save_structured_content, validate_book_outputs,
)
from nexalab_content_tool.workspace import ContentToolError, Workspace, init_workspace, write_json
from nexalab_content_tool.m0a_review import _multipart_text


class M1WorkflowTests(unittest.TestCase):
    def test_whole_book_batches_resume_and_track_unmapped_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace.open(init_workspace(Path(temporary) / "workspace", "whole-book"))
            pdf = pymupdf.open()
            for page in range(5):
                pdf.new_page().insert_text((60, 80), f"Source content for Lesson page {page + 1}. " * 5)
            payload = pdf.tobytes()
            pdf.close()
            book = import_book(workspace, payload, key="science-book", version="v1", title="Science", author="Publisher", local_rights=True)
            tree = [{
                "id": "chapter-one", "title": "Chapter one", "start": 1, "end": 4,
                "lessons": [
                    {"id": "source-lesson-one", "title": "Lesson one", "start": 1, "end": 2, "printedStart": 1, "printedEnd": 2},
                    {"id": "source-lesson-two", "title": "Lesson two", "start": 3, "end": 4, "printedStart": 3, "printedEnd": 4},
                ],
            }]
            save_toc_tree(workspace, "science-book", tree, {"sourceSha256": book["sha256"], "method": "fixture"})
            result = process_book(workspace, "science-book", None)
            self.assertEqual(result["report"]["lessonCount"], 2)
            self.assertEqual(result["report"]["mappedPageCount"], 4)
            self.assertEqual(result["report"]["completedPageCount"], 4)
            self.assertEqual(result["report"]["unmappedPages"], [5])
            self.assertTrue(all(item["status"] == "completed" for item in result["checkpoint"]["lessons"].values()))
            self.assertEqual(_page_batches(list(range(1, 45)), limit=20), [list(range(1, 21)), list(range(21, 41)), list(range(41, 45))])

    def test_structured_edits_survive_restart_and_acceptance_is_human_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "workspace"
            workspace = Workspace.open(init_workspace(root, "structured-review"))
            pdf = pymupdf.open()
            pdf.new_page().insert_text((60, 80), "A complete science source paragraph with enough content for review. " * 4)
            payload = pdf.tobytes()
            pdf.close()
            book = import_book(workspace, payload, key="science-book", version="v1", title="Science", author="Publisher", local_rights=True)
            save_toc_tree(workspace, "science-book", [{
                "id": "chapter-one", "title": "Chapter one", "start": 1, "end": 1,
                "lessons": [{"id": "source-lesson-one", "title": "Lesson one", "start": 1, "end": 1, "printedStart": 1, "printedEnd": 1}],
            }], {"sourceSha256": book["sha256"], "method": "fixture"})
            process_book(workspace, "science-book", None)
            candidate = export_chapter_candidates(workspace, "science-book", "chapter-one")
            self.assertIsNotNone(candidate["lessons"][0]["structuredPath"])
            artifact_path = Path(candidate["lessons"][0]["structuredPath"])
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["contentReview"] = None  # Legacy Chapter VI candidates used null; null is not acceptance.
            write_json(artifact_path, artifact)
            candidate = export_chapter_candidates(workspace, "science-book", "chapter-one")
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["contentReview"]["status"], "needs_review")
            content = artifact["learningContent"]
            source_id = artifact["sourceBlocks"][0]["id"]
            content["summary"] = "A human-edited concise source summary."
            content["summarySourceBlockIds"] = [source_id]
            content["sections"] = [{"id": "section-one", "heading": "Source", "content": "A reviewed source section.", "sourceBlockIds": [source_id]}]
            content["knowledgeUnits"] = [{"id": "unit-one", "title": "Source knowledge", "claims": [{"id": "claim-one", "text": "A source-grounded claim.", "sourceBlockIds": [source_id]}], "sourceBlockIds": [source_id]}]
            saved = save_structured_content(workspace, "science-book", "chapter-one", "source-lesson-one", content)
            self.assertEqual(saved["contentReview"]["status"], "needs_review")
            workspace = Workspace.open(root)
            reopened = export_chapter_candidates(workspace, "science-book", "chapter-one")
            persisted = json.loads(Path(reopened["lessons"][0]["structuredPath"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["learningContent"]["summary"], "A human-edited concise source summary.")
            self.assertEqual(persisted["sourceLesson"]["id"], "source-lesson-one")
            with self.assertRaisesRegex(ValueError, "confirmation"):
                accept_structured_content(workspace, "science-book", "chapter-one", "source-lesson-one", human_review_confirmed=False)
            accepted = accept_structured_content(workspace, "science-book", "chapter-one", "source-lesson-one", human_review_confirmed=True)
            self.assertEqual(accepted["contentReview"]["status"], "accepted")
            approved = export_approved_lesson(workspace, "science-book", "chapter-one", "source-lesson-one")
            self.assertTrue(Path(approved["path"]).is_file())
            content = accepted["learningContent"]
            content["summary"] = "A new edit invalidates prior acceptance."
            edited = save_structured_content(workspace, "science-book", "chapter-one", "source-lesson-one", content)
            self.assertEqual(edited["contentReview"]["status"], "needs_review")
            self.assertFalse(Path(approved["path"]).exists())
            validation = validate_book_outputs(workspace, "science-book")
            self.assertEqual(validation["status"], "valid")
            self.assertEqual(validation["validJsonCount"], 1)
            self.assertEqual(validation["lessons"][0]["contentReviewStatus"], "needs_review")
            exported = export_book_candidates(workspace, "science-book")
            candidate = json.loads(Path(exported["candidatePath"]).read_text(encoding="utf-8"))
            self.assertFalse(candidate["ready"])
            self.assertIsNone(candidate["releaseManifestCandidate"]["packs"][0]["domain"])
            self.assertTrue(Path(exported["blockerMarkdownPath"]).is_file())
            self.assertTrue(any("domain" in item.lower() for item in exported["blockers"]["source-lesson-one"]))
    def test_toc_to_lesson_ocr_and_reopened_draft_stays_in_source_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace.open(init_workspace(Path(temporary) / "workspace", "toc-lesson"))
            pdf = pymupdf.open()
            for text in (
                "CHUONG I. CELLS\nBAI 1 | Cells and structure | 1\nBAI 2 | Tissues and organs | 3",
                "Cell structure source text for the first lesson. " * 3,
                "Tissue source text for the second lesson. " * 3,
            ):
                pdf.new_page().insert_text((48, 72), text)
            payload = pdf.tobytes()
            pdf.close()
            import_book(workspace, payload, key="source-book", version="v1", title="Source book", author="Publisher", local_rights=True, printed_start=1)
            proposal = detect_toc(workspace, "source-book", pages=[1])
            chapter = proposal["tree"][0]
            self.assertEqual(chapter["title"], "Chương I. CELLS")
            self.assertEqual(len(chapter["lessons"]), 2)
            self.assertEqual(chapter["lessons"][0]["start"], 1)
            self.assertEqual(chapter["lessons"][0]["end"], 2)
            saved = save_toc_tree(workspace, "source-book", [chapter], proposal["provenance"])
            lesson = saved["tree"][0]["lessons"][0]
            state = process_lesson(workspace, "source-book", lesson["id"], None)
            self.assertIsNotNone(page_record(workspace, "source-book", 1))
            self.assertIsNotNone(page_record(workspace, "source-book", 2))
            self.assertIsNone(page_record(workspace, "source-book", 3))
            candidate = export_chapter_candidates(workspace, "source-book", chapter["id"])
            self.assertIsNotNone(candidate["lessons"][0]["structuredPath"])
            self.assertIsNone(candidate["lessons"][1]["structuredPath"])
            structured = json.loads(Path(candidate["lessons"][0]["structuredPath"]).read_text(encoding="utf-8"))
            self.assertEqual(structured["status"], "needs_review")
            self.assertEqual(structured["sourceLesson"]["id"], lesson["id"])
            self.assertTrue(structured["sourceBlocks"])
            self.assertEqual(structured["ocrCoverage"][0]["reviewStatus"], "pending")
            save_review(workspace, "source-book", 1, "accepted", {}, 1)
            save_review(workspace, "source-book", 2, "accepted", {}, 1)
            draft = save_draft(workspace, {
                "bookKey": "source-book", "chapterId": chapter["id"], "sourceLessonId": lesson["id"],
                "packKey": "source-lesson-draft", "title": lesson["title"], "grade": 8, "domain": "MATTER",
                "subjectId": "", "outcomeCode": "", "topic": chapter["title"], "learningObjective": "Read this source",
                "prerequisites": "", "claim": "Source text claim", "pages": [1, 2],
                "sections": [{"heading": "Source", "content": "A reviewed source paragraph for this lesson."}],
                "license": "UNKNOWN", "attribution": "Source book — Publisher", "sourceUrl": "", "basicExercises": None,
            })
            reopened = json.loads(draft_path(Workspace.open(workspace.root), draft["packKey"]).read_text(encoding="utf-8"))
            self.assertEqual(reopened["sourceLessonId"], lesson["id"])
            self.assertEqual(reopened["sourceLesson"]["chapterId"], chapter["id"])
            self.assertEqual(reopened["sourceLesson"]["pdfPageRange"], {"start": 1, "end": 2})
            self.assertEqual(reopened["pages"], [1, 2])
            with self.assertRaisesRegex(ContentToolError, "source Lesson identity is immutable"):
                save_draft(workspace, {
                    "bookKey": "source-book", "chapterId": chapter["id"], "sourceLessonId": chapter["lessons"][1]["id"],
                    "packKey": draft["packKey"], "title": lesson["title"], "grade": 8, "domain": "MATTER",
                    "subjectId": "", "outcomeCode": "", "topic": chapter["title"], "learningObjective": "Read this source",
                    "prerequisites": "", "claim": "Source text claim", "pages": [1],
                    "sections": [{"heading": "Source", "content": "A reviewed source paragraph for this lesson."}],
                    "license": "UNKNOWN", "attribution": "Source book — Publisher", "sourceUrl": "", "basicExercises": None,
                })

    def test_safe_normalization_preserves_vietnamese_and_math(self) -> None:
        decomposed = "Định\u00a0luật   m = 20,8 + 14,2 − 23,3\u200b\n\n\n\\mathrm{NaCl}"
        self.assertEqual(normalize_text(decomposed), "Định luật m = 20,8 + 14,2 − 23,3\n\n\\mathrm{NaCl}")

    def test_browser_multipart_metadata_preserves_utf8(self) -> None:
        boundary = "----browser-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n"
            "Khoa học tự nhiên 8\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: multipart/form-data; boundary={boundary}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        part = next(message.iter_parts())
        self.assertEqual(_multipart_text(part), "Khoa học tự nhiên 8")

    def test_mineru_content_field_keeps_table_text(self) -> None:
        self.assertEqual(_mineru_text({"content": "<table><tr><td>Khối lượng</td><td>11,7 g</td></tr></table>"}), "| Khối lượng | 11,7 g")

    def test_incomplete_real_draft_is_saved_but_not_exported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace.open(init_workspace(Path(temporary) / "workspace", "m1-draft"))
            pdf = pymupdf.open()
            pdf.new_page().insert_text((60, 80), "Reviewed source paragraph for this lesson. " * 4)
            payload = pdf.tobytes()
            pdf.close()
            import_book(workspace, payload, key="real-book", version="v1", title="Real book", author="Publisher", local_rights=True)
            save_chapter(workspace, "real-book", chapter_id="first", title="First", start=1, end=1)
            process_chapter(workspace, "real-book", "first", None)
            save_review(workspace, "real-book", 1, "accepted", {}, 1)
            draft = save_draft(workspace, {"bookKey": "real-book", "chapterId": "first", "packKey": "real-book-first-lesson", "title": "Authored lesson", "grade": 8, "domain": "MATTER", "subjectId": "", "outcomeCode": "", "topic": "First", "learningObjective": "Read the source carefully", "prerequisites": "", "claim": "Source-grounded claim", "pages": [1], "sections": [{"heading": "Main", "content": "This is an authored lesson based on the selected reviewed source."}], "license": "UNKNOWN", "attribution": "Real book — Publisher", "sourceUrl": "", "basicExercises": None})
            self.assertTrue(draft_path(workspace, draft["packKey"]).is_file())
            self.assertFalse(workspace.inside("packs", "real-book-first-lesson.json").exists())
            blockers = export_status(Workspace.open(workspace.root))["blockers"]
            self.assertTrue(any("outcome" in item for item in blockers))
            self.assertTrue(any("rights review" in item for item in blockers))
            stale_output = workspace.inside("exports", "release-manifest.json")
            write_json(stale_output, {"name": "stale", "namespace": "fixture", "packs": [], "sources": []})
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main(["export", str(workspace.root)]), 2)
            for blocker in blockers:
                self.assertIn(blocker, stderr.getvalue())
            self.assertTrue(stale_output.exists())
            self.assertEqual(json.loads(stale_output.read_text(encoding="utf-8"))["name"], "stale")

    def test_book_chapter_resume_review_draft_and_review_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = Workspace.open(init_workspace(root / "workspace", "m1-test"))
            pdf = pymupdf.open()
            for page in range(2):
                pdf.new_page().insert_text((60, 80), ("This is source text for a reviewed science lesson. " * 4) + str(page))
            content = pdf.tobytes()
            pdf.close()
            imported = import_book(workspace, content, key="test-book", version="v1", title="Test science book", author="Test author", local_rights=True, printed_start=1)
            self.assertEqual(imported["pageCount"], 2)
            save_chapter(workspace, "test-book", chapter_id="chapter-one", title="Chapter one", start=1, end=2)
            process_chapter(workspace, "test-book", "chapter-one", None)
            self.assertEqual(chapter_state(workspace, "test-book", "chapter-one")["completed"], 2)
            save_review(workspace, "test-book", 1, "accepted", {"0": "Manually corrected source text"}, 5)
            save_review(workspace, "test-book", 2, "accepted", {}, 2)
            self.assertEqual(build_enrichment_proposal(workspace, "test-book", "chapter-one", [1])["title"], "Chapter one")
            process_chapter(workspace, "test-book", "chapter-one", None, rerun=True)
            self.assertEqual(page_record(workspace, "test-book", 1)["review"]["edits"]["0"], "Manually corrected source text")
            workspace = Workspace.open(root / "workspace")  # Restart the tool from saved files.
            draft = save_draft(workspace, {
                "bookKey": "test-book", "chapterId": "chapter-one", "packKey": "test-book-chapter-one-lesson",
                "title": "A source-grounded lesson", "grade": 8, "domain": "ENERGY", "subjectId": "physics",
                "outcomeCode": "REAL-OUTCOME-TO-CONFIRM", "topic": "Chapter one", "learningObjective": "Read the source text carefully",
                "prerequisites": "", "claim": "This claim is authored from the reviewed source", "pages": [1],
                "sections": [{"heading": "Introduction", "content": "Manually corrected source text and additional operator-authored explanation."}],
                "license": "UNKNOWN", "attribution": "Test science book — Test author", "sourceUrl": "https://example.test/source",
                "sourceArtifactVersionId": "sourceversion00000001",
                "materials": [{"type": "video", "url": "assetv:videoversion00000001", "title": "Reviewed video", "transcript": "Reviewed transcript", "captionUrl": "assetv:captionversion0000001"}],
                "basicExercises": {"id": "exercise-one", "passThreshold": 50, "questions": [{"id": "question-one", "prompt": "What is in the source?", "options": [{"id": "option-a", "text": "Source text"}, {"id": "option-b", "text": "No text"}], "correctOptionId": "option-a"}]},
            })
            self.assertTrue(draft_path(workspace, draft["packKey"]).is_file())
            self.assertEqual(chapter_state(Workspace.open(root / "workspace"), "test-book", "chapter-one")["lessonDrafts"], [draft["packKey"]])
            manifest = build_manifest(workspace, allow_unreviewed=True)
            self.assertEqual(manifest["packs"][0]["lesson"]["basicExercises"]["id"], "exercise-one")
            self.assertEqual(manifest["packs"][0]["lesson"]["questions"], [])
            self.assertEqual(manifest["packs"][0]["lesson"]["materials"][0]["url"], "assetv:videoversion00000001")
            self.assertEqual(manifest["packs"][0]["sources"][0]["artifactVersionId"], "sourceversion00000001")
            status = export_status(workspace)
            self.assertFalse(status["ready"])
            self.assertTrue(any("missing formal rights review" in blocker for blocker in status["blockers"]))

    def test_reviewed_ocr_builds_editable_proposals_and_lab_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace.open(init_workspace(Path(temporary) / "workspace", "enrichment-test"))
            pdf = pymupdf.open()
            page = pdf.new_page()
            page.insert_text((60, 80), "2. Phan ung hoa hoc")
            page.insert_text((60, 120), "Phản ứng hoá học bảo toàn khối lượng của chất phản ứng và sản phẩm. " * 2)
            page.insert_text((60, 160), "3. Dinh luat bao toan")
            page.insert_text((60, 200), "Tổng khối lượng các chất tham gia bằng tổng khối lượng sản phẩm.")
            payload = pdf.tobytes()
            pdf.close()
            import_book(workspace, payload, key="science-book", version="v1", title="Science", author="Publisher", local_rights=True)
            save_chapter(workspace, "science-book", chapter_id="reaction", title="Reaction", start=1, end=1)
            process_chapter(workspace, "science-book", "reaction", None)
            record = page_record(workspace, "science-book", 1)
            record["blocks"][0]["type"] = "paragraph_title"
            record["blocks"][2]["type"] = "paragraph_title"
            write_json(page_path(workspace, "science-book", 1), record)
            save_review(workspace, "science-book", 1, "accepted", {}, 1)
            proposal = build_enrichment_proposal(workspace, "science-book", "reaction", [1])
            self.assertEqual(proposal["status"], "proposed")
            self.assertTrue(proposal["sections"][0]["sourceBlockIds"])
            self.assertTrue(proposal["knowledgeUnits"][0]["claims"])
            self.assertEqual(len(proposal["sections"]), 2)
            self.assertEqual(len(proposal["knowledgeUnits"]), 2)
            self.assertEqual(proposal["title"], "2. Phan ung hoa hoc")
            self.assertEqual(proposal["summary"], " ".join(unit["claims"][0]["text"] for unit in proposal["knowledgeUnits"]))
            self.assertEqual(proposal["knowledgeUnits"][0]["claims"][0]["sourceBlockIds"], [proposal["blocks"][1]["id"]])
            self.assertNotEqual(proposal["blocks"][0]["originalText"], "")

            draft = {
                "packKey": "science-reaction-lesson", "title": "Phản ứng hoá học", "learningObjective": "Mô tả phản ứng hoá học",
                "claim": "Khối lượng được bảo toàn trong phản ứng", "outcomeCode": "VERIFIED-OUTCOME",
                "grade": 8, "domain": "MATTER", "sections": proposal["sections"], "pages": [1], "materials": [],
            }
            with self.assertRaises(ContentToolError):
                suggest_lab_candidates(workspace, draft)
            verification = verify_authoring_context(draft, {
                "outcomes": [{"code": "VERIFIED-OUTCOME", "grade": 8, "domain": "MATTER", "status": "active", "synthetic": False}],
                "assets": [],
                "labs": [{"id": "chemistry", "simulationModelRef": "chemistry@1.0.0", "status": "draft", "challenges": [{"id": "chemistry_001"}]}],
            }, "http://127.0.0.1:4000/api")
            save_verification(workspace, verification)
            candidates = suggest_lab_candidates(workspace, draft)
            self.assertEqual(candidates[0]["modelRef"], "chemistry@1.0.0")
            self.assertEqual(candidates[0]["blueprint"]["challengeIds"], ["chemistry_001"])
            saved = save_lab_candidates(workspace, draft["packKey"], candidates)
            self.assertEqual(saved["status"], "proposed")

    def test_be_context_verifies_pinned_ready_shared_media(self) -> None:
        draft = {
            "packKey": "media-lesson", "outcomeCode": "OUTCOME-1", "grade": 8, "domain": "ENERGY",
            "sourceArtifactVersionId": "sourceversion00000001",
            "materials": [{"type": "video", "url": "assetv:videoversion00000001", "title": "Video", "transcript": "Transcript", "captionUrl": "assetv:captionversion0000001"}],
        }
        context = {
            "outcomes": [{"code": "OUTCOME-1", "grade": 8, "domain": "ENERGY", "status": "active", "synthetic": False}],
            "assets": [
                {"kind": "pdf", "scope": "SHARED_LIBRARY", "status": "ACTIVE", "versions": [{"id": "sourceversion00000001", "status": "READY"}]},
                {"kind": "video", "scope": "SHARED_LIBRARY", "status": "ACTIVE", "versions": [{"id": "videoversion00000001", "status": "READY"}]},
                {"kind": "caption", "scope": "SHARED_LIBRARY", "status": "ACTIVE", "versions": [{"id": "captionversion0000001", "status": "READY"}]},
            ],
            "labs": [],
        }
        verified = verify_authoring_context(draft, context, "http://127.0.0.1:4000/api")
        self.assertEqual(len(verified["assets"]), 3)
        self.assertNotIn("accessToken", json.dumps(verified))
        context["assets"][1]["scope"] = "TEACHER_PRIVATE"
        with self.assertRaisesRegex(ContentToolError, "shared-library"):
            verify_authoring_context(draft, context, "http://127.0.0.1:4000/api")

    def test_gemini_is_off_without_explicit_provider_and_transmission_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace.open(init_workspace(Path(temporary) / "workspace", "gemini-gate"))
            with self.assertRaisesRegex(ContentToolError, "provider policy"):
                gemini_proposal(workspace, "book", "chapter", [1], provider_confirmed=False, transmission_allowed=False)


if __name__ == "__main__":
    unittest.main()
