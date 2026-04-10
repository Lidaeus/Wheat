# Phase1 异机部署与运行手册

## 1. 适用范围

本手册用于在另一台 Windows 机器上完整部署并运行 Phase1 第一阶段实验，目标与口径对齐：

- `docs/Drafts/04_Phase1_实验实践指南.md`
- 当前代码仓：`Parallel_Exp`

默认目标：

- 可复现实验入口
- 可稳定运行 Batch A/B/C/D 与 Baselines
- 可导出论文与后处理所需结果文件

---

## 2. 关于 `pestpp-glm.exe / pestpp-ies.exe` 的推荐方案

你提出“把二进制也提交到仓库”是可行的。实践上建议采用分层方案：

### 方案 A（最稳妥，推荐）

- 将 `pestpp-glm.exe`、`pestpp-ies.exe` 放入仓库内固定位置：
  - `mvp_pest_mgda/vendor/pestpp_5.2.16_iwin/bin/`
- 运行时只依赖仓库相对路径，不依赖机器绝对路径。

优点：

- 异机最省心
- 命令几乎零改动
- 与当前代码的自动发现逻辑一致

注意点：

- 仓库体积增大
- 需要确认二进制分发许可与团队策略

### 方案 B（不提交二进制，但仍可便携）

- 每台机器本地放置 PEST++，并在运行前设置环境变量：
  - `PESTPP_ROOT`
  - `PESTPP_GLM`
  - `PESTPP_IES`

当前代码已支持优先读取这些变量。

---

## 3. 目录与前置条件

建议目录结构：

```text
D:\Wheat\
 ├─ Parallel_Exp\               # 本仓库
 └─ DSSAT48\                    # DSSAT 根目录（可在其它盘）
```

必需前置：

- Windows PowerShell 5+
- Python 3.11/3.12/3.13（与项目环境一致）
- DSSAT 可执行环境可用
- 观测与试验文件齐全（WHA/WHT/WHX/CUL）

---

## 4. 首次部署步骤

在新机器上执行：

```powershell
cd D:\Wheat
git clone <你的仓库地址> Parallel_Exp
cd .\Parallel_Exp\mvp_pest_mgda
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果没有 `requirements.txt`，按你当前环境实际依赖安装（至少需 `pyemu`、`numpy`、`pandas`、`scipy`、`mypy`、`ruff` 等）。

---

## 5. PEST++ 二进制放置与检查

### 5.1 推荐放置

把二进制放到：

```text
Parallel_Exp\mvp_pest_mgda\vendor\pestpp_5.2.16_iwin\bin\
  pestpp-glm.exe
  pestpp-ies.exe
