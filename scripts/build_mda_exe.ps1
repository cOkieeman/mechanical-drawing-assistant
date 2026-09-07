[CmdletBinding()]
param(
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptPath "..")).Path
$SpecPath = Join-Path $ProjectRoot "packaging\mda.spec"
$ExePath = Join-Path $ProjectRoot "dist\mda\mda.exe"
$DiagnosePath = Join-Path $ProjectRoot "dist\mda\diagnose.json"

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

Set-Location $ProjectRoot

if (-not $env:UV_PROJECT_ENVIRONMENT) {
    $env:UV_PROJECT_ENVIRONMENT = ".venv-build"
}

if (-not (Test-Path -LiteralPath $SpecPath)) {
    throw "Missing PyInstaller spec: $SpecPath"
}

Assert-InProject -Path $ExePath
Write-Host "Building mda.exe from $SpecPath"
Write-Host "Using UV_PROJECT_ENVIRONMENT=$env:UV_PROJECT_ENVIRONMENT"
uv run pyinstaller --noconfirm --clean $SpecPath
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Build finished but mda.exe was not found: $ExePath"
}

if (-not $SkipSmoke) {
    Write-Host "Running smoke checks"
    & $ExePath --help | Out-Null
    & $ExePath diagnose --out $DiagnosePath | Out-Null
    if (-not (Test-Path -LiteralPath $DiagnosePath)) {
        throw "Smoke diagnose did not create: $DiagnosePath"
    }
}

Write-Host "Built $ExePath"
