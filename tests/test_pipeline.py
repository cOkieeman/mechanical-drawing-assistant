from pathlib import Path

from mechanical_drawing_assistant.adapters.solidworks import VIEW_POSITIONS_M
from mechanical_drawing_assistant.knowledge import KnowledgeBase
from mechanical_drawing_assistant.pipeline import build_plan, extract_annotation_manifest, load_job
from mechanical_drawing_assistant.review import review_plan

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_sample_job_builds_plan() -> None:
    job = load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json")
    plan = build_plan(job, KnowledgeBase(PROJECT_ROOT / "knowledge"))

    assert plan.job_name == "20丝杆-定制单带轮"
    assert plan.views == ["front", "top", "left"]
    assert len(plan.dimension_intents) >= 5
    assert any(intent.intent_id == "pulley_bore_diameter" for intent in plan.dimension_intents)


def test_gb_first_angle_view_positions() -> None:
    front_x, front_y = VIEW_POSITIONS_M["front"]
    top_x, top_y = VIEW_POSITIONS_M["top"]
    left_x, left_y = VIEW_POSITIONS_M["left"]

    assert top_x == front_x
    assert top_y < front_y
    assert left_x > front_x
    assert left_y == front_y


def test_review_reports_dry_run_context() -> None:
    job = load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json")
    plan = build_plan(job, KnowledgeBase(PROJECT_ROOT / "knowledge"))
    findings = review_plan(plan, {"mode": "dry-run"})

    assert any(finding.code == "DRY_RUN" for finding in findings)


def test_extract_annotation_manifest() -> None:
    manifest = {
        "steps": [
            {"action": "create_three_view_drawing"},
            {
                "action": "normalize_drawing",
                "dxf_annotation": {"status": "annotated", "dimensions_added": 3},
            },
        ]
    }

    annotation = extract_annotation_manifest(manifest)

    assert annotation is not None
    assert annotation["dimensions_added"] == 3
