from __future__ import annotations

from itertools import combinations
from typing import Any

from mechanical_drawing_assistant.models import DrawingPlan, JsonObject

A3_LANDSCAPE_SIZE_M = (0.420, 0.297)
SHEET_SIZES_M = {
    "A0": (1.189, 0.841),
    "A1": (0.841, 0.594),
    "A2": (0.594, 0.420),
    "A3": A3_LANDSCAPE_SIZE_M,
    "A4": (0.297, 0.210),
}

VIEW_DIRECTION_TOLERANCE_M = 0.006
VIEW_ALIGNMENT_TOLERANCE_M = 0.025
VIEW_CLEARANCE_MARGIN_M = 0.005
VIEW_ANNOTATION_SPACE_M = 0.018
SHEET_SAFE_MARGIN_M = 0.006
MIN_VIEW_EXTENT_M = 0.035
MIN_VIEW_AREA_RATIO = 0.006
TITLE_BLOCK_WIDTH_M = 0.180
TITLE_BLOCK_HEIGHT_M = 0.060
TITLE_BLOCK_MARGIN_M = 0.005
EXTRA_VIEW_MARKER_FIELDS = (
    "view",
    "view_name",
    "view_type",
    "extra_view",
    "extra_view_type",
    "extra_view_request_id",
    "planned_extra_view",
    "recommendation",
    "source_recommendation",
)
EXTRA_VIEW_MARKER_LIST_FIELDS = (
    "implemented_extra_views",
    "satisfies_recommendations",
    "source_recommendations",
)


def review_drawing_views(
    plan: DrawingPlan,
    inserted_views: list[JsonObject],
    failed_views: list[JsonObject] | None = None,
    sheet_info: JsonObject | None = None,
) -> JsonObject:
    findings: list[JsonObject] = []
    failed = failed_views or []
    views_by_name = _views_by_name(inserted_views)
    expected_views = _list_of_text(plan.views)
    projection_method = _text_value(plan.view_plan.get("projection_method"), "unknown")
    layout_rule = _text_value(plan.view_plan.get("layout_rule"), "unknown")
    sheet_size = _sheet_size_m(plan, sheet_info)
    safe_area, safe_area_source = _safe_area_m(plan, sheet_size, sheet_info)
    title_block_zone, title_block_source = _title_block_zone_m(sheet_size, sheet_info)
    extra_view_status = _extra_view_status(plan, inserted_views)

    _review_required_views(findings, expected_views, views_by_name, failed)
    _review_view_geometry_fields(findings, inserted_views)
    if projection_method == "first_angle" and layout_rule == "front_top_below_left_right":
        _review_first_angle_layout(findings, views_by_name)
    else:
        findings.append(
            _finding(
                "INFO",
                "VIEW_LAYOUT_RULE",
                f"当前暂未内置 `{projection_method}/{layout_rule}` 的自动排布复查。",
                "补充对应投影法和排布规则后，再启用几何位置复查。",
            )
        )

    _review_overlaps(findings, inserted_views)
    _review_sheet_bounds(findings, inserted_views, sheet_size)
    _review_safe_area(findings, inserted_views, safe_area)
    _review_view_scale(findings, inserted_views, sheet_size)
    _review_annotation_space(findings, inserted_views, sheet_size, title_block_zone)
    _review_title_block(findings, inserted_views, title_block_zone)
    _review_pending_extra_views(findings, extra_view_status)

    return {
        "status": _status_from_findings(findings),
        "projection_method": projection_method,
        "layout_rule": layout_rule,
        "expected_views": expected_views,
        "inserted_views": sorted(views_by_name),
        "failed_views": [_view_name(view) for view in failed if _view_name(view)],
        "extra_view_requests": extra_view_status["extra_view_requests"],
        "recommended_extra_views": extra_view_status["recommended_extra_views"],
        "implemented_extra_views": extra_view_status["implemented_extra_views"],
        "pending_extra_views": extra_view_status["pending_extra_views"],
        "pending_extra_view_requests": extra_view_status["pending_extra_view_requests"],
        "sheet_size_m": [round(sheet_size[0], 6), round(sheet_size[1], 6)],
        "safe_area_m": [round(value, 6) for value in safe_area],
        "safe_area_source": safe_area_source,
        "title_block_zone_m": [round(value, 6) for value in title_block_zone],
        "title_block_source": title_block_source,
        "annotation_space_m": VIEW_ANNOTATION_SPACE_M,
        "checks": [
            "required_views",
            "view_geometry_fields",
            "projection_layout",
            "view_overlap",
            "sheet_bounds",
            "safe_area",
            "view_scale",
            "annotation_space",
            "title_block",
            "pending_extra_views",
        ],
        "findings": findings,
    }


