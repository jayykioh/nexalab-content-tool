from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf

from nexalab_content_tool.m1_workflow import (
    _mineru_text, chapter_state, draft_path, export_status, import_book, page_record,
    process_chapter, save_chapter, save_draft, save_review,
)
from nexalab_content_tool.manifest import build_manifest
from nexalab_content_tool.workspace import Workspace, init_workspace


class M1WorkflowTests(unittest.TestCase):
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
                "basicExercises": {"id": "exercise-one", "passThreshold": 50, "questions": [{"id": "question-one", "prompt": "What is in the source?", "options": [{"id": "option-a", "text": "Source text"}, {"id": "option-b", "text": "No text"}], "correctOptionId": "option-a"}]},
            })
            self.assertTrue(draft_path(workspace, draft["packKey"]).is_file())
            manifest = build_manifest(workspace, allow_unreviewed=True)
            self.assertEqual(manifest["packs"][0]["lesson"]["basicExercises"]["id"], "exercise-one")
            self.assertEqual(manifest["packs"][0]["lesson"]["questions"], [])
            status = export_status(workspace)
            self.assertFalse(status["ready"])
            self.assertTrue(any("missing formal rights review" in blocker for blocker in status["blockers"]))


if __name__ == "__main__":
    unittest.main()
