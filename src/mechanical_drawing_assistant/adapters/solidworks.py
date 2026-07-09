from __future__ import annotations

import importlib.util
import os
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Any

from mechanical_drawing_assistant.models import DrawingPlan, JsonObject
from mechanical_drawing_assistant.view_review import review_drawing_views

SW_DOC_PART = 1
SW_DOC_ASSEMBLY = 2
SW_DOC_DRAWING = 3
SW_OPEN_SILENT = 1
SW_PAPER_A3 = 9
SW_HIDDEN_LINES_REMOVED = 6
SW_DEFAULT_TEMPLATE_DRAWING = 10
SW_TEMPLATE_FOLDER = 6

PREFERRED_DRAWING_TEMPLATE = "gb_a3.drwdot"
VIEW_OVERLAP_MARGIN_M = 0.02
SHEET_SAFE_MARGIN_M = 0.006
EXTRA_VIEW_HINT_OFFSET_M = 0.04
EXTRA_VIEW_SECTION_INSET_RATIO = 0.08
EXTRA_VIEW_DETAIL_RADIUS_RATIO = 0.32
LAUNCH_SOLIDWORKS_ENV = "MDA_LAUNCH_SOLIDWORKS"
SOLIDWORKS_VISIBLE_ENV = "MDA_SOLIDWORKS_VISIBLE"
EXPERIMENTAL_EXTRA_VIEWS_ENV = "MDA_SOLIDWORKS_EXPERIMENTAL_EXTRA_VIEWS"
MAX_MODEL_FEATURES = 200
MAX_FEATURE_DIMENSIONS = 20
MAX_MODEL_DIMENSIONS = 300
IMPORTED_MODEL_FEATURE_TYPES = {"MBimport", "Imported", "ImportedBody", "Import"}

VIEW_CANDIDATES = {
    "front": ["*Front", "\u002a\u524d\u89c6", "\u002a\u524d\u8996"],
    "top": ["*Top", "\u002a\u4e0a\u89c6", "\u002a\u4e0a\u8996"],
    "right": ["*Right", "\u002a\u53f3\u89c6", "\u002a\u53f3\u8996"],
    "left": ["*Left", "\u002a\u5de6\u89c6", "\u002a\u5de6\u8996"],
    "bottom": ["*Bottom", "\u002a\u4e0b\u89c6", "\u002a\u4e0b\u8996"],
    "back": ["*Back", "\u002a\u540e\u89c6", "\u002a\u5f8c\u8996"],
    "isometric": ["*Isometric", "\u002a\u7b49\u8f74\u6d4b", "\u002a\u7b49\u89d2\u8996"],
}

VIEW_POSITIONS_M = {
    "front": (0.13, 0.17),
    "top": (0.13, 0.07),
    "right": (0.04, 0.17),
    "left": (0.27, 0.17),
    "bottom": (0.13, 0.25),
    "back": (0.27, 0.25),
    "isometric": (0.35, 0.08),
}