```

### 5.2 快速检查

```powershell
cd D:\Wheat\Parallel_Exp\mvp_pest_mgda
Get-ChildItem .\vendor\pestpp_5.2.16_iwin\bin\pestpp-*.exe
```

---

## 6. 运行前环境建议

建议固定：

```powershell
$env:PROJECT_CROP = "wheat"
$env:DSSAT_ROOT = "C:\DSSAT48"
```

可选增强（如果二进制不在 vendor）：

```powershell
$env:PESTPP_ROOT = "D:\path\to\mvp_pest_mgda"
$env:PESTPP_GLM  = "D:\path\to\pestpp-glm.exe"
$env:PESTPP_IES  = "D:\path\to\pestpp-ies.exe"
```

---

## 7. Phase1 运行命令模板

说明：根据 `04_Phase1_实验实践指南.md`，正式运行最低预算应为 `standard`。`quick` 仅用于冒烟检查。

统一解释器：

```powershell
$py = "D:\Wheat\Parallel_Exp\mvp_pest_mgda\.venv\Scripts\python.exe"
$runner = "D:\Wheat\Parallel_Exp\autoresearch_sandbox\phase1_runner.py"
```

### 7.1 冒烟检查（quick）

```powershell
& $py $runner --batch BatchA --budget quick --workers 14 --repetitions 1 --crops Wheat --tag smoke_quick --skip-postprocess
```

### 7.2 正式 Baselines（standard）

```powershell
& $py $runner --batch Baselines --budget standard --workers 14 --repetitions 1 --crops Wheat --tag phase1_baselines_standard
```

### 7.3 正式 Batch A/B/C/D（standard）

```powershell
& $py $runner --batch BatchA --budget standard --workers 14 --repetitions 1 --crops Wheat --tag phase1_batcha_standard
& $py $runner --batch BatchB --budget standard --workers 14 --repetitions 1 --crops Wheat --tag phase1_batchb_standard
& $py $runner --batch BatchC --budget standard --workers 14 --repetitions 1 --crops Wheat --tag phase1_batchc_standard
& $py $runner --batch BatchD --budget standard --workers 14 --repetitions 1 --crops Wheat --tag phase1_batchd_standard
```

### 7.4 一键运行全部正式实验（推荐）

根据实验实践指南，正式实验需要运行全部批次（BatchA/B/C/D + Baselines）覆盖五作物，并设置足够重复次数以支撑 rank stability 分析。

**单作物完整正式实验（5 次重复）：**

```powershell
& $py $runner --batch All --budget standard --workers 14 --repetitions 5 --crops Wheat --tag phase1_wheat_full
```

**五作物完整正式实验（一键运行）：**

```powershell
& $py $runner --batch All --budget standard --workers 14 --repetitions 5 --crops Wheat,Maize,Soybean,Rice,Cotton --tag phase1_full_standard
```

> 说明：`--batch All` 会依次运行 Baselines + BatchA/B/C/D，共 175 个唯一配置（32×5 主矩阵 + 3×5 基线）。`--repetitions 5` 确保每个配置运行 5 次，总计约 875 次运行，可支撑稳健性统计与论文主结果。

### 7.5 多作物串行模板

```powershell
$crops = @("Wheat","Maize","Soybean","Rice","Cotton")
foreach ($c in $crops) {
  & $py $runner --batch BatchA --budget standard --workers 14 --repetitions 1 --crops $c --tag ("phase1_batcha_" + $c.ToLower())
}
```

---

## 8. 结果目录与必须带回文件

每次运行会创建会话目录：

```text
autoresearch_sandbox\phase1_runs\<session_name>\
```

至少带回以下文件（用于后处理与论文）：

- `phase1_run_manifest.json`
- `phase1_experiment_summary.tsv`
- `phase1_aggregate_metrics.tsv`
- `phase1_treatment_metrics.tsv`
- `phase1_parameters.tsv`
- `phase1_figure_ready.tsv`
- `logs\*.stdout.log`
- `logs\*.stderr.log`

打包示例：

```powershell
$session = "D:\Wheat\Parallel_Exp\autoresearch_sandbox\phase1_runs\20260409_xxx"
Compress-Archive -Path $session -DestinationPath ($session + ".zip") -Force
```

---

## 9. 常见故障与定位

### 9.1 `pestpp-glm.exe not found`

含义：不是 DSSAT 崩溃，而是 PEST++ 二进制解析失败。

处理：

- 确认 `vendor/pestpp_5.2.16_iwin/bin` 下存在 exe
- 或设置 `PESTPP_ROOT / PESTPP_GLM / PESTPP_IES`

### 9.2 `InstructionFile EOF encountered marker search`

含义：`pest_out.ins` 与 `pest_out.dat` 键不一致。

处理：

- 检查对应 run 的：
  - `runs/runtime/pest_out.ins`
  - `runs/runtime/pest_out.dat`
  - `logs/*.stderr.log`

### 9.3 怀疑 DSSAT 崩溃

优先检查：

- `logs/*.stderr.log`
- `workspaces/<run_id>/runs/runtime/contract_report.json`
- `workspaces/<run_id>/dssat_case/` 下 `Summary.OUT`、`WARNING.OUT`、`Evaluate.OUT`

若 `run_model.py` 返回码为 0，但 PEST++ 失败，通常不是 DSSAT 进程崩溃，而是观测解析或协议契约问题。

---

## 10. 运行后质量门

在 `mvp_pest_mgda` 下执行：

```powershell
python -m ruff check src
python -m mypy src
```

建议追加：

- 检查 `phase1_experiment_summary.tsv` 是否存在且非空
- 检查 `status` 字段失败率
- 检查是否出现大面积 `score=999`

---

## 11. 与第一阶段实践指南的对齐点

本手册直接服务以下实践要求：

- 支持 Batch A/B/C/D 分批执行
- 运行并保留 Baselines（B0/B1/B2）
- 输出完整 5 张核心结果表 + 日志
- 支持后续“主分数 + 负优化 + 稳健性 + 参数合理性”四类证据分析
- 支持 `workers=14` 并发运行

