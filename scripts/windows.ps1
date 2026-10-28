<#
.SYNOPSIS
  Native Windows runner (PowerShell, no Docker, no WSL) for the Makefile targets.

.DESCRIPTION
  The Makefile needs make and bash, and `make up` needs docker or `su postgres`.
  This script runs the same `python -m src.*` steps in the same order against a
  locally installed PostgreSQL. The pipeline itself is unchanged.

  Usage (from the repository root):
    powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 <target>

  Targets: setup, init-db, check, build, test, web, web-open, demo, demo-login,
           demo-interactive, ingest, profile, dq, model, ledger, reference,
           semantic, entitlements, questions, evaluate, extra, workbook, ddr, zip,
           deliverables, status, simulate, simulate-faults, all, clean, help

  Connection settings come from the same environment variables as
  src/config.py (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD) with the
  same defaults. Nothing secret is written to disk.
#>
param(
    [Parameter(Position = 0)][string]$Target = "help",
    # Base interpreter for `setup`, e.g. -Python "C:\Python312\python.exe".
    [string]$Python = "",
    # PostgreSQL superuser for `init-db` (psql prompts for its password).
    [string]$PgSuperuser = "postgres",
    [string]$WebHost = "127.0.0.1",
    [int]$WebPort = 8080
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root
# UTF-8 for stdout and default file encoding: Windows defaults to cp1252.
$env:PYTHONUTF8 = "1"

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$Py = if (Test-Path $VenvPy) { $VenvPy } else { "python" }

function Invoke-Py {
    & $Py @args
    if ($LASTEXITCODE -ne 0) { throw "failed (exit $LASTEXITCODE): python $($args -join ' ')" }
}

function Get-BasePython {
    if ($Python) { return , @($Python) }
    if (Get-Command py -ErrorAction SilentlyContinue) { return , @("py", "-3") }
    return , @("python")
}

function Invoke-Setup {
    $base = Get-BasePython
    $exe = $base[0]; $rest = @($base | Select-Object -Skip 1)
    $version = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($LASTEXITCODE -ne 0) { throw "No Python found. Install Python 3.11+ from python.org, or pass -Python <path>." }
    & $exe @rest -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Python $version found; this project needs 3.11 or newer (pyproject.toml)." }
    Write-Host "setup | using Python $version ($($base -join ' '))"
    if (-not (Test-Path $VenvPy)) {
        & $exe @rest -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "could not create .venv" }
    }
    $script:Py = $VenvPy
    Invoke-Py -m pip install --quiet --upgrade pip
    Invoke-Py -m pip install --quiet -e ".[dev]"
    Write-Host "setup | dependencies installed into .venv"
}

function Find-Psql {
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $found = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Directory.Parent.Name -replace '\D', '') } -Descending |
        Select-Object -First 1
    if ($found) { return $found.FullName }
    throw "psql.exe not found. Add your PostgreSQL bin folder (e.g. C:\Program Files\PostgreSQL\16\bin) to PATH."
}

function Invoke-InitDb {
    $psql = Find-Psql
    $pgHost = if ($env:PGHOST) { $env:PGHOST } else { "localhost" }
    $port = if ($env:PGPORT) { $env:PGPORT } else { "5432" }
    $db = if ($env:PGDATABASE) { $env:PGDATABASE } else { "berka" }
    $owner = if ($env:PGUSER) { $env:PGUSER } else { "berka_owner" }
    $ownerPw = if ($env:PGPASSWORD) { $env:PGPASSWORD } else { "berka_owner_pw" }
    Write-Host "init-db | as $PgSuperuser on ${pgHost}:$port -> role $owner, database $db"
    # PGPASSWORD/PGUSER describe the project owner; hide them so psql asks for
    # the superuser's own password instead of reusing the owner's.
    $savedPw = $env:PGPASSWORD; $savedUser = $env:PGUSER
    Remove-Item Env:PGPASSWORD, Env:PGUSER -ErrorAction SilentlyContinue
    try {
        & $psql -X -h $pgHost -p $port -U $PgSuperuser -d postgres -v ON_ERROR_STOP=1 `
            -v "owner=$owner" -v "owner_pw=$ownerPw" -v "dbname=$db" `
            -f (Join-Path $Root "scripts\windows_init_db.sql")
        if ($LASTEXITCODE -ne 0) { throw "init-db failed (psql exit $LASTEXITCODE)" }
    } finally {
        if ($null -ne $savedPw) { $env:PGPASSWORD = $savedPw }
        if ($null -ne $savedUser) { $env:PGUSER = $savedUser }
    }
    Write-Host "init-db | done"
}

