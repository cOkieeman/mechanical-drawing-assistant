from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from mechanical_drawing_assistant.adapters.dxf import DxfAdapter
from mechanical_drawing_assistant.adapters.solidworks import SolidWorksAdapter
from mechanical_drawing_assistant.cli import (
    attach_annotation_manifest,
    load_model_manifest,
    load_sheet_info,
    load_view_outlines,
    read_json_file,
)
from mechanical_drawing_assistant.diagnostics import diagnose_environment
from mechanical_drawing_assistant.knowledge import KnowledgeBase
from mechanical_drawing_assistant.pipeline import build_plan, load_job, run_pipeline, write_json
from mechanical_drawing_assistant.review import render_review_markdown, review_plan

PROJECT_ROOT = Path(__file__).resolve().parents[2]

mcp = FastMCP("mechanical-drawing-assistant")


@mcp.tool()
def diagnose_cad_environment() -> dict[str, Any]:
    """Report local CAD/MCP/DXF dependency status."""
    return diagnose_environment(PROJECT_ROOT)


@mcp.tool()
def plan_drawing(
    job_path: str,
    knowledge_path: str = "knowledge",
    output_path: str = "output/mcp/drawing_plan.json",
) -> dict[str, Any]:
    """Generate a drawing plan JSON file from a job file."""
    job = load_job(resolve_path(job_path))
    plan = build_plan(job, KnowledgeBase(resolve_path(knowledge_path)))
    output = resolve_path(output_path)
    write_json(output, plan.to_mapping())
    return {"status": "ok", "output_path": str(output), "plan": plan.to_mapping()}


@mcp.tool()
def run_drawing_pipeline(
    job_path: str,
    knowledge_path: str = "knowledge",
    output_dir: str = "output/mcp",
    live: bool = False,
) -> dict[str, Any]:
    """Run plan, export, and review steps. Defaults to dry-run."""
    output = resolve_path(output_dir)
    run_pipeline(
        resolve_path(job_path),
        resolve_path(knowledge_path),
        output,
        dry_run=not live,
    )
    return {
        "status": "ok",
        "mode": "live" if live else "dry-run",
        "output_dir": str(output),
        "files": {
            "drawing_plan": str(output / "drawing_plan.json"),
            "model_manifest": str(output / "model_manifest.json"),
            "export_manifest": str(output / "export_manifest.json"),
            "annotation_manifest": str(output / "annotation_manifest.json"),
            "review_report": str(output / "review_report.md"),
        },
    }


@mcp.tool()
def review_drawing_job(
    job_path: str,
    knowledge_path: str = "knowledge",
    manifest_path: str | None = None,
    annotation_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Return a Markdown review report for a drawing job."""
    job = load_job(resolve_path(job_path))
    plan = build_plan(job, KnowledgeBase(resolve_path(knowledge_path)))
    manifest: dict[str, Any] = {"mode": "dry-run"}
    if manifest_path:
        manifest_file = resolve_path(manifest_path)
        if manifest_file.exists():
            with manifest_file.open("r", encoding="utf-8") as file:
                manifest = json.load(file)
    if annotation_path:
        annotation_file = resolve_path(annotation_path)
        if annotation_file.exists():
            annotation = read_json_file(annotation_file)
            if isinstance(annotation, dict):
                manifest = attach_annotation_manifest(
                    manifest,
                    cast(dict[str, object], annotation),
                )
    findings = review_plan(plan, manifest)
    markdown = render_review_markdown(plan, findings)
    if output_path:
        output = resolve_path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
    return {
        "status": "ok",
        "finding_count": len(findings),
        "output_path": str(resolve_path(output_path)) if output_path else None,
        "markdown": markdown,
    }


@mcp.tool()
def inspect_dxf(path: str) -> dict[str, Any]:
    """Inspect a DXF file and summarize entity/dimension counts."""
    return DxfAdapter().inspect_file(resolve_path(path))


@mcp.tool()
def inspect_solidworks_model(
    model_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Inspect an open or specified SolidWorks model and optionally write model_manifest JSON."""
    result = SolidWorksAdapter().inspect_model(
        str(resolve_path(model_path)) if model_path else None,
        dry_run=False,
    )
    if output_path:
        write_json(resolve_path(output_path), result)
    return result


@mcp.tool()
def annotate_dxf_file(
    path: str,
    output_dxf_path: str,
    output_manifest_path: str,
    views_json_path: str | None = None,
    export_manifest_path: str | None = None,
    model_manifest_path: str | None = None,
) -> dict[str, Any]:
    """Annotate a DXF file, write annotated DXF, and write annotation manifest JSON."""
    output_manifest = resolve_path(output_manifest_path)
    result = DxfAdapter().annotate_file(
        resolve_path(path),
        output_path=resolve_path(output_dxf_path),
        view_outlines_m=load_view_outlines(
            resolve_path(views_json_path) if views_json_path else None,
            resolve_path(export_manifest_path) if export_manifest_path else None,
        ),
        model_manifest=load_model_manifest(
            resolve_path(model_manifest_path) if model_manifest_path else None,
            resolve_path(export_manifest_path) if export_manifest_path else None,
        ),
        sheet_info=load_sheet_info(
            resolve_path(export_manifest_path) if export_manifest_path else None
        ),
    )
    write_json(output_manifest, result)
    return {
        "status": result.get("status", "unknown"),
        "output_dxf_path": str(resolve_path(output_dxf_path)),
        "output_manifest_path": str(output_manifest),
        "dimensions_added": result.get("dimensions_added", 0),
        "annotation_review": result.get("annotation_review"),
    }


def resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
