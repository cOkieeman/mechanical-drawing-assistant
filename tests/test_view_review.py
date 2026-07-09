from pathlib import Path

from mechanical_drawing_assistant.knowledge import KnowledgeBase
from mechanical_drawing_assistant.models import DrawingJob, DrawingPlan, JsonObject
from mechanical_drawing_assistant.pipeline import build_plan, load_job
from mechanical_drawing_assistant.view_review import review_drawing_views

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_view_review_accepts_first_angle_front_top_left_layout() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )

    result = review_drawing_views(plan, _first_angle_views())

    assert result["status"] == "passed"
    assert result["expected_views"] == ["front", "top", "left"]
    assert "annotation_space" in result["checks"]
    assert "safe_area" in result["checks"]
    assert not _codes(result)


def test_view_review_reports_wrong_first_angle_layout() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )
    inserted_views = [
        _view("front", [0.13, 0.17], [0.08, 0.13, 0.18, 0.21]),
        _view("top", [0.13, 0.25], [0.08, 0.22, 0.18, 0.28]),
        _view("left", [0.04, 0.17], [0.00, 0.13, 0.08, 0.21]),
    ]

    result = review_drawing_views(plan, inserted_views)

    assert result["status"] == "error"
    assert "VIEW_TOP_POSITION" in _codes(result)
    assert "VIEW_LEFT_POSITION" in _codes(result)


def test_view_review_reports_right_view_wrong_side_for_first_angle() -> None:
    plan = _right_view_plan()

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.13, 0.17], [0.08, 0.13, 0.18, 0.21]),
            _view("right", [0.27, 0.17], [0.23, 0.13, 0.33, 0.21]),
        ],
    )

    assert result["status"] == "error"
    assert "VIEW_RIGHT_POSITION" in _codes(result)


def test_view_review_accepts_right_view_on_left_side_for_first_angle() -> None:
    plan = _right_view_plan()

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.20, 0.17], [0.15, 0.13, 0.25, 0.21]),
            _view("right", [0.08, 0.17], [0.03, 0.13, 0.13, 0.21]),
        ],
    )

    assert result["status"] == "passed"
    assert not _codes(result)


def test_view_review_reports_right_view_vertical_misalignment() -> None:
    plan = _right_view_plan()

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.20, 0.17], [0.15, 0.13, 0.25, 0.21]),
            _view("right", [0.08, 0.23], [0.03, 0.19, 0.13, 0.27]),
        ],
    )

    assert result["status"] == "warning"
    assert "VIEW_RIGHT_ALIGNMENT" in _codes(result)


def test_view_review_reports_missing_position_and_outline() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.13, 0.17], [0.08, 0.13, 0.18, 0.21]),
            _view_without_geometry("top"),
            _view("left", [0.27, 0.17], [0.23, 0.13, 0.33, 0.21]),
        ],
    )

    assert result["status"] == "warning"
    assert "VIEW_POSITION_MISSING" in _codes(result)
    finding = _finding_by_code(result, "VIEW_POSITION_MISSING")
    assert finding["details"]["view"] == "top"


def test_view_review_reports_missing_outline_even_when_position_exists() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.13, 0.17], [0.08, 0.13, 0.18, 0.21]),
            _view_without_outline("top", [0.13, 0.055]),
            _view("left", [0.27, 0.17], [0.23, 0.13, 0.33, 0.21]),
        ],
    )

    assert result["status"] == "warning"
    assert "VIEW_OUTLINE_MISSING" in _codes(result)
    assert "VIEW_POSITION_MISSING" not in _codes(result)
    finding = _finding_by_code(result, "VIEW_OUTLINE_MISSING")
    assert finding["details"]["view"] == "top"


def test_view_review_reports_failed_view_insertions() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.13, 0.17], [0.08, 0.13, 0.18, 0.21]),
            _view("top", [0.13, 0.055], [0.08, 0.02, 0.18, 0.09]),
        ],
        failed_views=[
            {
                "view": "left",
                "status": "failed",
                "candidates": ["*Left", "*左视"],
                "last_error": "fake COM failure",
            }
        ],
    )

    assert result["status"] == "error"
    assert result["failed_views"] == ["left"]
    assert "VIEW_MISSING" in _codes(result)
    assert "VIEW_INSERT_FAILED" in _codes(result)
    finding = _finding_by_code(result, "VIEW_INSERT_FAILED")
    assert finding["details"]["last_error"] == "fake COM failure"
    assert finding["details"]["candidates"] == ["*Left", "*左视"]


