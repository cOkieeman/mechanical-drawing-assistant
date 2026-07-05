# 发现记录

## 2026-07-05

- 当前工作区原本为空，不是 git 仓库。
- `uv 0.11.3` 可用，脚手架创建项目时初始化了本地 `.git` 目录，但未 commit。
- 第一版应从 dry-run 起步，避免直接操作用户给出的 DWG 原图。
- 标准库应保存索引和规则摘要，标准正文需要用户自行持有授权文本。
- Codex MCP 配置位于 `~/.codex/config.toml`，也可用 `codex mcp add` 注册 stdio server。
- Windows 路径大小写不敏感，`U-C4N/Autocad-MCP` 和 `puran-water/autocad-mcp` 不能直接用仓库名作为同级目录，否则会撞名。
- SolidWorks 2026 COM 在 pywin32 中常把零参数方法暴露为属性，例如 `ActiveDoc`、`GetTitle`、`GetPathName`、`GetType`。
- SolidWorks 2026 当前环境中 `ModelDoc2.SaveAs(path)` 可成功导出 `.SLDDRW/.PDF/.DWG/.DXF`；`Extension.SaveAs3(path, 0, 1)` 会报“非选择性的参数”。
- 简体中文 SolidWorks 标准视图名可用 `*前视`、`*上视`、`*左视`、`*右视`；英文 `*Front/*Top/*Left/*Right` 在本机未作为首选成功路径。
- 视图拥挤的根因是硬编码坐标、未读取 view outline、且默认模板取到 `gb_a0.drwdot`。已改为优先 `gb_a3.drwdot`，并在 manifest 中记录 `outline_m` 与 overlap warnings。
- SolidWorks 标准视图名应在源码中用 Unicode escape 保存，避免中文源码在 PowerShell/终端显示时被误读成乱码。
