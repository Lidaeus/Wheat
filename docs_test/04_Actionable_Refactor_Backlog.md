# 可执行改进清单与重构路线

## 1. 目标

本清单不是泛泛而谈的“优化建议”，而是按你的研究需要重新排序后的执行路线。排序依据是：

1. 是否直接影响 `W × O × S × G` 主矩阵的研究可信度
2. 是否直接影响未来多作物与全作物扩展
3. 是否能在不推翻现有重构成果的前提下渐进落地

## 2. P0：必须优先完成

### 当前进度快照

- 已完成：研究层质量门禁已纳入正式脚本与配置，覆盖 [pyproject.toml](file:///d:/Wheat/Wheat/mvp_pest_mgda/pyproject.toml)、[lint.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/lint.ps1)、[typecheck.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/typecheck.ps1) 与 [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py)
- 已完成：研究层路径约定继续稳定在 `runs/runtime`、`runs/parallel_workers`、`artifacts`，对应实现位于 [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py) 与 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py)
- 已完成：显式协议首轮已落盘到 [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)、[build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 与 [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py)
- 已完成：`crop_registry` 已进入只读接入阶段，[observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py)、[dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py) 与 [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 已开始复用同一份作物配置
- 已完成：研究层 artifacts 索引与主报告已继续消费协议细字段，当前可从 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 汇总 `contract_status`、active groups、`fallback_metrics`、`dropped_groups`、`weight_fallbacks`、`zero_weight_observations` 及其 overview/panel 聚合
- 已完成：`crop_registry` 的只读 API、snapshot contract 与多作物 golden subset 已由 [test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py) 稳定覆盖
- 已完成：protocol 细字段已经扩到 `weight/engine/sequence/grouping` 维度切片、嵌套切片、hotspot summary 与 quality gate，入口位于 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 与 [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py)
- 已完成：主矩阵 report rebuild 已补成端到端 smoke test，[test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 已验证 `runtime protocol inputs -> protocol artifacts -> quality gate -> report` 主链路
- 已完成：默认 lint/typecheck 已固定到项目 `.venv`，对应 [lint.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/lint.ps1) 与 [typecheck.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/typecheck.ps1)，并由 [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 防回退
- 已完成：多作物农学语义门禁已覆盖 `.CUL` 固定宽度回写、`FileX` treatment/cultivar 解析、registry 驱动的 `params.dat` / `params.tpl` 顺序，以及多作物 `FileX` / cultivar / bounds 对齐契约，入口位于 [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 与 [test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py)
- 已完成：posterior diagnostics 已补 bounds preview 坏数值退化、manifest/params 顺序回退、自定义 `output_dir` 隔离与旧工件清理契约，核心实现位于 [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py)
- 下一优先级：停止继续扩“基础设施功能面”，转为冻结 paper-facing 验收口径、补一条可选 live DSSAT 安装验收，并把 `main_matrix_quality_gate` 绑定为科研批量运行的 stop/go 规则

## P0-1 收口共享内核边界

### 目标

把当前仍散落在顶层 `src` 的基础能力逐步收拢进 `calibration_core`：

- [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)
- [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py)
- [case_runtime.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/case_runtime.py)
- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py)

### 理由

如果共享内核边界不收口，研究层就始终是在“调用一个仍在迁移中的工程内部实现”，这不利于长期演化。

### 建议顺序

1. 先迁 `observations.py`
2. 再迁 `case_runtime.py`
3. 再拆 `dssat_io.py`
4. 最后让 `run_model.py` 与 `build_pest_setup.py` 成为薄 CLI 壳

## P0-2 建立作物注册表 `crop_registry`

### 目标

把当前分散在配置文件、默认值与回退逻辑中的作物知识统一成正式注册表。

### 注册表至少应包含

- `crop_family`
- `aliases`
- `required_metrics`
- `optional_metrics`
- `yield_metric`
- `timeseries_metrics`
- `grouping_profiles`
- `phase_templates`
- `bounds_source`
- `genotype_locator`

### 理由

这是从“五作物可用”走向“DSSAT 全作物可扩展”的关键一步。

### 当前状态

本项已完成第二轮最小接入：

- [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py) 已从 registry 读取 `yield_var` / `laix_var` / `t_vars`
- [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py) 已从 registry 读取作物别名、trial prefix 与默认 project config
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 已改为从 registry 读取 `SUMMARY_AFILE_COLUMN_MAP` 与默认观测组，而不是继续维护独立硬编码

### 下一子任务

- 保持 `iter_supported_crops()`、alias/trial-prefix、`summary_afile_columns`、`grouping_profiles`、`phase_templates` 的只读字段冻结，避免后续迁移时隐式改口径
- 把当前已落地的 `.CUL` / `FileX` / bounds 语义门禁视为“科研前最低契约”，后续只在新增作物或新增实验模板时按需扩展，不再把 registry 字段本身无限扩张
- 如需进一步提高科研前信心，优先补“真实 DSSAT 安装 + 真实 Wheat 参考文件”的可选 acceptance smoke，而不是继续堆抽象层

## P0-3 为每次运行生成 `run_manifest.json`

### 目标

每次实验都输出一份可审计的 manifest。

### 当前状态

本项已完成首轮落地：

- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py) 已在运行开始与结果写回阶段更新 `run_manifest.json`
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 已写入 build/setup 侧的 manifest 元数据
- 共享协议对象已收口到 [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py)

### 至少记录

- run_id
- crop
- config_path
- weight
- engine
- sequence
- grouping
- baseline_profile
- budget_profile
- split
- active_metrics
- bounds_source
- project_root
- runtime_dir

## P0-4 为每次运行生成 `run_manifest.json`

### 理由

这是论文方法复现、负优化判定与结果追责的基础设施。内部仍可继续使用 env/cwd 做 handoff，但 manifest 必须成为外部真相源。

## P0-5 为每次运行生成 `contract_report.json`

### 目标

显式记录：

- 缺失观测
- 缺失指标
- 被置零的 observation
- 被裁剪的组
- 实际参与目标函数的变量
- 回退到默认权重或默认指标的情况

### 当前状态

本项已完成第二轮落地：

- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py) 与 [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py) 已稳定复用共享 payload builder 输出 `contract_report.json`
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 已补入 split、active groups、fallback metrics、active counts、`dropped_groups`、`weight_fallbacks`、`zero_weight_observations` 与 resolved output context
- [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已把这些细字段写入 protocol artifacts 索引，并在主报告 overview/panel 中聚合
- [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 已新增 manifest/contract/report 聚合断言，防止协议回退
- [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已继续产出 `main_matrix_protocol_dimension_summary.tsv`、`main_matrix_protocol_nested_dimension_summary.tsv`、`main_matrix_protocol_hotspot_summary.tsv`、`main_matrix_protocol_reason_summary.tsv` 与 `main_matrix_quality_gate.tsv`

### 理由

这样才能严格区分：

- 方法失败
- 数据契约不完整
- 运行口径退化

## P0-6 建立作物注册表 `crop_registry`

### 目标

把当前分散在配置文件、默认值与回退逻辑中的作物知识统一成正式注册表。

### 注册表至少应包含

- `crop_family`
- `aliases`
- `required_metrics`
- `optional_metrics`
- `yield_metric`
- `timeseries_metrics`
- `grouping_profiles`
- `phase_templates`
- `bounds_source`
- `genotype_locator`

### 理由

这是从“五作物可用”走向“DSSAT 全作物可扩展”的关键一步。

## P0-7 将研究层纳入质量门禁

### 当前状态

本项已完成首轮落地，当前已经具备：

- [pyproject.toml](file:///d:/Wheat/Wheat/mvp_pest_mgda/pyproject.toml#L1-L11) 同时覆盖 `src` 与 `..\autoresearch_sandbox`
- [lint.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/lint.ps1) 同时检查 `src` 与 `..\autoresearch_sandbox`
- [typecheck.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/typecheck.ps1) 同时检查 `src` 与 `..\autoresearch_sandbox`
- [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 已增加门禁目标断言
- [test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py) 与现有 runtime/layout 契约继续保障研究层目录规范

### 本轮收敛结果

- `ruff check autoresearch_sandbox` 已纳入默认脚本
- `mypy autoresearch_sandbox` 已纳入默认脚本
- 已补齐“门禁范围配置”与“研究层路径契约”的 smoke tests
- `eval_v2.py`、[eval_v3.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval_v3.py)、[eval_baseline.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval_baseline.py) 的存量 lint 问题已一并清理

### 理由

研究层已承担大量结果编排与论文产物逻辑，这部分门禁缺口已经是当前问题，而不是中长期理想态。

### 后续子任务

- 把现有 `main_matrix_quality_gate.tsv` 从“报告产物”进一步上收为科研批量运行的 stop/go 规则
- 视论文写作需要，冻结 `main_matrix_protocol_paper_table.tsv`、`main_matrix_paper_main_table.tsv`、`main_matrix_paper_appendix_table.tsv` 的字段口径，而不是继续无上限扩字段
- 仅在进入多人协作或新实验入口增多时，再考虑把 CLI 与 research orchestrator 做更严格的流程固化

## 3. P1：主矩阵完成后应立即推进

## P1-1 收口共享内核边界

### 目标

把当前仍散落在顶层 `src` 的基础能力逐步收拢进 `calibration_core`：

- [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)
- [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py)
- [case_runtime.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/case_runtime.py)
- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py)

### 理由

如果共享内核边界不继续收口，研究层就始终是在“调用一个仍在迁移中的工程内部实现”。这项工作方向正确，但从落地风险看，应排在显式协议和研究层门禁之后。

### 建议顺序

1. 先迁 `observations.py`
2. 再迁 `case_runtime.py`
3. 再拆 `dssat_io.py`
4. 最后让 `run_model.py` 与 `build_pest_setup.py` 更聚焦于编排壳层，而不是承载过多农学知识

## P1-2 把主矩阵与增强层拆成两个正式 profile

### 目标

显式区分：

- `matrix_profile`
- `robustness_profile`

### 理由

你的路线图明确要求 `Budget` 不属于主轴。这里更准确地说，是为了降低报告与论文整理阶段的混写风险，而不是在指责当前显式建模做法本身有错。

## P1-3 补齐多作物农学语义 golden tests

### 建议测试对象

- `.CUL` 回写格式
- `FileX` treatment 解析
- 各 crop 的主指标识别
- `G3` 分组映射
- `S2` 阶段模板裁剪

### 理由

当前测试已经覆盖 registry 只读 API、snapshot contract 与稳定字段 golden subset，但尚未充分覆盖“多作物农学语义”。

## P1-4 统一 CLI 入口

### 建议入口

- `run-matrix`
- `run-robustness`
- `build-report`
- `validate-contract`

### 理由

这会显著降低论文复现和团队协作成本。

## 4. P2：中期优化

## P2-1 让 `public_api` 进化为正式服务接口

### 当前状态

[public_api.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/public_api.py#L21-L32) 仍以模块转发为主。

### 目标

逐步过渡为领域服务：

- `load_case_runtime_service()`
- `load_pest_workflow_service()`
- `load_result_export_service()`

## P2-2 建立论文导出 profile

### 目标

为论文专门定义稳定导出：

- `paper_main_table`
- `paper_appendix_table`
- `figure_ready`
- `robustness_appendix`

### 理由

这样研究层就不用在大型脚本中临时拼接导出逻辑。

## P2-3 给兼容包装器制定弃用节奏

### 当前问题

包装器非常有用，但如果无限期保留，会导致边界模糊。

### 建议

采用三步策略：

1. 文档标注“新代码请只依赖 core”
2. 测试只保障外部兼容，不再向包装器加新逻辑
3. 当研究层完成迁移后再考虑正式弃用

## 5. 面向论文方法学的特别建议

## 5.1 主矩阵结果必须严格可追溯到四轴

每一行主结果都应能唯一回答：

- W 是什么
- O 是什么
- S 是什么
- G 是什么
- B0 对照是什么
- 是否启用了增强层

如果不能从单行结果直接回答这些问题，论文写作阶段会很痛苦。

## 5.2 `S2/S3` 必须显式绑定作物阶段模板

不能再让 `S2` 仅靠参数名约定存在。必须能从配置中直接读出：

- 阶段 1 包含哪些参数
- 阶段 2 包含哪些参数
- 阶段 3 包含哪些参数
- 缺失组如何裁剪

## 5.3 `W8` 的工程地位与论文地位要同时固化

建议在代码层就固定 `W8` 标签为：

- `reference_engineering_baseline`

不要让其在后续实现中被误写成“统计最优默认方案”。

## 6. 推荐实施节奏

## 第 1 阶段：协议与门禁闭环

已完成：

- `run_manifest`
- `contract_report`
- 研究层质量门禁
- 主矩阵 report rebuild 端到端 smoke
- `.venv` 固定执行环境

## 第 2 阶段：多作物语义闭环

已完成最小闭环：

- `crop_registry`
- `observations` / `case_runtime` / `dssat_io` 的 registry 接入
- registry 驱动的 phase/grouping profile
- `.CUL` / `FileX` / bounds 关键语义门禁

## 第 3 阶段：进入科研运行前的收尾

现在优先做：

- 冻结 paper-facing protocol / paper table 口径
- 增加可选 live DSSAT 安装 acceptance smoke
- 把 quality gate 绑定到批量实验 stop/go

## 第 4 阶段：长期平台化

最后再做：

- `public_api` 服务化
- 更深的 core 边界迁移
- 更广的全作物 trial discovery

## 7. 最终结论

这次重构已经把项目从“脚本集合”推进到了“平台雏形”。下一步最重要的不是继续堆优化器，而是让平台具备：

- 清晰边界
- 显式协议
- 多作物正式抽象
- 论文级可复核性

当前版本已经足以继续推进 Wheat 主线和多作物雏形；只要按上述节奏补齐这些能力，项目就不仅能更稳地支撑当前论文的方法学研究，还会自然具备向 DSSAT 全作物遗传参数率定扩展的能力。

## 8. 面向尽快进入科研实践的最短收尾清单

如果目标是“尽快结束平台型开发、进入可持续科研运行”，建议把剩余工作收缩为三条：

1. 冻结 `main_matrix_protocol_paper_table.tsv`、`main_matrix_paper_main_table.tsv`、`main_matrix_paper_appendix_table.tsv` 等 paper-facing 产物的字段口径，避免进入科研实践后仍频繁改 schema
2. 补一条可选 live Wheat / DSSAT acceptance smoke，验证真实 `C:\DSSAT48\Wheat` 安装、路径解析与参考观测文件在本机环境下可用
3. 把 `main_matrix_quality_gate.tsv` 明确绑定到批量实验的 stop/go 规则与最小人工复核动作，作为真正的科研运行门禁

除上述三条外，其余 `public_api` 服务化、深层 core 迁移、长期平台化能力都应降级为“不阻塞科研实践”的后续演化项。
