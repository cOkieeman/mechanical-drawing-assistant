# 最小闭环流程

## 阶段 1：SolidWorks 出图

目标是从 `.SLDPRT` 或 `.SLDASM` 生成工程图：

- 使用公司图框模板。
- 创建 front/top/left 三视图，按主视图、俯视图在主下、左视图在主右排布。
- 对轴类、带轮、板类等零件选择必要剖视或局部放大。
- 记录所有候选标注意图，不在这一层猜尺寸值。

## 阶段 2：导出

输出至少包含：

- `.SLDDRW`：可人工继续编辑的 SolidWorks 工程图。
- `.DWG`：给 AutoCAD 继续标注和整理。
- `.DXF`：给本地几何/标注检查程序读取。
- `.PDF`：用于视觉复查、归档和给加工方确认。

## 阶段 3：复查

第一版复查先回答这些问题：

- 是否至少有三视图。
- 是否有外形尺寸、基准、孔/槽/倒角/圆角等必选标注意图。
- 是否有未注尺寸公差、未注形位公差、粗糙度或技术要求提示。
- 是否存在需要人工确认的关键加工面、配合、公差和装配基准。
- DXF 中是否已经存在 `DIMENSION` 实体。若为 0，说明当前只是三视图线框，尚未生成加工尺寸。

## 阶段 4：SolidWorks 模型依据层

在自动标注前，先从 SolidWorks 模型生成 `model_manifest.json`：

- 读取模型路径、标题、文档类型和保存状态。
- 读取模型包围盒，输出米制和毫米尺寸。
- 遍历特征树，收集特征类型、特征名和显示尺寸候选。
- 只作为尺寸依据和复查证据，不直接替代机械工程师判断。

可单独运行：

```powershell
uv run mda inspect-solidworks-model `
  --model path/to/model.SLDPRT `
  --out path/to/model_manifest.json
```

后续标注器应优先使用 `model_manifest.json` 中的模型尺寸和特征，再回退到 DXF 几何。

## 阶段 5：初次 CAD 标注

第一版自动标注先做保守、低风险初稿：

- 读取 SolidWorks 导出的 DXF。
- 根据 `outline_m` 将 DXF 几何分到 front/top/left 视图。
- 自动写入主视图总长、端面外径、内孔直径等高置信尺寸。
- 台阶长度、重复投影视图和额外同心圆先只作为候选特征进入报告。
- 另存 `*-annotated.dxf`，不覆盖原始 DWG/DXF。
- 输出 `annotation_manifest.json`，记录每个尺寸、候选特征、来源和数值。
- `annotation_summary` 统计各视图、各特征类型和各尺寸类型的数量。
- `annotation_review` 检查 DXF 初次标注是否存在未标视图、重复尺寸 ID、候选特征未生成尺寸等问题。

如果已经有 DXF 和 `export_manifest.json`，也可以独立运行：

```powershell
uv run mda annotate-dxf path/to/input.dxf `
  --output-dxf path/to/input-annotated.dxf `
  --manifest path/to/export_manifest.json `
  --out path/to/annotation_manifest.json

uv run mda review --job path/to/job.json `
  --knowledge knowledge `
  --annotation path/to/annotation_manifest.json `
  --out path/to/review_report.md
```

## 阶段 6：逐步填库

后续再补：

- 国标索引和企业标准索引。
- 零件类型模板：板件、轴类、带轮、丝杆、支架、钣金件。
- 特征模板：孔、槽、键槽、螺纹孔、沉孔、倒角、圆角、阵列孔。
- 审查规则：漏标、重复标注、尺寸链、文字遮挡、图层和样式。