def test_view_review_reports_unknown_layout_rule_as_info() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )
    plan.view_plan["layout_rule"] = "third_angle_front_top_above_left_left"

    result = review_drawing_views(plan, _first_angle_views())

    assert result["status"] == "passed"
    assert "VIEW_LAYOUT_RULE" in _codes(result)
    finding = _finding_by_code(result, "VIEW_LAYOUT_RULE")
    assert finding["severity"] == "INFO"


def test_view_review_reports_overlap_and_title_block_intrusion() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )
    inserted_views = [
        _view("front", [0.13, 0.17], [0.08, 0.13, 0.18, 0.21]),
        _view("top", [0.13, 0.055], [0.09, 0.12, 0.19, 0.20]),
        _view("left", [0.30, 0.04], [0.27, 0.01, 0.36, 0.05]),
    ]

    result = review_drawing_views(plan, inserted_views)

    assert result["status"] == "error"
    assert "VIEW_OVERLAP" in _codes(result)
    assert "VIEW_TITLE_BLOCK" in _codes(result)


def test_view_review_keeps_pending_extra_view_recommendations() -> None:
    job = DrawingJob.from_mapping(
        {
            "job_name": "sleeve-auto-view-review",
            "part": {
                "name": "sleeve",
                "category": "turned_mounting_sleeve",
            },
            "drawing_standard": "GB",
            "feature_templates": ["basic_mechanical"],
            "output": {
                "workdir": "output/sleeve-auto-view-review",
                "drawing_basename": "sleeve",
                "export_formats": ["dxf"],
            },
        }
    )
    plan = build_plan(job, KnowledgeBase(PROJECT_ROOT / "knowledge"))

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.13, 0.17], [0.08, 0.13, 0.18, 0.21]),
            _view("left", [0.27, 0.17], [0.23, 0.13, 0.33, 0.21]),
        ],
    )

    assert result["status"] == "passed"
    assert result["recommended_extra_views"] == ["section_view_for_internal_bore"]
    assert result["implemented_extra_views"] == []
    assert result["pending_extra_views"] == ["section_view_for_internal_bore"]
    assert "pending_extra_views" in result["checks"]
    assert "VIEW_PENDING_EXTRA" in _codes(result)
    pending_finding = _finding_by_code(result, "VIEW_PENDING_EXTRA")
    assert pending_finding["severity"] == "INFO"
    assert pending_finding["details"]["automation_status"] == "not_executed"
    assert pending_finding["details"]["pending_extra_views"] == ["section_view_for_internal_bore"]
    assert pending_finding["details"]["pending_extra_view_requests"][0]["id"] == (
        "section_view_for_internal_bore"
    )


def test_view_review_clears_pending_extra_view_when_inserted() -> None:
    job = DrawingJob.from_mapping(
        {
            "job_name": "sleeve-extra-view-done",
            "part": {
                "name": "sleeve",
                "category": "turned_mounting_sleeve",
            },
            "drawing_standard": "GB",
            "feature_templates": ["basic_mechanical"],
            "output": {
                "workdir": "output/sleeve-extra-view-done",
                "drawing_basename": "sleeve",
                "export_formats": ["dxf"],
            },
        }
    )
    plan = build_plan(job, KnowledgeBase(PROJECT_ROOT / "knowledge"))

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.13, 0.17], [0.08, 0.13, 0.18, 0.21]),
            _view("left", [0.27, 0.17], [0.23, 0.13, 0.33, 0.21]),
            _view(
                "section-a",
                [0.37, 0.17],
                [0.34, 0.13, 0.40, 0.21],
                extra_view_request_id="section_view_for_internal_bore",
                view_type="section",
            ),
        ],
    )

    assert result["status"] == "passed"
    assert result["implemented_extra_views"] == ["section_view_for_internal_bore"]
    assert result["pending_extra_views"] == []
    assert result["pending_extra_view_requests"] == []
    assert "VIEW_PENDING_EXTRA" not in _codes(result)


