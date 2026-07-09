# EXE 打包说明

本文档记录 P9 的本地分发方案。当前目标是生成 `mda.exe`、本地 Web UI、
启动脚本和 release zip，用于运行现有 CLI、诊断环境、读取内置规则库和样例 job。

## 当前范围

已覆盖：

- 使用 PyInstaller 生成 `dist/mda/mda.exe`。
- 打包 `knowledge/` 和 `samples/`，使 exe 可以默认找到规则库和样例。
- 保留 `mda --help` 与 `mda diagnose` 作为最小烟测。
- 提供 `mda webui --open` 本地 Web UI。
- 提供 `start_mda_webui.cmd` 和 `run_diagnose.cmd` 双击入口。
- 提供 `scripts/build_release_zip.ps1` 生成 release zip。
- 提供 `scripts/smoke_mda_exe.ps1` 验证 exe 诊断和 bundled dry-run。
- Web UI 可生成 `webui_run_log.json`，并可导出支持包 zip。
- 显式加入 pywin32/COM 常见隐藏导入。

暂不覆盖：

- 安装器。
- 代码签名。
- AutoCAD/DWG 真正写回。
- SolidWorks/AutoCAD 程序本体打包。

SolidWorks 和 AutoCAD 是本机外部依赖，exe 只能通过 COM 连接已安装软件。

## 构建命令

在仓库根目录运行：

```powershell
.\scripts\build_mda_exe.ps1
```

脚本默认使用独立的 `.venv-build`，避免和正在运行的开发环境或 MCP 进程抢占
`.venv\Scripts\mda-mcp.exe` 等入口文件。

构建完成后产物位于：

```text
dist\mda\mda.exe
```

脚本默认执行烟测：

```powershell
dist\mda\mda.exe --help
dist\mda\mda.exe diagnose --out dist\mda\diagnose.json
```

仅构建、不跑烟测：

```powershell
.\scripts\build_mda_exe.ps1 -SkipSmoke
```

## Release Zip

生成可解压使用的 zip：

```powershell
.\scripts\build_release_zip.ps1
```

产物位于：

```text
dist\release\mda-0.1.0-alpha-windows-x64.zip
```

脚本会：

- 构建 `dist\mda\mda.exe`。
- 复制 one-dir 产物到 `dist\release\mda`。
- 生成 `start_mda_webui.cmd` 和 `run_diagnose.cmd`。
- 附带 `README.md`、`CHANGELOG.md` 和本说明文档。
- 压缩成 zip。
- 解压到 `dist\release\_smoke_extract` 后运行 `smoke_mda_exe.ps1`。

用户解压后双击：

```text
start_mda_webui.cmd
```

即可打开本地 Web UI。

## 最小验收

P9 本地分发版通过以下检查即可认为可用：

```powershell
uv run pytest --basetemp .pytest-tmp
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
.\scripts\build_mda_exe.ps1
.\scripts\build_release_zip.ps1
dist\mda\mda.exe diagnose --out dist\mda\diagnose.json
```

`diagnose.json` 应包含：

- `runtime.frozen=true`
- `resources.knowledge.present=true`
- `resources.samples.present=true`
- `python_packages.ezdxf=true`
- `python_packages.pywin32=true`

SolidWorks/AutoCAD 是否可用取决于本机安装和当前是否允许 COM 连接。

## 运行样例

dry-run 样例：

```powershell
$diag = Get-Content dist\mda\diagnose.json | ConvertFrom-Json
$job = Join-Path $diag.runtime.default_samples_path "jobs\pulley_job.sample.json"
dist\mda\mda.exe run --job $job --out-dir dist\mda\smoke-output
```

该命令会使用 exe 内置的 `samples/` 和 `knowledge/`。产物应包含：

- `dist\mda\smoke-output\drawing_plan.json`
- `dist\mda\smoke-output\export_manifest.json`
- `dist\mda\smoke-output\review_report.md`

启动 Web UI：

```powershell
dist\mda\mda.exe webui --open
```

## 打包文件

- `packaging/mda.spec`：PyInstaller 配置。
- `scripts/build_mda_exe.ps1`：Windows 构建和烟测脚本。
- `scripts/build_release_zip.ps1`：release zip 构建和解压 smoke。
- `scripts/smoke_mda_exe.ps1`：对 exe 目录运行诊断和 dry-run smoke。
- `src/mechanical_drawing_assistant/runtime.py`：源码运行和 frozen exe 运行时的资源路径解析。
- `src/mechanical_drawing_assistant/webui.py`：内置本地 Web UI。

## 已知风险

- pywin32 COM 隐藏导入可能随 PyInstaller/pywin32 版本变化，需要用真实机器 smoke test。
- one-dir exe 比 one-file 更容易排查资源和 DLL 问题，当前 alpha 使用 one-dir。
- 杀毒软件可能拦截未签名 exe；public stable 阶段再处理签名和安装器。
- 真实 SolidWorks live 流程仍依赖本机 SolidWorks 版本、语言、模板和打开状态。
