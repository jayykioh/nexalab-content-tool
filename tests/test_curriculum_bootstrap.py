from __future__ import annotations

import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from nexalab_content_tool.curriculum_bootstrap import apply_approved_mappings, propose_registry, review_registry, sync_approved_registry
from nexalab_content_tool.m1_workflow import import_book, process_book, save_draft, save_review, save_toc_tree
from nexalab_content_tool.workspace import ContentToolError, Workspace, init_workspace, read_json


class CurriculumBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Workspace.open(init_workspace(Path(self.temporary.name) / "workspace", "curriculum-test"))
        self.proposal = {
            "framework": {
                "key": "VN2018", "version": "2025.1", "title": "Vietnam general education curriculum",
                "source": {"authority": "Ministry of Education", "url": "https://example.gov.vn/curriculum.pdf", "publishedAt": "2018-12-26", "accessedAt": "2026-10-24", "sha256": "a" * 64},
            },
            "textbookIdentity": {"bookKey": "book-one", "version": "edition-one"},
            "subjects": [{"id": "khtn", "name": "Khoa học tự nhiên", "chapters": [{"code": "KHTN-G8-MATTER-01", "title": "Matter", "grade": 8, "domain": "MATTER", "topics": [{"code": "KHTN-G8-MATTER-ATOMS", "title": "Atoms", "outcomes": [{"key": "atomic-model", "statement": "Describe a simple model of an atom.", "sourceLocator": "page 14, section 2"}]}]}]}],
            "mappings": [{"lessonId": "book-one-lesson-1", "knowledgeUnitId": "unit-1", "outcomeKeys": ["atomic-model"], "sourcePages": [8], "rationale": "Describes atom structure"}],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_proposal_uses_stable_internal_code_and_exact_active_outcome_reuse(self) -> None:
        code = "G8-MATTER-ATOM"
        taxonomy = {"outcomes": [{"code": code, "grade": 8, "domain": "MATTER", "statement": "Describe a simple model of an atom.", "status": "active", "synthetic": False}]}
        result = propose_registry(self.workspace, self.proposal, taxonomy)
        outcome = result["registry"]["subjects"][0]["chapters"][0]["topics"][0]["outcomes"][0]
        self.assertEqual(outcome["approvedCode"], code)
        self.assertIsNone(outcome["officialCode"])
        self.assertTrue(outcome["internalCode"].startswith("NX-VN201-8-MA-"))
        self.assertLessEqual(len(outcome["internalCode"]), 40)
        self.assertTrue(result["registry"]["framework"]["id"].startswith("NX-FW-"))

    def test_local_proposals_accept_future_grade_and_subject_domains_but_be_sync_preflights(self) -> None:
        proposal = json.loads(json.dumps(self.proposal))
        chapter = proposal["subjects"][0]["chapters"][0]
        chapter.update({"grade": 6, "domain": "BIOLOGY"})
        result = propose_registry(self.workspace, proposal)
        outcome = result["registry"]["subjects"][0]["chapters"][0]["topics"][0]["outcomes"][0]
        mapping_id = result["registry"]["mappings"][0]["id"]
        review_registry(self.workspace, "VN2018", "2025.1", outcome_codes={"atomic-model": outcome["internalCode"]}, mapping_ids=[mapping_id], reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Verified source and mapping", source_verified=True)
        with patch("nexalab_content_tool.curriculum_bootstrap._api_request") as request:
            with self.assertRaisesRegex(ContentToolError, "only accepts grades 8-9"):
                sync_approved_registry(self.workspace, "VN2018", "2025.1", "http://127.0.0.1:4000/api", "ephemeral")
        request.assert_not_called()

    def test_non_exact_outcome_reuse_requires_an_explicit_reviewer_choice(self) -> None:
        candidate_code = "G8-MATTER-MODEL"
        taxonomy = {"outcomes": [{"code": candidate_code, "grade": 8, "domain": "MATTER", "statement": "Use a model to explain atom structure.", "status": "active", "synthetic": False}]}
        proposed = propose_registry(self.workspace, self.proposal, taxonomy)
        outcome = proposed["registry"]["subjects"][0]["chapters"][0]["topics"][0]["outcomes"][0]
        self.assertEqual(outcome["reuseCandidates"], [])
        self.assertEqual(outcome["reviewCandidates"], [candidate_code])
        self.assertIsNone(outcome["approvedCode"])
        reviewed = review_registry(self.workspace, "VN2018", "2025.1", outcome_codes={"atomic-model": candidate_code}, mapping_ids=[], reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Confirmed equivalent outcome", source_verified=True)
        self.assertEqual(reviewed["registry"]["subjects"][0]["chapters"][0]["topics"][0]["outcomes"][0]["approvedCode"], candidate_code)

    def test_unapproved_registry_cannot_sync_and_source_must_be_reviewed(self) -> None:
        propose_registry(self.workspace, self.proposal)
        with self.assertRaisesRegex(ContentToolError, "explicitly approved"):
            sync_approved_registry(self.workspace, "VN2018", "2025.1", "http://127.0.0.1:4000/api", "token")
        with self.assertRaisesRegex(ContentToolError, "verify the official source"):
            review_registry(self.workspace, "VN2018", "2025.1", outcome_codes={"atomic-model": "NX-VN2018-8-MA-ATOMIC-MOD-00000000"}, mapping_ids=[], reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="source checked")

    def test_sync_only_calls_admin_apis_for_approved_missing_records(self) -> None:
        result = propose_registry(self.workspace, self.proposal)
        code = result["registry"]["subjects"][0]["chapters"][0]["topics"][0]["outcomes"][0]["internalCode"]
        mapping_id = result["registry"]["mappings"][0]["id"]
        review_registry(self.workspace, "VN2018", "2025.1", outcome_codes={"atomic-model": code}, mapping_ids=[mapping_id], reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Verified official source and Lesson mapping", source_verified=True)
        taxonomy = {"frameworks": [], "subjects": [], "chapters": [], "topics": [], "outcomes": []}
        calls: list[tuple[str, dict | None]] = []

        def request(_base: str, _token: str, path: str, body: dict | None = None, expected_project_ref: str | None = None):
            calls.append((path, body))
            if path == "/admin/curriculum-target":
                return {"environment": "development", "configuredConnections": 2, "localDevelopmentTarget": True, "outcomeSourceEvidencePersisted": True}
            if path == "/admin/taxonomy":
                return taxonomy
            return {"created": True}

        with patch("nexalab_content_tool.curriculum_bootstrap._api_request", side_effect=request):
            sync = sync_approved_registry(self.workspace, "VN2018", "2025.1", "http://127.0.0.1:4000/api", "ephemeral")
        self.assertEqual([path for path, _ in calls], ["/admin/curriculum-target", "/admin/taxonomy", "/admin/subjects", "/admin/frameworks", "/admin/chapters", "/admin/outcomes", "/admin/topics"])
        self.assertFalse(sync["publishPerformed"])
        self.assertTrue(all(body is None or "reason" in body for _, body in calls))

    def test_sync_is_idempotent_after_be_records_exist(self) -> None:
        proposed = propose_registry(self.workspace, self.proposal)
        code = proposed["registry"]["subjects"][0]["chapters"][0]["topics"][0]["outcomes"][0]["internalCode"]
        mapping_id = proposed["registry"]["mappings"][0]["id"]
        review_registry(self.workspace, "VN2018", "2025.1", outcome_codes={"atomic-model": code}, mapping_ids=[mapping_id], reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Verified source and mapping", source_verified=True)
        taxonomy = {"frameworks": [], "subjects": [], "chapters": [], "topics": [], "outcomes": []}
        calls: list[str] = []

        def request(_base: str, _token: str, path: str, body: dict | None = None, expected_project_ref: str | None = None):
            calls.append(path)
            if path == "/admin/curriculum-target":
                return {"environment": "development", "configuredConnections": 2, "localDevelopmentTarget": True, "outcomeSourceEvidencePersisted": True}
            if path == "/admin/taxonomy":
                return taxonomy
            if path == "/admin/subjects":
                taxonomy["subjects"].append({"id": body["id"], "name": body["name"]})
            elif path == "/admin/frameworks":
                taxonomy["frameworks"].append({"id": body["id"], "frameworkKey": body["frameworkKey"], "title": body["title"], "version": body["version"], "sourceMetadata": body["sourceMetadata"], "subjects": body["subjects"]})
            elif path == "/admin/chapters":
                taxonomy["chapters"].append({key: body[key] for key in ("code", "subjectId", "grade", "domain", "title")})
            elif path == "/admin/outcomes":
                taxonomy["outcomes"].append({key: body[key] for key in ("code", "grade", "domain", "statement", "sourceEvidence") } | {"status": "active", "synthetic": False})
            elif path == "/admin/topics":
                taxonomy["topics"].append({key: body[key] for key in ("code", "chapterCode", "title", "outcomeCodes")})
            return {"created": True}

        with patch("nexalab_content_tool.curriculum_bootstrap._api_request", side_effect=request):
            first = sync_approved_registry(self.workspace, "VN2018", "2025.1", "http://127.0.0.1:4000/api", "ephemeral")
            first_call_count = len(calls)
            second = sync_approved_registry(self.workspace, "VN2018", "2025.1", "http://127.0.0.1:4000/api", "ephemeral")
        self.assertEqual(len(first["created"]), 5)
        self.assertEqual(second["created"], [])
        self.assertEqual(len(second["reused"]), 5)
        self.assertEqual(calls[first_call_count:], ["/admin/curriculum-target", "/admin/taxonomy"])

    def test_sync_rejects_remote_target(self) -> None:
        with self.assertRaisesRegex(ContentToolError, "local BE API or an explicitly verified remote development project"):
            from nexalab_content_tool.curriculum_bootstrap import _api_request
            _api_request("https://api.example.test", "token", "/admin/taxonomy")

    def test_sync_stops_before_taxonomy_or_writes_when_be_target_is_not_verified_local(self) -> None:
        proposed = propose_registry(self.workspace, self.proposal)
        code = proposed["registry"]["subjects"][0]["chapters"][0]["topics"][0]["outcomes"][0]["internalCode"]
        mapping_id = proposed["registry"]["mappings"][0]["id"]
        review_registry(self.workspace, "VN2018", "2025.1", outcome_codes={"atomic-model": code}, mapping_ids=[mapping_id], reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Verified source and mapping", source_verified=True)
        calls = []

        def request(_base: str, _token: str, path: str, body: dict | None = None, expected_project_ref: str | None = None):
            calls.append(path)
            return {"environment": "production", "configuredConnections": 2, "localDevelopmentTarget": False, "outcomeSourceEvidencePersisted": False}

        with patch("nexalab_content_tool.curriculum_bootstrap._api_request", side_effect=request):
            with self.assertRaisesRegex(ContentToolError, "CurriculumOutcome.sourceEvidence migration"):
                sync_approved_registry(self.workspace, "VN2018", "2025.1", "http://127.0.0.1:4000/api", "ephemeral")
        self.assertEqual(calls, ["/admin/curriculum-target"])

    def test_remote_sync_requires_matching_allowlisted_project_ref(self) -> None:
        proposed = propose_registry(self.workspace, self.proposal)
        code = proposed["registry"]["subjects"][0]["chapters"][0]["topics"][0]["outcomes"][0]["internalCode"]
        mapping_id = proposed["registry"]["mappings"][0]["id"]
        review_registry(self.workspace, "VN2018", "2025.1", outcome_codes={"atomic-model": code}, mapping_ids=[mapping_id], reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Verified source and mapping", source_verified=True)
        calls: list[str] = []

        def request(_base: str, _token: str, path: str, body: dict | None = None, expected_project_ref: str | None = None):
            calls.append(path)
            if path == "/admin/curriculum-target":
                return {"environment": "development", "configuredConnections": 2, "localDevelopmentTarget": False, "remoteDevelopmentTarget": True, "projectRef": "devproject", "outcomeSourceEvidencePersisted": True}
            if path == "/admin/taxonomy":
                return {"frameworks": [], "subjects": [{"id": "khtn", "name": "Khoa học tự nhiên"}], "chapters": [], "topics": [], "outcomes": []}
            return {"created": True}

        with patch("nexalab_content_tool.curriculum_bootstrap._api_request", side_effect=request):
            sync_approved_registry(self.workspace, "VN2018", "2025.1", "https://dev-api.example.test/api", "ephemeral", "devproject")
        self.assertEqual(calls[:2], ["/admin/curriculum-target", "/admin/taxonomy"])

        with patch("nexalab_content_tool.curriculum_bootstrap._api_request", side_effect=request):
            with self.assertRaisesRegex(ContentToolError, "did not confirm the requested"):
                sync_approved_registry(self.workspace, "VN2018", "2025.1", "https://dev-api.example.test/api", "ephemeral", "otherproject")

    def test_approved_mapping_populates_existing_pack_without_rewriting_lesson_content(self) -> None:
        pdf = pymupdf.open()
        pdf.new_page().insert_text((60, 80), "A source paragraph with reviewed evidence for the Lesson. " * 5)
        payload = pdf.tobytes()
        pdf.close()
        book = import_book(self.workspace, payload, key="book-one", version="edition-one", title="Book one", author="Publisher", local_rights=True)
        save_toc_tree(self.workspace, "book-one", [{"id": "chapter-one", "title": "Chapter one", "start": 1, "end": 1, "lessons": [{"id": "lesson-one", "title": "Lesson one", "start": 1, "end": 1, "printedStart": 1, "printedEnd": 1}]}], {"sourceSha256": book["sha256"], "method": "test"})
        process_book(self.workspace, "book-one", None)
        save_review(self.workspace, "book-one", 1, "accepted", {})
        authored = {"bookKey": "book-one", "chapterId": "chapter-one", "sourceLessonId": "lesson-one", "packKey": "book-one-lesson-one", "title": "Authored title", "grade": 8, "domain": "MATTER", "subjectId": "", "outcomeCode": "", "topic": "Book chapter", "learningObjective": "Describe the source topic clearly.", "prerequisites": "", "claim": "A reviewed source claim.", "pages": [1], "sections": [{"heading": "Human heading", "content": "Human-edited lesson body."}], "knowledgeUnits": [{"id": "unit-one", "title": "Human unit", "claims": [{"id": "claim-one", "text": "A reviewed claim."}]}], "license": "UNKNOWN", "attribution": "Book one — Publisher", "sourceUrl": "", "sourceArtifactVersionId": ""}
        before = save_draft(self.workspace, authored)
        self.proposal["mappings"] = [{"lessonId": "lesson-one", "knowledgeUnitId": "unit-one", "outcomeKeys": ["atomic-model"], "sourcePages": [1], "rationale": "Curriculum mapping reviewed"}]
        proposal = propose_registry(self.workspace, self.proposal)
        mapping_id = proposal["registry"]["mappings"][0]["id"]
        outcome_code = proposal["registry"]["subjects"][0]["chapters"][0]["topics"][0]["outcomes"][0]["internalCode"]
        reviewed = review_registry(self.workspace, "VN2018", "2025.1", outcome_codes={"atomic-model": outcome_code}, mapping_ids=[mapping_id], reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Verified source and mapping", source_verified=True)
        result = apply_approved_mappings(self.workspace, reviewed["registry"])
        self.assertEqual(result, {"applied": ["book-one-lesson-one"], "blockers": []})
        after = read_json(self.workspace.inside(".local", "lessons", "book-one-lesson-one.json"))
        pack = read_json(self.workspace.inside("packs", "book-one-lesson-one.json"))["pack"]
        self.assertEqual(after["sections"], before["sections"])
        self.assertEqual(after["knowledgeUnits"][0]["title"], "Human unit")
        self.assertEqual(pack["outcomeCodes"], [outcome_code])
        self.assertEqual(pack["knowledgeUnits"][0]["outcomeCodes"], [outcome_code])


if __name__ == "__main__":
    unittest.main()
