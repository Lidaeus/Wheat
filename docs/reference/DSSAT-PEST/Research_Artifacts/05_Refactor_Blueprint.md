# 重构蓝图：DSSAT 率定基础设施与研究沙盒分层方案

## 1. 文档目的
本蓝图用于把当前仓库中的两个相关项目：

- `d:\Wheat\Wheat\mvp_pest_mgda`
- `d:\Wheat\Wheat\autoresearch_sandbox`

从“相互引用、路径耦合、职责混杂”的状态，逐步重构为一个更适合论文主线与长期研究演化的三层结构：

1. **共享内核层**：负责 DSSAT / PEST / 文件改写 / 结果抽取等稳定能力
2. **工程执行层**：负责稳定、可复核、可批量运行的标准率定工作流
3. **研究探索层**：负责权重策略、搜索协议、预算敏感性与混合优化等探索

本蓝图既是架构规划文件，也是后续重构过程的追踪文件。

## 2. 重构动因
当前研究主线已经明确为：

- 主实验矩阵：`W × O × S × G`
- 外部基线：`B0`
- 增强层：`Budget / Initialization / Multi-start / Hybrid Search`

这意味着工程结构也必须与研究结构一致：

- **基础协议能力** 不能和 **探索性策略** 混在一起
- **可复用执行链路** 不能依赖单个实验脚本的内部细节
- **研究增强层** 不能污染主矩阵结论所依赖的稳定实现

因此，本次重构不是单纯“整理目录”，而是为了支撑论文中的三类贡献：

1. 可复用流程贡献
2. 稳健性证据贡献
3. 主矩阵与增强层严格分离的工程对应物

## 3. 当前问题诊断

### 3.1 `mvp_pest_mgda` 的优点
- 已具备较成熟的 DSSAT 运行能力
- 已具备固定宽度文件安全改写能力
- 已具备 `pestpp-glm` / `pestpp-ies` / PST 构建相关逻辑
- 已具备多作物配置雏形
- 更接近“稳定执行基础设施”

### 3.2 `mvp_pest_mgda` 的问题
- 基础设施与具体实验脚本仍混在一起
- 仍包含应用级流程编排逻辑
- 一些模块属于算法增强层，不应与运行时基础层并列
- 输出层偏向 CSV 聚合，尚未形成稳定报告接口

### 3.3 `autoresearch_sandbox` 的优点
- 适合快速做损失函数、权重、预算与策略探索
- 适合并行 worker 式实验
- 适合保留失败实验与研究日志

### 3.4 `autoresearch_sandbox` 的问题
- 对旧路径和 `mvp_pest_mgda` 内部脚本存在硬编码耦合
- 当前结构明显偏 Wheat 单作物
- 源码、运行产物、实验日志、临时文件混放
- worker 通过复制脚本运行，长期维护成本高
- 研究层直接依赖工程层私有文件路径，不利于演进

## 4. 目标架构
目标不是“两个项目简单分工”，而是“三层架构解耦”。

### 4.1 目标分层

#### A. 共享内核层
建议命名：

- `d:\Wheat\Wheat\calibration_core`
  或
- `d:\Wheat\Wheat\mvp_pest_mgda\src\calibration_core`

推荐优先采用第二种过渡方式：**先在 `mvp_pest_mgda` 内部抽象共享内核，再决定是否独立为新包**。

共享内核负责：

- DSSAT case 定位与运行
- `.CUL` / `.X` / `.WTH` / `.SOL` 固定宽度安全改写
- 观测读取与统一结果抽取
- PST 构建
- `pestpp-glm` / `pestpp-ies` 进程调用
- 分组权重与 WLS 契约
- 通用配置解析
- 标准化结果对象与 TSV/CSV 导出接口

共享内核不负责：

- 某一篇研究当前测试中的权重公式发明
- AutoResearch 候选策略生成
- 论文图表挑选逻辑
- 单次实验日志写作习惯

#### B. 工程执行层
保留项目：

- `d:\Wheat\Wheat\mvp_pest_mgda`

职责：

- 稳定执行 `B0`
- 运行标准单目标协议与 PEST 家族工作流
- 运行多作物批量实验
- 导出主矩阵结果表
- 为论文图表提供规范化数据产物
- 维护项目级 lint / typecheck / CLI / PowerShell 入口

它应依赖共享内核，而不是自己重复实现底层运行时。

#### C. 研究探索层
保留项目：

- `d:\Wheat\Wheat\autoresearch_sandbox`

职责：

- 探索 `W` 维新候选
- 探索 `Budget` 敏感性
- 探索 `Initialization` / `Multi-start` / `Hybrid Search`
- 实现 AutoResearch 或 AI scientist 风格的候选生成与筛查
- 产生探索性日志与候选池

它应通过共享内核暴露的稳定 API / CLI 调用 DSSAT 与 PEST，而不应再直接引用 `mvp_pest_mgda\src\*.py` 的私有实现路径。

## 5. 目录蓝图
建议最终演化为：

```text
d:\Wheat\Wheat\
├─ mvp_pest_mgda\
│  ├─ config\
│  ├─ scripts\
│  ├─ src\
│  │  ├─ calibration_core\
│  │  │  ├─ config.py
│  │  │  ├─ case_runtime.py
│  │  │  ├─ fixed_width.py
│  │  │  ├─ observations.py
│  │  │  ├─ pest_builder.py
│  │  │  ├─ pest_runner.py
│  │  │  ├─ result_schema.py
│  │  │  └─ reporting.py
│  │  ├─ app\
│  │  │  ├─ run_model.py
│  │  │  ├─ build_pest_setup.py
│  │  │  ├─ compare_three.py
│  │  │  └─ aggregate_iters.py
│  │  └─ algorithms\
│  │     └─ mgda_update.py
│  └─ tests\
│     ├─ test_fixed_width.py
│     ├─ test_config_resolution.py
│     ├─ test_grouping_contract.py
│     ├─ test_pst_build_contract.py
│     └─ test_result_schema.py
│
└─ autoresearch_sandbox\
   ├─ configs\
   ├─ strategies\
   ├─ runs\
   ├─ artifacts\
   ├─ auto_evolve.py
   ├─ eval.py
   └─ tests\
      ├─ test_strategy_contract.py
      └─ test_eval_plan_translation.py
```

## 6. 文件迁移建议

### 6.1 优先下沉到共享内核的能力

#### 来自 `run_model.py`
- DSSAT case 选择逻辑
- DSSAT 执行逻辑
- `.INP/.INH` 路径修补逻辑
- 固定宽度块更新逻辑
- `.CUL` 参数回写逻辑

#### 来自 `build_pest_setup.py`
- 观测分组定义解析
- 分组方差估计
- 训练/验证 split 解析
- PST 观察值与权重构造

#### 来自 `dssat_io.py`
- 项目配置装载
- 参数映射
- 试验号提取
- 结果表头解析
- 多作物 project config 生成

### 6.2 保留在工程执行层的内容
- `run_mvp.ps1`
- `run_pure_pest.ps1`
- 多作物项目配置文件
- 工程级汇总脚本
- 输出整形与论文数据导出脚本

### 6.3 保留在研究探索层的内容
- `strategy.py`
- `auto_evolve.py`
- 候选生成器
- 预算敏感性矩阵
- 初值敏感性实验
- 实验日志与探索性结果

## 7. 接口蓝图
为避免再次形成跨项目私有路径依赖，重构后只允许以下两种调用方式：

### 7.1 Python API
示例目标：

```python
from calibration_core.case_runtime import run_dssat_case
from calibration_core.pest_builder import build_pst
from calibration_core.pest_runner import run_pestpp_glm, run_pestpp_ies
```

### 7.2 CLI 契约
示例目标：

```powershell
python -m calibration_core.run_model --project path\to\project.json
python -m calibration_core.build_pst --project path\to\project.json
python -m calibration_core.run_pest --engine glm --workdir path\to\workspace
```

原则：

- sandbox 只调用公共 API / CLI
- 不再直接指向 `mvp_pest_mgda\src\run_model.py`
- 不再假设工程层内部目录结构稳定不变

## 8. 配置蓝图

### 8.1 配置分层
建议把配置分成三类：

1. **运行时配置**
   - DSSAT 根目录
   - case 目录
   - 可执行文件路径

2. **实验协议配置**
   - `W / O / S / G`
   - Budget
   - Initialization policy
   - Split

3. **研究配置**
   - 搜索空间
   - 候选生成规则
   - 演化轮数
   - worker 数

### 8.2 配置原则
- 统一使用仓库内相对路径或可覆盖的绝对路径
- 所有默认路径都以当前仓库为基准，而不是旧 `C:\DSSAT48\Wheat` 路径
- 保留 `DSSAT_ROOT` / `PROJECT_CONFIG` 等环境变量覆盖能力
- 多作物配置与单作物探索配置共用同一 schema

## 9. 测试驱动重构策略
本次重构推荐采用 **Characterization Test + Contract Test + Incremental Refactor**，而不是先搬代码再补测试。

### 9.1 核心思路
先把当前行为锁定，再移动实现。

顺序为：

1. 为当前关键行为补 characterization tests
2. 为未来公共接口补 contract tests
3. 在测试保护下迁移代码
4. 每迁移一批功能就跑 lint / typecheck / tests

### 9.2 第一批必须先补的测试

#### 固定宽度文件测试
- 给定样例 `.CUL` 行，参数更新后列宽不变
- 给定样例 `.X` 区块，更新后总行长不变
- 日期/浮点/整数格式均保持 DSSAT 可接受格式

#### 配置解析测试
- 环境变量覆盖优先级正确
- 相对路径与绝对路径都可正确解析
- 多作物配置中的参数映射正确落地

#### 分组与权重契约测试
- `G1` 与 `G3` 的观测映射符合当前实现
- `W8` 的 `1 / max(y_obs in group g)` 行为不变
- `S3` 只能在 `G3` 下执行的约束不被破坏

#### 结果 schema 测试
- 单次运行结果字段齐全
- Train / Valid / All 三套指标结构稳定
- 负优化判定与 baseline 字段保留

### 9.3 第二批测试
- PST 构建契约测试
- `pestpp-ies` 配置拼装测试
- sandbox 策略函数接口测试
- worker 工作目录规划测试

## 10. 分阶段落地计划
本重构不采用大爆炸重写，而采用 5 个阶段逐步推进。

### Phase R0：冻结现状与建立保护网
目标：

- 先不搬代码
- 先补测试
- 先识别当前必须保持不变的行为

交付物：

- `tests/test_fixed_width.py`
- `tests/test_config_resolution.py`
- `tests/test_grouping_contract.py`
- `tests/test_result_schema.py`

完成标准：

- 现有关键行为被测试锁定
- 之后的迁移可以以“测试是否仍通过”为依据

### Phase R1：抽取共享内核最小闭环
目标：

- 从 `run_model.py` / `build_pest_setup.py` / `dssat_io.py` 中抽出最稳定能力
- 不改变对外行为

