# MCP 接入

本项目现在提供一个本地 MCP server：

```powershell
uv run mda-mcp
```

它暴露这些工具：

- `diagnose_cad_environment`：检查 `mcp`、`pywin32`、`ezdxf`、CAD adapter 和外部参考 repo 状态。
- `plan_drawing`：从 job JSON 生成 `drawing_plan.json`。
- `run_drawing_pipeline`：运行 plan/export/review，默认 dry-run；live 且 DXF 标注成功时会生成 `annotation_manifest.json`。
- `review_drawing_job`：返回 Markdown 复查报告。
- `inspect_dxf`：读取 DXF，统计实体和 DIMENSION 数量。DWG 需要先用 AutoCAD/ODA/SolidWorks 导出为 DXF。

## Codex/其他 MCP 客户端配置示例

本机已经执行过：

```powershell
codex mcp add mechanical_drawing_assistant -- uv run --directory "I:/codex-Fa/Fa-v1.9/9.个人工作/mechanical-drawing-assistant" mda-mcp
```

可用下面命令查看：

```powershell
codex mcp get mechanical_drawing_assistant
```

如果需要手动配置，不同客户端的配置文件位置不一样，核心命令是一致的：

```json
{
  "mcpServers": {
    "mechanical-drawing-assistant": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "I:/codex-Fa/Fa-v1.9/9.个人工作/mechanical-drawing-assistant",
        "mda-mcp"
      ]
    }
  }
}
```

注意：新增 MCP server 通常需要新线程、刷新或重启 Codex 才会出现在当前可调用工具列表中。

## 外部参考项目

运行：

```powershell
.\scripts\bootstrap_external.ps1
```

会把 SolidWorks MCP、AutoCAD MCP、CodeStack、AutoLISP 自动标注和工程图 OCR 相关项目拉到 `external/`。该目录被 `.gitignore` 忽略，只作为本地研究和移植参考。
