# ViewReview

ViewReview 用于复查 SolidWorks 实际生成的工程图视图位置。它不直接操作 SolidWorks，只读取 `export_manifest.json` 中的视图 JSON 数据，因此可以用单元测试稳定验证。

## 输入

`SolidWorksAdapter.create_three_view_drawing()` 会记录：

```json
{
  "inserted_views": [
    {
      "view": "front",
      "position_m": [0.13, 0.17],
      "outline_m": [0.08, 0.13, 0.18, 0.21]
    }
  ],
  "failed_views": []
}
```

ViewReview 同时读取 `drawing_plan.json` 中的：

- `views`
- `view_plan.projection_method`
- `view_plan.layout_rule`
- `view_plan.recommended_extra_views`
- `view_plan.extra_view_requests`
- `standard_profile.sheet.preferred_size`

SolidWorks live 模式还会尽量读取当前 sheet 信息：

- `sheet_info.sheet_size_m`
- `sheet_info.safe_area_m`
- `sheet_info.title_block_zone_m`
- `sheet_info.properties`

## 当前检查项

- 计划视图是否成功插入。
- 第一角法排布：
  - 主视图 `front`。
  - 俯视图 `top` 应在主视图下方。
  - 左视图 `left` 应在主视图右侧。
  - 如果使用 `right`，按第一角法应在主视图左侧。
- 已插入视图是否带有可用 `outline_m`；缺失时输出 `VIEW_OUTLINE_MISSING`，避免边界、安全区和比例检查被静默跳过。
- 俯视图和主视图的 X 方向对齐。
- 左视图和主视图的 Y 方向对齐。
- 右视图和主视图的 Y 方向对齐。
- 视图轮廓是否重叠或小于安全间距。
- 视图是否超出图纸边界。
- 视图是否超出图纸安全区。
- 视图是否显示过小。
- 视图是否靠近图纸边界，导致外侧标注预留空间不足。
- 视图是否侵入或靠近标题栏区域。
- ViewPlanner 推荐的剖视图、断面图或局部放大是否已经生成；若未生成，则写入 `VIEW_PENDING_EXTRA`。

## 输出

live 出图时，`export_manifest.json` 的 SolidWorks step 会包含：

```json
{
  "view_review": {
    "status": "passed",
    "projection_method": "first_angle",
    "layout_rule": "front_top_below_left_right",
    "expected_views": ["front", "top", "left"],
    "inserted_views": ["front", "left", "top"],
    "recommended_extra_views": ["detail_view_for_dense_hole_pattern"],
    "extra_view_requests": [
      {
        "id": "detail_view_for_dense_hole_pattern",
        "view_type": "detail",
        "base_view": "top",
        "geometry_hint": {
          "schema_version": 1,
          "status": "hint_only",
          "coordinate_space": "base_view_outline_normalized",
          "units": "ratio",
          "requires_manual_review": true,
          "primitive": {
            "type": "detail_circle",
            "center": {"x": 0.5, "y": 0.5},
            "radius": 0.32
          }
        }
      }
    ],
    "implemented_extra_views": [],
    "pending_extra_views": ["detail_view_for_dense_hole_pattern"],
    "pending_extra_view_requests": [
      {
        "id": "detail_view_for_dense_hole_pattern",
        "view_type": "detail",
        "base_view": "top"
      }
    ],
    "safe_area_m": [0.006, 0.006, 0.414, 0.291],
    "safe_area_source": "solidworks_sheet_safe_area",
    "title_block_source": "solidworks_sheet_title_block",
    "annotation_space_m": 0.018,
    "checks": [
      "required_views",
      "view_geometry_fields",
      "projection_layout",
      "view_overlap",
      "sheet_bounds",
      "safe_area"
    ],
    "findings": []
  }
}
```

这些 findings 会进入 `review_report.md`，用于人工复核。
`checks` 用于说明本轮实际执行了哪些复查项，避免把“没有发现问题”误解为“所有规则都已实现”。

## 额外视图状态

ViewPlanner 只负责提出 `recommended_extra_views`，例如 `section_view_for_internal_bore` 或 `detail_view_for_dense_hole_pattern`。当前 SolidWorksAdapter 还不会自动创建剖视图、断面图或局部放大，因此 ViewReview 会把这些推荐拆成三类：

- `recommended_extra_views`：规则库推荐评估的额外表达。
- `implemented_extra_views`：已经在 `inserted_views` 中匹配到的额外表达。
- `pending_extra_views`：推荐了但本轮没有生成的额外表达。
- `pending_extra_view_requests`：仍未生成的结构化请求，保留 `id`、`view_type`、`base_view` 等上下文。

只有 `pending_extra_views` 非空时才输出 `VIEW_PENDING_EXTRA`。如果后续 SolidWorks 自动剖视或局部放大接入，只要在插入视图 JSON 中写入 `extra_view_request_id` 或对应推荐标识，ViewReview 就不会再把它报告为未执行。

`geometry_hint` 和 `resolved_geometry_hint` 不会清空 pending：

- `geometry_hint` 来自 ViewPlanner，使用 normalized ratio，只说明应该尝试的剖视线或局部放大圆意图。
- `resolved_geometry_hint` 来自 SolidWorksAdapter，基于已插入视图 `outline_m` 估算图纸坐标，单位为米。
- 只有 SolidWorks 真正插入了额外视图，并在 `inserted_views` 写入 `extra_view_request_id`，才会被计入 `implemented_extra_views`。

这条边界很重要：几何 hint 是下一步自动创建所需的准备材料，不是加工图表达已经完成的证据。

## 边界

- 标题栏检查优先使用 SolidWorks sheet 尺寸和 `title_block_zone_m`；若没有 sheet 信息，则按 A3 右下角 `180 mm x 60 mm` 近似区域判断。
- 安全区检查优先使用 SolidWorks `sheet_info.safe_area_m`；若没有，则使用标准 profile 中的 `sheet.safe_margin_mm`，再退回 6 mm。
- `VIEW_INSERT_FAILED` 会保留 `failed_views` 中的 `status`、`last_error`、`error`、`candidates` 等排障字段；仍可能同时出现 `VIEW_MISSING`，前者说明 COM 插入失败，后者说明计划视图未落图。
- 当前 `title_block_zone_m` 仍是区域近似值，尚未解析模板中真实标题栏线框。
- 视图比例、剖视图、局部放大、断裂画法还没有自动生成。
- ViewReview 只能判断视图层面的几何关系，不能判断尺寸是否完整或加工基准是否合理。
