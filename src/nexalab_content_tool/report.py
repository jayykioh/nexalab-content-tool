from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from .manifest import REVIEW_KINDS, build_manifest, load_authoring
from .workspace import ContentToolError, Workspace, read_json


def _text(value: Any) -> str:
    return escape("" if value is None else str(value))


def _evidence_excerpt(workspace: Workspace, item: dict[str, Any]) -> str:
    if item.get("extractionMethod") == "synthetic-fixture":
        return "Synthetic fixture; no source artifact"
    artifact = read_json(
        workspace.inside(
            "extracts", item["sourceId"], f"{item['sourceVersion']}.native.json"
        )
    )
    return "\n".join(
        block.get("text", "")
        for block in artifact.get("blocks", [])
        if isinstance(block, dict) and block.get("physicalPageIndex") == item.get("physicalPageIndex")
    )


def render_report(workspace: Workspace, output: str | Path | None = None) -> Path:
    build_manifest(workspace)
    release, wrappers = load_authoring(workspace)
    sections = []
    for path, wrapper in wrappers:
        pack_value = wrapper.get("pack")
        pack = pack_value if isinstance(pack_value, dict) else {}
        claim_text = {
            claim.get("id"): claim.get("text")
            for unit in pack.get("knowledgeUnits", [])
            if isinstance(unit, dict)
            for claim in unit.get("claims", [])
            if isinstance(claim, dict)
        }
        lesson_content = pack.get("lesson", {}).get("content", "")
        source_rows = "".join(
            "<tr>"
            f"<td><code>{_text(item.get('id'))}</code></td>"
            f"<td>{_text(item.get('title'))}</td>"
            f"<td>{_text(item.get('author'))}</td>"
            f"<td>{_text(item.get('license'))}</td>"
            f"<td>{_text(item.get('attribution'))}</td>"
            "</tr>"
            for item in pack.get("sources", [])
            if isinstance(item, dict)
        )
        unit_rows = "".join(
            "<tr>"
            f"<td><code>{_text(unit.get('id'))}</code></td>"
            f"<td>{_text(', '.join(unit.get('outcomeCodes', [])))}</td>"
            f"<td>{_text(', '.join(unit.get('terms', [])))}</td>"
            f"<td>{_text('; '.join(unit.get('misconceptions', [])))}</td>"
            "</tr>"
            for unit in pack.get("knowledgeUnits", [])
            if isinstance(unit, dict)
        )
        material_rows = "".join(
            "<tr>"
            f"<td>{_text(item.get('type'))}</td><td>{_text(item.get('title'))}</td>"
            f"<td><code>{_text(item.get('url'))}</code></td>"
            "</tr>"
            for item in pack.get("lesson", {}).get("materials", [])
            if isinstance(item, dict)
        )
        exercise = pack.get("lesson", {}).get("basicExercises")
        exercise_rows = "" if not isinstance(exercise, dict) else "".join(
            "<tr>"
            f"<td><code>{_text(question.get('id'))}</code></td>"
            f"<td>{_text(question.get('prompt'))}</td>"
            f"<td>{_text('; '.join('{}: {}'.format(option.get('id'), option.get('text')) for option in question.get('options', []) if isinstance(option, dict)))}</td>"
            f"<td><code>{_text(question.get('correctOptionId'))}</code></td>"
            "</tr>"
            for question in exercise.get("questions", [])
            if isinstance(question, dict)
        )
        review_by_kind = {
            item.get("kind"): item for item in wrapper.get("reviewLog", []) if isinstance(item, dict)
        }
        review_rows = "".join(
            "<tr>"
            f"<td>{_text(kind)}</td>"
            f"<td>{_text(pack.get('reviews', {}).get(kind, {}).get('name'))}</td>"
            f"<td>{_text(pack.get('reviews', {}).get(kind, {}).get('email'))}</td>"
            f"<td>{_text(review_by_kind.get(kind, {}).get('status', 'missing'))}</td>"
            "</tr>"
            for kind in REVIEW_KINDS
        )
        evidence_rows = "".join(
            "<tr>"
            f"<td>{_text(item.get('contentRef') or item.get('claimId'))}</td>"
            f"<td>{_text(lesson_content if item.get('contentRef') == 'lesson.content' else claim_text.get(item.get('claimId')))}</td>"
            f"<td>{_text(item.get('sourceId'))}</td>"
            f"<td>{_text(item.get('sourceVersion'))}</td>"
            f"<td>{_text(item.get('physicalPageIndex'))}</td>"
            f"<td>{_text(item.get('printedPageLabel'))}</td>"
            f"<td><code>{_text(item.get('sourceSha256'))}</code></td>"
            f"<td>{_text(item.get('extractionMethod'))}</td>"
            f"<td>{_text(item.get('locator'))}</td>"
            f"<td><pre>{_text(_evidence_excerpt(workspace, item))}</pre></td>"
            "</tr>"
            for item in wrapper.get("evidence", [])
            if isinstance(item, dict)
        )
        sections.append(
            "<section>"
            f"<h2>{_text(pack.get('title', path.name))}</h2>"
            f"<p><strong>Pack:</strong> <code>{_text(pack.get('key'))}</code> &middot; "
            f"<strong>File:</strong> <code>{_text(path.relative_to(workspace.root).as_posix())}</code></p>"
            f"<p><strong>Objective:</strong> {_text(pack.get('lesson', {}).get('learningObjective'))}</p>"
            f"<p><strong>Outcomes:</strong> {_text(', '.join(pack.get('outcomeCodes', [])))}</p>"
            f"<h3>Final lesson content</h3><div>{_text(lesson_content)}</div>"
            "<h3>Knowledge units</h3>"
            "<table><thead><tr><th>ID</th><th>Outcomes</th><th>Terms</th><th>Misconceptions</th></tr></thead>"
            f"<tbody>{unit_rows}</tbody></table>"
            "<h3>Materials</h3>"
            "<table><thead><tr><th>Type</th><th>Title</th><th>Pinned URL</th></tr></thead>"
            f"<tbody>{material_rows}</tbody></table>"
            + (
                "<h3>Basic exercise</h3>"
                f"<p><strong>Step ID:</strong> <code>{_text(exercise.get('id'))}</code> &middot; "
                f"<strong>Pass threshold:</strong> {_text(exercise.get('passThreshold'))}%</p>"
                "<table><thead><tr><th>Question ID</th><th>Prompt</th><th>Options</th><th>Correct option</th></tr></thead>"
                f"<tbody>{exercise_rows}</tbody></table>"
                if isinstance(exercise, dict)
                else ""
            )
            +
            "<h3>Sources and rights</h3>"
            "<table><thead><tr><th>ID</th><th>Title</th><th>Author</th><th>License</th><th>Attribution</th></tr></thead>"
            f"<tbody>{source_rows}</tbody></table>"
            "<h3>Review log</h3>"
            "<table><thead><tr><th>Role</th><th>Name</th><th>Email</th><th>Local status</th></tr></thead>"
            f"<tbody>{review_rows}</tbody></table>"
            "<h3>Claim evidence</h3>"
            "<table><thead><tr><th>Content reference</th><th>Final text</th><th>Source</th><th>Version</th><th>PDF page</th>"
            "<th>Printed label</th><th>Source SHA-256</th><th>Method</th><th>Locator</th><th>Extracted page text</th></tr></thead>"
            f"<tbody>{evidence_rows}</tbody></table>"
            "</section>"
        )
    html = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{_text(release.get('name'))} review report</title>"
        "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:1200px;margin:32px auto;padding:0 20px;color:#172033}"
        "h1,h2,h3{line-height:1.2}section{border-top:2px solid #d8deea;margin-top:28px;padding-top:20px}"
        "table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #ccd4e0;padding:7px;text-align:left;vertical-align:top}"
        "th{background:#eef2f7}code{word-break:break-all}pre{white-space:pre-wrap;max-width:36rem}.notice{background:#fff5d6;border:1px solid #d8a900;padding:12px}</style>"
        "</head><body>"
        f"<h1>{_text(release.get('name'))}</h1>"
        f"<p><strong>Namespace:</strong> {_text(release.get('namespace'))}</p>"
        "<p class=\"notice\">This local report records evidence and declared review state. It is not proof that "
        "a reviewer authenticated or approved the backend payload. Fixture-only reviews must never be presented as baseline approval.</p>"
        + "".join(sections)
        + "</body></html>\n"
    )
    target = Path(output).resolve() if output else workspace.inside("reports", "review-report.html")
    if output and not target.is_relative_to(workspace.root):
        raise ContentToolError("Report output must stay inside the workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8", newline="\n")
    return target
