# 边界收口与质量门禁路线图

## 1. 目标

这份路线图用于回答两个问题：

1. 当前哪些问题是需要尽快动手的阻塞项
2. 哪些是方向正确但不宜过早推进的中期演化项

它的核心作用，是避免把“理想架构”误当成“当前版本不合格”。

## 2. 当前应立即处理的问题

### 2.1 冻结 paper-facing 口径

主矩阵 protocol artifacts、quality gate 与 report rebuild 的技术闭环已经成立；当前最急的风险，已经从“功能缺失”转为“科研运行期字段口径继续漂移”。

因此下一轮应优先冻结：

- `main_matrix_protocol_paper_table.tsv`
- `main_matrix_paper_main_table.tsv`
- `main_matrix_paper_appendix_table.tsv`

重点不再是继续扩 protocol 细字段，而是把真正进入论文、补充材料与复核流程的表口径固定下来。

### 2.2 把 quality gate 升级为科研 stop/go 规则

当前 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已能稳定产出 `main_matrix_quality_gate.tsv`，但它仍更像“报告产物”，尚未完全提升为科研批量运行的正式决策门禁。

下一轮需要明确：

- 哪些 `pass/warn/fail` 组合可以直接进入后续分析
- 哪些情况必须先人工复核 contract/protocol artifacts
- 哪些失败会阻断批量实验继续扩展

### 2.3 增加可选 live DSSAT acceptance

研究层门禁、主矩阵端到端 smoke、多作物农学语义门禁与 `.venv` 固定执行环境都已具备第一轮稳定闭环；此时最有价值的新增验证，不再是抽象层单元测试，而是一条可选的真实安装 acceptance。

这条 acceptance 应使用本机 `C:\DSSAT48\Wheat` 与真实参考文件，确认：

- 路径解析在真实安装环境下可用
- 观测文件可被稳定识别
- protocol artifacts 与质量门禁能在真实 DSSAT 环境中完成一轮落盘

## 3. 中期再推进的问题

### 3.1 `public_api` 服务化

