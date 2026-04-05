# 下一阶段重构开发文档规划

## 1. 规划目标

基于本轮 code review 以及原作者反馈，下一阶段重构不宜一开始就做大规模模块迁移；更稳妥的顺序是先补**显式协议**，再补**多作物正式抽象**，最后再做**边界收口**。

因此，开发文档也应按同样顺序组织，优先服务于：

1. 论文级可复核性
2. 当前 Wheat 主线与多作物雏形的稳定推进
3. 中期架构演化，而不是一次性追求理想态

## 1.1 本轮进度更新

截至当前版本，文档排序所依赖的工程状态已经继续前进，关键变化包括：

1. [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py) 与 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 的研究层路径协议已基本稳定在 `runs/runtime`、`runs/parallel_workers` 与 `artifacts`
2. `autoresearch_sandbox` 已正式纳入 [pyproject.toml](file:///d:/Wheat/Wheat/mvp_pest_mgda/pyproject.toml)、[lint.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/lint.ps1)、[typecheck.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/typecheck.ps1) 与相关测试
3. [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)、[build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 与 [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py) 已落地共享协议对象，并正式写出 `run_manifest.json` / `contract_report.json`
4. [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 已开始从 [crop_registry.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/crop_registry.py) 读取默认观测组与 summary A-file 列映射，`crop_registry` 不再只停留在 `observations.py` / [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)
5. [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已把 protocol artifacts 索引扩展到 `dropped_groups`、`weight_fallbacks`、`zero_weight_observations`，并在主报告 overview/panel、dimension summary、nested dimension summary、hotspot summary 与 quality gate 中聚合这些协议细节
6. [test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py) 已补齐 `crop_registry` 的只读 API、snapshot contract 与多作物 golden subset 断言
7. [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 已补主矩阵 report rebuild 的端到端 smoke，覆盖 `runtime protocol inputs -> artifacts -> quality gate -> report`
8. [lint.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/lint.ps1) 与 [typecheck.ps1](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/typecheck.ps1) 已固定使用项目 `.venv`，并由测试防止脚本退回系统 Python
9. `.CUL` 固定宽度回写、`FileX` treatment/cultivar 解析、registry 驱动的参数顺序与多作物 `FileX` / cultivar / bounds 对齐契约，已经进入稳定门禁

这意味着下一轮文档不再需要把“研究层是否进入门禁”“协议是否要先落盘”“registry 是否已有稳定只读契约”“主矩阵 smoke 是否存在”或“.venv 是否已固定”写成开放问题，而应把它们视为已完成前置项，并把重点前移到 paper-facing 口径冻结、live DSSAT acceptance，以及把现有 protocol/quality gate 真正收口为科研运行门禁。

## 2. 文档分层

建议把下一阶段文档分成三层：

### A. 立即落地文档

用于直接指导下一轮实现，优先级最高：

- [06_Explicit_Protocol_Spec.md](file:///d:/Wheat/Wheat/docs_test/06_Explicit_Protocol_Spec.md)
- [07_Crop_Registry_Design_Spec.md](file:///d:/Wheat/Wheat/docs_test/07_Crop_Registry_Design_Spec.md)
- [08_Boundary_and_Quality_Gate_Roadmap.md](file:///d:/Wheat/Wheat/docs_test/08_Boundary_and_Quality_Gate_Roadmap.md)

### B. 实施追踪文档

用于把设计转成可执行任务，建议在真正开工时补齐：

- `implementation_checklist.md`
- `migration_status.tsv`
- `contract_examples/`

这一层更像工程跟踪板，不需要现在一次性写完，但需要预留结构。

### C. 验收文档

用于证明本轮重构有效：

- `protocol_acceptance.md`
- `crop_registry_acceptance.md`
- `research_gate_acceptance.md`

这一层应在代码落地后补充。

## 3. 当前建议先写的三份文档

### 3.1 显式协议规格

核心目的：让 [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py#L405-L521)、[pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py#L201-L237)、[build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L956-L1029) 之间的运行协议从“靠 env/cwd 传递”升级为“有 manifest/contract report 统摄的显式协议”。

### 3.2 作物注册表设计规格

核心目的：把当前分散在 [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L501-L553)、[dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L840-L888)、[observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py#L98-L128)、[build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L28-L43) 的 crop-specific 知识收口为正式数据模型。

### 3.3 边界与门禁路线图

核心目的：明确哪些属于当前阻塞问题，哪些属于中期架构演化，并给出不破坏现有实验能力的迁移顺序。

## 4. 推荐执行顺序

### 第一批：马上驱动收尾

1. `06_Explicit_Protocol_Spec.md` 中冻结 protocol TSV / paper table 的字段口径，并明确科研写作期不再随意扩 schema
2. `08_Boundary_and_Quality_Gate_Roadmap.md` 中把 `main_matrix_quality_gate.tsv` 升级为批量实验的 stop/go 验收规则
3. `08_Boundary_and_Quality_Gate_Roadmap.md` 中补一条可选 live Wheat / DSSAT acceptance smoke，用来验证真实安装环境

### 第二批：在科研启动后按需推进

1. 把 registry 的下一轮约束继续落到真实实验输入校验，而不是重复扩 profile 字段快照
2. 仅在新增作物或新增模板时扩展 `.CUL` / `FileX` / bounds 语义门禁
3. 将主矩阵与 robustness/profile 的运行边界进一步固定，减少报告与论文口径混写

### 第三批：等 Phase 1/2 稳定后再进入

1. `public_api` 服务化
2. 更深的 core 边界迁移
3. 更广的全作物发现机制

## 5. 文档编写原则

下一阶段所有开发文档建议统一遵循以下原则：

- 先写当前目标，再写长期目标，避免把理想态误写成当前缺陷
- 明确区分 `must now`、`should next`、`could later`
- 所有协议文档都要回答“写入时机、落盘位置、上游数据源、下游消费者”
- 所有数据模型文档都要回答“最小必需字段、默认策略、兼容旧逻辑的方法”
- 所有迁移文档都要回答“先做什么不破坏现有结果”

## 6. 本文件结论

下一阶段的开发文档，不应再从“大重构蓝图”开始，而应聚焦**最短科研落地路径**。基于当前实现，研究层门禁、显式协议、protocol 维度切片、主矩阵端到端 smoke、多作物农学语义门禁以及 `.venv` 固定执行环境，都已经从计划项转为既成事实；因此本阶段文档的真正主轴，已经前移为“冻结 paper-facing 口径、把 quality gate 变成科研 stop/go、补 live DSSAT acceptance，然后再把深层边界迁移降级为中长期演化”。