交付物：

- `src/calibration_core/config.py`
- `src/calibration_core/fixed_width.py`
- `src/calibration_core/case_runtime.py`
- `src/calibration_core/observations.py`

完成标准：

- 原 `run_model.py` 变成薄封装
- 核心运行逻辑进入共享模块

### Phase R2：抽取 PEST 契约层
目标：

- 把 PST 构建与 PEST 运行封装成标准接口
- 保证 `glm / ies` 都通过同一层进入

交付物：

- `src/calibration_core/pest_builder.py`
- `src/calibration_core/pest_runner.py`
- `src/calibration_core/result_schema.py`

完成标准：

- sandbox 不再需要直接知道 PST 细节
- 工程层和研究层共享同一 PEST 契约

### Phase R3：让 sandbox 改用公共接口
目标：

- 切断 `autoresearch_sandbox` 对 mvp 私有脚本路径的依赖
- 切断旧硬编码目录依赖

交付物：

- `autoresearch_sandbox/eval.py` 改用共享 API / CLI
- `autoresearch_sandbox/auto_evolve.py` 改用统一 workspace 规划
- 新增 `runs/` 与 `artifacts/` 目录约定

完成标准：

- sandbox 可独立运行
- sandbox 只依赖共享内核，不依赖工程层内部文件路径

### Phase R4：整理由工程层负责标准报告
目标：

- 让主矩阵实验结果导出形成稳定产物契约
- 把论文需要的数据输出从“脚本副产物”变为“正式接口”

交付物：

- 统一 long/wide TSV schema
- 主矩阵结果导出脚本
- 图表就绪数据导出脚本

完成标准：

- Phase 0 / Phase 1 可执行批次能稳定输出可比较表
- 论文结果章的数据依赖不再绑定某次临时实验脚本

## 11. 重构过程追踪表
后续执行时，按下表更新状态。

