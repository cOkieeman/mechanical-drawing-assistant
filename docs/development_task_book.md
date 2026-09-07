# 机械制图自动标注助手后续开发任务书

版本：v0.1
日期：2026-07-06
项目：Mechanical Drawing Assistant
仓库：https://github.com/cOkieeman/mechanical-drawing-assistant

## 1. 项目背景

当前机械制图工作流中，用户使用 SolidWorks 建模并生成工程图，再导出 DWG 进入 AutoCAD 标注。实际问题是图纸数量多、标注繁杂、规则分散，人工标注容易漏标、错标、重复标注或不符合加工习惯。

本项目目标是建立一个本地机械制图辅助系统，使其能够基于 SolidWorks 模型、DXF/DWG 图纸、国标索引和本地规则库，生成可人工继续修正的二维机械工程图初稿，并逐步具备机械工程师式的视图规划、标注、复查能力。

## 2. 当前基础能力

截至当前阶段，项目已经具备以下能力：

- Python/uv 项目结构、CLI 和 MCP server。
- SolidWorks COM live 出图：生成工程图，插入标准视图，导出 `SLDDRW/PDF/DWG/DXF`。
- 默认第一角法排布：主视图、俯视图在主下、左视图在主右。
- DXF 初次标注：读取 SolidWorks 导出的 DXF，生成 `DIMENSION` 实体并另存 `*-annotated.dxf`。
- `annotation_manifest.json`：记录自动生成的尺寸来源和数量。
- GB 标准索引：保存标准编号、用途、状态和官方链接，不保存标准正文。
- `GB_MECHANICAL_DRAWING` profile：作为 ViewPlanner、标注器和 review 的规则入口。
- ViewPlanner MVP：按零件类型推荐视图，并提示剖视图、断面图、局部放大等人工复核项。
- ViewReview MVP：复查第一角法排布、视图对齐、视图重叠和 A3 标题栏近似侵入。
- `turned_mounting_sleeve` 特征库：记录套筒总长、外径、内孔、台阶长度、端面特征和剖视确认意图。
- DXF 标注器可输出 `feature_candidates`，初步识别端面圆、外径、内孔和台阶长度。
- GitHub 仓库和 CI：pytest、ruff、format、ty 均可在 CI 中验证。

补充状态（2026-07-07）：

- 根目录新增活动计划文件 `task_plan.md/findings.md/progress.md`，作为 `planning-with-files-zh` 的默认入口。
- `电机安装板` 样例已进入 model-driven DXF 标注：当前可输出 14 条 annotation，其中 12 条为 `DIMENSION`、2 条为 `MTEXT callout`。
- `电机安装板` 已补充孔/槽中心线到基准边的定位尺寸：`thread_hole_edge_x/y`、`slot_edge_x/y`。
- 标注排布已具备第一版包围盒避让：callout 写入 `layout.text_box/collision_count`。
- `dimension_intents` 规则库已具备 MVP：新增电机安装板和轴类模板，支持 `coverage_labels/coverage_mode/verification`，review 可按规则检查自动标注覆盖。
- AutoCAD/DWG 写回仍未正式实现，当前只完成 DXF 另存和样式初稿。
- P9 内部稳定分发版已完成：PyInstaller one-dir `mda.exe`、本地 Web UI、双击启动脚本、诊断/日志/支持包、release zip、内置 `knowledge/samples` 资源定位、exe smoke 和 release 解压 smoke 已跑通。

## 3. 总体目标

建立一个可本地运行、可迭代扩展的机械制图辅助系统，最终实现：

- 根据零件类型和加工工艺自动规划工程图视图。
- 按 GB 机械制图标准索引和企业规则生成二维工程图初稿。
- 自动生成基础尺寸、特征尺寸、公差提示、粗糙度提示和技术要求提示。
- 自动复查视图、标注、图层、样式、标题栏、尺寸链和漏标风险。
- 输出可在 SolidWorks/AutoCAD 中继续编辑的工程图文件。
- 未来提供 Web UI 和 exe，降低非开发用户使用门槛。

## 4. 开发原则

