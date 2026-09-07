from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from mechanical_drawing_assistant.adapters.dxf import DxfAdapter
from mechanical_drawing_assistant.adapters.solidworks import SolidWorksAdapter
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
from mechanical_drawing_assistant.runtime import default_knowledge_path, project_root
from mechanical_drawing_assistant.webui import run_webui


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
    review_parser.add_argument(
        "--annotation",
        type=Path,
        help="annotation_manifest.json produced by `mda annotate-dxf`.",
    )
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

    webui_parser = subparsers.add_parser("webui", help="Run the local Web UI.")
    webui_parser.add_argument("--host", default="127.0.0.1")
    webui_parser.add_argument("--port", type=int, default=8765)
    webui_parser.add_argument("--open", action="store_true", help="Open the browser automatically.")
    webui_parser.add_argument("--log-dir", type=Path)
    webui_parser.set_defaults(handler=handle_webui)

    inspect_model_parser = subparsers.add_parser(
        "inspect-solidworks-model",
        help="Inspect an open or specified SolidWorks model and write model_manifest JSON.",
    )
    inspect_model_parser.add_argument(
        "--model",
        type=Path,
        help="Optional .SLDPRT/.SLDASM path. Defaults to the active SolidWorks model.",
    )
    inspect_model_parser.add_argument("--out", type=Path)
    inspect_model_parser.set_defaults(handler=handle_inspect_solidworks_model)

    dxf_parser = subparsers.add_parser("inspect-dxf", help="Inspect a DXF file.")
    dxf_parser.add_argument("path", type=Path)
    dxf_parser.add_argument("--out", type=Path)
    dxf_parser.set_defaults(handler=handle_inspect_dxf)

    annotate_dxf_parser = subparsers.add_parser(
        "annotate-dxf",
        help="Annotate a DXF file and write annotation_manifest JSON.",
    )
    annotate_dxf_parser.add_argument("path", type=Path)
    annotate_dxf_parser.add_argument("--output-dxf", type=Path, required=True)
    annotate_dxf_parser.add_argument("--out", type=Path, required=True)
    annotate_dxf_parser.add_argument(
        "--views-json",
        type=Path,
        help="JSON file containing a list of SolidWorks inserted view objects.",
    )
    annotate_dxf_parser.add_argument(
        "--manifest",
        type=Path,
        help="export_manifest.json containing a SolidWorks step with inserted_views.",
    )
    annotate_dxf_parser.add_argument(
        "--model-manifest",
        type=Path,
        help="model_manifest.json produced by `mda inspect-solidworks-model`.",
    )
    annotate_dxf_parser.set_defaults(handler=handle_annotate_dxf)

    return parser


def add_common_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, default=default_knowledge_path())


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
        view_plan=data.get("view_plan", {"source": "loaded_plan", "views": data["views"]}),
        standards=data["standards"],
        standard_profile=data.get("standard_profile"),
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
    if args.annotation and args.annotation.exists():
        annotation = read_json_file(args.annotation)
        if not isinstance(annotation, dict):
            raise ValueError("--annotation must contain a JSON object.")
        manifest = attach_annotation_manifest(
            manifest,
            cast(dict[str, object], annotation),
        )
    findings = review_plan(plan, manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_review_markdown(plan, findings), encoding="utf-8")
    print(f"Wrote review report: {args.out}")


def handle_run(args: argparse.Namespace) -> None:
    run_pipeline(args.job, args.knowledge, args.out_dir, dry_run=not args.live)
    print(f"Wrote pipeline outputs under: {args.out_dir}")


def handle_diagnose(args: argparse.Namespace) -> None:
    data = diagnose_environment(project_root())
    emit_json(data, args.out)


def handle_webui(args: argparse.Namespace) -> None:
    run_webui(
        host=args.host,
        port=args.port,
        open_browser=args.open,
        log_dir=args.log_dir,
    )


def handle_inspect_solidworks_model(args: argparse.Namespace) -> None:
    data = SolidWorksAdapter().inspect_model(
        str(args.model) if args.model else None,
        dry_run=False,
    )
    emit_json(data, args.out)