def test_view_review_reports_small_views_and_annotation_space() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.015, 0.17], [0.005, 0.13, 0.025, 0.15]),
            _view("top", [0.015, 0.055], [0.005, 0.02, 0.025, 0.04]),
            _view("left", [0.27, 0.17], [0.23, 0.13, 0.33, 0.21]),
        ],
    )

    assert "VIEW_SCALE_SMALL" in _codes(result)
    assert "VIEW_ANNOTATION_SPACE" in _codes(result)


def test_view_review_reports_view_outside_sheet_and_safe_area() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )

    result = review_drawing_views(
        plan,
        [
            _view("front", [0.13, 0.17], [-0.002, 0.13, 0.18, 0.21]),
            _view("top", [0.13, 0.055], [0.08, 0.02, 0.18, 0.09]),
            _view("left", [0.27, 0.17], [0.23, 0.13, 0.33, 0.21]),
        ],
    )

    assert result["status"] == "error"
    assert result["safe_area_source"] == "standard_profile_safe_margin"
    assert "VIEW_OUTSIDE_SHEET" in _codes(result)
    assert "VIEW_OUTSIDE_SAFE_AREA" in _codes(result)
    sheet_finding = _finding_by_code(result, "VIEW_OUTSIDE_SHEET")
    safe_area_finding = _finding_by_code(result, "VIEW_OUTSIDE_SAFE_AREA")
    assert sheet_finding["details"]["violations"] == ["left"]
    assert safe_area_finding["details"]["violations"] == ["left"]


def test_view_review_uses_solidworks_sheet_info_when_available() -> None:
    plan = build_plan(
        load_job(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
        KnowledgeBase(PROJECT_ROOT / "knowledge"),
    )

    result = review_drawing_views(
        plan,
        _first_angle_views(),
        sheet_info={
            "sheet_size_m": [0.420, 0.297],
            "safe_area_m": [0.006, 0.006, 0.414, 0.291],
            "title_block_zone_m": [0.240, 0.000, 0.420, 0.060],
        },
    )

    assert result["title_block_source"] == "solidworks_sheet_title_block"
    assert result["safe_area_source"] == "solidworks_sheet_safe_area"
    assert result["sheet_size_m"] == [0.42, 0.297]
    assert result["safe_area_m"] == [0.006, 0.006, 0.414, 0.291]


def _first_angle_views() -> list[JsonObject]:
    return [
        _view("front", [0.13, 0.17], [0.08, 0.13, 0.18, 0.21]),
        _view("top", [0.13, 0.055], [0.08, 0.02, 0.18, 0.09]),
        _view("left", [0.27, 0.17], [0.23, 0.13, 0.33, 0.21]),
    ]


def _right_view_plan() -> DrawingPlan:
    job = DrawingJob.from_mapping(
        {
            "job_name": "right-view-layout-review",
            "part": {
                "name": "manual-right-view",
                "category": "plate",
            },
            "drawing_standard": "GB",
            "feature_templates": ["basic_mechanical"],
            "views": ["front", "right"],
            "output": {
                "workdir": "output/right-view-layout-review",
                "drawing_basename": "right-view-layout-review",
                "export_formats": ["dxf"],
            },
        }
    )
    return build_plan(job, KnowledgeBase(PROJECT_ROOT / "knowledge"))


def _view(
    view: str,
    position_m: list[float],
    outline_m: list[float],
    **extra: object,
) -> JsonObject:
    return {
        "view": view,
        "status": "inserted",
        "position_m": position_m,
        "outline_m": outline_m,
        **extra,
    }


def _view_without_outline(view: str, position_m: list[float]) -> JsonObject:
    return {
        "view": view,
        "status": "inserted",
        "position_m": position_m,
    }


def _view_without_geometry(view: str) -> JsonObject:
    return {
        "view": view,
        "status": "inserted",
    }


def _codes(result: JsonObject) -> set[str]:
    findings = result.get("findings")
    if not isinstance(findings, list):
        return set()
    return {finding["code"] for finding in findings if isinstance(finding, dict)}


def _finding_by_code(result: JsonObject, code: str) -> JsonObject:
    findings = result.get("findings")
    if not isinstance(findings, list):
        raise AssertionError(f"No findings found for code={code}")
    for finding in findings:
        if isinstance(finding, dict) and finding.get("code") == code:
            return finding
    raise AssertionError(f"Finding not found: {code}")