- 不覆盖用户原始 CAD 文件。
- 不提交真实客户图纸、SolidWorks 模型、DWG/DXF/PDF 输出到公开仓库。
- 不提交国标正文，只保存标准索引、摘要和本地规则引用。
- 每轮开发必须有可验证产物：测试、manifest、review report 或实际图纸输出。
- 先做能跑通的初稿，再逐步靠真实图纸和人工复核提升工程质量。
- AI 只做辅助判断，关键加工基准、公差、配合、粗糙度仍需人工确认。

## 5. 范围定义

### 5.1 本阶段范围

- 视图规划器升级。
- SolidWorks 出图准确性提升。
- DXF 初次标注质量提升。
- 标准库和规则库持续补充。
- 复查报告增强。
- AutoCAD 写回方案研究与 MVP。

### 5.2 暂不作为当前重点

- Web UI。
- exe 打包。
- 完整三维特征识别。
- 全自动生成最终加工图。
- 完整国标条款解析和标准正文内置。

这些内容作为后续阶段保留。

## 6. 技术路线

```text
SolidWorks 模型
  -> ViewPlanner 规划视图
  -> SolidWorksAdapter 生成工程图
  -> 导出 SLDDRW/PDF/DWG/DXF
  -> DxfAdapter 初次标注
  -> annotation_manifest.json
  -> ReviewEngine 复查报告
  -> 人工复核与规则沉淀
```

核心模块：

- `view_planner.py`：视图规划。
- `adapters/solidworks.py`：SolidWorks 出图与导出。
- `adapters/dxf.py`：DXF 读取、标注、检查。
- `adapters/autocad.py`：AutoCAD/DWG 规范化与写回。
- `knowledge/`：标准索引、特征库、零件模板。
- `review.py`：复查报告。
- `mcp_server.py`：Codex/MCP 集成入口。

## 7. 分阶段任务

### 阶段 1：视图规划与 SolidWorks 出图准确性

目标：让系统能按零件类型和 GB profile 决定需要哪些视图，并让 SolidWorks 实际出图更稳定。

任务：

- 完善 ViewPlanner 零件类型模板：套筒、轴类、带轮、板件、支架。
- 支持 job 人工覆盖 views，同时保留 review 提醒。
- 增加视图规划输出字段：投影法、布局规则、推荐剖视、推荐局部放大、标准引用。
- SolidWorks 出图后复查视图：位置、对齐、重叠、标题栏侵入、比例过小。
- 为套筒/带轮类生成剖视图占位方案。

验收：

- `drawing_plan.json` 包含完整 `view_plan`。
- `review_report.md` 能说明视图来源和剖视建议。
- 至少 3 类零件能得到不同的推荐视图。

### 阶段 2：特征库与尺寸意图升级

目标：从“总体尺寸初标注”升级为“按特征生成尺寸意图”。

任务：

- 建立特征模板：孔、槽、键槽、台阶、倒角、圆角、螺纹孔、沉孔、阵列孔。
- 建立零件模板：套筒、轴、带轮、板件、支架。
- 将 `dimension_intents` 与标准索引、视图、推荐放置位置关联。
- 输出尺寸意图置信度和人工确认项。

验收：

- `annotation_manifest.json` 能区分总体尺寸和特征尺寸。
- review 能指出未覆盖的必标特征。

### 阶段 3：SolidWorks 模型尺寸与几何信息接入

目标：减少 DXF 几何猜测，优先从 SolidWorks 模型或工程图 API 获取可靠信息。

任务：

- 尝试导入模型尺寸到工程图。
- 读取模型 bounding box、质量属性、主要方向、草图/特征名。
- 识别旋转体、板件、孔阵列等基础类型。
- 记录 SolidWorks API 调用结果到 manifest，方便调试。

验收：

- 真实模型可输出基础几何摘要。
- 尺寸来源能区分 `solidworks_model`、`solidworks_drawing`、`dxf_geometry`。

### 阶段 4：CAD 标注样式与 AutoCAD 写回

目标：让输出图纸更接近 AutoCAD 可直接接手的状态。

任务：

- 建立图层规范：轮廓线、中心线、尺寸线、文字、辅助线。
- 建立 DIMSTYLE：文字高度、箭头大小、比例、单位。
- 通过 AutoCAD COM 打开 DWG/DXF 并另存。
- 将 annotated DXF 能力扩展为 DWG 写回或 DWG 另存。

验收：

