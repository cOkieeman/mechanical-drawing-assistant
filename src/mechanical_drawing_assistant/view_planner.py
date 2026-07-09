from __future__ import annotations

from mechanical_drawing_assistant.models import (
    DEFAULT_GB_THREE_VIEWS,
    DrawingJob,
    JsonObject,
)


def _section_geometry_hint(semantic_target: str) -> JsonObject:
    return {
        "schema_version": 1,
        "status": "hint_only",
        "source": "category_rule",
        "coordinate_space": "base_view_outline_normalized",
        "units": "ratio",
        "requires_manual_review": True,
        "primitive": {
            "type": "section_line",
            "label": "A-A",
            "points": [{"x": 0.12, "y": 0.5}, {"x": 0.88, "y": 0.5}],
            "semantic_target": semantic_target,
            "direction_hint": "auto",
        },
    }


def _detail_geometry_hint(semantic_target: str) -> JsonObject:
    return {
        "schema_version": 1,
        "status": "hint_only",
        "source": "category_rule",
        "coordinate_space": "base_view_outline_normalized",
        "units": "ratio",
        "requires_manual_review": True,
        "primitive": {
            "type": "detail_circle",
            "center": {"x": 0.5, "y": 0.5},
            "radius": 0.32,
            "semantic_target": semantic_target,
        },
    }


CATEGORY_VIEW_RULES: dict[str, JsonObject] = {
    "turned_mounting_sleeve": {
        "views": ["front", "left"],
        "reason": "套筒类零件优先表达轴向轮廓和端面圆形特征。",
        "recommended_extra_views": ["section_view_for_internal_bore"],
        "extra_view_requests": [
            {
                "id": "section_view_for_internal_bore",
                "view_type": "section",
                "base_view": "front",
                "target_feature": "internal_bore",
                "placement_hint": "place_near_front_or_replace_left_when_clear",
                "automation_status": "planned_not_implemented",
                "api_hint": (
                    "Create a section line on the base view, then use the "
                    "SolidWorks drawing section-view API."
                ),
                "geometry_hint": _section_geometry_hint("internal_bore_axis"),
            }
        ],
        "manual_review_notes": [
            "内孔、内台阶或装配配合面重要时，应优先评估剖视图。",
            "若外形或孔位不能由两视图表达清楚，再补充俯视图或局部放大。",
        ],
        "standard_refs": ["GB/T 4458.1-2002", "GB/T 4458.6-2002"],
    },
    "pulley": {
        "views": ["front", "left"],
        "reason": "带轮类零件优先表达轴向轮廓、轮槽和端面孔径。",
        "recommended_extra_views": ["section_view_for_bore_and_groove"],
        "extra_view_requests": [
            {
                "id": "section_view_for_bore_and_groove",
                "view_type": "section",
                "base_view": "front",
                "target_feature": "bore_and_groove",
                "placement_hint": "place_near_front_with_space_for_bore_dimensions",
                "automation_status": "planned_not_implemented",
                "api_hint": (
                    "Create a section line through the rotation axis, then use the "
                    "SolidWorks drawing section-view API."
                ),
                "geometry_hint": _section_geometry_hint("bore_and_groove_axis"),
            }
        ],
        "manual_review_notes": [
            "轮槽、内孔和键槽需要进一步确认是否用剖视或局部放大表达。",
            "端面孔、键槽或紧定孔存在时，应补充相应特征尺寸。",
        ],
        "standard_refs": ["GB/T 4458.1-2002", "GB/T 4458.6-2002"],
    },
    "shaft": {
        "views": ["front", "left"],
        "reason": "轴类零件通常以轴向主视图表达台阶、长度和直径，端面视图用于补充端部特征。",
        "recommended_extra_views": ["detail_view_for_keyway_or_thread"],
        "extra_view_requests": [
            {
                "id": "detail_view_for_keyway_or_thread",
                "view_type": "detail",
                "base_view": "front",
                "target_feature": "keyway_or_thread",
                "placement_hint": "place_above_or_below_front_away_from_dimension_chain",
                "automation_status": "planned_not_implemented",
                "api_hint": (
                    "Create or select a detail circle on the base view, then use the "
                    "SolidWorks drawing detail-view API."
                ),
                "geometry_hint": _detail_geometry_hint("keyway_or_thread"),
            }
        ],
        "manual_review_notes": [
            "键槽、螺纹、中心孔或退刀槽应评估局部放大或局部剖视。",
            "长轴可评估断裂画法。",
        ],
        "standard_refs": ["GB/T 4458.1-2002"],
    },
    "plate": {
        "views": ["front", "top", "left"],
        "reason": "板类零件优先用三视图表达厚度、外形和孔位关系。",
        "recommended_extra_views": ["detail_view_for_dense_hole_pattern"],
        "extra_view_requests": [
            {
                "id": "detail_view_for_dense_hole_pattern",
                "view_type": "detail",
                "base_view": "top",
                "target_feature": "dense_hole_pattern",
                "placement_hint": "place_to_right_of_top_view_when_sheet_space_allows",
                "automation_status": "planned_not_implemented",
                "api_hint": (
                    "Create or select a detail circle around the dense hole area, then use "
                    "the SolidWorks drawing detail-view API."
                ),
                "geometry_hint": _detail_geometry_hint("dense_hole_pattern"),
            }
        ],
        "manual_review_notes": [
            "阵列孔、沉孔或局部复杂轮廓应评估局部放大。",
            "厚度方向简单时可人工确认是否省略冗余视图。",
        ],
        "standard_refs": ["GB/T 4458.1-2002", "GB/T 4458.4-2003"],
    },
    "motor_mounting_plate": {
        "views": ["front", "top", "left"],
        "reason": (
            "电机安装板优先用俯视图表达外形、中心孔、螺纹孔和长圆孔位置，用主视/侧视补充厚度。"
        ),
        "recommended_extra_views": ["detail_view_for_dense_hole_pattern"],
        "extra_view_requests": [
            {
                "id": "detail_view_for_dense_hole_pattern",
                "view_type": "detail",
                "base_view": "top",
                "target_feature": "dense_hole_pattern",
                "placement_hint": "place_to_right_of_top_view_when_sheet_space_allows",
                "automation_status": "planned_not_implemented",
                "api_hint": (
                    "Create or select a detail circle around the hole group, then use the "
                    "SolidWorks drawing detail-view API."
                ),
                "geometry_hint": _detail_geometry_hint("dense_hole_pattern"),
            }
        ],
        "manual_review_notes": [
            "孔组和长圆孔应同时确认中心距与到加工基准边的定位尺寸。",
            "沉孔、台阶孔或局部密集孔位存在时，应评估局部放大。",
        ],
        "standard_refs": ["GB/T 4458.1-2002", "GB/T 4458.4-2003"],
    },
}


