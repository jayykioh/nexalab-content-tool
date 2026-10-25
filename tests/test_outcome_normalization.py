from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexalab_content_tool.outcome_normalization import _candidate_id, build_outcome_sync_bundle, propose_outcomes, save_outcome_proposal, validate_llm_normalization
from nexalab_content_tool.outcome_normalization import review_outcome_proposal, sync_approved_outcomes
from nexalab_content_tool.workspace import ContentToolError, Workspace, init_workspace


def _lesson(book: str, lesson: str, unit_id: str, title: str, blocks: list[str], page: int) -> dict:
    return {
        "book": {"key": book, "version": "edition-1", "sha256": "a" * 64},
        "sourceLesson": {"id": lesson, "title": f"Lesson {lesson}"},
        "chapter": {"id": "chapter-1", "title": "Chapter 1"},
        "contentReview": {"status": "needs_review"},
        "sourceBlocks": [
            {"id": f"objective-heading-{lesson}", "type": "paragraph_title", "reviewedText": "MỤC TIÊU", "physicalPageIndex": page, "sourceSha256": "a" * 64},
            {"id": f"objective-{lesson}", "type": "text", "reviewedText": "Explain how a simple model represents matter.", "physicalPageIndex": page, "printedPageLabel": str(page - 2), "sourceSha256": "a" * 64},
            *[{"id": block, "type": "text", "reviewedText": "A model represents matter using particles.", "physicalPageIndex": page, "printedPageLabel": str(page - 2), "sourceSha256": "a" * 64} for block in blocks],
        ],
        "learningContent": {
            "knowledgeUnits": [{"id": unit_id, "title": title, "sourceBlockIds": blocks, "claims": [{"id": "claim-1", "text": "A model represents matter using particles.", "sourceBlockIds": [blocks[0]]}]}],
        },
    }


class OutcomeNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp")
        self.workspace = Workspace.open(init_workspace(Path(self.temporary.name) / "workspace", "outcomes-test"))
        structured = self.workspace.inside("exports", "structured")
        structured.mkdir(parents=True)
        (structured / "lesson-one.json").write_text(json.dumps(_lesson("book-a", "lesson-a", "unit-a", "1. Particle model", ["block-a"], 14)), encoding="utf-8")
        (structured / "lesson-two.json").write_text(json.dumps(_lesson("book-b", "lesson-b", "unit-b", "Model particle", ["block-b"], 23)), encoding="utf-8")
        noise = _lesson("book-b", "lesson-c", "unit-c", "� !!!", ["block-c"], 24)
        (structured / "lesson-three.json").write_text(json.dumps(noise), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_extracts_grounded_objectives_and_units_and_deduplicates_across_books(self) -> None:
        taxonomy = {"outcomes": [
            {"code": "EXISTING-01", "statement": "Particle model", "status": "active", "synthetic": False},
            {"code": "SYNTHETIC-01", "statement": "Particle model", "status": "active", "synthetic": True},
        ]}
        proposal = propose_outcomes(self.workspace, taxonomy=taxonomy)
        rerun = propose_outcomes(self.workspace, taxonomy=taxonomy)
        self.assertEqual(proposal["outcomes"], rerun["outcomes"])
        self.assertEqual(proposal["knowledgeUnitMappings"], rerun["knowledgeUnitMappings"])
        self.assertEqual(proposal["coverage"]["sourceLessons"], 3)
        self.assertEqual(proposal["coverage"]["explicitObjectiveCandidates"], 3)
        self.assertEqual(proposal["coverage"]["measurableOutcomeCandidates"], 1)
        shared = proposal["outcomes"][0]
        self.assertEqual(len(shared["evidence"]), 3)
        self.assertEqual({item["bookKey"] for item in shared["evidence"]}, {"book-a", "book-b"})
        self.assertEqual(shared["officialCode"], None)
        self.assertEqual(shared["qualityGate"]["sourceGrounding"], "pass")
        self.assertEqual(shared["qualityGate"]["sourceTextFidelity"], "not_independently_verified")
        self.assertTrue(all(item["status"] == "needs_human_review" for item in proposal["outcomes"]))
        self.assertEqual(len(proposal["sourceConcepts"]), 2)
        self.assertEqual(proposal["coverage"]["ambiguousSourceConcepts"], 2)
        self.assertEqual(len(proposal["knowledgeUnitMappings"]), 2)
        self.assertTrue(all(mapping["outcomeId"] == shared["id"] for mapping in proposal["knowledgeUnitMappings"]))
        self.assertTrue(all(mapping["status"] == "needs_human_review" for mapping in proposal["knowledgeUnitMappings"]))
        self.assertTrue(all(item["officialCode"] is None for item in proposal["sourceConcepts"]))
        path = save_outcome_proposal(self.workspace, proposal, "independent-fixture")
        self.assertTrue(path.exists())
        self.assertRegex(proposal["proposalVersion"], r"^[a-f0-9]{64}$")
        self.assertTrue(self.workspace.inside(".local", "outcomes", "versions", "independent-fixture", f"{proposal['proposalVersion']}.json").exists())
        self.assertEqual(proposal["registrySync"]["ready"], False)

    def test_review_decisions_require_source_verification_and_remain_internal(self) -> None:
        proposal = propose_outcomes(self.workspace)
        save_outcome_proposal(self.workspace, proposal, "review-fixture")
        outcome = proposal["outcomes"][0]
        mapping = proposal["knowledgeUnitMappings"][0]
        details = {"reviewer_name": "Reviewer", "reviewer_email": "reviewer@example.test", "reason": "Verified source text and mapping"}
        approval = {"decision": "approve", "verifiedSourceBlockIds": outcome["evidenceSourceBlockIds"], "registryAttributes": {"grade": 8, "domain": "MATTER", "chapter": "Chapter one"}}
        mapping_approval = {"decision": "approve", "verifiedSourceBlockIds": mapping["sourceBlockIds"]}
        with self.assertRaisesRegex(ContentToolError, "sourceTextVerified"):
            review_outcome_proposal(self.workspace, "review-fixture", outcome_decisions={outcome["id"]: approval}, mapping_decisions={}, source_text_verified=False, **details)
        reviewed = review_outcome_proposal(self.workspace, "review-fixture", outcome_decisions={outcome["id"]: approval}, mapping_decisions={mapping["mappingId"]: mapping_approval}, source_text_verified=True, **details)["proposal"]
        accepted = next(item for item in reviewed["outcomes"] if item["id"] == outcome["id"])
        self.assertEqual(accepted["status"], "approved_internal")
        self.assertIsNone(accepted["officialCode"])
        self.assertFalse(reviewed["registrySync"]["ready"])
        self.assertEqual(len(reviewed["reviewHistory"]), 1)
        self.assertEqual(accepted["qualityGate"]["sourceTextFidelity"], "verified")
        self.assertEqual(reviewed["knowledgeUnitMappings"][0]["status"], "accepted_internal_mapping")
        bundle = build_outcome_sync_bundle(reviewed)
        self.assertEqual(len(bundle["approvedInternalOutcomes"]), 1)
        export = bundle["approvedInternalOutcomes"][0]
        self.assertEqual(export["originType"], "textbook_derived_internal")
        self.assertIsNone(export["officialCode"])
        self.assertEqual(export["grade"], 8)
        self.assertTrue(all(source["sourceDigest"] == "a" * 64 for source in export["sourceEvidence"]))
        self.assertTrue(all(source["sourceLocators"][0]["sourceBlockId"] for source in export["sourceEvidence"]))
        self.assertEqual(export["sourceEvidence"][0]["reviewReference"]["reviewId"], accepted["reviewDecision"]["reviewId"])
        self.assertGreater(bundle["mappingApprovalCoverage"]["unitsWithApprovedOutcomeMapping"], 0)
        self.assertTrue(bundle["reviewedKnowledgeUnitOutcomeMappings"][0]["sourceEvidence"][0]["sourceLocators"])
        rerun = propose_outcomes(self.workspace)
        save_outcome_proposal(self.workspace, rerun, "review-fixture")
        persisted = json.loads(self.workspace.inside(".local", "outcomes", "review-fixture.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["outcomes"][0]["status"], "approved_internal")
        self.assertEqual(persisted["reviewHistory"][0]["reviewId"], accepted["reviewDecision"]["reviewId"])

    def test_outcome_review_explicitly_supports_revise_reject_merge_and_reuse(self) -> None:
        proposal = propose_outcomes(self.workspace)
        original = proposal["outcomes"][0]
        clone_ids = ["out-extra-merge", "out-extra-reuse", "out-extra-reject", "out-extra-revise"]
        for clone_id, suffix in zip(clone_ids, ("merged", "reused", "rejected", "revised")):
            clone = json.loads(json.dumps(original))
            clone.update({"id": clone_id, "internalIdentity": clone_id, "statement": f"Explain the {suffix} model of matter.", "ambiguity": []})
            proposal["outcomes"].append(clone)
        save_outcome_proposal(self.workspace, proposal, "decision-types")
        selected = {item["id"]: {"verifiedSourceBlockIds": item["evidenceSourceBlockIds"]} for item in proposal["outcomes"]}
        decisions = {
            original["id"]: {**selected[original["id"]], "decision": "approve", "registryAttributes": {"grade": 8, "domain": "MATTER", "chapter": "Chapter one"}},
            "out-extra-merge": {**selected["out-extra-merge"], "decision": "merge", "targetOutcomeId": original["id"]},
            "out-extra-reuse": {**selected["out-extra-reuse"], "decision": "reuse", "targetOutcomeCode": "EXISTING-01", "registryAttributes": {"grade": 8, "domain": "MATTER", "chapter": "Chapter one"}},
            "out-extra-reject": {**selected["out-extra-reject"], "decision": "reject"},
            "out-extra-revise": {**selected["out-extra-revise"], "decision": "revise", "statement": "Describe the revised model of matter."},
        }
        reviewed = review_outcome_proposal(self.workspace, "decision-types", outcome_decisions=decisions, mapping_decisions={}, source_text_verified=True, reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Reviewed exact source blocks")["proposal"]
        statuses = {item["id"]: item["status"] for item in reviewed["outcomes"]}
        self.assertEqual(statuses[original["id"]], "approved_internal")
        self.assertEqual(statuses["out-extra-merge"], "merged_into")
        self.assertEqual(statuses["out-extra-reuse"], "reused_outcome")
        self.assertEqual(statuses["out-extra-reject"], "rejected_by_reviewer")
        self.assertEqual(statuses["out-extra-revise"], "needs_revision")
        bundle = build_outcome_sync_bundle(reviewed)
        self.assertEqual(len(bundle["mergedOutcomes"]), 1)
        self.assertEqual(len(bundle["reuseRequests"]), 1)
        self.assertEqual(len(bundle["rejectedOutcomes"]), 1)

    def test_unmapped_unit_requires_an_explicit_documented_decision(self) -> None:
        proposal = propose_outcomes(self.workspace)
        proposal["knowledgeUnitMappings"][0]["outcomeId"] = None
        proposal["knowledgeUnitMappings"][0]["status"] = "unmapped"
        save_outcome_proposal(self.workspace, proposal, "unmapped-review")
        mapping = proposal["knowledgeUnitMappings"][0]
        reviewed = review_outcome_proposal(self.workspace, "unmapped-review", outcome_decisions={}, mapping_decisions={mapping["mappingId"]: {"decision": "unmapped", "verifiedSourceBlockIds": mapping["sourceBlockIds"], "reason": "No outcome correspondence in source"}}, source_text_verified=True, reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Reviewed source evidence")["proposal"]
        decision = next(item for item in reviewed["knowledgeUnitMappings"] if item["mappingId"] == mapping["mappingId"])
        self.assertEqual(decision["status"], "accepted_unmapped")
        bundle = build_outcome_sync_bundle(reviewed)
        self.assertGreater(bundle["mappingApprovalCoverage"]["unitsDocumentedUnmapped"], 0)

    def test_sync_preflight_stops_before_api_when_there_are_no_human_approvals(self) -> None:
        proposal = propose_outcomes(self.workspace)
        save_outcome_proposal(self.workspace, proposal, "no-approval")
        with patch("nexalab_content_tool.curriculum_bootstrap._api_request") as request:
            with self.assertRaisesRegex(ContentToolError, "No explicitly approved outcome"):
                sync_approved_outcomes(self.workspace, "no-approval", "http://127.0.0.1:4000/api", "token")
        request.assert_not_called()

    def test_sync_preflight_stops_when_target_lacks_the_provenance_migration(self) -> None:
        proposal = propose_outcomes(self.workspace)
        outcome = proposal["outcomes"][0]
        save_outcome_proposal(self.workspace, proposal, "missing-provenance")
        review_outcome_proposal(self.workspace, "missing-provenance", outcome_decisions={outcome["id"]: {
            "decision": "approve", "verifiedSourceBlockIds": outcome["evidenceSourceBlockIds"],
            "registryAttributes": {"grade": 8, "domain": "MATTER", "chapter": "Chapter one"},
        }}, mapping_decisions={}, source_text_verified=True, reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Verified source evidence")
        calls = []

        def request(_base, _token, path, body=None, expected_project_ref=None):
            calls.append(path)
            return {"environment": "development", "configuredConnections": 2, "localDevelopmentTarget": True, "outcomeSourceEvidencePersisted": False}

        with patch("nexalab_content_tool.curriculum_bootstrap._api_request", side_effect=request):
            with self.assertRaisesRegex(ContentToolError, "sourceEvidence migration"):
                sync_approved_outcomes(self.workspace, "missing-provenance", "http://127.0.0.1:4000/api", "token")
        self.assertEqual(calls, ["/admin/curriculum-target"])

    def test_sync_writes_only_approved_outcomes_with_source_evidence_after_target_preflight(self) -> None:
        proposal = propose_outcomes(self.workspace)
        outcome = proposal["outcomes"][0]
        save_outcome_proposal(self.workspace, proposal, "sync-approved")
        review_outcome_proposal(self.workspace, "sync-approved", outcome_decisions={outcome["id"]: {
            "decision": "approve",
            "verifiedSourceBlockIds": outcome["evidenceSourceBlockIds"],
            "registryAttributes": {"grade": 8, "domain": "MATTER", "chapter": "Chapter one"},
        }}, mapping_decisions={}, source_text_verified=True, reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Verified source evidence")
        calls = []
        taxonomy = {"outcomes": []}

        def request(_base, _token, path, body=None, expected_project_ref=None):
            calls.append((path, body))
            if path == "/admin/curriculum-target":
                return {"environment": "development", "configuredConnections": 2, "localDevelopmentTarget": True, "outcomeSourceEvidencePersisted": True}
            if path == "/admin/taxonomy":
                return taxonomy
            if path == "/admin/outcomes":
                taxonomy["outcomes"].append({**body, "status": "active", "synthetic": False})
            return {"created": True}

        with patch("nexalab_content_tool.curriculum_bootstrap._api_request", side_effect=request):
            result = sync_approved_outcomes(self.workspace, "sync-approved", "http://127.0.0.1:4000/api", "token")
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual([path for path, _ in calls], ["/admin/curriculum-target", "/admin/taxonomy", "/admin/outcomes", "/admin/taxonomy"])
        body = next(body for path, body in calls if path == "/admin/outcomes")
        self.assertIsNone(body.get("officialCode"))
        self.assertEqual(body["sourceEvidence"][0]["originType"], "textbook_derived_internal")
        self.assertTrue(body["sourceEvidence"][0]["sourceLocators"][0]["sourceBlockId"])
        self.assertFalse(result["publishPerformed"])
        self.assertFalse(result["lessonWritesPerformed"])

    def test_sync_reuse_appends_provenance_to_existing_outcome(self) -> None:
        proposal = propose_outcomes(self.workspace)
        outcome = proposal["outcomes"][0]
        save_outcome_proposal(self.workspace, proposal, "sync-reuse")
        review_outcome_proposal(self.workspace, "sync-reuse", outcome_decisions={outcome["id"]: {
            "decision": "reuse", "targetOutcomeCode": "EXISTING-01",
            "verifiedSourceBlockIds": outcome["evidenceSourceBlockIds"],
            "registryAttributes": {"grade": 8, "domain": "MATTER", "chapter": "Chapter one"},
        }}, mapping_decisions={}, source_text_verified=True, reviewer_name="Reviewer", reviewer_email="reviewer@example.test", reason="Reuse approved BE outcome")
        calls = []
        existing = {"code": "EXISTING-01", "grade": 8, "domain": "MATTER", "chapter": "Chapter one", "statement": "Existing registry statement.", "status": "active", "synthetic": False, "sourceEvidence": []}
        taxonomy = {"outcomes": [existing]}

        def request(_base, _token, path, body=None, expected_project_ref=None):
            calls.append((path, body))
            if path == "/admin/curriculum-target":
                return {"environment": "development", "configuredConnections": 2, "localDevelopmentTarget": True, "outcomeSourceEvidencePersisted": True}
            if path == "/admin/taxonomy":
                return taxonomy
            if path == "/admin/outcomes/EXISTING-01":
                existing["sourceEvidence"].extend(body["sourceEvidence"])
            return {"updated": True}

        with patch("nexalab_content_tool.curriculum_bootstrap._api_request", side_effect=request):
            result = sync_approved_outcomes(self.workspace, "sync-reuse", "http://127.0.0.1:4000/api", "token")
        self.assertEqual([path for path, _ in calls], ["/admin/curriculum-target", "/admin/taxonomy", "/admin/outcomes/EXISTING-01", "/admin/taxonomy"])
        evidence_body = next(body for path, body in calls if path == "/admin/outcomes/EXISTING-01")
        self.assertEqual(len(evidence_body["sourceEvidence"]), len(outcome["evidence"]))
        self.assertEqual(result["reused"], ["EXISTING-01"])

    def test_optional_llm_must_return_strict_schema_and_grounded_evidence(self) -> None:
        candidate = {"evidenceSourceBlockIds": ["block-a"]}
        candidate["possibleDuplicateIds"] = ["out-allowed"]
        valid = {"normalizedStatement": "Explain a particle model of matter.", "evidenceSourceBlockIds": ["block-a"], "confidence": 0.8, "ambiguity": [], "mergeWithOutcomeId": None, "suggestedOutcomeIds": []}
        self.assertEqual(validate_llm_normalization(candidate, valid)["status"], "needs_human_review")
        invalid = {**valid, "evidenceSourceBlockIds": ["invented-block"]}
        with self.assertRaisesRegex(ContentToolError, "source-grounding"):
            validate_llm_normalization(candidate, invalid)
        with self.assertRaisesRegex(ContentToolError, "source-grounding"):
            validate_llm_normalization(candidate, {**valid, "mergeWithOutcomeId": "out-not-similar"})
        with self.assertRaisesRegex(ContentToolError, "strict outcome proposal schema"):
            validate_llm_normalization(candidate, {**valid, "officialCode": "made-up"})

    def test_stable_candidate_identity_preserves_statement_word_order(self) -> None:
        self.assertNotEqual(_candidate_id("Matter affects energy"), _candidate_id("Energy affects matter"))


if __name__ == "__main__":
    unittest.main()
