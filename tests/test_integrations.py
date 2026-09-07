import json
import threading
import urllib.request
from pathlib import Path

import ezdxf
from pytest import MonkeyPatch

from mechanical_drawing_assistant.adapters.dxf import LAYOUT_CLEARANCE_MM, DxfAdapter
from mechanical_drawing_assistant.adapters.solidworks import SolidWorksAdapter
from mechanical_drawing_assistant.cli import main
from mechanical_drawing_assistant.diagnostics import diagnose_environment
from mechanical_drawing_assistant.runtime import default_knowledge_path, default_samples_path
from mechanical_drawing_assistant.webui import create_webui_server

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_diagnose_environment_reports_dependencies() -> None:
    data = diagnose_environment(PROJECT_ROOT)

    assert data["runtime"]["frozen"] is False
    assert data["resources"]["knowledge"]["present"] is True
    assert data["resources"]["samples"]["present"] is True
    assert data["python_packages"]["mcp"] is True
    assert data["python_packages"]["pywin32"] is True
    assert data["python_packages"]["ezdxf"] is True
    assert data["python_packages"]["pyinstaller"] is True


def test_runtime_default_resource_paths_point_to_repository_assets() -> None:
    assert default_knowledge_path() == PROJECT_ROOT / "knowledge"
    assert default_samples_path() == PROJECT_ROOT / "samples"


def test_exe_packaging_assets_are_declared() -> None:
    spec_path = PROJECT_ROOT / "packaging" / "mda.spec"
    build_script_path = PROJECT_ROOT / "scripts" / "build_mda_exe.ps1"

    spec = spec_path.read_text(encoding="utf-8")
    build_script = build_script_path.read_text(encoding="utf-8")

    assert "knowledge" in spec
    assert "samples" in spec
    assert "win32com.client" in spec
    assert "pythoncom" in spec
    assert "pywintypes" in spec
    assert ".venv-build" in build_script
    assert "pyinstaller" in build_script


def test_release_packaging_scripts_are_declared() -> None:
    release_script = (PROJECT_ROOT / "scripts" / "build_release_zip.ps1").read_text(
        encoding="utf-8"
    )
    smoke_script = (PROJECT_ROOT / "scripts" / "smoke_mda_exe.ps1").read_text(encoding="utf-8")

    assert "start_mda_webui.cmd" in release_script
    assert "run_diagnose.cmd" in release_script
    assert "Compress-Archive" in release_script
    assert "Expand-Archive" in release_script
    assert "diagnose.json" in smoke_script
    assert "pulley_job.sample.json" in smoke_script


