<#
One-line installer for the Nutanix VLAN Migrator (Windows / PowerShell).

  Remote (recommended):
    irm https://raw.githubusercontent.com/guranshdeol/nutanix-vlan-migrator/main/install.ps1 | iex

  From a local checkout:
    powershell -ExecutionPolicy Bypass -File install.ps1

Creates a self-contained virtualenv (.venv) inside the project, installs the
tool + all dependencies into it, then launches it. Nothing is placed on your
system PATH; everything lives in <project>\.venv.
#>
[CmdletBinding()]
param([switch]$NoRun)

$ErrorActionPreference = "Stop"
function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

$Repo   = if ($env:VLANMIG_REPO)   { $env:VLANMIG_REPO }   else { "https://github.com/guranshdeol/nutanix-vlan-migrator.git" }
$Branch = if ($env:VLANMIG_BRANCH) { $env:VLANMIG_BRANCH } else { "main" }

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

# ---- locate source (local) or clone -------------------------------------
$Src = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "pyproject.toml"))) { $Src = $PSScriptRoot }
elseif (Test-Path ".\pyproject.toml") { $Src = (Get-Location).Path }

if (-not $Src) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git is required to clone $Repo" }
    $Target = if ($env:VLANMIG_DIR) { $env:VLANMIG_DIR } else { Join-Path (Get-Location).Path "nutanix-vlan-migrator" }
    if (Test-Path (Join-Path $Target ".git")) {
        Say "Updating existing checkout at $Target"
        git -C $Target pull --ff-only
    } else {
        Say "Cloning $Repo -> $Target"
        git clone --depth 1 --branch $Branch $Repo $Target
    }
    $Src = $Target
}
Say "Source: $Src"

# ---- venv + install ------------------------------------------------------
$Venv = Join-Path $Src ".venv"
Say "Creating virtualenv at $Venv"
$pyExe, $pyArg = $PyBin.Split(" ", 2)
if ($pyArg) { & $pyExe $pyArg -m venv $Venv } else { & $pyExe -m venv $Venv }
$VenvPy = Join-Path $Venv "Scripts\python.exe"

Say "Installing tool and dependencies into the venv..."
& $VenvPy -m pip install --upgrade pip wheel | Out-Null
& $VenvPy -m pip install "$Src"

$Exe = Join-Path $Venv "Scripts\vlan-migrator.exe"
Say "Installed into $Venv (isolated; not on system PATH)."
Write-Host "Run it any time with:  $Exe"

if (-not $NoRun) {
    Say "Launching vlan-migrator..."
    & $Exe
}
