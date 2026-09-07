# Turned Mounting Sleeve 复盘记录

日期：2026-07-06
对象：本地 `vul_lizhu_job.sample.json` 对应的安装筒/套筒类样例
边界：真实 CAD/SLDPRT/DWG 文件不进入公开仓库，本文件只记录规则和问题。

## 当前生成能力

- SolidWorks live 可生成 `front/top/left` 工程图并导出 `SLDDRW/PDF/DWG/DXF`。
- ViewPlanner 对 `turned_mounting_sleeve` 默认建议 `front/left`，并提示评估内孔剖视。
- DXF 初次标注可输出总体尺寸、端面圆直径、内孔候选和台阶长度候选。
- `annotation_summary` 和 `annotation_review` 会记录视图覆盖、特征覆盖、未标候选和重复 ID 风险。
- Review 会检查视图排布、重叠、标题栏风险、视图过小、标注预留空间和必选标注意图覆盖。

## 套筒类图纸应关注的表达

- 主视图：优先表达轴向轮廓、总长、台阶长度、倒角/圆角。
- 端面视图：表达外圆、内孔、端面安装孔或槽。
- 剖视图：内孔、内台阶、配合孔、隐藏结构重要时应优先评估。
- 标注重点：总长、主要外径、内孔直径、台阶长度、端面安装特征、倒角/圆角。
- 人工确认：配合公差、形位公差、粗糙度、材料/热处理、未注公差和数量。

## 当前差距

| 项目 | 当前状态 | 后续动作 |
| --- | --- | --- |
| 内孔表达 | 只能从端面同心圆候选推断 | 接入剖视图或 SolidWorks 模型特征 |
| 台阶长度 | 从轮廓视图竖向边界推断 | 结合轴线、基准面和隐藏线过滤误识别 |
| 标题栏 | 使用 SolidWorks sheet 尺寸 + 近似标题栏区域 | 后续读取模板真实标题栏几何 |
| 标注空间 | 已检查靠边和标题栏附近风险 | 继续检查尺寸文字、箭头和几何遮挡 |
| 加工基准 | 尚不能自动判断 | 建立企业规则和人工复核字段 |

## 近期验收目标

- `annotation_manifest.json` 中能看到 `outer_diameter`、`bore_diameter`、`step_length` 候选。
- `annotation_manifest.json` 中 `annotation_review.status` 不应为 `error`。
- `annotation_review.findings` 中如果出现 `DXF_VIEW_WITHOUT_DIMENSIONS`，需要人工判断该视图是否只是辅助视图。
- `review_report.md` 能通过 `DIMENSION_INTENT_COVERAGE` 提示套筒关键标注意图是否缺失。
- live 生成图纸不出现视图重叠、标题栏侵入和明显视图过小。
- 人工复查后，把漏标/误标继续沉淀到 `turned_mounting_sleeve.json` 和 DXF 识别规则。
