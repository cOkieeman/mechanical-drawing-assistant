# Mechanical Drawing Assistant

本项目用于搭建一条本地机械制图辅助闭环：

1. 从 SolidWorks 模型/历史 DWG 建立出图任务。
2. 生成三视图、标注意图和输出清单。
3. 导出 DWG/PDF 或先 dry-run。
4. 复查图纸是否缺少基础尺寸、视图、标准索引和人工复核项。

第一版不直接修改原始 DWG，也不依赖 AI 猜尺寸。尺寸值后续必须从 SolidWorks/AutoCAD API 或 DXF 几何中取得。

## 快速运行

```powershell
uv run mda run --job samples/jobs/pulley_job.sample.json --knowledge knowledge --out-dir output/demo
```

运行后会生成：

- `output/demo/drawing_plan.json`
- `output/demo/model_manifest.json`（live 且 SolidWorks 模型检查成功时生成）
- `output/demo/export_manifest.json`
- `output/demo/annotation_manifest.json`（live 且 DXF 标注成功时生成）
- `output/demo/review_report.md`

## 仓库入口

- [仓库结构](docs/repository.md)
- [后续开发任务书](docs/development_task_book.md)
- [最小闭环流程](docs/workflow.md)
- [视图规划器](docs/view_planner.md)
- [视图复查器](docs/view_review.md)
- [路线图](docs/roadmap.md)
- [标准库](docs/standards.md)
- [MCP 接入](docs/mcp.md)
- [第三方项目接入策略](docs/integrations.md)
- [变更记录](CHANGELOG.md)
- [贡献说明](CONTRIBUTING.md)

## SolidWorks Live 测试

电脑已验证可通过 COM 连接已启动的 SolidWorks。使用 `vul` 样例：

```powershell
uv run mda run --job samples/jobs/vul_lizhu_job.sample.json --knowledge knowledge --out-dir output/vul-live --live
uv run mda inspect-dxf output/vul-lizhu/lizhu-anzhuangtong-live-three-view.dxf --out output/vul-live/generated-dxf-inspect.json
```

默认只连接已经启动的 SolidWorks，不会自动拉起软件。若需要让工具在没有活动 COM 实例时尝试启动 SolidWorks，可显式设置：

```powershell
$env:MDA_LAUNCH_SOLIDWORKS='1'
$env:MDA_SOLIDWORKS_VISIBLE='1'
uv run mda diagnose
```

当前 live 流程会生成三视图并导出：

- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view.SLDDRW`
- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view.pdf`
- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view.dwg`
- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view.dxf`
- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view-annotated.dxf`

live 流程会先尝试生成 `model_manifest.json`，记录 SolidWorks 模型包围盒、
特征树摘要和显示尺寸候选。这个文件是后续从“DXF 几何猜尺寸”升级到
“按模型特征和尺寸出图”的基础。

也可以单独检查当前已打开或指定路径的 SolidWorks 模型：

```powershell
uv run mda inspect-solidworks-model `
  --model "I:/codex-Fa/Fa-v1.9/9.个人工作/vul/立柱安装筒.SLDPRT" `
  --out output/vul-live/model_manifest.json
```

DXF 初次标注有两种策略：

- `conservative_standard_draft`：没有参数化模型尺寸时，只自动写入高置信尺寸，例如主视图总长、端面外径和内孔直径；台阶长度、重复投影视图和额外同心圆先作为候选特征进入报告。
- `model_driven_standard_draft`：存在 `model_manifest.json` 且模型有参数化尺寸时，优先使用 SolidWorks 模型值覆盖 DXF 尺寸文字；当前可写入板件外形长宽、厚度、中心孔直径、M 螺纹孔和孔距等基础尺寸。

manifest 会包含 `annotation_summary` 和 `annotation_review`，用于追踪视图覆盖、特征覆盖和未标候选。
这只是初稿尺寸，不代表最终加工图已经完整。

也可以对已有 DXF 单独运行初次标注：

```powershell
uv run mda annotate-dxf output/vul-lizhu/lizhu-anzhuangtong-live-three-view.dxf `
  --output-dxf output/vul-lizhu/lizhu-anzhuangtong-live-three-view-annotated.dxf `
  --manifest output/vul-live/export_manifest.json `
  --out output/vul-live/annotation_manifest.json

uv run mda review --job samples/jobs/vul_lizhu_job.sample.json `
  --knowledge knowledge `
  --annotation output/vul-live/annotation_manifest.json `
  --out output/vul-live/review_report.md
```

布局说明：

- 优先使用 SolidWorks 自带 `gb_a3.drwdot`。
- 每个视图插入后记录 `outline_m`，并检查视图之间是否小于安全边距。
- live 出图会生成 `view_review`，复查第一角法排布、视图重叠、视图过小、标注预留空间和标题栏侵入风险。
- 默认导出成功后会关闭本工具创建的临时工程图；设置 `MDA_KEEP_DRAWING_OPEN=1` 可保留窗口用于调试。

## 当前边界

- SolidWorks COM 已实现基础三视图和 SaveAs 导出；AutoCAD/DWG 写回尚未实现。
- 初次 CAD 标注先写入 annotated DXF，不覆盖原始 DWG/DXF。
- `knowledge/` 只保存规则索引和样例，不保存国标正文。
- 复查报告已能检查视图排布、视图重叠、标注预留空间和必选标注意图覆盖；尺寸文字遮挡和真实标题栏几何识别仍待增强。

## 本地验证

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```

## EXE 打包

当前提供本地分发版骨架：

```powershell
.\scripts\build_mda_exe.ps1
dist\mda\mda.exe diagnose --out dist\mda\diagnose.json
dist\mda\mda.exe webui --open
```

生成 release zip：

```powershell
.\scripts\build_release_zip.ps1
```

解压 `dist\release\mda-0.1.0-alpha-windows-x64.zip` 后，双击 `start_mda_webui.cmd`
即可打开本地 Web UI。

详细说明见 [docs/packaging.md](docs/packaging.md)。

## MCP

本项目已提供 `mda-mcp`：

```powershell
uv run mda-mcp
```

本机已通过以下命令注册到 Codex 全局 MCP 配置：

```powershell
codex mcp add mechanical_drawing_assistant -- uv run --directory "I:/codex-Fa/Fa-v1.9/9.个人工作/mechanical-drawing-assistant" mda-mcp
```

新增 MCP 通常需要新线程、刷新或重启 Codex 后才会作为工具出现。

## 外部参考项目

```powershell
.\scripts\bootstrap_external.ps1
```

该命令会把 SolidWorks MCP、AutoCAD MCP、CodeStack、AutoLISP 自动标注和工程图 OCR 相关项目拉到 `external/`。该目录被 `.gitignore` 忽略。