class SolidWorksAdapter:
    def __init__(self) -> None:
        self._last_drawing_title: str | None = None

    def is_available(self) -> bool:
        return importlib.util.find_spec("win32com") is not None

    def diagnose(self) -> JsonObject:
        data: JsonObject = {
            "available": self.is_available(),
            "backend": "pywin32 COM",
            "prog_id": "SldWorks.Application",
            "live_generation": "basic three-view drawing and SaveAs export",
            "launch_env_var": LAUNCH_SOLIDWORKS_ENV,
            "launch_allowed": self._env_flag(LAUNCH_SOLIDWORKS_ENV),
            "experimental_extra_views_env_var": EXPERIMENTAL_EXTRA_VIEWS_ENV,
            "experimental_extra_views_enabled": self._env_flag(EXPERIMENTAL_EXTRA_VIEWS_ENV),
        }
        if not self.is_available():
            return data

        try:
            app = self._get_active_app()
            data["active_instance"] = True
            data["revision"] = self._com_value(app, "RevisionNumber")
            active_doc = self._com_value(app, "ActiveDoc")
            if active_doc is not None:
                data["active_doc"] = {
                    "title": self._com_value(active_doc, "GetTitle"),
                    "path": self._com_value(active_doc, "GetPathName"),
                    "type": self._com_value(active_doc, "GetType"),
                }
        except Exception as exc:  # noqa: BLE001 - diagnostics should report COM errors.
            data["active_instance"] = False
            data["error"] = f"{type(exc).__name__}: {exc}"
        return data

    def inspect_model(
        self,
        source_model: str | None = None,
        dry_run: bool = False,
    ) -> JsonObject:
        if dry_run:
            return {
                "adapter": "solidworks",
                "action": "inspect_model",
                "status": "planned",
                "source_model": source_model,
                "note": "Model inspection requires live SolidWorks COM access.",
            }
        if not self.is_available():
            return {
                "adapter": "solidworks",
                "action": "inspect_model",
                "status": "unavailable",
                "reason": "pywin32 is not installed.",
            }

        self._co_initialize()
        try:
            app = self._get_active_app()
            document = self._resolve_model_document(app, source_model)
            warnings: list[str] = []
            bounding_box = self._model_bounding_box(document, warnings)
            features, dimensions = self._model_features_and_dimensions(document, warnings)
            model_source_quality = self._model_source_quality(features, dimensions)
            if bounding_box is None:
                warnings.append("SolidWorks model bounding box was not available.")
            if not dimensions:
                warnings.append(
                    "No model display dimensions were collected; dimensions may be hidden "
                    "or exposed through an unsupported SolidWorks COM path."
                )
            if model_source_quality == "imported_body_without_parametric_dimensions":
                warnings.append(
                    "The model appears to be an imported body without parametric dimensions; "
                    "automatic standard dimensions must rely on body geometry or manual rules."
                )

            return {
                "adapter": "solidworks",
                "action": "inspect_model",
                "status": "inspected",
                "source_model": self._document_path(document) or source_model,
                "title": self._text_value(self._com_optional(document, "GetTitle")),
                "document_type": self._com_optional(document, "GetType"),
                "is_dirty": bool(self._com_optional(document, "GetSaveFlag") or False),
                "unit_assumption": (
                    "SolidWorks length values are reported in meters; mm values are derived."
                ),
                "bounding_box": bounding_box,
                "model_source_quality": model_source_quality,
                "feature_type_counts": self._feature_type_counts(features),
                "feature_count": len(features),
                "dimension_count": len(dimensions),
                "features": features,
                "dimensions": dimensions,
                "warnings": warnings,
            }
        except Exception as exc:  # noqa: BLE001 - model probing should report COM errors.
            return {
                "adapter": "solidworks",
                "action": "inspect_model",
                "status": "error",
                "source_model": source_model,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            self._co_uninitialize()

    def create_three_view_drawing(self, plan: DrawingPlan, dry_run: bool = True) -> JsonObject:
        recommended_extra_views = self._list_of_text(plan.view_plan.get("recommended_extra_views"))
        extra_view_requests = self._extra_view_requests(plan)
        extra_view_attempts = self._planned_extra_view_attempts(extra_view_requests)
        if dry_run:
            return {
                "adapter": "solidworks",
                "action": "create_three_view_drawing",
                "status": "planned",
                "views": plan.views,
                "extra_view_requests": extra_view_requests,
                "extra_view_attempts": extra_view_attempts,
                "recommended_extra_views": recommended_extra_views,
                "implemented_extra_views": [],
                "pending_extra_views": recommended_extra_views,
                "pending_extra_view_requests": extra_view_requests,
            }

        self._co_initialize()
        try:
            app = self._get_active_app()
            source_model = self._resolve_source_model(app, plan)
            template = self._resolve_drawing_template(app)
            if not template:
                raise RuntimeError("SolidWorks default drawing template is empty.")

            drawing = app.NewDocument(template, SW_PAPER_A3, 0, 0)
            if drawing is None:
                raise RuntimeError(f"NewDocument failed with template={template}")
            drawing_title = str(self._com_value(drawing, "GetTitle"))
            self._last_drawing_title = drawing_title
            sheet_info = self._get_sheet_info(drawing, template)

            inserted: list[JsonObject] = []
            failed: list[JsonObject] = []
            overlap_warnings: list[JsonObject] = []
            for view_name in plan.views:
                inserted_view = self._insert_standard_view(drawing, source_model, view_name)
                if inserted_view["status"] == "inserted":
                    overlap_warnings.extend(self._find_overlaps(inserted_view, inserted))
                    inserted.append(inserted_view)
                else:
                    failed.append(inserted_view)

            extra_view_attempts = self._process_extra_view_requests(drawing, inserted, plan)
            with suppress(Exception):
                drawing.ViewZoomtofit2()

            view_review = review_drawing_views(plan, inserted, failed, sheet_info=sheet_info)
            return {
                "adapter": "solidworks",
                "action": "create_three_view_drawing",
                "status": "created",
                "source_model": source_model,
                "template": template,
                "drawing_title": drawing_title,
                "sheet_info": sheet_info,
                "inserted_views": inserted,
                "failed_views": failed,
                "extra_view_requests": view_review.get("extra_view_requests", []),
                "extra_view_attempts": extra_view_attempts,
                "recommended_extra_views": view_review.get("recommended_extra_views", []),
                "implemented_extra_views": view_review.get("implemented_extra_views", []),
                "pending_extra_views": view_review.get("pending_extra_views", []),
                "pending_extra_view_requests": view_review.get(
                    "pending_extra_view_requests",
                    [],
                ),
                "overlap_warnings": overlap_warnings,
                "view_review": view_review,
            }
        finally:
            self._co_uninitialize()

    def export_outputs(self, plan: DrawingPlan, dry_run: bool = True) -> JsonObject:
        if dry_run:
            return {
                "adapter": "solidworks",
                "action": "export_outputs",
                "status": "planned",
                "outputs": plan.planned_outputs,
            }

        self._co_initialize()
        try:
            app = self._get_active_app()
            doc = self._com_value(app, "ActiveDoc")
            if doc is not None and self._com_value(doc, "GetType") != SW_DOC_DRAWING:
                doc = self._activate_last_drawing(app)
            if doc is None:
                raise RuntimeError("SolidWorks has no active document to export.")
            doc_type = self._com_value(doc, "GetType")
            if doc_type != SW_DOC_DRAWING:
                raise RuntimeError(f"Active SolidWorks document is not a drawing: type={doc_type}")

            outputs: list[JsonObject] = []
            for output in plan.planned_outputs:
                path = Path(output)
                if not path.is_absolute():
                    path = Path.cwd() / path
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with suppress(OSError):
                        path.unlink()
                    ok = bool(doc.SaveAs(str(path)))
                    saved = path.exists() and path.stat().st_size > 0
                    outputs.append(
                        {
                            "path": str(path),
                            "status": "saved" if saved else "failed",
                            "ok": ok,
                            "exists": saved,
                            "size_bytes": path.stat().st_size if path.exists() else 0,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    outputs.append(
                        {
                            "path": str(path),
                            "status": "error",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

            all_saved = all(output.get("status") == "saved" for output in outputs)
            close_result = self._close_last_drawing(app) if all_saved else None
            return {
                "adapter": "solidworks",
                "action": "export_outputs",
                "status": "completed",
                "outputs": outputs,
                "close_result": close_result,
            }
        finally:
            self._co_uninitialize()

    def _insert_standard_view(
        self,
        drawing: Any,
        source_model: str,
        view_name: str,
    ) -> JsonObject:
        key = view_name.lower()
        candidates = VIEW_CANDIDATES.get(key)
        if not candidates:
            return {
                "view": view_name,
                "status": "skipped",
                "message": "No SolidWorks standard view mapping is configured.",
            }

        x, y = VIEW_POSITIONS_M.get(key, (0.17, 0.16))
        last_error: str | None = None
        for candidate in candidates:
            try:
                view = drawing.CreateDrawViewFromModelView3(source_model, candidate, x, y, 0)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                continue

            if view is None:
                continue

            with suppress(Exception):
                view.SetDisplayMode3(False, SW_HIDDEN_LINES_REMOVED, False, False)
            return {
                "view": view_name,
                "status": "inserted",
                "solidworks_view_name": candidate,
                "position_m": [x, y],
                "outline_m": self._get_view_outline(view),
            }

        return {
            "view": view_name,
            "status": "failed",
            "candidates": candidates,
            "last_error": last_error,
        }

    def _planned_extra_view_attempts(
        self,
        extra_view_requests: list[JsonObject],
    ) -> list[JsonObject]:
        return [
            {
                "id": self._request_id(request),
                "view_type": self._text_value(request.get("view_type")),
                "base_view": self._text_value(request.get("base_view")),
                "status": "planned",
                "automation_status": "requires_live_solidworks",
                "env_var": EXPERIMENTAL_EXTRA_VIEWS_ENV,
                "geometry_hint": self._request_geometry_hint(request),
                "resolved_geometry_hint": self._unavailable_extra_view_geometry_hint(
                    request,
                    "Dry-run has no inserted base view outline to derive geometry from.",
                ),
            }
            for request in extra_view_requests
            if self._request_id(request)
        ]

    def _process_extra_view_requests(
        self,
        drawing: Any,
        inserted_views: list[JsonObject],
        plan: DrawingPlan,
    ) -> list[JsonObject]:
        extra_view_requests = self._extra_view_requests(plan)
        if not extra_view_requests:
            return []

        if not self._env_flag(EXPERIMENTAL_EXTRA_VIEWS_ENV):
            return [
                {
                    "id": self._request_id(request),
                    "view_type": self._text_value(request.get("view_type")),
                    "base_view": self._text_value(request.get("base_view")),
                    "status": "skipped",
                    "automation_status": "experimental_disabled",
                    "env_var": EXPERIMENTAL_EXTRA_VIEWS_ENV,
                    "geometry_hint": self._request_geometry_hint(request),
                    "resolved_geometry_hint": self._extra_view_geometry_hint(
                        inserted_views,
                        request,
                    ),
                    "reason": (
                        "Extra view COM execution is disabled by default to avoid "
                        "creating incorrect section/detail views."
                    ),
                }
                for request in extra_view_requests
                if self._request_id(request)
            ]

        return [
            self._probe_extra_view_request(drawing, inserted_views, request)
            for request in extra_view_requests
        ]

    def _probe_extra_view_request(
        self,
        drawing: Any,
        inserted_views: list[JsonObject],
        request: JsonObject,
    ) -> JsonObject:
        request_id = self._request_id(request)
        view_type = self._text_value(request.get("view_type"))
        base_view = self._text_value(request.get("base_view"))
        api_method = self._extra_view_api_method(view_type)
        result: JsonObject = {
            "id": request_id,
            "view_type": view_type,
            "base_view": base_view,
            "status": "not_created",
            "automation_status": "api_probe_only",
            "env_var": EXPERIMENTAL_EXTRA_VIEWS_ENV,
            "api_method": api_method,
            "geometry_hint": self._request_geometry_hint(request),
            "resolved_geometry_hint": self._extra_view_geometry_hint(inserted_views, request),
        }
        if not request_id:
            result["reason"] = "Extra view request is missing id."
            return result
        if not api_method:
            result["reason"] = f"Unsupported extra view type: {view_type or 'unknown'}."
            return result
        if not self._has_inserted_view(inserted_views, base_view):
            result["reason"] = f"Base view is not inserted: {base_view or 'missing'}."
            return result
        if not self._com_member_available(drawing, api_method):
            result["reason"] = f"SolidWorks drawing API method is not available: {api_method}."
            return result

        result["reason"] = (
            "API method is available, but automatic geometry creation is not implemented yet. "
            "The geometry hint is only a draft section line/detail circle, not a selected "
            "SolidWorks sketch entity."
        )
        return result

    def _request_geometry_hint(self, request: JsonObject) -> JsonObject:
        value = request.get("geometry_hint")
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items()}
        return {
            "schema_version": 1,
            "status": "missing",
            "source": "extra_view_request",
            "requires_manual_review": True,
            "reason": "Extra view request has no normalized geometry_hint.",
        }

    def _extra_view_api_method(self, view_type: str) -> str:
        normalized = view_type.strip().lower()
        if normalized == "section":
            return "CreateSectionViewAt5"
        if normalized == "detail":
            return "CreateDetailViewAt5"
        return ""

    def _has_inserted_view(self, inserted_views: list[JsonObject], view_name: str) -> bool:
        return self._find_inserted_view(inserted_views, view_name) is not None

    def _find_inserted_view(
        self,
        inserted_views: list[JsonObject],
        view_name: str,
    ) -> JsonObject | None:
        normalized = view_name.strip().lower()
        if not normalized:
            return None
        for view in inserted_views:
            if (
                view.get("status") == "inserted"
                and isinstance(view.get("view"), str)
                and view["view"].strip().lower() == normalized
            ):
                return view
        return None

    def _extra_view_geometry_hint(
        self,
        inserted_views: list[JsonObject],
        request: JsonObject,
    ) -> JsonObject:
        view_type = self._text_value(request.get("view_type"))
        base_view_name = self._text_value(request.get("base_view"))
        base_view = self._find_inserted_view(inserted_views, base_view_name)
        if base_view is None:
            return self._unavailable_extra_view_geometry_hint(
                request,
                f"Base view is not inserted: {base_view_name or 'missing'}.",
            )

        outline = self._outline_box(base_view.get("outline_m"))
        if outline is None:
            return self._unavailable_extra_view_geometry_hint(
                request,
                f"Base view has no usable outline_m: {base_view_name}.",
            )

        if view_type == "section":
            return self._section_line_geometry_hint(request, outline)
        if view_type == "detail":
            return self._detail_circle_geometry_hint(request, outline)
        return self._unavailable_extra_view_geometry_hint(
            request,
            f"Unsupported extra view type: {view_type or 'unknown'}.",
        )

    def _section_line_geometry_hint(
        self,
        request: JsonObject,
        outline: tuple[float, float, float, float],
    ) -> JsonObject:
        left, bottom, right, top = outline
        width = right - left
        height = top - bottom
        center_y = (bottom + top) / 2
        primitive = self._geometry_primitive(request)
        line = self._ratio_line_to_outline(primitive.get("points"), outline)
        if line is not None:
            start, end = line
            orientation = self._line_orientation(start, end)
        elif width >= height:
            inset = width * EXTRA_VIEW_SECTION_INSET_RATIO
            start = [left + inset, center_y]
            end = [right - inset, center_y]
            orientation = "horizontal"
        else:
            center_x = (left + right) / 2
            inset = height * EXTRA_VIEW_SECTION_INSET_RATIO
            start = [center_x, bottom + inset]
            end = [center_x, top - inset]
            orientation = "vertical"

        hint = {
            **self._extra_view_geometry_hint_base(request, outline),
            "status": "prepared",
            "type": "section_line",
            "orientation": orientation,
            "line_m": [
                [round(start[0], 6), round(start[1], 6)],
                [round(end[0], 6), round(end[1], 6)],
            ],
            "suggested_view_position_m": self._suggest_extra_view_position(outline, request),
            "confidence": "low",
            "note": (
                "Draft geometry derived from the base view outline; a real SolidWorks "
                "section view still needs an actual selected sketch line."
            ),
        }
        label = self._text_value(primitive.get("label"))
        if label:
            hint["label"] = label
        return hint

    def _detail_circle_geometry_hint(
        self,
        request: JsonObject,
        outline: tuple[float, float, float, float],
    ) -> JsonObject:
        left, bottom, right, top = outline
        width = right - left
        height = top - bottom
        diameter = min(width, height)
        primitive = self._geometry_primitive(request)
        center = self._ratio_point_to_outline(primitive.get("center"), outline) or [
            (left + right) / 2,
            (bottom + top) / 2,
        ]
        radius_ratio = self._ratio_value(primitive.get("radius"))
        if radius_ratio is None:
            radius_ratio = EXTRA_VIEW_DETAIL_RADIUS_RATIO
        radius = min(diameter * radius_ratio, diameter / 2)

        return {
            **self._extra_view_geometry_hint_base(request, outline),
            "status": "prepared",
            "type": "detail_circle",
            "center_m": [round(center[0], 6), round(center[1], 6)],
            "radius_m": round(radius, 6),
            "suggested_view_position_m": self._suggest_extra_view_position(outline, request),
            "confidence": "low",
            "note": (
                "Draft geometry derived from the base view outline; a real SolidWorks "
                "detail view still needs an actual selected circle around the target feature."
            ),
        }

    def _extra_view_geometry_hint_base(
        self,
        request: JsonObject,
        outline: tuple[float, float, float, float],
    ) -> JsonObject:
        return {
            "request_id": self._request_id(request),
            "view_type": self._text_value(request.get("view_type")),
            "base_view": self._text_value(request.get("base_view")),
            "target_feature": self._text_value(request.get("target_feature")),
            "placement_hint": self._text_value(request.get("placement_hint")),
            "schema_version": 1,
            "source": "inserted_view_outline",
            "coordinate_space": "drawing_sheet",
            "units": "m",
            "requires_manual_review": True,
            "base_outline_m": [round(value, 6) for value in outline],
        }

    def _unavailable_extra_view_geometry_hint(
        self,
        request: JsonObject,
        reason: str,
    ) -> JsonObject:
        return {
            "request_id": self._request_id(request),
            "view_type": self._text_value(request.get("view_type")),
            "base_view": self._text_value(request.get("base_view")),
            "target_feature": self._text_value(request.get("target_feature")),
            "placement_hint": self._text_value(request.get("placement_hint")),
            "schema_version": 1,
            "status": "unavailable",
            "source": "inserted_view_outline",
            "coordinate_space": "drawing_sheet",
            "units": "m",
            "requires_manual_review": True,
            "reason": reason,
        }

    def _geometry_primitive(self, request: JsonObject) -> JsonObject:
        hint = request.get("geometry_hint")
        if not isinstance(hint, dict):
            return {}
        primitive = hint.get("primitive")
        if not isinstance(primitive, dict):
            return {}
        return primitive

    def _ratio_line_to_outline(
        self,
        value: object,
        outline: tuple[float, float, float, float],
    ) -> tuple[list[float], list[float]] | None:
        if not isinstance(value, list) or len(value) != 2:
            return None
        first = self._ratio_point_to_outline(value[0], outline)
        second = self._ratio_point_to_outline(value[1], outline)
        if first is None or second is None:
            return None
        return first, second

    def _ratio_point_to_outline(
        self,
        value: object,
        outline: tuple[float, float, float, float],
    ) -> list[float] | None:
        if not isinstance(value, dict):
            return None
        x_ratio = self._ratio_value(value.get("x"))
        y_ratio = self._ratio_value(value.get("y"))
        if x_ratio is None or y_ratio is None:
            return None
        left, bottom, right, top = outline
        return [
            left + (right - left) * x_ratio,
            bottom + (top - bottom) * y_ratio,
        ]

    def _ratio_value(self, value: object) -> float | None:
        ratio = self._float_like_value(value)
        if ratio is None:
            return None
        if 0.0 <= ratio <= 1.0:
            return ratio
        return None

    def _float_like_value(self, value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _line_orientation(self, start: list[float], end: list[float]) -> str:
        if abs(end[0] - start[0]) >= abs(end[1] - start[1]):
            return "horizontal"
        return "vertical"

    def _outline_box(self, value: object) -> tuple[float, float, float, float] | None:
        if not isinstance(value, list) or len(value) != 4:
            return None
        values = [self._float_like_value(item) for item in value]
        if any(item is None for item in values):
            return None
        x1 = values[0]
        y1 = values[1]
        x2 = values[2]
        y2 = values[3]
        if x1 is None or y1 is None or x2 is None or y2 is None:
            return None
        left, right = sorted((x1, x2))
        bottom, top = sorted((y1, y2))
        if left == right or bottom == top:
            return None
        return left, bottom, right, top

    def _suggest_extra_view_position(
        self,
        outline: tuple[float, float, float, float],
        request: JsonObject,
    ) -> list[float]:
        left, bottom, right, top = outline
        center_x = (left + right) / 2
        center_y = (bottom + top) / 2
        placement_hint = self._text_value(request.get("placement_hint")).lower()
        if "above" in placement_hint:
            return [round(center_x, 6), round(top + EXTRA_VIEW_HINT_OFFSET_M, 6)]
        if "below" in placement_hint:
            return [round(center_x, 6), round(max(0.0, bottom - EXTRA_VIEW_HINT_OFFSET_M), 6)]
        if "left" in placement_hint and "replace_left" not in placement_hint:
            return [round(max(0.0, left - EXTRA_VIEW_HINT_OFFSET_M), 6), round(center_y, 6)]
        return [round(right + EXTRA_VIEW_HINT_OFFSET_M, 6), round(center_y, 6)]

    def _request_id(self, request: JsonObject) -> str:
        return self._text_value(request.get("id"))

    def _com_member_available(self, obj: Any, name: str) -> bool:
        if obj is None or not name:
            return False
        with suppress(Exception):
            getattr(obj, name)
            return True
        return False

    def _resolve_drawing_template(self, app: Any) -> str:
        default_template = str(
            self._com_value(app, "GetUserPreferenceStringValue", SW_DEFAULT_TEMPLATE_DRAWING) or ""
        )
        template_folder = str(
            self._com_value(app, "GetUserPreferenceStringValue", SW_TEMPLATE_FOLDER) or ""
        )
        candidates = []
        if template_folder:
            candidates.append(Path(template_folder) / PREFERRED_DRAWING_TEMPLATE)
        if default_template:
            candidates.append(Path(default_template).with_name(PREFERRED_DRAWING_TEMPLATE))
            candidates.append(Path(default_template))

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return default_template

    def _get_view_outline(self, view: Any) -> list[float] | None:
        with suppress(Exception):
            outline = self._com_optional(view, "GetOutline")
            return [round(float(value), 6) for value in outline]
        return None

    def _get_sheet_info(self, drawing: Any, template: str) -> JsonObject:
        result: JsonObject = {
            "template": template,
            "source": "solidworks_current_sheet",
            "title_block_note": (
                "Sheet size is read from SolidWorks; title block zone is still approximated "
                "until template geometry parsing is implemented."
            ),
        }
        with suppress(Exception):
            sheet = self._com_optional(drawing, "GetCurrentSheet")
            if sheet is None:
                return result
            result["name"] = self._com_optional(sheet, "GetName")
            properties = self._com_optional(sheet, "GetProperties")
            if properties is not None:
                values = [float(value) for value in properties]
                result["properties"] = [round(value, 6) for value in values]
                if len(values) >= 7 and values[5] > 0 and values[6] > 0:
                    result["sheet_size_m"] = [round(values[5], 6), round(values[6], 6)]
                    result["safe_area_m"] = self._safe_area_zone(values[5], values[6])
                    result["title_block_zone_m"] = self._approximate_title_block_zone(
                        values[5],
                        values[6],
                    )
        return result

    def _safe_area_zone(self, width_m: float, height_m: float) -> list[float]:
        x_margin = min(SHEET_SAFE_MARGIN_M, max(width_m, 0.0) / 2)
        y_margin = min(SHEET_SAFE_MARGIN_M, max(height_m, 0.0) / 2)
        return [
            round(x_margin, 6),
            round(y_margin, 6),
            round(max(x_margin, width_m - x_margin), 6),
            round(max(y_margin, height_m - y_margin), 6),
        ]

    def _approximate_title_block_zone(self, width_m: float, height_m: float) -> list[float]:
        title_block_width = min(0.180, max(width_m, 0.0))
        title_block_height = min(0.060, max(height_m, 0.0))
        return [
            round(max(0.0, width_m - title_block_width), 6),
            0.0,
            round(width_m, 6),
            round(title_block_height, 6),
        ]

    def _find_overlaps(
        self,
        inserted_view: JsonObject,
        existing_views: list[JsonObject],
    ) -> list[JsonObject]:
        outline = inserted_view.get("outline_m")
        if not isinstance(outline, list) or len(outline) != 4:
            return []

        warnings: list[JsonObject] = []
        for existing in existing_views:
            existing_outline = existing.get("outline_m")
            if not isinstance(existing_outline, list) or len(existing_outline) != 4:
                continue
            if self._outlines_overlap(outline, existing_outline, VIEW_OVERLAP_MARGIN_M):
                warnings.append(
                    {
                        "view": inserted_view["view"],
                        "overlaps_with": existing["view"],
                        "margin_m": VIEW_OVERLAP_MARGIN_M,
                    }
                )
        return warnings

    def _outlines_overlap(
        self,
        first: list[float],
        second: list[float],
        margin: float,
    ) -> bool:
        return not (
            first[2] + margin <= second[0]
            or second[2] + margin <= first[0]
            or first[3] + margin <= second[1]
            or second[3] + margin <= first[1]
        )

    def _resolve_source_model(self, app: Any, plan: DrawingPlan) -> str:
        document = self._resolve_model_document(app, plan.part.source_model)
        path = self._document_path(document)
        if path:
            return path
        if plan.part.source_model:
            return plan.part.source_model

        active_doc = self._com_value(app, "ActiveDoc")
        if active_doc is None:
            raise RuntimeError("No source_model provided and SolidWorks has no active document.")
        if self._com_value(active_doc, "GetType") != SW_DOC_PART:
            raise RuntimeError(
                "No source_model provided and active SolidWorks document is not a part."
            )
        return str(self._com_value(active_doc, "GetPathName"))

    def _resolve_model_document(self, app: Any, source_model: str | None) -> Any:
        if source_model:
            source_path = Path(source_model)
            if not source_path.exists():
                raise FileNotFoundError(f"SolidWorks source model not found: {source_model}")
            opened = self._com_value(app, "GetOpenDocumentByName", source_model)
            if opened is None:
                errors = self._byref_i4()
                warnings = self._byref_i4()
                opened = app.OpenDoc6(
                    source_model,
                    self._solidworks_doc_type(source_path),
                    SW_OPEN_SILENT,
                    "",
                    errors,
                    warnings,
                )
            if opened is None:
                raise RuntimeError(f"Unable to open SolidWorks source model: {source_model}")
            return opened

        active_doc = self._com_value(app, "ActiveDoc")
        if active_doc is None:
            raise RuntimeError("No source_model provided and SolidWorks has no active document.")
        if self._com_value(active_doc, "GetType") not in {SW_DOC_PART, SW_DOC_ASSEMBLY}:
            raise RuntimeError(
                "No source_model provided and active SolidWorks document is not a model."
            )
        return active_doc

    def _solidworks_doc_type(self, source_path: Path) -> int:
        if source_path.suffix.lower() == ".sldasm":
            return SW_DOC_ASSEMBLY
        return SW_DOC_PART

    def _document_path(self, document: Any) -> str | None:
        path = self._text_value(self._com_optional(document, "GetPathName"))
        return path or None

    def _model_bounding_box(
        self,
        document: Any,
        warnings: list[str],
    ) -> JsonObject | None:
        box = self._numeric_sequence(self._com_optional(document, "GetPartBox", True), 6)
        source = "GetPartBox"
        if box is None:
            box = self._numeric_sequence(self._com_optional(document, "GetPartBox", False), 6)
        if box is None:
            extension = self._com_optional(document, "Extension")
            box = self._numeric_sequence(self._com_optional(extension, "GetBox", 0), 6)
            source = "Extension.GetBox"
        if box is None:
            warnings.append("Unable to read model bounding box through GetPartBox/GetBox.")
            return None

        min_x, min_y, min_z, max_x, max_y, max_z = box
        size_m = [
            max(0.0, max_x - min_x),
            max(0.0, max_y - min_y),
            max(0.0, max_z - min_z),
        ]
        return {
            "source": source,
            "min_m": [round(min_x, 9), round(min_y, 9), round(min_z, 9)],
            "max_m": [round(max_x, 9), round(max_y, 9), round(max_z, 9)],
            "size_m": [round(value, 9) for value in size_m],
            "size_mm": [round(value * 1000, 3) for value in size_m],
        }

    def _model_features_and_dimensions(
        self,
        document: Any,
        warnings: list[str],
    ) -> tuple[list[JsonObject], list[JsonObject]]:
        feature = self._com_optional(document, "FirstFeature")
        if feature is None:
            warnings.append("Unable to read SolidWorks feature tree through FirstFeature.")
            return [], []

        features: list[JsonObject] = []
        dimensions: list[JsonObject] = []
        while feature is not None and len(features) < MAX_MODEL_FEATURES:
            feature_summary = self._feature_summary(feature, len(features) + 1)
            feature_dimensions = self._feature_dimensions(
                feature,
                str(feature_summary.get("name", "")),
                len(dimensions),
            )
            if feature_dimensions:
                feature_summary["dimension_count"] = len(feature_dimensions)
                feature_summary["dimension_names"] = [
                    str(dimension.get("name", ""))
                    for dimension in feature_dimensions
                    if dimension.get("name")
                ]
                dimensions.extend(feature_dimensions)
            features.append(feature_summary)
            if len(dimensions) >= MAX_MODEL_DIMENSIONS:
                warnings.append(
                    f"Model dimension collection stopped at {MAX_MODEL_DIMENSIONS} items."
                )
                break
            feature = self._com_optional(feature, "GetNextFeature")

        if len(features) >= MAX_MODEL_FEATURES:
            warnings.append(f"Feature collection stopped at {MAX_MODEL_FEATURES} items.")
        return features, dimensions[:MAX_MODEL_DIMENSIONS]

    def _feature_summary(self, feature: Any, index: int) -> JsonObject:
        summary: JsonObject = {
            "index": index,
            "name": self._text_value(self._com_optional(feature, "Name")),
            "type": self._text_value(
                self._com_optional(feature, "GetTypeName2")
                or self._com_optional(feature, "GetTypeName")
            ),
        }
        suppressed = self._com_optional(feature, "IsSuppressed")
        if isinstance(suppressed, bool):
            summary["is_suppressed"] = suppressed
        return summary

    def _feature_type_counts(self, features: list[JsonObject]) -> JsonObject:
        counts = Counter(str(feature.get("type", "unknown")) for feature in features)
        return dict(sorted(counts.items()))

    def _model_source_quality(
        self,
        features: list[JsonObject],
        dimensions: list[JsonObject],
    ) -> str:
        feature_types = {str(feature.get("type", "")) for feature in features}
        if dimensions:
            return "parametric_dimensions_available"
        if feature_types.intersection(IMPORTED_MODEL_FEATURE_TYPES):
            return "imported_body_without_parametric_dimensions"
        if features:
            return "feature_tree_without_collected_dimensions"
        return "unknown"

    def _feature_dimensions(
        self,
        feature: Any,
        feature_name: str,
        global_dimension_count: int,
    ) -> list[JsonObject]:
        dimensions: list[JsonObject] = []
        display_dimension = self._com_optional(feature, "GetFirstDisplayDimension")
        while display_dimension is not None and len(dimensions) < MAX_FEATURE_DIMENSIONS:
            summary = self._display_dimension_summary(display_dimension, feature_name)
            if summary:
                dimensions.append(summary)
            if global_dimension_count + len(dimensions) >= MAX_MODEL_DIMENSIONS:
                break
            next_dimension = self._com_optional(
                feature,
                "GetNextDisplayDimension",
                display_dimension,
            )
            if next_dimension is None:
                next_dimension = self._com_optional(display_dimension, "GetNext")
            display_dimension = next_dimension
        return dimensions

    def _display_dimension_summary(
        self,
        display_dimension: Any,
        feature_name: str,
    ) -> JsonObject | None:
        dimension = self._com_optional(display_dimension, "GetDimension2", 0)
        if dimension is None:
            dimension = self._com_optional(display_dimension, "GetDimension")
        if dimension is None:
            return None

        value_m = self._float_value(self._com_optional(dimension, "SystemValue"))
        name = self._text_value(
            self._com_optional(dimension, "FullName")
            or self._com_optional(dimension, "Name")
            or self._com_optional(display_dimension, "GetNameForSelection")
        )
        result: JsonObject = {
            "name": name,
            "feature": feature_name,
            "source": "solidworks_display_dimension",
        }
        dimension_type = self._com_optional(display_dimension, "GetType2")
        if dimension_type is not None:
            result["display_dimension_type"] = dimension_type
        if value_m is not None:
            result["value_m"] = round(value_m, 9)
            result["value_mm"] = round(value_m * 1000, 3)
        return result

    def _activate_last_drawing(self, app: Any) -> Any:
        if not self._last_drawing_title:
            return self._com_value(app, "ActiveDoc")
        errors = self._byref_i4()
        with suppress(Exception):
            app.ActivateDoc3(self._last_drawing_title, False, 0, errors)
        return self._com_value(app, "ActiveDoc")

    def _close_last_drawing(self, app: Any) -> JsonObject:
        if os.getenv("MDA_KEEP_DRAWING_OPEN") == "1":
            return {"status": "kept_open", "reason": "MDA_KEEP_DRAWING_OPEN=1"}
        if not self._last_drawing_title:
            return {"status": "skipped", "reason": "No drawing title was recorded."}
        with suppress(Exception):
            app.CloseDoc(self._last_drawing_title)
            return {"status": "closed", "title": self._last_drawing_title}
        return {
            "status": "failed",
            "title": self._last_drawing_title,
            "reason": "CloseDoc raised a COM exception.",
        }

    def _get_active_app(self) -> Any:
        import win32com.client

        try:
            return win32com.client.GetActiveObject("SldWorks.Application")
        except Exception:  # noqa: BLE001 - optionally fall back to starting SolidWorks.
            if not self._env_flag(LAUNCH_SOLIDWORKS_ENV):
                raise
        app = win32com.client.Dispatch("SldWorks.Application")
        with suppress(Exception):
            app.Visible = self._env_flag(SOLIDWORKS_VISIBLE_ENV, default=True)
        return app

    def _env_flag(self, name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _co_initialize(self) -> None:
        import pythoncom

        pythoncom.CoInitialize()

    def _co_uninitialize(self) -> None:
        import pythoncom

        pythoncom.CoUninitialize()

    def _byref_i4(self) -> Any:
        import pythoncom
        from win32com.client import VARIANT

        return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    def _com_value(self, obj: Any, name: str, *args: object) -> Any:
        value = getattr(obj, name)
        if not args:
            return value
        if callable(value):
            return value(*args)
        raise TypeError(f"COM property `{name}` is not callable.")

    def _com_optional(self, obj: Any, name: str, *args: object) -> Any:
        if obj is None:
            return None
        try:
            value = getattr(obj, name)
        except Exception:  # noqa: BLE001 - COM probing is best-effort.
            return None
        try:
            if callable(value):
                if not args and self._is_com_dispatch(value):
                    return value
                return value(*args)
            if args:
                return None
            return value
        except Exception:  # noqa: BLE001 - COM probing is best-effort.
            return None

    def _is_com_dispatch(self, value: Any) -> bool:
        value_type = type(value)
        return value_type.__name__ == "CDispatch" and value_type.__module__.startswith("win32com")

    def _numeric_sequence(self, value: Any, length: int) -> list[float] | None:
        if value is None:
            return None
        try:
            values = [float(item) for item in value]
        except (TypeError, ValueError):
            return None
        if len(values) < length:
            return None
        return values[:length]

    def _float_value(self, value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _text_value(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _list_of_text(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    def _extra_view_requests(self, plan: DrawingPlan) -> list[JsonObject]:
        value = plan.view_plan.get("extra_view_requests")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []
