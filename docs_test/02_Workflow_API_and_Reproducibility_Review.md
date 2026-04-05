# 工作流、接口契约与可复核性审查

## 1. 评审结论

当前工作流已经具备“能跑主矩阵、能产出结构化结果”的基础，但它的可复核性还更多依赖开发者经验，而不是依赖一个显式、稳定、可归档的运行协议。

对研究项目来说，这是当前最值得尽快补强的部分。

## 2. 当前工作流的优点

### 2.1 工程层已有相对完整的单次运行链

`run_model.py` 的入口已经把以下流程串起来：

- 解析参数文件
- 决定 treatment 集
- 定位 project config
- 建立本地 runtime
- 处理 cultivar 与输入文件
- 运行 DSSAT
- 生成 `pest_out.dat`

参考：[run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py#L405-L521)

这说明运行链不再是完全零散的脚本拼接，而是已经拥有标准入口。

### 2.2 PEST 构建链路也已具备统一入口

`build_pest_setup.py` 已统一承载：

- 参数边界解析
- 参数分组
- 观测组定义
- train/valid 过滤
- 权重模式计算
- PST 写出

参考：[build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L956-L1029)

### 2.3 研究层产物目录设计较成熟

`auto_evolve.py` 的 `SandboxPaths` 已将运行期目录与研究产物目录分离：

- `runs`
- `runtime`
- `artifacts`
- 各类 summary / leaderboard / paper table

参考：[auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L53-L171)

这对论文写作非常有利，因为它天然鼓励“计算过程”和“研究产物”分层保存。

## 3. 当前工作流的主要风险

## 3.1 环境变量驱动过强，隐式契约过多

目前多个关键模块曾经依赖环境变量作为主通信方式，例如：

- `run_model.py` 会消费 `PARAMS_PATH`、`DSSAT_TRTS`、`CUL_PATH`、`DSSAT_EXTRA_SUMMARY_VARS`、`DSSAT_ALLOW_MISSING_WHT_DATES` 等运行请求，但现在支持通过 `--runtime-request` 显式加载请求文件 [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)
- `pest_runner.py` 不再把整份环境直接当成隐式契约，而是把研究相关键收口到 `run_model_request.json` / `build_pest_setup_request.json` [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py)
- `build_pest_setup.py` 也支持通过 `--runtime-request` 读取显式请求对象，而不是只依赖进程环境 [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py)

问题不在于这种方式不能用，而在于：

- 它很难从单次输出文件中完整追溯
- 它对复现实验口径不友好
- 它容易让“主矩阵参数”和“临时调试参数”混在一起

### 当前收口

本轮已经把“执行链 handoff”从纯环境变量推进到“双层契约”：

- 进程内仍允许保留 env/cwd 兼容旧流程
- 进程间入口改为显式 `runtime_request.json`
- 研究侧归档继续使用 `run_manifest.json` / `contract_report.json`

也就是说，现在运行入口已经拆成两类对象：

1. `runtime_request.json`：给脚本执行入口消费
2. `run_manifest.json`：给结果追溯、论文归档和质量门消费

### 建议

每次运行仍然都要生成一个 `run_manifest.json`，至少记录：

- crop
- config path
- bounds source
- weight mode
- engine
- sequence
- grouping
- baseline profile
- budget profile
- active metrics
- split 配置
- 输入参数路径
- 输出目录

这个 manifest 应该成为**所有结果表的上游真相源**；当前内部虽然还保留 env/cwd 兼容层，但主执行入口已经可以依赖 `runtime_request.json`，外部则由 manifest 负责归档、追溯和解释。

## 3.2 当前协议更像“流程拼接”，还不是“声明式实验”

当前项目里已经有：

- `project.json`
- `project_wheat.json`
- `config/multi/*.json`
- 多种环境变量
- plan preset

但这些信息分散在多个位置，缺少一个最终组合对象来表达：

“这一次实验到底在跑什么？”

例如论文中需要稳定回答：

- 是否属于主矩阵组合
- 是否属于增强层预算测试
- 是否使用负优化基线
- 是否允许缺失观测
- 是否使用 MGDA alpha 反馈

当前实现可以推导这些信息，但还不能保证所有结果都自然携带这些信息。

### 建议

把实验描述统一为两层：

1. `project_config`：作物与数据边界
2. `experiment_spec`：本次研究组合

其中 `experiment_spec` 建议显式包含：

- `matrix_axes`
- `engine_profile`
- `budget_profile`
- `search_enhancements`
- `report_profile`

## 3.3 失败与降级缺少“结构化原因”

当前已有一些很好的失败保护：

- 找不到参数文件会报错
- 找不到 PEST 可执行文件会报错 [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py#L27-L48)
- 无可用观测会报错 [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L1026-L1029)

但还有不少“软降级”没有结构化落盘，例如：

- 某个指标在 A 文件中不存在，于是被静默清空 [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py#L107-L128)
- 某些观测在 split 中被置零
- 某些观测因缺失而被跳过
- 某些组因无方差或无最大值而回退到默认权重

### 建议

为每次运行追加 `contract_report.json`，至少记录：

- 缺失的观测文件
- 缺失的观测变量
- 被置零权重的观测及原因
- 实际启用的组
- 被裁剪的组
- 最终参与目标函数的指标数

这对论文里的“方法本身无效”和“数据契约不完整导致失效”的区分非常关键。

## 3.4 主矩阵与稳健性分析层的边界尚不够硬

研究路线图明确指出：

- `Budget` 不是主轴
- `Initialization / Multi-start / Hybrid Search` 也不是主轴

但当前研究层里 `budget` 仍与其他维度共同出现在许多结果表和排行逻辑中 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L53-L171) [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L2178-L2215)。

这更像是**报告组织层面的风险**，不是代码层面的事实性错误；但它会带来两个后果：

1. 主矩阵结果表和稳健性结果表的分析边界容易模糊
2. 论文写作时容易把预算差异误写成方法差异

### 建议

在产物层强制区分两套命名空间：

- `matrix_*`
- `robustness_*`

并要求：

- 主矩阵导出不允许出现增强层字段影响排序主键
- 稳健性分析必须引用一个已经定型的主矩阵冠军/候选集

## 4. 接口设计评估

## 4.1 `public_api` 是正确方向，但还可以再强化

目前 `public_api.py` 的价值很明显：

- 降低研究层直接 import 私有模块的需求
- 提供稳定入口
- 为后续抽包留出空间

参考：[public_api.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/public_api.py#L9-L32)

但它目前仍然偏“模块转发器”，还不是“正式 API 面”。这项改造方向正确，但优先级低于 manifest、contract report 和研究层门禁。

### 建议

下一步可以把公共接口进一步上收为几类明确对象：

- `ProjectConfigService`
- `CaseRuntimeService`
- `PestWorkflowService`
- `EvaluationExportService`

这样研究层依赖的就不再是“模块名”，而是“领域能力面”。

## 4.2 运行参数输入建议先上收到 spec，再按需序列化为 env / 命令参数

当前 `build_run_model_env()` 虽然做得很整齐 [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py#L201-L237)，但它本质仍是环境变量拼装器。

更稳妥的中期方向是：

- 先定义 `RunModelSpec`
- 再由 CLI 层把 `RunModelSpec` 序列化成 env 或命令参数

这样可以兼顾：

- 与现有脚本兼容
- 内部接口更强类型
- 测试更容易写

## 5. 交互设计评估

从研究者使用体验来看，当前交互层还存在一个明显问题：**入口很多，但“推荐入口”不够单一。**

现状更像：

- 有 `run_model.py`
- 有 `build_pest_setup.py`
- 有 `eval.py`
- 有 `auto_evolve.py`
- 有 `run_mvp.ps1`

对于熟悉项目的人问题不大，但对未来论文复现、团队协作、跨作物批处理来说，最佳实践入口仍不够清晰。

### 建议

新增一个统一命令层，哪怕仍基于 PowerShell，也建议固定三类入口：

1. `Invoke-MatrixRun`
2. `Invoke-RobustnessRun`
3. `Invoke-ReportBuild`

并让底层 Python 只关注能力实现。

## 6. 测试与质量门禁评估

测试层有一个明显优点：已经开始为共享契约写测试，尤其是：

- 公共 API 入口
- 路径解析
- `result_schema` 输出字段顺序
- 研究层路径布局

参考：

- [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py#L108-L136)
- [test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py#L230-L331)
- [test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py#L934-L998)

但质量门禁仍有两个不足：

1. `pyproject.toml` 只检查 `src`，未覆盖 `autoresearch_sandbox` [pyproject.toml](file:///d:/Wheat/Wheat/mvp_pest_mgda/pyproject.toml#L1-L10)
2. 缺少多作物集成测试与固定宽度文件 golden test

## 7. 本文件建议摘要

### 高优先级

1. 引入 `run_manifest.json`
2. 引入 `contract_report.json`
3. 扩大 lint/typecheck/test 覆盖到 `autoresearch_sandbox`
4. 将主矩阵与增强层结果命名空间分离

### 中优先级

1. 明确统一入口命令
2. 把 `public_api` 从模块转发升级为领域能力接口
3. 将 env 驱动逐步升级为 typed spec 驱动

## 8. 本文件结论

如果说当前架构问题主要是“边界还不够硬”，那么当前工作流问题主要是“实验协议还不够显式”。对你的研究目标而言，后者是必须尽快补上的，因为论文最终需要的不是“我知道这次怎么跑的”，而是“任何人都能从产物中看出这次是怎么跑的”。
