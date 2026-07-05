from pathlib import Path

import ezdxf

from mechanical_drawing_assistant.adapters.dxf import DxfAdapter
from mechanical_drawing_assistant.diagnostics import diagnose_environment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_diagnose_environment_reports_dependencies() -> None:
    data = diagnose_environment(PROJECT_ROOT)

    assert data["python_packages"]["mcp"] is True
    assert data["python_packages"]["pywin32"] is True
    assert data["python_packages"]["ezdxf"] is True


def test_dxf_adapter_rejects_dwg_without_conversion() -> None:
    data = DxfAdapter().inspect_file(Path("example.dwg"))

    assert data["status"] == "unsupported"
    assert "DXF" in data["reason"]


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
    assert result["dimensions_added"] == 3
    assert annotated.exists()
    assert inspect_result["dimension_count"] == 3


def test_mcp_server_imports() -> None:
    from mechanical_drawing_assistant import mcp_server

    assert mcp_server.PROJECT_ROOT == PROJECT_ROOT
