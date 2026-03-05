$ErrorActionPreference = 'Stop'
$projRoot = Resolve-Path ".."
$env:PATH = "$projRoot\.venv\Scripts;" + $env:PATH

Write-Host ">>> Final Tournament: Baseline vs Pure PEST vs PEST+MGDA <<<" -ForegroundColor Yellow

$resultsDir = "$projRoot\results"
$baselineParams = "$projRoot\work\params.dat" # Original baseline
$finalPest = "$resultsDir\final_pest_params.dat"
$finalMgda = "$resultsDir\final_mgda_params.dat"

# Check prerequisites
if (-not (Test-Path $finalPest)) { Write-Error "Path A results missing. Run run_pure_pest.ps1 first." }
if (-not (Test-Path $finalMgda)) { Write-Error "Path B results missing. Run run_pest_mgda.ps1 first." }

# Create a temporary workspace for evaluation
$evalWork = New-Item -ItemType Directory -Path "..\runs\tournament_$(Get-Date -Format 'yyyyMMdd_HHmm')" -Force

# Run comparison using the unified compare script
# We will pass the paths to the final param files as environment variables
$env:TOURNAMENT_BASELINE = $baselineParams
$env:TOURNAMENT_PEST = $finalPest
$env:TOURNAMENT_MGDA = $finalMgda

Write-Host "Executing unified evaluation..." -ForegroundColor Cyan
# Here we reuse src/compare_three.py but in a special 'Tournament Mode'
python "$projRoot\src\compare_three.py" --tournament

Write-Host "Tournament Complete! Check results in the latest run directory." -ForegroundColor Green