| ID | 任务 | 层级 | 状态 | 验收标准 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R0-1 | 固定宽度更新行为测试 | 共享内核 | 已完成 | `.CUL/.X` 行宽不变 | `tests/test_fixed_width.py` 已建立，固定宽度改写受测试保护 |
| R0-2 | 配置解析行为测试 | 共享内核 | 已完成 | 环境变量覆盖通过 | `tests/test_config_resolution.py` 已覆盖参数解析、运行时组装与 `prepare_case_run/execute_case` 关键行为 |
| R0-3 | `G1/G3` 分组契约测试 | 共享内核 | 已完成 | 当前分组结果锁定 | `tests/test_grouping_contract.py` 已建立 |
| R0-4 | 结果 schema 测试 | 共享内核 | 已完成 | Train/Valid/All 字段稳定 | `src/result_schema.py` 已补齐 `MatrixSummaryView` / `extract_matrix_summary_view(...)` 契约测试，Train/Valid/All 聚合字段与主指标字段已有回归保护 |
| R1-1 | 抽取 `fixed_width.py` | 共享内核 | 进行中 | `run_model.py` 仅保留薄封装 | `src/calibration_core/fixed_width.py` 已落地，`run_model.py` 已改为调用共享改写能力 |
| R1-2 | 抽取 `case_runtime.py` | 共享内核 | 进行中 | DSSAT 调用入口统一 | 已形成 `prepare_case_run(...) -> execute_case(...) -> build_pest_output_text(...)` 三段式，但 `case_runtime.py` 仍待下沉到共享内核命名空间 |
| R1-3 | 抽取 `observations.py` | 共享内核 | 进行中 | 观测读取逻辑去重 | `src/observations.py` 已承接 WHT/A 路径解析、TRT→dates 映射、输出变量契约与观测字段对齐，`case_runtime.py` 已开始复用该模块 |
| R2-1 | 抽取 `pest_builder.py` | 共享内核 | 已完成 | PST 构造统一 | `src/calibration_core/pest_builder.py` 与兼容封装已落地，`run_build_pest_setup(...)` / `run_build_pest_setup_cli(...)` 稳定入口已承接 `eval.py`、`scripts/run_*.ps1`、builder CLI 子命令与 `src/build_pest_setup.py` 的生产调用面；当前工程侧已不再有生产脚本绕过顶层 `src/pest_builder.py` 直接拼装 builder 调用 |
| R2-2 | 抽取 `pest_runner.py` | 共享内核 | 已完成 | `glm/ies` 调用统一 | `src/calibration_core/pest_runner.py` 已统一 `run_model.py` Python 入口、`run_pestpp_executable(...)` 二进制调用、`run_model_with_params(...)` 参数评估入口、`run_compare_model(...)` compare 场景包装、`run_pestpp_cli(...)` CLI 透传入口与 GLM 结果解析；`build_run_model_env(...)` 现也承接 `PROJECT_CONFIG / DSSAT_CASE_DIR / CUL_PATH / DSSAT_EXTRA_SUMMARY_VARS / DSSAT_ALLOW_MISSING_WHT_DATES` 等运行环境字段，`build_pest_setup.py` 与 sandbox `eval.py` 已共用同一套运行上下文组装逻辑 |
| R2-3 | 抽取 `result_schema.py` | 共享内核 | 已完成 | 结果对象统一 | `metrics_by_trt`、输出命名规则、`build_pest_output_text(...)`、`MatrixSummaryView`、sandbox 主矩阵提取、聚合指标导出、`build_treatment_comparison_records(...)`、`build_experiment_export_context(...)`、`build_treatment_metric_export_rows(...)`、`build_aggregate_metric_export_rows(...)`、`build_combo_key(...)`、`TREATMENT_METRIC_EXPORT_FIELDNAMES`、`AGGREGATE_METRIC_EXPORT_FIELDNAMES`、summary/scatter/residual/figure-ready/compare-summary fieldname 常量与导出 helper 已统一落入 `src/result_schema.py`；`case_runtime.py`、`run_model.py`、`compare_three.py`、`eval.py` 与 `auto_evolve.py` 当前均经由稳定顶层入口复用结果 schema |
| R3-1 | sandbox 去除私有路径依赖 | 研究层 | 已完成 | 不再直连 mvp 私有脚本 | `auto_evolve.py` 与 `eval.py` 已改为按脚本位置 / 环境变量解析 sandbox 与 mvp 根目录，不再绑定旧 `C:\DSSAT48\Wheat\...` 常量；`mvp_pest_mgda\public_api.py` 已作为稳定公共入口承接 `pest_builder / pest_runner / result_schema / dssat_io` 的加载，sandbox 主链已不再向 `mvp_pest_mgda\src` 注入路径；本轮进一步补齐了 `public_api.py` 与并行 worker 调度的契约测试，并清理了根目录下历史 `parallel_workers` 运行副本 |
| R3-2 | sandbox 引入 `runs/` | 研究层 | 进行中 | 根目录不再堆积运行产物 | `auto_evolve.py` 已把并行 workspace 收敛到 `runs/parallel_workers`，主日志与矩阵/导出 TSV 收敛到 `artifacts/`；本轮进一步把根目录遗留 `experiment_summary.tsv` 等产物改成自动迁移进 `artifacts/`，报告输入也正式收口到标准 `artifacts/experiment_summary.tsv` |
| R3-3 | sandbox 多作物配置抽象 | 研究层 | 进行中 | 不再绑定 `project_wheat.json` | `auto_evolve.py` 与 `eval.py` 已优先解析通用 `project.json`，并保留对旧 `project_wheat.json` 的兼容回退；本轮又把 sandbox project config 路径解析收敛到 `dssat_io.resolve_project_config_path(...)` 共享 helper，经由 `public_api.py` 统一承接 `AR_PROJECT_CONFIG / project.json / project_wheat.json` 解析顺序，多作物参数顺序也已开始从 project config 动态读取 |
| R4-1 | 标准结果导出接口 | 工程层 | 进行中 | 论文图表数据接口稳定 | `auto_evolve.py` 已新增 `experiment_aggregate_metrics.tsv`，并让 `experiment_metric_split_heatmap.tsv`、`experiment_summary.tsv`、`experiment_scatter_1to1.tsv`、`experiment_residuals_wide.tsv` 与 `experiment_figure_ready.tsv` 优先吸收共享 schema 的 `split/metric/count/nrmse/bias` 聚合字段；本轮又把导出上下文、逐处理导出行、聚合导出行、TSV header 常量、行 value-map、summary/scatter/residual/figure-ready dict 组装与 `combo_key` 组装进一步下沉到 `src/result_schema.py`，使 sandbox 导出链更接近稳定接口 |
| R4-2 | 主矩阵报告生成脚本 | 工程层 | 进行中 | `W/O/S/G` 可批量汇总 | `auto_evolve.py` 已新增 `--mode report` 入口，可基于 `artifacts\experiment_summary.tsv` 生成 `artifacts\main_matrix_report.md`、`artifacts\main_matrix_leaderboard.tsv`、`artifacts\main_matrix_dimension_summary.tsv`、`artifacts\main_matrix_baseline_summary.tsv`、`artifacts\main_matrix_baseline_detail.tsv`、`artifacts\main_matrix_key_indicator_table.tsv`、`artifacts\main_matrix_baseline_winners.tsv`、`artifacts\main_matrix_paper_main_table.tsv`、`artifacts\main_matrix_paper_appendix_table.tsv`、兼容别名 `artifacts\main_matrix_paper_table.tsv` 与多份 `top-k` 面板 TSV；当前已具备 `W/O/S/G` 维度汇总、baseline 汇总/明细双层导出、论文主文关键指标表、baseline 胜出组合摘要、论文主文最小字段表/附录全字段表拆分、`engine/weight/improvement` 分面榜单、`validation × budget` 附录面板与 appendix index 收口，且报告输入路径已收口到标准 `artifacts/` 入口 |

