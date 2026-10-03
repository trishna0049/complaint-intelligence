<#
.SYNOPSIS
  Developer commands for the Complaint Intelligence System (Windows PowerShell 5.1+ / PowerShell 7).

.EXAMPLE
  .\scripts\dev.ps1 setup     # venv + Python deps + npm deps + .env
  .\scripts\dev.ps1 train     # profile data, train classifiers, validate sentiment model
  .\scripts\dev.ps1 import    # load the dataset into SQLite
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
        Write-Host "`nSetup complete. Next: .\scripts\dev.ps1 train ; .\scripts\dev.ps1 import ; .\scripts\dev.ps1 start" -ForegroundColor Green
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

    "reset-db" {
        $db = Join-Path $Root "var\complaints.db"
        Get-ChildItem "$db*" -ErrorAction SilentlyContinue | Remove-Item -Force
        Write-Host "Deleted var\complaints.db (it is recreated on the next API start or import)"
    }

    "api" {
        Need-Venv
        $port = EnvValue "API_PORT" "18000"
        Run $Py @("-m", "uvicorn", "app.main:app", "--port", $port, "--reload") (Join-Path $Root "backend")
    }

    "web" { Run "npm" @("run", "dev") (Join-Path $Root "frontend") }

    "start" {
        Need-Venv
        Start-Process powershell -ArgumentList "-NoExit", "-File", "`"$PSCommandPath`"", "api"
        Start-Process powershell -ArgumentList "-NoExit", "-File", "`"$PSCommandPath`"", "web"
        $web = EnvValue "WEB_PORT" "15173"
        Write-Host "API: http://localhost:$(EnvValue 'API_PORT' '18000')/docs   App: http://localhost:$web" -ForegroundColor Cyan
    }

    "test" {
        Need-Venv
        Run $Py @("-m", "pytest")
        Run "npm" @("run", "test") (Join-Path $Root "frontend")
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
  train      Profile the dataset, train category/intent classifiers, validate the sentiment model
  import     Load data\ecommerce_support.csv into the SQLite database (idempotent)
  start      Start the API and the web app in two new windows
  api | web  Start only the API (uvicorn --reload) or only the Vite dev server
  test       Backend (pytest) + frontend (Vitest) tests
  lint       ruff + eslint + TypeScript type-check
  reset-db   Delete the SQLite database
"@
    }
}
