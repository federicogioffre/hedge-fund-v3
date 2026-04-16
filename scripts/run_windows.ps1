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
# PowerShell 7.3+ makes native command non-zero exit codes throw when
# $ErrorActionPreference is "Stop". We call tools like `pip show` and
# `psql -tAc` whose non-zero exits are informational (package missing,
# no rows), not failures, so opt out of that behaviour globally.
$PSNativeCommandUseErrorActionPreference = $false

# Resolve repo root (scripts/ -> ..)
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Run a native command, swallow stdout+stderr, return its exit code.
# Used for idempotent probes where non-zero != failure.
#
# Windows PowerShell 5.1 turns any native-command stderr line into a
# NativeCommandError *before* redirection takes effect, which explodes
# under $ErrorActionPreference=Stop even when we redirect with *>$null.
# Locally flip the preference and merge streams (2>&1) so stderr travels
# as plain output and never reaches the error stream.
function Invoke-NativeQuiet {
    param([scriptblock]$Cmd)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        $null = & $Cmd 2>&1
    } finally {
        $ErrorActionPreference = $prev
    }
    return $LASTEXITCODE
}

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

# Auto-locate psql.exe if it isn't on PATH. The EnterpriseDB installer
# leaves it in C:\Program Files\PostgreSQL\<ver>\bin\ by default. Add
# that directory to $env:Path for the current session so the user
# doesn't have to remember it every time they open a new shell.
if (-not (Get-Command "psql" -ErrorAction SilentlyContinue)) {
    $psqlCandidate = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue |
                     Sort-Object { [int]($_.Directory.Parent.Name) } -Descending |
                     Select-Object -First 1
    if ($psqlCandidate) {
        $env:Path += ";" + $psqlCandidate.DirectoryName
        Write-Host "[INFO] Added $($psqlCandidate.DirectoryName) to PATH for this session" -ForegroundColor DarkGray
    }
}

$missing = @()
if (-not (Test-Command "python")) {
    Write-Host "[MISSING] python - install from https://www.python.org/downloads/windows/" -ForegroundColor Red
    $missing += "python"
} else {
    # Gate on interpreter version: psycopg2-binary and pydantic-core only
    # publish prebuilt wheels for CPython <= 3.12. Newer versions fall back
    # to building from source, which needs MSVC + Rust and usually fails.
    $pyVer = (& python -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null).Trim()
    $pyMajor = 0; $pyMinor = 0
    if ($pyVer -match '^(\d+)\.(\d+)$') { $pyMajor = [int]$Matches[1]; $pyMinor = [int]$Matches[2] }

    if ($pyMajor -eq 3 -and $pyMinor -ge 10 -and $pyMinor -le 12) {
        Write-Host "[OK] python $pyVer"
    } else {
        Write-Host "[BAD] python $pyVer - supported range is 3.10-3.12." -ForegroundColor Red
        Write-Host "      psycopg2-binary and pydantic-core have no wheels for Python $pyVer." -ForegroundColor Yellow
        Write-Host "      Install Python 3.12 (https://www.python.org/downloads/windows/)" -ForegroundColor Yellow
        Write-Host "      and recreate the venv with:" -ForegroundColor Yellow
        Write-Host "        deactivate; Remove-Item -Recurse -Force .venv; py -3.12 -m venv .venv" -ForegroundColor Yellow
        $missing += "python-version"
    }
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

# Fast check: can we import fastapi from the current venv?
# Using `python -c` instead of `pip show` because pip writes WARNINGs to
# stderr even on success (e.g. new version available), which trips up
# Windows PowerShell 5.1 even with stream redirection.
$fastapiExit = Invoke-NativeQuiet { python -c "import fastapi" }
if ($fastapiExit -ne 0) {
    Write-Host "Installing Python deps (first run, a few minutes) ..."
    python -m pip install --upgrade pip
    pip install -r requirements.txt
} else {
    Write-Host "[OK] Python deps already installed (delete .venv\ to force a clean reinstall)"
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

# Run psql and capture stdout as a string, never letting stderr reach
# the PS error stream. Returns the trimmed stdout (empty string on error).
function Invoke-Psql {
    param([string]$Sql)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        $out = & psql -U postgres -h localhost -tAc $Sql 2>&1 | Out-String
    } finally {
        $ErrorActionPreference = $prev
    }
    return "$out".Trim()
}

# Create role if missing
$roleExists = Invoke-Psql "SELECT 1 FROM pg_roles WHERE rolname='hedgefund'"
if ($roleExists -ne "1") {
    $rc = Invoke-NativeQuiet { psql -U postgres -h localhost -c "CREATE ROLE hedgefund WITH LOGIN PASSWORD 'hedgefund' CREATEDB;" }
    if ($rc -eq 0) { Write-Host "[OK] role 'hedgefund' created" }
    else { Write-Host "[WARN] could not create role; if it already exists this is fine." -ForegroundColor Yellow }
} else {
    Write-Host "[OK] role 'hedgefund' exists"
}

# Create DB if missing
$dbExists = Invoke-Psql "SELECT 1 FROM pg_database WHERE datname='hedgefund'"
if ($dbExists -ne "1") {
    $rc = Invoke-NativeQuiet { psql -U postgres -h localhost -c "CREATE DATABASE hedgefund OWNER hedgefund;" }
    if ($rc -eq 0) { Write-Host "[OK] database 'hedgefund' created" }
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
