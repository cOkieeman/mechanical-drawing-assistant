from __future__ import annotations

from mechanical_drawing_assistant.models import (
    DimensionIntent,
    DrawingPlan,
    JsonObject,
    ReviewFinding,
)

DXF_COVERAGE_ALIASES = {
    "overall_size": {"overall_width", "overall_height", "overall_length", "thickness"},
    "overall_length": {"overall_width", "overall_length"},
    "outer_diameter": {"outer_diameter"},
    "turned_outer_diameter": {"outer_diameter", "turned_outer_diameter"},
    "bore": {"bore", "bore_diameter"},
    "bore_diameter": {"bore", "bore_diameter"},
    "center_cutout_diameter": {"center_cutout_diameter"},
    "thread_hole": {"thread_hole"},
    "thread_hole_pattern": {
        "thread_hole_edge_x",
        "thread_hole_edge_y",
        "thread_hole_pitch_x",
        "thread_hole_pitch_y",
    },
    "slot_callout": {"slot_callout"},
    "slot_pattern": {"slot_edge_x", "slot_edge_y", "slot_pitch_x", "slot_pitch_y"},
    "step_length": {"step_length"},
    "thickness": {"overall_height", "overall_width", "thickness"},
}


def review_plan(plan: DrawingPlan, export_manifest: JsonObject) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    view_review_codes = _view_review_codes(export_manifest)

    if plan.warnings:
        for warning in plan.warnings:
            findings.append(
                ReviewFinding(
                    severity="WARN",
                    code="INPUT_CONTEXT",
                    message=warning,
                    recommendation="补充真实 SolidWorks 模型路径，或确认当前只做 dry-run 规划。",
                )
            )

    if len(plan.views) < 3 and plan.view_plan.get("source") == "job_override":
        findings.append(
            ReviewFinding(
                severity="WARN",
                code="VIEW_SET",
                message="当前人工指定视图少于三视图。",
                recommendation="确认两视图已经能完整表达零件结构；必要时再加剖视或局部放大。",
            )
        )

    if plan.view_plan.get("warnings"):
        findings.append(
            ReviewFinding(
                severity="INFO",
                code="VIEW_PLANNER",
                message=(
                    "视图规划器存在提示：" + "、".join(_list_of_text(plan.view_plan["warnings"]))
                ),
                recommendation="补充该零件类型的视图模板，或在 job 中显式指定 views。",
            )
        )

    recommended_extra_views = _list_of_text(plan.view_plan.get("recommended_extra_views"))
    pending_extra_views = _manifest_pending_extra_views(export_manifest)
    if pending_extra_views and "VIEW_PENDING_EXTRA" not in view_review_codes:
        findings.append(
            ReviewFinding(
                severity="INFO",
                code="VIEW_PENDING_EXTRA",
                message="视图规划器建议的额外表达尚未生成：" + "、".join(pending_extra_views),
                recommendation=(
                    "复核是否需要剖视图、断面图或局部放大；后续可接入 SolidWorks 自动剖视。"
                ),
            )
        )
    elif (
        recommended_extra_views
        and "VIEW_PENDING_EXTRA" not in view_review_codes
        and not _view_review_resolved_extra_views(export_manifest)
    ):
        findings.append(
            ReviewFinding(
                severity="INFO",
                code="VIEW_RECOMMENDATION",
                message="视图规划器建议评估额外表达：" + "、".join(recommended_extra_views),
                recommendation=(
                    "人工复核是否需要剖视图、断面图或局部放大；后续可接入 SolidWorks 自动剖视。"
                ),
            )
        )

    findings.extend(_view_review_findings(export_manifest))
    findings.extend(_model_review_findings(export_manifest))

    required_intents = [intent for intent in plan.dimension_intents if intent.required]
    if not required_intents:
        findings.append(
            ReviewFinding(
                severity="ERROR",
                code="NO_REQUIRED_DIMENSIONS",
                message="规则库没有提供必选尺寸意图。",
                recommendation="至少启用 basic_mechanical 模板，并为零件类型添加特征模板。",
            )
        )

    missing_refs = [
        intent.label for intent in required_intents if not intent.standard_refs and intent.required
    ]
    if missing_refs:
        findings.append(
            ReviewFinding(
                severity="INFO",
                code="MISSING_STANDARD_REF",
                message="部分必选尺寸意图尚未关联国标索引：" + "、".join(missing_refs),
                recommendation="后续填充标准库时给这些规则补上 GB/T 条目或企业标准条目。",
            )
        )

    manual_required_intents = [
        intent for intent in required_intents if not _intent_is_dxf_checkable(intent)
    ]
    if manual_required_intents:
        findings.append(
            ReviewFinding(
                severity="INFO",
                code="MANUAL_INTENT_REVIEW",
                message="以下必选标注意图仍需人工确认："
                + "、".join(_intent_label(intent) for intent in manual_required_intents),
                recommendation=(
                    "DXF 初稿不能证明这些工程要求已经满足；需要结合模型、工艺、"
                    "企业规范和人工图纸复核。"
                ),
            )
        )

    if export_manifest.get("mode") == "dry-run":
        findings.append(
            ReviewFinding(
                severity="INFO",
                code="DRY_RUN",
                message="当前没有调用 SolidWorks/AutoCAD，只生成计划和复查报告。",
                recommendation="等接口适配完成后，再切换 live 模式进行真实出图。",
            )
        )

    if export_manifest.get("mode") != "dry-run":
        annotation = _annotation_result(export_manifest)
        if not annotation:
            findings.append(
                ReviewFinding(
                    severity="WARN",
                    code="CAD_ANNOTATION",
                    message="live 流程没有生成初次 CAD 标注清单。",
                    recommendation=(
                        "确认 job 输出中包含 DXF，并检查 SolidWorks 导出的 view outline "
                        "是否可传递给 DXF 标注器。"
                    ),
                )
            )
        elif int(annotation.get("dimensions_added", 0)) <= 0:
            findings.append(
                ReviewFinding(
                    severity="ERROR",
                    code="NO_DXF_DIMENSIONS",
                    message="初次 CAD 标注没有生成任何 DIMENSION 实体。",
                    recommendation=(
                        "优先检查 DXF 几何是否能按视图区域分组，再补充零件特征识别规则。"
                    ),
                )
            )
        else:
            findings.extend(_annotation_review_findings(annotation))
            findings.extend(_dimension_intent_coverage_findings(plan, annotation))

    return findings


