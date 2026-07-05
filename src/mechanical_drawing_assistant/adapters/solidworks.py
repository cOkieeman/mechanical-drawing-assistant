from __future__ import annotations

import importlib.util
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from mechanical_drawing_assistant.models import DrawingPlan, JsonObject

SW_DOC_PART = 1
SW_DOC_DRAWING = 3
SW_OPEN_SILENT = 1
SW_PAPER_A3 = 9
SW_HIDDEN_LINES_REMOVED = 6
SW_DEFAULT_TEMPLATE_DRAWING = 10
SW_TEMPLATE_FOLDER = 6

PREFERRED_DRAWING_TEMPLATE = "gb_a3.drwdot"
VIEW_OVERLAP_MARGIN_M = 0.02

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
    "top": (0.13, 0.055),
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

    def create_three_view_drawing(self, plan: DrawingPlan, dry_run: bool = True) -> JsonObject:
        if dry_run:
            return {
                "adapter": "solidworks",
                "action": "create_three_view_drawing",
                "status": "planned",
                "views": plan.views,
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

            with suppress(Exception):
                drawing.ViewZoomtofit2()

            return {
                "adapter": "solidworks",
                "action": "create_three_view_drawing",
                "status": "created",
                "source_model": source_model,
                "template": template,
                "drawing_title": drawing_title,
                "inserted_views": inserted,
                "failed_views": failed,
                "overlap_warnings": overlap_warnings,
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
            outline = self._com_value(view, "GetOutline")
            return [round(float(value), 6) for value in outline]
        return None

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
        source_model = plan.part.source_model
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
                    SW_DOC_PART,
                    SW_OPEN_SILENT,
                    "",
                    errors,
                    warnings,
                )
            if opened is None:
                raise RuntimeError(f"Unable to open SolidWorks source model: {source_model}")
            return source_model

        active_doc = self._com_value(app, "ActiveDoc")
        if active_doc is None:
            raise RuntimeError("No source_model provided and SolidWorks has no active document.")
        if self._com_value(active_doc, "GetType") != SW_DOC_PART:
            raise RuntimeError(
                "No source_model provided and active SolidWorks document is not a part."
            )
        return str(self._com_value(active_doc, "GetPathName"))

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

        return win32com.client.GetActiveObject("SldWorks.Application")

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
