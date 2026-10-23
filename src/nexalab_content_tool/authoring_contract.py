from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .identity import ID_PATTERN
from .workspace import ContentToolError, Workspace, read_json, write_json


ASSET_REF = re.compile(r"^assetv:([a-z0-9]{20,40})$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_materials(materials: Any) -> list[dict[str, Any]]:
    if not isinstance(materials, list) or len(materials) > 20:
        raise ContentToolError("Lesson materials must be an array with at most 20 items")
    clean: list[dict[str, Any]] = []
    for item in materials:
        if not isinstance(item, dict) or set(item) - {"type", "url", "title", "transcript", "captionUrl"}:
            raise ContentToolError("Each material must use the existing BE material fields")
        kind, url, title = item.get("type"), str(item.get("url", "")).strip(), str(item.get("title", "")).strip()
        if kind not in {"video", "pdf", "image"} or not ASSET_REF.fullmatch(url) or not title or len(title) > 200:
            raise ContentToolError("Materials need type video/pdf/image, title and a pinned assetv: version")
        value = {"type": kind, "url": url, "title": title}
        if item.get("transcript") is not None:
            transcript = str(item["transcript"]).strip()
            if len(transcript) > 50_000:
                raise ContentToolError("Video transcript is too long")
            value["transcript"] = transcript
        if item.get("captionUrl") is not None:
            caption = str(item["captionUrl"]).strip()
            if not ASSET_REF.fullmatch(caption):
                raise ContentToolError("Video caption must be a pinned assetv: version")
            value["captionUrl"] = caption
        if kind == "video" and (not value.get("transcript") or not value.get("captionUrl")):
            raise ContentToolError("Video materials require a transcript and pinned caption asset")
        clean.append(value)
    return clean


def verify_authoring_context(draft: dict[str, Any], context: dict[str, Any], api_base: str) -> dict[str, Any]:
    outcome_code = str(draft.get("outcomeCode", "")).strip()
    outcome = next((item for item in context.get("outcomes", []) if item.get("code") == outcome_code), None)
    if not outcome:
        raise ContentToolError(f"Outcome {outcome_code or '(blank)'} is absent from the BE curriculum taxonomy")
    if outcome.get("status") != "active" or outcome.get("grade") != draft.get("grade") or outcome.get("domain") != draft.get("domain"):
        raise ContentToolError("Outcome is archived or does not match the Lesson grade/domain")

    materials = validate_materials(draft.get("materials", []))
    versions: dict[str, dict[str, Any]] = {}
    for asset in context.get("assets", []):
        for version in asset.get("versions", []):
            versions[str(version.get("id", ""))] = {**version, "assetStatus": asset.get("status"), "scope": asset.get("scope"), "kind": asset.get("kind")}
    checked_assets = []
    refs = [(item["url"], item["title"], item["type"]) for item in materials]
    refs.extend((item["captionUrl"], f"caption for {item['title']}", "caption") for item in materials if item.get("captionUrl"))
    source_version = str(draft.get("sourceArtifactVersionId", "")).strip()
    if source_version:
        refs.append((f"assetv:{source_version}", "source artifact", "source"))
    for reference, title, expected_kind in refs:
        match = ASSET_REF.fullmatch(reference)
        version = versions.get(match.group(1) if match else "")
        if not version or version.get("status") != "READY" or version.get("assetStatus") != "ACTIVE" or version.get("scope") != "SHARED_LIBRARY":
            raise ContentToolError(f'{title} is not a READY version of an ACTIVE shared-library asset')
        if expected_kind == "caption" and version.get("kind") != "caption":
            raise ContentToolError(f"{title} must reference a caption asset")
        checked_assets.append({"reference": reference, "kind": version.get("kind"), "status": "READY", "scope": "SHARED_LIBRARY"})

    labs = []
    for lab in context.get("labs", []):
        model_ref = str(lab.get("simulationModelRef") or "")
        if model_ref:
            labs.append({"id": lab.get("id"), "modelRef": model_ref, "challengeIds": [item.get("id") for item in lab.get("challenges", []) if item.get("id")], "status": lab.get("status")})
    verification = {
        "schemaVersion": 1,
        "packKey": draft.get("packKey"),
        "apiBase": api_base.rstrip("/"),
        "verifiedAt": _now(),
        "outcome": {key: outcome.get(key) for key in ("code", "grade", "domain", "status", "synthetic")},
        "verifiedDraft": {"outcomeCode": outcome_code, "grade": draft.get("grade"), "domain": draft.get("domain"), "materials": materials, "sourceArtifactVersionId": source_version},
        "assets": checked_assets,
        "labs": labs,
    }
    return verification


def _get_json(api_base: str, token: str, path: str, query: dict[str, str] | None = None) -> Any:
    base = api_base.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    if query:
        url += "?" + urlencode(query)
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ContentToolError(f"BE authoring lookup returned HTTP {error.code}") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ContentToolError(f"Cannot read BE authoring data: {error}") from error


def fetch_authoring_context(api_base: str, token: str) -> dict[str, Any]:
    if not re.fullmatch(r"https?://[^\s]+", api_base.strip()) or len(token.strip()) < 10:
        raise ContentToolError("A BE API URL and current admin access token are required")
    taxonomy = _get_json(api_base, token, "/admin/taxonomy")
    asset_items: list[dict[str, Any]] = []
    cursor = None
    for _ in range(20):
        query = {"status": "ACTIVE", "scope": "SHARED_LIBRARY", "limit": "100"}
        if cursor:
            query["cursor"] = cursor
        page = _get_json(api_base, token, "/admin/assets", query)
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise ContentToolError("BE asset endpoint returned an unexpected contract")
        asset_items.extend(page["items"])
        cursor = page.get("nextCursor")
        if not cursor:
            break
    labs = _get_json(api_base, token, "/admin/labs")
    if not isinstance(taxonomy, dict) or not isinstance(taxonomy.get("outcomes"), list) or not isinstance(labs, list):
        raise ContentToolError("BE authoring endpoints returned an unexpected contract")
    return {"outcomes": taxonomy["outcomes"], "assets": asset_items, "labs": labs}


def verification_path(workspace: Workspace, pack_key: str) -> Path:
    if not ID_PATTERN.fullmatch(pack_key):
        raise ContentToolError("Lesson pack key is invalid")
    return workspace.inside(".local", "authoring-verification", f"{pack_key}.json")


def save_verification(workspace: Workspace, verification: dict[str, Any]) -> dict[str, Any]:
    write_json(verification_path(workspace, str(verification.get("packKey", ""))), verification)
    return verification


def load_verification(workspace: Workspace, pack_key: str) -> dict[str, Any]:
    path = verification_path(workspace, pack_key)
    if not path.exists():
        raise ContentToolError("Verify the draft against the current BE curriculum before creating a Lab candidate")
    return read_json(path)


def validate_lab_blueprint(backend_path: str | Path, blueprint: dict[str, Any]) -> dict[str, Any]:
    backend = Path(backend_path).resolve()
    if not (backend / "scripts" / "content-studio-validate.ts").is_file():
        raise ContentToolError("Choose a BE checkout with the Content Studio validator")
    executable = "npm.cmd" if os.name == "nt" else "npm"
    try:
        run = subprocess.run(
            [executable, "run", "content:studio:validate", "--silent"],
            cwd=backend,
            input=json.dumps(blueprint, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise ContentToolError(f"Cannot run BE Lab validator: {error}") from error
    try:
        result = json.loads(run.stdout)
    except json.JSONDecodeError as error:
        raise ContentToolError((run.stderr or run.stdout or "BE Lab validator returned no JSON")[-1000:]) from error
    if not isinstance(result, dict):
        raise ContentToolError("BE Lab validator returned an invalid result")
    return result
