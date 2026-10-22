from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import urllib.request
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from nexalab_content_tool.backend import run_apply, run_plan
from nexalab_content_tool.extract import extract_native_pdf
from nexalab_content_tool.identity import reserve_id
from nexalab_content_tool.m0a_review import _ReviewServer
from nexalab_content_tool.manifest import build_manifest, export_manifest
from nexalab_content_tool.report import render_report
from nexalab_content_tool.workspace import ContentToolError, Workspace, init_workspace, read_json, write_json


REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLE = REPOSITORY / "examples" / "synthetic-pilot"


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def copy_example(self) -> Workspace:
        target = self.root / "example"
        shutil.copytree(EXAMPLE, target)
        return Workspace.open(target)

    def extraction_workspace(self) -> Workspace:
        target = init_workspace(self.root / "extract", "extract-test")
        config = read_json(target / "workspace.json")
        config["reviewPolicy"]["localSourceRightsConfirmed"] = True
        write_json(target / "workspace.json", config)
        write_json(
            target / "source-inventory.json",
            {
                "schemaVersion": 1,
                "sources": [
                    {
                        "key": "source-one",
                        "version": "v1",
                        "sha256": None,
                        "rights": {"localProcessingConfirmed": True},
                        "printedPageLabels": {"1": "fixture-1"},
                    }
                ],
            },
        )
        return Workspace.open(target)

    def test_init_refuses_nonempty_directory(self) -> None:
        target = self.root / "occupied"
        target.mkdir()
        existing = target / "release.json"
        existing.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ContentToolError, "empty directory"):
            init_workspace(target, "demo")
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_conflicting_id_does_not_rewrite_registry(self) -> None:
        workspace = Workspace.open(init_workspace(self.root / "ids", "ids"))
        reserve_id(workspace, "claim", "claim-one", "first-owner")
        before = workspace.registry_path.read_bytes()
        with self.assertRaisesRegex(ContentToolError, "already owned"):
            reserve_id(workspace, "claim", "claim-one", "second-owner")
        self.assertEqual(workspace.registry_path.read_bytes(), before)

    def test_empty_native_pdf_fails_without_binding_hash(self) -> None:
        workspace = self.extraction_workspace()
        pdf = self.root / "empty.pdf"
        document = pymupdf.open()
        document.new_page()
        document.save(pdf)
        document.close()
        with self.assertRaisesRegex(ContentToolError, "no native text blocks"):
            extract_native_pdf(workspace, "source-one", "v1", pdf)
        self.assertIsNone(read_json(workspace.inventory_path)["sources"][0]["sha256"])

    def test_corrupt_pdf_is_an_operator_error(self) -> None:
        workspace = self.extraction_workspace()
        pdf = self.root / "corrupt.pdf"
        pdf.write_bytes(b"not a pdf")
        with self.assertRaisesRegex(ContentToolError, "Cannot extract PDF"):
            extract_native_pdf(workspace, "source-one", "v1", pdf)

    def test_export_is_deterministic(self) -> None:
        workspace = self.copy_example()
        first_path, first_digest = export_manifest(workspace)
        first_bytes = first_path.read_bytes()
        second_path, second_digest = export_manifest(workspace)
        self.assertEqual(first_digest, second_digest)
        self.assertEqual(first_bytes, second_path.read_bytes())
        manifest = json.loads(first_bytes)
        exercise = manifest["packs"][0]["lesson"]["basicExercises"]
        self.assertEqual(exercise["id"], "practice-series-current")
        self.assertEqual(exercise["questions"][0]["id"], "practice-current-question")
        self.assertEqual(exercise["questions"][0]["options"][0]["id"], "same-current")
        self.assertEqual(manifest["packs"][0]["lesson"]["questions"], [])

    def test_fabricated_or_ambiguous_evidence_is_rejected(self) -> None:
        workspace = self.copy_example()
        pack_path = workspace.inside("packs", "fixture-khtn8-local-reading.json")
        wrapper = read_json(pack_path)
        wrapper["evidence"][0]["claimId"] = "claim-current-same"
        write_json(pack_path, wrapper)
        with self.assertRaisesRegex(ContentToolError, "exactly one"):
            build_manifest(workspace)

    def test_report_uses_export_completeness_gate(self) -> None:
        workspace = self.copy_example()
        pack_path = workspace.inside("packs", "fixture-khtn8-local-reading.json")
        wrapper = read_json(pack_path)
        wrapper["evidence"][0]["locator"] = ""
        write_json(pack_path, wrapper)
        with self.assertRaisesRegex(ContentToolError, "non-empty locator"):
            render_report(workspace)

    def test_m0a_review_saves_local_decision_history(self) -> None:
        workspace = Workspace.open(init_workspace(self.root / "review", "review-test"))
        pdf = self.root / "one-page.pdf"
        document = pymupdf.open()
        document.new_page()
        document.save(pdf)
        document.close()
        server = _ReviewServer(
            workspace,
            pdf,
            {1: {"page_idx": 0, "blocks": [{"type": "text", "text": "sample"}]}},
            1,
            "a" * 64,
            "b" * 64,
            0,
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            state = json.loads(urllib.request.urlopen(f"{base}/api/state", timeout=2).read())
            self.assertEqual(state["pages"][0]["pageIndex"], 1)
            request = urllib.request.Request(
                f"{base}/api/review",
                data=json.dumps({
                    "pageIndex": 1,
                    "action": "needs-correction",
                    "edits": {"0": "corrected"},
                    "durationSeconds": 42,
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            self.assertTrue(json.loads(urllib.request.urlopen(request, timeout=2).read())["saved"])
            saved = read_json(server.review_path)
            self.assertEqual(saved["pages"]["1"]["edits"]["0"], "corrected")
            self.assertNotIn("reviewer", saved["pages"]["1"])
            self.assertEqual(saved["history"][0]["durationSeconds"], 42)
            self.assertEqual(saved["resultSha256"], "b" * 64)
        finally:
            server.shutdown()
            worker.join(timeout=2)
            server.server_close()

    def test_backend_command_is_dry_run_and_bounded(self) -> None:
        workspace = self.copy_example()
        backend = self.root / "backend"
        (backend / "scripts").mkdir(parents=True)
        (backend / "package.json").write_text("{}", encoding="utf-8")
        (backend / "scripts" / "content-release.ts").write_text("", encoding="utf-8")
        completed = subprocess.CompletedProcess([], 7)
        with patch("nexalab_content_tool.backend.subprocess.run", return_value=completed) as called:
            self.assertEqual(run_plan(workspace, backend, "development"), 7)
        command = called.call_args.args[0]
        self.assertNotIn("--apply", command)
        self.assertEqual(called.call_args.kwargs["timeout"], 300)

    def test_apply_requires_matching_unblocked_backend_plan(self) -> None:
        workspace = self.copy_example()
        backend = self.root / "backend"
        (backend / "scripts").mkdir(parents=True)
        (backend / "package.json").write_text("{}", encoding="utf-8")
        (backend / "scripts" / "content-release.ts").write_text("", encoding="utf-8")
        digest = "a" * 64
        plan = json.dumps({"blocked": False, "digest": digest, "target": "development", "environment": "development"})
        with patch("nexalab_content_tool.backend.subprocess.run", return_value=subprocess.CompletedProcess([], 0, plan, "")) as called:
            with self.assertRaisesRegex(ContentToolError, "Digest confirmation mismatch"):
                run_apply(workspace, backend, "development", "operator@example.test", "admin@example.test", "wrong")
        self.assertEqual(called.call_count, 1)
        self.assertNotIn("--apply", called.call_args.args[0])

    def test_apply_runs_backend_only_after_matching_plan_confirmation(self) -> None:
        workspace = self.copy_example()
        backend = self.root / "backend"
        (backend / "scripts").mkdir(parents=True)
        (backend / "package.json").write_text("{}", encoding="utf-8")
        (backend / "scripts" / "content-release.ts").write_text("", encoding="utf-8")
        digest = "b" * 64
        plan = json.dumps({"blocked": False, "digest": digest, "target": "development", "environment": "development"})
        with patch(
            "nexalab_content_tool.backend.subprocess.run",
            side_effect=[subprocess.CompletedProcess([], 0, plan, ""), subprocess.CompletedProcess([], 0)],
        ) as called:
            self.assertEqual(
                run_apply(workspace, backend, "development", "operator@example.test", "admin@example.test", digest),
                0,
            )
        self.assertEqual(called.call_count, 2)
        self.assertNotIn("--apply", called.call_args_list[0].args[0])
        self.assertIn("--apply", called.call_args_list[1].args[0])
        self.assertEqual(called.call_args_list[1].args[0][-4:], ["--initiated-by", "operator@example.test", "--approved-by", "admin@example.test"])


if __name__ == "__main__":
    unittest.main()