- 自动生成的尺寸在 AutoCAD 中样式一致。
- 不覆盖原始 DWG。
- review 能检查 DIMSTYLE、图层和文字高度。

### 阶段 5：复查引擎增强

目标：从“流程复查”升级为“图纸质量复查”。

任务：

- 检查漏标、重复标注、封闭尺寸链。
- 检查尺寸文字遮挡、视图重叠、标题栏侵入。
- 检查是否缺未注公差、粗糙度、材料、数量、技术要求。
- 形成分级 finding：ERROR、WARN、INFO。

验收：

- review report 能清楚列出可操作问题。
- 每个 finding 有规则来源、建议和人工确认项。

### 阶段 6：标准库与企业规则库

目标：把机械工程师的经验沉淀为可追踪规则。

任务：

- 扩展 GB 标准索引。
- 建立企业标准 profile。
- 建立常用技术要求模板。
- 为每条规则记录适用范围、来源、风险。

验收：

- 每个自动判断能追溯到标准索引或企业规则。
- 规则库不包含受版权保护的标准正文。

### 阶段 7：使用界面和分发

目标：让非开发用户能稳定使用。

任务：

- 已完成 P9-S1：命令行 `mda.exe` alpha 打包骨架。
- 已完成 P9-S2：本地 Web UI，可选择样例 job、填写自定义 job、运行 dry-run/live、查看输出和复查报告。
- 已完成 P9-S3：release zip，包含 `start_mda_webui.cmd`、`run_diagnose.cmd`、内置资源和文档。
- 已完成 P9-S4：日志、运行记录和支持包。

验收：

- 用户无需命令行即可运行基础流程。
- 打包产物不包含用户 CAD 文件或授权标准正文。

## 8. 近期开发优先级

建议下一轮优先做：

1. 已完成本轮 MVP：ViewPlanner 推荐的剖视图/局部放大已写入 manifest/review 三态字段，并新增结构化 `extra_view_requests`。
2. 已启动：针对 `turned_mounting_sleeve` 做真实图纸复盘，记录在 `docs/project/turned_mounting_sleeve_review.md`。
3. 已完成 MVP：DXF 标注器识别端面圆、内孔、外径、台阶长度，并写入 `feature_candidates`。
4. 已完成 MVP：SolidWorks 出图复查增强比例过小、标题栏区域来源、视图外侧标注预留空间。
5. 已完成几何准备层：ViewPlanner 输出 normalized `geometry_hint`，SolidWorksAdapter 输出图纸坐标 `resolved_geometry_hint`；下一步基于 `MDA_SOLIDWORKS_EXPERIMENTAL_EXTRA_VIEWS` 做真实 section line/detail circle 草图实体与选择集小样，让实际生成的额外视图能写入 `extra_view_request_id` 并清空 `pending_extra_views`。

## 9. 验证要求

每轮开发至少运行：

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```

涉及 SolidWorks live 时额外运行：

```powershell
uv run mda run --job samples/jobs/vul_lizhu_job.sample.json --knowledge knowledge --out-dir output/vul-live --live
uv run mda inspect-dxf output/vul-lizhu/lizhu-anzhuangtong-live-three-view-annotated.dxf --out output/vul-live/annotated-dxf-inspect.json
```

## 10. 风险与约束

- SolidWorks/AutoCAD COM 行为受本机版本、模板、语言环境影响。
- DXF 几何标注只能作为初稿，不能替代模型尺寸和工程判断。
- 国标状态和标准编号需要定期复查。
- 真实加工图涉及企业经验，必须通过人工样本持续校正。
- 自动剖视、局部放大、断裂画法需要更深入的 SolidWorks API 适配。

## 11. 交付物

- 可运行 CLI：`mda`。
- 可集成 MCP：`mda-mcp`。
- 标准索引和 profile：`knowledge/standards/`。
- 特征库：`knowledge/features/`。
- 样例 job：`samples/jobs/`。
- 出图 manifest、标注 manifest、复查报告。
- GitHub CI 和开发文档。

## 12. 任务书维护方式

- 每完成一个阶段，更新本任务书状态或拆分为 issue。
- 每次真实图纸复盘后，将发现沉淀到 `docs/project/findings.md` 或规则库。
- 不把临时想法直接写进代码，先进入任务书、roadmap 或 issue。
