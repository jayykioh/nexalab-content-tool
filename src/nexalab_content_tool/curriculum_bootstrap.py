from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from .workspace import ContentToolError, Workspace, read_json, write_json


BE_SYNC_DOMAINS = {"ENERGY", "MATTER", "LIVING", "EARTH_SKY"}
_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,39}$")
_SUBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,39}$")


def _safe_code(value: str, label: str) -> str:
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise ContentToolError(f"{label} must be a stable uppercase code (2-40 characters)")
    return value


def _registry_path(workspace: Workspace, framework_key: str, version: str):
    return workspace.inside(".local", "curriculum", f"{framework_key}@{version}.json")


def _internal_code(framework_key: str, grade: int, domain: str, key: str) -> str:
    framework_slug = re.sub(r"[^A-Z0-9]+", "-", framework_key.upper()).strip("-")[:5] or "CURR"
    slug = re.sub(r"[^A-Z0-9]+", "-", key.upper()).strip("-")[:10] or "OUTCOME"
    digest = hashlib.sha256(f"{framework_key}|{grade}|{domain}|{key}".encode()).hexdigest()[:8].upper()
    return f"NX-{framework_slug}-{grade}-{domain[:2]}-{slug}-{digest}"


def _framework_id(framework_key: str, version: str) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "-", f"{framework_key}-{version}".upper()).strip("-")[:10]
    digest = hashlib.sha256(f"{framework_key}|{version}".encode()).hexdigest()[:8].upper()
    return f"NX-FW-{slug}-{digest}"


