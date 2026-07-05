from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import ezdxf

from mechanical_drawing_assistant.models import JsonObject

DIMENSION_LAYER = "MDA-DIM"
ANNOTATION_MARGIN_MM = 0.5
MIN_DIMENSION_SIZE_MM = 1.0


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

        regions = self._resolve_view_regions(view_outlines_m)
        annotations: list[JsonObject] = []
        warnings: list[str] = []

        if not regions:
            warnings.append("No view outlines were provided; first-pass annotation was skipped.")

        for region in regions:
            view_name = str(region.get("view", "unknown"))
            entities = self._entities_in_region(modelspace, region)
            bounds = self._combined_bounds(entities)
            if bounds is None:
                warnings.append(f"No DXF geometry was found for view `{view_name}`.")
                continue

            circular_feature = self._largest_circular_feature(entities)
            if self._looks_like_circular_view(bounds, circular_feature):
                annotation = self._add_diameter_dimension(modelspace, view_name, circular_feature)
                if annotation:
                    annotations.append(annotation)
                continue

            annotations.extend(self._add_overall_dimensions(modelspace, view_name, bounds, region))

        output.parent.mkdir(parents=True, exist_ok=True)
        document.saveas(output)
        inspect_result = self.inspect_file(output)

        return {
            "path": str(path),
            "output_path": str(output),
            "status": "annotated",
            "units_assumption": "DXF modelspace units are millimeters.",
            "view_count": len(regions),
            "dimensions_added": len(annotations),
            "dimension_count_after": inspect_result.get("dimension_count", 0),
            "annotations": annotations,
            "warnings": warnings,
        }

    def _dimension_summary(self, entity: Any) -> JsonObject:
        return {
            "layer": entity.dxf.layer,
            "dimtype": int(entity.dxf.dimtype),
            "text": getattr(entity.dxf, "text", ""),
        }

    def _ensure_annotation_layer(self, document: Any) -> None:
        if not document.layers.has_entry(DIMENSION_LAYER):
            document.layers.add(DIMENSION_LAYER, color=1)

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

    def _largest_circular_feature(self, entities: list[Any]) -> JsonObject | None:
        features: list[JsonObject] = []
        for entity in entities:
            if entity.dxftype() not in {"ARC", "CIRCLE"}:
                continue
            center = entity.dxf.center
            features.append(
                {
                    "center": [float(center.x), float(center.y)],
                    "radius_mm": float(entity.dxf.radius),
                }
            )
        if not features:
            return None
        return max(features, key=lambda feature: float(feature["radius_mm"]))

    def _add_overall_dimensions(
        self,
        modelspace: Any,
        view_name: str,
        bounds: list[float],
        region: JsonObject,
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

        annotations: list[JsonObject] = []
        horizontal = modelspace.add_linear_dim(
            base=(min_x, base_y),
            p1=(min_x, min_y),
            p2=(max_x, min_y),
            angle=0,
            dimstyle="EZDXF",
            dxfattribs={"layer": DIMENSION_LAYER},
        )
        horizontal.render()
        annotations.append(
            {
                "id": f"{view_name}_overall_width",
                "view": view_name,
                "kind": "linear",
                "label": "overall_width",
                "value_mm": round(width, 3),
                "source": "dxf_geometry_bounds",
            }
        )

        base_x = max_x + offset
        vertical = modelspace.add_linear_dim(
            base=(base_x, min_y),
            p1=(max_x, min_y),
            p2=(max_x, max_y),
            angle=90,
            dimstyle="EZDXF",
            dxfattribs={"layer": DIMENSION_LAYER},
        )
        vertical.render()
        annotations.append(
            {
                "id": f"{view_name}_overall_height",
                "view": view_name,
                "kind": "linear",
                "label": "overall_height",
                "value_mm": round(height, 3),
                "source": "dxf_geometry_bounds",
            }
        )
        return annotations

    def _add_diameter_dimension(
        self,
        modelspace: Any,
        view_name: str,
        circular_feature: JsonObject | None,
    ) -> JsonObject | None:
        if not circular_feature:
            return None
        center_x, center_y = circular_feature["center"]
        radius = float(circular_feature["radius_mm"])
        if radius <= MIN_DIMENSION_SIZE_MM:
            return None
        dimension = modelspace.add_diameter_dim(
            center=(center_x, center_y),
            radius=radius,
            angle=0,
            location=(center_x + radius * 1.35, center_y + radius * 0.35),
            dimstyle="EZ_RADIUS",
            dxfattribs={"layer": DIMENSION_LAYER},
        )
        dimension.render()
        return {
            "id": f"{view_name}_diameter",
            "view": view_name,
            "kind": "diameter",
            "label": "diameter",
            "value_mm": round(radius * 2, 3),
            "source": "dxf_circular_geometry",
        }
