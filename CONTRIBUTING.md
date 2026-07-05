# Contributing

## 开发原则

- 不覆盖原始 CAD 文件。
- 不把真实客户图纸、SolidWorks 模型、DWG/DXF/PDF 输出提交到仓库。
- 标准库只保存索引、规则摘要和本地引用，不提交受版权保护的标准正文。
- 每次改动都要能用命令验证，优先保持 dry-run 和 DXF 流程可测试。

## 本地验证

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```

SolidWorks/AutoCAD live 流程只能在装有对应软件的 Windows 本机验证：

```powershell
uv run mda run --job samples/jobs/vul_lizhu_job.sample.json --knowledge knowledge --out-dir output/vul-live --live
uv run mda inspect-dxf output/vul-lizhu/lizhu-anzhuangtong-live-three-view-annotated.dxf --out output/vul-live/annotated-dxf-inspect.json
```

## 提交流程建议

1. 每轮只解决一个明确问题。
2. 先更新或新增测试，再改实现。
3. 运行本地验证。
4. 在 PR 或提交说明里写清楚：改了什么、如何验证、剩余风险。

