from __future__ import annotations

import os
import json
import re
import subprocess
import sys
from pathlib import Path

from .manifest import export_manifest
from .workspace import ContentToolError, Workspace


TARGET_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,39}$")


def run_plan(workspace: Workspace, backend_path: str | Path, target: str) -> int:
    if not TARGET_PATTERN.fullmatch(target):
        raise ContentToolError("Target must be an explicit lowercase environment name")
    backend = Path(backend_path).resolve()
    if not (backend / "package.json").is_file() or not (backend / "scripts/content-release.ts").is_file():
        raise ContentToolError(f"Not a NexaLab backend checkout: {backend}")
    manifest_path, _ = export_manifest(workspace)
    executable = "npm.cmd" if os.name == "nt" else "npm"
    command = [
        executable,
        "run",
        "content:release",
        "--",
        "--manifest",
        str(manifest_path),
        "--target",
        target,
    ]
    if "--apply" in command:
        raise ContentToolError("The Content Tool M1 plan command cannot apply a release")
    try:
        completed = subprocess.run(command, cwd=backend, check=False, timeout=300)
    except FileNotFoundError as error:
        raise ContentToolError(f"Cannot find {executable}") from error
    except subprocess.TimeoutExpired as error:
        raise ContentToolError("Backend dry run exceeded the 300-second safety timeout") from error
    return completed.returncode


def run_apply(
    workspace: Workspace,
    backend_path: str | Path,
    target: str,
    initiated_by: str,
    approved_by: str,
    confirm_digest: str,
) -> int:
    if not TARGET_PATTERN.fullmatch(target):
        raise ContentToolError("Target must be an explicit lowercase environment name")
    if not initiated_by.strip() or not approved_by.strip():
        raise ContentToolError("Initiator and approver account emails are required")
    backend = Path(backend_path).resolve()
    if not (backend / "package.json").is_file() or not (backend / "scripts/content-release.ts").is_file():
        raise ContentToolError(f"Not a NexaLab backend checkout: {backend}")
    manifest_path, _ = export_manifest(workspace)
    executable = "npm.cmd" if os.name == "nt" else "npm"
    base_command = [executable, "run", "content:release", "--", "--manifest", str(manifest_path), "--target", target]
    try:
        plan = subprocess.run(base_command, cwd=backend, check=False, timeout=300, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise ContentToolError(f"Cannot find {executable}") from error
    except subprocess.TimeoutExpired as error:
        raise ContentToolError("Backend dry run exceeded the 300-second safety timeout") from error
    print(plan.stdout, end="")
    if plan.stderr:
        print(plan.stderr, end="", file=sys.stderr)
    if plan.returncode:
        return plan.returncode

    result = _release_plan(plan.stdout)
    if result.get("blocked") is not False or result.get("target") != target or result.get("environment") != target:
        raise ContentToolError("Backend plan is blocked or its target/environment does not match")
    digest = result.get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ContentToolError("Backend plan did not return a valid release digest")
    if confirm_digest != digest:
        raise ContentToolError(f"Digest confirmation mismatch; review the plan and pass --confirm-digest {digest}")

    apply_command = [
        *base_command,
        "--apply",
        "--initiated-by",
        initiated_by,
        "--approved-by",
        approved_by,
    ]
    try:
        applied = subprocess.run(apply_command, cwd=backend, check=False, timeout=300)
    except FileNotFoundError as error:
        raise ContentToolError(f"Cannot find {executable}") from error
    except subprocess.TimeoutExpired as error:
        raise ContentToolError("Backend apply exceeded the 300-second safety timeout") from error
    return applied.returncode


def _release_plan(output: str) -> dict[str, object]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(output):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and {"blocked", "digest", "target", "environment"} <= value.keys():
            return value
    raise ContentToolError("Could not read the backend release plan JSON")
