from __future__ import annotations

import argparse
import json
from pathlib import Path

from mechanical_drawing_assistant.adapters.dxf import DxfAdapter
from mechanical_drawing_assistant.diagnostics import diagnose_environment
from mechanical_drawing_assistant.knowledge import KnowledgeBase
from mechanical_drawing_assistant.pipeline import (
    build_plan,
    export_plan,
    load_job,
    run_pipeline,
    write_json,
)
from mechanical_drawing_assistant.review import render_review_markdown, review_plan


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.handler(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mda",
        description="Mechanical drawing assistant for annotation planning and review.",
    )
    parser.set_defaults(handler=handle_help)
    subparsers = parser.add_subparsers(dest="command")

    plan_parser = subparsers.add_parser("plan", help="Generate drawing_plan.json.")
    add_common_inputs(plan_parser)
    plan_parser.add_argument("--out", type=Path, required=True)
    plan_parser.set_defaults(handler=handle_plan)

    export_parser = subparsers.add_parser("export", help="Generate export_manifest.json.")
    export_parser.add_argument("--plan", type=Path, required=True)
    export_parser.add_argument("--out", type=Path, required=True)
    export_parser.add_argument(
        "--live",
        action="store_true",
        help="Use live CAD adapters when implemented.",
    )
    export_parser.set_defaults(handler=handle_export)

    review_parser = subparsers.add_parser("review", help="Generate review_report.md.")
    add_common_inputs(review_parser)
    review_parser.add_argument("--manifest", type=Path)
    review_parser.add_argument("--out", type=Path, required=True)
    review_parser.set_defaults(handler=handle_review)

    run_parser = subparsers.add_parser("run", help="Run plan, export, and review.")
    add_common_inputs(run_parser)
    run_parser.add_argument("--out-dir", type=Path, required=True)
    run_parser.add_argument(
        "--live",
        action="store_true",
        help="Use live CAD adapters when implemented.",
    )
    run_parser.set_defaults(handler=handle_run)

    diagnose_parser = subparsers.add_parser("diagnose", help="Check CAD/MCP/DXF environment.")
    diagnose_parser.add_argument("--out", type=Path)
    diagnose_parser.set_defaults(handler=handle_diagnose)

    dxf_parser = subparsers.add_parser("inspect-dxf", help="Inspect a DXF file.")
    dxf_parser.add_argument("path", type=Path)
    dxf_parser.add_argument("--out", type=Path)
    dxf_parser.set_defaults(handler=handle_inspect_dxf)

    return parser


def add_common_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, default=Path("knowledge"))


def handle_help(args: argparse.Namespace) -> None:
    raise SystemExit("Run `mda --help` to see available commands.")


def handle_plan(args: argparse.Namespace) -> None:
    job = load_job(args.job)
    plan = build_plan(job, KnowledgeBase(args.knowledge))
    write_json(args.out, plan.to_mapping())
    print(f"Wrote drawing plan: {args.out}")


def handle_export(args: argparse.Namespace) -> None:
    from mechanical_drawing_assistant.models import DrawingPlan, PartInput

    with args.plan.open("r", encoding="utf-8") as file:
        data = json.load(file)

    part = PartInput.from_mapping(data["part"])
    plan = DrawingPlan(
        job_name=data["job_name"],
        part=part,
        views=data["views"],
        standards=data["standards"],
        dimension_intents=[],
        planned_outputs=data["planned_outputs"],
        warnings=data.get("warnings", []),
    )
    manifest = export_plan(plan, args.out.parent, dry_run=not args.live)
    write_json(args.out, manifest)
    print(f"Wrote export manifest: {args.out}")


def handle_review(args: argparse.Namespace) -> None:
    job = load_job(args.job)
    plan = build_plan(job, KnowledgeBase(args.knowledge))
    manifest = {"mode": "dry-run"}
    if args.manifest and args.manifest.exists():
        with args.manifest.open("r", encoding="utf-8") as file:
            manifest = json.load(file)
    findings = review_plan(plan, manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_review_markdown(plan, findings), encoding="utf-8")
    print(f"Wrote review report: {args.out}")


def handle_run(args: argparse.Namespace) -> None:
    run_pipeline(args.job, args.knowledge, args.out_dir, dry_run=not args.live)
    print(f"Wrote pipeline outputs under: {args.out_dir}")


def handle_diagnose(args: argparse.Namespace) -> None:
    data = diagnose_environment(Path(__file__).resolve().parents[2])
    emit_json(data, args.out)


def handle_inspect_dxf(args: argparse.Namespace) -> None:
    data = DxfAdapter().inspect_file(args.path)
    emit_json(data, args.out)


def emit_json(data: object, output_path: Path | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        print(f"Wrote JSON: {output_path}")
    else:
        print(text)
