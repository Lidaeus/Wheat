# 架构与研究适配性审查

## 1. 评审结论

从顶层设计看，当前项目已经基本走在 [05_Refactor_Blueprint.md](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/Research_Artifacts/05_Refactor_Blueprint.md#L63-L125) 预期的方向上，但**只完成了“共享能力开始内聚”的阶段，还没有完成“共享内核成为更稳定公共边界”的阶段**。

换句话说：

- 架构方向是对的
- 兼容性保留做得也合理
- 但“内核层 / 工程层 / 研究层”的边界仍然偏软

## 2. 与研究主线的匹配度

### 2.1 与论文方法主线的正向匹配

论文主线要求项目能稳定支撑：

- `W × O × S × G` 主实验矩阵
- `B0` 外部基线
- 预算、初值、局部最优风险等增强层分析
- 五作物并可进一步扩展到更多作物

当前实现中，以下设计已经明显与该主线对齐：

- `auto_evolve.py` 将 `weight / engine / budget / sequence / grouping` 显式建模 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L500-L605)
- `result_schema.py` 将实验结果对象化、导出表结构统一化 [result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L45-L123)
- `public_api.py` 为研究层访问工程能力提供了统一入口 [public_api.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/public_api.py#L9-L32)

这使“研究矩阵”第一次具备了较清楚的工程映射，满足论文大纲中“方法框架贡献”和“工程实现贡献”的叙述基础。

### 2.2 与研究主线的主要偏差

当前的偏差不在于“没有实现”，而在于“实现边界还不够稳定”：

1. 共享内核没有彻底抽离
2. 多作物抽象没有成为第一公民
3. 主矩阵与增强层的数据边界没有完全制度化

## 3. 三层架构完成度评估

### 3.1 共享内核层

已迁移进入 `calibration_core` 的能力包括：

- PEST 构建 [calibration_core/pest_builder.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_builder.py#L174-L225)
- PEST 运行与结果解析 [calibration_core/pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py#L21-L48) [calibration_core/pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py#L169-L307)
- 结果 schema 与导出契约 [calibration_core/result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L315-L425) [calibration_core/result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L552-L938)

这部分重构是成功的，尤其是 `result_schema`，它已经表现出“稳定公共契约层”的特征。

但共享内核仍存在两个问题：

#### 问题 A：内核仍被拆散在 `src` 顶层

以下模块仍是关键运行能力，却没有收口到 `calibration_core`：

- [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)
- [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py)
- [case_runtime.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/case_runtime.py)
- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py)

这意味着当前共享内核仍然是“半包化、半脚本化”的。

#### 问题 B：兼容包装器虽然有价值，但还缺正式策略

例如：

- [src/pest_builder.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/pest_builder.py#L1-L38)
- [src/pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/pest_runner.py#L1-L13)
- [src/result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/result_schema.py#L1-L115)

这些包装器对稳定迁移非常有用，但当前看起来更像“长期并存”而不是“有节奏地退场”。如果未来继续增长，会造成：

- 文档边界模糊
- 静态分析路径混乱
- 新贡献者难以判断该依赖哪一层

### 3.2 工程执行层

工程执行层最强的部分，是已经拥有较清晰的“标准运行链”：

- `run_model.py` 负责 case 运行 [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py#L405-L521)
- `build_pest_setup.py` 负责构建 PST 与观测权重 [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L963-L1029)
- `case_runtime.py` 负责运行时文件与输入计划 [case_runtime.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/case_runtime.py#L68-L116) [case_runtime.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/case_runtime.py#L137-L204)

这一点非常符合蓝图中“稳定、可复核、可批量运行的标准率定工作流”的要求。

但工程层还有两个架构问题：

#### 问题 A：工程层承担了过多“策略解释责任”

例如 `build_pest_setup.py` 中不仅在做构建，还在承载：

- 权重模式选择
- train/valid 切分
- MGDA alpha 反馈
- 活跃指标过滤

这在功能上能跑，但从架构上说已经接近“执行层 + 一部分研究策略层”的混合体。

#### 问题 B：工程层的“标准协议”还没有 manifest 化

当前协议更多是：

- `project.json`
- 环境变量
- 当前工作目录
- 若干运行时文件

而不是一个可序列化、可归档、可审计的单次运行说明书。

这对论文来说是一个实际风险，因为你后面需要证明：

- 某个结果属于主矩阵
- 某个结果属于增强层
- 某个结果使用了哪些边界、权重、分组、预算和初值协议

### 3.3 研究探索层

研究层目前有两个明显优点：

#### 优点 A：已经开始通过公共入口访问工程能力

- `eval.py` 通过 [public_api.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/public_api.py#L21-L32) 动态加载稳定模块 [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L33-L45)
- `auto_evolve.py` 将路径、产物目录、报表目录结构化 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L53-L171)

这说明研究层已经不再是直接硬连私有脚本路径的旧形态。

#### 优点 B：研究产物目录比过去更规范

`build_sandbox_paths()` 已经把：

- runs
- runtime
- artifacts
- 多种表格产物

明确分开，这非常有利于论文产物积累与批量实验追踪。

但研究层仍有两个值得关注的演化限制：

#### 缺陷 A：路径耦合虽然下降，但仍偏“项目内协作”，不是“稳定 SDK”

`eval.py` 和 `auto_evolve.py` 仍建立在“知道 `mvp_pest_mgda/public_api.py` 在哪里”的前提下 [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L72-L95) [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py#L107-L171)。

这比直接 import 私有模块已经强很多，对单仓库研究项目来说也是合理过渡；但如果后续还要持续扩展，仍建议逐步把这层边界做得更显式。

#### 缺陷 B：研究层仍在承担一部分主矩阵与报告解释逻辑

当前 `auto_evolve.py` 同时负责：

- 组合生成
- 运行编排
- 结果汇总
- leaderboard / appendix / paper table 生成

这会让研究代码变成“大型单文件方法平台”。它短期高效，长期会变成维护热点。

## 4. 对未来“支持 DSSAT 所有作物”的架构判断

如果把“支持 DSSAT 所有作物遗传参数率定”视为长期目标，那么当前架构最重要的缺口不是优化器数量，而是**作物知识抽象层缺失**。

目前已经有：

- `crop_family`
- 参数 alias/mapping
- 多作物配置文件

但还没有真正形成统一的“作物注册表”对象来表达：

- cultivar 文件类型与定位规则
- 观测主指标集合
- 可用阶段模板
- 分组字典
- 默认边界来源
- 输出变量语义映射

因此，当前的多作物支持更像是“多份配置文件 + 若干回退逻辑”，还不是“正式的多作物平台抽象”。

## 5. 架构级建议

### 5.1 建议新增 `crop_registry`

建议把以下信息统一成注册表：

- `crop_family`
- 参数主名与别名
- 阶段模板 `S2/S3`
- 观测分组模板 `G1/G3`
- 指标族定义
- 默认 `yield_var / laix_var / t_vars`
- 官方 bounds 来源与裁剪规则

这样可以把当前分散在：

- `dssat_io.py`
- `observations.py`
- `build_pest_setup.py`
- `auto_evolve.py`

中的作物知识收口为一个稳定层。

### 5.2 建议把共享内核逐步收口为更稳定的公共边界

中期目标应该是：

- 工程层和研究层都只依赖 `calibration_core`
- 顶层 `src/*.py` 只保留短期兼容入口
- 新增功能默认只进 `calibration_core`

### 5.3 建议把“主矩阵”与“增强层”在架构上分成两套 profile

建议显式区分：

- `matrix_profile`
- `robustness_profile`

避免预算、初始化、多启动等增强协议在导出与报告阶段重新污染主矩阵结论。

## 6. 本文件结论

当前架构已经具备继续推进研究的能力，但还不够“论文级稳定”。从落地优先级看，更合理的顺序是：

1. 先补显式实验协议与结构化契约报告
2. 再把多作物知识提升为正式抽象
3. 然后分阶段收口共享内核边界
4. 最后再推进更服务化的公共边界
