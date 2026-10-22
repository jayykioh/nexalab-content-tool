from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .backend import run_apply, run_plan
from .extract import extract_native_pdf
from .identity import reserve_id
from .manifest import export_manifest
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

    export = commands.add_parser("export", help="export a deterministic current-schema release manifest")
    export.add_argument("workspace")
    export.add_argument("--output")

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
        if args.command == "export":
            path, digest = export_manifest(workspace, args.output)
            print(f"{path}\nsha256={digest}")
            return 0
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
