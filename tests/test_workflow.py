from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from nexalab_content_tool.backend import run_plan
from nexalab_content_tool.extract import extract_native_pdf
from nexalab_content_tool.identity import reserve_id
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
        config["reviewPolicy"]["hReviewMaxHours"] = 1
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


if __name__ == "__main__":
    unittest.main()