def propose_registry(workspace: Workspace, proposal: dict[str, Any], taxonomy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist a versioned proposal; never writes to BE or changes Lesson JSON."""
    framework = proposal.get("framework")
    if not isinstance(framework, dict):
        raise ContentToolError("framework metadata is required")
    framework_key = _safe_code(framework.get("key"), "framework.key")
    version = str(framework.get("version", "")).strip()
    title = str(framework.get("title", "")).strip()
    source = framework.get("source")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", version) or not title or len(title) > 200 or not isinstance(source, dict):
        raise ContentToolError("Framework version, title and verified source metadata are required")
    for key in ("authority", "url", "publishedAt", "accessedAt", "sha256"):
        if not str(source.get(key, "")).strip():
            raise ContentToolError(f"framework.source.{key} is required; source provenance must not be inferred")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", str(source["sha256"])):
        raise ContentToolError("framework.source.sha256 must be a 64-character source file digest")
    source_url = urllib.parse.urlsplit(str(source["url"]))
    if source_url.scheme != "https" or not source_url.hostname or len(str(source["url"])) > 500:
        raise ContentToolError("Curriculum source URL must use HTTPS")
    if len(str(source["authority"])) > 200 or any(len(str(source[key])) > 40 for key in ("publishedAt", "accessedAt")):
        raise ContentToolError("Curriculum source metadata exceeds the BE admin API field limits")
    subjects = proposal.get("subjects")
    if not isinstance(subjects, list) or not subjects or len(subjects) > 50:
        raise ContentToolError("Provide 1-50 curriculum subjects")

    existing = (taxonomy or {}).get("outcomes", [])
    registry_subjects: list[dict[str, Any]] = []
    subject_ids: set[str] = set()
    chapter_codes: set[str] = set()
    topic_codes: set[str] = set()
    outcome_statements: dict[str, str] = {}
    for subject in subjects:
        subject_id = subject.get("id")
        if not isinstance(subject_id, str) or not _SUBJECT_ID.fullmatch(subject_id):
            raise ContentToolError("subject.id must be a stable BE Subject ID (2-40 characters)")
        if subject_id in subject_ids:
            raise ContentToolError(f"Duplicate curriculum Subject identity: {subject_id}")
        subject_ids.add(subject_id)
        subject_name = str(subject.get("name", "")).strip()
        if not subject_name or len(subject_name) > 200:
            raise ContentToolError(f"Subject {subject_id} requires a name")
        chapters_out = []
        for chapter in subject.get("chapters", []):
            chapter_code = _safe_code(chapter.get("code"), "chapter.code")
            if chapter_code in chapter_codes:
                raise ContentToolError(f"Duplicate curriculum Chapter identity: {chapter_code}")
            chapter_codes.add(chapter_code)
            grade, domain = chapter.get("grade"), chapter.get("domain")
            if isinstance(grade, bool) or not isinstance(grade, int) or not 1 <= grade <= 12:
                raise ContentToolError(f"Chapter {chapter_code} requires a curriculum grade from 1 to 12")
            _safe_code(domain, f"chapter {chapter_code}.domain")
            if not str(chapter.get("title", "")).strip() or len(str(chapter.get("title", "")).strip()) > 200:
                raise ContentToolError(f"Chapter {chapter_code} requires a title")
            topics_out = []
            for topic in chapter.get("topics", []):
                topic_code = _safe_code(topic.get("code"), "topic.code")
                if topic_code in topic_codes:
                    raise ContentToolError(f"Duplicate curriculum Topic identity: {topic_code}")
                topic_codes.add(topic_code)
                if not str(topic.get("title", "")).strip() or len(str(topic.get("title", "")).strip()) > 200:
                    raise ContentToolError(f"Topic {topic_code} requires a title")
                outcomes_out = []
                for outcome in topic.get("outcomes", []):
                    key = str(outcome.get("key", "")).strip()
                    statement = str(outcome.get("statement", "")).strip()
                    locator = str(outcome.get("sourceLocator", "")).strip()
                    if len(key) < 2 or len(statement) < 5 or len(statement) > 1000 or not locator or len(locator) > 200:
                        raise ContentToolError(f"Outcome in {topic_code} needs a stable semantic key, source statement and locator (1-200 characters)")
                    code = _internal_code(framework_key, grade, domain, key)
                    prior_statement = outcome_statements.setdefault(key, statement)
                    if prior_statement != statement:
                        raise ContentToolError(f"Semantic outcome key {key} has conflicting statements")
                    normalized = " ".join(statement.casefold().split())
                    exact = [item for item in existing if item.get("grade") == grade and item.get("domain") == domain and " ".join(str(item.get("statement", "")).casefold().split()) == normalized and item.get("status") == "active" and item.get("synthetic") is False]
                    candidates = [item for item in existing if item.get("grade") == grade and item.get("domain") == domain and item.get("status") == "active" and item.get("synthetic") is False]
                    outcomes_out.append({
                        "key": key,
                        "internalCode": code,
                        "officialCode": None,
                        "officialStatement": statement,
                        "sourceLocator": locator,
                        "reuseCandidates": [item.get("code") for item in exact],
                        "reviewCandidates": [item.get("code") for item in candidates],
                        "approvedCode": exact[0]["code"] if len(exact) == 1 else None,
                        "status": "proposed",
                        "review": None,
                    })
                if not outcomes_out:
                    raise ContentToolError(f"Topic {topic_code} must have proposed outcomes")
                if len({item["internalCode"] for item in outcomes_out}) > 30:
                    raise ContentToolError(f"Topic {topic_code} exceeds the BE limit of 30 mapped outcomes")
                topics_out.append({"code": topic_code, "title": str(topic.get("title", "")).strip(), "outcomes": outcomes_out})
            if not topics_out:
                raise ContentToolError(f"Chapter {chapter_code} must have topics")
            chapters_out.append({"code": chapter_code, "title": str(chapter.get("title", "")).strip(), "grade": grade, "domain": domain, "topics": topics_out})
        if not chapters_out:
            raise ContentToolError(f"Subject {subject_id} must have chapters")
        registry_subjects.append({"id": subject_id, "name": subject_name, "chapters": chapters_out})

    mappings = []
    known_outcome_keys = {outcome["key"] for subject in registry_subjects for chapter in subject["chapters"] for topic in chapter["topics"] for outcome in topic["outcomes"]}
    for mapping in proposal.get("mappings", []):
        lesson_id = str(mapping.get("lessonId", "")).strip()
        unit_id = str(mapping.get("knowledgeUnitId", "")).strip()
        outcome_keys = mapping.get("outcomeKeys")
        if not lesson_id or not isinstance(outcome_keys, list) or not outcome_keys or len(outcome_keys) > 30:
            raise ContentToolError("Each Lesson/Knowledge Unit mapping needs lessonId and outcomeKeys")
        if any(not isinstance(key, str) or key not in known_outcome_keys for key in mapping["outcomeKeys"]):
            raise ContentToolError(f"Mapping for {lesson_id} references an unknown proposed outcome key")
        source_pages = mapping.get("sourcePages", [])
        if not isinstance(source_pages, list) or any(isinstance(page, bool) or not isinstance(page, int) or page < 1 for page in source_pages):
            raise ContentToolError(f"Mapping for {lesson_id} sourcePages must be positive PDF page numbers")
        if len(str(mapping.get("rationale", "")).strip()) < 5:
            raise ContentToolError(f"Mapping for {lesson_id} needs a reviewable rationale")
        mappings.append({"id": hashlib.sha256(f"{lesson_id}|{unit_id}|{'|'.join(outcome_keys)}".encode()).hexdigest()[:20], "lessonId": lesson_id, "knowledgeUnitId": unit_id or None, "outcomeKeys": outcome_keys, "sourcePages": mapping.get("sourcePages", []), "rationale": str(mapping.get("rationale", "")), "status": "proposed", "review": None})
    if len({mapping["id"] for mapping in mappings}) != len(mappings):
        raise ContentToolError("Duplicate Lesson/Knowledge Unit mapping identity")
    if len({(subject["id"], chapter["grade"]) for subject in registry_subjects for chapter in subject["chapters"]}) > 50:
        raise ContentToolError("Framework exceeds the BE limit of 50 subject/grade links")
    registry = {"schemaVersion": 1, "framework": {"id": _framework_id(framework_key, version), "key": framework_key, "version": version, "title": title, "source": source}, "textbookIdentity": proposal.get("textbookIdentity"), "subjects": registry_subjects, "mappings": mappings, "createdAt": datetime.now(timezone.utc).isoformat(), "status": "proposed"}
    version_material = {key: registry[key] for key in ("framework", "textbookIdentity", "subjects", "mappings")}
    registry["proposalVersion"] = hashlib.sha256(json.dumps(version_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    path = _registry_path(workspace, framework_key, version)
    if path.exists():
        raise ContentToolError(f"Registry version already exists and is immutable: {path}")
    write_json(path, registry)
    return {"path": str(path), "registry": registry}


def review_registry(workspace: Workspace, framework_key: str, version: str, *, outcome_codes: dict[str, str], mapping_ids: list[str], reviewer_name: str, reviewer_email: str, reason: str, source_verified: bool = False) -> dict[str, Any]:
    """Record explicit local curriculum/mapping review; no approval is inferred."""
    path = _registry_path(workspace, framework_key, version)
    registry = read_json(path)
    if not reviewer_name.strip() or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reviewer_email.strip()) or len(reason.strip()) < 5:
        raise ContentToolError("A named reviewer, valid email and review reason are required")
    if source_verified is not True:
        raise ContentToolError("A human must verify the official source and its locators before approving this registry")
    all_outcomes = [outcome for subject in registry["subjects"] for chapter in subject["chapters"] for topic in chapter["topics"] for outcome in topic["outcomes"]]
    review_id = "curriculum-review-" + uuid.uuid4().hex
    keys = {outcome["key"] for outcome in all_outcomes}
    if set(outcome_codes) - keys:
        raise ContentToolError("Review references unknown outcome keys")
    for outcome in all_outcomes:
        if outcome["key"] not in outcome_codes:
            continue
        selected = str(outcome_codes[outcome["key"]]).strip()
        allowed = {outcome["internalCode"], *outcome.get("reviewCandidates", outcome["reuseCandidates"])}
        if selected not in allowed:
            raise ContentToolError(f"Outcome {outcome['key']} may only reuse an exact BE candidate or its generated internal code")
        outcome["approvedCode"] = selected
        outcome["status"] = "approved"
        outcome["review"] = {"reviewId": review_id, "proposalVersion": registry["proposalVersion"], "decision": "approved_official", "status": "approved", "reviewerName": reviewer_name.strip(), "reviewerEmail": reviewer_email.strip(), "reason": reason.strip(), "reviewedAt": datetime.now(timezone.utc).isoformat()}
    known_mapping_ids = {mapping["id"] for mapping in registry["mappings"]}
    if set(mapping_ids) - known_mapping_ids:
        raise ContentToolError("Review references unknown Lesson/Knowledge Unit mapping IDs")
    for mapping in registry["mappings"]:
        if mapping["id"] in mapping_ids:
            if not all(key in keys and next(item for item in all_outcomes if item["key"] == key)["status"] == "approved" for key in mapping["outcomeKeys"]):
                raise ContentToolError(f"Mapping {mapping['id']} cannot be approved before each outcome is approved")
            mapping["status"] = "approved"
            mapping["review"] = {"reviewId": review_id, "proposalVersion": registry["proposalVersion"], "decision": "approved_official", "status": "approved", "reviewerName": reviewer_name.strip(), "reviewerEmail": reviewer_email.strip(), "reason": reason.strip(), "reviewedAt": datetime.now(timezone.utc).isoformat()}
    registry["framework"]["source"]["review"] = {"reviewId": review_id, "proposalVersion": registry["proposalVersion"], "decision": "verified", "status": "verified", "reviewerName": reviewer_name.strip(), "reviewerEmail": reviewer_email.strip(), "reason": reason.strip(), "reviewedAt": datetime.now(timezone.utc).isoformat()}
    registry["status"] = "approved" if all(item["status"] == "approved" for item in all_outcomes) and all(item["status"] == "approved" for item in registry["mappings"]) else "partially_approved"
    write_json(path, registry)
    return {"path": str(path), "registry": registry}


def _api_request(base: str, token: str, path: str, body: dict[str, Any] | None = None, expected_project_ref: str | None = None) -> Any:
    parts = urllib.parse.urlsplit(base)
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if parts.scheme not in {"http", "https"} or (not local and (parts.scheme != "https" or not expected_project_ref)):
        raise ContentToolError("Curriculum sync is restricted to a local BE API or an explicitly verified remote development project")
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise ContentToolError(f"BE API {path} returned HTTP {error.code}: {detail[:500]}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ContentToolError(f"Could not reach the local BE API: {error}") from error


def sync_approved_registry(workspace: Workspace, framework_key: str, version: str, api_base: str, access_token: str, expected_project_ref: str | None = None) -> dict[str, Any]:
    """Create only approved missing records through existing BE admin APIs."""
    if not access_token.strip():
        raise ContentToolError("A current BE admin access token is required")
    path = _registry_path(workspace, framework_key, version)
    registry = read_json(path)
    source_review = registry.get("framework", {}).get("source", {}).get("review", {})
    if registry.get("status") != "approved" or not _review_record(source_review, "verified"):
        raise ContentToolError("All proposed outcomes and mappings must be explicitly approved before curriculum sync")
    for subject in registry["subjects"]:
        for chapter in subject["chapters"]:
            for topic in chapter["topics"]:
                for outcome in topic["outcomes"]:
                    if not _review_record(outcome.get("review"), "approved"):
                        raise ContentToolError(f"Outcome {outcome.get('key')} is missing its human approval record")
    for mapping in registry["mappings"]:
        if not _review_record(mapping.get("review"), "approved"):
            raise ContentToolError(f"Mapping {mapping.get('id')} is missing its human approval record")
    unsupported = [
        f"{chapter['code']} (grade={chapter['grade']}, domain={chapter['domain']})"
        for subject in registry["subjects"]
        for chapter in subject["chapters"]
        if chapter["grade"] not in (8, 9) or chapter["domain"] not in BE_SYNC_DOMAINS
    ]
    if unsupported:
        raise ContentToolError("Current BE Curriculum Registry API only accepts grades 8-9 and its configured domains; unsupported chapters: " + ", ".join(unsupported))
    target = _api_request(api_base, access_token, "/admin/curriculum-target", expected_project_ref=expected_project_ref)
    local_target = isinstance(target, dict) and target.get("localDevelopmentTarget") is True
    remote_target = isinstance(target, dict) and bool(expected_project_ref) and target.get("remoteDevelopmentTarget") is True and target.get("projectRef") == expected_project_ref
    if not isinstance(target, dict) or target.get("environment") != "development" or target.get("configuredConnections") != 2 or not (local_target or remote_target) or target.get("outcomeSourceEvidencePersisted") is not True:
        raise ContentToolError("BE did not confirm the requested development database and CurriculumOutcome.sourceEvidence migration; no curriculum writes were started")
    taxonomy = _api_request(api_base, access_token, "/admin/taxonomy", expected_project_ref=expected_project_ref)
    created: list[str] = []
    reused: list[str] = []
    source = registry["framework"]["source"]
    reason = f"Approved registry {framework_key}@{version}; source-sha256={source['sha256']}"
    subjects = {item["id"]: item for item in taxonomy.get("subjects", [])}
    frameworks = {item["id"]: item for item in taxonomy.get("frameworks", [])}
    chapters = {item["code"]: item for item in taxonomy.get("chapters", [])}
    topics = {item["code"]: item for item in taxonomy.get("topics", [])}
    outcomes = {item["code"]: item for item in taxonomy.get("outcomes", [])}
    created_outcome_codes: set[str] = set()
    for subject in registry["subjects"]:
        current = subjects.get(subject["id"])
        if current:
            if current.get("name") != subject["name"]:
                raise ContentToolError(f"Existing Subject {subject['id']} conflicts; no records were overwritten")
            reused.append(f"subject:{subject['id']}")
        else:
            _api_request(api_base, access_token, "/admin/subjects", {"id": subject["id"], "name": subject["name"], "reason": reason}, expected_project_ref)
            created.append(f"subject:{subject['id']}")

    framework_subjects = sorted({(subject["id"], chapter["grade"]) for subject in registry["subjects"] for chapter in subject["chapters"]})
    source_metadata = {key: source[key] for key in ("authority", "url", "publishedAt", "accessedAt", "sha256")}
    framework_payload = {"id": registry["framework"]["id"], "frameworkKey": framework_key, "title": registry["framework"]["title"], "version": version, "sourceMetadata": source_metadata, "subjects": [{"subjectId": subject_id, "grade": grade} for subject_id, grade in framework_subjects]}
    current_framework = frameworks.get(framework_payload["id"])
    if current_framework:
        existing_subjects = sorted((item["subjectId"], item["grade"]) for item in current_framework.get("subjects", []))
        desired_subjects = sorted(framework_subjects)
        if current_framework.get("frameworkKey") != framework_key or current_framework.get("title") != framework_payload["title"] or current_framework.get("version") != version or current_framework.get("sourceMetadata") != source_metadata or existing_subjects != desired_subjects:
            raise ContentToolError(f"Existing Framework {framework_payload['id']} conflicts; no records were overwritten")
        reused.append(f"framework:{framework_payload['id']}")
    else:
        _api_request(api_base, access_token, "/admin/frameworks", {**framework_payload, "reason": reason}, expected_project_ref)
        created.append(f"framework:{framework_payload['id']}")

    for subject in registry["subjects"]:
        for chapter in subject["chapters"]:
            current = chapters.get(chapter["code"])
            payload = {"code": chapter["code"], "subjectId": subject["id"], "grade": chapter["grade"], "domain": chapter["domain"], "title": chapter["title"]}
            if current:
                if any(current.get(key) != payload[key] for key in ("subjectId", "grade", "domain", "title")):
                    raise ContentToolError(f"Existing Chapter {chapter['code']} conflicts; no records were overwritten")
                reused.append(f"chapter:{chapter['code']}")
            else:
                _api_request(api_base, access_token, "/admin/chapters", {**payload, "reason": reason}, expected_project_ref)
                created.append(f"chapter:{chapter['code']}")
            for topic in chapter["topics"]:
                topic_codes = list(dict.fromkeys(item["approvedCode"] for item in topic["outcomes"]))
                for outcome in topic["outcomes"]:
                    code = outcome["approvedCode"]
                    current_outcome = outcomes.get(code)
                    source_evidence = _official_outcome_evidence(outcome, registry)
                    outcome_payload = {"code": code, "grade": chapter["grade"], "domain": chapter["domain"], "chapter": chapter["title"], "statement": outcome["officialStatement"]}
                    if current_outcome:
                        if current_outcome.get("grade") != outcome_payload["grade"] or current_outcome.get("domain") != outcome_payload["domain"] or current_outcome.get("status") != "active" or current_outcome.get("synthetic") is True:
                            raise ContentToolError(f"Existing Outcome {code} conflicts; no records were overwritten")
                        if code == outcome["internalCode"] and current_outcome.get("statement") != outcome_payload["statement"]:
                            raise ContentToolError(f"Existing generated Outcome {code} conflicts; no records were overwritten")
                        reused.append(f"outcome:{code}")
                        prior_evidence = current_outcome.get("sourceEvidence")
                        if prior_evidence is None:
                            prior_evidence = []
                        if not isinstance(prior_evidence, list):
                            raise ContentToolError(f"Existing Outcome {code} has invalid source evidence; no records were overwritten")
                        prior_by_id = {item.get("evidenceId"): item for item in prior_evidence}
                        previous = prior_by_id.get(source_evidence["evidenceId"])
                        if previous is not None and previous != source_evidence:
                            raise ContentToolError(f"Existing Outcome {code} has conflicting source evidence identity")
                        if previous is None:
                            _api_request(api_base, access_token, f"/admin/outcomes/{code}", {"statement": current_outcome["statement"], "status": current_outcome.get("status", "active"), "sourceEvidence": [source_evidence], "reason": reason + f" provenance-review={outcome['review']['reviewId']}"}, expected_project_ref)
                            current_outcome["sourceEvidence"] = [*prior_evidence, source_evidence]
                    elif code in created_outcome_codes:
                        reused.append(f"outcome:{code}")
                    elif code in outcome.get("reviewCandidates", outcome["reuseCandidates"]):
                        raise ContentToolError(f"Previously matched Outcome {code} is no longer present in BE taxonomy")
                    elif code != outcome["internalCode"]:
                        raise ContentToolError(f"Approved Outcome code {code} is neither an existing BE outcome nor its generated internal code")
                    else:
                        api_payload = {**outcome_payload, "sourceEvidence": [source_evidence], "reason": reason + f" locator={outcome['sourceLocator']} internalCode={outcome['internalCode']}"}
                        _api_request(api_base, access_token, "/admin/outcomes", api_payload, expected_project_ref)
                        created.append(f"outcome:{code}")
                        created_outcome_codes.add(code)
                        outcomes[code] = {**outcome_payload, "status": "active", "synthetic": False, "sourceEvidence": [source_evidence]}
                current_topic = topics.get(topic["code"])
                topic_payload = {"code": topic["code"], "chapterCode": chapter["code"], "title": topic["title"], "outcomeCodes": topic_codes}
                if current_topic:
                    if any(current_topic.get(key) != topic_payload[key] for key in ("chapterCode", "title", "outcomeCodes")):
                        raise ContentToolError(f"Existing Topic {topic['code']} conflicts; no records were overwritten")
                    reused.append(f"topic:{topic['code']}")
                else:
                    _api_request(api_base, access_token, "/admin/topics", {**topic_payload, "reason": reason}, expected_project_ref)
                    created.append(f"topic:{topic['code']}")
    mappings = apply_approved_mappings(workspace, registry)
    return {"framework": f"{framework_key}@{version}", "created": created, "reused": reused, "mappings": mappings, "writeTarget": api_base, "publishPerformed": False}


def apply_approved_mappings(workspace: Workspace, registry: dict[str, Any]) -> dict[str, Any]:
    """Apply reviewed curriculum codes to existing local Lesson drafts, preserving authored fields."""
    if registry.get("status") != "approved" or not _review_record(registry.get("framework", {}).get("source", {}).get("review"), "verified"):
        raise ContentToolError("Cannot apply mappings from an unreviewed curriculum registry")
    outcome_owner: dict[str, dict[str, Any]] = {}
    for subject in registry["subjects"]:
        for chapter in subject["chapters"]:
            for topic in chapter["topics"]:
                for outcome in topic["outcomes"]:
                    if outcome.get("status") == "approved" and outcome.get("approvedCode") and _review_record(outcome.get("review"), "approved"):
                        outcome_owner[outcome["key"]] = {"subjectId": subject["id"], "grade": chapter["grade"], "domain": chapter["domain"]}

    drafts = [read_json(path) for path in workspace.inside(".local", "lessons").glob("*.json")]
    by_source = {draft.get("sourceLessonId"): draft for draft in drafts if draft.get("sourceLessonId")}
    assignments: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for mapping in registry["mappings"]:
        if mapping.get("status") != "approved" or not _review_record(mapping.get("review"), "approved"):
            blockers.append(f"Mapping {mapping.get('id')}: not approved")
            continue
        draft = by_source.get(mapping["lessonId"])
        if draft is None:
            blockers.append(f"{mapping['lessonId']}: no saved Content Tool Lesson draft to map")
            continue
        target = assignments.setdefault(draft["packKey"], {"draft": draft, "subjectIds": set(), "grades": set(), "domains": set(), "lessonCodes": set(), "unitCodes": {unit.get("id"): set() for unit in draft.get("knowledgeUnits", [])}})
        codes = []
        for key in mapping["outcomeKeys"]:
            outcome = next((item for subject in registry["subjects"] for chapter in subject["chapters"] for topic in chapter["topics"] for item in topic["outcomes"] if item["key"] == key), None)
            if outcome is None or outcome.get("status") != "approved" or not outcome.get("approvedCode"):
                blockers.append(f"Mapping {mapping['id']}: outcome {key} is not approved")
                continue
            codes.append(outcome["approvedCode"])
            owner = outcome_owner[key]
            target["subjectIds"].add(owner["subjectId"])
            target["grades"].add(owner["grade"])
            target["domains"].add(owner["domain"])
        if mapping.get("knowledgeUnitId"):
            unit_id = mapping["knowledgeUnitId"]
            if unit_id not in target["unitCodes"]:
                blockers.append(f"Mapping {mapping['id']}: knowledge unit {unit_id} is absent from draft {draft['packKey']}")
                continue
            target["unitCodes"][unit_id].update(codes)
        else:
            target["lessonCodes"].update(codes)
    if blockers:
        return {"applied": [], "blockers": blockers}
    from .m1_workflow import save_draft

    applied = []
    for pack_key, assignment in assignments.items():
        draft = assignment["draft"]
        if len(assignment["subjectIds"]) != 1 or len(assignment["grades"]) != 1 or len(assignment["domains"]) != 1:
            blockers.append(f"{pack_key}: mappings span multiple subjects, grades or domains")
            continue
        if draft.get("grade") not in assignment["grades"] or draft.get("domain") not in assignment["domains"]:
            blockers.append(f"{pack_key}: draft grade/domain differs from approved curriculum mapping")
            continue
        unit_codes = assignment["unitCodes"]
        if unit_codes and any(not values and not assignment["lessonCodes"] for values in unit_codes.values()):
            blockers.append(f"{pack_key}: every Knowledge Unit needs an approved mapping")
            continue
        lesson_codes = sorted(assignment["lessonCodes"] | set().union(*unit_codes.values()) if unit_codes else assignment["lessonCodes"])
        if len(lesson_codes) > 30:
            blockers.append(f"{pack_key}: mapped outcomes exceed the BE pack limit of 30")
            continue
        updated_units = []
        for unit in draft.get("knowledgeUnits", []):
            codes = unit_codes.get(unit["id"], set()) or assignment["lessonCodes"]
            updated_units.append({**unit, "outcomeCodes": sorted(codes)})
        updated = {**draft, "subjectId": next(iter(assignment["subjectIds"])), "outcomeCodes": lesson_codes, "outcomeCode": lesson_codes[0], "knowledgeUnits": updated_units}
        save_draft(workspace, updated)
        applied.append(pack_key)
    return {"applied": applied, "blockers": blockers}


def _review_record(review: Any, status: str) -> bool:
    return isinstance(review, dict) and review.get("status", status) == status and all(str(review.get(key, "")).strip() for key in ("reviewerName", "reviewerEmail", "reason", "reviewedAt"))


def _official_outcome_evidence(outcome: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    review = outcome["review"]
    source = registry["framework"]["source"]
    evidence = {
        "originType": "official_curriculum",
        "sourceDigest": source["sha256"],
        "sourceIdentity": f"{registry['framework']['key']}@{registry['framework']['version']}",
        "sourceLocators": [{"locator": outcome["sourceLocator"]}],
        "reviewReference": {
            "proposalVersion": registry["proposalVersion"],
            "reviewId": review["reviewId"],
            "reviewerName": review["reviewerName"],
            "reviewerEmail": review["reviewerEmail"],
            "reason": review["reason"],
            "reviewedAt": review["reviewedAt"],
            "decision": "approved_official",
        },
    }
    evidence["evidenceId"] = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return evidence
