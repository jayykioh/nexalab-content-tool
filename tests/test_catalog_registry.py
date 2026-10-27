import json
from pathlib import Path

import pytest

from nexalab_content_tool.canonical_html import normalize_lesson_html
from nexalab_content_tool.catalog_registry import validate_confirmed_curriculum
from nexalab_content_tool.workspace import ContentToolError, Workspace, init_workspace


def test_html_normalizer_has_no_curriculum_behavior():
    assert "KHTN9" not in Path(__file__).parents[1].joinpath("src/nexalab_content_tool/canonical_html.py").read_text(encoding="utf-8")
    out = normalize_lesson_html("<p>| A | B |</p><p>| --- | --- |</p><p>| $x$ | y |</p><h2>?</h2><p>\\- item</p><p>Mô tả hình: sơ đồ</p>")
    assert "<table>" in out and "<thead>" in out and "\\-" not in out
    assert "Câu hỏi thảo luận" in out and '<figure class="figure-note">' in out and "$x$" in out


def test_confirmed_curriculum_must_exist_in_registry(tmp_path):
    root = Path(tmp_path) / "workspace"
    init_workspace(root, "registry-test")
    workspace = Workspace.open(root)
    (root / "catalog-registry.json").write_text(json.dumps({"schemaVersion": 1, "chapters": [{"code": "CH-1"}], "topics": [{"code": "TOP-1"}], "outcomes": [{"code": "OUT-1"}]}), encoding="utf-8")
    pack = {"curriculum": {"chapterCode": "CH-1", "topicCode": "TOP-1", "order": 1, "outcomeCodes": ["OUT-1"], "confirmed": True}, "outcomeCodes": ["OUT-1"]}
    validate_confirmed_curriculum(workspace, pack)
    pack["curriculum"]["confirmed"] = False
    with pytest.raises(ContentToolError, match="CURRICULUM_CONFIRMATION_REQUIRED"):
        validate_confirmed_curriculum(workspace, pack)
