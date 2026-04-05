# 显式运行协议规格

## 1. 目标

本规格定义下一阶段应新增的两份核心产物：

- `run_manifest.json`
- `contract_report.json`

目标不是取消环境变量，而是让环境变量与 `cwd` 不再是唯一协议载体。执行链内部仍可继续使用 env 做 subprocess handoff，但所有关键运行信息都必须被显式落盘，成为可追溯、可审计、可供论文引用的真相源。

## 1.1 当前进度

与上一版规格相比，协议落地的外围前置条件已经明显改善：

- [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py) 与 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已统一到 `runs/runtime`、`runs/parallel_workers` 与 `artifacts` 目录协议
- [pyproject.toml](file:///d:/Wheat/Wheat/mvp_pest_mgda/pyproject.toml)、[lint.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/lint.ps1)、[typecheck.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/typecheck.ps1) 已把研究层纳入门禁，并固定使用项目 `.venv`
- [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 与 [test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py) 已对研究层路径契约与门禁范围建立回归断言
- [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 已补主矩阵 report rebuild 的端到端 smoke，用真实 runtime/protocol 输入重建 protocol artifacts、quality gate 与主报告

因此，本规格现在的角色已经从“先搭好外围条件”转为“记录首轮已落地协议，并定义下一轮扩展字段”。

## 1.2 首轮已落地内容

当前实现已经在以下位置完成首轮接入：

- [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py) 提供共享协议 dataclass、payload builder 与 JSON artifact writer
- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py) 在 runtime 侧写出 `run_manifest.json` 与 `contract_report.json`
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 在 build/setup 侧补写 split、active groups、fallback metrics、active counts 与 resolved output context
- [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 已对共享 builder 复用和协议产物写入建立回归断言
- [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已建立 protocol artifacts 索引，并消费 `contract_status`、`fallback_metrics`、`dropped_groups`、`weight_fallbacks`、`zero_weight_observations` 与 report-level overview/panel 聚合
- [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 还会写出 `main_matrix_protocol_dimension_summary.tsv`、`main_matrix_protocol_nested_dimension_summary.tsv`、`main_matrix_protocol_hotspot_summary.tsv`、`main_matrix_protocol_reason_summary.tsv`、`main_matrix_protocol_paper_table.tsv` 与 `main_matrix_quality_gate.tsv`
- [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 还已覆盖 bounds preview 损坏时的退化、manifest 路径缺失时的回退，以及 posterior diagnostics `output_dir` 复用不串工件的协议稳定性

## 2. 适用范围

本规格覆盖以下链路：

- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py#L405-L521)
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L956-L1029)
- [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py#L201-L237)
- [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L500-L605)

## 3. 设计原则

### 3.1 manifest 统摄 env

- env 继续保留，用于 DSSAT/PEST 子进程 handoff
- manifest 负责归档、解释、审计
- contract report 负责解释“为什么最终目标函数是现在这个样子”

### 3.2 先最小闭环，再扩字段

首轮实现只记录对研究复现最关键的信息，不追求一次把所有调试细节都写进去。

### 3.3 写一次，多处复用

同一批字段不要在：

- `run_model.py`
- `build_pest_setup.py`
- `auto_evolve.py`

中各写一套不同口径。应由一个共享的协议对象统一生成。

## 4. `run_manifest.json` 规格

## 4.1 必需字段

```json
{
  "run_id": "string",
  "created_at": "ISO-8601 datetime",
  "run_kind": "matrix|robustness|manual",
  "crop_family": "string",
  "project_config_path": "string",
  "params_path": "string",
  "runtime_dir": "string",
  "case_dir": "string|null",
  "weight_mode": "string|null",
  "engine": "string|null",
  "sequence": "string|null",
  "grouping": "string|null",
  "budget_profile": "string|null",
  "baseline_profile": "string|null",
  "active_metrics": ["string"],
  "split": {
    "train": ["int"],
    "valid": ["int"],
    "mode": "string|null"
  },
  "bounds": {
    "source": "custom|official|fallback|mixed|unknown",
    "official_source_path": "string|null"
  },
  "execution": {
    "python_executable": "string",
    "cwd": "string",
    "env_keys": ["string"]
  }
}
```

## 4.2 首轮可以为空的字段

以下字段允许先写 `null`，以降低接入成本：

- `engine`
- `sequence`
- `grouping`
- `budget_profile`
- `baseline_profile`
- `case_dir`

但这些字段一旦在 `auto_evolve.py` 中可得，就应优先补齐。

## 4.3 写入时机

建议采用“两阶段写入”：

1. **启动前写骨架**
   - 在运行刚开始时生成 manifest
   - 记录输入参数、路径、实验轴信息
2. **运行后补结果元数据**
   - 可补充实际执行文件、退出状态、产物位置

## 4.4 写入位置

建议统一写到 runtime 根目录下，例如：

- `<runtime_dir>\run_manifest.json`

如果由研究层统一编排，则还应在 artifacts 层保存索引引用，而不是复制多份实体。

## 5. `contract_report.json` 规格

## 5.1 目标

`contract_report.json` 不记录“实验想怎么跑”，而记录“实验最终实际以什么口径参与了目标函数”。

## 5.2 必需字段

```json
{
  "run_id": "string",
  "status": "ok|degraded|invalid",
  "missing_files": ["string"],
  "missing_metrics": ["string"],
  "fallback_metrics": [
    {
      "requested": "string",
      "actual": "string",
      "reason": "string"
    }
  ],
  "zero_weight_observations": [
    {
      "obs_name": "string",
      "reason": "string"
    }
  ],
  "active_groups": ["string"],
  "dropped_groups": [
    {
      "group": "string",
      "reason": "string"
    }
  ],
  "weight_fallbacks": [
    {
      "group": "string",
      "reason": "string"
    }
  ],
  "summary": {
    "active_metric_count": "int",
    "active_observation_count": "int"
  }
}
```

## 5.3 `status` 规则

- `ok`：无关键缺失，主指标与分组按预期启用
- `degraded`：存在回退、裁剪或缺失，但仍可运行
- `invalid`：不满足当前模式的最低契约

## 5.4 模式差异

这里必须显式区分两种模式：

- **paper / matrix strict mode**
  - 主指标缺失可直接判为 `invalid`
  - 不允许无提示地更换主指标语义
- **exploratory mode**
  - 允许保留 `pick_eval_value()` 这类 fallback
  - 但必须在 `fallback_metrics` 中落盘

## 6. 与现有模块的接入点

## 6.1 `run_model.py`

负责提供：

- crop
- params path
- project config path
- case/runtime 路径
- 实际执行 cwd

## 6.2 `build_pest_setup.py`

负责提供：

- `weight_mode`
- `split`
- `active_metrics`
- 实际启用观测数
- 分组/权重回退信息

## 6.3 `observations.py` 与 `dssat_io.py`

负责提供：

- 主指标识别结果
- 指标缺失
- fallback 命中情况
- A/T 文件契约降级信息

## 6.4 `auto_evolve.py`

负责补充：

- `run_kind`
- `engine`
- `sequence`
- `grouping`
- `budget_profile`
- `baseline_profile`

## 7. 建议实现顺序

### Phase 1

先实现最小 `run_manifest.json`：

- run_id
- crop_family
- params_path
- project_config_path
- runtime_dir
- execution.cwd
- execution.env_keys
- python_executable
- project_config_path
- case_dir / runtime_dir

当前状态：已完成。

### Phase 2

再补最小 `contract_report.json`：

- status
- missing_metrics
- fallback_metrics
- active_groups
- summary
- resolved output context

当前状态：已完成首轮版本。

### Phase 3

最后把：

- 矩阵轴信息
- 权重回退
- zero-weight observations
- group drop reasons

完整纳入共享协议对象。

当前状态：已完成第二轮落地。研究层 artifacts 索引已结构化消费 `weight_fallbacks`、`zero_weight_observations` 与 `group drop reasons`，并在 protocol overview、dimension summary、nested dimension summary、hotspot summary、reason summary、panel table 与 quality gate 中形成聚合输出。

## 7.1 当前建议切入点

结合现有代码结构，下一轮实现建议从以下位置切入：

1. 继续在 [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py) 维持共享协议对象单点生成，而不是回退到各模块各写一套
2. 把已落地的端到端 smoke 继续上推为可选 live DSSAT acceptance，用真实 `C:\DSSAT48\Wheat` 安装验证 runtime 路径与协议落盘
3. 让 [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 与测试继续守住 dropped groups / weight fallbacks / zero-weight observations 的结构化口径，避免后续边界迁移改变字段语义
4. 冻结 paper-facing TSV 的字段口径，避免在进入科研实践后仍频繁改 protocol schema
5. 把 `main_matrix_quality_gate.tsv` 明确绑定为研究批量运行的 stop/go 规则，而不是只作为报告附属表

## 8. 验收标准

满足以下条件即视为协议层进入科研可用状态：

1. 单次运行结束后总能找到 manifest
2. 发生指标缺失或回退时总能找到 contract report
3. 仅凭产物文件即可回答“这次实验怎么跑、最后按什么口径算目标”
4. 主矩阵 report rebuild smoke 能从 runtime/protocol 输入重建出 protocol artifacts、quality gate 与主报告
5. 不要求移除现有 env 机制

### 当前剩余验收缺口

- 冻结 `main_matrix_protocol_paper_table.tsv` 与 paper tables 的最终字段口径
- 增加一条可选 live DSSAT acceptance，用真实安装环境确认路径、观测文件与 protocol artifacts 在本机可用
- 把 quality gate 的 `pass/warn/fail` 明确接入科研批量运行决策

## 9. 本文件结论

当前显式协议已经完成从 JSON artifact 到 TSV 切片、hotspot、quality gate 以及 report rebuild smoke 的第二轮闭环。下一轮最有价值的工作，不是继续扩协议字段，而是冻结真正服务科研复现的 paper-facing 口径、补 live DSSAT acceptance，并把 `main_matrix_quality_gate.tsv` 升级为科研运行的正式 stop/go 标准。