def _model_review_findings(export_manifest: JsonObject) -> list[ReviewFinding]:
    model = _model_inspection_result(export_manifest)
    if model is None:
        return []

    status = _text_value(model.get("status"), "")
    if status in {"error", "unavailable"}:
        return [
            ReviewFinding(
                severity="WARN",
                code="MODEL_INSPECTION",
                message="SolidWorks 模型检查未成功：" + _text_value(model.get("error"), status),
                recommendation=(
                    "确认 SolidWorks 已启动、模型路径正确，并重新生成 model_manifest.json。"
                ),
            )
        ]

    findings: list[ReviewFinding] = []
    quality = _text_value(model.get("model_source_quality"), "")
    dimension_count = _int_value(model.get("dimension_count"), 0)
    if quality == "imported_body_without_parametric_dimensions":
        findings.append(
            ReviewFinding(
                severity="INFO",
                code="MODEL_IMPORTED_BODY",
                message="当前 SolidWorks 模型像是导入体，未发现参数化模型尺寸。",
                recommendation=(
                    "自动标注应优先使用包围盒、实体几何识别和人工规则；"
                    "若需要更可靠的台阶、孔深、倒角尺寸，建议补建参数化特征或企业特征模板。"
                ),
            )
        )
    elif status == "inspected" and dimension_count == 0:
        findings.append(
            ReviewFinding(
                severity="INFO",
                code="MODEL_DIMENSIONS_UNAVAILABLE",
                message="SolidWorks 模型检查未收集到显示尺寸。",
                recommendation=(
                    "确认模型尺寸是否被隐藏、是否为导入体，或补充其他 SolidWorks 尺寸读取路径。"
                ),
            )
        )
    return findings