def _review_required_views(
    findings: list[JsonObject],
    expected_views: list[str],
    views_by_name: dict[str, JsonObject],
    failed_views: list[JsonObject],
) -> None:
    if "front" not in expected_views:
        findings.append(
            _finding(
                "WARN",
                "VIEW_FRONT_MISSING_FROM_PLAN",
                "视图计划中没有主视图 front。",
                (
                    "机械工程图通常应先确认主视图方向；除非任务明确是局部图或补充图，"
                    "否则建议保留 front。"
                ),
            )
        )

    for expected_view in expected_views:
        if expected_view not in views_by_name:
            findings.append(
                _finding(
                    "ERROR",
                    "VIEW_MISSING",
                    f"计划视图 `{expected_view}` 没有成功插入工程图。",
                    "检查 SolidWorks 标准视图名称映射、模型路径和当前模板，再重新生成工程图。",
                    {"view": expected_view},
                )
            )

    for failed_view in failed_views:
        view_name = _view_name(failed_view)
        if not view_name:
            continue
        details = _failed_view_details(failed_view)
        details["view"] = view_name
        findings.append(
            _finding(
                "ERROR",
                "VIEW_INSERT_FAILED",
                f"SolidWorks 插入 `{view_name}` 视图失败。",
                "查看 export_manifest.json 中 failed_views 的候选视图名和 COM 错误信息。",
                details,
            )
        )


def _review_view_geometry_fields(
    findings: list[JsonObject],
    inserted_views: list[JsonObject],
) -> None:
    for view in inserted_views:
        view_name = _view_name(view)
        if not view_name:
            continue
        if _outline(view) is not None:
            continue
        findings.append(
            _finding(
                "WARN",
                "VIEW_OUTLINE_MISSING",
                f"视图 `{view_name}` 缺少 outline_m，无法复查图纸边界、安全区和视图比例。",
                "确认 SolidWorks view.GetOutline 可用，并在 export_manifest.json 中保留视图轮廓。",
                {"view": view_name},
            )
        )


def _review_first_angle_layout(
    findings: list[JsonObject],
    views_by_name: dict[str, JsonObject],
) -> None:
    front = views_by_name.get("front")
    if not front:
        return

    front_point = _view_point(front)
    if front_point is None:
        findings.append(
            _finding(
                "WARN",
                "VIEW_POSITION_MISSING",
                "主视图缺少 position_m 或 outline_m，无法复查投影排布。",
                "确认 SolidWorks view.GetOutline 可用，并在 manifest 中保留视图位置字段。",
                {"view": "front"},
            )
        )
        return

    top = views_by_name.get("top")
    if top:
        _review_top_view_position(findings, front_point, top)

    left = views_by_name.get("left")
    if left:
        _review_left_view_position(findings, front_point, left)

    right = views_by_name.get("right")
    if right:
        _review_right_view_position(findings, front_point, right)


def _review_top_view_position(
    findings: list[JsonObject],
    front_point: tuple[float, float],
    top_view: JsonObject,
) -> None:
    top_point = _view_point(top_view)
    if top_point is None:
        findings.append(_missing_position_finding("top"))
        return

    if top_point[1] >= front_point[1] - VIEW_DIRECTION_TOLERANCE_M:
        findings.append(
            _finding(
                "ERROR",
                "VIEW_TOP_POSITION",
                "俯视图 top 没有位于主视图 front 下方，不符合当前第一角法排布规则。",
                "按主视图、俯视图在主下、左视图在主右重新排布。",
                {"front_position_m": front_point, "top_position_m": top_point},
            )
        )
    if abs(top_point[0] - front_point[0]) > VIEW_ALIGNMENT_TOLERANCE_M:
        findings.append(
            _finding(
                "WARN",
                "VIEW_TOP_ALIGNMENT",
                "俯视图 top 与主视图 front 的水平中心线偏差较大。",
                "优先让俯视图与主视图在 X 方向对齐，并为标注预留外侧空间。",
                {"front_position_m": front_point, "top_position_m": top_point},
            )
        )


