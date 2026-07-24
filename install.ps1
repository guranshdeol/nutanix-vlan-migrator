# One-line installer for the Nutanix VLAN Migrator (Windows / PowerShell).
#
#   irm https://raw.githubusercontent.com/guranshdeol/nutanix-vlan-migrator/main/install.ps1 | iex
#
# Self-bootstrapping: on a fresh machine it installs the prerequisites it needs
# (Python 3.8+ and git), then installs the tool into an isolated virtualenv,
# adds a global `vlan-migrator` command to your user PATH, and launches it.
# Safe under `irm | iex` (never calls `exit`, so it won't close your terminal).

function Invoke-VlanMigratorInstall {
    $ErrorActionPreference = "Stop"
    function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }

    $Repo    = if ($env:VLANMIG_REPO)   { $env:VLANMIG_REPO }   else { "https://github.com/guranshdeol/nutanix-vlan-migrator.git" }
    $Branch  = if ($env:VLANMIG_BRANCH) { $env:VLANMIG_BRANCH } else { "main" }
    $HomeDir = if ($env:VLANMIG_HOME)   { $env:VLANMIG_HOME }   else { Join-Path $env:USERPROFILE ".nutanix-vlan-migrator" }
    $BinDir  = if ($env:VLANMIG_BIN)    { $env:VLANMIG_BIN }    else { Join-Path $env:USERPROFILE ".local\bin" }
    $Venv    = Join-Path $HomeDir "venv"
    $NoRun   = [bool]$env:VLANMIG_NORUN
    $PyVer   = "3.12.4"

    function Refresh-Path {
        $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
        $user    = [Environment]::GetEnvironmentVariable("Path", "User")
        $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ";"
    }

    # Return @{Exe;Pre} for a Python >=3.8, or $null.
    function Find-Python {
        $verCheck = "import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,8) else 1)"
        foreach ($c in @(@{Exe="py";Pre=@("-3")}, @{Exe="python";Pre=@()}, @{Exe="python3";Pre=@()})) {
            if (Get-Command $c.Exe -ErrorAction SilentlyContinue) {
                & $c.Exe @($c.Pre + @("-c", $verCheck)) 2>$null
                if ($LASTEXITCODE -eq 0) { return $c }
            }
        }
        return $null
    }

    function Ensure-Python {
        $p = Find-Python
        if ($p) { return $p }
        Say "Python 3.8+ not found - installing it..."
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install --id Python.Python.3.12 -e --source winget `
                --accept-package-agreements --accept-source-agreements --scope user
        } else {
            $url = "https://www.python.org/ftp/python/$PyVer/python-$PyVer-amd64.exe"
            $tmp = Join-Path $env:TEMP "python-$PyVer-amd64.exe"
            Say "Downloading Python $PyVer from python.org..."
            Invoke-WebRequest -Uri $url -OutFile $tmp
            Say "Installing Python (silent)..."
            Start-Process -FilePath $tmp -Wait -ArgumentList `
                "/quiet","InstallAllUsers=0","PrependPath=1","Include_pip=1","Include_venv=1"
        }
        Refresh-Path
        $p = Find-Python
        if (-not $p) {
            Write-Host "Python was installed but isn't on PATH yet. Open a NEW PowerShell window and re-run the installer." -ForegroundColor Yellow
        }
        return $p
    }

    function Ensure-Git {
        if (Get-Command git -ErrorAction SilentlyContinue) { return $true }
        Say "git not found - installing it..."
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install --id Git.Git -e --source winget `
                --accept-package-agreements --accept-source-agreements
        } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
            choco install git -y
        } else {
            $gver = "2.45.2"
            $url  = "https://github.com/git-for-windows/git/releases/download/v$gver.windows.1/Git-$gver-64-bit.exe"
            $tmp  = Join-Path $env:TEMP "Git-$gver-64-bit.exe"
            Say "Downloading Git for Windows..."
            Invoke-WebRequest -Uri $url -OutFile $tmp
            Say "Installing Git (silent)..."
            Start-Process -FilePath $tmp -Wait -ArgumentList "/VERYSILENT","/NORESTART"
        }
        Refresh-Path
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Write-Host "git was installed but isn't on PATH yet. Open a NEW PowerShell window and re-run the installer." -ForegroundColor Yellow
            return $false
        }
        Say "git installed: $(git --version)"
        return $true
    }

    # ---- bootstrap prerequisites ----------------------------------------
    $Py = Ensure-Python
    if (-not $Py) { return }
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
        if (-not (Ensure-Git)) { return }
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
    if ($env:Path -notlike "*$BinDir*") { $env:Path = "$env:Path;$BinDir" }

    Say "Installed. Type 'vlan-migrator' anywhere to run it."

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
