[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$SkipBuild,
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptPath "..")).Path
$ReleaseRoot = Join-Path $ProjectRoot "dist\release"
$PackageRoot = Join-Path $ReleaseRoot "mda"
$ZipVersion = if ($Version) { $Version } else { "0.1.0-alpha" }
$ZipPath = Join-Path $ReleaseRoot "mda-$ZipVersion-windows-x64.zip"
$ExtractRoot = Join-Path $ReleaseRoot "_smoke_extract"

function Assert-InProject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $ResolvedParent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $ResolvedParent)) {
        New-Item -ItemType Directory -Path $ResolvedParent | Out-Null
    }
    $Resolved = (Resolve-Path -LiteralPath $ResolvedParent).Path
    if (-not $Resolved.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside project root: $Path"
    }
}

function Remove-InProject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $Resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not $Resolved.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete outside project root: $Path"
    }
    Remove-Item -LiteralPath $Resolved -Recurse -Force
}

Set-Location $ProjectRoot

if (-not $SkipBuild) {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptPath "build_mda_exe.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "build_mda_exe.ps1 failed with exit code $LASTEXITCODE"
    }
}

$DistApp = Join-Path $ProjectRoot "dist\mda"
$ExePath = Join-Path $DistApp "mda.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "mda.exe not found. Run scripts\build_mda_exe.ps1 first."
}

Assert-InProject -Path $PackageRoot
Remove-InProject -Path $PackageRoot
New-Item -ItemType Directory -Path $PackageRoot | Out-Null
Copy-Item -Path (Join-Path $DistApp "*") -Destination $PackageRoot -Recurse -Force

Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination $PackageRoot -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "CHANGELOG.md") -Destination $PackageRoot -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\packaging.md") -Destination $PackageRoot -Force

$StartScript = @'
@echo off
setlocal
cd /d "%~dp0"
mda.exe webui --open
pause
'@
Set-Content -LiteralPath (Join-Path $PackageRoot "start_mda_webui.cmd") -Value $StartScript -Encoding ASCII

$DiagnoseScript = @'
@echo off
setlocal
cd /d "%~dp0"
mda.exe diagnose --out diagnose.json
echo diagnose.json written.
pause
'@
Set-Content -LiteralPath (Join-Path $PackageRoot "run_diagnose.cmd") -Value $DiagnoseScript -Encoding ASCII

if (Test-Path -LiteralPath $ZipPath) {
    Remove-InProject -Path $ZipPath
}
Compress-Archive -LiteralPath $PackageRoot -DestinationPath $ZipPath -Force

if (-not $SkipSmoke) {
    Remove-InProject -Path $ExtractRoot
    New-Item -ItemType Directory -Path $ExtractRoot | Out-Null
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $ExtractRoot -Force
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptPath "smoke_mda_exe.ps1") `
        -AppDir (Join-Path $ExtractRoot "mda") `
        -OutputDir (Join-Path $ExtractRoot "mda\smoke-output")
    if ($LASTEXITCODE -ne 0) {
        throw "release smoke failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Release zip built: $ZipPath"