def test_webui_serves_diagnose_and_runs_sample_job(tmp_path: Path) -> None:
    server = create_webui_server("127.0.0.1", 0, log_dir=tmp_path / "logs")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"
    try:
        with urllib.request.urlopen(f"{base_url}/api/diagnose", timeout=10) as response:
            diagnose = json.loads(response.read().decode("utf-8"))
        assert diagnose["resources"]["knowledge"]["present"] is True
        assert diagnose["resources"]["samples"]["present"] is True

        payload = {
            "job_path": str(PROJECT_ROOT / "samples" / "jobs" / "pulley_job.sample.json"),
            "output_dir": str(tmp_path / "webui-output"),
            "knowledge_path": str(PROJECT_ROOT / "knowledge"),
            "live": False,
        }
        request = urllib.request.Request(
            f"{base_url}/api/run",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        assert result["ok"] is True
        assert (tmp_path / "webui-output" / "drawing_plan.json").exists()
        assert (tmp_path / "webui-output" / "export_manifest.json").exists()
        assert (tmp_path / "webui-output" / "review_report.md").exists()
        assert (tmp_path / "webui-output" / "webui_run_log.json").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dxf_adapter_rejects_dwg_without_conversion() -> None:
    data = DxfAdapter().inspect_file(Path("example.dwg"))

    assert data["status"] == "unsupported"
    assert "DXF" in data["reason"]


def test_solidworks_launch_is_opt_in(monkeypatch: MonkeyPatch) -> None:
    adapter = SolidWorksAdapter()

    monkeypatch.delenv("MDA_LAUNCH_SOLIDWORKS", raising=False)
    assert adapter._env_flag("MDA_LAUNCH_SOLIDWORKS") is False

    monkeypatch.setenv("MDA_LAUNCH_SOLIDWORKS", "1")
    assert adapter._env_flag("MDA_LAUNCH_SOLIDWORKS") is True


def test_solidworks_sheet_safe_area_uses_six_mm_margin() -> None:
    adapter = SolidWorksAdapter()

    assert adapter._safe_area_zone(0.420, 0.297) == [0.006, 0.006, 0.414, 0.291]
    assert adapter._safe_area_zone(0.008, 0.004) == [0.004, 0.002, 0.004, 0.002]


def test_solidworks_sheet_info_accepts_method_style_com_access() -> None:
    class FakeSheet:
        def GetName(self) -> str:
            return "Sheet1"

        def GetProperties(self) -> list[float]:
            return [0.0, 0.0, 0.0, 0.0, 0.0, 0.420, 0.297]

    class FakeDrawing:
        def GetCurrentSheet(self) -> FakeSheet:
            return FakeSheet()

    info = SolidWorksAdapter()._get_sheet_info(FakeDrawing(), "gb_a3.drwdot")

    assert info["name"] == "Sheet1"
    assert info["sheet_size_m"] == [0.42, 0.297]
    assert info["safe_area_m"] == [0.006, 0.006, 0.414, 0.291]
    assert info["title_block_zone_m"] == [0.24, 0.0, 0.42, 0.06]


def test_solidworks_sheet_info_accepts_property_style_com_access() -> None:
    class FakeSheet:
        GetName = "Sheet2"
        GetProperties = [0.0, 0.0, 0.0, 0.0, 0.0, 0.297, 0.210]

    class FakeDrawing:
        GetCurrentSheet = FakeSheet()

    info = SolidWorksAdapter()._get_sheet_info(FakeDrawing(), "gb_a4.drwdot")

    assert info["name"] == "Sheet2"
    assert info["sheet_size_m"] == [0.297, 0.21]
    assert info["safe_area_m"] == [0.006, 0.006, 0.291, 0.204]
    assert info["title_block_zone_m"] == [0.117, 0.0, 0.297, 0.06]


def test_solidworks_view_outline_accepts_method_style_com_access() -> None:
    class FakeView:
        def GetOutline(self) -> list[float]:
            return [0.08, 0.13, 0.18, 0.21]

    assert SolidWorksAdapter()._get_view_outline(FakeView()) == [0.08, 0.13, 0.18, 0.21]


def test_solidworks_view_outline_accepts_property_style_com_access() -> None:
    class FakeView:
        GetOutline = [0.08, 0.13, 0.18, 0.21]

    assert SolidWorksAdapter()._get_view_outline(FakeView()) == [0.08, 0.13, 0.18, 0.21]


def test_solidworks_model_probe_collects_box_features_and_dimensions() -> None:
    class FakeDimension:
        FullName = "D1@Sketch1"
        SystemValue = 0.025

    class FakeDisplayDimension:
        def GetDimension2(self, index: int) -> FakeDimension:
            assert index == 0
            return FakeDimension()

        def GetType2(self) -> int:
            return 5

    class FakeFeature:
        Name = "Boss-Extrude1"

        def GetTypeName2(self) -> str:
            return "Boss"

        def GetFirstDisplayDimension(self) -> FakeDisplayDimension:
            return FakeDisplayDimension()

        def GetNextDisplayDimension(
            self,
            display_dimension: FakeDisplayDimension,
        ) -> None:
            assert isinstance(display_dimension, FakeDisplayDimension)
            return None

        def GetNextFeature(self) -> None:
            return None

    class FakeDocument:
        def GetPartBox(self, precise: bool) -> list[float]:
            assert precise is True
            return [-0.01, -0.02, 0.0, 0.015, 0.02, 0.03]

        def FirstFeature(self) -> FakeFeature:
            return FakeFeature()

    adapter = SolidWorksAdapter()
    warnings: list[str] = []

    box = adapter._model_bounding_box(FakeDocument(), warnings)
    features, dimensions = adapter._model_features_and_dimensions(FakeDocument(), warnings)

    assert box is not None
    assert box["size_mm"] == [25.0, 40.0, 30.0]
    assert features[0]["name"] == "Boss-Extrude1"
    assert features[0]["dimension_count"] == 1
    assert dimensions[0]["name"] == "D1@Sketch1"
    assert dimensions[0]["value_mm"] == 25.0
    assert adapter._feature_type_counts(features)["Boss"] == 1
    assert adapter._model_source_quality(features, dimensions) == "parametric_dimensions_available"
    assert (
        adapter._model_source_quality([{"type": "MBimport"}], [])
        == "imported_body_without_parametric_dimensions"
    )


def test_dxf_adapter_adds_first_pass_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    annotated = tmp_path / "source-annotated.dxf"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_line((10, 10), (50, 10))
    modelspace.add_line((50, 10), (50, 35))
    modelspace.add_line((50, 35), (10, 35))
    modelspace.add_line((10, 35), (10, 10))
    modelspace.add_circle((90, 22), 12)
    document.saveas(source)

    result = DxfAdapter().annotate_file(
        source,
        output_path=annotated,
        view_outlines_m=[
            {"view": "front", "outline_m": [0.005, 0.005, 0.055, 0.04]},
            {"view": "left", "outline_m": [0.075, 0.005, 0.105, 0.04]},
        ],
    )
    inspect_result = DxfAdapter().inspect_file(annotated)

    assert result["status"] == "annotated"
    assert result["annotation_policy"] == "conservative_standard_draft"
    assert result["dimensions_added"] == 2
    assert result["annotation_summary"]["annotation_count"] == 2
    assert result["annotation_review"]["status"] == "passed"
    assert annotated.exists()
    assert inspect_result["dimension_count"] == 2


def test_dxf_adapter_detects_sleeve_features(tmp_path: Path) -> None:
    source = tmp_path / "sleeve.dxf"
    annotated = tmp_path / "sleeve-annotated.dxf"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_line((10, 10), (60, 10))
    modelspace.add_line((60, 10), (60, 32))
    modelspace.add_line((60, 32), (10, 32))
    modelspace.add_line((10, 32), (10, 10))
    modelspace.add_line((28, 10), (28, 32))
    modelspace.add_circle((100, 22), 16)
    modelspace.add_circle((100, 22), 7)
    document.saveas(source)

    result = DxfAdapter().annotate_file(
        source,
        output_path=annotated,
        view_outlines_m=[
            {"view": "front", "outline_m": [0.005, 0.005, 0.065, 0.04]},
            {"view": "left", "outline_m": [0.080, 0.000, 0.120, 0.045]},
        ],
    )
    feature_types = {
        feature["feature_type"]
        for feature in result["feature_candidates"]
        if isinstance(feature, dict)
    }

    assert result["status"] == "annotated"
    assert result["dimensions_added"] == 3
    assert result["annotation_summary"]["features_by_type"]["outer_diameter"] == 1
    assert result["annotation_summary"]["features_by_type"]["bore_diameter"] == 1
    assert result["annotation_review"]["status"] == "passed"
    assert any(
        finding["code"] == "DXF_FEATURES_NOT_DIMENSIONED"
        for finding in result["annotation_review"]["findings"]
        if isinstance(finding, dict)
    )
    assert {"outer_diameter", "bore_diameter", "step_length"}.issubset(feature_types)


def test_dxf_adapter_places_callouts_away_from_occupied_boxes() -> None:
    adapter = DxfAdapter()
    layout = adapter._new_annotation_layout("top", [0.0, 0.0, 20.0, 10.0], [])

    placement = adapter._layout_place_text(
        layout,
        "test_callout",
        "4-M3",
        [(5.0, 5.0), (24.0, 12.0)],
    )

    assert placement["candidate_index"] == 1
    assert placement["collision_count"] == 0
    assert layout["placements"][0]["id"] == "test_callout"


def test_dxf_adapter_places_callouts_away_from_title_block() -> None:
    adapter = DxfAdapter()
    layout = adapter._new_annotation_layout("top", [50.0, 50.0, 100.0, 100.0], [])

    placement = adapter._layout_place_text(
        layout,
        "test_callout",
        "4-M3",
        [(250.0, 50.0), (200.0, 80.0)],
    )

    assert placement["candidate_index"] == 1
    assert placement["collision_count"] == 0


def test_dxf_adapter_adjusts_linear_dimension_text_inside_sheet_safe_area() -> None:
    adapter = DxfAdapter()
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    layout = adapter._new_annotation_layout("top", [58.0, 28.0, 202.0, 112.0], [])

    annotation = adapter._add_linear_dimension(
        modelspace,
        "top",
        "near_border_dimension",
        "thread_hole_pitch_x",
        (99.0, 4.0),
        (99.0, 39.0),
        (161.0, 39.0),
        0,
        31.0,
        "test",
        "medium",
        layout=layout,
    )

    assert annotation["layout"]["strategy"] == "dimension_base_safe_area_adjusted"
    assert annotation["layout"]["text_box"][1] >= 6.0
    assert annotation["layout"]["base_adjustment"]["axis"] == "y"


def test_dxf_adapter_adjusts_vertical_dimension_away_from_title_block() -> None:
    adapter = DxfAdapter()
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    layout = {
        "view": "top",
        "occupied_boxes": [],
        "placements": [],
        "sheet_bounds": [0.0, 0.0, 420.0, 297.0],
        "sheet_source": "test_sheet",
        "safe_area": [6.0, 6.0, 414.0, 291.0],
        "restricted_boxes": [
            {
                "kind": "title_block",
                "source": "test_title_block",
                "box": [240.0, 0.0, 420.0, 60.0],
            }
        ],
    }

    annotation = adapter._add_linear_dimension(
        modelspace,
        "top",
        "near_title_block_vertical_dimension",
        "slot_edge_y",
        (252.0, 30.0),
        (252.0, 20.0),
        (252.0, 50.0),
        90,
        30.0,
        "test",
        "medium",
        layout=layout,
    )

    assert annotation["layout"]["strategy"] == "dimension_base_safe_area_adjusted"
    assert annotation["layout"]["base_adjustment"]["axis"] == "x"
    assert annotation["layout"]["base_adjustment"]["shift_mm"] < 0
    assert annotation["layout"]["text_box"][2] <= 240.0 - LAYOUT_CLEARANCE_MM
    assert "constraint_sources" not in annotation["layout"]


def test_dxf_adapter_primary_fallback_dimension_uses_layout_avoidance() -> None:
    adapter = DxfAdapter()
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    layout = adapter._new_annotation_layout("front", [10.0, 13.0, 30.0, 20.0], [])

    annotations = adapter._add_primary_linear_dimensions(
        modelspace,
        "front",
        [10.0, 13.0, 30.0, 20.0],
        {"bounds": [10.0, 13.0, 30.0, 20.0]},
        layout,
    )

    assert annotations[0]["layout"]["text_box"][1] >= 6.0
    assert annotations[0]["layout"]["base_adjustment"]["axis"] == "y"


def test_dxf_adapter_reviews_overlapping_annotation_text_boxes() -> None:
    findings = DxfAdapter()._annotation_layout_findings(
        [
            {
                "id": "dim_a",
                "view": "top",
                "kind": "linear",
                "label": "overall_length",
                "layout": {"text_box": [10.0, 10.0, 18.0, 14.0]},
            },
            {
                "id": "callout_b",
                "view": "top",
                "kind": "callout",
                "label": "thread_hole",
                "layout": {"text_box": [16.0, 11.0, 26.0, 15.0]},
            },
        ],
        [{"view": "top", "bounds": [0.0, 0.0, 8.0, 8.0]}],
    )

    overlap = next(
        finding for finding in findings if finding["code"] == "DXF_ANNOTATION_TEXT_OVERLAP"
    )
    assert overlap["details"]["overlap_count"] == 1
    assert overlap["details"]["overlaps"][0]["first_kind"] == "linear"
    assert overlap["details"]["overlaps"][0]["second_kind"] == "callout"
    assert overlap["details"]["overlaps"][0]["overlap_area_mm2"] == 6.0


def test_dxf_adapter_does_not_report_text_boxes_touching_or_in_other_view() -> None:
    findings = DxfAdapter()._annotation_layout_findings(
        [
            {
                "id": "dim_a",
                "view": "top",
                "kind": "linear",
                "label": "overall_length",
                "layout": {"text_box": [10.0, 10.0, 18.0, 14.0]},
            },
            {
                "id": "dim_b",
                "view": "top",
                "kind": "linear",
                "label": "slot_pitch_x",
                "layout": {"text_box": [18.0, 10.0, 24.0, 14.0]},
            },
            {
                "id": "dim_c",
                "view": "front",
                "kind": "linear",
                "label": "thickness",
                "layout": {"text_box": [10.0, 10.0, 18.0, 14.0]},
            },
        ],
        [
            {"view": "top", "bounds": [0.0, 0.0, 8.0, 8.0]},
            {"view": "front", "bounds": [0.0, 0.0, 8.0, 8.0]},
        ],
    )

    assert not any(finding["code"] == "DXF_ANNOTATION_TEXT_OVERLAP" for finding in findings)


def test_dxf_adapter_reviews_annotation_text_inside_geometry() -> None:
    findings = DxfAdapter()._annotation_layout_findings(
        [
            {
                "id": "inside_linear",
                "view": "top",
                "kind": "linear",
                "label": "slot_edge_x",
                "layout": {"text_box": [2.0, 2.0, 6.0, 5.0]},
            },
            {
                "id": "inside_diameter",
                "view": "top",
                "kind": "diameter",
                "label": "center_cutout_diameter",
                "layout": {"text_box": [3.0, 3.0, 7.0, 6.0]},
            },
        ],
        [{"view": "top", "bounds": [0.0, 0.0, 10.0, 10.0]}],
    )
    inside_findings = [
        finding for finding in findings if finding["code"] == "DXF_ANNOTATION_TEXT_INSIDE_GEOMETRY"
    ]

    assert len(inside_findings) == 1
    assert inside_findings[0]["details"]["annotation_ids"] == ["inside_linear"]
    assert inside_findings[0]["details"]["items"][0]["inside_center"] is True


def test_dxf_adapter_reviews_callout_layout_collision() -> None:
    findings = DxfAdapter()._annotation_layout_findings(
        [
            {
                "id": "thread_callout",
                "view": "top",
                "kind": "callout",
                "label": "thread_hole",
                "layout": {
                    "collision_count": 2,
                    "collision_sources": ["view_geometry:view_geometry", "dimension_text:dim_a"],
                    "text_box": [12.0, 12.0, 20.0, 16.0],
                },
            }
        ],
        [{"view": "top", "bounds": [0.0, 0.0, 8.0, 8.0]}],
    )
    collision = next(
        finding for finding in findings if finding["code"] == "DXF_CALLOUT_LAYOUT_COLLISION"
    )

    assert collision["details"]["annotation_ids"] == ["thread_callout"]
    assert collision["details"]["items"][0]["collision_sources"] == [
        "view_geometry:view_geometry",
        "dimension_text:dim_a",
    ]


def test_dxf_adapter_reviews_annotation_text_against_sheet_safe_area() -> None:
    adapter = DxfAdapter()
    layout = adapter._new_annotation_layout("top", [50.0, 50.0, 100.0, 100.0], [])
    findings = adapter._annotation_layout_findings(
        [
            {
                "id": "near_bottom",
                "view": "top",
                "kind": "linear",
                "label": "thread_hole_pitch_x",
                "layout": {"text_box": [20.0, 1.0, 28.0, 5.0]},
            },
            {
                "id": "near_title_block",
                "view": "top",
                "kind": "callout",
                "label": "thread_hole",
                "layout": {"text_box": [220.0, 20.0, 239.0, 28.0]},
            },
        ],
        [{"view": "top", "bounds": [50.0, 50.0, 100.0, 100.0], "annotation_layout": layout}],
    )
    codes = {finding["code"] for finding in findings}

    assert "DXF_ANNOTATION_TEXT_OUTSIDE_SAFE_AREA" in codes
    assert "DXF_ANNOTATION_TEXT_IN_RESTRICTED_ZONE" in codes


def test_dxf_adapter_uses_parametric_model_manifest_for_plate_dimensions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "plate.dxf"
    annotated = tmp_path / "plate-annotated.dxf"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_line((58, 164.5), (202, 164.5))
    modelspace.add_line((202, 164.5), (202, 175.5))
    modelspace.add_line((202, 175.5), (58, 175.5))
    modelspace.add_line((58, 175.5), (58, 164.5))
    modelspace.add_line((58, 28), (202, 28))
    modelspace.add_line((202, 28), (202, 112))
    modelspace.add_line((202, 112), (58, 112))
    modelspace.add_line((58, 112), (58, 28))
    modelspace.add_circle((130, 70), 24)
    modelspace.add_circle((99, 39), 2.5)
    modelspace.add_circle((161, 39), 2.5)
    modelspace.add_circle((99, 101), 2.5)
    modelspace.add_circle((161, 101), 2.5)
    for center_x in [70, 190]:
        for lower_y in [41, 89]:
            upper_y = lower_y + 10
            modelspace.add_arc((center_x, lower_y), 6, 180, 0)
            modelspace.add_arc((center_x, upper_y), 6, 0, 180)
    document.saveas(source)

    result = DxfAdapter().annotate_file(
        source,
        output_path=annotated,
        view_outlines_m=[
            {"view": "front", "outline_m": [0.05206, 0.15856, 0.20794, 0.18144]},
            {"view": "top", "outline_m": [0.05206, 0.02206, 0.20794, 0.11794]},
            {"view": "left", "outline_m": [0.22206, 0.15856, 0.31794, 0.18144]},
        ],
        model_manifest={
            "status": "inspected",
            "model_source_quality": "parametric_dimensions_available",
            "dimension_count": 25,
            "bounding_box": {"size_mm": [72.0, 5.5, 42.0]},
            "dimensions": [
                {
                    "name": "D2@孔螺蚊线1@电机安装板.Part",
                    "feature": "M3 螺纹孔1",
                    "value_mm": 3.0,
                },
                {
                    "name": "通孔螺纹孔钻头直径@草图5@电机安装板.Part",
                    "feature": "M3 螺纹孔1",
                    "value_mm": 2.5,
                },
            ],
        },
        sheet_info={
            "sheet_size_m": [0.42, 0.297],
            "title_block_zone_m": [0.24, 0.0, 0.42, 0.06],
        },
    )
    labels = {
        annotation["label"] for annotation in result["annotations"] if isinstance(annotation, dict)
    }
    annotation_values = {
        annotation["label"]: annotation["value_mm"]
        for annotation in result["annotations"]
        if isinstance(annotation, dict) and "value_mm" in annotation
    }
    callout_texts = {
        annotation["text"]
        for annotation in result["annotations"]
        if isinstance(annotation, dict) and annotation.get("kind") == "callout"
    }
    callout_layouts = [
        annotation["layout"]
        for annotation in result["annotations"]
        if isinstance(annotation, dict) and annotation.get("kind") == "callout"
    ]
    annotations_by_id = {
        annotation["id"]: annotation
        for annotation in result["annotations"]
        if isinstance(annotation, dict)
    }
    annotated_document = ezdxf.readfile(annotated)
    mtext_texts = {
        str(getattr(entity, "text", ""))
        for entity in annotated_document.modelspace().query("MTEXT")
    }
    dimension_texts = {
        entity.dxf.text for entity in annotated_document.modelspace().query("DIMENSION")
    }

    assert result["annotation_policy"] == "model_driven_standard_draft"
    assert result["layout_context"]["sheet"]["source"] == "solidworks_sheet_info"
    assert result["layout_context"]["sheet"]["restricted_boxes"][0]["source"] == (
        "solidworks_title_block"
    )
    assert result["dimensions_added"] == 14
    assert result["dimension_count_after"] == 12
    assert {
        "overall_length",
        "overall_width",
        "thickness",
        "center_cutout_diameter",
        "thread_hole",
        "thread_hole_edge_x",
        "thread_hole_edge_y",
        "thread_hole_pitch_x",
        "thread_hole_pitch_y",
        "slot_callout",
        "slot_edge_x",
        "slot_edge_y",
        "slot_pitch_x",
        "slot_pitch_y",
    }.issubset(labels)
    for label in [
        "thread_hole_edge_x",
        "thread_hole_edge_y",
        "slot_edge_x",
        "slot_edge_y",
    ]:
        assert result["annotation_summary"]["annotations_by_label"][label] == 1
    assert annotation_values["thread_hole_edge_x"] == 20.5
    assert annotation_values["thread_hole_edge_y"] == 5.5
    assert annotation_values["slot_edge_x"] == 6.0
    assert annotation_values["slot_edge_y"] == 9.0
    assert {"4-M3", "4-\u957f\u5706\u5b54 6x11"}.issubset(callout_texts)
    assert {"4-M3", "4-\u957f\u5706\u5b54 6x11"}.issubset(mtext_texts)
    assert {"72", "42", "%%c24", "31", "60", "24", "20.5", "6", "9", "5.5"}.issubset(
        dimension_texts
    )
    assert len(callout_layouts) == 2
    assert all(layout["strategy"] == "candidate_box_avoidance" for layout in callout_layouts)
    assert all(layout["collision_count"] == 0 for layout in callout_layouts)
    pitch_x_layout = annotations_by_id["top_thread_hole_pitch_x"]["layout"]
    assert pitch_x_layout["strategy"] == "dimension_base_safe_area_adjusted"
    assert pitch_x_layout["text_box"][1] >= 6.0
    review_codes = {
        finding["code"]
        for finding in result["annotation_review"]["findings"]
        if isinstance(finding, dict)
    }
    assert "DXF_ANNOTATION_TEXT_OUTSIDE_SAFE_AREA" not in review_codes
    assert "DXF_ANNOTATION_TEXT_IN_RESTRICTED_ZONE" not in review_codes


def test_dxf_adapter_reviews_missing_view_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "partial.dxf"
    annotated = tmp_path / "partial-annotated.dxf"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_line((10, 10), (50, 10))
    modelspace.add_line((50, 10), (50, 35))
    modelspace.add_line((50, 35), (10, 35))
    modelspace.add_line((10, 35), (10, 10))
    document.saveas(source)

    result = DxfAdapter().annotate_file(
        source,
        output_path=annotated,
        view_outlines_m=[
            {"view": "front", "outline_m": [0.005, 0.005, 0.055, 0.04]},
            {"view": "left", "outline_m": [0.080, 0.000, 0.120, 0.045]},
        ],
    )
    codes = {
        finding["code"]
        for finding in result["annotation_review"]["findings"]
        if isinstance(finding, dict)
    }

    assert result["annotation_review"]["status"] == "warning"
    assert "DXF_ANNOTATION_WARNING" in codes
    assert "DXF_VIEW_WITHOUT_DIMENSIONS" in codes


def test_cli_annotate_dxf_writes_manifest(tmp_path: Path) -> None:
    source = tmp_path / "cli-source.dxf"
    annotated = tmp_path / "cli-source-annotated.dxf"
    manifest = tmp_path / "annotation_manifest.json"
    views_json = tmp_path / "views.json"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_line((10, 10), (50, 10))
    modelspace.add_line((50, 10), (50, 35))
    modelspace.add_line((50, 35), (10, 35))
    modelspace.add_line((10, 35), (10, 10))
    document.saveas(source)
    views_json.write_text(
        """
[
  {"view": "front", "outline_m": [0.005, 0.005, 0.055, 0.04]}
]
""".strip(),
        encoding="utf-8",
    )

    main(
        [
            "annotate-dxf",
            str(source),
            "--output-dxf",
            str(annotated),
            "--out",
            str(manifest),
            "--views-json",
            str(views_json),
        ]
    )

    result = DxfAdapter().inspect_file(annotated)
    assert manifest.exists()
    assert result["dimension_count"] == 1


def test_cli_review_accepts_standalone_annotation_manifest(tmp_path: Path) -> None:
    annotation = tmp_path / "annotation_manifest.json"
    report = tmp_path / "review_report.md"
    annotation.write_text(
        json.dumps(
            {
                "status": "annotated",
                "dimensions_added": 1,
                "feature_candidates": [{"feature_type": "outer_diameter"}],
                "annotation_review": {
                    "status": "warning",
                    "findings": [
                        {
                            "severity": "WARN",
                            "code": "DXF_VIEW_WITHOUT_DIMENSIONS",
                            "message": "部分视图没有生成任何尺寸：top",
                            "recommendation": "确认该视图是否为辅助表达。",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    main(
        [
            "review",
            "--job",
            str(PROJECT_ROOT / "samples" / "jobs" / "vul_lizhu_job.sample.json"),
            "--knowledge",
            str(PROJECT_ROOT / "knowledge"),
            "--annotation",
            str(annotation),
            "--out",
            str(report),
        ]
    )

    text = report.read_text(encoding="utf-8")
    assert "DXF_VIEW_WITHOUT_DIMENSIONS" in text
    assert "DIMENSION_INTENT_COVERAGE" in text


def test_mcp_annotate_dxf_and_review_with_annotation(tmp_path: Path) -> None:
    from mechanical_drawing_assistant import mcp_server

    source = tmp_path / "mcp-source.dxf"
    annotated = tmp_path / "mcp-source-annotated.dxf"
    annotation_manifest = tmp_path / "annotation_manifest.json"
    review_report = tmp_path / "review_report.md"
    views_json = tmp_path / "views.json"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_line((10, 10), (50, 10))
    modelspace.add_line((50, 10), (50, 35))
    modelspace.add_line((50, 35), (10, 35))
    modelspace.add_line((10, 35), (10, 10))
    document.saveas(source)
    views_json.write_text(
        '[{"view": "front", "outline_m": [0.005, 0.005, 0.055, 0.04]}]',
        encoding="utf-8",
    )

    annotation_result = mcp_server.annotate_dxf_file(
        str(source),
        str(annotated),
        str(annotation_manifest),
        views_json_path=str(views_json),
    )
    review_result = mcp_server.review_drawing_job(
        str(PROJECT_ROOT / "samples" / "jobs" / "vul_lizhu_job.sample.json"),
        knowledge_path=str(PROJECT_ROOT / "knowledge"),
        annotation_path=str(annotation_manifest),
        output_path=str(review_report),
    )

    assert annotation_result["status"] == "annotated"
    assert annotation_manifest.exists()
    assert annotated.exists()
    assert "DIMENSION_INTENT_COVERAGE" in review_result["markdown"]
    assert review_report.exists()


def test_mcp_server_imports() -> None:
    from mechanical_drawing_assistant import mcp_server

    assert mcp_server.PROJECT_ROOT == PROJECT_ROOT
