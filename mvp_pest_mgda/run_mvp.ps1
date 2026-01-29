$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runsRoot = Join-Path $root "_runs"
New-Item -ItemType Directory -Path $runsRoot -Force | Out-Null

$runId = Get-Date -Format "yyyyMMdd_HHmmss"
$runDir = Join-Path $runsRoot $runId
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$keepRuns = 20
$oldRuns = Get-ChildItem -LiteralPath $runsRoot -Directory | Sort-Object Name -Descending | Select-Object -Skip $keepRuns
foreach ($d in $oldRuns) {
    Remove-Item -LiteralPath $d.FullName -Recurse -Force
}

Set-Location $runDir

Write-Host "[1/4] Build PEST setup (and baseline run)" -ForegroundColor Cyan
python (Join-Path $root "build_pest_setup.py")
if ($LASTEXITCODE -ne 0) { throw "build_pest_setup.py failed (exit $LASTEXITCODE)" }

Write-Host "[2/4] Run PEST++ GLM to generate JCO (NOPTMAX=-1)" -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath "$root\pestpp-glm.exe")) {
    throw "pestpp-glm.exe not found in $root. Download pestpp-glm.exe here first."
}
& "$root\pestpp-glm.exe" ksas_mvp.pst
if ($LASTEXITCODE -ne 0) { throw "pestpp-glm.exe failed (exit $LASTEXITCODE)" }

Write-Host "[3/4] Compute MGDA parameter update and write params.dat" -ForegroundColor Cyan
python (Join-Path $root "mgda_update.py")
if ($LASTEXITCODE -ne 0) { throw "mgda_update.py failed (exit $LASTEXITCODE)" }

Write-Host "[4/4] Run DSSAT once with updated params.dat" -ForegroundColor Cyan
python (Join-Path $root "run_model.py")
if ($LASTEXITCODE -ne 0) { throw "run_model.py failed (exit $LASTEXITCODE)" }

Write-Host "Done." -ForegroundColor Green
Write-Host "Run directory: $runDir" -ForegroundColor Green
Write-Host "Key files: mgda_report.txt, pest_out.dat, Evaluate.OUT" -ForegroundColor Green