[public_api.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/public_api.py#L21-L32) 目前更像模块转发器。方向上应逐步上收为领域服务，但这不是当前最急的阻塞项。

### 3.2 深层 core 迁移

把：

- [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py)
- [case_runtime.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/case_runtime.py)
- [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)

完全迁入 `calibration_core` 是正确方向，但如果现在先做，容易与协议重构、作物注册表重构相互打架。

## 4. Phase 划分

## Phase 1：协议与门禁先行

### 目标

- 落地 `run_manifest.json`
- 落地 `contract_report.json`
- 为 `autoresearch_sandbox` 补齐 lint/typecheck/smoke test

### 当前状态

Phase 1 已完成：

- 已完成：`autoresearch_sandbox` 已纳入 [pyproject.toml](file:///d:/Wheat/Wheat/mvp_pest_mgda/pyproject.toml)、[lint.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/lint.ps1)、[typecheck.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/typecheck.ps1)
- 已完成：门禁范围与研究层路径契约已由 [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 和 [test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py) 保护
- 已完成：`run_manifest.json` 与 `contract_report.json` 已由 [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)、[build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 和 [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py) 正式落盘
- 已完成：研究层 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已消费协议产物的 `contract_status`、active groups、`fallback_metrics`、`dropped_groups`、`weight_fallbacks`、`zero_weight_observations`，并在 protocol overview / panel 中聚合
- 已完成：`main_matrix_protocol_overview.tsv`、`main_matrix_protocol_dimension_summary.tsv`、`main_matrix_protocol_nested_dimension_summary.tsv`、`main_matrix_protocol_hotspot_summary.tsv`、`main_matrix_protocol_reason_summary.tsv`、`main_matrix_protocol_paper_table.tsv` 与 `main_matrix_quality_gate.tsv` 已纳入 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 与 [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 的验证闭环
- 已完成：[test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 已补主矩阵端到端 smoke，覆盖 `runtime protocol inputs -> artifacts -> quality gate -> report` 主链路
- 下一入口：冻结 paper-facing table 口径，并把现有 quality gate 从报告产物升级为科研批量运行的 stop/go 验收

### 推荐文件落点

- 协议对象：`mvp_pest_mgda/src/calibration_core/`
- 研究层门禁：`mvp_pest_mgda/scripts/` 或 `pyproject.toml`

### 验收点

- 单次运行产物可解释
- 研究层改动能进入自动检查
- 协议产物可被测试断言稳定读取

## Phase 2：作物注册表落地

### 目标

- 建立 `crop_registry`
- 让 `observations.py` / `dssat_io.py` 先读取 registry
- 不改变 Wheat 主线行为

### 当前状态

Phase 2 已完成最小稳定闭环：

- 已完成：[observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py) 与 [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py) 已读取 registry 的指标、trial prefix 与 cultivar 信息
- 已完成：[build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 已改为从 registry 读取 summary A-file 列映射与默认观测组
- 已完成：研究层 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已消费同一份 registry 的 stage/grouping profile
- 已完成：[test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py) 已补 crop registry read-only smoke test、snapshot contract 与多作物 golden subset，稳定 alias/trial-prefix/profile 字段契约
- 已完成：[test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 与 [test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py) 已覆盖 `.CUL` 固定宽度回写、`FileX` treatment/cultivar 解析、registry 驱动参数顺序与多作物 bounds 对齐契约
- 下一入口：把现有语义门禁上收为科研 acceptance 的最低契约，只在新增作物或新增实验模板时按需扩展

### 风险控制

- 先“复述现有逻辑”，再“替换现有逻辑”
- 不在这一阶段同步重写研究层 orchestrator

## Phase 3：边界继续收口

### 目标

- 拆出 `observations` 相关共享能力
- 拆出 `case_runtime` 相关共享能力
- 缩减 `dssat_io.py` 的职责

### 原则

- 收口的是领域知识，不是机械减少文件行数
- `run_model.py` / `build_pest_setup.py` 可以继续保留 orchestrator 身份
- 目标是“更清楚的职责边界”，不是“空心化 CLI”

## Phase 4：服务化与长期平台化

### 目标

- `public_api` 服务化
- grouping / phase profile 化
- 更广泛的作物发现机制

### 说明

这一阶段才更接近“长期平台理想态”，不应被前置成当前交付标准。

## 5. 门禁清单建议

## 5.1 立即补齐

- `ruff check src`
- `mypy src`
- `ruff check autoresearch_sandbox`
- `mypy autoresearch_sandbox`

以上四项已全部纳入默认脚本，下一阶段不再是“要不要接入”，而是“如何持续防止回退”。

## 5.2 下一步补齐

- 冻结 paper-facing TSV / table 字段口径
- 把 `main_matrix_quality_gate.tsv` 接入批量实验 stop/go 决策
- 增加可选 live Wheat / DSSAT acceptance smoke

其中下一轮的首要项应改写为：

1. 冻结 `main_matrix_protocol_paper_table.tsv`、`main_matrix_paper_main_table.tsv`、`main_matrix_paper_appendix_table.tsv`
2. 明确 `main_matrix_quality_gate.tsv` 的 `pass/warn/fail` 与人工复核动作
3. 增加真实 `C:\DSSAT48\Wheat` 安装环境下的 acceptance smoke
4. 将深层 core 迁移与服务化继续降级为不阻塞科研实践的后续项

## 6. 迁移原则

所有边界迁移建议遵循：

1. 先加新对象，不立即删旧入口
2. 先让新对象复述旧逻辑，再切换调用方
3. 每一步都保证 Wheat 主线可继续运行
4. 每一步都优先保证论文结果可复核

## 7. 本文件结论

下一轮重构最稳妥的路线，不是“先大迁移再慢慢补协议”，而是“先把现有协议和门禁升级为真正可执行的科研验收，再推进数据模型和边界收口”。基于当前进度，这句话现在应更新为：**Phase 1 已完成，Phase 2 已完成最小稳定闭环，主矩阵端到端 smoke、多作物农学语义门禁与 `.venv` 固定执行环境都已进入既成事实；真正的下一阻塞点已经前移为 paper-facing 口径冻结、live DSSAT acceptance，以及把 `main_matrix_quality_gate.tsv` 升级为科研批量运行的正式 stop/go 标准。**
