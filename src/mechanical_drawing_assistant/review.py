from __future__ import annotations

from mechanical_drawing_assistant.models import DrawingPlan, JsonObject, ReviewFinding


def review_plan(plan: DrawingPlan, export_manifest: JsonObject) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []

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

    if len(plan.views) < 3:
        findings.append(
            ReviewFinding(
                severity="WARN",
                code="VIEW_SET",
                message="当前视图少于三视图。",
                recommendation=(
                    "对常规机加工零件优先保留 front/top/left，必要时再加剖视或局部放大。"
                ),
            )
        )

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

    return findings


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


def render_review_markdown(plan: DrawingPlan, findings: list[ReviewFinding]) -> str:
    lines = [
        f"# 图纸复查报告：{plan.job_name}",
        "",
        "## 基本信息",
        f"- 零件：{plan.part.name}",
        f"- 类型：{plan.part.category}",
        f"- 视图：{', '.join(plan.views)}",
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
