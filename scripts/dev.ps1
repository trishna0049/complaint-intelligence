<#
.SYNOPSIS
  Developer commands for the Complaint Intelligence System (Windows PowerShell 5.1+ / PowerShell 7).

.EXAMPLE
  .\scripts\dev.ps1 setup     # venv + Python deps + npm deps + .env
  .\scripts\dev.ps1 up        # Postgres (pgvector) + Redis in Docker
  .\scripts\dev.ps1 migrate   # Alembic migrations
  .\scripts\dev.ps1 seed      # teams, categories, admin + dataset agents
  .\scripts\dev.ps1 train     # profile data, train classifiers, validate sentiment model
  .\scripts\dev.ps1 import    # load the dataset into Postgres
  .\scripts\dev.ps1 embed     # MiniLM embeddings for similar-ticket search (after import)
  .\scripts\dev.ps1 start     # API + web app (opens two windows)
#>
param(
    [Parameter(Position = 0)][string]$Command = "help",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root "backend\.venv\Scripts\python.exe"
# Keep model and package caches inside the project (not on the system drive).
$env:HF_HOME = Join-Path $Root "ml\.hf_cache"

function Run([string]$Exe, [string[]]$Arguments, [string]$Dir = $Root) {
    Push-Location $Dir
    # Native tools (uvicorn, pip, npm) log to stderr; under "Stop", Windows PowerShell 5.1 would treat
    # that as a terminating error when output is redirected. Failure is detected via the exit code instead.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Failed ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
    } finally {
        $ErrorActionPreference = $previous
        Pop-Location
    }
}

function EnvValue([string]$Name, [string]$Default) {
    $file = Join-Path $Root ".env"
    if (Test-Path $file) {
        $line = Get-Content $file | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -First 1
        if ($line) { $v = ($line -split "=", 2)[1].Trim(); if ($v) { return $v } }
    }
    return $Default
}

function Need-Venv { if (-not (Test-Path $Py)) { throw "Run '.\scripts\dev.ps1 setup' first." } }
function Compose([string[]]$Arguments) { Run "docker" (@("compose", "--project-directory", $Root) + $Arguments) }
function Wait-Healthy([string]$Service) {
    for ($i = 0; $i -lt 60; $i++) {
        $id = (& docker compose --project-directory $Root ps -q $Service)
        if ($id) {
            $state = (& docker inspect -f "{{.State.Health.Status}}" $id)
            if ($state -eq "healthy") { return }
        }
        Start-Sleep -Seconds 2
    }
    throw "$Service did not become healthy (docker compose logs $Service)"
}
function Need-Data {
    if (-not (Test-Path (Join-Path $Root "data\ecommerce_support.csv"))) {
        throw "Put the Kaggle 'eCommerce Customer Service Satisfaction' CSV at data\ecommerce_support.csv"
    }
}

