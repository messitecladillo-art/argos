# Argos — Windows installer
# Run in PowerShell:  iex (irm https://raw.githubusercontent.com/messitecladillo-art/argos/main/scripts/install.ps1)
param(
    [string]$Branch = "main",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/messitecladillo-art/argos.git"

Write-Host @'
    +--------------------------------------------------+
    |       A R G O S                                   |
    |       Multi-Agent Collaboration System            |
    +--------------------------------------------------+
'@ -ForegroundColor Cyan

# ── Determine install directory ──────────────────────
if (-not $InstallDir) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "argos"
}
Write-Host "Installing to: $InstallDir" -ForegroundColor Gray

# ── Check Python ──────────────────────────────────────
$PythonCmd = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $version = & $cmd --version 2>$null
        if ($version -match "3\.(1[1-9]|[2-9])") {
            $PythonCmd = $cmd
            Write-Host "Found Python: $version ($cmd)" -ForegroundColor Green
            break
        }
    } catch {}
}
if (-not $PythonCmd) {
    Write-Host "ERROR: Python 3.11+ is required. Install from https://python.org" -ForegroundColor Red
    exit 1
}

# ── Check Git ─────────────────────────────────────────
try {
    $gitVersion = & git --version 2>$null
    Write-Host "Found Git: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "Git not found. Downloading portable Git..."
    # If git isn't available, download zip instead
    $zipUrl = "https://github.com/messitecladillo-art/argos/archive/refs/heads/$Branch.zip"
    $zipPath = "$env:TEMP\argos.zip"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $env:TEMP -Force
    $InstallDir = $env:TEMP + "\argos-$Branch"
    # Continue with zip extraction...
    Write-Host "Downloaded source to: $InstallDir" -ForegroundColor Green
}

# ── Clone or download ─────────────────────────────────
if (Test-Path $InstallDir) {
    Write-Host "Directory already exists, pulling latest..." -ForegroundColor Gray
    Push-Location $InstallDir
    & git pull origin $Branch 2>$null
    Pop-Location
} else {
    Write-Host "Cloning Argos..." -ForegroundColor Gray
    & git clone --branch $Branch $RepoUrl $InstallDir 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Git clone failed. Downloading zip instead..." -ForegroundColor Yellow
        $zipUrl = "https://github.com/messitecladillo-art/argos/archive/refs/heads/$Branch.zip"
        $zipPath = "$env:TEMP\argos.zip"
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
        Expand-Archive -Path $zipPath -DestinationPath (Split-Path $InstallDir -Parent) -Force
        $extractedDir = (Split-Path $InstallDir -Parent) + "\argos-$Branch"
        if (Test-Path $extractedDir) {
            Rename-Item $extractedDir (Split-Path $InstallDir -Leaf)
        }
        Remove-Item $zipPath -Force
    }
}

# ── Setup virtual environment ─────────────────────────
Push-Location $InstallDir
Write-Host "Creating virtual environment..." -ForegroundColor Gray
& $PythonCmd -m venv .venv
$VenvPython = "$InstallDir\.venv\Scripts\python.exe"

# ── Install dependencies ──────────────────────────────
Write-Host "Installing dependencies..." -ForegroundColor Gray
& $VenvPython -m pip install --upgrade pip 2>$null | Out-Null
& $VenvPython -m pip install -e . 2>&1 | Out-Null

# ── Generate .env ─────────────────────────────────────
$SecretKey = & $VenvPython -c "import secrets; print(secrets.token_hex(32))"
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    (Get-Content .env) -replace "# SECRET_KEY=", "SECRET_KEY=$SecretKey" |
        Set-Content .env
    Write-Host "Generated .env with SECRET_KEY" -ForegroundColor Green
}

# ── Create launcher scripts ───────────────────────────
$BinDir = "$InstallDir\bin"
New-Item -ItemType Directory -Force $BinDir | Out-Null

@"
@echo off
call "$InstallDir\.venv\Scripts\python.exe" -m argos.cli %*
"@ | Out-File -FilePath "$BinDir\argos-cli.cmd" -Encoding ASCII

@"
@echo off
call "$InstallDir\.venv\Scripts\python.exe" -m argos.tui.app %*
"@ | Out-File -FilePath "$BinDir\argos-tui.cmd" -Encoding ASCII

Pop-Location

# ── Success ───────────────────────────────────────────
Write-Host ''
Write-Host @'
+--------------------------------------------------+
|       Installation Complete!                      |
+--------------------------------------------------+
'@ -ForegroundColor Green

Write-Host ''
Write-Host "Add to PATH or use full paths:"
Write-Host "  $BinDir\argos-cli.cmd info" -ForegroundColor Cyan
Write-Host "  $BinDir\argos-tui.cmd" -ForegroundColor Cyan
Write-Host ''
Write-Host "Or use Python directly:"
Write-Host "  $VenvPython -m argos.cli info" -ForegroundColor Cyan
Write-Host "  $VenvPython run.py" -ForegroundColor Cyan
Write-Host ''
Write-Host "Start the web server:"
Write-Host "  cd $InstallDir && $VenvPython run.py" -ForegroundColor Cyan
Write-Host ''
