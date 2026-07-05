# 第三方项目接入策略

## 已接入为依赖

- `mcp`：用于暴露本项目自己的 MCP server。
- `pywin32`：用于后续通过 COM 控制 SolidWorks 和 AutoCAD。
- `ezdxf`：用于 DXF 读取、检查和后续无界面 DXF 标注。

## 本地参考源码

通过 `scripts/bootstrap_external.ps1` 拉取到 `external/`：

- `haunchen/solidworks-mcp`：SolidWorks MCP 控制思路。
- `xarial/codestack`：SolidWorks API 示例库。
- `U-C4N/Autocad-MCP` -> `external/u-c4n-autocad-mcp`：AutoCAD MCP / COM / ezdxf 思路。
- `puran-water/autocad-mcp` -> `external/puran-water-autocad-mcp`：AutoCAD LT / AutoLISP / ezdxf 思路。
- `Dvir-Cohen1/AutoCAD-Automatic-Dimensioning-LISP`：AutoLISP 自动尺寸逻辑。
- `aeewws/ocrx-engineering-drawings`：工程图 OCR/信息抽取参考。
- `Werk24-Service-GmbH/werk24-python`：工程图识别 API SDK 参考。

## 不直接 vendoring 的原因

这些项目的成熟度、许可、依赖和运行方式不同。第一阶段更安全的方式是：

1. 作为本地参考源码拉取。
2. 抽取可用接口和算法思路。
3. 把稳定能力沉淀到本项目 adapter 或 rules。
4. 保持我们的核心流程可测试、可替换。
