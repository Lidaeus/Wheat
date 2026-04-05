$ErrorActionPreference = 'Stop'

$projRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$python = Join-Path $projRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Project virtual environment not found: $python"
}
Set-Location $projRoot

& $python -m mypy src ..\autoresearch_sandbox
