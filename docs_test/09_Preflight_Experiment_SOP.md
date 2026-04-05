# 正式实验前预演与收口 SOP

## 1. 目的

这份 SOP 只回答一个问题：**在正式批量实验开始前，哪些事项必须先冻结、先预演、先约定好恢复策略。**

当前代码状态已经具备：

- 显式协议落盘
- 多作物配置解析
- 研究层质量门禁
- 基础 lint / typecheck / smoke 闭环

因此现在最关键的，不再是继续扩抽象层，而是把实验口径、预演流程和失败恢复动作固定下来，避免科研运行中途漂移。

## 2. 正式实验配置快照

正式实验启动前，应冻结一版“实验清单”，至少包含以下内容：

### 2.1 配置文件快照

- 最终采用的 `project_*.json` 文件集合
- 每个作物对应的 `dssat_case_dir`
- 每个作物对应的 `filex` / `base_filex`
- 每个作物对应的 `obs_a_path` / `obs_t_path`
- 每个作物对应的 `cul_path`

当前多作物配置文件位于：

- [config/multi](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi)

其中玉米的 `base_filex` 已修正为真实存在模板：

- [project_maize.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_maize.json#L12-L15)

### 2.2 实验设计快照

- 正式纳入批跑的作物列表
- 每个作物启用的 treatment 集合
- 最终采用的目标指标集合
- `weight mode`
- `calibration sequence`
- `grouping mode`
- `optimizer / engine mode`
- `budget profile`

这里的“目标指标集合”不再应理解为所有作物强行共用一套主指标，而应冻结为“跨作物可比指标集合 + 每个作物自己的主指标口径”：

- 跨作物可比指标集合：`ADAP`、`MDAP`、`LAIX`、`CWAM`、`HWAM`、`HWUM`
- wheat / maize / rice / cassava 当前主产量口径仍以 `HWAM` 为主
- cabbage 当前主产量口径固定为 `PWAM`
- cabbage 的辅助生物量 / 冠层口径改为 `CWAD`、`LAID`、`PWAD`，不再错误复用 `HWAM` / `LAIX`

研究层主矩阵与 paper-facing 产物的文件落点已经集中到：

- [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L183-L243)

正式实验前应把本轮最终使用的这些维度值写成一份独立清单，避免后续修改配置后无法追溯。

### 2.3 推荐快照方式

- 在正式实验根目录保存一份 `experiment_snapshot` 文档
- 复制本轮实际使用的 `project_*.json`
- 写明作物列表、treatments、指标、权重、sequence、budget
- 写明 Python 环境与 DSSAT 根目录
- 写明运行日期、批次名、负责人

建议原则：**配置快照要能独立回答“这一轮实验到底跑了什么”。**

## 3. 小规模 Rehearsal

正式批跑前，至少做一轮小规模 rehearsal：

- 1 个作物
- 1 套正式参数组合
- 1 次完整输出链路

### 3.1 Rehearsal 目标

不是验证“算法优不优秀”，而是验证“正式链路是否闭环”。

至少确认以下产物落盘正确：

- `run_manifest.json`
- `contract_report.json`
- `main_matrix_quality_gate.tsv`
- `main_matrix_protocol_paper_table.tsv`
- `main_matrix_paper_main_table.tsv`
- `main_matrix_paper_appendix_table.tsv`

当前主矩阵和 paper-facing TSV 产物路径由研究层统一定义：

- [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L223-L235)

单次运行侧协议产物由运行层统一写出：

- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py#L677-L715)
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L363-L375)

### 3.2 Rehearsal 验收点

- `run_manifest.json` 中的 `crop`、`project_config_path`、`case_dir` 与实际一致
- `contract_report.json` 没有出现意料外 fallback
- quality gate 的等级与预期一致
- paper-facing 表没有空列、错列、重复口径
- 结果目录命名与后续批跑规则一致

### 3.3 当前建议

优先用 Wheat 做 live rehearsal，因为真实安装路径和参考文件最稳定；如需验证多作物模板一致性，可再补一轮 maize 或 rice。

