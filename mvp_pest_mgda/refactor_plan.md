# Refactor Plan

## R2-3 Compare Orchestration

- 将 `compare_three.py` 继续收缩为入口编排层：模式解析、共享 selector、共享 scenario runner、结果汇总写出。
- 将“场景目录创建 + `params.dat` 物化 + 单场景执行”统一下沉到 `pest_runner.run_compare_scenarios(...)`。
- 保持单场景执行器可注入，使 `compare_three.py`、后续 tournament/progress 入口以及其他 PEST 驱动入口都能复用同一循环框架。

## Parameter Bounds Architecture

### Current State

- 当前项目配置以 `params.bounds` 作为 PEST 建模入口，`build_pest_setup.py` 会直接消费该结构并写入 `parlbnd/parubnd`。
- `dssat_io.py` 在自动生成项目配置时，对缺省参数仅按初值生成经验边界：非零值默认 `0.7x ~ 1.3x`，零值默认 `-0.1 ~ 0.1`。
- 当前还没有“官方上下界”和“用户自定义上下界”的统一优先级解析层，也没有率定前的参数边界总览输出。

### Target Priority Rules

- 最高优先级：用户自定义上下界。
- 次优先级：作物/参数的官方上下界。
- 兜底策略：若不存在官方上下界，则默认使用相对浮动边界。
- 默认浮动方案：
  - 标准默认：`±30%`
  - 可选紧边界：`±15%`
- 需要对负值、零值、上下界倒置、单位差异做统一归一和校验。

### Proposed Data Model

- 新增共享 bounds resolver，输出统一结构：
  - `name`
  - `source`，取值为 `custom`、`official`、`fallback_30`、`fallback_15`
  - `lower`
  - `upper`
  - `initial`
  - `group`
  - `crop`
- 官方上下界建议以独立数据源承载，避免与项目实例配置混写：
  - 可优先采用 `config/parameter_bounds/*.json`
  - 按 crop family 或 cultivar family 分层
- 项目配置保留用户覆写入口，例如：
  - `params.bounds`
  - `params.bounds_mode`
  - `params.official_bounds_source`

## Preflight Visibility

- 在正式率定前，提供参数边界预览入口，按来源分类展示全部参与率定参数：
  - 用户自定义
  - 官方上下界
  - 经验回退边界
- 预览输出至少支持：
  - 终端表格
  - CSV 落盘
- 建议新增共享能力：
  - `resolve_parameter_bounds(...)`
  - `build_parameter_bounds_report(...)`
  - `write_parameter_bounds_report(...)`
- 该阶段应在 `build_pest_setup.py` 和优化器实际启动前执行，作为 preflight gate。

## Posterior Distribution Support

- 对支持后验分析的优化器，统一定义 posterior artifacts 输出协议。
- `pestpp-ies` 已有可利用的参数集合输出基础，例如 `*.par.csv`，可直接作为后验样本源。
- 目标产物：
  - 单参数后验分布图
  - 参数 prior/posterior 对比图
  - 关键参数联合分布或相关性热图
  - 后验统计摘要表
- 建议新增共享分析模块，职责包括：
  - 读取 ensemble / posterior 样本
  - 生成 tidy dataframe
  - 输出 PNG 与 CSV
- 非样本型优化器应优雅跳过，不阻断主流程。

## Delivery Phases

### Phase 1

- 完成 compare orchestration 下沉。
- 引入共享 bounds resolver 接口，不改动现有率定逻辑。
- 在现有 `params.bounds` 基础上接入优先级解析骨架。

### Phase 2

- 接入官方上下界数据源。
- 支持 `±30%` 与 `±15%` fallback mode。
- 增加参数边界 preflight 报告。

### Phase 3

- 为 `pestpp-ies` 增加 posterior 分布图与统计摘要输出。
- 为其他支持样本输出的优化器复用同一 posterior pipeline。

### Phase 4

- 将 bounds resolver 与 posterior reporting 接入 MGDA / compare / batch 入口，形成统一校准前检查和校准后诊断闭环。