def _review_left_view_position(
    findings: list[JsonObject],
    front_point: tuple[float, float],
    left_view: JsonObject,
) -> None:
    left_point = _view_point(left_view)
    if left_point is None:
        findings.append(_missing_position_finding("left"))
        return

    if left_point[0] <= front_point[0] + VIEW_DIRECTION_TOLERANCE_M:
        findings.append(
            _finding(
                "ERROR",
                "VIEW_LEFT_POSITION",
                "左视图 left 没有位于主视图 front 右侧，不符合当前第一角法排布规则。",
                "按主视图、俯视图在主下、左视图在主右重新排布。",
                {"front_position_m": front_point, "left_position_m": left_point},
            )
        )
    if abs(left_point[1] - front_point[1]) > VIEW_ALIGNMENT_TOLERANCE_M:
        findings.append(
            _finding(
                "WARN",
                "VIEW_LEFT_ALIGNMENT",
                "左视图 left 与主视图 front 的垂直中心线偏差较大。",
                "优先让左视图与主视图在 Y 方向对齐，并为标注预留外侧空间。",
                {"front_position_m": front_point, "left_position_m": left_point},
            )
        )


def _review_right_view_position(
    findings: list[JsonObject],
    front_point: tuple[float, float],
    right_view: JsonObject,
) -> None:
    right_point = _view_point(right_view)
    if right_point is None:
        findings.append(_missing_position_finding("right"))
        return

    if right_point[0] >= front_point[0] - VIEW_DIRECTION_TOLERANCE_M:
        findings.append(
            _finding(
                "ERROR",
                "VIEW_RIGHT_POSITION",
                "右视图 right 没有位于主视图 front 左侧，不符合第一角法右视图排布。",
                (
                    "若目标是主视图右侧的侧向表达，应使用 left 视图；"
                    "若确需 right 视图，应放在主视图左侧。"
                ),
                {"front_position_m": front_point, "right_position_m": right_point},
            )
        )
    if abs(right_point[1] - front_point[1]) > VIEW_ALIGNMENT_TOLERANCE_M:
        findings.append(
            _finding(
                "WARN",
                "VIEW_RIGHT_ALIGNMENT",
                "右视图 right 与主视图 front 的垂直中心线偏差较大。",
                "优先让右视图与主视图在 Y 方向对齐，并为标注预留外侧空间。",
                {"front_position_m": front_point, "right_position_m": right_point},
            )
        )


def _review_overlaps(findings: list[JsonObject], inserted_views: list[JsonObject]) -> None:
    for first, second in combinations(inserted_views, 2):
        first_outline = _outline(first)
        second_outline = _outline(second)
        if first_outline is None or second_outline is None:
            continue
        if _outlines_overlap(first_outline, second_outline, VIEW_CLEARANCE_MARGIN_M):
            findings.append(
                _finding(
                    "ERROR",
                    "VIEW_OVERLAP",
                    f"视图 `{_view_name(first)}` 与 `{_view_name(second)}` 重叠或间距小于 5 mm。",
                    "拉开视图间距，并在视图外侧预留尺寸线、粗糙度和技术要求空间。",
                    {
                        "first_view": _view_name(first),
                        "second_view": _view_name(second),
                        "clearance_margin_m": VIEW_CLEARANCE_MARGIN_M,
                    },
                )
            )


