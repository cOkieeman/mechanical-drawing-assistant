from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mechanical_drawing_assistant.adapters.autocad import AutoCadAdapter
from mechanical_drawing_assistant.adapters.solidworks import SolidWorksAdapter
from mechanical_drawing_assistant.knowledge import KnowledgeBase
from mechanical_drawing_assistant.models import DrawingJob, DrawingPlan, JsonObject, path_exists
from mechanical_drawing_assistant.review import render_review_markdown, review_plan


def load_job(path: Path) -> DrawingJob:
    with path.open("r", encoding="utf-8") as file:
        data: Any = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("Job file must contain a JSON object.")
    return DrawingJob.from_mapping(data)


def build_plan(job: DrawingJob, knowledge: KnowledgeBase) -> DrawingPlan:
    templates = job.feature_templates or ["basic_mechanical"]
    warnings: list[str] = []

    if job.part.source_model and not path_exists(job.part.source_model):
        warnings.append(f"SolidWorks source model not found yet: {job.part.source_model}")
    if job.part.source_dwg and not path_exists(job.part.source_dwg):
        warnings.append(f"Reference DWG not found yet: {job.part.source_dwg}")
    if not job.part.source_model:
        warnings.append(
            "No SolidWorks source model provided; generation will stay in planning/dry-run mode."
        )

    output_root = Path(job.output.workdir)
    planned_outputs = [
        str(output_root / f"{job.output.drawing_basename}.{extension.lower()}")
        for extension in job.output.export_formats
    ]

    return DrawingPlan(
        job_name=job.job_name,
        part=job.part,
        views=job.views,
        standards=knowledge.load_standard_index(),
        dimension_intents=knowledge.load_dimension_intents(templates),
        planned_outputs=planned_outputs,
        warnings=warnings,
    )


def export_plan(plan: DrawingPlan, output_dir: Path, dry_run: bool = True) -> JsonObject:
    solidworks = SolidWorksAdapter()
    autocad = AutoCadAdapter()

    export_manifest: JsonObject = {
        "job_name": plan.job_name,
        "mode": "dry-run" if dry_run else "live",
        "solidworks_available": solidworks.is_available(),
        "autocad_available": autocad.is_available(),
        "planned_outputs": plan.planned_outputs,
        "steps": [],
    }

    solidworks_create_result = solidworks.create_three_view_drawing(plan, dry_run=dry_run)
    export_manifest["steps"].append(solidworks_create_result)
    export_manifest["steps"].append(solidworks.export_outputs(plan, dry_run=dry_run))
    export_manifest["steps"].append(
        autocad.normalize_drawing(
            plan,
            dry_run=dry_run,
            solidworks_result=solidworks_create_result,
        )
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    return export_manifest


def run_pipeline(
    job_path: Path,
    knowledge_root: Path,
    output_dir: Path,
    dry_run: bool = True,
) -> None:
    job = load_job(job_path)
    knowledge = KnowledgeBase(knowledge_root)
    plan = build_plan(job, knowledge)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "drawing_plan.json", plan.to_mapping())

    manifest = export_plan(plan, output_dir, dry_run=dry_run)
    write_json(output_dir / "export_manifest.json", manifest)
    annotation_manifest = extract_annotation_manifest(manifest)
    if annotation_manifest:
        write_json(output_dir / "annotation_manifest.json", annotation_manifest)

    findings = review_plan(plan, manifest)
    (output_dir / "review_report.md").write_text(
        render_review_markdown(plan, findings),
        encoding="utf-8",
    )


def write_json(path: Path, data: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def extract_annotation_manifest(export_manifest: JsonObject) -> JsonObject | None:
    steps = export_manifest.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        annotation = step.get("dxf_annotation")
        if isinstance(annotation, dict) and annotation.get("status") == "annotated":
            return annotation
    return None