switch ($Command) {
    "setup" {
        if (-not (Test-Path (Join-Path $Root ".env"))) { Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env"); Write-Host "Created .env" }
        if (-not (Test-Path $Py)) { Run "python" @("-m", "venv", "backend\.venv") }
        Run $Py @("-m", "pip", "install", "--no-cache-dir", "--upgrade", "pip")
        Run $Py @("-m", "pip", "install", "--no-cache-dir", "-r", "backend\requirements.txt", "-r", "backend\requirements-dev.txt")
        Run "npm" @("install", "--no-audit", "--no-fund", "--cache", (Join-Path $Root ".npm-cache")) (Join-Path $Root "frontend")
        Write-Host "`nSetup complete. Next: .\scripts\dev.ps1 up ; migrate ; seed ; train ; import ; embed ; start" -ForegroundColor Green
    }

    "up" {
        Compose @("up", "-d", "postgres", "redis", "kafka", "kafka-ui")
        Wait-Healthy "postgres"; Wait-Healthy "redis"; Wait-Healthy "kafka"
        Write-Host "Postgres on localhost:$(EnvValue 'POSTGRES_PORT' '15432'), Redis on localhost:$(EnvValue 'REDIS_PORT' '16379')" -ForegroundColor Cyan
        Write-Host "Kafka on localhost:$(EnvValue 'KAFKA_PORT' '19092'), Kafka UI on http://localhost:$(EnvValue 'KAFKA_UI_PORT' '18090')" -ForegroundColor Cyan
    }

    "down" { Compose (@("down") + $Rest) }

    "migrate" {
        Need-Venv
        Run $Py @("-m", "scripts.prepare_db") (Join-Path $Root "backend")
    }

    "seed" {
        # Departments, teams, categories, the admin and every dataset agent (idempotent). Prints the demo logins.
        Need-Venv
        Run $Py (@("-m", "scripts.seed") + $Rest) (Join-Path $Root "backend")
    }

    "train" {
        Need-Venv; Need-Data
        Run $Py @("ml\profile_dataset.py")
        Run $Py @("-u", "ml\train_classifiers.py")
        Run $Py @("-u", "ml\eval_sentiment.py")
    }

    "import" {
        Need-Venv; Need-Data
        Run $Py (@("-m", "scripts.import_dataset") + $Rest) (Join-Path $Root "backend")
    }

    "embed" {
        # Backfill ticket embeddings (MiniLM, 384 dims) for similar-ticket search and copilot grounding (idempotent).
        Need-Venv
        Run $Py (@("-m", "scripts.embed_tickets") + $Rest) (Join-Path $Root "backend")
    }

    "eval-retrieval" {
        # Knowledge-base and similar-ticket retrieval on fixed examples -> ml\reports\retrieval_report.md
        Need-Venv
        Run $Py @("ml\eval_retrieval.py")
    }

    "reset-db" {
        # Drops every table in the development database and re-applies the migrations (data is lost).
        Need-Venv
        Run $Py @("-m", "scripts.prepare_db", "--reset") (Join-Path $Root "backend")
        Write-Host "Database reset. Re-load the data with: .\scripts\dev.ps1 import" -ForegroundColor Yellow
    }

    "api" {
        Need-Venv
        $port = EnvValue "API_PORT" "18000"
        Run $Py @("-m", "uvicorn", "app.main:app", "--port", $port, "--reload") (Join-Path $Root "backend")
    }

    "web" { Run "npm" @("run", "dev") (Join-Path $Root "frontend") }

    "topics" {
        # Create the Kafka topics for EVENTS_PREFIX (idempotent; add --reset to delete and recreate them).
        Need-Venv
        Run $Py (@("-m", "app.workers.run", "topics") + $Rest) (Join-Path $Root "backend")
    }

    "workers" {
        # Outbox relay + AI, LLM, SLA and notification workers (Kafka). One process; or pass a single name:
        # .\scripts\dev.ps1 workers ai | llm | sla | notification | relay
        Need-Venv
        $what = if ($Rest) { $Rest } else { @("all") }
        Run $Py (@("-m", "app.workers.run") + $what) (Join-Path $Root "backend")
    }

    "start" {
        Need-Venv
        Run $Py @("-m", "app.workers.run", "topics") (Join-Path $Root "backend")
        Start-Process powershell -ArgumentList "-NoExit", "-File", "`"$PSCommandPath`"", "api"
        Start-Process powershell -ArgumentList "-NoExit", "-File", "`"$PSCommandPath`"", "workers"
        Start-Process powershell -ArgumentList "-NoExit", "-File", "`"$PSCommandPath`"", "web"
        $web = EnvValue "WEB_PORT" "15173"
        Write-Host "API: http://localhost:$(EnvValue 'API_PORT' '18000')/docs   App: http://localhost:$web   Kafka UI: http://localhost:$(EnvValue 'KAFKA_UI_PORT' '18090')" -ForegroundColor Cyan
    }

    "test" {
        Need-Venv
        Run $Py @("-m", "pytest")
        Run "npm" @("run", "test") (Join-Path $Root "frontend")
    }

    "e2e" {
        # Playwright starts its own API + web servers (ports 18100/15200, var\e2e.db, mock LLM).
        Need-Venv
        if (-not (Test-Path (Join-Path $Root "ml\artifacts\classifier_meta.json"))) { throw "Train the models first: .\scripts\dev.ps1 train" }
        $e2e = Join-Path $Root "tests\e2e"
        $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Root ".pw-browsers"
        if (-not (Test-Path (Join-Path $e2e "node_modules"))) {
            Run "npm" @("install", "--no-audit", "--no-fund", "--cache", (Join-Path $Root ".npm-cache")) $e2e
        }
        Run "npx" @("playwright", "install", "chromium") $e2e
        Run "npx" (@("playwright", "test") + $Rest) $e2e
    }

    "lint" {
        Need-Venv
        Run $Py @("-m", "ruff", "check", "backend", "ml", "tests")
        Run "npm" @("run", "lint") (Join-Path $Root "frontend")
        Run "npm" @("run", "typecheck") (Join-Path $Root "frontend")
    }

    default {
        Write-Host @"
Usage: .\scripts\dev.ps1 <command>

  setup      Create .env, Python venv (backend\.venv) and install all dependencies
  up | down  Start / stop Postgres (pgvector), Redis, Kafka (KRaft) and Kafka UI in Docker (down -v deletes the data)
  migrate    Create the database if needed and apply the Alembic migrations
  train      Profile the dataset, train category/intent classifiers, validate the sentiment model
  seed       Teams, categories, admin, the 1,371 dataset agents and the knowledge base (idempotent; prints logins)
  import     Load data\ecommerce_support.csv into Postgres (idempotent, batched)
  embed      Embed tickets for similar-ticket search (MiniLM; run after import, idempotent)
  eval-retrieval  Retrieval evaluation on fixed examples (needs seed) -> ml\reports\retrieval_report.md
  start      Create the Kafka topics, then start the API, the workers and the web app in three new windows
  workers    Outbox relay + the AI, LLM, SLA and notification workers (or one: workers ai|llm|sla|notification|relay)
  topics     Create the Kafka topics (topics --reset deletes and recreates them)
  api | web  Start only the API (uvicorn --reload) or only the Vite dev server
  test       Backend (pytest) + frontend (Vitest) tests
  e2e        Playwright end-to-end test of the full complaint flow (own servers + database)
  lint       ruff + eslint + TypeScript type-check
  reset-db   Drop and re-create the development database schema (data is lost)
"@
    }
}