def _model_inspection_result(export_manifest: JsonObject) -> JsonObject | None:
    steps = export_manifest.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("action") == "inspect_model":
            return step
    return None


def _annotation_result(export_manifest: JsonObject) -> JsonObject | None:
    steps = export_manifest.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        annotation = step.get("dxf_annotation")
        if isinstance(annotation, dict):
            return annotation
    return None


def _annotation_review_findings(annotation: JsonObject) -> list[ReviewFinding]:
    annotation_review = annotation.get("annotation_review")
    if not isinstance(annotation_review, dict):
        return []
    findings = annotation_review.get("findings")
    if not isinstance(findings, list):
        return []

    result: list[ReviewFinding] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        result.append(
            ReviewFinding(
                severity=_text_value(finding.get("severity"), "INFO"),
                code=_text_value(finding.get("code"), "DXF_ANNOTATION_REVIEW"),
                message=_text_value(finding.get("message"), "DXF 标注复查存在未命名提示。"),
                recommendation=_text_value(
                    finding.get("recommendation"),
                    "查看 annotation_manifest.json 中的 annotation_review 详情。",
                ),
            )
        )
    return result


def _dimension_intent_coverage_findings(
    plan: DrawingPlan,
    annotation: JsonObject,
) -> list[ReviewFinding]:
    coverage_keys = _annotation_coverage_keys(annotation)
    checkable_intents = [
        intent
        for intent in plan.dimension_intents
        if intent.required and _intent_is_dxf_checkable(intent)
    ]
    missing = [
        intent for intent in checkable_intents if not _intent_is_covered(intent, coverage_keys)
    ]
    if not missing:
        return []

    return [
        ReviewFinding(
            severity="WARN",
            code="DIMENSION_INTENT_COVERAGE",
            message="DXF 初次标注尚未覆盖部分必选标注意图："
            + "、".join(_intent_label(intent) for intent in missing),
            recommendation=(
                "人工复核这些尺寸是否已在原图中存在；后续优先补充对应 DXF 特征识别，"
                "或从 SolidWorks 模型尺寸、剖视图中获取。"
            ),
        )
    ]


def _intent_is_covered(intent: DimensionIntent, coverage_keys: set[str]) -> bool:
    aliases = _intent_coverage_labels(intent)
    if not aliases:
        return False
    if intent.coverage_mode.strip().lower() == "all":
        return aliases.issubset(coverage_keys)
    return bool(aliases.intersection(coverage_keys))


def _intent_is_dxf_checkable(intent: DimensionIntent) -> bool:
    return intent.verification.strip().lower() == "dxf" and bool(_intent_coverage_labels(intent))


def _intent_coverage_labels(intent: DimensionIntent) -> set[str]:
    if intent.coverage_labels:
        return {label.strip() for label in intent.coverage_labels if label.strip()}
    return DXF_COVERAGE_ALIASES.get(intent.feature_type, set())


def _intent_label(intent: DimensionIntent) -> str:
    return f"{intent.label} / {intent.feature_type}"


def _annotation_coverage_keys(annotation: JsonObject) -> set[str]:
    result: set[str] = set()
    result.update(_annotation_labels(annotation))
    return result


def _annotation_feature_types(annotation: JsonObject) -> set[str]:
    features = annotation.get("feature_candidates")
    if not isinstance(features, list):
        return set()
    result: set[str] = set()
    for feature in features:
        if not isinstance(feature, dict):
            continue
        feature_type = feature.get("feature_type")
        if isinstance(feature_type, str) and feature_type.strip():
            result.add(feature_type.strip())
    return result


def _annotation_labels(annotation: JsonObject) -> set[str]:
    result: set[str] = set()
    annotations = annotation.get("annotations")
    if isinstance(annotations, list):
        for annotation_item in annotations:
            if not isinstance(annotation_item, dict):
                continue
            label = annotation_item.get("label")
            if isinstance(label, str) and label.strip():
                result.add(label.strip())

    summary = annotation.get("annotation_summary")
    if isinstance(summary, dict):
        annotations_by_label = summary.get("annotations_by_label")
        if isinstance(annotations_by_label, dict):
            result.update(
                label for label in annotations_by_label if isinstance(label, str) and label.strip()
            )
    return result