## 4. 失败恢复策略

正式批跑前，不要只考虑“成功时会产出什么”，还要先约定“失败时如何恢复”。

### 4.1 必须先定下来的规则

- 结果目录命名规则
- 批次 ID / run ID 规则
- 中间 TSV/CSV 是否采用追加写入
- 失败后是重跑单 cell、单作物，还是整批重跑
- 哪些文件可视为断点恢复依据

### 4.2 当前工程里已经可利用的恢复抓手

- 运行层会写 `run_manifest.json` 与 `contract_report.json`
- 研究层 artifacts 使用集中路径管理
- 主矩阵结果、experiment 级结果、quality gate、paper tables 都有独立 TSV 文件

参考：

- [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L199-L243)

### 4.3 推荐恢复策略

- 批量实验目录按“批次名 + 日期”固定
- 单次运行目录按 `run_id` 固定
- 结果表尽量采用追加写入或分步重建，而不是只保留内存态
- 每完成一个阶段或一代优化，就立即保存一次 TSV / CSV
- 遇到 `fail` 级 quality gate 时先停止扩跑，再复核 protocol artifacts

当前 quick smoke 已按与正式批跑一致的目录口径执行：

- 研究层汇总产物继续落到 `autoresearch_sandbox/artifacts`
- 单次运行协议产物继续落到 `autoresearch_sandbox/runs/runtime`
- smoke 使用的 `custom + quick` 入口与后续正式批跑命令保持一致，因此满足“结果目录命名与后续批跑规则一致”的要求

建议原则：**恢复策略必须允许“最小重跑”，不要因为一个 cell 失败就让整批结果不可用。**

## 5. 真实模板完整性检查

正式实验前，应做一轮模板与真实 DSSAT 安装的一致性检查。

### 5.1 每个作物至少检查

- `dssat_case_dir` 是否存在
- `filex` 是否存在
- `base_filex` 是否存在
- `obs_a_path` 是否存在
- `obs_t_path` 是否存在
- `cul_path` 是否存在
- trial prefix 是否与 registry / 观测解析逻辑一致

多作物注册表与作物语义契约当前主要由以下模块承接：

- [crop_registry.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/crop_registry.py)
- [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py)
- [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)

### 5.2 本轮已确认

- wheat、maize、rice、cabbage、cassava 已完成运行级 smoke
- maize 的 `base_filex` 历史错误已修复
- cabbage 的主指标口径已修正为 `PWAM + CWAD/LAID/PWAD`，不再要求其 A-file 提供 `HWAM` / `LAIX`
- 5 作物顺序 quick smoke 已实际执行完成，5 个作物都得到 `Matrix quality gate: stop_level=required overall=pass decision=go`

### 5.3 正式实验前仍建议做

- 对正式纳入实验的每个作物，再做一次真实路径检查
- 不只检查 JSON 存在，还要检查目标文件确实位于本机 DSSAT 安装目录
- 若新增作物或更换模板，必须重新过这一轮检查

### 5.4 正式开跑前 checklist 表格

下表不是“计划”，而是本轮已经逐项执行后的结果汇总。