def _review_sheet_bounds(
    findings: list[JsonObject],
    inserted_views: list[JsonObject],
    sheet_size: tuple[float, float],
) -> None:
    sheet_bounds = (0.0, 0.0, sheet_size[0], sheet_size[1])
    for view in inserted_views:
        outline = _outline(view)
        if outline is None:
            continue
        if not _box_inside(outline, sheet_bounds):
            findings.append(
                _finding(
                    "ERROR",
                    "VIEW_OUTSIDE_SHEET",
                    f"视图 `{_view_name(view)}` 超出当前图纸边界。",
                    "调整视图比例或位置，确保所有视图轮廓都落在图幅内。",
                    {
                        "view": _view_name(view),
                        "outline_m": [round(value, 6) for value in outline],
                        "sheet_bounds_m": [round(value, 6) for value in sheet_bounds],
                        "violations": _box_violations(outline, sheet_bounds),
                    },
                )
            )


def _review_safe_area(
    findings: list[JsonObject],
    inserted_views: list[JsonObject],
    safe_area: tuple[float, float, float, float],
) -> None:
    for view in inserted_views:
        outline = _outline(view)
        if outline is None:
            continue
        if not _box_inside(outline, safe_area):
            findings.append(
                _finding(
                    "WARN",
                    "VIEW_OUTSIDE_SAFE_AREA",
                    f"视图 `{_view_name(view)}` 超出图纸安全区。",
                    "按图框内缩安全区重新排布视图，给图框、装订边和外侧标注留出余量。",
                    {
                        "view": _view_name(view),
                        "outline_m": [round(value, 6) for value in outline],
                        "safe_area_m": [round(value, 6) for value in safe_area],
                        "violations": _box_violations(outline, safe_area),
                    },
                )
            )


def _review_view_scale(
    findings: list[JsonObject],
    inserted_views: list[JsonObject],
    sheet_size: tuple[float, float],
) -> None:
    sheet_area = sheet_size[0] * sheet_size[1]
    for view in inserted_views:
        outline = _outline(view)
        if outline is None:
            continue
        width = outline[2] - outline[0]
        height = outline[3] - outline[1]
        largest_extent = max(width, height)
        area_ratio = (width * height) / sheet_area if sheet_area > 0 else 0.0
        if largest_extent < MIN_VIEW_EXTENT_M or area_ratio < MIN_VIEW_AREA_RATIO:
            findings.append(
                _finding(
                    "WARN",
                    "VIEW_SCALE_SMALL",
                    f"视图 `{_view_name(view)}` 在图纸上显示偏小，可能不利于标注和加工读图。",
                    "优先提高视图比例或减少不必要视图；确认仍能为尺寸线和技术要求留出空间。",
                    {
                        "view": _view_name(view),
                        "outline_m": [round(value, 6) for value in outline],
                        "largest_extent_m": round(largest_extent, 6),
                        "area_ratio": round(area_ratio, 6),
                    },
                )
            )


def _review_annotation_space(
    findings: list[JsonObject],
    inserted_views: list[JsonObject],
    sheet_size: tuple[float, float],
    title_block_zone: tuple[float, float, float, float],
) -> None:
    sheet_bounds = (0.0, 0.0, sheet_size[0], sheet_size[1])
    for view in inserted_views:
        outline = _outline(view)
        if outline is None:
            continue
        tight_edges = _tight_sheet_edges(outline, sheet_bounds)
        if tight_edges:
            findings.append(
                _finding(
                    "WARN",
                    "VIEW_ANNOTATION_SPACE",
                    f"视图 `{_view_name(view)}` 靠近图纸边界，外侧标注预留空间不足。",
                    "移动视图或调整比例，尽量在视图外侧保留尺寸线、箭头和文字空间。",
                    {
                        "view": _view_name(view),
                        "tight_edges": tight_edges,
                        "required_space_m": VIEW_ANNOTATION_SPACE_M,
                    },
                )
            )
        if _distance_to_zone(outline, title_block_zone) < VIEW_ANNOTATION_SPACE_M:
            findings.append(
                _finding(
                    "WARN",
                    "VIEW_TITLE_BLOCK_CLEARANCE",
                    f"视图 `{_view_name(view)}` 距离标题栏区域过近，后续标注可能压到标题栏。",
                    "优先将视图和尺寸线避开标题栏，必要时调整视图比例或换图幅。",
                    {
                        "view": _view_name(view),
                        "required_space_m": VIEW_ANNOTATION_SPACE_M,
                    },
                )
            )


