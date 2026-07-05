# Changelog

本项目遵循“小步迭代、每轮可验证”的节奏记录关键变化。

## Unreleased

- 建立 SolidWorks -> DXF/DWG/PDF -> DXF 初次标注 -> 复查报告的本地闭环。
- 默认三视图改为 `front/top/left`，按主视图、俯视图在主下、左视图在主右排布。
- 新增 DXF 初次 CAD 标注 MVP，输出 `*-annotated.dxf` 和 `annotation_manifest.json`。
- 新增 MCP server 入口 `mda-mcp`，供 Codex 或其他 MCP 客户端调用。
- 增加仓库结构、路线图、贡献说明和 GitHub Actions CI 配置。