| 序号 | 检查项 | 当前结果 | 执行结果 | 关键证据 |
| --- | --- | --- | --- | --- |
| 1 | 冻结正式实验配置快照 | ✅ 完成 | Wheat 已统一到 `SWSW7501` 口径；sandbox 解析优先回落到多作物正式配置，运行 manifest 也已指向正式配置快照 | 默认指标与模式来自 [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L325-L344)、[eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L384-L438)、[eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L538-L544)；正式 Wheat 配置见 [project_wheat.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_wheat.json#L1-L22)；最新 rehearsal 落盘见 [run_manifest.json](file:///d:/Wheat/Wheat/autoresearch_sandbox/runs/runtime/run_manifest.json#L2-L29) |
| 2 | 检查 5 作物真实模板完整性 | ✅ 完成 | 已核查 wheat、maize、rice、cabbage、cassava 的 `case_dir`、`filex`、`base_filex`、`obs_a`、`obs_t`、`cul` 均存在；玉米 `base_filex` 已修正 | 5 作物配置见 [project_wheat.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_wheat.json#L1-L22)、[project_maize.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_maize.json#L1-L16)、[project_rice.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_rice.json#L1-L22)、[project_cabbage.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_cabbage.json#L1-L24)、[project_cassava.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_cassava.json#L1-L20) |
| 3 | 做 1 轮 live rehearsal | ✅ 完成 | 已对 Wheat 跑通 1 轮 matrix rehearsal，`run_manifest.json`、`contract_report.json`、paper tables 与 quality gate 均正常落盘；`paper_rows_present` 已恢复为 pass | rehearsal 落盘见 [run_manifest.json](file:///d:/Wheat/Wheat/autoresearch_sandbox/runs/runtime/run_manifest.json#L1-L29)、[contract_report.json](file:///d:/Wheat/Wheat/autoresearch_sandbox/runs/runtime/contract_report.json#L1-L120)；quality gate 通过见 [main_matrix_quality_gate.tsv](file:///d:/Wheat/Wheat/autoresearch_sandbox/artifacts/main_matrix_quality_gate.tsv#L1-L10)；paper 主表见 [main_matrix_paper_main_table.tsv](file:///d:/Wheat/Wheat/autoresearch_sandbox/artifacts/main_matrix_paper_main_table.tsv#L1-L2) |
| 4 | 确认失败恢复策略 | ✅ 完成 | 已确认 `run_id` 规则、artifact 集中路径、实验级 TSV 追加写入，以及 quality gate stop/go 机制都已具备 | `run_id` 生成见 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L5373-L5377)；artifact 路径见 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L199-L243)；追加写入见 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L5991-L5997)；stop/go 判定见 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L6012-L6038) |
| 5 | 正式开跑判定 | ✅ 可开跑 | 配置快照、真实模板、rehearsal 落盘与失败恢复规则均已闭环；当前仓库已具备正式批跑前置条件 | 证据见第 1~4 项，以及 lint / mypy 验证结果 |

### 5.5 当前已冻结的快照信息

基于本轮代码和已执行检查，当前已经可以冻结下来的信息有：

