from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from math import hypot
from pathlib import Path
from typing import Any

import ezdxf

from mechanical_drawing_assistant.models import JsonObject

DIMENSION_LAYER = "MDA-DIM"
ANNOTATION_DIMSTYLE = "MDA_DIM"
ANNOTATION_RADIUS_DIMSTYLE = "MDA_RADIUS"
ANNOTATION_TEXT_HEIGHT_MM = 3.5
ANNOTATION_ARROW_SIZE_MM = 2.5
ANNOTATION_DIM_GAP_MM = 0.8
CALLOUT_DOGLEG_MM = 4.0
LAYOUT_CLEARANCE_MM = 2.0
LAYOUT_TEXT_WIDTH_FACTOR = 0.68
LAYOUT_TEXT_HEIGHT_FACTOR = 1.35
SHEET_WIDTH_MM = 420.0
SHEET_HEIGHT_MM = 297.0
SHEET_SAFE_MARGIN_MM = 6.0
TITLE_BLOCK_WIDTH_MM = 180.0
TITLE_BLOCK_HEIGHT_MM = 60.0
ANNOTATION_MARGIN_MM = 0.5
MIN_DIMENSION_SIZE_MM = 1.0
FEATURE_CLUSTER_TOLERANCE_MM = 0.25
MAX_STEP_DIMENSIONS_PER_VIEW = 4
PRIMARY_LINEAR_DIMENSION_VIEWS = {"front"}
TRUSTED_CIRCULAR_DIMENSION_TYPES = {"outer_diameter", "bore_diameter"}
ANNOTATION_POLICY = "conservative_standard_draft"
MODEL_DRIVEN_ANNOTATION_POLICY = "model_driven_standard_draft"


