# One-line installer for the Nutanix VLAN Migrator (Windows / PowerShell).
#
#   irm https://raw.githubusercontent.com/guranshdeol/nutanix-vlan-migrator/main/install.ps1 | iex
#
# Installs the tool into an isolated virtualenv, adds a global `vlan-migrator`
# command to your user PATH, and launches it. Designed to be safe under
# `irm | iex` (never calls `exit`, so it won't close your terminal).

function Invoke-VlanMigratorInstall {
    $ErrorActionPreference = "Stop"
    function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }

    $Repo    = if ($env:VLANMIG_REPO)   { $env:VLANMIG_REPO }   else { "https://github.com/guranshdeol/nutanix-vlan-migrator.git" }
    $Branch  = if ($env:VLANMIG_BRANCH) { $env:VLANMIG_BRANCH } else { "main" }
    $HomeDir = if ($env:VLANMIG_HOME)   { $env:VLANMIG_HOME }   else { Join-Path $env:USERPROFILE ".nutanix-vlan-migrator" }
    $BinDir  = if ($env:VLANMIG_BIN)    { $env:VLANMIG_BIN }    else { Join-Path $env:USERPROFILE ".local\bin" }
    $Venv    = Join-Path $HomeDir "venv"
    $NoRun   = [bool]$env:VLANMIG_NORUN

    # ---- find Python (>=3.8) --------------------------------------------
    $verCheck = "import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,8) else 1)"
    $candidates = @(
        @{ Exe = "py";      Pre = @("-3") },
        @{ Exe = "python";  Pre = @() },
        @{ Exe = "python3"; Pre = @() }
    )
    $Py = $null
    foreach ($c in $candidates) {
        if (Get-Command $c.Exe -ErrorAction SilentlyContinue) {
            & $c.Exe @($c.Pre + @("-c", $verCheck)) 2>$null
            if ($LASTEXITCODE -eq 0) { $Py = $c; break }
        }
    }
    if (-not $Py) {
        Write-Host "ERROR: Python 3.8+ is required but was not found. Install it from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
        return
    }
    Say "Using Python: $($Py.Exe) $($Py.Pre -join ' ')"

    # ---- determine source: local checkout or git ------------------------
    $Src = $null
    if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "pyproject.toml"))) { $Src = $PSScriptRoot }
    elseif (Test-Path ".\pyproject.toml") { $Src = (Get-Location).Path }

    # ---- create isolated venv -------------------------------------------
    Say "Creating virtualenv at $Venv"
    New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null
    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
    & $Py.Exe @($Py.Pre + @("-m", "venv", $Venv))
    $VenvPy = Join-Path $Venv "Scripts\python.exe"
    if (-not (Test-Path $VenvPy)) {
        Write-Host "ERROR: virtualenv creation failed ($VenvPy not found)." -ForegroundColor Red
        return
    }
    & $VenvPy -m pip install --upgrade pip wheel | Out-Null

    if ($Src) {
        Say "Installing from local checkout: $Src"
        & $VenvPy -m pip install "$Src"
    } else {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Write-Host "ERROR: git is required to install from $Repo. Install Git for Windows and re-run." -ForegroundColor Red
            return
        }
        Say "Installing from $Repo@$Branch"
        & $VenvPy -m pip install "git+$Repo@$Branch"
    }

    $Exe = Join-Path $Venv "Scripts\vlan-migrator.exe"
    if (-not (Test-Path $Exe)) {
        Write-Host "ERROR: install did not produce $Exe" -ForegroundColor Red
        return
    }

    # ---- expose a global `vlan-migrator` command ------------------------
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    "@echo off`r`n`"$Venv\Scripts\vlan-migrator.exe`" %*" | Set-Content -Encoding ASCII (Join-Path $BinDir "vlan-migrator.cmd")
    "@echo off`r`n`"$Venv\Scripts\vlanmig.exe`" %*"       | Set-Content -Encoding ASCII (Join-Path $BinDir "vlanmig.cmd")
    Say "Global command installed -> $BinDir\vlan-migrator.cmd"

    # ---- ensure BinDir on user PATH -------------------------------------
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    if ($userPath -notlike "*$BinDir*") {
        $newPath = if ($userPath) { "$userPath;$BinDir" } else { $BinDir }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Say "Added $BinDir to your user PATH (new terminals will see it)."
    }
    if ($env:Path -notlike "*$BinDir*") { $env:Path = "$env:Path;$BinDir" }  # usable now

    Say "Installed. Type 'vlan-migrator' anywhere to run it."

    # ---- launch ---------------------------------------------------------
    if (-not $NoRun) {
        Say "Launching vlan-migrator..."
        & $Exe
    }
}

try {
    Invoke-VlanMigratorInstall
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Installation did not complete. Your terminal stays open; see the message above." -ForegroundColor Yellow
}
