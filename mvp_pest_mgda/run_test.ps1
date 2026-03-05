$env:MGDA_GATE_MODE = "off"
$env:MGDA_MAX_ITER = "5"
$env:MGDA_START_COUNT = "3"
$env:MGDA_START_MODE = "lhs"
. .\.venv\Scripts\Activate.ps1
.\scripts\run_mvp.ps1