class DxfAdapter:
    def is_available(self) -> bool:
        return True

    def inspect_file(self, path: Path) -> JsonObject:
        if path.suffix.lower() == ".dwg":
            return {
                "path": str(path),
                "status": "unsupported",
                "reason": "ezdxf cannot read DWG directly; export/convert to DXF first.",
            }
        if not path.exists():
            return {"path": str(path), "status": "missing"}

        document = ezdxf.readfile(path)
        modelspace = document.modelspace()
        entity_counts = Counter(entity.dxftype() for entity in modelspace)
        dimensions = [
            self._dimension_summary(entity)
            for entity in modelspace
            if entity.dxftype() == "DIMENSION"
        ]

        return {
            "path": str(path),
            "status": "ok",
            "dxfversion": document.dxfversion,
            "entity_counts": dict(sorted(entity_counts.items())),
            "dimension_count": len(dimensions),
            "dimensions": dimensions[:100],
        }

    def annotate_file(
        self,
        path: Path,
        output_path: Path | None = None,
        view_outlines_m: list[JsonObject] | None = None,
        model_manifest: JsonObject | None = None,
        sheet_info: JsonObject | None = None,
    ) -> JsonObject:
        if path.suffix.lower() == ".dwg":
            return {
                "path": str(path),
                "status": "unsupported",
                "reason": "ezdxf cannot write DWG directly; export/convert to DXF first.",
            }
        if not path.exists():
            return {"path": str(path), "status": "missing"}

        output = output_path or path.with_name(f"{path.stem}-annotated.dxf")
        document = ezdxf.readfile(path)
        modelspace = document.modelspace()
        self._ensure_annotation_layer(document)
        self._ensure_annotation_styles(document)

        regions = self._resolve_view_regions(view_outlines_m)
        sheet_layout = self._sheet_layout_from_info(sheet_info)
        annotations: list[JsonObject] = []
        feature_candidates: list[JsonObject] = []
        warnings: list[str] = []
        view_contexts: list[JsonObject] = []
        annotation_policy = ANNOTATION_POLICY

        if not regions:
            warnings.append("No view outlines were provided; first-pass annotation was skipped.")

        for region in regions:
            view_name = str(region.get("view", "unknown"))
            entities = self._entities_in_region(modelspace, region)
            bounds = self._combined_bounds(entities)
            if bounds is None:
                warnings.append(f"No DXF geometry was found for view `{view_name}`.")
                continue

            circular_features = self._circular_features(entities)
            view_contexts.append(
                {
                    "view": view_name,
                    "region": region,
                    "bounds": bounds,
                    "circular_features": circular_features,
                    "annotation_layout": self._new_annotation_layout(
                        view_name,
                        bounds,
                        circular_features,
                        sheet_layout,
                    ),
                }
            )
            circular_feature = circular_features[0] if circular_features else None
            view_features = self._view_feature_candidates(
                view_name,
                entities,
                bounds,
                circular_features,
            )
            feature_candidates.extend(view_features)

        model_annotations = self._add_model_driven_dimensions(
            modelspace,
            view_contexts,
            model_manifest,
        )
        if model_annotations:
            annotations.extend(model_annotations)
            annotation_policy = MODEL_DRIVEN_ANNOTATION_POLICY
        else:
            for context in view_contexts:
                view_name = str(context.get("view", "unknown"))
                bounds = context.get("bounds")
                if not isinstance(bounds, list) or len(bounds) != 4:
                    continue
                circular_features = context.get("circular_features")
                if not isinstance(circular_features, list):
                    circular_features = []
                circular_feature = circular_features[0] if circular_features else None
                view_features = [
                    feature for feature in feature_candidates if feature.get("view") == view_name
                ]

                if self._looks_like_circular_view(bounds, circular_feature):
                    annotations.extend(
                        self._add_circular_dimensions(
                            modelspace,
                            view_name,
                            view_features,
                        )
                    )
                    continue

                if view_name in PRIMARY_LINEAR_DIMENSION_VIEWS:
                    region = context.get("region")
                    if isinstance(region, dict):
                        annotations.extend(
                            self._add_primary_linear_dimensions(
                                modelspace,
                                view_name,
                                bounds,
                                region,
                                context.get("annotation_layout"),
                            )
                        )

        output.parent.mkdir(parents=True, exist_ok=True)
        actual_output = self._save_with_locked_file_fallback(document, output, warnings)
        inspect_result = self.inspect_file(actual_output)
        annotation_summary = self._annotation_summary(annotations, feature_candidates, regions)
        annotation_review = self._review_annotations(
            annotations,
            feature_candidates,
            regions,
            view_contexts,
            warnings,
        )

        return {
            "path": str(path),
            "output_path": str(actual_output),
            "requested_output_path": str(output),
            "status": "annotated",
            "annotation_policy": annotation_policy,
            "units_assumption": "DXF modelspace units are millimeters.",
            "view_count": len(regions),
            "layout_context": {
                "sheet": sheet_layout,
                "regions": [
                    {
                        "view": str(region.get("view", "unknown")),
                        "bounds": [
                            round(float(value), 3)
                            for value in region.get("bounds", [])
                            if isinstance(value, int | float)
                        ],
                    }
                    for region in regions
                    if isinstance(region.get("bounds"), list)
                ],
            },
            "dimensions_added": len(annotations),
            "dimension_count_after": inspect_result.get("dimension_count", 0),
            "annotations": annotations,
            "feature_candidates": feature_candidates,
            "annotation_summary": annotation_summary,
            "annotation_review": annotation_review,
            "warnings": warnings,
        }

    def _save_with_locked_file_fallback(
        self,
        document: Any,
        output: Path,
        warnings: list[str],
    ) -> Path:
        try:
            document.saveas(output)
            return output
        except PermissionError:
            pass
        except OSError as exc:
            if not self._looks_like_locked_file_error(exc):
                raise

        for index in range(1, 100):
            candidate = output.with_name(f"{output.stem}-{index}{output.suffix}")
            try:
                document.saveas(candidate)
                warnings.append(
                    f"Requested output `{output}` was locked; wrote `{candidate}` instead."
                )
                return candidate
            except PermissionError:
                continue
            except OSError as exc:
                if self._looks_like_locked_file_error(exc):
                    continue
                raise
        raise PermissionError(
            f"Unable to write DXF output; all fallback paths are locked: {output}"
        )

    def _looks_like_locked_file_error(self, exc: OSError) -> bool:
        return getattr(exc, "errno", None) in {13, 32}

    def _new_annotation_layout(
        self,
        view_name: str,
        bounds: list[float],
        circular_features: list[JsonObject],
        sheet_layout: JsonObject | None = None,
    ) -> JsonObject:
        layout_sheet = sheet_layout or self._sheet_layout_from_info(None)
        layout: JsonObject = {
            "view": view_name,
            "view_bounds": [round(value, 3) for value in bounds],
            "occupied_boxes": [],
            "placements": [],
            "sheet_bounds": layout_sheet["sheet_bounds"],
            "sheet_source": layout_sheet["source"],
            "safe_area": layout_sheet["safe_area"],
            "restricted_boxes": layout_sheet["restricted_boxes"],
        }
        self._layout_add_box(layout, bounds, "view_geometry", "view_geometry")
        for index, feature in enumerate(circular_features):
            center = feature.get("center")
            radius = self._float_value(feature.get("radius_mm"))
            if not isinstance(center, list) or len(center) != 2 or radius is None:
                continue
            circle_box = [
                float(center[0]) - radius,
                float(center[1]) - radius,
                float(center[0]) + radius,
                float(center[1]) + radius,
            ]
            self._layout_add_box(
                layout,
                circle_box,
                str(feature.get("entity_type", "circular_feature")),
                f"circular_feature_{index + 1}",
            )
        return layout

    def _layout_add_box(
        self,
        layout: JsonObject | None,
        box: list[float] | tuple[float, float, float, float],
        kind: str,
        source: str,
    ) -> None:
        if not isinstance(layout, dict) or len(box) != 4:
            return
        boxes = layout.setdefault("occupied_boxes", [])
        if not isinstance(boxes, list):
            return
        boxes.append(
            {
                "kind": kind,
                "source": source,
                "box": [round(float(value), 3) for value in box],
            }
        )

    def _layout_place_text(
        self,
        layout: JsonObject | None,
        annotation_id: str,
        text: str,
        candidates: list[tuple[float, float]],
    ) -> JsonObject:
        normalized_candidates = candidates or [(0.0, 0.0)]
        scored: list[tuple[int, int, tuple[float, float], list[float], list[str]]] = []
        for index, point in enumerate(normalized_candidates):
            box = self._text_box_from_top_left(text, point)
            collision_sources = self._layout_collision_sources(layout, box)
            collision_count = len(collision_sources)
            scored.append((collision_count, index, point, box, collision_sources))
            if collision_count == 0:
                break

        collision_count, index, point, box, collision_sources = min(
            scored, key=lambda item: (item[0], item[1])
        )
        placement: JsonObject = {
            "strategy": "candidate_box_avoidance",
            "candidate_index": index,
            "collision_count": collision_count,
            "collision_sources": collision_sources,
            "text_point": [round(point[0], 3), round(point[1], 3)],
            "text_box": [round(value, 3) for value in box],
        }
        self._layout_add_box(layout, box, "annotation_text", annotation_id)
        if isinstance(layout, dict):
            placements = layout.setdefault("placements", [])
            if isinstance(placements, list):
                placements.append(
                    {
                        "id": annotation_id,
                        "text": text,
                        "layout": placement,
                    }
                )
        return placement

    def _layout_collision_count(self, layout: JsonObject | None, box: list[float]) -> int:
        return len(self._layout_collision_sources(layout, box))

    def _layout_collision_sources(self, layout: JsonObject | None, box: list[float]) -> list[str]:
        if not isinstance(layout, dict):
            return []
        sources = self._layout_constraint_sources(layout, box)
        occupied_boxes = layout.get("occupied_boxes")
        if not isinstance(occupied_boxes, list):
            return sources
        for item in occupied_boxes:
            if not isinstance(item, dict):
                continue
            other = item.get("box")
            if not isinstance(other, list) or len(other) != 4:
                continue
            if self._boxes_overlap(box, [float(value) for value in other], LAYOUT_CLEARANCE_MM):
                kind = str(item.get("kind", "occupied_box"))
                source = str(item.get("source", "unknown"))
                sources.append(f"{kind}:{source}")
        return sources

    def _layout_constraint_sources(
        self,
        layout: JsonObject | None,
        box: list[float],
    ) -> list[str]:
        if not isinstance(layout, dict):
            return []
        sources: list[str] = []
        safe_area = self._normalized_box(layout.get("safe_area"))
        if safe_area is not None and not self._box_inside(box, safe_area):
            sources.append("sheet_safe_area:outside")
        restricted_boxes = layout.get("restricted_boxes")
        if isinstance(restricted_boxes, list):
            for item in restricted_boxes:
                if not isinstance(item, dict):
                    continue
                restricted_box = self._normalized_box(item.get("box"))
                if restricted_box is None:
                    continue
                if self._boxes_overlap(box, restricted_box, LAYOUT_CLEARANCE_MM):
                    kind = str(item.get("kind", "restricted_box"))
                    source = str(item.get("source", "unknown"))
                    sources.append(f"{kind}:{source}")
        return sources

    def _text_box_from_top_left(
        self,
        text: str,
        point: tuple[float, float],
    ) -> list[float]:
        lines = text.splitlines() or [text]
        text_width = max(len(line) for line in lines) * ANNOTATION_TEXT_HEIGHT_MM
        text_width *= LAYOUT_TEXT_WIDTH_FACTOR
        text_height = max(1, len(lines)) * ANNOTATION_TEXT_HEIGHT_MM
        text_height *= LAYOUT_TEXT_HEIGHT_FACTOR
        x, y = point
        return [x, y - text_height, x + text_width, y]

    def _text_box_from_center(
        self,
        text: str,
        point: tuple[float, float],
    ) -> list[float]:
        box = self._text_box_from_top_left(text, (0.0, 0.0))
        width = box[2] - box[0]
        height = box[3] - box[1]
        center_x, center_y = point
        return [
            center_x - width / 2,
            center_y - height / 2,
            center_x + width / 2,
            center_y + height / 2,
        ]

    def _boxes_overlap(
        self,
        first: list[float],
        second: list[float],
        clearance: float = 0.0,
    ) -> bool:
        first_min_x, first_min_y, first_max_x, first_max_y = first
        second_min_x, second_min_y, second_max_x, second_max_y = second
        return not (
            first_max_x + clearance <= second_min_x
            or second_max_x + clearance <= first_min_x
            or first_max_y + clearance <= second_min_y
            or second_max_y + clearance <= first_min_y
        )

    def _box_inside(self, inner: list[float], outer: list[float]) -> bool:
        return (
            inner[0] >= outer[0]
            and inner[1] >= outer[1]
            and inner[2] <= outer[2]
            and inner[3] <= outer[3]
        )

    def _layout_from_context(self, context: JsonObject) -> JsonObject | None:
        layout = context.get("annotation_layout")
        return layout if isinstance(layout, dict) else None

    def _dimension_summary(self, entity: Any) -> JsonObject:
        return {
            "layer": entity.dxf.layer,
            "dimtype": int(entity.dxf.dimtype),
            "text": getattr(entity.dxf, "text", ""),
        }

    def _annotation_summary(
        self,
        annotations: list[JsonObject],
        feature_candidates: list[JsonObject],
        regions: list[JsonObject],
    ) -> JsonObject:
        annotations_by_view = Counter(
            str(annotation.get("view", "unknown")) for annotation in annotations
        )
        features_by_view = Counter(
            str(feature.get("view", "unknown")) for feature in feature_candidates
        )
        features_by_type = Counter(
            str(feature.get("feature_type", "unknown")) for feature in feature_candidates
        )
        annotations_by_label = Counter(
            str(annotation.get("label", "unknown")) for annotation in annotations
        )
        return {
            "region_count": len(regions),
            "annotation_count": len(annotations),
            "feature_candidate_count": len(feature_candidates),
            "annotations_by_view": dict(sorted(annotations_by_view.items())),
            "features_by_view": dict(sorted(features_by_view.items())),
            "features_by_type": dict(sorted(features_by_type.items())),
            "annotations_by_label": dict(sorted(annotations_by_label.items())),
        }

    def _review_annotations(
        self,
        annotations: list[JsonObject],
        feature_candidates: list[JsonObject],
        regions: list[JsonObject],
        view_contexts: list[JsonObject],
        warnings: list[str],
    ) -> JsonObject:
        findings: list[JsonObject] = []
        if warnings:
            findings.append(
                self._annotation_finding(
                    "WARN",
                    "DXF_ANNOTATION_WARNING",
                    "DXF 初次标注存在警告：" + "；".join(warnings),
                    "检查 view outline 是否覆盖真实几何，必要时重新导出 DXF 或调整视图区域。",
                )
            )

        if regions and not annotations:
            findings.append(
                self._annotation_finding(
                    "ERROR",
                    "DXF_NO_ANNOTATIONS",
                    "DXF 标注器没有生成任何尺寸。",
                    "优先检查 DXF 单位、视图区域和几何实体类型。",
                )
            )

        duplicate_annotation_ids = self._duplicates(
            str(annotation.get("id", "")) for annotation in annotations
        )
        if duplicate_annotation_ids:
            findings.append(
                self._annotation_finding(
                    "WARN",
                    "DXF_DUPLICATE_ANNOTATION_ID",
                    "DXF 标注结果存在重复 annotation id：" + "、".join(duplicate_annotation_ids),
                    "检查特征命名规则，避免后续审查或写回时覆盖同名尺寸。",
                    {"duplicate_ids": duplicate_annotation_ids},
                )
            )

        unannotated_features = self._unannotated_features(annotations, feature_candidates)
        if unannotated_features:
            findings.append(
                self._annotation_finding(
                    "INFO",
                    "DXF_FEATURES_NOT_DIMENSIONED",
                    "部分候选特征尚未生成对应尺寸："
                    + "、".join(feature["id"] for feature in unannotated_features[:8]),
                    "这些候选特征需要人工复核；后续可补充对应标注规则。",
                    {
                        "feature_ids": [feature["id"] for feature in unannotated_features],
                    },
                )
            )

        view_names = [str(region.get("view", "unknown")) for region in regions]
        annotated_views = {str(annotation.get("view", "unknown")) for annotation in annotations}
        missing_view_annotations = [
            view_name for view_name in view_names if view_name not in annotated_views
        ]
        if missing_view_annotations:
            severity = "WARN" if not annotations else "INFO"
            findings.append(
                self._annotation_finding(
                    severity,
                    "DXF_VIEW_WITHOUT_DIMENSIONS",
                    "部分视图未自动写入尺寸：" + "、".join(missing_view_annotations),
                    "当前采用保守初稿策略，重复投影视图和低置信候选特征先交给人工复核。",
                    {
                        "views": missing_view_annotations,
                        "annotation_policy": (
                            MODEL_DRIVEN_ANNOTATION_POLICY
                            if any(
                                annotation.get("source", "").startswith("solidworks_")
                                for annotation in annotations
                            )
                            else ANNOTATION_POLICY
                        ),
                    },
                )
            )

        findings.extend(self._annotation_layout_findings(annotations, view_contexts))

        return {
            "status": self._annotation_review_status(findings),
            "findings": findings,
        }

    def _annotation_layout_findings(
        self,
        annotations: list[JsonObject],
        view_contexts: list[JsonObject],
    ) -> list[JsonObject]:
        findings: list[JsonObject] = []
        text_boxes = self._annotation_text_boxes(annotations)

        overlapping_pairs = self._overlapping_annotation_text_boxes(text_boxes)
        if overlapping_pairs:
            findings.append(
                self._annotation_finding(
                    "WARN",
                    "DXF_ANNOTATION_TEXT_OVERLAP",
                    "部分标注文字盒存在重叠风险，可能影响读图。",
                    "优先调整尺寸基线、callout 候选位置或增加局部放大图。",
                    {
                        "overlap_count": len(overlapping_pairs),
                        "overlaps": overlapping_pairs[:20],
                    },
                )
            )

        inside_geometry = self._annotation_text_inside_geometry(text_boxes, view_contexts)
        if inside_geometry:
            findings.append(
                self._annotation_finding(
                    "WARN",
                    "DXF_ANNOTATION_TEXT_INSIDE_GEOMETRY",
                    "部分线性尺寸或引出注写文字落入视图几何范围，可能遮挡图形。",
                    "将这些文字移到视图外侧，或使用引出线、局部放大图重新排布。",
                    {
                        "annotation_ids": [item["id"] for item in inside_geometry],
                        "items": inside_geometry[:20],
                    },
                )
            )

        outside_safe_area = self._annotation_text_outside_safe_area(text_boxes, view_contexts)
        if outside_safe_area:
            findings.append(
                self._annotation_finding(
                    "WARN",
                    "DXF_ANNOTATION_TEXT_OUTSIDE_SAFE_AREA",
                    "部分标注文字过于靠近或越过图纸安全边距，可能与图框重合。",
                    "将尺寸基线或引出注写移入图纸安全区，必要时增大视图间距或换用局部放大图。",
                    {
                        "annotation_ids": [item["id"] for item in outside_safe_area],
                        "items": outside_safe_area[:20],
                    },
                )
            )

        restricted_zone_items = self._annotation_text_in_restricted_zones(
            text_boxes,
            view_contexts,
        )
        if restricted_zone_items:
            findings.append(
                self._annotation_finding(
                    "WARN",
                    "DXF_ANNOTATION_TEXT_IN_RESTRICTED_ZONE",
                    "部分标注文字压入或贴近标题栏等禁排区域。",
                    "优先把标注移出标题栏区域并保留安全间距；如果空间不足，应调整视图比例、视图间距或分配到局部放大图。",
                    {
                        "annotation_ids": [item["id"] for item in restricted_zone_items],
                        "items": restricted_zone_items[:20],
                    },
                )
            )

        callout_collisions = self._callout_layout_collisions(annotations)
        if callout_collisions:
            findings.append(
                self._annotation_finding(
                    "WARN",
                    "DXF_CALLOUT_LAYOUT_COLLISION",
                    "部分引出注写候选位置仍存在包围盒碰撞。",
                    "增加候选位置、扩大视图间距，或由人工重新放置引出注写。",
                    {
                        "annotation_ids": [item["id"] for item in callout_collisions],
                        "items": callout_collisions[:20],
                    },
                )
            )

        return findings

    def _annotation_text_boxes(self, annotations: list[JsonObject]) -> list[JsonObject]:
        result: list[JsonObject] = []
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            layout = annotation.get("layout")
            if not isinstance(layout, dict):
                continue
            box = self._normalized_box(layout.get("text_box"))
            if box is None:
                continue
            result.append(
                {
                    "id": str(annotation.get("id", "")),
                    "view": str(annotation.get("view", "unknown")),
                    "kind": str(annotation.get("kind", "unknown")),
                    "label": str(annotation.get("label", "unknown")),
                    "box": box,
                }
            )
        return result

    def _overlapping_annotation_text_boxes(
        self,
        text_boxes: list[JsonObject],
    ) -> list[JsonObject]:
        result: list[JsonObject] = []
        for index, first in enumerate(text_boxes):
            first_box = first.get("box")
            if not isinstance(first_box, list) or len(first_box) != 4:
                continue
            for second in text_boxes[index + 1 :]:
                if first.get("view") != second.get("view"):
                    continue
                second_box = second.get("box")
                if not isinstance(second_box, list) or len(second_box) != 4:
                    continue
                if self._boxes_overlap(first_box, second_box):
                    result.append(
                        {
                            "view": first.get("view", "unknown"),
                            "first": first.get("id", ""),
                            "second": second.get("id", ""),
                            "first_kind": first.get("kind", "unknown"),
                            "second_kind": second.get("kind", "unknown"),
                            "first_label": first.get("label", "unknown"),
                            "second_label": second.get("label", "unknown"),
                            "overlap_area_mm2": round(
                                self._box_overlap_area(first_box, second_box), 3
                            ),
                            "clearance_mm": 0.0,
                        }
                    )
        return result

    def _annotation_text_inside_geometry(
        self,
        text_boxes: list[JsonObject],
        view_contexts: list[JsonObject],
    ) -> list[JsonObject]:
        bounds_by_view: dict[str, list[float]] = {}
        for context in view_contexts:
            if not isinstance(context, dict):
                continue
            bounds = self._normalized_box(context.get("bounds"))
            if bounds is None:
                continue
            bounds_by_view[str(context.get("view", "unknown"))] = bounds

        result: list[JsonObject] = []
        for item in text_boxes:
            if item.get("kind") not in {"linear", "callout"}:
                continue
            view_name = str(item.get("view", "unknown"))
            view_bounds = bounds_by_view.get(view_name)
            box = item.get("box")
            if view_bounds is None or not isinstance(box, list) or len(box) != 4:
                continue
            if self._boxes_overlap(box, view_bounds):
                text_center = self._box_center(box)
                result.append(
                    {
                        "id": item.get("id", ""),
                        "view": view_name,
                        "kind": item.get("kind", "unknown"),
                        "label": item.get("label", "unknown"),
                        "text_box": [round(value, 3) for value in box],
                        "view_bounds": [round(value, 3) for value in view_bounds],
                        "overlap_area_mm2": round(self._box_overlap_area(box, view_bounds), 3),
                        "inside_center": self._point_inside_box(text_center, view_bounds),
                    }
                )
        return result

    def _annotation_text_outside_safe_area(
        self,
        text_boxes: list[JsonObject],
        view_contexts: list[JsonObject],
    ) -> list[JsonObject]:
        layouts = self._annotation_layouts_by_view(view_contexts)
        result: list[JsonObject] = []
        for item in text_boxes:
            layout = layouts.get(str(item.get("view", "unknown")))
            if layout is None:
                continue
            safe_area = self._normalized_box(layout.get("safe_area"))
            box = item.get("box")
            if safe_area is None or not isinstance(box, list) or len(box) != 4:
                continue
            if not self._box_inside(box, safe_area):
                result.append(
                    {
                        "id": item.get("id", ""),
                        "view": item.get("view", "unknown"),
                        "kind": item.get("kind", "unknown"),
                        "label": item.get("label", "unknown"),
                        "text_box": [round(value, 3) for value in box],
                        "safe_area": [round(value, 3) for value in safe_area],
                        "violations": self._safe_area_violations(box, safe_area),
                    }
                )
        return result

    def _annotation_text_in_restricted_zones(
        self,
        text_boxes: list[JsonObject],
        view_contexts: list[JsonObject],
    ) -> list[JsonObject]:
        layouts = self._annotation_layouts_by_view(view_contexts)
        result: list[JsonObject] = []
        for item in text_boxes:
            layout = layouts.get(str(item.get("view", "unknown")))
            if layout is None:
                continue
            restricted_boxes = layout.get("restricted_boxes")
            box = item.get("box")
            if not isinstance(restricted_boxes, list) or not isinstance(box, list):
                continue
            for restricted in restricted_boxes:
                if not isinstance(restricted, dict):
                    continue
                restricted_box = self._normalized_box(restricted.get("box"))
                if restricted_box is None:
                    continue
                if not self._boxes_overlap(box, restricted_box, LAYOUT_CLEARANCE_MM):
                    continue
                result.append(
                    {
                        "id": item.get("id", ""),
                        "view": item.get("view", "unknown"),
                        "kind": item.get("kind", "unknown"),
                        "label": item.get("label", "unknown"),
                        "restricted_kind": str(restricted.get("kind", "restricted_box")),
                        "restricted_source": str(restricted.get("source", "unknown")),
                        "text_box": [round(value, 3) for value in box],
                        "restricted_box": [round(value, 3) for value in restricted_box],
                        "overlap_area_mm2": round(self._box_overlap_area(box, restricted_box), 3),
                        "clearance_mm": LAYOUT_CLEARANCE_MM,
                    }
                )
        return result

    def _annotation_layouts_by_view(
        self,
        view_contexts: list[JsonObject],
    ) -> dict[str, JsonObject]:
        layouts: dict[str, JsonObject] = {}
        for context in view_contexts:
            if not isinstance(context, dict):
                continue
            layout = context.get("annotation_layout")
            if isinstance(layout, dict):
                layouts[str(context.get("view", "unknown"))] = layout
        return layouts

    def _safe_area_violations(self, box: list[float], safe_area: list[float]) -> list[str]:
        violations: list[str] = []
        if box[0] < safe_area[0]:
            violations.append("left")
        if box[1] < safe_area[1]:
            violations.append("bottom")
        if box[2] > safe_area[2]:
            violations.append("right")
        if box[3] > safe_area[3]:
            violations.append("top")
        return violations

    def _callout_layout_collisions(self, annotations: list[JsonObject]) -> list[JsonObject]:
        result: list[JsonObject] = []
        for annotation in annotations:
            if not isinstance(annotation, dict) or annotation.get("kind") != "callout":
                continue
            layout = annotation.get("layout")
            if not isinstance(layout, dict):
                continue
            collision_count = self._float_value(layout.get("collision_count"))
            if collision_count is None or collision_count <= 0:
                continue
            result.append(
                {
                    "id": str(annotation.get("id", "")),
                    "view": str(annotation.get("view", "unknown")),
                    "label": str(annotation.get("label", "unknown")),
                    "collision_count": int(collision_count),
                    "collision_sources": layout.get("collision_sources", []),
                }
            )
        return result

    def _normalized_box(self, value: object) -> list[float] | None:
        if not isinstance(value, list) or len(value) != 4:
            return None
        box: list[float] = []
        try:
            for item in value:
                if not isinstance(item, int | float | str):
                    return None
                box.append(float(item))
        except (TypeError, ValueError):
            return None
        min_x, min_y, max_x, max_y = box
        if min_x > max_x:
            min_x, max_x = max_x, min_x
        if min_y > max_y:
            min_y, max_y = max_y, min_y
        return [min_x, min_y, max_x, max_y]

    def _box_overlap_area(self, first: list[float], second: list[float]) -> float:
        min_x = max(first[0], second[0])
        min_y = max(first[1], second[1])
        max_x = min(first[2], second[2])
        max_y = min(first[3], second[3])
        if max_x <= min_x or max_y <= min_y:
            return 0.0
        return (max_x - min_x) * (max_y - min_y)

    def _box_center(self, box: list[float]) -> tuple[float, float]:
        return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

    def _point_inside_box(self, point: tuple[float, float], box: list[float]) -> bool:
        return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]

    def _unannotated_features(
        self,
        annotations: list[JsonObject],
        feature_candidates: list[JsonObject],
    ) -> list[JsonObject]:
        annotated_feature_ids = {
            str(annotation.get("feature_id"))
            for annotation in annotations
            if annotation.get("feature_id")
        }
        result: list[JsonObject] = []
        for feature in feature_candidates:
            feature_id = feature.get("id")
            if not isinstance(feature_id, str) or not feature_id:
                continue
            if feature_id not in annotated_feature_ids:
                result.append(feature)
        return result

    def _duplicates(self, values: Iterable[str]) -> list[str]:
        counter = Counter(value for value in values if isinstance(value, str) and value)
        return sorted(value for value, count in counter.items() if count > 1)

    def _annotation_review_status(self, findings: list[JsonObject]) -> str:
        severities = {finding.get("severity") for finding in findings}
        if "ERROR" in severities:
            return "error"
        if "WARN" in severities:
            return "warning"
        return "passed"

    def _annotation_finding(
        self,
        severity: str,
        code: str,
        message: str,
        recommendation: str,
        details: JsonObject | None = None,
    ) -> JsonObject:
        finding: JsonObject = {
            "severity": severity,
            "code": code,
            "message": message,
            "recommendation": recommendation,
        }
        if details:
            finding["details"] = details
        return finding

    def _ensure_annotation_layer(self, document: Any) -> None:
        if not document.layers.has_entry(DIMENSION_LAYER):
            document.layers.add(DIMENSION_LAYER, color=1)

    def _ensure_annotation_styles(self, document: Any) -> None:
        self._ensure_dimstyle(document, ANNOTATION_DIMSTYLE)
        self._ensure_dimstyle(document, ANNOTATION_RADIUS_DIMSTYLE)

    def _ensure_dimstyle(self, document: Any, name: str) -> None:
        if not document.dimstyles.has_entry(name):
            document.dimstyles.new(name)
        dimstyle = document.dimstyles.get(name)
        dimstyle.dxf.dimtxt = ANNOTATION_TEXT_HEIGHT_MM
        dimstyle.dxf.dimasz = ANNOTATION_ARROW_SIZE_MM
        dimstyle.dxf.dimgap = ANNOTATION_DIM_GAP_MM
        dimstyle.dxf.dimexo = 1.0
        dimstyle.dxf.dimexe = 1.5

    def _sheet_layout_from_info(self, sheet_info: JsonObject | None) -> JsonObject:
        sheet_width = SHEET_WIDTH_MM
        sheet_height = SHEET_HEIGHT_MM
        source = "fallback_a3"
        if isinstance(sheet_info, dict):
            sheet_size = self._float_values(sheet_info.get("sheet_size_m"), 2)
            if sheet_size is not None and sheet_size[0] > 0 and sheet_size[1] > 0:
                sheet_width = sheet_size[0] * 1000
                sheet_height = sheet_size[1] * 1000
                source = "solidworks_sheet_info"

        safe_area = [
            SHEET_SAFE_MARGIN_MM,
            SHEET_SAFE_MARGIN_MM,
            max(SHEET_SAFE_MARGIN_MM, sheet_width - SHEET_SAFE_MARGIN_MM),
            max(SHEET_SAFE_MARGIN_MM, sheet_height - SHEET_SAFE_MARGIN_MM),
        ]

        title_block_box = [
            max(0.0, sheet_width - min(TITLE_BLOCK_WIDTH_MM, sheet_width)),
            0.0,
            sheet_width,
            min(TITLE_BLOCK_HEIGHT_MM, sheet_height),
        ]
        title_source = "estimated_title_block"
        if isinstance(sheet_info, dict):
            title_block_zone = self._float_values(sheet_info.get("title_block_zone_m"), 4)
            if title_block_zone is not None:
                title_block_box = [value * 1000 for value in title_block_zone]
                title_source = "solidworks_title_block"

        return {
            "source": source,
            "sheet_bounds": [
                0.0,
                0.0,
                round(sheet_width, 3),
                round(sheet_height, 3),
            ],
            "safe_area": [round(value, 3) for value in safe_area],
            "restricted_boxes": [
                {
                    "kind": "title_block",
                    "source": title_source,
                    "box": [round(value, 3) for value in title_block_box],
                }
            ],
        }

    def _float_values(self, value: object, length: int) -> list[float] | None:
        if not isinstance(value, list) or len(value) < length:
            return None
        result: list[float] = []
        for item in value[:length]:
            converted = self._float_value(item)
            if converted is None:
                return None
            result.append(converted)
        return result

    def _resolve_view_regions(
        self,
        view_outlines_m: list[JsonObject] | None,
    ) -> list[JsonObject]:
        regions: list[JsonObject] = []
        for item in view_outlines_m or []:
            outline = item.get("outline_m")
            if not isinstance(outline, list) or len(outline) != 4:
                continue
            try:
                min_x, min_y, max_x, max_y = [float(value) * 1000 for value in outline]
            except (TypeError, ValueError):
                continue
            regions.append(
                {
                    "view": item.get("view", "unknown"),
                    "bounds": [min_x, min_y, max_x, max_y],
                }
            )
        return regions

    def _entities_in_region(self, modelspace: Any, region: JsonObject) -> list[Any]:
        region_bounds = region.get("bounds")
        if not isinstance(region_bounds, list) or len(region_bounds) != 4:
            return []
        entities: list[Any] = []
        for entity in modelspace:
            if entity.dxftype() in {"DIMENSION", "MTEXT", "TEXT"}:
                continue
            bounds = self._entity_bounds(entity)
            if bounds and self._bounds_center_inside(bounds, region_bounds):
                entities.append(entity)
        return entities

    def _combined_bounds(self, entities: list[Any]) -> list[float] | None:
        entity_bounds = [bounds for entity in entities if (bounds := self._entity_bounds(entity))]
        if not entity_bounds:
            return None
        return [
            min(bounds[0] for bounds in entity_bounds),
            min(bounds[1] for bounds in entity_bounds),
            max(bounds[2] for bounds in entity_bounds),
            max(bounds[3] for bounds in entity_bounds),
        ]

    def _entity_bounds(self, entity: Any) -> list[float] | None:
        entity_type = entity.dxftype()
        if entity_type == "LINE":
            start = entity.dxf.start
            end = entity.dxf.end
            return [
                min(float(start.x), float(end.x)),
                min(float(start.y), float(end.y)),
                max(float(start.x), float(end.x)),
                max(float(start.y), float(end.y)),
            ]
        if entity_type in {"ARC", "CIRCLE"}:
            center = entity.dxf.center
            radius = float(entity.dxf.radius)
            return [
                float(center.x) - radius,
                float(center.y) - radius,
                float(center.x) + radius,
                float(center.y) + radius,
            ]
        return None

    def _bounds_center_inside(self, bounds: list[float], region_bounds: list[float]) -> bool:
        center_x = (bounds[0] + bounds[2]) / 2
        center_y = (bounds[1] + bounds[3]) / 2
        return (
            region_bounds[0] - ANNOTATION_MARGIN_MM
            <= center_x
            <= region_bounds[2] + ANNOTATION_MARGIN_MM
            and region_bounds[1] - ANNOTATION_MARGIN_MM
            <= center_y
            <= region_bounds[3] + ANNOTATION_MARGIN_MM
        )

    def _looks_like_circular_view(
        self,
        bounds: list[float],
        circular_feature: JsonObject | None,
    ) -> bool:
        if not circular_feature:
            return False
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        larger = max(width, height)
        if larger <= MIN_DIMENSION_SIZE_MM:
            return False
        diameter = float(circular_feature["radius_mm"]) * 2
        return abs(width - height) / larger <= 0.2 and diameter >= larger * 0.75

    def _circular_features(self, entities: list[Any]) -> list[JsonObject]:
        features: list[JsonObject] = []
        for entity in entities:
            if entity.dxftype() not in {"ARC", "CIRCLE"}:
                continue
            center = entity.dxf.center
            feature = {
                "center": [round(float(center.x), 3), round(float(center.y), 3)],
                "radius_mm": round(float(entity.dxf.radius), 3),
                "entity_type": entity.dxftype(),
            }
            if not self._has_matching_circle_feature(features, feature):
                features.append(feature)
        return sorted(features, key=lambda feature: float(feature["radius_mm"]), reverse=True)

    def _has_matching_circle_feature(
        self,
        features: list[JsonObject],
        candidate: JsonObject,
    ) -> bool:
        candidate_center = candidate["center"]
        candidate_radius = float(candidate["radius_mm"])
        if not isinstance(candidate_center, list) or len(candidate_center) != 2:
            return False
        for feature in features:
            center = feature.get("center")
            if not isinstance(center, list) or len(center) != 2:
                continue
            if (
                abs(float(center[0]) - float(candidate_center[0])) <= FEATURE_CLUSTER_TOLERANCE_MM
                and abs(float(center[1]) - float(candidate_center[1]))
                <= FEATURE_CLUSTER_TOLERANCE_MM
                and abs(float(feature["radius_mm"]) - candidate_radius)
                <= FEATURE_CLUSTER_TOLERANCE_MM
            ):
                return True
        return False

    def _view_feature_candidates(
        self,
        view_name: str,
        entities: list[Any],
        bounds: list[float],
        circular_features: list[JsonObject],
    ) -> list[JsonObject]:
        features: list[JsonObject] = []
        if circular_features and self._looks_like_circular_view(bounds, circular_features[0]):
            features.extend(self._circular_view_features(view_name, circular_features))
        else:
            features.extend(self._step_length_features(view_name, entities, bounds))
        return features

    def _circular_view_features(
        self,
        view_name: str,
        circular_features: list[JsonObject],
    ) -> list[JsonObject]:
        if not circular_features:
            return []

        outer = circular_features[0]
        features = [
            self._diameter_feature(
                view_name,
                "outer_diameter",
                "外径",
                outer,
                "dxf_end_face_circle",
            )
        ]
        outer_center = outer.get("center")
        for index, feature in enumerate(circular_features[1:], start=1):
            if not self._same_center(outer_center, feature.get("center")):
                continue
            label = "内孔直径" if index == 1 else "同心圆直径"
            feature_type = "bore_diameter" if index == 1 else "concentric_diameter"
            features.append(
                self._diameter_feature(
                    view_name,
                    feature_type if index == 1 else f"{feature_type}_{index}",
                    label,
                    feature,
                    "dxf_concentric_circle",
                )
            )
        return features

    def _diameter_feature(
        self,
        view_name: str,
        feature_type: str,
        label: str,
        circular_feature: JsonObject,
        source: str,
    ) -> JsonObject:
        radius = float(circular_feature["radius_mm"])
        return {
            "id": f"{view_name}_{feature_type}",
            "view": view_name,
            "feature_type": feature_type,
            "label": label,
            "kind": "diameter",
            "center": circular_feature["center"],
            "radius_mm": round(radius, 3),
            "value_mm": round(radius * 2, 3),
            "source": source,
        }

    def _same_center(self, first: Any, second: Any) -> bool:
        if not isinstance(first, list) or not isinstance(second, list):
            return False
        if len(first) != 2 or len(second) != 2:
            return False
        return (
            abs(float(first[0]) - float(second[0])) <= FEATURE_CLUSTER_TOLERANCE_MM
            and abs(float(first[1]) - float(second[1])) <= FEATURE_CLUSTER_TOLERANCE_MM
        )

    def _step_length_features(
        self,
        view_name: str,
        entities: list[Any],
        bounds: list[float],
    ) -> list[JsonObject]:
        x_positions = self._vertical_edge_positions(entities)
        if len(x_positions) <= 2:
            return []

        features: list[JsonObject] = []
        min_y, max_y = bounds[1], bounds[3]
        for index, (start_x, end_x) in enumerate(
            zip(x_positions, x_positions[1:], strict=False),
            start=1,
        ):
            length = end_x - start_x
            if length <= MIN_DIMENSION_SIZE_MM:
                continue
            features.append(
                {
                    "id": f"{view_name}_step_length_{index}",
                    "view": view_name,
                    "feature_type": "step_length",
                    "label": f"台阶长度 {index}",
                    "kind": "linear",
                    "start": [round(start_x, 3), round(max_y, 3)],
                    "end": [round(end_x, 3), round(max_y, 3)],
                    "value_mm": round(length, 3),
                    "height_span_mm": round(max_y - min_y, 3),
                    "source": "dxf_vertical_edges",
                }
            )
            if len(features) >= MAX_STEP_DIMENSIONS_PER_VIEW:
                break
        return features

    def _vertical_edge_positions(self, entities: list[Any]) -> list[float]:
        raw_positions: list[float] = []
        for entity in entities:
            if entity.dxftype() != "LINE":
                continue
            start = entity.dxf.start
            end = entity.dxf.end
            dx = abs(float(start.x) - float(end.x))
            dy = abs(float(start.y) - float(end.y))
            if dx <= FEATURE_CLUSTER_TOLERANCE_MM and dy > MIN_DIMENSION_SIZE_MM:
                raw_positions.append(float(start.x))
        if len(raw_positions) <= 1:
            return []

        raw_positions.sort()
        clustered: list[float] = []
        for position in raw_positions:
            if not clustered or abs(position - clustered[-1]) > FEATURE_CLUSTER_TOLERANCE_MM:
                clustered.append(position)
            else:
                clustered[-1] = (clustered[-1] + position) / 2
        return clustered

    def _add_primary_linear_dimensions(
        self,
        modelspace: Any,
        view_name: str,
        bounds: list[float],
        region: JsonObject,
        layout: JsonObject | None = None,
    ) -> list[JsonObject]:
        min_x, min_y, max_x, max_y = bounds
        width = max_x - min_x
        height = max_y - min_y
        if width <= MIN_DIMENSION_SIZE_MM or height <= MIN_DIMENSION_SIZE_MM:
            return []

        offset = max(7.0, min(max(width, height) * 0.18, 14.0))
        region_bounds = region.get("bounds")
        lower_limit = 5.0
        if isinstance(region_bounds, list) and len(region_bounds) == 4:
            lower_limit = max(5.0, float(region_bounds[1]) - 12.0)
        base_y = min_y - offset
        if base_y < lower_limit:
            base_y = max_y + offset

        return [
            self._add_linear_dimension(
                modelspace,
                view_name,
                f"{view_name}_overall_length",
                "overall_length",
                (min_x, base_y),
                (min_x, min_y),
                (max_x, min_y),
                0,
                width,
                "dxf_primary_view_bounds",
                "medium",
                layout=layout,
            )
        ]

    def _add_model_driven_dimensions(
        self,
        modelspace: Any,
        view_contexts: list[JsonObject],
        model_manifest: JsonObject | None,
    ) -> list[JsonObject]:
        if not self._has_parametric_model_dimensions(model_manifest):
            return []
        model_size = self._model_size_mm(model_manifest)
        if model_size is None:
            return []

        contexts = {str(context.get("view", "unknown")): context for context in view_contexts}
        top = contexts.get("top")
        front = contexts.get("front")
        annotations: list[JsonObject] = []

        if top:
            annotations.extend(self._add_model_top_view_dimensions(modelspace, top, model_size))
            annotations.extend(
                self._add_model_hole_dimensions(modelspace, top, model_manifest, model_size)
            )
        if front:
            annotations.extend(self._add_model_front_view_dimensions(modelspace, front, model_size))
        return annotations

    def _has_parametric_model_dimensions(self, model_manifest: JsonObject | None) -> bool:
        if not isinstance(model_manifest, dict):
            return False
        if model_manifest.get("model_source_quality") != "parametric_dimensions_available":
            return False
        return int(model_manifest.get("dimension_count", 0) or 0) > 0

    def _model_size_mm(self, model_manifest: JsonObject | None) -> list[float] | None:
        if not isinstance(model_manifest, dict):
            return None
        bounding_box = model_manifest.get("bounding_box")
        if not isinstance(bounding_box, dict):
            return None
        size_mm = bounding_box.get("size_mm")
        if not isinstance(size_mm, list) or len(size_mm) < 3:
            return None
        try:
            values = [float(value) for value in size_mm[:3]]
        except (TypeError, ValueError):
            return None
        if any(value <= MIN_DIMENSION_SIZE_MM for value in values):
            return None
        return values

    def _add_model_top_view_dimensions(
        self,
        modelspace: Any,
        context: JsonObject,
        model_size: list[float],
    ) -> list[JsonObject]:
        bounds = self._context_bounds(context)
        if bounds is None:
            return []
        min_x, min_y, max_x, max_y = bounds
        width = max_x - min_x
        height = max_y - min_y
        offset = max(8.0, min(max(width, height) * 0.12, 16.0))
        layout = self._layout_from_context(context)
        return [
            self._add_linear_dimension(
                modelspace,
                "top",
                "top_overall_length",
                "overall_length",
                (min_x, min_y - offset),
                (min_x, min_y),
                (max_x, min_y),
                0,
                model_size[0],
                "solidworks_bounding_box",
                "high",
                layout=layout,
            ),
            self._add_linear_dimension(
                modelspace,
                "top",
                "top_overall_width",
                "overall_width",
                (max_x + offset, min_y),
                (max_x, min_y),
                (max_x, max_y),
                90,
                model_size[2],
                "solidworks_bounding_box",
                "high",
                layout=layout,
            ),
        ]

    def _add_model_front_view_dimensions(
        self,
        modelspace: Any,
        context: JsonObject,
        model_size: list[float],
    ) -> list[JsonObject]:
        bounds = self._context_bounds(context)
        if bounds is None:
            return []
        _min_x, min_y, max_x, max_y = bounds
        height = max_y - min_y
        offset = max(7.0, min(height * 1.2, 12.0))
        layout = self._layout_from_context(context)
        return [
            self._add_linear_dimension(
                modelspace,
                "front",
                "front_thickness",
                "thickness",
                (max_x + offset, min_y),
                (max_x, min_y),
                (max_x, max_y),
                90,
                model_size[1],
                "solidworks_bounding_box",
                "high",
                layout=layout,
            )
        ]

    def _add_model_hole_dimensions(
        self,
        modelspace: Any,
        context: JsonObject,
        model_manifest: JsonObject | None,
        model_size: list[float],
    ) -> list[JsonObject]:
        bounds = self._context_bounds(context)
        if bounds is None:
            return []
        scale = self._context_model_scale(bounds, model_size[0], model_size[2])
        if scale is None:
            return []

        circular_features = context.get("circular_features")
        if not isinstance(circular_features, list):
            return []
        annotations: list[JsonObject] = []
        layout = self._layout_from_context(context)
        central_circle = self._largest_circle(circular_features)
        if central_circle:
            central_annotation = self._add_model_diameter_dimension(
                modelspace,
                "top",
                "top_center_cutout_diameter",
                "center_cutout_diameter",
                central_circle,
                "%%c" + self._format_mm(float(central_circle["radius_mm"]) * 2 / scale),
                "solidworks_model_circle",
                "high",
                layout=layout,
            )
            if central_annotation:
                annotations.append(central_annotation)

        hole_info = self._hole_wizard_info(model_manifest)
        threaded_holes = self._threaded_hole_circles(circular_features, scale, hole_info)
        if not threaded_holes:
            return [annotation for annotation in annotations if annotation]

        thread_text = self._thread_callout_text(len(threaded_holes), hole_info)
        thread_annotation = self._add_thread_hole_callout(
            modelspace,
            threaded_holes,
            bounds,
            thread_text,
            layout,
        )
        if thread_annotation:
            annotations.append(thread_annotation)
        annotations.extend(
            self._add_hole_edge_dimensions(
                modelspace,
                threaded_holes,
                scale,
                bounds,
                layout,
            )
        )
        annotations.extend(
            self._add_hole_pitch_dimensions(
                modelspace,
                threaded_holes,
                scale,
                bounds,
                layout,
            )
        )
        annotations.extend(
            self._add_slot_dimensions(modelspace, circular_features, scale, bounds, layout)
        )
        return [annotation for annotation in annotations if annotation]

    def _context_bounds(self, context: JsonObject) -> list[float] | None:
        bounds = context.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            return None
        try:
            return [float(value) for value in bounds]
        except (TypeError, ValueError):
            return None

    def _context_model_scale(
        self,
        bounds: list[float],
        model_width_mm: float,
        model_height_mm: float,
    ) -> float | None:
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        if model_width_mm <= 0 or model_height_mm <= 0:
            return None
        x_scale = width / model_width_mm
        y_scale = height / model_height_mm
        if x_scale <= 0 or y_scale <= 0:
            return None
        if abs(x_scale - y_scale) / max(x_scale, y_scale) > 0.12:
            return None
        return (x_scale + y_scale) / 2

    def _largest_circle(self, circular_features: list[JsonObject]) -> JsonObject | None:
        circles = [
            feature
            for feature in circular_features
            if feature.get("entity_type") == "CIRCLE"
            and isinstance(feature.get("radius_mm"), int | float)
        ]
        if not circles:
            return None
        return max(circles, key=lambda feature: float(feature["radius_mm"]))

    def _hole_wizard_info(self, model_manifest: JsonObject | None) -> JsonObject:
        info: JsonObject = {}
        if not isinstance(model_manifest, dict):
            return info
        dimensions = model_manifest.get("dimensions")
        if not isinstance(dimensions, list):
            return info
        for dimension in dimensions:
            if not isinstance(dimension, dict):
                continue
            name = str(dimension.get("name", ""))
            feature = str(dimension.get("feature", ""))
            value = self._float_value(dimension.get("value_mm"))
            if value is None:
                continue
            if "钻头直径" in name:
                info["drill_diameter_mm"] = value
            if "钻头深度" in name:
                info["drill_depth_mm"] = value
            thread_match = re.search(r"M\s*(\d+(?:\.\d+)?)", feature, flags=re.IGNORECASE)
            if thread_match:
                info["thread_size_mm"] = float(thread_match.group(1))
        return info

    def _threaded_hole_circles(
        self,
        circular_features: list[JsonObject],
        scale: float,
        hole_info: JsonObject,
    ) -> list[JsonObject]:
        drill_diameter = self._float_value(hole_info.get("drill_diameter_mm"))
        expected_radius = drill_diameter * scale / 2 if drill_diameter else None
        circles = [
            feature
            for feature in circular_features
            if feature.get("entity_type") == "CIRCLE"
            and isinstance(feature.get("center"), list)
            and isinstance(feature.get("radius_mm"), int | float)
        ]
        if expected_radius:
            matches = [
                circle
                for circle in circles
                if abs(float(circle["radius_mm"]) - expected_radius)
                <= max(0.5, expected_radius * 0.2)
            ]
            if matches:
                return sorted(matches, key=lambda item: (item["center"][1], item["center"][0]))
        if not circles:
            return []
        largest_radius = max(float(circle["radius_mm"]) for circle in circles)
        small_circles = [
            circle for circle in circles if float(circle["radius_mm"]) <= largest_radius * 0.25
        ]
        return sorted(small_circles, key=lambda item: (item["center"][1], item["center"][0]))

    def _thread_callout_text(self, hole_count: int, hole_info: JsonObject) -> str:
        thread_size = self._float_value(hole_info.get("thread_size_mm"))
        if thread_size:
            return f"{hole_count}-M{self._format_mm(thread_size)}"
        return f"{hole_count}-M?"

    def _add_hole_pitch_dimensions(
        self,
        modelspace: Any,
        holes: list[JsonObject],
        scale: float,
        bounds: list[float],
        layout: JsonObject | None = None,
    ) -> list[JsonObject]:
        if len(holes) < 4:
            return []
        centers = [
            [float(hole["center"][0]), float(hole["center"][1])]
            for hole in holes
            if isinstance(hole.get("center"), list) and len(hole["center"]) == 2
        ]
        if len(centers) < 4:
            return []

        min_x, min_y, _max_x, _max_y = bounds
        bottom_row = sorted(centers, key=lambda center: (center[1], center[0]))[:2]
        left_column = sorted(centers, key=lambda center: (center[0], center[1]))[:2]
        bottom_row = sorted(bottom_row, key=lambda center: center[0])
        left_column = sorted(left_column, key=lambda center: center[1])
        annotations: list[JsonObject] = []

        if len(bottom_row) == 2:
            pitch = abs(bottom_row[1][0] - bottom_row[0][0]) / scale
            annotations.append(
                self._add_linear_dimension(
                    modelspace,
                    "top",
                    "top_thread_hole_pitch_x",
                    "thread_hole_pitch_x",
                    (bottom_row[0][0], min_y - 24.0),
                    (bottom_row[0][0], bottom_row[0][1]),
                    (bottom_row[1][0], bottom_row[1][1]),
                    0,
                    pitch,
                    "solidworks_hole_pattern",
                    "medium",
                    layout=layout,
                )
            )
        if len(left_column) == 2:
            pitch = abs(left_column[1][1] - left_column[0][1]) / scale
            annotations.append(
                self._add_linear_dimension(
                    modelspace,
                    "top",
                    "top_thread_hole_pitch_y",
                    "thread_hole_pitch_y",
                    (min_x - 16.0, left_column[0][1]),
                    (left_column[0][0], left_column[0][1]),
                    (left_column[1][0], left_column[1][1]),
                    90,
                    pitch,
                    "solidworks_hole_pattern",
                    "medium",
                    layout=layout,
                )
            )
        return annotations

    def _add_hole_edge_dimensions(
        self,
        modelspace: Any,
        holes: list[JsonObject],
        scale: float,
        bounds: list[float],
        layout: JsonObject | None = None,
    ) -> list[JsonObject]:
        centers = self._circle_centers(holes)
        if not centers or scale <= 0:
            return []

        min_x, min_y, _max_x, _max_y = bounds
        x_values = self._cluster_axis_values([center[0] for center in centers])
        y_values = self._cluster_axis_values([center[1] for center in centers])
        if not x_values or not y_values:
            return []

        left_x = min(x_values)
        lower_y = min(y_values)
        edge_x = abs(left_x - min_x) / scale
        edge_y = abs(lower_y - min_y) / scale
        annotations: list[JsonObject] = []

        if edge_x > MIN_DIMENSION_SIZE_MM:
            annotations.append(
                self._add_linear_dimension(
                    modelspace,
                    "top",
                    "top_thread_hole_edge_x",
                    "thread_hole_edge_x",
                    (min_x, min_y - 8.0),
                    (min_x, lower_y),
                    (left_x, lower_y),
                    0,
                    edge_x,
                    "solidworks_hole_datum",
                    "medium",
                    layout=layout,
                )
            )
        if edge_y > MIN_DIMENSION_SIZE_MM:
            annotations.append(
                self._add_linear_dimension(
                    modelspace,
                    "top",
                    "top_thread_hole_edge_y",
                    "thread_hole_edge_y",
                    (min_x - 8.0, min_y),
                    (min_x, min_y),
                    (min_x, lower_y),
                    90,
                    edge_y,
                    "solidworks_hole_datum",
                    "medium",
                    layout=layout,
                )
            )
        return annotations

    def _add_slot_dimensions(
        self,
        modelspace: Any,
        circular_features: list[JsonObject],
        scale: float,
        bounds: list[float],
        layout: JsonObject | None = None,
    ) -> list[JsonObject]:
        slots = self._slot_features(circular_features, scale)
        if not slots:
            return []

        slot = slots[0]
        min_x, _min_y, _max_x, max_y = slot["bounds"]
        width_mm = float(slot["width_mm"])
        length_mm = float(slot["length_mm"])
        annotations = self._add_slot_position_dimensions(
            modelspace,
            slots,
            scale,
            bounds,
            layout,
        )
        slot_text = (
            f"{len(slots)}-\u957f\u5706\u5b54 "
            f"{self._format_mm(width_mm)}x{self._format_mm(length_mm)}"
        )
        slot_center = slot["center"]
        annotation = self._add_note_callout(
            modelspace,
            "top",
            "top_slot_callout",
            "slot_callout",
            slot_text,
            (float(slot_center[0]), float(slot_center[1])),
            (min_x, max_y + 14.0),
            "solidworks_slot_geometry",
            "medium",
            value_mm=length_mm,
            layout=layout,
            candidate_points=self._slot_callout_candidates(slot, bounds),
        )
        annotations.append(annotation)
        return annotations

    def _slot_callout_candidates(
        self,
        slot: JsonObject,
        bounds: list[float],
    ) -> list[tuple[float, float]]:
        min_x, _min_y, max_x, max_y = [float(value) for value in slot["bounds"]]
        view_min_x, view_min_y, view_max_x, view_max_y = bounds
        return [
            (min_x, view_max_y + 14.0),
            (view_min_x, view_max_y + 22.0),
            (max_x + 8.0, view_max_y + 14.0),
            (view_max_x + 8.0, max_y),
            (view_min_x, view_min_y - 8.0),
        ]

    def _add_slot_position_dimensions(
        self,
        modelspace: Any,
        slots: list[JsonObject],
        scale: float,
        bounds: list[float],
        layout: JsonObject | None = None,
    ) -> list[JsonObject]:
        centers = self._slot_centers(slots)
        if len(centers) < 2 or scale <= 0:
            return []

        min_x, min_y, _max_x, max_y = bounds
        x_values = self._cluster_axis_values([center[0] for center in centers])
        y_values = self._cluster_axis_values([center[1] for center in centers])
        annotations: list[JsonObject] = []

        if x_values and y_values:
            left_x = min(x_values)
            lower_y = min(y_values)
            edge_x = abs(left_x - min_x) / scale
            edge_y = abs(lower_y - min_y) / scale
            if edge_x > MIN_DIMENSION_SIZE_MM:
                annotations.append(
                    self._add_linear_dimension(
                        modelspace,
                        "top",
                        "top_slot_edge_x",
                        "slot_edge_x",
                        (min_x, max_y + 20.0),
                        (min_x, lower_y),
                        (left_x, lower_y),
                        0,
                        edge_x,
                        "solidworks_slot_datum",
                        "medium",
                        layout=layout,
                    )
                )
            if edge_y > MIN_DIMENSION_SIZE_MM:
                annotations.append(
                    self._add_linear_dimension(
                        modelspace,
                        "top",
                        "top_slot_edge_y",
                        "slot_edge_y",
                        (min_x - 40.0, min_y),
                        (min_x, min_y),
                        (min_x, lower_y),
                        90,
                        edge_y,
                        "solidworks_slot_datum",
                        "medium",
                        layout=layout,
                    )
                )

        if len(x_values) >= 2:
            left_x = min(x_values)
            right_x = max(x_values)
            reference_y = min(y_values) if y_values else min(center[1] for center in centers)
            pitch_x = abs(right_x - left_x) / scale
            if pitch_x > MIN_DIMENSION_SIZE_MM:
                annotations.append(
                    self._add_linear_dimension(
                        modelspace,
                        "top",
                        "top_slot_pitch_x",
                        "slot_pitch_x",
                        (left_x, max_y + 28.0),
                        (left_x, reference_y),
                        (right_x, reference_y),
                        0,
                        pitch_x,
                        "solidworks_slot_pattern",
                        "medium",
                        layout=layout,
                    )
                )

        if len(y_values) >= 2:
            lower_y = min(y_values)
            upper_y = max(y_values)
            reference_x = min(x_values) if x_values else min(center[0] for center in centers)
            pitch_y = abs(upper_y - lower_y) / scale
            if pitch_y > MIN_DIMENSION_SIZE_MM:
                annotations.append(
                    self._add_linear_dimension(
                        modelspace,
                        "top",
                        "top_slot_pitch_y",
                        "slot_pitch_y",
                        (min_x - 28.0, lower_y),
                        (reference_x, lower_y),
                        (reference_x, upper_y),
                        90,
                        pitch_y,
                        "solidworks_slot_pattern",
                        "medium",
                        layout=layout,
                    )
                )
        return annotations

    def _circle_centers(self, circles: list[JsonObject]) -> list[tuple[float, float]]:
        centers: list[tuple[float, float]] = []
        for circle in circles:
            center = circle.get("center")
            if not isinstance(center, list) or len(center) != 2:
                continue
            centers.append((float(center[0]), float(center[1])))
        return centers

    def _slot_centers(self, slots: list[JsonObject]) -> list[tuple[float, float]]:
        centers: list[tuple[float, float]] = []
        for slot in slots:
            center = slot.get("center")
            if not isinstance(center, list) or len(center) != 2:
                continue
            centers.append((float(center[0]), float(center[1])))
        return centers

    def _cluster_axis_values(self, values: list[float]) -> list[float]:
        if not values:
            return []
        clustered: list[float] = []
        for value in sorted(values):
            if not clustered or abs(value - clustered[-1]) > FEATURE_CLUSTER_TOLERANCE_MM:
                clustered.append(value)
            else:
                clustered[-1] = (clustered[-1] + value) / 2
        return clustered

    def _slot_features(
        self,
        circular_features: list[JsonObject],
        scale: float,
    ) -> list[JsonObject]:
        arcs = [
            feature
            for feature in circular_features
            if feature.get("entity_type") == "ARC"
            and isinstance(feature.get("center"), list)
            and len(feature["center"]) == 2
            and isinstance(feature.get("radius_mm"), int | float)
        ]
        if not arcs:
            return []

        largest_arc_radius = max(float(arc["radius_mm"]) for arc in arcs)
        grouped: dict[tuple[int, int], list[JsonObject]] = {}
        for arc in arcs:
            radius = float(arc["radius_mm"])
            if abs(radius - largest_arc_radius) > max(0.3, largest_arc_radius * 0.08):
                continue
            center = arc["center"]
            key = (round(float(center[0]) * 10), round(radius * 10))
            grouped.setdefault(key, []).append(arc)

        slots: list[JsonObject] = []
        for group in grouped.values():
            ordered = sorted(group, key=lambda item: float(item["center"][1]))
            for first, second in zip(ordered, ordered[1:], strict=False):
                first_center = first["center"]
                second_center = second["center"]
                center_gap = abs(float(second_center[1]) - float(first_center[1]))
                radius = float(first["radius_mm"])
                if center_gap <= MIN_DIMENSION_SIZE_MM or center_gap > radius * 2.5:
                    continue
                slots.append(
                    {
                        "center": [
                            round(float(first_center[0]), 3),
                            round(
                                (float(first_center[1]) + float(second_center[1])) / 2,
                                3,
                            ),
                        ],
                        "radius": radius,
                        "bounds": [
                            round(float(first_center[0]) - radius, 3),
                            round(
                                min(float(first_center[1]), float(second_center[1])) - radius,
                                3,
                            ),
                            round(float(first_center[0]) + radius, 3),
                            round(
                                max(float(first_center[1]), float(second_center[1])) + radius,
                                3,
                            ),
                        ],
                        "width_mm": round((radius * 2) / scale, 3),
                        "length_mm": round((center_gap + radius * 2) / scale, 3),
                        "source": "dxf_slot_arcs",
                    }
                )
        return sorted(slots, key=lambda item: (item["center"][1], item["center"][0]))

    def _add_linear_dimension(
        self,
        modelspace: Any,
        view_name: str,
        annotation_id: str,
        label: str,
        base: tuple[float, float],
        p1: tuple[float, float],
        p2: tuple[float, float],
        angle: int,
        value_mm: float,
        source: str,
        confidence: str,
        override_text: str | None = None,
        layout: JsonObject | None = None,
    ) -> JsonObject:
        text = override_text or self._format_mm(value_mm)
        adjusted_base, adjustment = self._adjust_linear_dimension_base_for_layout(
            layout,
            text,
            base,
            p1,
            p2,
            angle,
        )
        dimension = modelspace.add_linear_dim(
            base=adjusted_base,
            p1=p1,
            p2=p2,
            angle=angle,
            dimstyle=ANNOTATION_DIMSTYLE,
            dxfattribs={"layer": DIMENSION_LAYER},
        )
        dimension.dimension.dxf.text = text
        dimension.render()
        text_point = self._linear_dimension_text_point(adjusted_base, p1, p2, angle)
        text_box = self._text_box_from_center(text, text_point)
        self._layout_add_box(layout, text_box, "dimension_text", annotation_id)
        constraint_sources = self._layout_constraint_sources(layout, text_box)
        annotation = {
            "id": annotation_id,
            "view": view_name,
            "kind": "linear",
            "label": label,
            "value_mm": round(value_mm, 3),
            "source": source,
            "confidence": confidence,
            "layout": {
                "strategy": adjustment.get("strategy", "dimension_base_estimate"),
                "text_point": [round(text_point[0], 3), round(text_point[1], 3)],
                "text_box": [round(value, 3) for value in text_box],
            },
        }
        if adjustment:
            annotation["layout"]["base_point"] = [
                round(adjusted_base[0], 3),
                round(adjusted_base[1], 3),
            ]
            annotation["layout"]["base_adjustment"] = adjustment
        if constraint_sources:
            annotation["layout"]["constraint_sources"] = constraint_sources
        if override_text:
            annotation["text"] = override_text
        return annotation

    def _adjust_linear_dimension_base_for_layout(
        self,
        layout: JsonObject | None,
        text: str,
        base: tuple[float, float],
        p1: tuple[float, float],
        p2: tuple[float, float],
        angle: int,
    ) -> tuple[tuple[float, float], JsonObject]:
        if not isinstance(layout, dict):
            return base, {}
        normalized_angle = angle % 180
        axis = "y" if normalized_angle == 0 else "x" if normalized_angle == 90 else ""
        if not axis:
            return base, {}

        initial_text_point = self._linear_dimension_text_point(base, p1, p2, angle)
        initial_box = self._text_box_from_center(text, initial_text_point)
        shift = self._layout_axis_shift_for_constraints(layout, initial_box, axis)
        if abs(shift) <= 0:
            return base, {}

        adjusted_base = (base[0], base[1] + shift) if axis == "y" else (base[0] + shift, base[1])
        adjusted_text_point = self._linear_dimension_text_point(adjusted_base, p1, p2, angle)
        adjusted_box = self._text_box_from_center(text, adjusted_text_point)
        remaining_sources = self._layout_constraint_sources(layout, adjusted_box)
        return adjusted_base, {
            "strategy": "dimension_base_safe_area_adjusted",
            "axis": axis,
            "shift_mm": round(shift, 3),
            "original_text_box": [round(value, 3) for value in initial_box],
            "remaining_constraint_sources": remaining_sources,
        }

    def _layout_axis_shift_for_constraints(
        self,
        layout: JsonObject,
        box: list[float],
        axis: str,
    ) -> float:
        shift = self._axis_shift_into_safe_area(layout, box, axis)
        shifted_box = self._shift_box(box, axis, shift)
        restriction_shift = self._axis_shift_out_of_restricted_boxes(layout, shifted_box, axis)
        shifted_box = self._shift_box(shifted_box, axis, restriction_shift)
        text_shift = self._axis_shift_out_of_text_boxes(layout, shifted_box, axis)
        return shift + restriction_shift + text_shift

    def _axis_shift_into_safe_area(
        self,
        layout: JsonObject,
        box: list[float],
        axis: str,
    ) -> float:
        safe_area = self._normalized_box(layout.get("safe_area"))
        if safe_area is None:
            return 0.0
        if axis == "y":
            if box[1] < safe_area[1]:
                return safe_area[1] - box[1]
            if box[3] > safe_area[3]:
                return safe_area[3] - box[3]
        if axis == "x":
            if box[0] < safe_area[0]:
                return safe_area[0] - box[0]
            if box[2] > safe_area[2]:
                return safe_area[2] - box[2]
        return 0.0

    def _axis_shift_out_of_restricted_boxes(
        self,
        layout: JsonObject,
        box: list[float],
        axis: str,
    ) -> float:
        restricted_boxes = layout.get("restricted_boxes")
        if not isinstance(restricted_boxes, list):
            return 0.0
        for item in restricted_boxes:
            if not isinstance(item, dict):
                continue
            restricted_box = self._normalized_box(item.get("box"))
            if restricted_box is None:
                continue
            if not self._boxes_overlap(box, restricted_box, LAYOUT_CLEARANCE_MM):
                continue
            if axis == "y":
                return restricted_box[3] + LAYOUT_CLEARANCE_MM - box[1]
            if axis == "x":
                return restricted_box[0] - LAYOUT_CLEARANCE_MM - box[2]
        return 0.0

    def _axis_shift_out_of_text_boxes(
        self,
        layout: JsonObject,
        box: list[float],
        axis: str,
    ) -> float:
        colliding_boxes = self._colliding_text_boxes(layout, box)
        if not colliding_boxes:
            return 0.0
        candidates: list[float] = []
        for other in colliding_boxes:
            if axis == "y":
                candidates.extend(
                    [
                        other[1] - LAYOUT_CLEARANCE_MM - box[3],
                        other[3] + LAYOUT_CLEARANCE_MM - box[1],
                    ]
                )
            else:
                candidates.extend(
                    [
                        other[0] - LAYOUT_CLEARANCE_MM - box[2],
                        other[2] + LAYOUT_CLEARANCE_MM - box[0],
                    ]
                )

        for shift in sorted(candidates, key=lambda value: abs(value)):
            candidate_box = self._shift_box(box, axis, shift)
            if self._layout_constraint_sources(layout, candidate_box):
                continue
            if self._colliding_text_boxes(layout, candidate_box):
                continue
            return shift
        return 0.0

    def _colliding_text_boxes(self, layout: JsonObject, box: list[float]) -> list[list[float]]:
        occupied_boxes = layout.get("occupied_boxes")
        if not isinstance(occupied_boxes, list):
            return []
        result: list[list[float]] = []
        for item in occupied_boxes:
            if not isinstance(item, dict):
                continue
            if item.get("kind") not in {"dimension_text", "annotation_text"}:
                continue
            other = self._normalized_box(item.get("box"))
            if other is None:
                continue
            if self._boxes_overlap(box, other, LAYOUT_CLEARANCE_MM):
                result.append(other)
        return result

    def _shift_box(self, box: list[float], axis: str, shift: float) -> list[float]:
        if axis == "y":
            return [box[0], box[1] + shift, box[2], box[3] + shift]
        if axis == "x":
            return [box[0] + shift, box[1], box[2] + shift, box[3]]
        return box

    def _linear_dimension_text_point(
        self,
        base: tuple[float, float],
        p1: tuple[float, float],
        p2: tuple[float, float],
        angle: int,
    ) -> tuple[float, float]:
        normalized_angle = angle % 180
        if normalized_angle == 0:
            return ((p1[0] + p2[0]) / 2, base[1])
        if normalized_angle == 90:
            return (base[0], (p1[1] + p2[1]) / 2)
        return base

    def _add_model_diameter_dimension(
        self,
        modelspace: Any,
        view_name: str,
        annotation_id: str,
        label: str,
        circle: JsonObject,
        display_text: str,
        source: str,
        confidence: str,
        layout: JsonObject | None = None,
    ) -> JsonObject | None:
        center = circle.get("center")
        radius = self._float_value(circle.get("radius_mm"))
        if not isinstance(center, list) or len(center) != 2 or radius is None:
            return None
        center_x, center_y = float(center[0]), float(center[1])
        location = (center_x + radius * 1.35, center_y + radius * 0.35)
        dimension = modelspace.add_diameter_dim(
            center=(center_x, center_y),
            radius=radius,
            angle=0,
            location=location,
            dimstyle=ANNOTATION_RADIUS_DIMSTYLE,
            dxfattribs={"layer": DIMENSION_LAYER},
        )
        dimension.dimension.dxf.text = display_text
        dimension.render()
        text_box = self._text_box_from_center(display_text, location)
        self._layout_add_box(layout, text_box, "dimension_text", annotation_id)
        return {
            "id": annotation_id,
            "view": view_name,
            "kind": "diameter",
            "label": label,
            "text": display_text,
            "source": source,
            "confidence": confidence,
            "layout": {
                "strategy": "diameter_location_estimate",
                "text_point": [round(location[0], 3), round(location[1], 3)],
                "text_box": [round(value, 3) for value in text_box],
            },
        }

    def _add_thread_hole_callout(
        self,
        modelspace: Any,
        threaded_holes: list[JsonObject],
        bounds: list[float],
        text: str,
        layout: JsonObject | None = None,
    ) -> JsonObject | None:
        target_hole = self._right_lower_circle(threaded_holes)
        if not target_hole:
            return None
        center = target_hole.get("center")
        radius = self._float_value(target_hole.get("radius_mm"))
        if not isinstance(center, list) or len(center) != 2 or radius is None:
            return None
        center_x, center_y = float(center[0]), float(center[1])
        anchor = self._circle_edge_anchor(
            (center_x, center_y), radius, (center_x + 1, center_y + 1)
        )
        candidates = self._thread_callout_candidates((center_x, center_y), bounds)
        return self._add_note_callout(
            modelspace,
            "top",
            "top_thread_hole_callout",
            "thread_hole",
            text,
            anchor,
            candidates[0],
            "solidworks_hole_wizard",
            "high",
            layout=layout,
            candidate_points=candidates,
        )

    def _thread_callout_candidates(
        self,
        center: tuple[float, float],
        bounds: list[float],
    ) -> list[tuple[float, float]]:
        center_x, center_y = center
        min_x, min_y, max_x, max_y = bounds
        return [
            (max_x + 8.0, center_y + 10.0),
            (max_x + 8.0, max_y + 6.0),
            (center_x + 10.0, max_y + 14.0),
            (max_x + 8.0, min_y + 18.0),
            (min_x, max_y + 14.0),
        ]

    def _right_lower_circle(self, circles: list[JsonObject]) -> JsonObject | None:
        valid_circles = [
            circle
            for circle in circles
            if isinstance(circle.get("center"), list) and len(circle["center"]) == 2
        ]
        if not valid_circles:
            return None
        return max(
            valid_circles,
            key=lambda circle: (
                float(circle["center"][0]),
                -float(circle["center"][1]),
            ),
        )

    def _circle_edge_anchor(
        self,
        center: tuple[float, float],
        radius: float,
        text_point: tuple[float, float],
    ) -> tuple[float, float]:
        center_x, center_y = center
        text_x, text_y = text_point
        delta_x = text_x - center_x
        delta_y = text_y - center_y
        distance = hypot(delta_x, delta_y)
        if distance <= 0:
            return center
        return (
            center_x + delta_x / distance * radius,
            center_y + delta_y / distance * radius,
        )

    def _add_note_callout(
        self,
        modelspace: Any,
        view_name: str,
        annotation_id: str,
        label: str,
        text: str,
        anchor: tuple[float, float],
        text_point: tuple[float, float],
        source: str,
        confidence: str,
        value_mm: float | None = None,
        layout: JsonObject | None = None,
        candidate_points: list[tuple[float, float]] | None = None,
    ) -> JsonObject:
        placement = self._layout_place_text(
            layout,
            annotation_id,
            text,
            candidate_points or [text_point],
        )
        placed_point = placement.get("text_point")
        if isinstance(placed_point, list) and len(placed_point) == 2:
            text_x, text_y = float(placed_point[0]), float(placed_point[1])
        else:
            text_x, text_y = text_point
        dogleg_x = text_x - CALLOUT_DOGLEG_MM if text_x >= anchor[0] else text_x + CALLOUT_DOGLEG_MM
        dogleg = (dogleg_x, text_y)
        text_point = (text_x, text_y)
        modelspace.add_line(anchor, dogleg, dxfattribs={"layer": DIMENSION_LAYER})
        modelspace.add_line(dogleg, text_point, dxfattribs={"layer": DIMENSION_LAYER})
        note = modelspace.add_mtext(
            text,
            dxfattribs={
                "layer": DIMENSION_LAYER,
                "char_height": ANNOTATION_TEXT_HEIGHT_MM,
            },
        )
        note.set_location(text_point, attachment_point=1)
        annotation: JsonObject = {
            "id": annotation_id,
            "view": view_name,
            "kind": "callout",
            "label": label,
            "text": text,
            "source": source,
            "confidence": confidence,
            "layout": placement,
        }
        if value_mm is not None:
            annotation["value_mm"] = round(value_mm, 3)
        return annotation

    def _float_value(self, value: object) -> float | None:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, int | float | str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    def _format_mm(self, value: float) -> str:
        rounded = round(value, 3)
        if rounded.is_integer():
            return str(int(rounded))
        return f"{rounded:.3f}".rstrip("0").rstrip(".")

    def _add_circular_dimensions(
        self,
        modelspace: Any,
        view_name: str,
        features: list[JsonObject],
    ) -> list[JsonObject]:
        annotations: list[JsonObject] = []
        circular_dimensions = [
            feature
            for feature in features
            if feature.get("kind") == "diameter"
            and feature.get("feature_type") in TRUSTED_CIRCULAR_DIMENSION_TYPES
        ]
        for index, feature in enumerate(circular_dimensions):
            annotation = self._add_diameter_dimension(modelspace, view_name, feature, index)
            if annotation:
                annotations.append(annotation)
        return annotations

    def _add_diameter_dimension(
        self,
        modelspace: Any,
        view_name: str,
        feature: JsonObject,
        index: int,
    ) -> JsonObject | None:
        center = feature.get("center")
        if not isinstance(center, list) or len(center) != 2:
            return None
        center_x, center_y = float(center[0]), float(center[1])
        radius = float(feature["radius_mm"])
        if radius <= MIN_DIMENSION_SIZE_MM:
            return None
        location_scale = 1.35 + index * 0.28
        dimension = modelspace.add_diameter_dim(
            center=(center_x, center_y),
            radius=radius,
            angle=0,
            location=(center_x + radius * location_scale, center_y + radius * 0.35),
            dimstyle=ANNOTATION_RADIUS_DIMSTYLE,
            dxfattribs={"layer": DIMENSION_LAYER},
        )
        dimension.render()
        return {
            "id": str(feature.get("id", f"{view_name}_diameter_{index + 1}")),
            "view": view_name,
            "kind": "diameter",
            "label": str(feature.get("feature_type", "diameter")),
            "value_mm": round(radius * 2, 3),
            "source": str(feature.get("source", "dxf_circular_geometry")),
            "feature_id": str(feature.get("id", "")),
            "confidence": "high",
        }

    def _add_step_length_dimensions(
        self,
        modelspace: Any,
        view_name: str,
        bounds: list[float],
        features: list[JsonObject],
        layout: JsonObject | None = None,
    ) -> list[JsonObject]:
        step_features = [
            feature for feature in features if feature.get("feature_type") == "step_length"
        ]
        if not step_features:
            return []

        _min_x, _min_y, _max_x, max_y = bounds
        annotations: list[JsonObject] = []
        base_offset = max(6.0, min((bounds[2] - bounds[0]) * 0.12, 12.0))
        for index, feature in enumerate(step_features):
            start = feature.get("start")
            end = feature.get("end")
            if not isinstance(start, list) or not isinstance(end, list):
                continue
            if len(start) != 2 or len(end) != 2:
                continue
            start_x, end_x = float(start[0]), float(end[0])
            base_y = max_y + base_offset + index * 5.0
            annotation = self._add_linear_dimension(
                modelspace,
                view_name,
                str(feature["id"]),
                "step_length",
                (start_x, base_y),
                (start_x, max_y),
                (end_x, max_y),
                0,
                float(feature["value_mm"]),
                str(feature["source"]),
                "medium",
                layout=layout,
            )
            annotation["feature_id"] = str(feature["id"])
            annotations.append(annotation)
        return annotations
