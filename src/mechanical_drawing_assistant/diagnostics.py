from __future__ import annotations

import importlib.util
from pathlib import Path

from mechanical_drawing_assistant.adapters.autocad import AutoCadAdapter
from mechanical_drawing_assistant.adapters.dxf import DxfAdapter
from mechanical_drawing_assistant.adapters.solidworks import SolidWorksAdapter
from mechanical_drawing_assistant.models import JsonObject


def diagnose_environment(project_root: Path) -> JsonObject:
    external_root = project_root / "external"
    return {
        "python_packages": {
            "mcp": module_available("mcp"),
            "pywin32": module_available("win32com"),
            "ezdxf": module_available("ezdxf"),
        },
        "adapters": {
            "solidworks": SolidWorksAdapter().diagnose(),
            "autocad": AutoCadAdapter().diagnose(),
            "dxf": {"available": DxfAdapter().is_available()},
        },
        "external_repositories": external_repository_status(external_root),
    }


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def external_repository_status(root: Path) -> dict[str, JsonObject]:
    repos = [
        "solidworks-mcp",
        "codestack",
        "u-c4n-autocad-mcp",
        "puran-water-autocad-mcp",
        "AutoCAD-Automatic-Dimensioning-LISP",
        "ocrx-engineering-drawings",
        "werk24-python",
    ]
    return {
        repo: {
            "path": str(root / repo),
            "present": (root / repo / ".git").exists(),
        }
        for repo in repos
    }