def _view_review_findings(export_manifest: JsonObject) -> list[ReviewFinding]:
    result: list[ReviewFinding] = []
    for finding in _raw_view_review_findings(export_manifest):
        severity = _text_value(finding.get("severity"), "INFO")
        code = _text_value(finding.get("code"), "VIEW_REVIEW")
        message = _text_value(finding.get("message"), "视图复查存在未命名提示。")
        recommendation = _text_value(
            finding.get("recommendation"),
            "查看 export_manifest.json 中的 view_review 详情。",
        )
        result.append(
            ReviewFinding(
                severity=severity,
                code=code,
                message=message,
                recommendation=recommendation,
            )
        )
    return result


def _view_review_codes(export_manifest: JsonObject) -> set[str]:
    codes: set[str] = set()
    for finding in _raw_view_review_findings(export_manifest):
        code = finding.get("code")
        if isinstance(code, str) and code.strip():
            codes.add(code.strip())
    return codes


def _view_review_resolved_extra_views(export_manifest: JsonObject) -> bool:
    view_review = _view_review_result(export_manifest)
    if view_review is None or "pending_extra_views" not in view_review:
        return False
    return not _list_of_text(view_review.get("pending_extra_views"))


def _manifest_pending_extra_views(export_manifest: JsonObject) -> list[str]:
    steps = export_manifest.get("steps")
    if not isinstance(steps, list):
        return []
    for step in steps:
        if not isinstance(step, dict):
            continue
        view_review = step.get("view_review")
        if isinstance(view_review, dict):
            return _list_of_text(view_review.get("pending_extra_views")) or _request_ids(
                view_review.get("pending_extra_view_requests")
            )
        if step.get("action") == "create_three_view_drawing":
            return _list_of_text(step.get("pending_extra_views")) or _request_ids(
                step.get("pending_extra_view_requests")
            )
    return []


def _request_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        request_id = item.get("id")
        if isinstance(request_id, str) and request_id.strip():
            result.append(request_id.strip())
    return result


def _view_review_result(export_manifest: JsonObject) -> JsonObject | None:
    steps = export_manifest.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        view_review = step.get("view_review")
        if isinstance(view_review, dict):
            return view_review
    return None


def _raw_view_review_findings(export_manifest: JsonObject) -> list[JsonObject]:
    view_review = _view_review_result(export_manifest)
    if view_review is None:
        return []
    findings = view_review.get("findings")
    if not isinstance(findings, list):
        return []
    return [finding for finding in findings if isinstance(finding, dict)]


def _list_of_text(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _text_value(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _int_value(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def render_review_markdown(plan: DrawingPlan, findings: list[ReviewFinding]) -> str:
    lines = [
        f"# 图纸复查报告：{plan.job_name}",
        "",
        "## 基本信息",
        f"- 零件：{plan.part.name}",
        f"- 类型：{plan.part.category}",
        f"- 视图：{', '.join(plan.views)}",
        f"- 视图规划：{plan.view_plan.get('source', 'unknown')}",
        f"- 计划输出：{', '.join(plan.planned_outputs)}",
        "",
        "## 必选标注意图",
    ]

    for intent in plan.dimension_intents:
        required = "必选" if intent.required else "可选"
        refs = ", ".join(intent.standard_refs) if intent.standard_refs else "待补充"
        lines.append(f"- [{required}] {intent.label} / {intent.feature_type} / 标准索引：{refs}")

    lines.extend(["", "## 发现的问题"])
    if findings:
        lines.extend(finding.to_markdown() for finding in findings)
    else:
        lines.append("- 暂未发现问题。")

    lines.extend(
        [
            "",
            "## 下一步人工复核",
            "- 确认零件类型是否正确。",
            "- 确认基准选择、关键加工面和装配尺寸。",
            "- 确认未注公差、粗糙度、热处理和材料要求。",
        ]
    )
    return "\n".join(lines) + "\n"
