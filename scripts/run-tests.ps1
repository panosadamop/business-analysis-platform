<#
.SYNOPSIS
    Runs the automated test suite on Windows PowerShell.

.DESCRIPTION
    Default: backend unit, backend API, acceptance scenarios, frontend unit and
    type check. These need no infrastructure.

    -All  also runs the live deployment suites (API end to end and browser end
          to end) against a running stack.
    -E2E  runs only the live deployment suites.

.EXAMPLE
    .\scripts\run-tests.ps1
    .\scripts\run-tests.ps1 -All
#>
param(
    [switch]$All,
    [switch]$E2E,
    [switch]$Coverage
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$baseUrl = if ($env:AIT_E2E_BASE_URL) { $env:AIT_E2E_BASE_URL } else { 'http://localhost:8080' }

$python = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

$results = [ordered]@{}
$failed = @()

function Invoke-Suite {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ""
    Write-Host "-- $Name --------------------------------------------"
    $started = Get-Date
    & $Body
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    if ($LASTEXITCODE -eq 0) {
        $results[$Name] = "pass ${elapsed}s"
    } else {
        $results[$Name] = "FAIL ${elapsed}s"
        $script:failed += $Name
    }
}

$runDefault = -not $E2E
$runE2E = $All -or $E2E

if ($runDefault) {
    $coverageArgs = if ($Coverage) { @('--cov=app', '--cov-report=term-missing') } else { @() }
    Invoke-Suite 'backend unit (service level)' { Push-Location $backend; & $python -m pytest tests/unit -q @coverageArgs; Pop-Location }
    Invoke-Suite 'backend API (functional)' { Push-Location $backend; & $python -m pytest tests/api -q; Pop-Location }
    Invoke-Suite 'acceptance scenarios AT-01..AT-20' { Push-Location $backend; & $python -m pytest tests/acceptance -q; Pop-Location }
    Invoke-Suite 'frontend unit and component' { Push-Location $frontend; & npx vitest run; Pop-Location }
    Invoke-Suite 'frontend type check' { Push-Location $frontend; & npx tsc --noEmit; Pop-Location }
}

if ($runE2E) {
    $up = $false
    try {
        $probe = Invoke-WebRequest -Uri "$baseUrl/health" -TimeoutSec 5 -UseBasicParsing
        $up = $probe.StatusCode -eq 200
    } catch { $up = $false }

    if ($up) {
        $env:AIT_E2E_BASE_URL = $baseUrl
        Invoke-Suite 'live API end to end' { Push-Location $backend; & $python -m pytest tests/e2e -q; Pop-Location }
        Invoke-Suite 'browser end to end' { Push-Location $frontend; & npx playwright test; Pop-Location }
    } else {
        Write-Host ""
        Write-Host "!! No deployment answering at $baseUrl - skipping the live suites."
        Write-Host "   Start one with: docker compose up -d; docker compose run --rm seed"
        $results['live suites'] = "skipped (no deployment at $baseUrl)"
    }
}

Write-Host ""
Write-Host "== summary ========================================="
foreach ($entry in $results.GetEnumerator()) {
    Write-Host ("  {0,-40} {1}" -f $entry.Key, $entry.Value)
}

if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "FAILED: $($failed -join ', ')"
    exit 1
}
Write-Host ""
Write-Host "All selected suites passed."
