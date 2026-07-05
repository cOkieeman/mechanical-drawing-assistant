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
- `output/demo/export_manifest.json`
- `output/demo/annotation_manifest.json`（live 且 DXF 标注成功时生成）
- `output/demo/review_report.md`

## 仓库入口

- [仓库结构](docs/repository.md)
- [最小闭环流程](docs/workflow.md)
- [路线图](docs/roadmap.md)
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

当前 live 流程会生成三视图并导出：

- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view.SLDDRW`
- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view.pdf`
- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view.dwg`
- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view.dxf`
- `output/vul-lizhu/lizhu-anzhuangtong-live-three-view-annotated.dxf`

DXF 初次标注目前会基于 SolidWorks 视图区域生成外形尺寸和圆视图直径，
并输出 `annotation_manifest.json`。这只是初稿尺寸，不代表最终加工图已经完整。

布局说明：

- 优先使用 SolidWorks 自带 `gb_a3.drwdot`。
- 每个视图插入后记录 `outline_m`，并检查视图之间是否小于安全边距。
- 默认导出成功后会关闭本工具创建的临时工程图；设置 `MDA_KEEP_DRAWING_OPEN=1` 可保留窗口用于调试。

## 当前边界

- SolidWorks COM 已实现基础三视图和 SaveAs 导出；AutoCAD/DWG 写回尚未实现。
- 初次 CAD 标注先写入 annotated DXF，不覆盖原始 DWG/DXF。
- `knowledge/` 只保存规则索引和样例，不保存国标正文。
- 复查报告只做规则级检查，尚未做几何级漏标/重叠检查。

## 本地验证

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```

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