function Invoke-Check {
    & $Py -c "import psycopg, yaml, sqlglot, openpyxl, docx"
    if ($LASTEXITCODE -ne 0) { throw "Python dependencies missing. Run: scripts\windows.ps1 setup" }
    & $Py -c "from src import db; c = db.connect(); c.execute('SELECT 1'); print('check | database reachable')"
    if ($LASTEXITCODE -ne 0) { throw "Cannot connect to PostgreSQL. Is the service running, and did you run init-db?" }
}

function Invoke-Model {
    Invoke-Py -m src.build_model
    # Rebuilding core drops the dependent ai views; re-apply them (as the Makefile does).
    Invoke-Py -m src.build_security
}

function Invoke-Target([string]$name) {
    switch ($name) {
        "setup"            { Invoke-Setup }
        "init-db"          { Invoke-InitDb }
        "check"            { Invoke-Check }
        "ingest"           { Invoke-Py -m src.ingest }
        "profile"          { Invoke-Py -m src.profile_data }
        "dq"               { Invoke-Py -m src.dq_runner }
        "model"            { Invoke-Model }
        "ledger"           { Invoke-Py -m src.cleaning_ledger }
        "demo"             { Invoke-Py -m src.worked_example }
        "demo-login"       { Invoke-Py -m src.demo_console --script }
        "demo-interactive" { Invoke-Py -m src.demo_console --interactive }
        "web"              { Invoke-Py -m src.webapp --host $WebHost --port $WebPort }
        "web-open"         { Invoke-Py -m src.webapp --host $WebHost --port $WebPort --open }
        "reference"        { Invoke-Py -m src.run_reference }
        "semantic"         { Invoke-Py -m src.semantic_context --write }
        "entitlements"     { Invoke-Py -m src.build_security }
        "questions"        { Invoke-Py -m src.run_questions }
        "evaluate"         { Invoke-Py -m src.evaluate }
        "extra"            {
            Invoke-Py -m src.run_reference --suite extra
            Invoke-Py -m src.run_questions --suite extra
            Invoke-Py -m src.evaluate --suite extra
        }
        "workbook"         { Invoke-Py -m src.make_workbook }
        "ddr"              { Invoke-Py -m src.make_ddr }
        "zip"              { Invoke-Py -m src.make_zip }
        "deliverables"     { "workbook", "ddr", "zip" | ForEach-Object { Invoke-Target $_ } }
        "status"           { Invoke-Py -m src.make_status }
        "simulate"         { Invoke-Py scripts\simulate_agents.py }
        "simulate-faults"  {
            foreach ($f in "scope", "contract", "acceptance", "dangling-flag") {
                & $Py scripts\simulate_agents.py --fault $f *> $null
                if ($LASTEXITCODE -ne 0) { throw "simulate | fault $f -> NOT CAUGHT" }
                Write-Host "simulate | fault $f -> caught"
            }
            Invoke-Py scripts\simulate_agents.py --scenario propose
        }
        "test"             { Invoke-Py -m pytest }
        # Same steps as `make build`, minus `up` (PostgreSQL runs as a Windows service).
        "build"            {
            "check", "ingest", "profile", "dq", "model", "ledger", "reference",
            "semantic", "entitlements", "demo", "test" | ForEach-Object { Invoke-Target $_ }
            Write-Host "build | done. Try: scripts\windows.ps1 web-open"
        }
        "all"              { "build", "questions", "evaluate", "deliverables", "status" | ForEach-Object { Invoke-Target $_ } }
        "clean"            { Invoke-Py -m src.ingest --drop-all }
        default            { Get-Help $PSCommandPath -Detailed | Out-Host }
    }
}

Invoke-Target $Target
