$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$ExternalRoot = Join-Path $ProjectRoot "external"
New-Item -ItemType Directory -Force -Path $ExternalRoot | Out-Null

$Repos = @(
    @{
        Name = "solidworks-mcp"
        Url = "https://github.com/haunchen/solidworks-mcp.git"
    },
    @{
        Name = "codestack"
        Url = "https://github.com/xarial/codestack.git"
    },
    @{
        Name = "u-c4n-autocad-mcp"
        Url = "https://github.com/U-C4N/Autocad-MCP.git"
    },
    @{
        Name = "puran-water-autocad-mcp"
        Url = "https://github.com/puran-water/autocad-mcp.git"
    },
    @{
        Name = "AutoCAD-Automatic-Dimensioning-LISP"
        Url = "https://github.com/Dvir-Cohen1/AutoCAD-Automatic-Dimensioning-LISP.git"
    },
    @{
        Name = "ocrx-engineering-drawings"
        Url = "https://github.com/aeewws/ocrx-engineering-drawings.git"
    },
    @{
        Name = "werk24-python"
        Url = "https://github.com/W24-Service-GmbH/werk24-python.git"
    }
)

foreach ($Repo in $Repos) {
    $Target = Join-Path $ExternalRoot $Repo.Name
    if (Test-Path -LiteralPath (Join-Path $Target ".git")) {
        Write-Host "Updating $($Repo.Name)"
        git -C $Target pull --ff-only
    }
    else {
        Write-Host "Cloning $($Repo.Name)"
        git clone --depth 1 $Repo.Url $Target
    }
}