def _review_title_block(
    findings: list[JsonObject],
    inserted_views: list[JsonObject],
    title_block_zone: tuple[float, float, float, float],
) -> None:
    for view in inserted_views:
        outline = _outline(view)
        if outline is None:
            continue
        if _outlines_overlap(outline, title_block_zone, TITLE_BLOCK_MARGIN_M):
            findings.append(
                _finding(
                    "WARN",
                    "VIEW_TITLE_BLOCK",
                    f"视图 `{_view_name(view)}` 可能侵入 A3 标题栏近似区域。",
                    "当前按右下角 180 mm x 60 mm 近似标题栏检查；后续应读取模板真实图框。",
                    {
                        "view": _view_name(view),
                        "outline_m": [round(value, 6) for value in outline],
                        "title_block_zone_m": [round(value, 6) for value in title_block_zone],
                    },
                )
            )


def _review_pending_extra_views(
    findings: list[JsonObject],
    extra_view_status: JsonObject,
) -> None:
    pending = _list_of_text(extra_view_status.get("pending_extra_views"))
    if not pending:
        return
    findings.append(
        _finding(
            "INFO",
            "VIEW_PENDING_EXTRA",
            "视图规划器建议的额外表达尚未生成：" + "、".join(pending),
            "复核是否需要剖视图、断面图或局部放大；后续版本再接入 SolidWorks 自动剖视。",
            {
                "automation_status": "not_executed",
                "extra_view_requests": extra_view_status["extra_view_requests"],
                "recommended_extra_views": extra_view_status["recommended_extra_views"],
                "implemented_extra_views": extra_view_status["implemented_extra_views"],
                "pending_extra_views": pending,
                "pending_extra_view_requests": extra_view_status["pending_extra_view_requests"],
                "inserted_extra_view_markers": extra_view_status["inserted_extra_view_markers"],
            },
        )
    )


def _extra_view_status(plan: DrawingPlan, inserted_views: list[JsonObject]) -> JsonObject:
    recommended = _list_of_text(plan.view_plan.get("recommended_extra_views"))
    requests = _extra_view_requests(plan)
    inserted_markers = _inserted_extra_view_markers(inserted_views)
    implemented = [
        recommendation
        for recommendation in recommended
        if _extra_view_is_implemented(recommendation, inserted_markers)
    ]
    pending = [
        recommendation for recommendation in recommended if recommendation not in implemented
    ]
    pending_requests = [
        request for request in requests if _text_value(request.get("id"), "") in set(pending)
    ]
    return {
        "extra_view_requests": requests,
        "recommended_extra_views": recommended,
        "implemented_extra_views": implemented,
        "pending_extra_views": pending,
        "pending_extra_view_requests": pending_requests,
        "inserted_extra_view_markers": sorted(inserted_markers),
    }


def _extra_view_requests(plan: DrawingPlan) -> list[JsonObject]:
    requests = _list_of_objects(plan.view_plan.get("extra_view_requests"))
    if requests:
        return requests
    return [
        {
            "id": recommendation,
            "view_type": _extra_view_type_from_id(recommendation),
            "automation_status": "planned_not_implemented",
        }
        for recommendation in _list_of_text(plan.view_plan.get("recommended_extra_views"))
    ]


def _extra_view_type_from_id(recommendation: str) -> str:
    lowered = recommendation.lower()
    if "section" in lowered:
        return "section"
    if "detail" in lowered:
        return "detail"
    return "extra"


def _inserted_extra_view_markers(inserted_views: list[JsonObject]) -> set[str]:
    markers: set[str] = set()
    for view in inserted_views:
        for field in EXTRA_VIEW_MARKER_FIELDS:
            _add_extra_view_marker(markers, view.get(field))
        for field in EXTRA_VIEW_MARKER_LIST_FIELDS:
            _add_extra_view_marker(markers, view.get(field))
    return markers


def _add_extra_view_marker(markers: set[str], value: object) -> None:
    if isinstance(value, str):
        marker = _normalize_extra_view_marker(value)
        if marker:
            markers.add(marker)
        return
    if isinstance(value, list):
        for item in value:
            _add_extra_view_marker(markers, item)


