from __future__ import annotations

import importlib.util
from pathlib import Path

from mechanical_drawing_assistant.adapters.dxf import DxfAdapter
from mechanical_drawing_assistant.models import DrawingPlan, JsonObject


class AutoCadAdapter:
    def is_available(self) -> bool:
        return importlib.util.find_spec("win32com") is not None

    def diagnose(self) -> JsonObject:
        return {
            "available": self.is_available(),
            "backend": "pywin32 COM",
            "prog_id": "AutoCAD.Application",
            "live_normalization": "DXF first-pass annotation via ezdxf; AutoCAD COM not used yet",
        }

    def normalize_drawing(
        self,
        plan: DrawingPlan,
        dry_run: bool = True,
        solidworks_result: JsonObject | None = None,
        model_result: JsonObject | None = None,
    ) -> JsonObject:
        if dry_run:
            return {
                "adapter": "autocad",
                "action": "normalize_drawing",
                "status": "planned",
                "checks": [
                    "dimension_style",
                    "layer_names",
                    "text_height",
                    "overlap_review",
                ],
                "job_name": plan.job_name,
            }
        dxf_path = self._first_planned_dxf(plan)
        if dxf_path is None:
            return {
                "adapter": "autocad",
                "action": "normalize_drawing",
                "status": "skipped",
                "reason": "No DXF output is planned; DWG cannot be annotated by ezdxf directly.",
                "job_name": plan.job_name,
            }

        output_path = dxf_path.with_name(f"{dxf_path.stem}-annotated.dxf")
        annotation_result = DxfAdapter().annotate_file(
            dxf_path,
            output_path=output_path,
            view_outlines_m=self._view_outlines_from_solidworks(solidworks_result),
            model_manifest=model_result,
            sheet_info=self._sheet_info_from_solidworks(solidworks_result),
        )
        return {
            "adapter": "autocad",
            "action": "normalize_drawing",
            "status": "completed" if annotation_result.get("status") == "annotated" else "skipped",
            "job_name": plan.job_name,
            "dxf_annotation": annotation_result,
            "note": (
                "First-pass CAD annotation is written to annotated DXF; "
                "DWG write-back is not implemented yet."
            ),
        }

    def _first_planned_dxf(self, plan: DrawingPlan) -> Path | None:
        for output in plan.planned_outputs:
            path = Path(output)
            if path.suffix.lower() != ".dxf":
                continue
            if not path.is_absolute():
                path = Path.cwd() / path
            return path
        return None

    def _view_outlines_from_solidworks(
        self,
        solidworks_result: JsonObject | None,
    ) -> list[JsonObject]:
        if not solidworks_result:
            return []
        inserted_views = solidworks_result.get("inserted_views")
        if not isinstance(inserted_views, list):
            return []
        return [view for view in inserted_views if isinstance(view, dict)]

    def _sheet_info_from_solidworks(
        self,
        solidworks_result: JsonObject | None,
    ) -> JsonObject | None:
        if not isinstance(solidworks_result, dict):
            return None
        sheet_info = solidworks_result.get("sheet_info")
        return sheet_info if isinstance(sheet_info, dict) else None
