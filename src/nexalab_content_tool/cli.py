from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from .backend import run_apply, run_plan
from .curriculum_bootstrap import propose_registry, review_registry, sync_approved_registry
from .extract import extract_native_pdf
from .identity import reserve_id
from .manifest import export_manifest
from .m0a_review import launch_review, launch_studio
from .m1_workflow import export_status
from .outcome_normalization import export_outcome_sync_bundle, propose_outcomes, review_outcome_proposal, save_outcome_proposal, sync_approved_outcomes
from .structured import export_book_candidates, export_chapter_candidates, validate_book_outputs
from .structured_import import import_structured_lessons as import_structured_lesson_drafts
from .report import render_report
from .workspace import ContentToolError, Workspace, init_workspace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexalab-content", description="Prepare reviewed NexaLab content locally")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a local file-based workspace")
    init.add_argument("workspace")
    init.add_argument("--name", default="nexalab-content-pilot")

    extract = commands.add_parser("extract", help="extract native text from a rights-confirmed PDF")
    extract.add_argument("workspace")
    extract.add_argument("--source", required=True)
    extract.add_argument("--version", required=True)
    extract.add_argument("--file", required=True)

    identity = commands.add_parser("id", help="reserve an operator-authored stable ID")
    identity.add_argument("workspace")
    identity.add_argument("--kind", required=True)
    identity.add_argument("--id", required=True)
    identity.add_argument("--owner", required=True)

    report = commands.add_parser("report", help="render a static local review report")
    report.add_argument("workspace")
    report.add_argument("--output")

    review = commands.add_parser("review", help="review local MinerU OCR beside source PDF pages")
    review.add_argument("workspace")
    review.add_argument("--pdf", required=True)
    review.add_argument("--mineru-zip", required=True)
    review.add_argument("--port", type=int, default=0)

    studio = commands.add_parser("studio", help="open the local PDF import and OCR review UI")
    studio.add_argument("workspace")
    studio.add_argument("--port", type=int, default=8765)
    studio.add_argument("--mineru-bin", help="path to local mineru-kit executable; defaults to NEXALAB_MINERU_KIT or PATH")

    export = commands.add_parser("export", help="export a deterministic current-schema release manifest")
    export.add_argument("workspace")
    export.add_argument("--output")

    resolve = commands.add_parser("resolve-lesson", help="apply decisions for one Lesson and build its canonical content")
    resolve.add_argument("workspace")
    resolve.add_argument("--lesson", required=True)
    resolve.add_argument("--dir", required=True, help="folder with authoring.json and decisions.json, relative to the workspace")
    resolve.add_argument("--report", help="where to write blocked-report.json when items are unresolved")
    resolve.add_argument("--no-apply", action="store_true")

    contract = commands.add_parser("export-lesson-contract", help="export Candidate and Release Pack for one resolved Lesson")
    contract.add_argument("workspace")
    contract.add_argument("--lesson", required=True)
    contract.add_argument("--out", required=True, help="output folder, relative to the workspace")

    verify = commands.add_parser("verify-lesson-contract", help="independently check an exported one-Lesson contract")
    verify.add_argument("workspace")
    verify.add_argument("--lesson", required=True)
    verify.add_argument("--dir", required=True)
    verify.add_argument("--out", required=True)

    structured = commands.add_parser("export-structured", help="export reviewable source Lesson JSON and a BE mapping candidate")
    structured.add_argument("workspace")
    structured.add_argument("--book", required=True)
    structured.add_argument("--chapter", help="omit to export the entire book")
    validate = commands.add_parser("validate-structured", help="check current OCR, provenance and Structured JSON completeness")
    validate.add_argument("workspace")
    validate.add_argument("--book", required=True)

    structured_import = commands.add_parser("structured-import", help="import local Structured Lesson JSON files as private BE drafts")
    structured_import.add_argument("workspace")
    structured_import.add_argument("--api-base", required=True, help="BE API base URL, for example http://127.0.0.1:4100/api")
    structured_import.add_argument("--expected-project-ref", help="exact allowlisted Supabase development project ref for a remote BE API")

    curriculum_propose = commands.add_parser("curriculum-propose", help="create a versioned local curriculum registry proposal from verified source statements")
    curriculum_propose.add_argument("workspace")
    curriculum_propose.add_argument("--input", required=True, help="proposal JSON; source identity and locators are required")
    curriculum_propose.add_argument("--taxonomy", help="optional saved /admin/taxonomy JSON for exact-match reuse suggestions")
    curriculum_propose.add_argument("--api-base", help="read current BE taxonomy from this API (token comes from NEXALAB_ADMIN_ACCESS_TOKEN)")

    curriculum_review = commands.add_parser("curriculum-review", help="record explicit human approvals for proposed outcomes and mappings")
    curriculum_review.add_argument("workspace")
    curriculum_review.add_argument("--framework", required=True)
    curriculum_review.add_argument("--version", required=True)
    curriculum_review.add_argument("--input", required=True, help="JSON with outcomeCodes, mappingIds, reviewerName, reviewerEmail and reason")

    curriculum_sync = commands.add_parser("curriculum-sync", help="idempotently create approved missing curriculum through verified BE admin APIs")
    curriculum_sync.add_argument("workspace")
    curriculum_sync.add_argument("--framework", required=True)
    curriculum_sync.add_argument("--version", required=True)
    curriculum_sync.add_argument("--api-base", required=True, help="BE API base URL; remote use also requires --expected-project-ref")
    curriculum_sync.add_argument("--expected-project-ref", help="exact allowlisted Supabase project ref expected from /admin/curriculum-target")

    outcomes = commands.add_parser("outcomes-propose", help="extract evidence-backed, review-only curriculum outcome candidates from Structured Lessons")
    outcomes.add_argument("workspace")
    outcomes.add_argument("--taxonomy", help="optional /admin/taxonomy JSON snapshot for exact reuse suggestions")
    outcomes.add_argument("--name", default="proposal", help="local proposal filename under .local/outcomes")
    outcomes.add_argument("--llm-proposals", help="optional JSON object of candidate ID to strict, source-grounded model proposal")
    outcomes.add_argument("--curriculum-source-metadata", help="optional source catalog JSON; its document checksum remains null unless the source file itself is pinned")

    outcomes_review = commands.add_parser("outcomes-review", help="record human decisions for textbook-derived internal candidates and mappings")
    outcomes_review.add_argument("workspace")
    outcomes_review.add_argument("--name", default="proposal", help="proposal filename under .local/outcomes")
    outcomes_review.add_argument("--input", required=True, help="review JSON with decisions, reviewer, reason and sourceTextVerified")

    outcomes_export = commands.add_parser("outcomes-export", help="materialize approved-only outcome and mapping exports plus sync preflight")
    outcomes_export.add_argument("workspace")
    outcomes_export.add_argument("--name", default="proposal", help="proposal filename under .local/outcomes")

    outcomes_sync = commands.add_parser("outcomes-sync", help="sync only explicitly approved internal outcomes through BE admin APIs")
    outcomes_sync.add_argument("workspace")
    outcomes_sync.add_argument("--name", default="proposal", help="proposal filename under .local/outcomes")
    outcomes_sync.add_argument("--api-base", required=True, help="BE API base URL; remote use also requires --expected-project-ref")
    outcomes_sync.add_argument("--expected-project-ref", help="exact allowlisted Supabase project ref expected from /admin/curriculum-target")

    plan = commands.add_parser("plan", help="run the authoritative NexaLab backend dry run")
    plan.add_argument("workspace")
    plan.add_argument("--backend", required=True)
    plan.add_argument("--target", required=True)

    apply = commands.add_parser("apply", help="apply through the backend CLI after a matching dry-run digest")
    apply.add_argument("workspace")
    apply.add_argument("--backend", required=True)
    apply.add_argument("--target", required=True)
    apply.add_argument("--initiated-by", required=True, help="active NexaLab account email checked by the backend")
    apply.add_argument("--approved-by", required=True, help="active admin email checked by the backend")
    apply.add_argument("--confirm-digest", required=True, help="exact digest from the reviewed backend plan")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            print(init_workspace(args.workspace, args.name))
            return 0
        workspace = Workspace.open(args.workspace)
        if args.command == "extract":
            print(extract_native_pdf(workspace, args.source, args.version, args.file))
            return 0
        if args.command == "id":
            added = reserve_id(workspace, args.kind, args.id, args.owner)
            print("reserved" if added else "already reserved")
            return 0
        if args.command == "report":
            print(render_report(workspace, args.output))
            return 0
        if args.command == "review":
            launch_review(workspace, args.pdf, args.mineru_zip, args.port)
            return 0
        if args.command == "studio":
            launch_studio(workspace, args.port, args.mineru_bin)
            return 0
        if args.command == "export":
            status = export_status(workspace, write_manifest=False)
            if not status["ready"]:
                blockers = "\n".join(f"- {blocker}" for blocker in status["blockers"])
                raise ContentToolError(f"Export blocked:\n{blockers}")
            path, digest = export_manifest(workspace, args.output)
            print(f"{path}\nsha256={digest}")
            return 0
        if args.command == "verify-lesson-contract":
            from .lesson_verify import verify

            report = verify(workspace.root, args.lesson, workspace.inside(*Path(args.out).parts), workspace.inside(*Path(args.dir).parts))
            print(json.dumps({"allChecksPassed": report["allChecksPassed"], "schemaValid": report["schemaValid"], "releaseReady": report["releaseReady"], "failed": [c["check"] for c in report["checks"] if not c["passed"]]}, ensure_ascii=False))
            return 0 if report["allChecksPassed"] else 2
        if args.command in {"resolve-lesson", "export-lesson-contract"}:
            from .lesson_commands import run_export_lesson_contract, run_resolve_lesson

            if args.command == "resolve-lesson":
                return run_resolve_lesson(workspace, args.lesson, args.dir, args.report, not args.no_apply)
            return run_export_lesson_contract(workspace, args.lesson, args.out)
        if args.command == "export-structured":
            if not args.chapter:
                result = export_book_candidates(workspace, args.book)
                print(result["candidatePath"])
                return 0
            result = export_chapter_candidates(workspace, args.book, args.chapter)
            print(result["candidatePath"])
            for lesson in result["lessons"]:
                print(f"{lesson['title']}: {lesson['structuredPath'] or 'missing OCR text'}")
            return 0
        if args.command == "structured-import":
            token = os.environ.get("NEXALAB_ADMIN_ACCESS_TOKEN", "")
            if not token:
                raise ContentToolError("Set NEXALAB_ADMIN_ACCESS_TOKEN for ADMIN API authentication")
            result = import_structured_lesson_drafts(workspace, args.api_base, token, args.expected_project_ref)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["rejected"] else 0
        if args.command == "curriculum-propose":
            proposal = json.loads(Path(args.input).read_text(encoding="utf-8"))
            taxonomy = json.loads(Path(args.taxonomy).read_text(encoding="utf-8")) if args.taxonomy else None
            if args.api_base:
                if taxonomy:
                    raise ContentToolError("Use either --taxonomy or --api-base, not both")
                from .authoring_contract import _get_json
                token = os.environ.get("NEXALAB_ADMIN_ACCESS_TOKEN", "")
                if not token:
                    raise ContentToolError("Set NEXALAB_ADMIN_ACCESS_TOKEN for the read-only BE taxonomy lookup")
                taxonomy = _get_json(args.api_base, token, "/admin/taxonomy")
            result = propose_registry(workspace, proposal, taxonomy)
            print(result["path"])
            print(f"outcomes={sum(len(topic['outcomes']) for subject in result['registry']['subjects'] for chapter in subject['chapters'] for topic in chapter['topics'])} mappings={len(result['registry']['mappings'])}")
            return 0
        if args.command == "curriculum-review":
            review = json.loads(Path(args.input).read_text(encoding="utf-8"))
            result = review_registry(workspace, args.framework, args.version, outcome_codes=review.get("outcomeCodes", {}), mapping_ids=review.get("mappingIds", []), reviewer_name=review.get("reviewerName", ""), reviewer_email=review.get("reviewerEmail", ""), reason=review.get("reason", ""), source_verified=review.get("sourceVerified", False))
            print(f"{result['path']}\nstatus={result['registry']['status']}")
            return 0
        if args.command == "curriculum-sync":
            token = os.environ.get("NEXALAB_ADMIN_ACCESS_TOKEN", "")
            if not token:
                raise ContentToolError("Set NEXALAB_ADMIN_ACCESS_TOKEN for admin API authentication")
            result = sync_approved_registry(workspace, args.framework, args.version, args.api_base, token, args.expected_project_ref)
            status = export_status(workspace, write_manifest=False)
            mapping_blockers = result.get("mappings", {}).get("blockers", [])
            ready = status["ready"] and not mapping_blockers
            result["contentRelease"] = {"ready": ready, "blockers": list(status["blockers"]) + mapping_blockers}
            if ready:
                path, digest = export_manifest(workspace)
                result["contentRelease"].update({"manifest": str(path), "sha256": digest})
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "outcomes-propose":
            taxonomy = json.loads(Path(args.taxonomy).read_text(encoding="utf-8")) if args.taxonomy else None
            llm_proposals = json.loads(Path(args.llm_proposals).read_text(encoding="utf-8")) if args.llm_proposals else None
            curriculum_source = None
            if args.curriculum_source_metadata:
                source_path = Path(args.curriculum_source_metadata)
                catalog = json.loads(source_path.read_text(encoding="utf-8"))
                curriculum_source = {
                    "status": catalog.get("status", "unverified"),
                    "sourceDocument": catalog.get("sourceDocument"),
                    "regulatoryBasis": catalog.get("regulatoryBasis", []),
                    "contractFinding": catalog.get("contractFinding"),
                    "catalogArtifactSha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                    "officialSha256": (catalog.get("sourceDocument") or {}).get("localArtifactSha256"),
                    "officialCodesPublished": bool((catalog.get("contractFinding") or {}).get("officialOutcomeCodesPublished")),
                }
            if llm_proposals is not None and not isinstance(llm_proposals, dict):
                raise ContentToolError("--llm-proposals must be an object keyed by candidate ID")
            normalizer = (lambda candidate: llm_proposals.get(candidate["id"])) if llm_proposals is not None else None
            result = propose_outcomes(workspace, taxonomy=taxonomy, llm_normalizer=normalizer, curriculum_source_metadata=curriculum_source)
            path = save_outcome_proposal(workspace, result, args.name)
            print(f"{path}\noutcomes={result['coverage']['measurableOutcomeCandidates']} concepts={result['coverage']['sourceConceptCandidates']} lessons={result['coverage']['sourceLessons']} KU-outcome-mappings={result['coverage']['knowledgeUnitOutcomeMappings']} ambiguous={result['coverage']['ambiguousSourceConcepts']} rejected={result['coverage']['rejected']}")
            return 0
        if args.command == "outcomes-review":
            review = json.loads(Path(args.input).read_text(encoding="utf-8"))
            result = review_outcome_proposal(
                workspace,
                args.name,
                outcome_decisions=review.get("outcomeDecisions", {}),
                mapping_decisions=review.get("mappingDecisions", {}),
                reviewer_name=review.get("reviewerName", ""),
                reviewer_email=review.get("reviewerEmail", ""),
                reason=review.get("reason", ""),
                source_text_verified=review.get("sourceTextVerified", False),
            )
            print(f"{result['path']}\nstatus={result['proposal']['status']} registrySync={result['proposal']['registrySync']['ready']}")
            return 0
        if args.command == "outcomes-export":
            result = export_outcome_sync_bundle(workspace, args.name)
            preflight = result["bundle"]["registrySyncPreflight"]
            print(f"{result['path']}\napproved={preflight['approvedOutcomeCount']} rejected={len(result['bundle']['rejectedOutcomes'])} merged={len(result['bundle']['mergedOutcomes'])} pending={preflight['unapprovedOutcomeCount']} preflight={preflight['status']}")
            return 0
        if args.command == "outcomes-sync":
            token = os.environ.get("NEXALAB_ADMIN_ACCESS_TOKEN", "")
            if not token:
                raise ContentToolError("Set NEXALAB_ADMIN_ACCESS_TOKEN for admin API authentication")
            result = sync_approved_outcomes(workspace, args.name, args.api_base, token, args.expected_project_ref)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate-structured":
            result = validate_book_outputs(workspace, args.book)
            print(json.dumps(result, ensure_ascii=True))
            return 0 if result["status"] == "valid" else 2
        if args.command == "plan":
            return run_plan(workspace, args.backend, args.target)
        if args.command == "apply":
            return run_apply(
                workspace,
                args.backend,
                args.target,
                args.initiated_by,
                args.approved_by,
                args.confirm_digest,
            )
        raise ContentToolError(f"Unsupported command: {args.command}")
    except ContentToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