def _extra_view_is_implemented(recommendation: str, inserted_markers: set[str]) -> bool:
    recommendation_marker = _normalize_extra_view_marker(recommendation)
    if not recommendation_marker:
        return False
    if recommendation_marker in inserted_markers:
        return True
    return any(
        len(marker) >= 6 and (recommendation_marker in marker or marker in recommendation_marker)
        for marker in inserted_markers
    )


def _normalize_extra_view_marker(value: str) -> str:
    return "".join(character.lower() for character in value.strip() if character.isalnum())


def _views_by_name(inserted_views: list[JsonObject]) -> dict[str, JsonObject]:
    result: dict[str, JsonObject] = {}
    for view in inserted_views:
        view_name = _view_name(view)
        if view_name:
            result[view_name] = view
    return result


def _view_name(view: JsonObject) -> str:
    value = view.get("view")
    return value.strip().lower() if isinstance(value, str) and value.strip() else ""


def _view_point(view: JsonObject) -> tuple[float, float] | None:
    position = view.get("position_m")
    if isinstance(position, list) and len(position) >= 2:
        point = _float_pair(position[0], position[1])
        if point is not None:
            return point

    outline = _outline(view)
    if outline is None:
        return None
    return ((outline[0] + outline[2]) / 2, (outline[1] + outline[3]) / 2)


def _outline(view: JsonObject) -> tuple[float, float, float, float] | None:
    outline = view.get("outline_m")
    if not isinstance(outline, list) or len(outline) != 4:
        return None
    try:
        left, bottom, right, top = (float(value) for value in outline)
    except (TypeError, ValueError):
        return None
    if left > right or bottom > top:
        return None
    return (left, bottom, right, top)


def _outlines_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    margin: float,
) -> bool:
    return not (
        first[2] + margin <= second[0]
        or second[2] + margin <= first[0]
        or first[3] + margin <= second[1]
        or second[3] + margin <= first[1]
    )


def _tight_sheet_edges(
    outline: tuple[float, float, float, float],
    sheet_bounds: tuple[float, float, float, float],
) -> list[str]:
    edges: list[str] = []
    if outline[0] - sheet_bounds[0] < VIEW_ANNOTATION_SPACE_M:
        edges.append("left")
    if outline[1] - sheet_bounds[1] < VIEW_ANNOTATION_SPACE_M:
        edges.append("bottom")
    if sheet_bounds[2] - outline[2] < VIEW_ANNOTATION_SPACE_M:
        edges.append("right")
    if sheet_bounds[3] - outline[3] < VIEW_ANNOTATION_SPACE_M:
        edges.append("top")
    return edges


def _distance_to_zone(
    outline: tuple[float, float, float, float],
    zone: tuple[float, float, float, float],
) -> float:
    if _outlines_overlap(outline, zone, 0.0):
        return 0.0
    dx = max(zone[0] - outline[2], outline[0] - zone[2], 0.0)
    dy = max(zone[1] - outline[3], outline[1] - zone[3], 0.0)
    return (dx**2 + dy**2) ** 0.5


def _box_inside(
    box: tuple[float, float, float, float],
    bounds: tuple[float, float, float, float],
) -> bool:
    return (
        box[0] >= bounds[0] and box[1] >= bounds[1] and box[2] <= bounds[2] and box[3] <= bounds[3]
    )


def _box_violations(
    box: tuple[float, float, float, float],
    bounds: tuple[float, float, float, float],
) -> list[str]:
    violations: list[str] = []
    if box[0] < bounds[0]:
        violations.append("left")
    if box[1] < bounds[1]:
        violations.append("bottom")
    if box[2] > bounds[2]:
        violations.append("right")
    if box[3] > bounds[3]:
        violations.append("top")
    return violations


