$ErrorActionPreference = 'Stop'

$projRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
Set-Location $projRoot

python -m mypy src
