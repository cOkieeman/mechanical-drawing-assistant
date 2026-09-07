# ViewPlanner

ViewPlanner 用于把“固定三视图”升级为“按标准 profile 和零件类型规划视图”。

## 输入

- `part.category`
- `part.process`
- `drawing_standard`
- `standard_profile`
- job 中可选的 `views`

## 输出

`drawing_plan.json` 中会包含：

```json
{
  "views": ["front", "left"],
  "view_plan": {
    "source": "category_rule",
    "projection_method": "first_angle",
    "layout_rule": "front_top_below_left_right",
    "recommended_extra_views": ["section_view_for_internal_bore"],
    "extra_view_requests": [
      {
        "id": "section_view_for_internal_bore",
        "view_type": "section",
        "base_view": "front",
        "target_feature": "internal_bore",
        "placement_hint": "place_near_front_or_replace_left_when_clear",
        "automation_status": "planned_not_implemented",
        "geometry_hint": {
          "schema_version": 1,
          "status": "hint_only",
          "coordinate_space": "base_view_outline_normalized",
          "units": "ratio",
          "requires_manual_review": true,
          "primitive": {
            "type": "section_line",
            "label": "A-A",
            "points": [{"x": 0.12, "y": 0.5}, {"x": 0.88, "y": 0.5}]
          }
        }
      }
    ],
    "standard_refs": ["GB/T 14692-2008", "GB/T 4458.1-2002"]
  }
}
```

## 规则来源

- `knowledge/standards/profiles/gb_mechanical_drawing.json`
- `src/mechanical_drawing_assistant/view_planner.py`

## 当前模板

- `turned_mounting_sleeve`：主视图 + 左视图，建议评估内孔剖视。
- `pulley`：主视图 + 左视图，建议评估轮槽和内孔剖视。
- `shaft`：主视图 + 左视图，建议评估键槽、螺纹、中心孔局部表达。
- `plate`：默认三视图，孔阵列或复杂局部建议放大。
- `motor_mounting_plate`：默认三视图，孔组或长圆孔密集区域建议局部放大。
- 未知类型：使用 GB profile 默认 `front/top/left`。

## 额外视图请求

`recommended_extra_views` 继续保留为旧版字符串列表，用于兼容已有 review 和旧 manifest。新的 `extra_view_requests` 用于描述后续可交给 SolidWorks API 尝试生成的额外表达：

- `id`：稳定请求 ID，应与 `recommended_extra_views` 中的字符串一致。
- `view_type`：`section`、`detail` 或后续扩展类型。
- `base_view`：建议基于哪个标准视图生成。
- `target_feature`：希望表达的特征，例如 `internal_bore`、`dense_hole_pattern`。
- `placement_hint`：排布建议，当前只作为 manifest/review 提示。
- `automation_status`：当前为 `planned_not_implemented`，表示尚未真实调用 SolidWorks 自动生成。
- `api_hint`：开发提示，不等于已经实现的 API 调用。
- `geometry_hint`：规则层几何意图，使用 `base_view_outline_normalized` 比例坐标；用于后续生成 SolidWorks 草图元素前的准备，不代表真实图纸坐标。

`geometry_hint.primitive.type` 当前支持：

- `section_line`：剖视线意图，例如穿过轴类或套筒类零件轴线的 `A-A`。
- `detail_circle`：局部放大圆意图，例如包住孔组、长圆孔、键槽或螺纹局部区域。

SolidWorks live 出图时，adapter 会尝试根据已插入视图的 `outline_m` 生成 `resolved_geometry_hint`，单位为米。它仍然只是草图准备信息，不会让 ViewReview 判断额外视图已经实现。

## 人工覆盖

如果 job 中显式写了：

```json
"views": ["front", "top", "left"]
```

则 `view_plan.source` 为 `job_override`，系统按人工指定视图执行，同时在复查中保留视图表达检查。

## 边界

当前 ViewPlanner 不分析真实 SolidWorks 几何，只做规则模板推荐。自动剖视图、局部放大和断裂画法需要后续接入 SolidWorks API。
