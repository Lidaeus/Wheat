$ErrorActionPreference = 'Stop'
$projRoot = Resolve-Path ".."
$env:PATH = "$projRoot\.venv\Scripts;" + $env:PATH

Write-Host ">>> Starting Path A: Pure PEST-GLM Independent Long-Run <<<" -ForegroundColor Green

# 1. Setup
$env:PEST_NOPTMAX = '30'
$env:USE_MGDA_ALPHAS = '0'
python "$projRoot\src\build_pest_setup.py"

# 2. Run PEST++ 
Write-Host "Running PEST++ GLM for 30 iterations..." -ForegroundColor Cyan
& "$projRoot\vendor\pestpp_5.2.16_iwin\bin\pestpp-glm.exe" ksas_mvp.pst

# 3. Export Result
if (-not (Test-Path "$projRoot\results")) { New-Item -ItemType Directory -Path "$projRoot\results" }
Copy-Item "ksas_mvp.par" -Destination "$projRoot\results\final_pest_params.dat" -Force

# 4. Immediate Evaluation of Path A results
Write-Host "Evaluating final PEST-GLM fit..." -ForegroundColor Cyan
$env:MGDA_PARAMS_PATH = "$projRoot\results\final_pest_params.dat"
python "$projRoot\src\compare_three.py" --progress

Write-Host "Path A Complete. Parameters saved to results\final_pest_params.dat" -ForegroundColor Green