def handle_inspect_dxf(args: argparse.Namespace) -> None:
    data = DxfAdapter().inspect_file(args.path)
    emit_json(data, args.out)


def handle_annotate_dxf(args: argparse.Namespace) -> None:
    view_outlines = load_view_outlines(args.views_json, args.manifest)
    model_manifest = load_model_manifest(args.model_manifest, args.manifest)
    sheet_info = load_sheet_info(args.manifest)
    data = DxfAdapter().annotate_file(
        args.path,
        output_path=args.output_dxf,
        view_outlines_m=view_outlines,
        model_manifest=model_manifest,
        sheet_info=sheet_info,
    )
    emit_json(data, args.out)


def load_view_outlines(views_json: Path | None, manifest: Path | None) -> list[dict[str, object]]:
    if views_json:
        data = read_json_file(views_json)
        if isinstance(data, list):
            return [cast(dict[str, object], item) for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            inserted_views = data.get("inserted_views")
            if isinstance(inserted_views, list):
                return [
                    cast(dict[str, object], item)
                    for item in inserted_views
                    if isinstance(item, dict)
                ]
        raise ValueError("--views-json must contain a list or an object with inserted_views.")

    if manifest:
        data = read_json_file(manifest)
        if not isinstance(data, dict):
            raise ValueError("--manifest must contain a JSON object.")
        return extract_inserted_views_from_manifest(cast(dict[str, object], data))

    return []


def extract_inserted_views_from_manifest(manifest: dict[str, object]) -> list[dict[str, object]]:
    steps = manifest.get("steps")
    if not isinstance(steps, list):
        return []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("action") != "create_three_view_drawing":
            continue
        inserted_views = step.get("inserted_views")
        if isinstance(inserted_views, list):
            return [
                cast(dict[str, object], item) for item in inserted_views if isinstance(item, dict)
            ]
    return []


def load_model_manifest(
    model_manifest_path: Path | None,
    export_manifest_path: Path | None,
) -> dict[str, object] | None:
    if model_manifest_path:
        data = read_json_file(model_manifest_path)
        if not isinstance(data, dict):
            raise ValueError("--model-manifest must contain a JSON object.")
        return cast(dict[str, object], data)

    if export_manifest_path:
        data = read_json_file(export_manifest_path)
        if not isinstance(data, dict):
            raise ValueError("--manifest must contain a JSON object.")
        steps = data.get("steps")
        if not isinstance(steps, list):
            return None
        for step in steps:
            if isinstance(step, dict) and step.get("action") == "inspect_model":
                return cast(dict[str, object], step)
    return None


def load_sheet_info(
    export_manifest_path: Path | None,
) -> dict[str, object] | None:
    if not export_manifest_path:
        return None
    data = read_json_file(export_manifest_path)
    if not isinstance(data, dict):
        raise ValueError("--manifest must contain a JSON object.")
    steps = data.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict) or step.get("action") != "create_three_view_drawing":
            continue
        sheet_info = step.get("sheet_info")
        if isinstance(sheet_info, dict):
            return cast(dict[str, object], sheet_info)
    return None


def attach_annotation_manifest(
    manifest: object,
    annotation: dict[str, object],
) -> dict[str, object]:
    result: dict[str, object] = (
        {str(key): value for key, value in manifest.items()}
        if isinstance(manifest, dict)
        else {"mode": "live"}
    )
    if result.get("mode") == "dry-run":
        result["mode"] = "live"

    raw_steps = result.get("steps")
    if isinstance(raw_steps, list):
        steps: list[object] = cast(list[object], raw_steps)
    else:
        steps = []
        result["steps"] = steps

    annotation_step: dict[str, object] = {
        "adapter": "autocad",
        "action": "normalize_drawing",
        "status": "completed",
        "dxf_annotation": annotation,
        "note": "Annotation manifest attached during review.",
    }
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        if step.get("action") == "normalize_drawing" or "dxf_annotation" in step:
            steps[index] = annotation_step
            break
    else:
        steps.append(annotation_step)
    return result


def read_json_file(path: Path) -> object:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def emit_json(data: object, output_path: Path | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        print(f"Wrote JSON: {output_path}")
    else:
        print(text)
