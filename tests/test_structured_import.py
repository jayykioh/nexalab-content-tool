from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexalab_content_tool.structured_import import import_structured_lessons
from nexalab_content_tool.workspace import ContentToolError, Workspace, init_workspace, write_json


def candidate(source_id: str = "source-lesson-1") -> dict:
    return {
        "schemaVersion": 1,
        "kind": "structured-lesson-candidate",
        "status": "needs_review",
        "book": {"key": "sgk-khtn8", "title": "Local fixture", "author": "Fixture", "version": "1", "sha256": "a" * 64},
        "chapter": {"id": "chapter-1", "title": "Chapter"},
        "sourceLesson": {"id": source_id, "title": "Lesson", "tocProvenance": {"row": 4}},
        "printedPageRange": {"start": 10, "end": 11},
        "pdfPageRange": {"start": 20, "end": 21},
        "sourcePdf": "source.pdf",
        "ocrCoverage": [{"pdfPage": 20, "sourceVersion": "1", "sourceSha256": "a" * 64, "sourceBlockIds": ["block-1"]}],
        "sourceBlocks": [{"id": "block-1", "text": "source", "provenance": {"page": 20}}],
        "learningContent": {
            "sections": [{"id": "section-1", "content": "Learning text"}],
            "summary": "Summary",
            "summarySourceBlockIds": ["block-1"],
            "knowledgeUnits": [{"id": "unit-1", "claims": [{"id": "claim-1", "text": "Claim"}]}],
            "definitions": [],
            "formulas": [{"id": "formula-1", "latex": "v = s/t"}],
            "tables": [{"id": "table-1", "rows": [["a", "b"]]}],
            "sourceImages": [],
            "examples": [],
            "basicExercises": [],
        },
        "warnings": [],
        "contentReview": {"status": "needs_review", "history": []},
        "mappingReview": {"status": "unmapped", "notes": ["curriculum mapping is deferred"]},
    }


class StructuredImportTests(unittest.TestCase):
    def make_workspace(self, root: Path, lessons: list[dict]) -> Workspace:
        init_workspace(root, "structured-import-test")
        directory = root / "exports" / "structured"
        directory.mkdir(parents=True, exist_ok=True)
        for lesson in lessons:
            write_json(directory / f"{lesson['sourceLesson']['id']}.json", lesson)
        return Workspace.open(root)

    def test_full_payload_readback_and_repeat_import_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            lesson = candidate()
            workspace = self.make_workspace(Path(temporary) / "workspace", [lesson])
            stored: dict[str, dict] = {}

            def api(_base, _token, path, *, body=None, expected_project_ref=None):
                if path == "/admin/curriculum-target":
                    return {"environment": "development", "configuredConnections": 2, "localDevelopmentTarget": True}
                if path == "/admin/structured-lessons/import":
                    results = []
                    for item in body["lessons"]:
                        identity = f"{item['book']['key']}:{item['chapter']['id']}:{item['sourceLesson']['id']}"
                        draft_id = f"draft-{item['sourceLesson']['id']}"
                        digest = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                        status = "unchanged" if draft_id in stored else "imported"
                        stored[draft_id] = {"id": draft_id, "digest": digest, "status": "draft", "manifest": item}
                        results.append({"sourceLessonId": item["sourceLesson"]["id"], "identity": identity, "status": status, "draftId": draft_id, "digest": digest})
                    return {"count": len(results), "results": results}
                return stored[Path(path).name]

            with patch("nexalab_content_tool.structured_import._request_json", side_effect=api):
                first = import_structured_lessons(workspace, "http://127.0.0.1:4100/api", "admin-token")
                second = import_structured_lessons(workspace, "http://127.0.0.1:4100/api", "admin-token")

            self.assertEqual((first["imported"], first["reused"], first["rejected"]), (1, 0, 0))
            self.assertEqual((second["imported"], second["reused"], second["rejected"]), (0, 1, 0))
            self.assertEqual(stored["draft-source-lesson-1"]["manifest"], lesson)
            self.assertEqual(stored["draft-source-lesson-1"]["manifest"]["learningContent"]["formulas"], lesson["learningContent"]["formulas"])
            self.assertEqual(stored["draft-source-lesson-1"]["manifest"]["learningContent"]["tables"], lesson["learningContent"]["tables"])
            self.assertEqual(stored["draft-source-lesson-1"]["manifest"]["sourceBlocks"], lesson["sourceBlocks"])

    def test_remote_target_requires_explicit_project_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.make_workspace(Path(temporary) / "workspace", [candidate()])
            with patch("nexalab_content_tool.structured_import._request_json") as api:
                api.return_value = {"environment": "development", "configuredConnections": 2, "localDevelopmentTarget": False, "remoteDevelopmentTarget": True, "projectRef": "other-project"}
                with self.assertRaises(ContentToolError):
                    import_structured_lessons(workspace, "https://api.example.test/api", "admin-token", "expected-project")
                self.assertEqual(api.call_count, 1)


if __name__ == "__main__":
    unittest.main()
