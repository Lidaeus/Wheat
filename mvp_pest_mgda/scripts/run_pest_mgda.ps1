$ErrorActionPreference = 'Stop'
$projRoot = Resolve-Path ".."
$env:PATH = "$projRoot\.venv\Scripts;" + $env:PATH

Write-Host ">>> Starting Path B: PEST+MGDA Pareto Independent Long-Run <<<" -ForegroundColor Green

# 1. Configuration for MGDA-only path
$env:PEST_NOPTMAX = '-1' # Force PEST to only act as a Jacobian sampler
$env:MGDA_MAX_ITER = '30'
$env:MGDA_GATE_MODE = 'off'

# 2. Execute the existing loop (now running in decoupled mode)
& ".\run_mvp.ps1"

# 3. Export Final Result from the latest run
$lastRun = Get-ChildItem "..\runs\_runs" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$finalIter = Get-ChildItem "$($lastRun.FullName)" -Directory -Filter "iter_*" | Sort-Object Name -Descending | Select-Object -First 1
$mgdaParams = Join-Path $finalIter.FullName "mgda\params_mgda.dat"

if (Test-Path $mgdaParams) {
    if (-not (Test-Path "$projRoot\results")) { New-Item -ItemType Directory -Path "$projRoot\results" }
    Copy-Item $mgdaParams -Destination "$projRoot\results\final_mgda_params.dat" -Force
    Write-Host "Path B Complete. Parameters saved to results\final_mgda_params.dat" -ForegroundColor Green
} else {
    Write-Error "MGDA run failed to produce final parameters."
}



