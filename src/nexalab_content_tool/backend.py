from __future__ import annotations

import os
import re
import subprocess
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
