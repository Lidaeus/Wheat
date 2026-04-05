$ErrorActionPreference = 'Stop'
$projRoot = Resolve-Path ".."
$env:PATH = "$projRoot\.venv\Scripts;" + $env:PATH

Write-Host ">>> Starting Path C: Pure PEST-IES Posterior Run <<<" -ForegroundColor Green

if ([string]::IsNullOrWhiteSpace($env:PESTPP_IES_NUM_REALS)) { $env:PESTPP_IES_NUM_REALS = '80' }
if ([string]::IsNullOrWhiteSpace($env:PESTPP_IES_SUBSET_SIZE)) { $env:PESTPP_IES_SUBSET_SIZE = '12' }

python "$projRoot\src\pest_builder.py" run --work-dir (Get-Location).Path

$iesExe = $env:PESTPP_IES
if ([string]::IsNullOrWhiteSpace($iesExe)) {
    $candidates = @(
        (Join-Path $projRoot "pestpp-ies.exe"),
        (Join-Path $projRoot "bin\pestpp-ies.exe"),
        (Join-Path $projRoot "vendor\pestpp_5.2.16_iwin\bin\pestpp-ies.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            $iesExe = $candidate
            break
        }
    }
}
if (-not (Test-Path -LiteralPath $iesExe)) {
    throw "pestpp-ies.exe not found. Set PESTPP_IES or put pestpp-ies.exe in $projRoot."
}

Write-Host "Running PEST++ IES..." -ForegroundColor Cyan
& $iesExe "ksas_mvp.pst"
if ($LASTEXITCODE -ne 0) {
    throw "pestpp-ies.exe failed (exit $LASTEXITCODE)"
}

$posteriorDir = Join-Path $projRoot "results\ies_posterior_latest"
if (-not (Test-Path -LiteralPath $posteriorDir)) {
    New-Item -ItemType Directory -Path $posteriorDir | Out-Null
}

$posteriorArgs = @(
    "$projRoot\src\pest_runner.py",
    "export-posterior",
    "--work-dir", (Get-Location).Path,
    "--prior-params", (Join-Path (Get-Location).Path "params.dat"),
    "--bounds-preview", (Join-Path (Get-Location).Path "parameter_bounds_preview.csv"),
    "--output-dir", $posteriorDir
)
if (-not [string]::IsNullOrWhiteSpace($env:POSTERIOR_INCLUDE_PARAMS)) {
    $posteriorArgs += @("--include-params", $env:POSTERIOR_INCLUDE_PARAMS)
}

python @posteriorArgs
if ($LASTEXITCODE -ne 0) {
    throw "posterior export failed (exit $LASTEXITCODE)"
}

Write-Host "Path C Complete. Posterior artifacts saved to $posteriorDir" -ForegroundColor Green