def plan_views(job: DrawingJob, standard_profile: JsonObject | None) -> JsonObject:
    projection = _object_value(standard_profile, "projection")
    default_views = _list_of_strings(projection.get("default_views")) or DEFAULT_GB_THREE_VIEWS
    projection_method = _text_value(projection.get("method"), "first_angle")
    layout_rule = _text_value(projection.get("layout_rule"), "front_top_below_left_right")
    projection_refs = _list_of_strings(projection.get("standard_refs"))

    if job.views:
        return {
            "source": "job_override",
            "projection_method": projection_method,
            "layout_rule": layout_rule,
            "views": job.views,
            "reason": "job 文件显式指定 views，本轮按人工覆盖执行。",
            "recommended_extra_views": [],
            "extra_view_requests": [],
            "warnings": [],
            "manual_review_notes": ["人工指定 views 时仍需复查是否符合投影法和零件表达需要。"],
            "standard_refs": projection_refs,
        }

    category = job.part.category.strip().lower()
    rule = CATEGORY_VIEW_RULES.get(category)
    if rule is None:
        return {
            "source": "default_profile",
            "projection_method": projection_method,
            "layout_rule": layout_rule,
            "views": default_views,
            "reason": "未找到零件类型视图模板，使用标准 profile 默认视图。",
            "recommended_extra_views": [],
            "extra_view_requests": [],
            "warnings": [f"缺少零件类型 `{job.part.category}` 的视图模板。"],
            "manual_review_notes": ["需要人工确认主视图选择、必要剖视和局部放大。"],
            "standard_refs": projection_refs,
        }

    rule_views = _list_of_strings(rule.get("views")) or default_views
    return {
        "source": "category_rule",
        "category": category,
        "projection_method": projection_method,
        "layout_rule": layout_rule,
        "views": rule_views,
        "reason": rule.get("reason", "按零件类型模板推荐视图。"),
        "recommended_extra_views": _list_of_strings(rule.get("recommended_extra_views")),
        "extra_view_requests": _list_of_objects(rule.get("extra_view_requests")),
        "warnings": [],
        "manual_review_notes": _list_of_strings(rule.get("manual_review_notes")),
        "standard_refs": sorted(set(projection_refs + _list_of_strings(rule.get("standard_refs")))),
    }


def _object_value(data: JsonObject | None, key: str) -> JsonObject:
    if not isinstance(data, dict):
        return {}
    value = data.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _list_of_objects(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    result: list[JsonObject] = []
    for item in value:
        if isinstance(item, dict):
            result.append({str(key): entry for key, entry in item.items()})
    return result


def _text_value(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return fallback
