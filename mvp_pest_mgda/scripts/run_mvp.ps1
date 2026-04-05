$ErrorActionPreference = 'Stop'

$batchChild = $env:BATCH_CHILD
$batchConfigsRaw = $env:BATCH_PROJECT_CONFIGS
$startMode = $env:MGDA_START_MODE
$startCountRaw = $env:MGDA_START_COUNT
$startParallelRaw = $env:MGDA_START_PARALLEL

function Split-PathList {
    param([string]$Value)
    $out = @()
    if ([string]::IsNullOrWhiteSpace($Value)) { return $out }
    foreach ($tok in ($Value -split "[`r`n;,]+" | ForEach-Object { $_.Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $out += $tok
    }
    return $out
}

function Get-CultivarCode {
    param([string]$FilexPath)
    if ([string]::IsNullOrWhiteSpace($FilexPath)) { return "" }
    if (-not (Test-Path -LiteralPath $FilexPath)) { return "" }
    $inSection = $false
    foreach ($line in (Get-Content -LiteralPath $FilexPath -ErrorAction SilentlyContinue)) {
        if ($line.StartsWith("*CULTIVARS")) { $inSection = $true; continue }
        if (-not $inSection) { continue }
        if (-not $line.Trim()) { continue }
        if ($line.StartsWith("@")) { continue }
        if ($line.StartsWith("*")) { break }
        $parts = $line -split "\s+"
        if ($parts.Count -ge 3) { return $parts[2].Trim() }
    }
    return ""
}

if ([string]::IsNullOrWhiteSpace($batchChild)) {
    $batchConfigs = Split-PathList $batchConfigsRaw
    $startParallel = (-not [string]::IsNullOrWhiteSpace($startParallelRaw)) -and ($startParallelRaw.Trim() -eq '1')
    $startCount = 0
    if (-not [string]::IsNullOrWhiteSpace($startCountRaw)) { try { $startCount = [int]$startCountRaw } catch { $startCount = 0 } }

    if ($batchConfigs -and $batchConfigs.Count -gt 0) {
        $projRootBatch = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
        $batchStamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $batchRoot = Join-Path $projRootBatch ("runs\_batch\{0}" -f $batchStamp)
        New-Item -ItemType Directory -Path $batchRoot -Force | Out-Null
        $jobsRaw = $env:BATCH_JOBS
        $maxJobs = 1
        if (-not [string]::IsNullOrWhiteSpace($jobsRaw)) { try { $maxJobs = [int]$jobsRaw } catch { $maxJobs = 1 } }
        if ($maxJobs -lt 1) { $maxJobs = 1 }

        $jobs = @()
        $batchItems = @()
        $idx = 0
        foreach ($cfg in $batchConfigs) {
            $idx += 1
            $cfgPath = (Resolve-Path $cfg).Path
            $tag = "{0:d3}_{1}" -f @($idx, ([IO.Path]::GetFileNameWithoutExtension($cfgPath)))
            $workDir = Join-Path $batchRoot $tag
            New-Item -ItemType Directory -Path $workDir -Force | Out-Null
            $batchItems += [pscustomobject]@{
                tag = $tag
                work_dir = $workDir
                config_path = $cfgPath
            }

            if ($maxJobs -gt 1) {
                while (@(Get-Job -State Running).Count -ge $maxJobs) { Wait-Job -Any | Out-Null }
                $jobs += Start-Job -ArgumentList @($PSCommandPath, $cfgPath, $workDir) -ScriptBlock {
                    param($scriptPath, $projectConfig, $runWorkDir)
                    $env:BATCH_CHILD = '1'
                    $env:PROJECT_CONFIG = $projectConfig
                    $env:RUN_WORKDIR = $runWorkDir
                    Remove-Item Env:BATCH_PROJECT_CONFIGS -ErrorAction SilentlyContinue
                    & powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath
                    if ($LASTEXITCODE -ne 0) { throw "Child run failed ($LASTEXITCODE): $projectConfig" }
                }
            }
            else {
                $env:BATCH_CHILD = '1'
                $env:PROJECT_CONFIG = $cfgPath
                $env:RUN_WORKDIR = $workDir
                Remove-Item Env:BATCH_PROJECT_CONFIGS -ErrorAction SilentlyContinue
                & powershell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath
                if ($LASTEXITCODE -ne 0) { throw "Child run failed ($LASTEXITCODE): $cfgPath" }
                Remove-Item Env:BATCH_CHILD -ErrorAction SilentlyContinue
                Remove-Item Env:PROJECT_CONFIG -ErrorAction SilentlyContinue
                Remove-Item Env:RUN_WORKDIR -ErrorAction SilentlyContinue
            }
        }

        if ($jobs -and $jobs.Count -gt 0) {
            Wait-Job -Job $jobs | Out-Null
            $failed = @()
            foreach ($j in $jobs) {
                if ($j.State -ne 'Completed') {
                    $failed += $j
                }
                Receive-Job -Job $j -Keep | Out-Null
            }
            Remove-Job -Job $jobs -Force | Out-Null

            if ($failed -and $failed.Count -gt 0) {
                Write-Error ("Batch run failed: {0} job(s). Root: {1}" -f @($failed.Count, $batchRoot))
                exit 1
            }
        }
        $summaryDir = Join-Path $batchRoot "per_project_summaries"
        New-Item -ItemType Directory -Path $summaryDir -Force | Out-Null
        $summaryIndex = @()
        foreach ($item in $batchItems) {
            $latest = Get-ChildItem -LiteralPath $item.work_dir -Recurse -Filter "compare_summary.csv" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($latest) {
                $dst = Join-Path $summaryDir ("{0}_compare_summary.csv" -f $item.tag)
                Copy-Item -LiteralPath $latest.FullName -Destination $dst -Force
                $paramsLatest = Get-ChildItem -LiteralPath $item.work_dir -Recurse -Filter "compare_params.csv" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                $summaryByLatest = Get-ChildItem -LiteralPath $item.work_dir -Recurse -Filter "compare_summary_by_species_cultivar.csv" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                $paramsByLatest = Get-ChildItem -LiteralPath $item.work_dir -Recurse -Filter "compare_params_by_species_cultivar.csv" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                $manifestLatest = Get-ChildItem -LiteralPath $item.work_dir -Recurse -Filter "run_manifest.csv" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                $paretoLatest = Get-ChildItem -LiteralPath $item.work_dir -Recurse -Filter "pareto_archive.csv" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                $robustLatest = Get-ChildItem -LiteralPath $item.work_dir -Recurse -Filter "robust_choice.csv" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                $paramsDst = $null
                $summaryByDst = $null
                $paramsByDst = $null
                $manifestDst = $null
                $paretoDst = $null
                $robustDst = $null
                if ($paramsLatest) {
                    $paramsDst = Join-Path $summaryDir ("{0}_compare_params.csv" -f $item.tag)
                    Copy-Item -LiteralPath $paramsLatest.FullName -Destination $paramsDst -Force
                }
                if ($summaryByLatest) {
                    $summaryByDst = Join-Path $summaryDir ("{0}_compare_summary_by_species_cultivar.csv" -f $item.tag)
                    Copy-Item -LiteralPath $summaryByLatest.FullName -Destination $summaryByDst -Force
                }
                if ($paramsByLatest) {
                    $paramsByDst = Join-Path $summaryDir ("{0}_compare_params_by_species_cultivar.csv" -f $item.tag)
                    Copy-Item -LiteralPath $paramsByLatest.FullName -Destination $paramsByDst -Force
                }
                if ($manifestLatest) {
                    $manifestDst = Join-Path $summaryDir ("{0}_run_manifest.csv" -f $item.tag)
                    Copy-Item -LiteralPath $manifestLatest.FullName -Destination $manifestDst -Force
                }
                if ($paretoLatest) {
                    $paretoDst = Join-Path $summaryDir ("{0}_pareto_archive.csv" -f $item.tag)
                    Copy-Item -LiteralPath $paretoLatest.FullName -Destination $paretoDst -Force
                }
                if ($robustLatest) {
                    $robustDst = Join-Path $summaryDir ("{0}_robust_choice.csv" -f $item.tag)
                    Copy-Item -LiteralPath $robustLatest.FullName -Destination $robustDst -Force
                }
                $summaryIndex += [pscustomobject]@{
                    tag = $item.tag
                    config_path = $item.config_path
                    work_dir = $item.work_dir
                    summary_path = $dst
                    params_path = $paramsDst
                    summary_by_species_cultivar_path = $summaryByDst
                    params_by_species_cultivar_path = $paramsByDst
                    run_manifest_path = $manifestDst
                    pareto_archive_path = $paretoDst
                    robust_choice_path = $robustDst
                }
            }
        }
        if ($summaryIndex -and $summaryIndex.Count -gt 0) {
            $caseRows = @()
            $indexPath = Join-Path $summaryDir "per_project_index.csv"
            $summaryIndex | Export-Csv -LiteralPath $indexPath -NoTypeInformation
            $summaryByGroup = @()
            $paramsByGroup = @()
            foreach ($s in $summaryIndex) {
                $cfgSnap = Join-Path $s.work_dir "project_snapshot\project.json"
                $cfgPath = $cfgSnap
                if (-not (Test-Path -LiteralPath $cfgPath)) { $cfgPath = $s.config_path }
                $cfgObj = Read-JsonFile $cfgPath
                $dssatDir = ""
                $filexName = ""
                if ($cfgObj -and $cfgObj.paths -and $cfgObj.paths.dssat_case_dir) { $dssatDir = [string]$cfgObj.paths.dssat_case_dir }
                if ($cfgObj -and $cfgObj.scenario -and $cfgObj.scenario.filex) { $filexName = [string]$cfgObj.scenario.filex }
                $species = ""
                if (-not [string]::IsNullOrWhiteSpace($dssatDir)) { $species = Split-Path -Leaf $dssatDir }
                $filexPath = ""
                if (-not [string]::IsNullOrWhiteSpace($filexName)) {
                    if ([IO.Path]::IsPathRooted($filexName)) {
                        $filexPath = $filexName
                    }
                    elseif (-not [string]::IsNullOrWhiteSpace($dssatDir)) {
                        $filexPath = Join-Path $dssatDir $filexName
                    }
                }
                $cultivar = Get-CultivarCode $filexPath
                if (Test-Path -LiteralPath $s.summary_path) {
                    $summaryRows = Import-Csv -LiteralPath $s.summary_path
                    foreach ($row in $summaryRows) {
                        $base = [ordered]@{
                            species = $species
                            cultivar = $cultivar
                            project_tag = $s.tag
                            config_path = $s.config_path
                            summary_path = $s.summary_path
                        }
                        foreach ($p in $row.PSObject.Properties) {
                            $base[$p.Name] = $p.Value
                        }
                        $summaryByGroup += [pscustomobject]$base
                    }
                    $pick = $summaryRows | Where-Object { $_.scenario -eq 'mgda' } | Select-Object -First 1
                    if (-not $pick) { $pick = $summaryRows | Where-Object { $_.scenario -eq 'pest' } | Select-Object -First 1 }
                    if (-not $pick) { $pick = $summaryRows | Select-Object -First 1 }
                    if ($pick) {
                        $caseRows += [pscustomobject]@{
                            project_tag = $s.tag
                            config_path = $s.config_path
                            work_dir = $s.work_dir
                            species = $species
                            cultivar = $cultivar
                            scenario = $pick.scenario
                            train_phi_w = $pick.train_phi_w
                            valid_phi_w = $pick.valid_phi_w
                            train_rmse_yield = $pick.train_rmse_yield
                            valid_rmse_yield = $pick.valid_rmse_yield
                            train_r2_yield = $pick.train_r2_yield
                            valid_r2_yield = $pick.valid_r2_yield
                            train_rmse_laix = $pick.train_rmse_laix
                            valid_rmse_laix = $pick.valid_rmse_laix
                            train_r2_laix = $pick.train_r2_laix
                            valid_r2_laix = $pick.valid_r2_laix
                            train_n_trt = $pick.train_n_trt
                            valid_n_trt = $pick.valid_n_trt
                        }
                    }
                }
                $paramsLatest = $null
                if ($s.params_path -and (Test-Path -LiteralPath $s.params_path)) {
                    $paramsLatest = $s.params_path
                }
                else {
                    $paramsLatest = (Get-ChildItem -LiteralPath $s.work_dir -Recurse -Filter "compare_params.csv" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
                }
                if ($paramsLatest -and (Test-Path -LiteralPath $paramsLatest)) {
                    foreach ($row in (Import-Csv -LiteralPath $paramsLatest)) {
                        $base = [ordered]@{
                            species = $species
                            cultivar = $cultivar
                            project_tag = $s.tag
                            config_path = $s.config_path
                            params_path = $paramsLatest
                        }
                        foreach ($p in $row.PSObject.Properties) {
                            $base[$p.Name] = $p.Value
                        }
                        $paramsByGroup += [pscustomobject]$base
                    }
                }
            }
            if ($summaryByGroup -and $summaryByGroup.Count -gt 0) {
                $groupPath = Join-Path $summaryDir "compare_summary_by_species_cultivar.csv"
                $summaryByGroup | Export-Csv -LiteralPath $groupPath -NoTypeInformation
            }
            if ($paramsByGroup -and $paramsByGroup.Count -gt 0) {
                $groupPath = Join-Path $summaryDir "compare_params_by_species_cultivar.csv"
                $paramsByGroup | Export-Csv -LiteralPath $groupPath -NoTypeInformation
            }
            if ($caseRows -and $caseRows.Count -gt 0) {
                $casesPath = Join-Path $summaryDir "cases_summary.csv"
                $caseRows | Export-Csv -LiteralPath $casesPath -NoTypeInformation

                function Get-Quantile {
                    param([double[]]$Values, [double]$Q)
                    $vals = $Values | Where-Object { $_ -eq $_ } | Sort-Object
                    if (-not $vals -or $vals.Count -lt 1) { return [double]::NaN }
                    if ($vals.Count -eq 1) { return [double]$vals[0] }
                    $pos = ($vals.Count - 1) * $Q
                    $lo = [math]::Floor($pos)
                    $hi = [math]::Ceiling($pos)
                    if ($lo -eq $hi) { return [double]$vals[$lo] }
                    $w = $pos - $lo
                    return [double]($vals[$lo] * (1.0 - $w) + $vals[$hi] * $w)
                }

                $metrics = @('train_phi_w','valid_phi_w','train_rmse_yield','valid_rmse_yield','train_r2_yield','valid_r2_yield','train_rmse_laix','valid_rmse_laix','train_r2_laix','valid_r2_laix')
                $overallRows = @()
                foreach ($m in $metrics) {
                    $vals = @()
                    foreach ($r in $caseRows) {
                        $v = $r.$m
                        if ($null -ne $v -and $v -ne '') { $vals += [double]$v }
                    }
                    if ($vals.Count -gt 0) {
                        $q1 = Get-Quantile -Values $vals -Q 0.25
                        $q2 = Get-Quantile -Values $vals -Q 0.50
                        $q3 = Get-Quantile -Values $vals -Q 0.75
                        $overallRows += [pscustomobject]@{
                            metric = $m
                            n = $vals.Count
                            median = $q2
                            q1 = $q1
                            q3 = $q3
                            iqr = ($q3 - $q1)
                        }
                    }
                }
                if ($overallRows.Count -gt 0) {
                    $overallPath = Join-Path $summaryDir "overall_summary.csv"
                    $overallRows | Export-Csv -LiteralPath $overallPath -NoTypeInformation
                }
            }
        }
        Write-Host ("Batch run done. Root: {0}" -f $batchRoot) -ForegroundColor Green
        exit 0
    }

    if ($startParallel -and (-not [string]::IsNullOrWhiteSpace($startMode)) -and ($startMode.Trim().ToLower() -eq 'lhs') -and ($startCount -gt 1)) {
        $projRootBatch = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
        $batchStamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $batchRoot = Join-Path $projRootBatch ("runs\_multistart\{0}" -f $batchStamp)
        New-Item -ItemType Directory -Path $batchRoot -Force | Out-Null
        $jobsRaw = $env:BATCH_JOBS
        $maxJobs = 1
        if (-not [string]::IsNullOrWhiteSpace($jobsRaw)) { try { $maxJobs = [int]$jobsRaw } catch { $maxJobs = 1 } }
        if ($maxJobs -lt 1) { $maxJobs = 1 }

        $jobs = @()
        for ($i = 0; $i -lt $startCount; $i++) {
            $tag = "start_{0:d3}" -f $i
            $workDir = Join-Path $batchRoot $tag
            New-Item -ItemType Directory -Path $workDir -Force | Out-Null

            while (@(Get-Job -State Running).Count -ge $maxJobs) { Wait-Job -Any | Out-Null }

            $jobs += Start-Job -ArgumentList @($PSCommandPath, $workDir, $i, $startCount) -ScriptBlock {
                param($scriptPath, $runWorkDir, $startIndex, $count)
                $env:BATCH_CHILD = '1'
                $env:RUN_WORKDIR = $runWorkDir
                $env:MGDA_START_MODE = 'lhs'
                $env:MGDA_START_COUNT = [string]$count
                $env:MGDA_START_INDEX = [string]$startIndex
                Remove-Item Env:BATCH_PROJECT_CONFIGS -ErrorAction SilentlyContinue
                & powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath
                if ($LASTEXITCODE -ne 0) { throw "Child run failed ($LASTEXITCODE): start_index=$startIndex" }
            }
        }

        Wait-Job -Job $jobs | Out-Null
        $failed = @()
        foreach ($j in $jobs) {
            if ($j.State -ne 'Completed') {
                $failed += $j
            }
            Receive-Job -Job $j -Keep | Out-Null
        }
        Remove-Job -Job $jobs -Force | Out-Null

        if ($failed -and $failed.Count -gt 0) {
            Write-Error ("Parallel multistart failed: {0} job(s). Root: {1}" -f @($failed.Count, $batchRoot))
            exit 1
        }
        Write-Host ("Parallel multistart done. Root: {0}" -f $batchRoot) -ForegroundColor Green
        exit 0
    }
}

try {

$runStart = Get-Date
$runStatus = 'success'
$skipRun = $false
$runError = ''
$runErrorCode = ''
$runErrorLog = ''
$runStage = 'init'
$stageStatus = @{}
$stageHistory = @()
$stageLogMap = @{}
$iterStatusMap = @{}
$iterHistory = @()
$iterMax = 1
$currentIter = 0
$resumeMode = $false

function Wait-ForAnyFile {
    param(
        [Parameter(Mandatory=$true)][string]$Dir,
        [Parameter(Mandatory=$true)][string]$Filter,
        [int]$TimeoutSeconds = 20
    )
    $deadline = (Get-Date).AddSeconds([double]$TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $files = Get-ChildItem -LiteralPath $Dir -Filter $Filter -File -ErrorAction SilentlyContinue
        if ($files -and $files.Count -gt 0) { return $true }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
    }
    catch {
        return $null
    }
}

$projRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$runsRoot = Join-Path $projRoot "runs\_runs"
$resumeDir = $env:RUN_WORKDIR
if ([string]::IsNullOrWhiteSpace($resumeDir)) { $resumeDir = $env:RESUME_RUN_DIR }
if (-not [string]::IsNullOrWhiteSpace($resumeDir) -and (Test-Path -LiteralPath $resumeDir)) {
    $rootWorkDir = (Resolve-Path $resumeDir).Path
    $stamp = Split-Path -Leaf $rootWorkDir
    $resumeMode = $true
}
else {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $rootWorkDir = Join-Path $runsRoot $stamp
    New-Item -ItemType Directory -Path $runsRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $rootWorkDir -Force | Out-Null
}

$projectSnapshotDir = Join-Path $rootWorkDir "project_snapshot"
New-Item -ItemType Directory -Path $projectSnapshotDir -Force | Out-Null
$cfgPath = $env:PROJECT_CONFIG
if ([string]::IsNullOrWhiteSpace($cfgPath)) { $cfgPath = (Join-Path $projRoot "config\project.json") }
$cfgHash = $null
$cfg = Read-JsonFile $cfgPath
$dssatExe = $null
$splitSeed = $null
$splitMode = $null
if ($cfg -and $cfg.paths) { $dssatExe = $cfg.paths.dssat_exe }
if ($cfg -and $cfg.split) {
    $splitSeed = $cfg.split.seed
    $splitMode = $cfg.split.mode
}
if (Test-Path -LiteralPath $cfgPath) {
    $snapPath = Join-Path $projectSnapshotDir "project.json"
    if (-not (Test-Path -LiteralPath $snapPath) -or (-not $resumeMode)) {
        Copy-Item -LiteralPath $cfgPath -Destination $snapPath -Force
    }
    $cfgHash = (Get-FileHash -LiteralPath $snapPath -Algorithm SHA256).Hash
}

Remove-Item Env:DSSAT_TRTS -ErrorAction SilentlyContinue
Remove-Item Env:PARAMS_PATH -ErrorAction SilentlyContinue
Remove-Item Env:MGDA_PARAMS_PATH -ErrorAction SilentlyContinue
$cfgPestMode = ''
if ($cfg -and $cfg.pest_mode) { $cfgPestMode = [string]$cfg.pest_mode }
$estNopt = $env:PEST_NOPTMAX_EST
$sensNopt = $env:PEST_NOPTMAX_SENS
if ([string]::IsNullOrWhiteSpace($estNopt)) {
    if (-not [string]::IsNullOrWhiteSpace($cfgPestMode)) {
        $mode = $cfgPestMode.Trim().ToLower()
        if ($mode -eq 'estimation') { $estNopt = '5' }
        elseif ($mode -eq 'sensitivity') { $estNopt = if ([string]::IsNullOrWhiteSpace($sensNopt)) { '-1' } else { $sensNopt } }
        else { $estNopt = '-1' }
    }
    else {
        $estNopt = '-1'
    }
}
Remove-Item Env:PEST_NOPTMAX -ErrorAction SilentlyContinue

function Parse-IntList {
    param([string]$Value)
    $out = @()
    foreach ($tok in ($Value -split '[,;\s]+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $out += [int]$tok
    }
    return $out
}

function Read-KvFile {
    param([string]$Path)
    $kv = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $kv }
    foreach ($line in (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
        $s = ($line | ForEach-Object { $_.Trim() })
        if ([string]::IsNullOrWhiteSpace($s)) { continue }
        if ($s.StartsWith('#')) { continue }
        $parts = $s -split '=', 2
        if ($parts.Count -ne 2) { continue }
        $k = $parts[0].Trim()
        $v = $parts[1].Trim()
        if (-not [string]::IsNullOrWhiteSpace($k)) { $kv[$k] = $v }
    }
    return $kv
}

function Read-ParParams {
    param([string]$Path)
    $kv = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $kv }
    foreach ($line in (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
        $s = ($line | ForEach-Object { $_.Trim() })
        if ([string]::IsNullOrWhiteSpace($s)) { continue }
        if ($s.StartsWith('*')) { continue }
        $parts = $s -split '\s+'
        if ($parts.Count -lt 2) { continue }
        $k = $parts[0].Trim().ToLower()
        try {
            $kv[$k] = [double]$parts[1]
        }
        catch {
            continue
        }
    }
    return $kv
}

function Write-ParamsDat {
    param([string]$Path, [hashtable]$Params)
    $keys = $Params.Keys | Sort-Object
    $lines = @()
    foreach ($k in $keys) {
        $lines += ("{0} {1}" -f @($k, [double]$Params[$k]))
    }
    $lines += ""
    Set-Content -LiteralPath $Path -Value $lines -Encoding utf8
}

function Read-RunMeta {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
    }
    catch {
        return $null
    }
}

function script:Get-ErrorCode {
    param([string]$Stage)
    $baseStage = $Stage
    if ($Stage -match "^iter_\d+[:/](.+)$") { $baseStage = $Matches[1] }
    switch ($baseStage) {
        'render_inputs' { return 'E_RENDER_INPUTS' }
        'run_dssat' { return 'E_RUN_DSSAT' }
        'run_pestpp' { return 'E_PESTPP' }
        'mgda_update' { return 'E_MGDA_UPDATE' }
        'evaluate' { return 'E_EVALUATE' }
        'archive' { return 'E_ARCHIVE' }
        default { return 'E_UNKNOWN' }
    }
}

function Write-RunMeta {
    if (-not $rootWorkDir) { return }
    $metaPath = Join-Path $rootWorkDir "meta.json"
    $meta = [pscustomobject]@{
        stamp = $stamp
        run_start = $runStart.ToString("s")
        run_end = if ($runEnd) { $runEnd.ToString("s") } else { $null }
        run_status = $runStatus
        error_stage = $runStage
        error_code = $runErrorCode
        error_message = $runError
        error_log = $runErrorLog
        project_root = $projRoot
        root_workdir = $rootWorkDir
        nopt_list = $noptList
        iter_max = $iterMax
        current_iter = $currentIter
        resume_mode = $resumeMode
        project_snapshot = $projectSnapshotDir
        config_hash_sha256 = $cfgHash
        config_path = $cfgPath
        dssat_exe = $dssatExe
        pestpp_glm = $pestppGlm
        python_version = if ($pyInfo) { $pyInfo.python } else { $null }
        pyemu_version = if ($pyInfo) { $pyInfo.pyemu } else { $null }
        numpy_version = if ($pyInfo) { $pyInfo.numpy } else { $null }
        split_mode = $splitMode
        split_seed = $splitSeed
        stage_status = $stageStatus
        stage_history = $stageHistory
        iter_status_map = $iterStatusMap
        iter_history = $iterHistory
    }
    $meta | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metaPath
}

function Set-Stage {
    param([string]$Stage, [string]$Status)
    $script:runStage = $Stage
    $stageStatus[$Stage] = $Status
    $stageHistory += [pscustomobject]@{
        stage = $Stage
        status = $Status
        time = (Get-Date).ToString("s")
    }
    Write-RunMeta
}

function Get-IterKey {
    param([int]$Iter)
    return ("iter_{0:d3}" -f $Iter)
}

function Write-IterMeta {
    param([string]$IterDir, [string]$IterKey)
    if (-not $IterDir) { return }
    $metaPath = Join-Path $IterDir "meta.json"
    $stageMap = $iterStatusMap[$IterKey]
    $hist = $iterHistory | Where-Object { $_.iter -eq $IterKey }
    $meta = [pscustomobject]@{
        iter = $IterKey
        run_stamp = $stamp
        stage_status = $stageMap
        stage_history = $hist
    }
    $meta | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metaPath
}

function Set-IterStage {
    param([int]$Iter, [string]$Stage, [string]$Status, [string]$IterDir)
    $iterKey = Get-IterKey $Iter
    if (-not $iterStatusMap.ContainsKey($iterKey)) { $iterStatusMap[$iterKey] = @{} }
    $iterStatusMap[$iterKey][$Stage] = $Status
    $iterHistory += [pscustomobject]@{
        iter = $IterKey
        stage = $Stage
        status = $Status
        time = (Get-Date).ToString("s")
    }
    $script:runStage = "${iterKey}:$Stage"
    Write-IterMeta -IterDir $IterDir -IterKey $iterKey
    Write-RunMeta
}

function Get-PythonInfo {
    $code = "import json,sys`ntry:`n import pyemu, numpy`n pyemu_v = getattr(pyemu,'__version__', None)`n numpy_v = getattr(numpy,'__version__', None)`nexcept Exception:`n pyemu_v = None`n numpy_v = None`nprint(json.dumps({'python':sys.version.split()[0],'pyemu':pyemu_v,'numpy':numpy_v}))"
    $json = & python -W ignore -c $code 2>$null
    if ([string]::IsNullOrWhiteSpace($json)) { return $null }
    try { return ($json | ConvertFrom-Json) } catch { return $null }
}

function Get-DoubleField {
    param([psobject]$Obj, [string]$Name)
    if ($null -eq $Obj) { return [double]::NaN }
    $prop = $Obj.PSObject.Properties[$Name]
    if ($null -eq $prop) { return [double]::NaN }
    $val = $prop.Value
    $valStr = [string]$val
    if ([string]::IsNullOrWhiteSpace($valStr)) { return [double]::NaN }
    if ($valStr.Trim().ToLower() -in @('nan', 'na', 'null')) { return [double]::NaN }
    try { return [double]$valStr } catch { return [double]::NaN }
}

function Get-IntField {
    param([psobject]$Obj, [string]$Name)
    if ($null -eq $Obj) { return 0 }
    $prop = $Obj.PSObject.Properties[$Name]
    if ($null -eq $prop) { return 0 }
    $val = $prop.Value
    if ($null -eq $val -or [string]::IsNullOrWhiteSpace([string]$val)) { return 0 }
    return [int]$val
}

function Invoke-LoggedJob {
    param(
        [Parameter(Mandatory=$true)][scriptblock]$ScriptBlock,
        [Parameter(Mandatory=$true)][object[]]$ArgumentList,
        [Parameter(Mandatory=$true)][string]$LogPath,
        [Parameter(Mandatory=$true)][string]$StageLabel,
        [int]$IntervalSeconds = 10
    )
    $job = Start-Job -ArgumentList $ArgumentList -ScriptBlock $ScriptBlock
    $start = Get-Date
    while ($true) {
        $job = Get-Job -Id $job.Id -ErrorAction SilentlyContinue
        if (-not $job) { break }
        if ($job.State -ne 'Running') { break }
        Start-Sleep -Seconds $IntervalSeconds
        $lastLine = ""
        if (Test-Path -LiteralPath $LogPath) {
            try { $lastLine = (Get-Content -LiteralPath $LogPath -Tail 1 -ErrorAction SilentlyContinue) } catch { $lastLine = "" }
        }
        if ([string]::IsNullOrWhiteSpace($lastLine)) { $lastLine = "(no log output)" }
        $elapsed = [int]((Get-Date) - $start).TotalSeconds
        Write-Host ("[{0}] {1} running... elapsed={2}s last_log={3}" -f @((Get-Date).ToString("HH:mm:ss"), $StageLabel, $elapsed, $lastLine))
    }
    $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    if ($output -and $output.Count -gt 0) { return [int]$output[-1] }
    return 0
}

$ablListRaw = $env:PEST_NOPTMAX_ABLATION
$noptList = @()
if ([string]::IsNullOrWhiteSpace($ablListRaw)) {
    $noptList = @([int]$estNopt)
}
else {
    $noptList = Parse-IntList $ablListRaw
}

$ablRows = @()
$pestppGlm = $null
$pyInfo = Get-PythonInfo
if ($env:MGDA_IMPROVE_EPS) {
    $improveEps = [double]$env:MGDA_IMPROVE_EPS
}
else {
    $improveEps = [double]'1e-6'
}
if ($env:MGDA_IMPROVE_STREAK) {
    $improveStreakN = [int]$env:MGDA_IMPROVE_STREAK
}
else {
    $improveStreakN = 3
}
$earlyStopRaw = $env:MGDA_EARLY_STOP
$allowEarlyStop = $true
if (-not [string]::IsNullOrWhiteSpace($earlyStopRaw)) {
    $earlyStopNorm = $earlyStopRaw.Trim().ToLower()
    if ($earlyStopNorm -in @('0', 'false', 'no')) { $allowEarlyStop = $false }
}
$prevPhiW = [double]::NaN
$noImproveStreak = 0
$metaResume = Read-RunMeta (Join-Path $rootWorkDir "meta.json")
if ($metaResume) {
    if ($metaResume.run_start) {
        try { $runStart = Get-Date $metaResume.run_start } catch { }
    }
    if ($metaResume.stage_status) {
        $stageStatus = @{}
        foreach ($p in $metaResume.stage_status.PSObject.Properties) { $stageStatus[$p.Name] = $p.Value }
    }
    if ($metaResume.stage_history) {
        $stageHistory = @()
        foreach ($h in $metaResume.stage_history) { $stageHistory += $h }
    }
    if ($metaResume.iter_status_map) {
        $iterStatusMap = @{}
        foreach ($p in $metaResume.iter_status_map.PSObject.Properties) {
            $iterStatusMap[$p.Name] = @{}
            foreach ($sp in $p.Value.PSObject.Properties) { $iterStatusMap[$p.Name][$sp.Name] = $sp.Value }
        }
    }
    if ($metaResume.iter_history) {
        $iterHistory = @()
        foreach ($h in $metaResume.iter_history) { $iterHistory += $h }
    }
}
$env:DSSAT_ALLOW_MISSING_WHT_DATES = "1"
$iterMaxRaw = $env:MGDA_MAX_ITER
if ([string]::IsNullOrWhiteSpace($iterMaxRaw)) { $iterMaxRaw = '15' }
$iterMax = [int]$iterMaxRaw

:RunMain foreach ($nopt in $noptList) {
    $workDir = if ($noptList.Count -gt 1) { (Join-Path $rootWorkDir ("noptmax_{0}" -f $nopt)) } else { $rootWorkDir }
    New-Item -ItemType Directory -Path $workDir -Force | Out-Null
    Set-Location $workDir
    $paretoDir = Join-Path $workDir "pareto_archive"
    New-Item -ItemType Directory -Path $paretoDir -Force | Out-Null
    $paretoRows = @()
    $stopIter = $null
    $mgdaGateMode = $env:MGDA_GATE_MODE
    if ([string]::IsNullOrWhiteSpace($mgdaGateMode)) { $mgdaGateMode = 'pest_streak' }
    $mgdaGateMode = $mgdaGateMode.Trim().ToLower()
    $pestImproveEpsRaw = $env:MGDA_PEST_IMPROVE_EPS
    if ([string]::IsNullOrWhiteSpace($pestImproveEpsRaw)) { $pestImproveEpsRaw = '0.05' }
    $pestImproveEps = [double]$pestImproveEpsRaw
    $pestImproveStreakRaw = $env:MGDA_PEST_IMPROVE_STREAK
    if ([string]::IsNullOrWhiteSpace($pestImproveStreakRaw)) { $pestImproveStreakRaw = '3' }
    $pestImproveStreakN = [int]$pestImproveStreakRaw
    $pestPrevPhiW = [double]::NaN
    $pestNoImproveStreak = 0
    $mgdaGateOpen = ($mgdaGateMode -eq 'off')
    $mgdaEverRan = $false
    $mgdaOnlyRoundsRaw = $env:MGDA_ONLY_ROUNDS
    if ([string]::IsNullOrWhiteSpace($mgdaOnlyRoundsRaw)) { $mgdaOnlyRoundsRaw = '2' }
    $mgdaOnlyRounds = [int]$mgdaOnlyRoundsRaw
    $mgdaOnlyRemaining = 0
    $mgdaAdaptRaw = $env:MGDA_ADAPT_PARAMS
    $mgdaAdapt = $true
    if (-not [string]::IsNullOrWhiteSpace($mgdaAdaptRaw)) {
        $mgdaAdaptNorm = $mgdaAdaptRaw.Trim().ToLower()
        if ($mgdaAdaptNorm -in @('0', 'false', 'no')) { $mgdaAdapt = $false }
    }
    $cfgMgda = $null
    if ($cfg -and $cfg.optimization -and $cfg.optimization.mgda) { $cfgMgda = $cfg.optimization.mgda }
    $trustRelBaseRaw = $env:MGDA_TRUST_REL_BASE
    if ([string]::IsNullOrWhiteSpace($trustRelBaseRaw)) {
        if ($cfgMgda -and $cfgMgda.trust_rel) { $trustRelBaseRaw = [string]$cfgMgda.trust_rel } else { $trustRelBaseRaw = '0.1' }
    }
    $regLambdaBaseRaw = $env:MGDA_REG_LAMBDA_BASE
    if ([string]::IsNullOrWhiteSpace($regLambdaBaseRaw)) {
        if ($cfgMgda -and $cfgMgda.reg_lambda) { $regLambdaBaseRaw = [string]$cfgMgda.reg_lambda } else { $regLambdaBaseRaw = '0.0' }
    }
    $mgdaTrustRel = [double]$trustRelBaseRaw
    $mgdaRegLambda = [double]$regLambdaBaseRaw
    $trustRelMinRaw = $env:MGDA_TRUST_REL_MIN
    if ([string]::IsNullOrWhiteSpace($trustRelMinRaw)) { $trustRelMinRaw = '0.02' }
    $trustRelMaxRaw = $env:MGDA_TRUST_REL_MAX
    if ([string]::IsNullOrWhiteSpace($trustRelMaxRaw)) { $trustRelMaxRaw = '0.5' }
    $trustRelUpRaw = $env:MGDA_TRUST_REL_UP
    if ([string]::IsNullOrWhiteSpace($trustRelUpRaw)) { $trustRelUpRaw = '1.25' }
    $trustRelDownRaw = $env:MGDA_TRUST_REL_DOWN
    if ([string]::IsNullOrWhiteSpace($trustRelDownRaw)) { $trustRelDownRaw = '0.7' }
    $regLambdaMinRaw = $env:MGDA_REG_LAMBDA_MIN
    if ([string]::IsNullOrWhiteSpace($regLambdaMinRaw)) { $regLambdaMinRaw = '0.0' }
    $regLambdaMaxRaw = $env:MGDA_REG_LAMBDA_MAX
    if ([string]::IsNullOrWhiteSpace($regLambdaMaxRaw)) { $regLambdaMaxRaw = '0.2' }
    $regLambdaUpRaw = $env:MGDA_REG_LAMBDA_UP
    if ([string]::IsNullOrWhiteSpace($regLambdaUpRaw)) { $regLambdaUpRaw = '1.3' }
    $regLambdaDownRaw = $env:MGDA_REG_LAMBDA_DOWN
    if ([string]::IsNullOrWhiteSpace($regLambdaDownRaw)) { $regLambdaDownRaw = '0.8' }
    $trustRelMin = [double]$trustRelMinRaw
    $trustRelMax = [double]$trustRelMaxRaw
    $trustRelUp = [double]$trustRelUpRaw
    $trustRelDown = [double]$trustRelDownRaw
    $regLambdaMin = [double]$regLambdaMinRaw
    $regLambdaMax = [double]$regLambdaMaxRaw
    $regLambdaUp = [double]$regLambdaUpRaw
    $regLambdaDown = [double]$regLambdaDownRaw

    for ($iter = 0; $iter -lt $iterMax; $iter++) {
        $currentIter = $iter
        $iterKey = Get-IterKey $iter
        $iterDir = Join-Path $workDir $iterKey
        $iterParamsDir = Join-Path $iterDir "params"
        $iterDssatDir = Join-Path $iterDir "dssat"
        $iterPestDir = Join-Path $iterDir "pest"
        $iterMgdaDir = Join-Path $iterDir "mgda"
        $iterEvalDir = Join-Path $iterDir "eval"
        $mgdaRanThisIter = $false
        $mgdaOnlyActive = ($mgdaOnlyRemaining -gt 0)
        New-Item -ItemType Directory -Path $iterDir -Force | Out-Null
        New-Item -ItemType Directory -Path $iterParamsDir -Force | Out-Null
        New-Item -ItemType Directory -Path $iterDssatDir -Force | Out-Null
        New-Item -ItemType Directory -Path $iterPestDir -Force | Out-Null
        New-Item -ItemType Directory -Path $iterMgdaDir -Force | Out-Null
        New-Item -ItemType Directory -Path $iterEvalDir -Force | Out-Null

        $paramsDat = Join-Path $iterDir "params.dat"
        if (-not (Test-Path -LiteralPath $paramsDat) -and $iter -gt 0) {
            $prevIterKey = Get-IterKey ($iter - 1)
            $prevIterDir = Join-Path $workDir $prevIterKey
            $prevParams = Join-Path $prevIterDir "params_next.dat"
            if (-not (Test-Path -LiteralPath $prevParams)) { $prevParams = Join-Path $prevIterDir "params_mgda.dat" }
            if (Test-Path -LiteralPath $prevParams) {
                Copy-Item -LiteralPath $prevParams -Destination $paramsDat -Force
            }
        }

        Set-Location $iterDir

        $iterStageMap = $null
        if ($iterStatusMap.ContainsKey($iterKey)) { $iterStageMap = $iterStatusMap[$iterKey] }

        if (-not ($iterStageMap -and $iterStageMap.ContainsKey('render_inputs') -and $iterStageMap['render_inputs'] -eq 'done')) {
            Write-Host ("[NOPTMAX={0}] [{1}/{2}] [1/5] Build PEST setup" -f @($nopt, ($iter + 1), $iterMax)) -ForegroundColor Cyan
            Set-IterStage -Iter $iter -Stage 'render_inputs' -Status 'start' -IterDir $iterDir
            $env:PEST_NOPTMAX = [string]$nopt
            $buildLog = (Join-Path $iterDir "build_pest_setup.log")
            $stageLogMap["$iterKey:render_inputs"] = $buildLog
            $exitCode = Invoke-LoggedJob -ScriptBlock {
                param($workDir, $projRootPath, $logPath)
                Set-Location $workDir
                $ErrorActionPreference = 'Continue'
                python (Join-Path $projRootPath "src\pest_builder.py") run --work-dir $workDir 2>&1 | Out-File -LiteralPath $logPath -Encoding utf8
                return $LASTEXITCODE
            } -ArgumentList @($iterDir, $projRoot, $buildLog) -LogPath $buildLog -StageLabel "Build PEST setup"
            if ($exitCode -ne 0) {
                $raw = ''
                try { $raw = Get-Content -LiteralPath $buildLog -Raw -ErrorAction SilentlyContinue } catch { $raw = '' }
                if ($raw -match 'No usable observations') {
                    $skipRun = $true
                    Set-IterStage -Iter $iter -Stage 'render_inputs' -Status 'skipped' -IterDir $iterDir
                    Set-IterStage -Iter $iter -Stage 'run_pestpp' -Status 'skipped' -IterDir $iterDir
                    Set-IterStage -Iter $iter -Stage 'mgda_update' -Status 'skipped' -IterDir $iterDir
                    Set-IterStage -Iter $iter -Stage 'evaluate' -Status 'skipped' -IterDir $iterDir
                    Set-IterStage -Iter $iter -Stage 'archive' -Status 'skipped' -IterDir $iterDir
                    $runStatus = 'skipped'
                    break RunMain
                }
                throw "pest_builder.py run failed (exit $exitCode)"
            }
            if (Test-Path -LiteralPath (Join-Path $iterDir "params.dat")) {
                Copy-Item -LiteralPath (Join-Path $iterDir "params.dat") -Destination (Join-Path $iterParamsDir "params.dat") -Force
            }
            if (Test-Path -LiteralPath (Join-Path $iterDir "params.tpl")) {
                Copy-Item -LiteralPath (Join-Path $iterDir "params.tpl") -Destination (Join-Path $iterParamsDir "params.tpl") -Force
            }
            Set-IterStage -Iter $iter -Stage 'render_inputs' -Status 'done' -IterDir $iterDir
        }

        if (-not ($iterStageMap -and $iterStageMap.ContainsKey('run_pestpp') -and $iterStageMap['run_pestpp'] -eq 'done')) {
            $doPestpp = $true
            if ($mgdaOnlyActive -and $iter -gt 0) {
                Write-Host ("[NOPTMAX={0}] [{1}/{2}] [2/5] MGDA-only: reuse previous JCO/REI" -f @($nopt, ($iter + 1), $iterMax)) -ForegroundColor Yellow
                Set-IterStage -Iter $iter -Stage 'run_pestpp' -Status 'start' -IterDir $iterDir
                $prevIterKey = Get-IterKey ($iter - 1)
                $prevIterDir = Join-Path $workDir $prevIterKey
                $prevJac = $null
                $prevJco = Join-Path $prevIterDir "ksas_mvp.jco"
                $prevJcb = Join-Path $prevIterDir "ksas_mvp.jcb"
                if (Test-Path -LiteralPath $prevJco) { $prevJac = $prevJco }
                elseif (Test-Path -LiteralPath $prevJcb) { $prevJac = $prevJcb }
                $prevRei = $null
                $prevReiCandidates = Get-ChildItem -LiteralPath $prevIterDir -Filter "ksas_mvp*.rei*" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
                if ($prevReiCandidates -and $prevReiCandidates.Count -gt 0) { $prevRei = $prevReiCandidates[0].FullName }
                if ($prevJac -and $prevRei) {
                    Copy-Item -LiteralPath (Join-Path $prevIterDir "ksas_mvp.pst") -Destination (Join-Path $iterDir "ksas_mvp.pst") -Force -ErrorAction SilentlyContinue
                    Copy-Item -LiteralPath $prevJac -Destination (Join-Path $iterDir (Split-Path -Leaf $prevJac)) -Force -ErrorAction SilentlyContinue
                    Copy-Item -LiteralPath $prevRei -Destination (Join-Path $iterDir (Split-Path -Leaf $prevRei)) -Force -ErrorAction SilentlyContinue
                    Copy-Item -LiteralPath (Join-Path $iterDir "ksas_mvp.pst") -Destination (Join-Path $iterPestDir "ksas_mvp.pst") -Force -ErrorAction SilentlyContinue
                    if (Test-Path -LiteralPath (Join-Path $iterDir "ksas_mvp.jco")) {
                        Copy-Item -LiteralPath (Join-Path $iterDir "ksas_mvp.jco") -Destination (Join-Path $iterPestDir "ksas_mvp.jco") -Force -ErrorAction SilentlyContinue
                    }
                    if (Test-Path -LiteralPath (Join-Path $iterDir "ksas_mvp.jcb")) {
                        Copy-Item -LiteralPath (Join-Path $iterDir "ksas_mvp.jcb") -Destination (Join-Path $iterPestDir "ksas_mvp.jcb") -Force -ErrorAction SilentlyContinue
                    }
                    Copy-Item -LiteralPath $prevRei -Destination (Join-Path $iterPestDir (Split-Path -Leaf $prevRei)) -Force -ErrorAction SilentlyContinue
                    $doPestpp = $false
                    Set-IterStage -Iter $iter -Stage 'run_pestpp' -Status 'done' -IterDir $iterDir
                }
                else {
                    $doPestpp = $true
                }
            }
            if ($doPestpp) {
                Write-Host ("[NOPTMAX={0}] [{1}/{2}] [2/5] Run PEST++ GLM (JCO/REI)" -f @($nopt, ($iter + 1), $iterMax)) -ForegroundColor Cyan
                Set-IterStage -Iter $iter -Stage 'run_pestpp' -Status 'start' -IterDir $iterDir
                $glmExe = $env:PESTPP_GLM
                if ([string]::IsNullOrWhiteSpace($glmExe)) {
                    $candidates = @(
                        (Join-Path $projRoot "pestpp-glm.exe"),
                        (Join-Path $projRoot "bin\pestpp-glm.exe"),
                        (Join-Path $projRoot "vendor\pestpp_5.2.16_iwin\bin\pestpp-glm.exe")
                    )
                    foreach ($c in $candidates) {
                        if (Test-Path -LiteralPath $c) {
                            $glmExe = $c
                            break
                        }
                    }
                }
                if (-not (Test-Path -LiteralPath $glmExe)) {
                    throw "pestpp-glm.exe not found. Set PESTPP_GLM or put pestpp-glm.exe in $projRoot."
                }
                $pestppGlm = $glmExe
                $glmLog = (Join-Path $iterDir "glm_console_est.log")
                $glmErrLog = (Join-Path $iterDir "glm_console_est.err.log")
                $stageLogMap["$iterKey:run_pestpp"] = $glmLog
                $exitCode = Invoke-LoggedJob -ScriptBlock {
                    param($workDir, $exePath, $logPath, $errPath)
                    Set-Location $workDir
                    & $exePath "ksas_mvp.pst" 1> $logPath 2> $errPath
                    return $LASTEXITCODE
                } -ArgumentList @($iterDir, $glmExe, $glmLog, $glmErrLog) -LogPath $glmLog -StageLabel "Run PEST++ GLM"
                if ($exitCode -ne 0) { throw "pestpp-glm.exe failed (exit $exitCode)" }
                if ((Test-Path -LiteralPath $glmErrLog) -and ((Get-Item -LiteralPath $glmErrLog).Length -gt 0)) {
                    Add-Content -LiteralPath $glmLog -Value "`n--- STDERR (appended) ---`n"
                    Get-Content -LiteralPath $glmErrLog | Add-Content -LiteralPath $glmLog
                }

                if (-not (Test-Path -LiteralPath (Join-Path $iterDir "ksas_mvp.par"))) {
                    throw "PEST parameter file missing (ksas_mvp.par)"
                }
                Copy-Item -LiteralPath (Join-Path $iterDir "ksas_mvp.par") -Destination (Join-Path $iterDir "ksas_mvp_est.par") -Force

                $null = Wait-ForAnyFile -Dir $iterDir -Filter "ksas_mvp.jc*" -TimeoutSeconds 300
                $hasJac = (Test-Path -LiteralPath (Join-Path $iterDir "ksas_mvp.jco")) -or (Test-Path -LiteralPath (Join-Path $iterDir "ksas_mvp.jcb"))
                if (-not $hasJac) { throw "Jacobian missing (ksas_mvp.jco/.jcb)" }
                $null = Wait-ForAnyFile -Dir $iterDir -Filter "ksas_mvp*.rei*" -TimeoutSeconds 300
                $reiCandidates = Get-ChildItem -LiteralPath $iterDir -Filter "ksas_mvp*.rei*" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
                if (($null -eq $reiCandidates) -or ($reiCandidates.Count -lt 1)) { throw "Residual file missing (ksas_mvp*.rei*)" }
                Copy-Item -LiteralPath (Join-Path $iterDir "ksas_mvp.pst") -Destination (Join-Path $iterPestDir "ksas_mvp.pst") -Force -ErrorAction SilentlyContinue
                Copy-Item -LiteralPath (Join-Path $iterDir "ksas_mvp.jco") -Destination (Join-Path $iterPestDir "ksas_mvp.jco") -Force -ErrorAction SilentlyContinue
                Copy-Item -LiteralPath (Join-Path $iterDir "ksas_mvp.jcb") -Destination (Join-Path $iterPestDir "ksas_mvp.jcb") -Force -ErrorAction SilentlyContinue
                Copy-Item -LiteralPath (Join-Path $iterDir "ksas_mvp.rei") -Destination (Join-Path $iterPestDir "ksas_mvp.rei") -Force -ErrorAction SilentlyContinue
                Set-IterStage -Iter $iter -Stage 'run_pestpp' -Status 'done' -IterDir $iterDir
            }
        }

        if (-not ($iterStageMap -and $iterStageMap.ContainsKey('mgda_update') -and $iterStageMap['mgda_update'] -eq 'done')) {
            $allowMgda = $true
            if (-not $mgdaOnlyActive -and $mgdaGateMode -eq 'pest_streak' -and (-not $mgdaGateOpen)) { $allowMgda = $false }
            if (-not $allowMgda) {
                Write-Host ("[NOPTMAX={0}] [{1}/{2}] [3/5] Skip MGDA update (waiting for PEST plateau)" -f @($nopt, ($iter + 1), $iterMax)) -ForegroundColor Yellow
                Set-IterStage -Iter $iter -Stage 'mgda_update' -Status 'start' -IterDir $iterDir
                $mgdaLog = (Join-Path $iterDir "mgda_console.log")
                $stageLogMap["$iterKey:mgda_update"] = $mgdaLog
                Set-Content -LiteralPath $mgdaLog -Value "MGDA skipped: waiting for PEST plateau" -Encoding utf8
                $pestParCandidates = @(
                    (Join-Path $iterDir "ksas_mvp_est.par"),
                    (Join-Path $iterDir "ksas_mvp.par"),
                    (Join-Path $iterDir "ksas_mvp.post.par")
                )
                $pestPar = $null
                foreach ($c in $pestParCandidates) { if (Test-Path -LiteralPath $c) { $pestPar = $c; break } }
                if (-not $pestPar) { throw "PEST parameter file missing for MGDA gating" }
                $pestParams = Read-ParParams $pestPar
                if (-not $pestParams -or $pestParams.Count -lt 1) { throw "PEST parameter file empty for MGDA gating" }
                Write-ParamsDat -Path (Join-Path $iterDir "params_mgda.dat") -Params $pestParams
                Write-ParamsDat -Path (Join-Path $iterDir "params_next.dat") -Params $pestParams
                $mgdaReport = @(
                    "status=skipped",
                    "reason=pest_no_plateau",
                    "step=0"
                )
                Set-Content -LiteralPath (Join-Path $iterDir "mgda_report.txt") -Value $mgdaReport -Encoding utf8
                Copy-Item -LiteralPath (Join-Path $iterDir "params_mgda.dat") -Destination (Join-Path $iterMgdaDir "params_mgda.dat") -Force
                Copy-Item -LiteralPath (Join-Path $iterDir "mgda_report.txt") -Destination (Join-Path $iterMgdaDir "mgda_report.txt") -Force
                Set-IterStage -Iter $iter -Stage 'mgda_update' -Status 'done' -IterDir $iterDir
            }
            else {
                Write-Host ("[NOPTMAX={0}] [{1}/{2}] [3/5] Compute MGDA parameter update" -f @($nopt, ($iter + 1), $iterMax)) -ForegroundColor Cyan
                Set-IterStage -Iter $iter -Stage 'mgda_update' -Status 'start' -IterDir $iterDir
                
                if ($iter -gt 0) {
                    $prevIterKey = Get-IterKey ($iter - 1)
                    $prevIterDir = Join-Path $workDir $prevIterKey
                    
                    # 传递自适应步长
                    $prevStepNext = Join-Path $prevIterDir "step_next.txt"
                    if (Test-Path -LiteralPath $prevStepNext) {
                        Copy-Item -LiteralPath $prevStepNext -Destination (Join-Path $iterDir "step.txt") -Force
                    }

                    # --- 闭环反馈：传递 MGDA Alpha 权重 ---
                    $prevAlphas = Join-Path $prevIterDir "mgda_alphas.json"
                    if (Test-Path -LiteralPath $prevAlphas) {
                        Copy-Item -LiteralPath $prevAlphas -Destination (Join-Path $iterDir "mgda_alphas.json") -Force
                    }
                }

                if ($mgdaAdapt) {
                    $env:MGDA_TRUST_REL = [string]$mgdaTrustRel
                    $env:MGDA_REG_LAMBDA = [string]$mgdaRegLambda
                }
                $env:OUT_PARAMS_PATH = (Join-Path $iterDir "params_mgda.dat")
                $mgdaLog = (Join-Path $iterDir "mgda_console.log")
                $stageLogMap["$iterKey:mgda_update"] = $mgdaLog
                $exitCode = Invoke-LoggedJob -ScriptBlock {
                    param($workDir, $projRootPath, $logPath)
                    Set-Location $workDir
                    $ErrorActionPreference = 'Continue'
                    python (Join-Path $projRootPath "src\mgda_update.py") 2>&1 | Out-File -LiteralPath $logPath -Encoding utf8
                    return $LASTEXITCODE
                } -ArgumentList @($iterDir, $projRoot, $mgdaLog) -LogPath $mgdaLog -StageLabel "MGDA update"
                if ($exitCode -ne 0) { throw "mgda_update.py failed (exit $exitCode)" }
                Remove-Item Env:OUT_PARAMS_PATH -ErrorAction SilentlyContinue
                if (-not (Test-Path -LiteralPath (Join-Path $iterDir "params_mgda.dat"))) { throw "MGDA params missing (params_mgda.dat)" }
                if (-not (Test-Path -LiteralPath (Join-Path $iterDir "mgda_report.txt"))) { throw "MGDA report missing (mgda_report.txt)" }
                Remove-Item Env:MGDA_TRUST_REL -ErrorAction SilentlyContinue
                Remove-Item Env:MGDA_REG_LAMBDA -ErrorAction SilentlyContinue
                Copy-Item -LiteralPath (Join-Path $iterDir "params_mgda.dat") -Destination (Join-Path $iterDir "params_next.dat") -Force
                Copy-Item -LiteralPath (Join-Path $iterDir "params_mgda.dat") -Destination (Join-Path $iterMgdaDir "params_mgda.dat") -Force
                Copy-Item -LiteralPath (Join-Path $iterDir "mgda_report.txt") -Destination (Join-Path $iterMgdaDir "mgda_report.txt") -Force
                if (Test-Path -LiteralPath (Join-Path $iterDir "step_next.txt")) {
                    Copy-Item -LiteralPath (Join-Path $iterDir "step_next.txt") -Destination (Join-Path $iterMgdaDir "step_next.txt") -Force
                }
                Set-IterStage -Iter $iter -Stage 'mgda_update' -Status 'done' -IterDir $iterDir
                $mgdaRanThisIter = $true
                if ($mgdaOnlyActive -and $mgdaOnlyRemaining -gt 0) { $mgdaOnlyRemaining -= 1 }
            }
        }

        if (-not ($iterStageMap -and $iterStageMap.ContainsKey('evaluate') -and $iterStageMap['evaluate'] -eq 'done')) {
            # --- RETHINK: Progress Evaluation Mode ---
            Write-Host ("[NOPTMAX={0}] [{1}/{2}] [4/5] Evaluate MGDA Progress" -f @($nopt, ($iter + 1), $iterMax)) -ForegroundColor Cyan
            Set-IterStage -Iter $iter -Stage 'evaluate' -Status 'start' -IterDir $iterDir
            
            # Pass only MGDA params for evaluation to avoid redundant Baseline/PEST runs in the loop
            $env:MGDA_PARAMS_PATH = (Join-Path $iterDir "params_mgda.dat")
            
            $compareLog = (Join-Path $iterDir "compare_console.log")
            $stageLogMap["$iterKey:evaluate"] = $compareLog
            $exitCode = Invoke-LoggedJob -ScriptBlock {
                param($workDir, $projRootPath, $logPath)
                Set-Location $workDir
                $ErrorActionPreference = 'Continue'
                # Use --progress flag for single-target evaluation (Path B only)
                python (Join-Path $projRootPath "src\compare_three.py") 2>&1 | Out-File -LiteralPath $logPath -Encoding utf8
                return $LASTEXITCODE
            } -ArgumentList @($iterDir, $projRoot, $compareLog) -LogPath $compareLog -StageLabel "Evaluate Progress"
            
            if ($exitCode -ne 0) { throw "Progress evaluation failed (exit $exitCode)" }
            Remove-Item Env:MGDA_PARAMS_PATH -ErrorAction SilentlyContinue
            
            if (-not (Test-Path -LiteralPath (Join-Path $iterDir "compare_summary.csv"))) { throw "Progress output missing (compare_summary.csv)" }
            
            Copy-Item -LiteralPath (Join-Path $iterDir "compare_summary.csv") -Destination (Join-Path $iterEvalDir "compare_summary.csv") -Force
            Set-IterStage -Iter $iter -Stage 'evaluate' -Status 'done' -IterDir $iterDir
        }

        if (-not ($iterStageMap -and $iterStageMap.ContainsKey('archive') -and $iterStageMap['archive'] -eq 'done')) {
            Write-Host ("[NOPTMAX={0}] [{1}/{2}] [5/5] Archive iteration artifacts" -f @($nopt, ($iter + 1), $iterMax)) -ForegroundColor Cyan
            Set-IterStage -Iter $iter -Stage 'archive' -Status 'start' -IterDir $iterDir
            Copy-Item -LiteralPath (Join-Path $iterDir "dssat_case") -Destination $iterDssatDir -Recurse -Force -ErrorAction SilentlyContinue
            Copy-Item -LiteralPath (Join-Path $iterDir "pest_out.dat") -Destination $iterEvalDir -Force -ErrorAction SilentlyContinue
            Set-IterStage -Iter $iter -Stage 'archive' -Status 'done' -IterDir $iterDir
        }

        $sum = Import-Csv -LiteralPath (Join-Path $iterDir "compare_summary.csv")
        # In Progress mode, the scenario is usually 'mgda'
        $mgda = $sum | Where-Object { $_.scenario -eq 'mgda' } | Select-Object -First 1
        if (-not $mgda) { $mgda = $sum | Select-Object -First 1 }
        
        $mgdaMeta = Read-KvFile (Join-Path $iterDir "mgda_report.txt")
        $mgdaStatus = $mgdaMeta['status']
        if ($mgdaRanThisIter -or ($mgdaStatus -and ($mgdaStatus -ne 'skipped'))) { $mgdaEverRan = $true }

        $mgdaPhiW = [double]$mgda.phi_w
        
        if ($mgdaGateMode -eq 'pest_streak') {
            # Note: In decoupled mode, gating logic might need reconsideration. 
            # For now, we keep it as-is but it's less relevant for Path B long-runs.
        }

        $warningOut = if (Test-Path -LiteralPath (Join-Path $iterDir "WARNING.OUT")) { (Join-Path $iterDir "WARNING.OUT") } else { $null }
        $ablRows += [pscustomobject]@{
            noptmax = [int]$nopt
            iter = [int]$iter
            mgda_phi_w = $mgdaPhiW
            mgda_train_rmse_yield = Get-DoubleField $mgda 'rmse_yield'
            mgda_train_rmse_laix = Get-DoubleField $mgda 'rmse_laix'
            mgda_status = $mgdaMeta['status']
            mgda_step = $mgdaMeta['step']
            mgda_backtracks = $mgdaMeta['backtracks']
            run_dir = $iterDir
            mgda_log = (Join-Path $iterDir "mgda_console.log")
            compare_log = (Join-Path $iterDir "compare_console.log")
        }

        $paretoRows += [pscustomobject]@{
            iter = [int]$iter
            obj_train_phi_w = [double](Get-DoubleField $mgda 'phi_w')
            run_dir = $iterDir
        }

        if ($mgdaEverRan) {
            $prev = $prevPhiW
            $curr = $mgdaPhiW
            if ([double]::IsNaN($prev)) {
                $prevPhiW = $curr
                $noImproveStreak = 0
            }
            else {
                $imp = $prev - $curr
                if ([double]::IsNaN($imp) -or [double]::IsInfinity($imp)) { $imp = 0.0 }
                if ($imp -lt $improveEps) { $noImproveStreak += 1 } else { $noImproveStreak = 0 }
                $prevPhiW = $curr
            }
        }

        $stationary = $mgdaEverRan -and (($mgdaStatus -eq 'pareto_stationary') -or ($mgdaMeta['step'] -eq '0.000000'))
        if ($allowEarlyStop -and $mgdaEverRan -and ($mgdaOnlyRemaining -le 0) -and ($stationary -or ($noImproveStreak -ge $improveStreakN))) {
            $stopIter = $iter
            break
        }
    }
}

Remove-Item Env:PEST_NOPTMAX -ErrorAction SilentlyContinue

$manifestPath = Join-Path $rootWorkDir "run_manifest.csv"
$ablRows | Export-Csv -LiteralPath $manifestPath -NoTypeInformation

Write-RunMeta
Write-Host "Done." -ForegroundColor Green
Write-Host "Work directory: $rootWorkDir" -ForegroundColor Green

}
catch {
    Write-Error ($_ | Out-String).Trim()
    exit 1
}
