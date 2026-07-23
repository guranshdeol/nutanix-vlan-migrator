<#
Launch the VLAN Migrator from the project-local virtualenv (Windows).
Passes through any args, e.g.:  .\run.ps1 list-basic
#>
$ErrorActionPreference = "Stop"
$Src = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$Exe = Join-Path $Src ".venv\Scripts\vlan-migrator.exe"
if (-not (Test-Path $Exe)) {
    Write-Host "venv not found. Run:  powershell -ExecutionPolicy Bypass -File install.ps1 -NoRun" -ForegroundColor Red
    exit 1
}
& $Exe @args