def _sheet_size_m(plan: DrawingPlan, sheet_info: JsonObject | None) -> tuple[float, float]:
    if isinstance(sheet_info, dict):
        sheet_size = _tuple4_or_pair(sheet_info.get("sheet_size_m"))
        if sheet_size and sheet_size[0] > 0 and sheet_size[1] > 0:
            return (sheet_size[0], sheet_size[1])

    sheet = plan.standard_profile.get("sheet") if isinstance(plan.standard_profile, dict) else None
    preferred_size = sheet.get("preferred_size") if isinstance(sheet, dict) else None
    if isinstance(preferred_size, str):
        return SHEET_SIZES_M.get(preferred_size.upper(), A3_LANDSCAPE_SIZE_M)
    return A3_LANDSCAPE_SIZE_M


def _safe_area_m(
    plan: DrawingPlan,
    sheet_size: tuple[float, float],
    sheet_info: JsonObject | None,
) -> tuple[tuple[float, float, float, float], str]:
    if isinstance(sheet_info, dict):
        safe_area = _tuple4_or_pair(sheet_info.get("safe_area_m"))
        if safe_area and len(safe_area) == 4 and _valid_box(safe_area):
            return (
                (
                    safe_area[0],
                    safe_area[1],
                    safe_area[2],
                    safe_area[3],
                ),
                "solidworks_sheet_safe_area",
            )

    margin = _sheet_safe_margin_m(plan)
    width, height = sheet_size
    x_margin = min(margin, width / 2)
    y_margin = min(margin, height / 2)
    return (
        (
            x_margin,
            y_margin,
            max(x_margin, width - x_margin),
            max(y_margin, height - y_margin),
        ),
        "standard_profile_safe_margin",
    )


def _sheet_safe_margin_m(plan: DrawingPlan) -> float:
    sheet = plan.standard_profile.get("sheet") if isinstance(plan.standard_profile, dict) else None
    if isinstance(sheet, dict):
        safe_margin_mm = _float_value(sheet.get("safe_margin_mm"))
        if safe_margin_mm is not None and safe_margin_mm >= 0:
            return safe_margin_mm / 1000
    return SHEET_SAFE_MARGIN_M


def _title_block_zone_m(
    sheet_size: tuple[float, float],
    sheet_info: JsonObject | None,
) -> tuple[tuple[float, float, float, float], str]:
    if isinstance(sheet_info, dict):
        title_block_zone = _tuple4_or_pair(sheet_info.get("title_block_zone_m"))
        if title_block_zone and len(title_block_zone) == 4:
            return (
                (
                    title_block_zone[0],
                    title_block_zone[1],
                    title_block_zone[2],
                    title_block_zone[3],
                ),
                "solidworks_sheet_title_block",
            )

    width, _height = sheet_size
    return (
        (
            max(0.0, width - TITLE_BLOCK_WIDTH_M),
            0.0,
            width,
            TITLE_BLOCK_HEIGHT_M,
        ),
        "a3_default_approximation",
    )


def _valid_box(value: tuple[float, ...]) -> bool:
    return len(value) == 4 and value[0] < value[2] and value[1] < value[3]


def _status_from_findings(findings: list[JsonObject]) -> str:
    severities = {finding.get("severity") for finding in findings}
    if "ERROR" in severities:
        return "error"
    if "WARN" in severities:
        return "warning"
    return "passed"


def _missing_position_finding(view_name: str) -> JsonObject:
    return _finding(
        "WARN",
        "VIEW_POSITION_MISSING",
        f"视图 `{view_name}` 缺少 position_m 或 outline_m，无法复查投影排布。",
        "确认 SolidWorks view.GetOutline 可用，并在 manifest 中保留视图位置字段。",
        {"view": view_name},
    )


def _failed_view_details(failed_view: JsonObject) -> JsonObject:
    details: JsonObject = {}
    for key in ("status", "last_error", "error"):
        value = failed_view.get(key)
        if isinstance(value, str) and value.strip():
            details[key] = value.strip()

    candidates = _list_of_text(failed_view.get("candidates"))
    if candidates:
        details["candidates"] = candidates
    return details


def _finding(
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


def _list_of_text(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


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
        return value.strip()
    return fallback


def _tuple4_or_pair(value: Any) -> tuple[float, ...] | None:
    if not isinstance(value, list) or len(value) not in {2, 4}:
        return None
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_pair(first: Any, second: Any) -> tuple[float, float] | None:
    try:
        return (float(first), float(second))
    except (TypeError, ValueError):
        return None
