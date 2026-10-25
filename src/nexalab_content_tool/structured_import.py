from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .workspace import ContentToolError, Workspace, read_json

MAX_REQUEST_BYTES = 2_500_000
MAX_LESSON_BYTES = 2 * 1024 * 1024


def _request_json(
    api_base: str,
    access_token: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    expected_project_ref: str | None = None,
) -> Any:
    parts = urllib.parse.urlsplit(api_base)
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if parts.scheme not in {"http", "https"} or (not local and (parts.scheme != "https" or not expected_project_ref)):
        raise ContentToolError("Structured import is restricted to a local BE API or an explicitly identified HTTPS development project")
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        api_base.rstrip("/") + path,
        data=data,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ContentToolError(f"BE API {path} returned HTTP {error.code}: {detail[:500]}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ContentToolError(f"Could not reach the BE API: {error}") from error


def _compact_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _load_lessons(workspace: Workspace) -> list[tuple[Path, dict[str, Any], str]]:
    directory = workspace.inside("exports", "structured")
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not files:
        raise ContentToolError(f"No Structured Lesson JSON files found in {directory}")

    lessons: list[tuple[Path, dict[str, Any], str]] = []
    identities: set[str] = set()
    for file in files:
        safe_path = workspace.inside("exports", "structured", file.name)
        lesson = read_json(safe_path)
        if not isinstance(lesson, dict):
            raise ContentToolError(f"Structured Lesson must be a JSON object: {file.name}")
        try:
            identity = ":".join((lesson["book"]["key"], lesson["chapter"]["id"], lesson["sourceLesson"]["id"]))
            source_id = lesson["sourceLesson"]["id"]
        except (KeyError, TypeError) as error:
            raise ContentToolError(f"Missing stable source identity in {file.name}") from error
        if not all(isinstance(value, str) and value for value in (identity, source_id)):
            raise ContentToolError(f"Invalid stable source identity in {file.name}")
        if identity in identities:
            raise ContentToolError(f"Duplicate source identity in Structured Lesson files: {identity}")
        identities.add(identity)
        size = _compact_bytes(lesson)
        if size > MAX_LESSON_BYTES:
            raise ContentToolError(f"Structured Lesson exceeds BE's 2 MiB limit: {file.name}")
        lessons.append((file, lesson, identity))
    return lessons


def _batches(lessons: list[tuple[Path, dict[str, Any], str]]) -> list[list[tuple[Path, dict[str, Any], str]]]:
    batches: list[list[tuple[Path, dict[str, Any], str]]] = []
    current: list[tuple[Path, dict[str, Any], str]] = []
    for item in lessons:
        candidate = [*current, item]
        if current and _compact_bytes({"lessons": [entry[1] for entry in candidate]}) > MAX_REQUEST_BYTES:
            batches.append(current)
            current = [item]
        else:
            current = candidate
        if _compact_bytes({"lessons": [entry[1] for entry in current]}) > MAX_REQUEST_BYTES:
            raise ContentToolError(f"Structured Lesson exceeds safe API batch size: {item[0].name}")
    if current:
        batches.append(current)
    return batches


def import_structured_lessons(
    workspace: Workspace,
    api_base: str,
    access_token: str,
    expected_project_ref: str | None = None,
) -> dict[str, Any]:
    if not access_token.strip():
        raise ContentToolError("A current NexaLab ADMIN access token is required")
    lessons = _load_lessons(workspace)
    target = _request_json(api_base, access_token, "/admin/curriculum-target", expected_project_ref=expected_project_ref)
    local_target = isinstance(target, dict) and target.get("localDevelopmentTarget") is True
    remote_target = (
        isinstance(target, dict)
        and bool(expected_project_ref)
        and target.get("environment") == "development"
        and target.get("remoteDevelopmentTarget") is True
        and target.get("projectRef") == expected_project_ref
    )
    if not isinstance(target, dict) or target.get("environment") != "development" or target.get("configuredConnections") != 2 or not (local_target or remote_target):
        raise ContentToolError("BE did not confirm the requested local or allowlisted remote development database; no imports were started")

    imported: list[dict[str, Any]] = []
    for batch in _batches(lessons):
        response = _request_json(
            api_base,
            access_token,
            "/admin/structured-lessons/import",
            body={"lessons": [lesson for _, lesson, _ in batch]},
            expected_project_ref=expected_project_ref,
        )
        results = response.get("results") if isinstance(response, dict) else None
        if not isinstance(response, dict) or response.get("count") != len(batch) or not isinstance(results, list) or len(results) != len(batch):
            raise ContentToolError("BE import response count does not match the submitted batch")
        for (_, lesson, identity), result in zip(batch, results):
            source_id = lesson["sourceLesson"]["id"]
            if result.get("sourceLessonId") != source_id or result.get("identity") != identity:
                raise ContentToolError(f"BE import response identity mismatch for source Lesson {source_id}")
            if result.get("status") == "conflict":
                imported.append({"sourceLessonId": source_id, "identity": identity, "status": "rejected", "reason": result.get("reason", "BE reported a conflict")})
                continue
            if result.get("status") not in {"imported", "unchanged"} or not result.get("draftId") or not result.get("digest"):
                raise ContentToolError(f"BE import returned an invalid result for source Lesson {source_id}")
            draft = _request_json(
                api_base,
                access_token,
                "/admin/structured-lessons/drafts/" + urllib.parse.quote(result["draftId"], safe=""),
                expected_project_ref=expected_project_ref,
            )
            manifest = draft.get("manifest") if isinstance(draft, dict) else None
            if (
                not isinstance(draft, dict)
                or draft.get("id") != result["draftId"]
                or draft.get("digest") != result["digest"]
                or draft.get("status") != "draft"
                or manifest != lesson
                or not isinstance(manifest, dict)
                or manifest.get("sourceLesson", {}).get("id") != source_id
            ):
                raise ContentToolError(f"Persisted draft readback did not match source JSON for Lesson {source_id}")
            imported.append({
                "sourceLessonId": source_id,
                "identity": identity,
                "digest": draft["digest"],
                "draftId": draft["id"],
                "status": "imported" if result["status"] == "imported" else "reused",
            })

    counts = {status: sum(item["status"] == status for item in imported) for status in ("imported", "reused", "rejected")}
    return {"count": len(imported), **counts, "batches": len(_batches(lessons)), "results": imported}
