# 任务计划：机械制图自动标注辅助闭环

## 目标

搭建一个本地最小闭环：SolidWorks 三视图/工程图任务 -> 导出清单 -> 图纸复查报告。第一版只做 dry-run 和规则接口，不修改用户原始 DWG。

## 阶段

- [x] 阶段 1：确认工作区和工具环境
- [x] 阶段 2：创建 Python 项目骨架
- [x] 阶段 3：实现最小流程 CLI
- [x] 阶段 4：加入规则库样例和文档
- [x] 阶段 5：运行基础验证
- [x] 阶段 6：安装 CAD/MCP 依赖，注册本地 MCP server，拉取外部参考项目
- [x] 阶段 7：连接已启动 SolidWorks，生成 `vul` 样例三视图并导出 SLDDRW/PDF/DWG/DXF

## 决策

- 使用 Python + uv。
- 入口命令为 `mda`。
- CAD 自动化先通过 `SolidWorksAdapter` 和 `AutoCadAdapter` 隔离，默认 dry-run。
- `knowledge/` 只保存标准索引和规则摘要，不保存标准正文。
- 项目 MCP server 入口为 `mda-mcp`，已注册为 Codex 全局 MCP：`mechanical_drawing_assistant`。
- 外部参考源码放在 `external/`，该目录被 `.gitignore` 忽略。
- SolidWorks live 当前只做三视图和 SaveAs 导出；自动标注尚未接入。

## 风险

- 本机是否安装 SolidWorks/AutoCAD 以及 COM 接口是否可用，当前未验证。
- 真实加工图是否合格，后续必须靠样本图、人工规则和实际 API 几何数据逐步校正。

## 验证

- `uv run mda run --job samples/jobs/pulley_job.sample.json --knowledge knowledge --out-dir output/demo`
- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run ty check src tests`
- `uv run mda diagnose --out output/diagnose.json`
- `codex mcp get mechanical_drawing_assistant`
- `uv run mda run --job samples/jobs/vul_lizhu_job.sample.json --knowledge knowledge --out-dir output/vul-live --live`
- `uv run mda inspect-dxf output/vul-lizhu/lizhu-anzhuangtong-live-three-view.dxf --out output/vul-live/generated-dxf-inspect.json`
