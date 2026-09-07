[CmdletBinding()]
param(
    [string]$AppDir = "dist\mda",
    [string]$OutputDir = "",
    [switch]$SkipRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ResolvedAppDir = (Resolve-Path -LiteralPath $AppDir).Path
$ExePath = Join-Path $ResolvedAppDir "mda.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "mda.exe not found: $ExePath"
}

if (-not $OutputDir) {
    $OutputDir = Join-Path $ResolvedAppDir "smoke-output"
}
$ResolvedOutputParent = Split-Path -Parent $OutputDir
if (-not (Test-Path -LiteralPath $ResolvedOutputParent)) {
    New-Item -ItemType Directory -Path $ResolvedOutputParent | Out-Null
}

$DiagnosePath = Join-Path $ResolvedAppDir "diagnose.json"
& $ExePath --help | Out-Null
& $ExePath diagnose --out $DiagnosePath | Out-Null

if (-not (Test-Path -LiteralPath $DiagnosePath)) {
    throw "diagnose.json was not created: $DiagnosePath"
}

$Diagnose = Get-Content -Raw -Encoding UTF8 -LiteralPath $DiagnosePath | ConvertFrom-Json
if (-not $Diagnose.runtime.frozen) {
    throw "Expected runtime.frozen=true in diagnose.json"
}
if (-not $Diagnose.resources.knowledge.present) {
    throw "Bundled knowledge resource is missing"
}
if (-not $Diagnose.resources.samples.present) {
    throw "Bundled samples resource is missing"
}
if (-not $Diagnose.python_packages.ezdxf) {
    throw "ezdxf is missing in packaged runtime"
}
if (-not $Diagnose.python_packages.pywin32) {
    throw "pywin32 is missing in packaged runtime"
}

if (-not $SkipRun) {
    $JobPath = Join-Path $Diagnose.runtime.default_samples_path "jobs\pulley_job.sample.json"
    & $ExePath run --job $JobPath --out-dir $OutputDir | Out-Null
    foreach ($FileName in @("drawing_plan.json", "export_manifest.json", "review_report.md")) {
        $Expected = Join-Path $OutputDir $FileName
        if (-not (Test-Path -LiteralPath $Expected)) {
            throw "Smoke output missing: $Expected"
        }
    }
}

Write-Host "Smoke passed: $ExePath"