- 正式纳入可切换运行的作物清单：`wheat`、`maize`、`rice`、`cabbage`、`cassava`
- 当前跨作物可比指标集合：`ADAP`、`MDAP`、`LAIX`、`CWAM`、`HWAM`、`HWUM`，定义见 [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L401-L405)
- 当前冻结的作物主指标口径：wheat / maize / rice / cassava 以 `HWAM` 为主，cabbage 以 `PWAM` 为主；其中 cabbage 配置见 [project_cabbage.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_cabbage.json#L78-L127)，作物注册口径见 [crop_registry.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/crop_registry.py#L34-L48) 与 [crop_registry.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/crop_registry.py#L161-L172)
- 当前默认预算来源：`AR_BUDGET` 默认 `standard`，定义见 [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L325-L344)
- 当前默认 sequence / weight / engine / grouping 归一化入口见 [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L501-L544)
- Wheat 正式快照已统一为 `SWSW7501.WH* + TRT[1,2,8,9,13,14] + WHCER048.CUL`，见 [project_wheat.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_wheat.json#L1-L22)
- 运行期 CUL 与 DSSAT EXE 已切到本地 runtime 副本，避免直接改写 `C:\DSSAT48\Genotype`，见 [run_manifest.json](file:///d:/Wheat/Wheat/autoresearch_sandbox/runs/runtime/run_manifest.json#L19-L29)
- 当前通过 rehearsal 的组合是 `W0_Raw_Identity + o1_least_squares + quick + s1_naive_joint + g1_flat_all_in_one`，见 [main_matrix_paper_main_table.tsv](file:///d:/Wheat/Wheat/autoresearch_sandbox/artifacts/main_matrix_paper_main_table.tsv#L1-L2) 与 [main_matrix_leaderboard.tsv](file:///d:/Wheat/Wheat/autoresearch_sandbox/artifacts/main_matrix_leaderboard.tsv#L1-L3)
- 协议落盘已覆盖 `requested/resolved metrics`、`trts`、`run_id` 与 `workspace_dir`，见 [contract_report.json](file:///d:/Wheat/Wheat/autoresearch_sandbox/runs/runtime/contract_report.json#L5-L119)
- 5 作物 quick smoke 后主报告质量门仍为 pass，且 `paper_rows_present` / `paper_protocol_contract` 均通过，见 [main_matrix_quality_gate.tsv](file:///d:/Wheat/Wheat/autoresearch_sandbox/artifacts/main_matrix_quality_gate.tsv#L1-L10)

### 5.6 当前未完成的收尾动作

本轮收尾已经完成，当前只剩运行策略层面的选择，不再有结构性阻塞：

1. 若正式实验采用当前通过 rehearsal 的 `W0_Raw_Identity` 组合，可以直接进入批跑
2. 若要把 `W8_DSSAT_PEST_Group_Max` 作为正式主组合，建议再单独做 1 轮定向 rehearsal，确认其在当前 split 与参数边界下的稳定性

这属于实验方案选择，不再属于基础设施或协议阻塞。

### 5.7 已固化的正式实验清单

基于当前唯一通过 live rehearsal 且 quality gate 为 pass 的组合，正式实验清单固定为：

| 维度 | 最终值 | 说明 |
| --- | --- | --- |
| weight | `W0_Raw_Identity` | 当前唯一已完成 live rehearsal 且 paper table 正常产出的权重方案 |
| engine | `o1_least_squares` | 当前最稳定、已通过 rehearsal 的求解引擎 |
| sequence | `s1_naive_joint` | 与当前通过组合一致 |
| budget | `quick` | 当前通过组合使用的预算档 |
| grouping | `g1_flat_all_in_one` | 与 `s1_naive_joint` 的通过组合一致 |
| plan | `custom` | 只执行这一个正式组合，避免主矩阵全展开 |
| quality gate | `required` | 继续保持 stop/go 阻断机制 |
| crops | `wheat`、`maize`、`rice`、`cabbage`、`cassava` | 当前已核查模板完整性的 5 个作物 |
| primary metrics | `HWAM` for wheat / maize / rice / cassava；`PWAM` for cabbage | 正式清单改为按作物冻结主指标，不再默认所有作物共用 `HWAM` |

如果后续要切换到 `W8_DSSAT_PEST_Group_Max` 或其他组合，应视为新实验清单，必须先补 1 轮定向 rehearsal，再单独冻结。

### 5.8 正式批跑命令清单

建议统一使用虚拟环境解释器：

`D:\Wheat\Wheat\mvp_pest_mgda\.venv\Scripts\python.exe`

单作物正式批跑命令模板：

```powershell
$env:PROJECT_CROP = "wheat"
& "D:\Wheat\Wheat\mvp_pest_mgda\.venv\Scripts\python.exe" "D:\Wheat\Wheat\autoresearch_sandbox\auto_evolve.py" --mode matrix --plan custom --weights W0_Raw_Identity --engines o1_least_squares --budgets quick --sequences s1_naive_joint --groupings g1_flat_all_in_one --quality-gate-stop-level required
```

5 作物顺序批跑命令清单：

```powershell
$python = "D:\Wheat\Wheat\mvp_pest_mgda\.venv\Scripts\python.exe"
$script = "D:\Wheat\Wheat\autoresearch_sandbox\auto_evolve.py"

$env:PROJECT_CROP = "wheat"
& $python $script --mode matrix --plan custom --weights W0_Raw_Identity --engines o1_least_squares --budgets quick --sequences s1_naive_joint --groupings g1_flat_all_in_one --quality-gate-stop-level required

$env:PROJECT_CROP = "maize"
& $python $script --mode matrix --plan custom --weights W0_Raw_Identity --engines o1_least_squares --budgets quick --sequences s1_naive_joint --groupings g1_flat_all_in_one --quality-gate-stop-level required

$env:PROJECT_CROP = "rice"
& $python $script --mode matrix --plan custom --weights W0_Raw_Identity --engines o1_least_squares --budgets quick --sequences s1_naive_joint --groupings g1_flat_all_in_one --quality-gate-stop-level required

$env:PROJECT_CROP = "cabbage"
& $python $script --mode matrix --plan custom --weights W0_Raw_Identity --engines o1_least_squares --budgets quick --sequences s1_naive_joint --groupings g1_flat_all_in_one --quality-gate-stop-level required

$env:PROJECT_CROP = "cassava"
& $python $script --mode matrix --plan custom --weights W0_Raw_Identity --engines o1_least_squares --budgets quick --sequences s1_naive_joint --groupings g1_flat_all_in_one --quality-gate-stop-level required
```

批跑完成后，建议立即重建主报告产物：

```powershell
& "D:\Wheat\Wheat\mvp_pest_mgda\.venv\Scripts\python.exe" "D:\Wheat\Wheat\autoresearch_sandbox\auto_evolve.py" --mode report --report-plan custom --paper-plan custom --paper-status ok --paper-protocol-status auto --top-n 10 --paper-max-rows 20 --top-k-per-panel 3
```

## 6. 术语解释

## 6.1 什么叫“大规模 core 迁移”

这里说的不是简单“挪几个文件”，而是把目前还带有明显 orchestrator 背景的领域逻辑，进一步沉到共享核心层。

在当前路线图里，典型对象是：

- [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py)
- [case_runtime.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/case_runtime.py)
- [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)

也就是把：

- 观测文件解析
- DSSAT 路径选择
- case runtime 准备
- 模板检查
- 作物配置解析

从当前入口脚本附近，进一步迁到更稳定的 `calibration_core` 之类共享层里。

它的好处是：

- 边界更清楚
- 复用更统一
- sandbox / CLI / 批处理更少重复逻辑

但它的问题是：

- 当前协议和科研门禁刚稳定，过早大迁移容易把运行口径再搅动一次
- 迁移过程中最容易引入“代码更优雅，但实验口径变了”的风险
- 对正式实验前的收益不如 acceptance、快照冻结和 stop/go 规则直接

所以它是**中期演化项**，不是正式实验前阻塞项。

## 6.2 什么叫“public_api 服务化”

当前 [public_api.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/public_api.py#L21-L32) 本质上还是一个模块转发器：

- 先把 `src` 加进路径
- 再暴露 `pest_builder`、`pest_runner`、`result_schema`、`dssat_io`、`crop_registry`

这意味着外部调用方现在仍然主要是在“拿模块对象来用”，而不是在消费一套稳定服务契约。

所谓“服务化”，更像是把它升级成明确的领域接口层，例如：

- 提供稳定的 build / run / report service
- 明确输入输出对象，而不是让外部直接感知底层模块
- 逐步弱化 `sys.path` 注入和模块级直连
- 为 sandbox、批处理、未来 UI 或 API 调用保留稳定边界

它的好处是：

- 外部入口更稳定
- 更容易做版本化接口
- 更容易把底层实现替换掉而不影响上层

但当前它不应前置，因为：

- 现在已经能稳定跑实验，服务化不会直接提高论文结果可信度
- 一旦过早改接口，反而容易影响当前 sandbox、CLI 和 smoke 链路
- 当前最紧要的是“把已稳定闭环收口成科研验收标准”，不是再做一轮接口抽象

所以“服务化 public_api”应理解为**长期平台化动作**，而不是当前正式实验前的必做项。

## 7. 当前建议结论

正式实验开始前，最值得优先完成的收尾顺序是：

1. 按当前快照启动正式批跑
2. 每轮批跑沿用现有 `run_id + TSV 增量落盘 + quality gate` 机制
3. 若切换到其他权重方案，先补 1 轮定向 rehearsal 再扩批
4. 把 core 迁移与 `public_api` 服务化继续留在正式实验之后

在当前状态下，正式批量实验已经具备启动条件。
