$ErrorActionPreference = 'Stop'

$cwd = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $cwd

Write-Host "[1/4] Build PEST setup (and baseline run)" -ForegroundColor Cyan
python build_pest_setup.py
if ($LASTEXITCODE -ne 0) { throw "build_pest_setup.py failed (exit $LASTEXITCODE)" }

Write-Host "[2/4] Run PEST++ GLM to generate JCO (NOPTMAX=-1)" -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath "$cwd\pestpp-glm.exe")) {
    throw "pestpp-glm.exe not found in $cwd. Download pestpp-glm.exe here first."
}
& "$cwd\pestpp-glm.exe" ksas_mvp.pst
if ($LASTEXITCODE -ne 0) { throw "pestpp-glm.exe failed (exit $LASTEXITCODE)" }

Write-Host "[3/4] Compute MGDA parameter update and write params.dat" -ForegroundColor Cyan
python mgda_update.py
if ($LASTEXITCODE -ne 0) { throw "mgda_update.py failed (exit $LASTEXITCODE)" }

Write-Host "[4/4] Run DSSAT once with updated params.dat" -ForegroundColor Cyan
python run_model.py
if ($LASTEXITCODE -ne 0) { throw "run_model.py failed (exit $LASTEXITCODE)" }

Write-Host "Done. See mgda_report.txt and pest_out.dat" -ForegroundColor Green
