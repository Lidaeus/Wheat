# DSSAT-PEST 重构后项目 Code Review 总览

## 1. 审查范围

本轮审查同时对照以下研究与重构文档：

- [01_Research_Roadmap.md](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/Research_Artifacts/01_Research_Roadmap.md)
- [02_Experimental_Design_Details.md](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/Research_Artifacts/02_Experimental_Design_Details.md)
- [04_Discussion_History.md](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/Research_Artifacts/04_Discussion_History.md)
- [01_Paper_Outline.md](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/Research_Artifacts/Drafts/01_Paper_Outline.md#L19-L32)
- [05_Refactor_Blueprint.md](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/Research_Artifacts/05_Refactor_Blueprint.md)

重点审查对象包括：

- `mvp_pest_mgda` 的共享能力、工程执行链路与配置体系
- `autoresearch_sandbox` 与工程层的耦合方式
- 当前实现对 `W × O × S × G` 方法学主线的支撑程度
- 未来扩展到 DSSAT 全作物遗传参数率定的可演化性

## 2. 总体判断

结论：**本次重构方向正确，且已经明显优于重构前状态，但还没有完全达到“面向论文主矩阵 + 多作物长期演化”的稳定形态。**

当前状态更准确地说是：

- 已经形成了一个**可工作的三层雏形**
- 已经有了较清晰的**共享接口与结果契约**
- 但共享内核的边界仍然**没有完全收口**
- 多作物支持已经从“单作物硬编码”进化为“配置驱动雏形”，但距离“长期支持 DSSAT 所有作物”仍有明显工程缺口

如果按照当前阶段目标来评估，这个版本已经足以支持：

- Wheat 主线继续推进与实测贴合优化
- 五作物框架的进一步收敛
- 主矩阵 `W × O × S × G` 的中短期实验

但如果要支撑论文中强调的：

- 方法学可解释性
- 跨作物稳健性
- 预算/初值/局部最优风险的稳健性分析
- 后续扩展到 DSSAT 全作物

则还需要再做一次**“边界硬化 + 多作物抽象 + 可复核工作流”导向的二次重构**。

## 3. 主要优点

### 3.1 分层方向基本正确

- 共享入口已经通过 [public_api.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/public_api.py#L9-L32) 建立
- `src/calibration_core` 已经承载了部分共享内核职责，例如 [pest_builder.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_builder.py#L174-L225)、[pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py#L169-L199)、[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L45-L123)
- 顶层兼容包装器保留了旧入口，例如 [src/pest_builder.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/pest_builder.py#L1-L38)、[src/pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/pest_runner.py#L1-L13)

### 3.2 共享结果契约明显增强

- `result_schema` 已经把实验输出、导出字段、矩阵汇总视图等统一下来，适合作为论文与报表接口层
- 这对于论文中“方法框架贡献 + 工程实现贡献”的叙述是加分项

### 3.3 运行链路更接近可复用基础设施

- `run_model.py` 已能在单一入口中完成 case 准备、参数映射、运行时文件修补、输出抽取 [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py#L405-L521)
- `build_pest_setup.py` 已把 PEST 构建、组权重、split 过滤、激活指标等集中在一处 [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L963-L1029)

### 3.4 与研究主矩阵已有实质对应

- `autoresearch_sandbox` 已显式表达 `weight / engine / budget / sequence / grouping` 这些研究维度 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L509-L605)
- 这使研究矩阵与工程结构之间第一次形成了较清楚的映射关系

## 4. 核心问题

### 4.1 共享内核边界仍未完全收口

虽然 `calibration_core` 已存在，但以下关键模块仍留在顶层 `src`：

- [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)
- [case_runtime.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/case_runtime.py)
- [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py)
- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py)

这意味着当前并不是“研究层只依赖共享内核”，而是“研究层通过公共入口间接使用一组仍在迁移中的模块集合”。

### 4.2 多作物抽象尚未彻底替代 Wheat 优先思维

项目已经不再是纯单作物，但仍保留多个“以 Wheat/当前五作物为中心”的实现习惯，例如：

- `_build_project_config` 直接写死默认观测组与指标 [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L840-L888)
- `DEFAULT_OBSERVATION_GROUPS` 与 `SUMMARY_AFILE_COLUMN_MAP` 仍是固定表 [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L28-L43)
- `resolve_primary_metric_codes` 仍以 `yield_var + laix_var` 为主要口径 [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py#L107-L128)

这对当前论文主线够用，但对“未来支持 DSSAT 所有作物”的目标还不够。

### 4.3 工作流契约过度依赖未落盘的环境变量与 cwd

当前工程层和研究层之间的大量接口是通过环境变量完成的，例如：

- `PARAMS_PATH`
- `DSSAT_TRTS`
- `PROJECT_CONFIG`
- `CUL_PATH`
- `DSSAT_EXTRA_SUMMARY_VARS`
- `PEST_OBS_WEIGHT_MODE`
- `USE_MGDA_ALPHAS`

在 Windows + DSSAT + PEST 的执行链里，用环境变量做 subprocess handoff 本身并不是错误；真正的问题是这些协议缺少显式落盘，因此对可复核性、审计性和论文方法复现不够友好。

### 4.4 研究主矩阵与稳健性增强层仍有混杂风险

研究路线图要求：

- `W × O × S × G` 是主实验矩阵
- `Budget / Initialization / Multi-start / Hybrid Search` 属于增强层

但当前 `auto_evolve.py` 中 `budget` 仍与主矩阵并列进入很多表结构与组合计划 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L107-L171) [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L509-L605)。

这不是功能错误，但会增加论文分析时“主结论”和“稳健性附加结论”被混写的风险。

## 5. 优先级结论

### P0：建议优先修正

1. 建立显式 `run_manifest`，作为 env/cwd handoff 之上的真相源
2. 建立 `contract_report`，显式记录缺失、降级、裁剪与回退原因
3. 建立作物注册表与阶段模板体系
4. 把 `autoresearch_sandbox` 纳入质量检查范围
5. 分阶段收口共享内核边界

### P1：应在下一轮推进

1. 补齐多作物 golden tests
2. 将主矩阵与增强层输出分流，避免报告阶段混写
3. 为论文导出建立更稳定的 report profile

### P2：中期优化

1. 将旧兼容包装器转为正式弃用路线
2. 建立统一 CLI
3. 建立论文导出专用 schema/profile

## 6. 文档导航

- [01_Architecture_and_Research_Fit_Review.md](file:///d:/Wheat/Wheat/docs_test/01_Architecture_and_Research_Fit_Review.md)
- [02_Workflow_API_and_Reproducibility_Review.md](file:///d:/Wheat/Wheat/docs_test/02_Workflow_API_and_Reproducibility_Review.md)
- [03_Implementation_Details_and_Multicrop_Review.md](file:///d:/Wheat/Wheat/docs_test/03_Implementation_Details_and_Multicrop_Review.md)
- [04_Actionable_Refactor_Backlog.md](file:///d:/Wheat/Wheat/docs_test/04_Actionable_Refactor_Backlog.md)

## 7. 后续开发文档

- [05_Refactor_Documentation_Plan.md](file:///d:/Wheat/Wheat/docs_test/05_Refactor_Documentation_Plan.md)
- [06_Explicit_Protocol_Spec.md](file:///d:/Wheat/Wheat/docs_test/06_Explicit_Protocol_Spec.md)
- [07_Crop_Registry_Design_Spec.md](file:///d:/Wheat/Wheat/docs_test/07_Crop_Registry_Design_Spec.md)
- [08_Boundary_and_Quality_Gate_Roadmap.md](file:///d:/Wheat/Wheat/docs_test/08_Boundary_and_Quality_Gate_Roadmap.md)
