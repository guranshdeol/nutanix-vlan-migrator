<#
Convenience launcher (Windows). Prefers the global install, falls back to a
local .venv. Passes through args, e.g.:  .\run.ps1 list-basic
#>
$ErrorActionPreference = "Stop"
$Global = Join-Path $env:USERPROFILE ".nutanix-vlan-migrator\venv\Scripts\vlan-migrator.exe"
$Src    = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$Local  = Join-Path $Src ".venv\Scripts\vlan-migrator.exe"
if     (Test-Path $Global) { & $Global @args }
elseif (Test-Path $Local)  { & $Local  @args }
else {
    Write-Host "Not installed yet. Run:  powershell -ExecutionPolicy Bypass -File install.ps1" -ForegroundColor Red
    exit 1
}
