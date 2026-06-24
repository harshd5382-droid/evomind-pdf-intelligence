# EvoMind — fully-automatic mode launcher.
#
# Starts the API (which auto-engages the autopilot + folder-watcher) and the
# Next.js frontend in two separate windows. The only thing you need to do is
# drop PDFs into  D:\Dream\data\dropbox  — everything else is automated.

param(
    [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Wait-ForHttp($Url, $TimeoutSec = 45) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $res = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($res.StatusCode -ge 200 -and $res.StatusCode -lt 500) {
                return $true
            }
        } catch {}
        Start-Sleep -Seconds 1
    }
    return $false
}

# 1. Make sure the dropbox folder exists
$dropbox = Join-Path $root "data\dropbox"
New-Item -ItemType Directory -Force -Path $dropbox | Out-Null
Write-Host "Dropbox folder: $dropbox"
Write-Host "  → drop PDFs (single files or sub-folders) here for auto-ingest."
Write-Host ""

# 2. Backend
$apiDir = Join-Path $root "apps\api"
$venv = Join-Path $apiDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venv)) { $venv = Join-Path $apiDir "venv\Scripts\python.exe" }
if (-not (Test-Path $venv)) { $venv = "python" }

Write-Host "Starting API on http://localhost:8000 (Swagger: /docs)"
Start-Process -WindowStyle Normal -FilePath "powershell" -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$apiDir'; & '$venv' -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
)

# 3. Frontend
if (-not $NoFrontend) {
    $webDir = Join-Path $root "apps\web"
    Write-Host "Starting Web UI on http://localhost:3000"
    Start-Process -WindowStyle Normal -FilePath "powershell" -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$webDir'; if (-not (Test-Path node_modules)) { npm install --legacy-peer-deps }; npm run dev"
    )
}

Write-Host ""
Write-Host "Waiting for local services to respond..."
$apiReady = Wait-ForHttp "http://localhost:8000/api/health"
$webReady = $NoFrontend -or (Wait-ForHttp "http://localhost:3000/dashboard")

Write-Host "Fully-automatic mode engaged."
Write-Host "  Drop PDFs into : $dropbox"
Write-Host "  Watch progress : http://localhost:3000/feed"
Write-Host "  Inspect status : http://localhost:8000/api/folder-watcher/status"
Write-Host "                   http://localhost:8000/api/autopilot/status"
Write-Host ""
Write-Host ("  API health     : " + ($(if ($apiReady) { "ready" } else { "not responding yet" })))
if (-not $NoFrontend) {
    Write-Host ("  Web UI         : " + ($(if ($webReady) { "ready" } else { "not responding yet" })))
}
