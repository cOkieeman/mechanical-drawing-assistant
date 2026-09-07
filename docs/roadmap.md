# Roadmap

## 阶段 1：初次 CAD 标注

状态：已具备 MVP，当前作为历史基线维护。

- SolidWorks 生成 `front/top/left` 三视图。
- 导出 `SLDDRW/PDF/DWG/DXF`。
- DXF 初次标注生成 `DIMENSION` 实体。
- 输出 `annotation_manifest.json` 和复查报告。

## 阶段 2：细化研究

状态：进行中。当前重点是模型驱动尺寸、板件/套筒特征模板、标注排布避让和复查规则增强。

目标：让标注逐步接近机械工程师出图习惯。

- 对比人工图纸，记录漏标、错标、多标。
- 建立零件类型模板：套筒、轴类、带轮、板件、支架。
- 建立特征模板：孔、槽、台阶、倒角、圆角、螺纹孔、阵列孔。
- 增强审查规则：重复标注、封闭尺寸链、尺寸遮挡、标题栏缺项。
- 当前已在 `电机安装板` 样例中实现模型驱动外形/孔/腰孔初稿标注、基准边定位和 callout 避让。
- 板件、套筒、轴类 `dimension_intents` 已具备 MVP；下一步把 `coverage_labels/coverage_mode` 推广到更多真实样例，并继续增强尺寸链和视图合理性复查。

## 阶段 3：AutoCAD 写回与样式规范

状态：未开始正式实现。当前只有 DXF 侧 DIMSTYLE/图层初稿。

目标：让 AutoCAD 端可以直接接手。

- 通过 AutoCAD COM 或脚本统一 `DIMSTYLE`、图层、文字高度、箭头样式。
- 将 annotated DXF 能力扩展到 DWG 写回或 DWG 另存。
- 增加图框、比例、标题栏、技术要求规范化。

## 阶段 4：工程知识库

状态：进行中。已有 GB 索引、profile 和部分特征库，仍需企业规则和适用范围说明。

目标：沉淀本地标准、企业规则和操作经验。

- 本地维护国标索引、企业标准索引、常用技术要求模板。
- 为每类零件配置必标尺寸、可选尺寸和人工确认项。
- 记录每个标注规则的来源、适用范围和风险说明。

## 阶段 5：Web UI 与桌面分发

状态：完成内部稳定分发版。已具备 PyInstaller one-dir `mda.exe`、本地 Web UI、双击启动脚本、诊断/日志/支持包、release zip、内置 `knowledge/samples` 资源定位、exe smoke 和 release 解压 smoke。代码签名、安装器、自动更新和公开发布页后置。

目标：让非开发使用者能更顺手地运行流程。

- 提供本地 Web UI，用于选择 SolidWorks 文件、job 配置、运行出图、查看复查报告。
- 提供 exe 或安装包，封装 Python 环境和命令入口。
- 保留 CLI/MCP 作为自动化和 Codex 工作流入口。

## 阶段 6：SolidWorks 出图稳定化

状态：第二阶段完成。当前已把视图是否超出图纸边界、是否超出图纸安全区、缺少 `outline_m`、右视图第一角法位置/对齐、失败视图排障信息和 SolidWorks sheet/view fake COM 兼容纳入测试基线。

目标：让真实零件生成工程图时，视图、比例、图框、安全区和标题栏先稳定，再继续推进自动标注。

- 建立视图稳定验收基线：必需视图、第一角法位置、重叠、图纸边界、安全区、标题栏、标注空间。
- 优先使用 SolidWorks 当前 sheet 信息；缺失时使用 GB profile 中的图幅和安全边距 fallback。
- 后续继续做真实零件 live smoke 样例，并把剖视/局部放大从 geometry hint 推进到 SolidWorks 草图/选择集小样。
