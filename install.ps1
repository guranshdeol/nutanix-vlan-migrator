<#
One-line installer for the Nutanix VLAN Migrator (Windows / PowerShell).

  irm https://raw.githubusercontent.com/guranshdeol/nutanix-vlan-migrator/main/install.ps1 | iex

Installs the tool into an isolated virtualenv, adds a global `vlan-migrator`
command to your user PATH, and launches it immediately.
#>
[CmdletBinding()]
param([switch]$NoRun)

$ErrorActionPreference = "Stop"
function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

$Repo    = if ($env:VLANMIG_REPO)   { $env:VLANMIG_REPO }   else { "https://github.com/guranshdeol/nutanix-vlan-migrator.git" }
$Branch  = if ($env:VLANMIG_BRANCH) { $env:VLANMIG_BRANCH } else { "main" }
$HomeDir = if ($env:VLANMIG_HOME)   { $env:VLANMIG_HOME }   else { Join-Path $env:USERPROFILE ".nutanix-vlan-migrator" }
$BinDir  = if ($env:VLANMIG_BIN)    { $env:VLANMIG_BIN }    else { Join-Path $env:USERPROFILE ".local\bin" }
$Venv    = Join-Path $HomeDir "venv"

# ---- find Python (>=3.8) -------------------------------------------------
$PyBin = $null
foreach ($cand in @("py -3", "python", "python3")) {
    $exe, $arg = $cand.Split(" ", 2)
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        & $exe $arg -c "import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,8) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $PyBin = $cand; break }
    }
}
if (-not $PyBin) { Die "Python 3.8+ is required but was not found. Install it from python.org." }
Say "Using Python: $PyBin"

# ---- determine source: local checkout or git ----------------------------
$Src = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "pyproject.toml"))) { $Src = $PSScriptRoot }
elseif (Test-Path ".\pyproject.toml") { $Src = (Get-Location).Path }

# ---- create isolated venv -----------------------------------------------
Say "Creating virtualenv at $Venv"
New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null
$pyExe, $pyArg = $PyBin.Split(" ", 2)
if ($pyArg) { & $pyExe $pyArg -m venv $Venv } else { & $pyExe -m venv $Venv }
$VenvPy = Join-Path $Venv "Scripts\python.exe"
& $VenvPy -m pip install --upgrade pip wheel | Out-Null

if ($Src) {
    Say "Installing from local checkout: $Src"
    & $VenvPy -m pip install "$Src"
} else {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git is required to install from $Repo" }
    Say "Installing from $Repo@$Branch"
    & $VenvPy -m pip install "git+$Repo@$Branch"
}

# ---- expose a global `vlan-migrator` command ----------------------------
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$launcher = Join-Path $BinDir "vlan-migrator.cmd"
"@echo off`r`n`"$Venv\Scripts\vlan-migrator.exe`" %*" | Set-Content -Encoding ASCII $launcher
$launcher2 = Join-Path $BinDir "vlanmig.cmd"
"@echo off`r`n`"$Venv\Scripts\vlanmig.exe`" %*" | Set-Content -Encoding ASCII $launcher2
Say "Wrote global launcher -> $launcher"

# ---- ensure BinDir on user PATH -----------------------------------------
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$BinDir", "User")
    $env:Path = "$env:Path;$BinDir"  # make it usable in this session too
    Say "Added $BinDir to your user PATH"
}

Say "Installed. Use it anywhere by typing:  vlan-migrator"
if (-not $NoRun) {
    Say "Launching vlan-migrator..."
    & (Join-Path $Venv "Scripts\vlan-migrator.exe")
}
