# 进度记录

## 2026-07-05

- 创建 `mechanical-drawing-assistant` Python 项目。
- 添加开发依赖：pytest、ruff、ty。
- 创建最小闭环代码：CLI、pipeline、knowledge loader、review、SolidWorks/AutoCAD adapter。
- 创建带轮样例任务和基础规则库样例。
- 运行样例流程，生成 `output/demo/drawing_plan.json`、`export_manifest.json`、`review_report.md`。
- 验证通过：样例流程生成成功、pytest 2 passed、ruff check passed、ruff format check passed、ty check passed。
- 安装运行依赖：`mcp`、`pywin32`、`ezdxf`。
- 新增 `mda-mcp`，暴露 diagnose、plan、run、review、inspect_dxf 工具。
- 通过 `codex mcp add mechanical_drawing_assistant -- uv run --directory ... mda-mcp` 注册到 Codex 全局 MCP。
- 新增 `scripts/bootstrap_external.ps1`，并拉取 SolidWorks MCP、CodeStack、两个 AutoCAD MCP、AutoLISP 自动标注、OCR/Werk24 参考项目到 `external/`。
- 发现 Windows 大小写路径会让 `Autocad-MCP` 和 `autocad-mcp` 撞名，已改成本地目录 `u-c4n-autocad-mcp` 和 `puran-water-autocad-mcp`。
- 用 `mda inspect-dxf` 检查用户样例 DWG，结果为 `unsupported`，确认后续需要先从 CAD 软件导出/转换 DXF。
- 用户提供 `vul` 目录，包含 `立柱安装筒.SLDPRT` 和 `立柱安装筒-AL6061-数量4.dwg`。
- 只读连接已启动 SolidWorks 成功：版本 `34.1.1`，活动文档为 `立柱安装筒.SLDPRT`，类型 Part，未保存标记为 False。
- 实现 SolidWorks live 三视图：使用默认工程图模板 `gb_a0.drwdot`，插入 `front/top/left`，视图名映射为 `*前视/*上视/*左视`。
- live 导出成功：`SLDDRW`、`PDF`、`DWG`、`DXF` 写入 `output/vul-lizhu/`。
- 生成 DXF 可被 `ezdxf` 读取，实体统计为 `ARC=10`、`LINE=167`、`MTEXT=114`、`DIMENSION=0`。下一步需要导入模型尺寸或生成尺寸实体。
- 根据用户截图修正视图布局：优先使用 `gb_a3.drwdot`，前视/上视/右视位置拉开，新增 `GetOutline` 记录和重叠检测。
- 默认导出成功后关闭本工具创建的临时工程图；调试时可设置 `MDA_KEEP_DRAWING_OPEN=1`。
- 渲染最新 PDF 到 `output/vul-live-layout/rendered-page-1.png`，视觉确认视图不再挤在一起。
- 根据第一角法修正默认三视图为 `front/top/left`：主视图、俯视图在主下、左视图在主右。
- 新增 DXF 初次 CAD 标注 MVP：基于 SolidWorks `outline_m` 对 DXF 视图几何分组，另存 `*-annotated.dxf`，并输出 `annotation_manifest.json`。
