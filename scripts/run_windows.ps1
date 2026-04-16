# Hedge Fund V7 - Native Windows runner (no Docker).
#
# Run from the repo root in PowerShell:
#   .\scripts\run_windows.ps1
#
# Prerequisites (install once, all with default options):
#   - Python 3.11     https://www.python.org/downloads/windows/
#   - PostgreSQL 16   https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
#                     During install, keep the default superuser password
#                     and pass it via $env:PGPASSWORD before running this script.
#   - Memurai (Redis) https://www.memurai.com/get-memurai   (free Developer edition)
#
# After the first run, two new PowerShell windows stay open:
#   - FastAPI  (http://localhost:8000)
#   - Celery worker (pool=solo, Windows-compatible)
# Close the windows (or Ctrl+C inside) to stop the services.

$ErrorActionPreference = "Stop"

# Resolve repo root (scripts/ -> ..)
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Write-Header($msg) {
    Write-Host ""
    Write-Host "--- $msg ---" -ForegroundColor Cyan
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Test-Port($port) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.ConnectAsync("127.0.0.1", $port).Wait(500) | Out-Null
        $ok = $c.Connected
        $c.Close()
        return $ok
    } catch {
        return $false
    }
}

Write-Host "=== Hedge Fund V7 - Local Windows Runner ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"

# ----- 1. Prerequisite binaries --------------------------------------------
Write-Header "Checking prerequisites"

$missing = @()
if (-not (Test-Command "python")) {
    Write-Host "[MISSING] python - install from https://www.python.org/downloads/windows/" -ForegroundColor Red
    $missing += "python"
} else {
    Write-Host "[OK] python"
}
if (-not (Test-Command "psql")) {
    Write-Host "[MISSING] psql (PostgreSQL client) - install PostgreSQL 16" -ForegroundColor Red
    $missing += "postgres"
} else {
    Write-Host "[OK] psql"
}
if ((Test-Command "memurai-cli") -or (Test-Command "redis-cli")) {
    Write-Host "[OK] redis/memurai client"
} else {
    Write-Host "[MISSING] Memurai - install from https://www.memurai.com/get-memurai" -ForegroundColor Red
    $missing += "memurai"
}
if ($missing.Count -gt 0) {
    Write-Host "`nInstall the missing tool(s), then re-run this script." -ForegroundColor Red
    exit 1
}

# ----- 2. Services running? -------------------------------------------------
Write-Header "Checking services"

if (Test-Port 5432) {
    Write-Host "[OK] Postgres listening on :5432"
} else {
    Write-Host "[WARN] Postgres not on :5432. Start it via Services.msc or 'net start postgresql-x64-16' (admin)." -ForegroundColor Yellow
    exit 1
}
if (Test-Port 6379) {
    Write-Host "[OK] Redis listening on :6379"
} else {
    Write-Host "[WARN] Memurai not on :6379. Start it via Services.msc or 'net start Memurai' (admin)." -ForegroundColor Yellow
    exit 1
}

# ----- 3. Python virtualenv + deps -----------------------------------------
Write-Header "Python virtualenv"

if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
}
& ".\.venv\Scripts\Activate.ps1"

# Fast check: is fastapi already installed?
$null = pip show fastapi 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Python deps (first run, a few minutes) ..."
    python -m pip install --upgrade pip
    pip install -r requirements.txt
} else {
    Write-Host "[OK] Python deps already installed (skip 'pip install -r requirements.txt' to force refresh)"
}

# ----- 4. .env configuration -----------------------------------------------
Write-Header "Configuration (.env)"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

# Patch Docker service hostnames -> localhost (idempotent)
$envText = Get-Content ".env" -Raw
$patched = $envText `
    -replace "@postgres:5432", "@localhost:5432" `
    -replace "//redis:6379",  "//localhost:6379"
if ($patched -ne $envText) {
    Set-Content ".env" $patched -NoNewline
    Write-Host "Patched .env: hostnames -> localhost"
} else {
    Write-Host "[OK] .env already points to localhost"
}

# ----- 5. Postgres role + database (idempotent) -----------------------------
Write-Header "Database setup"

if (-not $env:PGPASSWORD) {
    Write-Host "[INFO] `$env:PGPASSWORD not set; will attempt psql with no password (trust auth or .pgpass)." -ForegroundColor Yellow
}

# Create role if missing
$roleSql = "SELECT 1 FROM pg_roles WHERE rolname='hedgefund'"
$roleExists = (& psql -U postgres -h localhost -tAc $roleSql) 2>$null
if ($roleExists -ne "1") {
    & psql -U postgres -h localhost -c "CREATE ROLE hedgefund WITH LOGIN PASSWORD 'hedgefund' CREATEDB;" | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host "[OK] role 'hedgefund' created" }
    else { Write-Host "[WARN] could not create role; if it already exists this is fine." -ForegroundColor Yellow }
} else {
    Write-Host "[OK] role 'hedgefund' exists"
}

# Create DB if missing
$dbSql = "SELECT 1 FROM pg_database WHERE datname='hedgefund'"
$dbExists = (& psql -U postgres -h localhost -tAc $dbSql) 2>$null
if ($dbExists -ne "1") {
    & psql -U postgres -h localhost -c "CREATE DATABASE hedgefund OWNER hedgefund;" | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host "[OK] database 'hedgefund' created" }
    else { Write-Host "[WARN] could not create DB; check `$env:PGPASSWORD and pg_hba.conf." -ForegroundColor Yellow }
} else {
    Write-Host "[OK] database 'hedgefund' exists"
}

# ----- 6. Launch API + worker in separate windows ---------------------------
Write-Header "Starting services"

$activate = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"

$apiCmd = "Set-Location '$RepoRoot'; & '$activate'; " +
          "Write-Host '=== API (uvicorn) ===' -ForegroundColor Cyan; " +
          "uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

$workerCmd = "Set-Location '$RepoRoot'; & '$activate'; " +
             "Write-Host '=== Celery worker (pool=solo) ===' -ForegroundColor Cyan; " +
             "celery -A app.celery_app worker --loglevel=info --pool=solo -Q celery,default"

Start-Process powershell -ArgumentList "-NoExit", "-Command", $apiCmd
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit", "-Command", $workerCmd

# ----- 7. Done --------------------------------------------------------------
Write-Host ""
Write-Host "===========================================" -ForegroundColor Green
Write-Host "  Hedge Fund V7 running locally" -ForegroundColor Green
Write-Host "===========================================" -ForegroundColor Green
Write-Host "  API      http://localhost:8000"
Write-Host "  Docs     http://localhost:8000/docs"
Write-Host "  Health   http://localhost:8000/api/v1/health"
Write-Host ""
Write-Host "Two PowerShell windows were opened (API + worker)." -ForegroundColor Yellow
Write-Host "Close them (or Ctrl+C inside) to stop the services." -ForegroundColor Yellow
Write-Host ""
