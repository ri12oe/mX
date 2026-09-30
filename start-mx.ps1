# Start mX locally: rebuild the web app if it changed, run the server, open the browser.
#   .\start-mx.ps1              (or double-click start-mx.cmd)
#   .\start-mx.ps1 -NoBrowser   (don't open a browser tab)
# Only this computer can reach it (127.0.0.1). Press Ctrl+C to stop.
param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$Url = "http://localhost:8000"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

function Fail([string]$Message) {
    Write-Host "mX: $Message" -ForegroundColor Red
    exit 1
}

# --- Checks -------------------------------------------------------------------------
if (-not (Test-Path $Python)) {
    Fail "No Python venv found. Run: python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt"
}
if (-not (Test-Path ".env")) {
    Fail "No .env file. Copy .env.example to .env and fill in MX_API_KEY, MX_PASSWORD, ANTHROPIC_API_KEY."
}
if (-not (Select-String -Path ".env" -Pattern "^MX_PASSWORD=.{12,}" -Quiet)) {
    Fail "Add MX_PASSWORD=... (at least 12 characters) to .env; it's the web login password."
}

# Already running? Then just open it.
$running = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "mX (or something else) is already running on port 8000." -ForegroundColor Yellow
    if (-not $NoBrowser) { Start-Process $Url }
    exit 0
}

# --- Build the web app only when its sources changed ----------------------------------
Push-Location web
try {
    if (-not (Test-Path "node_modules")) {
        Write-Host "First run: installing web dependencies (npm ci)..."
        cmd /c "npm ci --silent"
        if ($LASTEXITCODE -ne 0) { Fail "npm ci failed." }
    }
    $built = Get-Item "dist\index.html" -ErrorAction SilentlyContinue
    $sources = @(Get-ChildItem "src" -Recurse -File) + @(Get-Item "index.html", "package.json", "vite.config.ts")
    $newest = ($sources | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    if (-not $built -or $newest -gt $built.LastWriteTime) {
        Write-Host "Building the web app..."
        # cmd merges stderr into stdout, so harmless build warnings (e.g. chunk size)
        # stay plain text instead of becoming PowerShell errors that stop the script.
        $log = cmd /c "npm run build --silent 2>&1"
        if ($LASTEXITCODE -ne 0) {
            $log | Write-Host
            Fail "Web build failed (see the errors above)."
        }
    } else {
        Write-Host "Web app is up to date."
    }
} finally {
    Pop-Location
}

# --- Open the browser once the server answers ----------------------------------------
if (-not $NoBrowser) {
    Start-Job -ArgumentList $Url -ScriptBlock {
        param($Url)
        for ($i = 0; $i -lt 60; $i++) {
            try {
                Invoke-WebRequest "$Url/health" -UseBasicParsing -TimeoutSec 1 | Out-Null
                Start-Process $Url
                return
            } catch {
                Start-Sleep -Milliseconds 500
            }
        }
    } | Out-Null
}

Write-Host "Starting mX at $Url (Ctrl+C to stop)..." -ForegroundColor Green
& $Python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