### 11.1 当前进度快照
- `run_model.py` 已从“大一统脚本”推进到薄入口形态，当前主干基本收敛为：`prepare_case_run(...)`、`execute_case(...)`、`build_pest_output_text(...)`
- 单处理执行已抽成 `execute_treatment(...)`，整 case 执行已抽成 `execute_case(...)`，DSSAT 执行内核与 CLI 入口开始解耦
- `prepare_case_run(...)` 已统一承担参数读取、试验号解析、运行时目录选择、参数映射、观测契约解析与 `RuntimeFileState` 组装
- 共享固定宽度改写能力已落到 `src/calibration_core/fixed_width.py`，说明最脆弱的 DSSAT 文件写入逻辑已开始从入口脚本中外移
- `src/observations.py` 已落地，观测路径解析、WHT 日期读取与输出契约对齐逻辑已从 `case_runtime.py` 中剥离出来，说明 `R1-3` 已进入实施阶段
- `src/result_schema.py` 已开始承接 `metrics_by_trt` 类型、输出命名规则、PEST 文本构建逻辑、`MatrixSummaryView` 摘要提取与聚合指标导出，说明结果侧抽象已从“主链路接入”继续推进到“导出链路接入”
- `src/calibration_core/pest_runner.py` 已承接 `run_pestpp_executable(...)`、GLM `*.par` 结果解析与 CLI `run` 子命令，`eval.py` 中 `pest_glm_*` / `pestpp_ies` 阶段运行均已复用该共享入口
- `src/calibration_core/pest_runner.py` 已新增 `run_model_with_params(...)`，`compare_three.py` 与 `mgda_update.py` 不再自行拼装 `PARAMS_PATH` / `DSSAT_KEEP_OUTPUTS` / `DSSAT_TRTS` 后直连 `run_python_entrypoint(...)`
- `src/build_pest_setup.py` 里的试跑链路也已改为复用 `run_model_with_params(...)`，当前源码中对 `run_python_entrypoint(...)` 的直接调用已基本收敛到 `calibration_core` 共享层
- `src/calibration_core/pest_runner.py` 的 `build_run_model_env(...)` 已开始统一承接 `PROJECT_CONFIG`、`DSSAT_CASE_DIR`、`CUL_PATH`、`DSSAT_EXTRA_SUMMARY_VARS` 与 `DSSAT_ALLOW_MISSING_WHT_DATES` 等 DSSAT 运行环境字段拼装，`src/build_pest_setup.py` 与 `autoresearch_sandbox\eval.py` 不再分别手写这些运行上下文
- `src/calibration_core/pest_builder.py` 已新增 `run_build_pest_setup(...)` 与 CLI `run` 子命令，`src/pest_builder.py` 也已提供顶层 CLI 转发，`eval.py` 与 `scripts/run_*.ps1` 已开始直接复用该稳定入口，说明 PST 构建链路开始从“脚本路径感知”转向“共享 API 感知”
- `autoresearch_sandbox\eval.py` 已改为通过 `public_api.py` 侧向复用 `pest_builder / pest_runner` 顶层稳定入口调用 `run_build_pest_setup_cli(...)`、`run_compare_model(...)` 与 `run_pestpp_cli(...)`，不再自行解析 `run_model.py` 路径，也不再直接感知底层 Python 入口与 PEST 二进制进程拼装
- `mvp_pest_mgda\public_api.py` 已作为 sandbox 消费 mvp 共享能力的稳定公共入口落地，内部统一承接 `src` 级模块解析，开始把“路径兼容细节”从 sandbox 侧回收到 mvp 工程侧
- `autoresearch_sandbox\eval.py` 与 `autoresearch_sandbox\auto_evolve.py` 已改为通过 `public_api.py` 加载 `pest_builder / pest_runner / result_schema / dssat_io`，不再向 `mvp_pest_mgda\src` 注入路径，当前 sandbox 主链源码中已完成对 `calibration_core.*` 私有命名空间与 `src` 路径注入的双重脱钩
- `src/case_runtime.py` 与 `src/run_model.py` 已开始经由 `src/result_schema.py` 顶层稳定入口复用 `build_pest_output_text(...)` 与相关类型，而不再直接引用 `calibration_core.result_schema`
- `tests\test_config_resolution.py` 已新增扫描式回归测试，确保生产脚本不会重新直接导入 `calibration_core.pest_builder / pest_runner / result_schema` 私有入口，从而把 R2-1 / R2-2 / R2-3 的调用面封口变成可回归验证的契约
- `autoresearch_sandbox\eval.py` 与 `autoresearch_sandbox\auto_evolve.py` 已不再各自手写 project config 查找逻辑，而是经由 `public_api.py -> dssat_io.resolve_project_config_path(...)` 共享 helper 统一解析 `AR_PROJECT_CONFIG / project.json / project_wheat.json`，并已补上 sandbox 路径构建与 legacy fallback 的回归测试
- `autoresearch_sandbox\auto_evolve.py` 已新增根目录遗留产物迁移逻辑，会在 benchmark / innovate / matrix / report 入口优先把 `evolution_log.md`、`matrix_results.tsv`、`experiment_summary.tsv` 等旧产物迁入 `artifacts\`，同时已补上“路径必须位于 `runs/` / `artifacts/`”与“legacy root summary 会被迁移后继续生成报告”的回归测试
- `tests\test_config_resolution.py` 已补充 `public_api.py` 的 idempotent path contract、trimmed module lookup、并行 worker workspace 不再复制 `eval.py`、以及 `execute_matrix_job(...)` 并行模式必须使用根 `eval.py` + `AR_SANDBOX_DIR` 的契约测试，说明 R3-1 已从“主链切换完成”推进到“关键边界已有回归保护”
- `autoresearch_sandbox\auto_evolve.py` 已停止向 worker workspace 复制 `eval.py`，并改为在并行模式下直接运行根 `eval.py` 且通过 `AR_SANDBOX_DIR` 指向 job 目录；同时根目录下历史 `parallel_workers\` 旧副本已清理，避免旧脚本快照继续暗示过时执行模式
- `autoresearch_sandbox\artifacts\experiment_aggregate_metrics.tsv` 已开始输出 `split/metric/count/nrmse/bias` 标准字段，说明论文图表与后续工程汇总已经拥有首个直接复用共享结果对象的稳定接口
- `experiment_metric_split_heatmap.tsv` 已开始直接复用聚合指标导出里的 `count/nrmse/bias` 字段，说明 metric/split 级汇总不再只依赖逐处理残差二次聚合
- `experiment_summary.tsv` 的 `train/valid/all mean_nrmse` 与主产量指标 `nrmse/bias` 已开始优先从共享 schema 聚合导出回填，说明工程层总表已开始摆脱对 `experiment_runs.tsv` 散落字段的单点依赖
- `build_treatment_comparison_records(...)` 已落入 `src/result_schema.py`，`experiment_metrics_long.tsv` 的逐处理误差拼装开始由共享结果对象统一推导，而不再完全散落在 sandbox 导出层
- `ExperimentExportContext`、`TreatmentMetricExportRow`、`AggregateMetricExportRow` 与 `build_combo_key(...)` 已落入 `src/result_schema.py`，`auto_evolve.py` 中 metrics-long / aggregate-metrics 导出与 summary/scatter 的组合键拼装已开始直接复用共享 helper
- `TREATMENT_METRIC_EXPORT_FIELDNAMES`、`AGGREGATE_METRIC_EXPORT_FIELDNAMES`、`build_treatment_metric_export_value_map(...)` 与 `build_aggregate_metric_export_value_map(...)` 已落入 `src/result_schema.py`，`auto_evolve.py` 中 metrics-long / aggregate-metrics 的 header 与写盘顺序不再散落硬编码
- `SUMMARY_EXPORT_FIELDNAMES`、`SCATTER_EXPORT_FIELDNAMES`、`RESIDUAL_EXPORT_BASE_FIELDNAMES`、`FIGURE_READY_EXPORT_FIELDNAMES` 以及 `build_summary_export_row(...)`、`build_scatter_export_row(...)`、`build_residual_export_row(...)`、`build_figure_ready_export_row(...)` 已落入 `src/result_schema.py`，`auto_evolve.py` 中 summary / scatter / residual / figure-ready 的 dict 组装不再散落在工程层
- `COMPARE_SUMMARY_FIELDNAMES` 与 `build_compare_summary_fieldnames(...)` 已落入 `src/result_schema.py`，`compare_three.py` 的 compare summary 表头顺序也开始由共享 schema 控制，而不再直接依赖局部 `dict.keys()` 顺序
- `experiment_residuals_wide.tsv` 与 `experiment_figure_ready.tsv` 已开始回填 panel 级 `count/nrmse/bias` 聚合字段，说明残差宽表与图表就绪点表也开始直接复用统一结果 schema，而不是只保留逐点误差
- `experiment_scatter_1to1.tsv` 已开始回填 panel 级 `count/nrmse/bias` 聚合字段，说明 1:1 散点图输入也开始直接挂接共享 schema，而不是只保存逐点观测/模拟值
- `dssat_io.py`、`auto_evolve.py` 与 `eval.py` 已开始共享多作物参数 schema：参数名、初值与边界优先从 project config 解析，sandbox 侧同时支持 `project.json` 与旧 `project_wheat.json`
- `auto_evolve.py` 已新增主矩阵报告构建链：从 `experiment_summary.tsv` 读取最新组合，输出 `main_matrix_leaderboard.tsv`、`main_matrix_dimension_summary.tsv` 与 `main_matrix_report.md`，并支持对 legacy 根目录 summary 文件的兼容回退，说明 `R4-2` 已从“待开始”进入“已有正式入口”
- `tests\test_config_resolution.py` 已补充主矩阵报告 contract test，覆盖 plan 过滤、排行榜排序、`W/O/S/G` 维度汇总以及 legacy summary 路径回退，说明报告脚本已具备首轮回归保护
- `auto_evolve.py` 的报告模式本轮继续扩展出论文主表视角：已支持 `paper_plan / paper_budget / paper_status / paper_yield_metric / paper_require_validation / paper_require_better_than` 等筛选参数，并新增 `main_matrix_paper_table.tsv`、`main_matrix_topk_overall.tsv`、`main_matrix_topk_by_engine.tsv`、`main_matrix_topk_by_weight.tsv` 与 `main_matrix_topk_improvement.tsv`，说明主矩阵报告已开始直接服务论文主文与附录
- `auto_evolve.py` 本轮又把论文表导出拆成 `main_matrix_paper_main_table.tsv` 与 `main_matrix_paper_appendix_table.tsv`：前者保留主文最小字段，后者保留完整字段，并继续用 `main_matrix_paper_table.tsv` 兼容旧调用方；markdown 报告也同步增加主文表与附录全表预览，appendix index 现已显式登记 full table 面板
- `tests\test_config_resolution.py` 已补充论文主表与 top-k 面板 contract test，覆盖 validation 优先回退、`b0` 改善筛选、`engine/weight` 分面榜单与 markdown 面板渲染，说明 R4-2 已拥有第二层回归保护
- `tests\test_config_resolution.py` 本轮继续补上论文表拆分契约：已覆盖 `paper_main_table / paper_appendix_table / legacy paper_table` 三路 TSV 输出、appendix index 新面板登记与报告新增章节，说明论文表拆分已具备回归保护
- `auto_evolve.py` 本轮继续把 baseline 视角从“摘要级”推进到“明细级”：已新增 `main_matrix_baseline_detail.tsv`，按 `b0 / b1 / negative_ref` 三个基准输出逐组合排序明细，并在 markdown 报告中加入 baseline detail preview，说明报告已开始具备直接支撑主文 baseline 论证与附录追溯的双层接口
- `tests\test_config_resolution.py` 也同步补上 baseline detail 契约：当前已覆盖 `main_matrix_baseline_detail.tsv` 写盘、`baseline_detail` 返回值、baseline 排序字段与 markdown 新章节，说明 baseline 明细产物也已纳入回归保护
- `auto_evolve.py` 本轮继续补齐论文主文摘要接口：已新增 `main_matrix_key_indicator_table.tsv` 与 `main_matrix_baseline_winners.tsv`，前者把 `score / valid_mean_nrmse / comparison_delta / train_mean_nrmse / all_mean_nrmse` 聚合为主文关键指标表，后者按 `b0 / b1 / negative_ref` 输出最优胜出组合摘要；同时新增 `main_matrix_topk_by_validation_budget.tsv`，把验证状态与预算组合成附录多筛选面板；markdown 报告也同步增加 `Paper Key Indicator Table`、`Baseline Winners` 与 `Validation × Budget Top-K` 章节
- `tests\test_config_resolution.py` 已同步补上关键指标表与 baseline winners 契约：覆盖新增 TSV 写盘、返回值暴露、baseline 胜出组合排序结果与 markdown 章节渲染，说明 R4-2 的论文主文摘要接口也已进入回归保护
- 当前总体已从“共享内核抽取中段”推进到“接口收口阶段”：`R0` 已完成，`R1/R2` 已形成可工作的共享骨架，`R3-1` 已完成主链与 worker 层的公共入口收口，`R4-1` 已出现首批稳定导出接口，`R4-2` 已具备首个正式报告入口；剩余重点不再是大面积搬运代码，而是继续完善报告内容与其余契约测试

### 11.2 项目总览判断
- **整体阶段**：项目已明显进入后半程，已经完成“保护网建立 + 主链能力抽离 + 报告入口落地”，当前处于“接口收口 + 报告成品化 + 多作物抽象补完”阶段
- **里程碑完成度**：按追踪表条目看，`R0` 已全部完成，`R2` 已全部完成，`R3-1` 已完成，`R4-1/R4-2` 已有可用正式产物；若按条目计，当前约为 `8 / 15` 项完成，但按主链可运行能力计，核心闭环已基本形成，整体更接近“后半程优化与封口”而非“前期搭框架”
- **共享内核层进度**：`fixed_width / observations / pest_builder / pest_runner / result_schema` 都已落地并被真实调用，说明最关键的 DSSAT / PEST 稳定能力已经不再只存在于单脚本内部；剩余工作主要是把 `case_runtime.py` 等仍在工程层暴露的能力继续向共享命名空间收口
- **工程执行层进度**：标准执行链路与导出 schema 已初步统一，主矩阵报告脚本已具备 leaderboard、baseline summary/detail、paper key indicator table、baseline winners、metric snapshot、论文主文最小字段表、附录全字段表、appendix index 与 top-k 面板等正式产物，说明论文结果章的数据接口已从“脚本副产物”升级为“可回归验证的产物契约”
- **研究探索层进度**：sandbox 已通过 `mvp_pest_mgda\public_api.py` 完成对共享能力的公共入口消费，主链与并行 worker 都不再依赖 `mvp_pest_mgda\src` 路径注入；`runs/` 与 `artifacts/` 约定已开始成形，但多作物配置与探索层契约测试仍需补齐
- **当前瓶颈**：后续风险已不再主要来自“底层能力不存在”，而主要来自三类接口边界尚未完全封口：一是报告接口虽已覆盖 baseline/detail、主文关键指标与 baseline winners，但附录多筛选导出与章节编排仍可继续收口，二是工程层仍存在少量能力未彻底收口到共享入口，三是 sandbox 多作物抽象和策略契约仍偏弱
- **总体判断**：项目现在不是缺“能跑的系统”，而是缺“最后一层稳定边界与论文交付级成品化”；因此后续工作重心应从“大规模抽取”转向“补齐接口、压实契约、打磨报告与多作物适配”

### 11.3 后续开发重点与推荐顺序
1. 优先完成 `R4-2` 的“论文交付级报告成品化”
   - 当前报告已经具备正式入口与多份产物，但距离“直接服务主文、附录与复现实验”还差最后一层收口
   - 现在 baseline 摘要/明细、主文关键指标表与 baseline 胜出组合摘要都已落地，下一步应优先补充附录多筛选导出、章节编排一致性与主文补充指标矩阵
   - 目标是把 `main_matrix_report.md + key_indicator_table + baseline_winners + paper_main_table + paper_appendix_table + appendix_index` 打造成稳定论文接口
2. 收尾 `R3-2 / R3-3`，把 sandbox 的运行与配置边界彻底稳定下来
   - 当前 `runs/` 与 `artifacts/` 已建立，但还应继续清理遗留 root 级运行习惯，并把多作物 project config、参数 schema、路径解析顺序完全收口到共享 helper
   - 目标是让 sandbox 真正成为“只消费公共入口的研究层”，而不是“仍带少量历史兼容负担的半过渡态”
3. 收尾 `R1-1 / R1-2 / R1-3` 的共享命名空间封口
   - 当前共享能力虽已大体形成，但 `case_runtime.py` 等仍存在“实现已共享、命名空间未完全收口”的情况
   - 下一步应继续把运行时准备、观测读取、固定宽度改写等残余工程层耦合点压回 `calibration_core`
   - 目标是让 DSSAT/PEST 主链真正只剩一套共享答案
4. 补齐第二批契约测试，尤其是“接口层测试”而非“算法细节测试”
   - 当前共享内核与主矩阵报告已有较强保护，但 sandbox 策略接口、多作物配置解析、worker 工作目录规划、报告 appendix 产物矩阵仍可继续补强
   - 推荐补充 `test_strategy_contract.py`、`test_eval_plan_translation.py`、多作物 config contract 与主矩阵报告多面板 contract
5. 最后再进入增强层与优化层扩展
   - 在接口封口前，不建议过早扩展更多策略搜索、预算分析和混合优化实验逻辑
   - 待报告接口和共享边界稳定后，再继续推进 `Budget / Initialization / Multi-start / Hybrid Search / MOO` 等增强层工作会更稳妥

### 11.4 建议的后续开发排期
建议按以下顺序推进后续开发，每一段都以“先契约、再实现、再验证”为执行纪律：

1. **阶段 A：报告成品化**
   - 聚焦 `R4-2`
   - 交付目标：在现有 baseline summary/detail、主文关键指标表与 baseline winners 之上继续补齐附录多视角导出、报告章节稳定顺序与更多主文指标矩阵
   - 验收信号：论文主文与附录所需 TSV 基本不再依赖人工二次整理
2. **阶段 B：sandbox 边界收口**
   - 聚焦 `R3-2 / R3-3`
   - 交付目标：`runs/` 与 `artifacts/` 约定彻底稳定，多作物 project config 与参数 schema 统一，遗留 root 级兼容路径进一步减少
   - 验收信号：sandbox 在不同作物/不同 workspace 下都通过统一入口稳定运行
3. **阶段 C：共享命名空间封口**
   - 聚焦 `R1-*`
   - 交付目标：把仍散落在工程层的运行时与观测层逻辑彻底迁入 `calibration_core`
   - 验收信号：工程层与研究层都只依赖共享入口，不再携带底层实现细节
4. **阶段 D：第二轮契约测试补强**
   - 聚焦 `R3/R4` 的接口级回归保护
   - 交付目标：形成覆盖多作物配置、策略接口、worker 规划、报告 appendix 面板的回归测试网
   - 验收信号：后续迭代可以在不担心回归的前提下继续扩展论文结果和增强层实验
5. **阶段 E：增强层恢复推进**
   - 聚焦 `Budget / Initialization / Multi-start / Hybrid Search / NSGA-II / MGDA`
   - 交付目标：在稳定接口之上恢复并扩展探索层创新
   - 验收信号：增强层实验可以复用前面已经固化的报告与导出接口，不再反向污染主链结构

## 12. 每阶段验收纪律
每完成一个子阶段，都必须执行以下检查：

1. 单元测试通过
2. lint 通过
3. typecheck 通过
4. 原有最小运行闭环仍可运行
5. 路径迁移后不再依赖旧目录硬编码

## 13. 风险与回退策略

### 13.1 主要风险
- 抽取共享内核时把当前 DSSAT 行为改坏
- 重构后固定宽度写入精度偏移
- sandbox 切换接口后实验结果不可比
- 工程层与研究层对 schema 的理解分叉

### 13.2 控制策略
- 先测后搬
- 一次只迁移一种职责
- 保留兼容薄封装，避免一步切断旧入口
- 所有导出表先保持字段向后兼容

### 13.3 回退规则
- 任一阶段只要最小闭环失败，立即回退到上一阶段提交
- 不同时重构路径、配置、算法逻辑三个维度
- 先保证 `B0 + O1 + S1 + G1` 最小闭环，再恢复增强层

## 14. 第一批建议直接执行的三个最小改动

### 14.1 改动 A
为 `mvp_pest_mgda` 新增测试目录与固定宽度测试。

原因：

- 风险最低
- 收益最大
- 可以立即开始保护最脆弱的 DSSAT 文件写入逻辑

### 14.2 改动 B
把 `run_model.py` 中纯工具性质的固定宽度函数抽到共享模块。

原因：

- 技术边界清晰
- 对外行为易保持不变
- 后续 `.X/.WTH/.SOL` 扩展会直接复用

### 14.3 改动 C
把 `autoresearch_sandbox/eval.py` 中对 `mvp_pest_mgda\src\run_model.py` 和 `build_pest_setup.py` 的硬编码路径替换为统一入口解析。

原因：

- 这是当前最明显的耦合点
- 改完以后，后续 sandbox 的大部分重构会更容易

## 15. Definition of Done
当以下条件同时成立时，本轮重构可视为完成：

1. sandbox 不再直接引用 mvp 私有实现路径
2. 核心 DSSAT / PEST 运行能力进入共享内核
3. `mvp_pest_mgda` 成为稳定工程执行端
4. `autoresearch_sandbox` 成为纯研究探索端
5. 路径从旧 `C:\DSSAT48\Wheat\...` 迁移到当前仓库后仍保持可运行
6. 主矩阵与增强层在代码结构上也形成清晰隔离
7. 结果输出可以直接服务论文的 Phase 0 / Phase 1 / 稳健性分析

## 16. 下一步执行建议
推荐直接按以下顺序开工：

1. **先做 `R4-2` 的报告成品化收尾**
   - 优先补主文关键指标表、baseline 胜出组合摘要与附录多筛选导出
2. **再做 `R3-2 / R3-3`**
   - 优先收口 sandbox 的 `runs/` / `artifacts/` 约定与多作物配置解析
3. **再做 `R1-*` 的共享命名空间封口**
   - 把运行时与观测层的残余耦合继续压回 `calibration_core`
4. **最后补第二轮契约测试并恢复增强层扩展**
   - 先锁定接口，再扩展更复杂的优化与探索逻辑

如果只能先做一件事，优先级最高的是：

- **把 `R4-2` 报告接口打磨到论文可直接消费的程度**

因为当前项目最接近论文交付价值、也最能带动后续接口收口的，已经不是底层能力抽取，而是“把已有能力稳定地组织成可复用结果接口”。
