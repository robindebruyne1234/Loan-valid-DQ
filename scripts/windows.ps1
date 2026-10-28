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
           semantic, entitlements, questions, evaluate, workbook, ddr, zip,
           deliverables, status, simulate, simulate-faults, all, clean, help,
           llm-pull, llm-check, llm-warm, questions-local, evaluate-local

  Connection settings come from the same environment variables as
  src/config.py (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD) with the
  same defaults. Nothing secret is written to disk.

  The model step (web step 7, questions) runs on a local Ollama model unless
  LLM_PROVIDER is already set: no API key, no paid inference. See
  docs/LOCAL_LLM_WINDOWS.md.
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

# Local, free inference by default: Ollama and the model src/config.py names
# for it. Set LLM_PROVIDER (and LLM_MODEL) beforehand to use another provider.
if (-not $env:LLM_PROVIDER) { $env:LLM_PROVIDER = "ollama" }
# A laptop CPU evaluates the semantic layer slowly the first time; see the docs.
if (-not $env:LLM_TIMEOUT_SECONDS -and $env:LLM_PROVIDER -eq "ollama") { $env:LLM_TIMEOUT_SECONDS = "900" }
# CPU only unless told otherwise: on a 2 GB laptop GPU, Ollama's Vulkan backend
# loaded the model once and then crashed on every load. -1 lets Ollama decide.
if (-not $env:OLLAMA_NUM_GPU -and $env:LLM_PROVIDER -eq "ollama") { $env:OLLAMA_NUM_GPU = "0" }

# Where a local model's question run goes, so it never replaces the recorded
# Claude run in dq\results\llm_results.json that the deliverables are built from.
$LocalResults = "dq\results\local\llm_results.json"
$LocalEvaluation = "dq\results\local\evaluation.json"

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
    $found = Get-ChildItem "D:\Programmas\PostGres\bin\psql.exe" -ErrorAction SilentlyContinue |
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

function Find-Ollama {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # The installer adds itself to PATH, but only for shells opened afterwards.
    $default = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $default) { return $default }
    throw "ollama.exe not found. Install it with: winget install --id Ollama.Ollama -e --source winget"
}

function Invoke-LlmPull {
    $ollama = Find-Ollama
    $model = & $Py -c "from src import config; print(config.LLM_MODEL)"
    if ($LASTEXITCODE -ne 0) { throw "could not read the configured model from src/config.py" }
    Write-Host "llm-pull | $ollama pull $model"
    & $ollama pull $model
    if ($LASTEXITCODE -ne 0) { throw "ollama pull $model failed (exit $LASTEXITCODE). Is the Ollama app running?" }
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
        "questions"        {
            if ($env:LLM_PROVIDER -eq "ollama") {
                throw "questions replaces the recorded Claude run (dq\results\llm_results.json). For the local model run: scripts\windows.ps1 questions-local"
            }
            Invoke-Py -m src.run_questions
        }
        "evaluate"         { Invoke-Py -m src.evaluate }
        "llm-pull"         { Invoke-LlmPull }
        "llm-check"        { Invoke-Py -m src.llm_client }
        "llm-warm"         { Invoke-Py -m src.llm_client --warm }
        "questions-local"  { Invoke-Py -m src.run_questions --output $LocalResults --log-subdir local }
        "evaluate-local"   { Invoke-Py -m src.evaluate --llm-results $LocalResults --output $LocalEvaluation }
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
        "all"              {
            $ask = if ($env:LLM_PROVIDER -eq "ollama") { "questions-local", "evaluate-local" } else { "questions", "evaluate" }
            @("build") + $ask + @("deliverables", "status") | ForEach-Object { Invoke-Target $_ }
        }
        "clean"            { Invoke-Py -m src.ingest --drop-all }
        default            { Get-Help $PSCommandPath -Detailed | Out-Host }
    }
}

Invoke-Target $Target
