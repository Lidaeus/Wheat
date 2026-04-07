# 第一阶段实验实践指南

## 1. 文档定位

本文件不是论文总控，也不是结果总结，而是 **第一阶段正式实验的执行指南**。它回答四个实践问题：

1. 第一阶段到底要回答什么科学问题
2. 这些问题应如何被拆成可执行的实验批次
3. 每次运行必须落哪些结果，才能支撑后续数据处理与论文写作
4. 什么样的结果可以进入主文，什么样的结果只能作为边界或补充材料

本文默认前提是：

- 当前研究目标仍是五作物 DSSAT 遗传参数率定
- 第一阶段的角色是 **主矩阵核心筛选**
- 可以假设算力较充足，因此实践层面不再只做最小对照，而要同时兼顾 **问题识别、重复验证、后处理可用性**

## 2. 第一阶段要回答的科学问题

第一阶段不追求直接找出全局最低分组合，而是先建立足够清晰、可复用、可解释的主结论证据。

### 2.1 核心研究问题

1. `RQ1`：在多量纲观测共同进入率定时，`G3` 是否比 `G1` 更能缓解大数值变量支配，并提升组间误差平衡与运行稳定性。
2. `RQ2`：在观测分组已经固定后，`S2` 是否比 `S1` 更能减少参数代偿、降低负优化并改善参数合理性。
3. `RQ3`：在固定 `W × G × S` 协议环境下，`O1` 与 `O2` 的差异到底有多大，优化器是否真是主效应。
4. `RQ4`：`O1` 与 `O2` 的相对优劣是否依赖 `W`，即是否存在实质性的 `W × O` 交互。

### 2.2 第一阶段允许形成的结论类型

- 可以形成：`G` 是否值得保留为主轴、`S2` 是否应进入推荐协议、`O1/O2` 是否存在协议依赖、`W × O` 是否构成真实交互
- 可以形成：哪些结论跨作物较稳健，哪些只在个别作物成立
- 不应形成：预算越深越好、某个混合搜索一定优于所有主矩阵组合、真多目标已经重写主文结论

## 3. 第一阶段的固定契约

第一阶段必须先冻结实验契约，再比较组合。

### 3.1 基线与判定契约

- `B0`：官方参数基线，唯一 `negative_optimization` 判定锚点
- `B1`：sandbox 可行域诊断基线，只做解释，不参与优劣裁决
- `B2`：DSSAT-PEST 外部 benchmark，单列展示，不并入第一阶段排序

### 3.2 活跃设计轴

- `W = {W0, W4, W6, W8}`
- `O = {O1, O2}`
- `S = {S1, S2}`
- `G = {G1, G3}`

### 3.3 固定运行约束

- 第一阶段所有正式运行至少采用 `standard` 预算
- 每个作物必须先通过 Phase 0 可执行性检查，才能进入第一阶段正式比较
- 同一批次内必须冻结：
  - 数据划分口径
  - 参数边界版本
  - `B0/B1/B2` 定义
  - 评分函数版本
  - 输出表头版本
- 若脚本层存在 `O1` 的过渡命名，应在批处理入口中先建立稳定映射表，避免论文编号与脚本命名脱节

### 3.4 第一阶段暂不纳入的内容

- 自创新权重或 AI 演化策略
- `O3`、`O4`、`O5`
- `S3`
- 初始化增强
- 全局到局部混合搜索
- 多预算并排行为比较

这些内容统一放在后续稳健性层或探索层。

## 4. 第一阶段的总体设计策略

在算力充足前提下，第一阶段建议采用 **“识别子实验 + 全矩阵确认 + 重复复验”** 的三层结构，而不是只做最小对照，也不是一开始就只做大而全总表。

### 4.1 层 1：问题识别子实验

目的不是形成最终排名，而是先明确每个研究问题最敏感的比较对。

推荐批次如下：

1. **G 识别批次**
   - `W0 × O1 × S1 × G1`
   - `W0 × O1 × S1 × G3`
   - `W4 × O1 × S1 × G1`
   - `W4 × O1 × S1 × G3`
   - 可选复核：`W0 × O2 × S1 × G1/G3`

2. **S 识别批次**
   - `W8 × O1 × G3 × S1/S2`
   - `W8 × O2 × G3 × S1/S2`
   - `W4 × O1 × G3 × S1/S2`

3. **O 识别批次**
   - `W8 × G3 × S2 × O1/O2`
   - `W4 × G3 × S2 × O1/O2`

4. **`W × O` 识别批次**
   - `G3 × S2` 固定
   - 比较 `W0/W4/W6/W8 × O1/O2`

### 4.2 层 2：全矩阵确认批次

在识别批次没有暴露结构性错误后，执行每个作物的完整主矩阵：

- `4 × 2 × 2 × 2 = 32` 个组合 / 作物
- `32 × 5 = 160` 个唯一组合 / 五作物

全矩阵确认的目标不是简单补齐表格，而是验证：

- 识别批次得出的结论是否在完整矩阵中仍成立
- 是否出现只在局部对子里可见、但全矩阵里会消失的“假阳性规律”
- 哪些作物会成为真正的例外作物

### 4.3 层 3：重复复验批次

第一阶段正式结果不建议只基于单次运行。

推荐重复策略：

- `O1`：每个组合至少重复 `2` 次
- `O2`：每个组合至少重复 `5` 次

理由：

- `O1` 即便理论上更稳定，仍需检查工作目录、文件 staging、边界贴附和阶段收敛是否存在实现层抖动
- `O2` 具有更强的集合和随机性特征，单次结果不足以支撑稳健性判断

若希望统一后处理，可直接采用：

- 所有组合统一重复 `5` 次

这样会提高计算量，但能换来更干净的 rank stability 与 failure rate 统计。

## 5. 训练/验证设计

第一阶段不能只关心训练内最低分。

### 5.1 主验证方案

每个作物应在正式运行前冻结一个 **主验证划分**：

- 优先按 treatment 划分 train / valid
- 若处理数足够，优先采用“保留少量代表性处理为 valid”的固定划分
- 若作物数据覆盖多个年份或环境，则优先保留环境级验证，而不是仅 treatment 级验证

### 5.2 备用验证方案

若某作物数据不足以稳定支撑主验证集，则必须在文档中明确标记：

- 该作物第一阶段结果属于“训练内协议比较”
- 只能用于协议排序线索，不用于强泛化结论

### 5.3 充足算力下的增强做法

对第一阶段筛出的代表性组合，建议追加：

- 留一处理验证
- 留一环境验证
- 替代 split 复验

但这些属于第一阶段的 **确认性增强批次**，不是所有格点的默认要求。

## 6. 第一阶段的正式实验矩阵

### 6.1 必跑基线

每个作物都必须先跑：

- `B0`
- `B1`
- `B2`

其中：

- `B0` 用于主裁决
- `B1` 用于判断边界约束本身的影响
- `B2` 用于回答“外部完整 DSSAT-PEST 契约”的表现

### 6.2 主矩阵格点

每个作物正式主矩阵为：

- `W0 × O1/O2 × S1/S2 × G1/G3`
- `W4 × O1/O2 × S1/S2 × G1/G3`
- `W6 × O1/O2 × S1/S2 × G1/G3`
- `W8 × O1/O2 × S1/S2 × G1/G3`

### 6.3 推荐执行顺序

建议分四个批次执行，而不是把 32 个组合一次性混跑：

1. **Batch A：`G` 识别**
2. **Batch B：`S` 识别**
3. **Batch C：`O` 识别**
4. **Batch D：全矩阵确认与 `W × O` 交互**

这样做的好处是：

- 一旦发现某类比较存在目标口径不一致或分组映射问题，可以在扩大批次前先修正
- 结果解释天然按研究问题组织，后续写论文不必再从大总表中倒推叙事

## 7. 每次运行必须记录的原始输出

第一阶段的一个核心原则是：**后处理需求决定原始结果的最小落盘粒度**。

只保留 `Final_Score` 远远不够。

### 7.1 运行级摘要表

建议文件：`phase1_experiment_summary.tsv`

至少包含以下字段：

- `run_id`
- `combo_key`
- `executed_at`
- `plan`
- `weight`
- `engine`
- `budget`
- `sequence`
- `grouping`
- `status`
- `score`
- `delta_vs_b0`
- `delta_vs_b1`
- `delta_vs_negative_ref`
- `better_than_b0`
- `train_mean_nrmse`
- `valid_mean_nrmse`
- `all_mean_nrmse`
- `train_yield_nrmse`
- `train_yield_bias`
- `valid_yield_nrmse`
- `valid_yield_bias`
- `duration_sec`
- `validation_enabled`
- `train_trts`
- `valid_trts`
- `workspace_dir`

这些字段与现有 [result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L162-L196) 的摘要输出口径是一致的。

### 7.2 指标聚合长表

建议文件：`phase1_aggregate_metrics.tsv`

至少包含：

- `run_id`
- `plan`
- `weight`
- `engine`
- `budget`
- `sequence`
- `grouping`
- `status`
- `split`
- `metric`
- `count`
- `nrmse`
- `bias`

这些字段与 [result_schema.py:L145-L159](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L145-L159) 一致。

### 7.3 处理级长表

建议文件：`phase1_treatment_metrics.tsv`

至少包含：

- `run_id`
- `plan`
- `weight`
- `engine`
- `budget`
- `sequence`
- `grouping`
- `status`
- `trt`
- `split`
- `metric`
- `observed`
- `simulated`
- `error`
- `abs_error`
- `relative_error`

这些字段与 [result_schema.py:L125-L142](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L125-L142) 一致。

### 7.4 参数表

建议文件：`phase1_parameters.tsv`

至少包含：

- `run_id`
- `crop`
- `combo_key`
- `param_name`
- `param_value`
- `lower_bound`
- `upper_bound`
- `is_at_lower_bound`
- `is_at_upper_bound`
- `normalized_distance_to_b0`

参数表是后续分析“贴边”“参数漂移”“重复稳定性”的前提，不能只保留最终屏幕日志。

### 7.5 图表就绪表

建议文件：`phase1_figure_ready.tsv`

至少包含：

- `run_id`
- `score_rank`
- `combo_key`
- `plan`
- `weight`
- `engine`
- `budget`
- `sequence`
- `grouping`
- `status`
- `score`
- `metric`
- `split`
- `trt`
- `panel_key`
- `series_key`
- `point_key`
- `x_observed`
- `y_simulated`
- `residual`
- `abs_residual`
- `relative_error`
- `panel_count`
- `panel_nrmse`
- `panel_bias`

这些字段与 [result_schema.py:L242-L268](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L242-L268) 对齐。

## 8. 后处理阶段必须计算的派生指标

第一阶段若想支撑论文主文，除了原始字段，还必须形成一批可比较的派生指标。

### 8.1 主裁决指标

1. **Primary Score**
   - 优先使用 `Final_Valid_Score`
   - 若无验证集，则降级为 `Final_All_Score`，并显式标记为训练内比较

2. **Negative Optimization Rate**
   - 定义：相对 `B0` 退化的运行比例
   - 这是主文推荐与否的硬约束

3. **Failure Rate**
   - 定义：运行失败、最终评估失败、关键指标缺失、严重不收敛的比例

### 8.2 稳健性指标

1. **Rank Stability**
   - 同一组合跨重复运行的平均排名、排名标准差、最差排名

2. **Repeatability Spread**
   - 同一组合跨重复运行的 `score` 标准差、`valid_mean_nrmse` 标准差

3. **Cross-Crop Consistency**
   - 组合在五作物上的中位排名
   - 组合在五作物上的排名方差
   - 优于 `B0` 的作物比例

### 8.3 机制解释指标

1. **Group Balance Index**
   - 同一 split 下各 metric 的 `nrmse` 标准差
   - 值越小，说明协议没有把某一类观测严重牺牲掉

2. **Generalization Gap**
   - `valid_mean_nrmse - train_mean_nrmse`
   - 用于判断深度搜索或高适配解是否只是训练内变好

3. **Yield Guard Metrics**
   - `TRAIN/VALID_HWAM_NRMSE`
   - `TRAIN/VALID_HWAM_BIAS`
   - 若是其他作物，应使用其主产量变量替代

4. **Phenology Guard Metrics**
   - `ADAP/MDAP` 或等价物候指标的 `NRMSE/MAE/BIAS`
   - 防止协议靠牺牲物候换来产量局部收益

5. **Canopy / Biomass Guard Metrics**
   - `LAIX`、`CWAM` 等指标的 `NRMSE/BIAS`
   - 用于识别“总分更好但过程结构更差”的组合

### 8.4 参数合理性指标

1. **Boundary Hit Rate**
   - 命中上下界的参数数 / 总参数数

2. **Normalized Parameter Shift**
   - `mean(abs(theta - theta_B0) / (ub - lb))`
   - 用于衡量协议是否需要通过剧烈参数漂移才能改善分数

3. **Parameter Repeatability**
   - 同一组合跨重复运行时各参数的标准差
   - 用于识别“分数稳定但参数漂移很大”的伪稳健情况

### 8.5 交互识别指标

1. **Engine Advantage by Weight**
   - 对每个 `W` 计算 `score(O2) - score(O1)`
   - 观察符号是否翻转

2. **Weight Sensitivity by Engine**
   - 对固定 `O1` 或 `O2`，计算不同 `W` 间的分数跨度

3. **Protocol Lift**
   - `S2 - S1`
   - `G3 - G1`
   - `W8 - W4`
   - 全部用配对差值而不是裸分数看

## 9. 第一阶段的统一复评要求

若不同引擎内部使用的目标表达并不完全同构，则必须增加 **统一复评**。

### 9.1 统一复评的目的

- 分离“算法差异”和“目标实现路径差异”
- 避免某个引擎只是因为内部 `phi` 定义不同而在表面上占优

### 9.2 统一复评的做法

对每个最终参数解，都要用同一个统一评价器重新计算：

- `Final_Train_Score`
- `Final_Valid_Score`
- `Final_All_Score`
- 各 metric 的 `NRMSE`
- 各 metric 的 `BIAS`

只有统一复评后的结果，才能进入第一阶段主分析表。

## 10. 第一阶段的判定规则

### 10.1 单作物层面的判定

某组合若满足以下条件，可在单作物内被视为“有效候选”：

- 相对 `B0` 不发生负优化
- `Final_Valid_Score` 或主评分优于主要对照
- 失败率低
- 组间误差没有明显恶化
- 参数未出现大面积贴边

### 10.2 跨作物层面的判定

某组合若满足以下条件，可进入主文推荐讨论：

- 在至少 `3/5` 个作物上优于 `B0`
- 五作物中位排名进入前列
- 排名方差不过大
- 负优化率与失败率均处于较低水平

### 10.3 不得直接宣称为更优协议的情况

- 总分略好，但负优化率显著更高
- 总分略好，但参数普遍贴边
- 均值略好，但重复运行方差很大
- 只在单作物显著占优，其他作物普遍一般或退化

## 11. 推荐的批处理规模

若采用“主矩阵全跑 + 重复复验”的正式口径，可参考下列规模：

### 11.1 唯一组合数

- 主矩阵：`32 × 5 = 160`
- 基线：`3 × 5 = 15`
- 总唯一配置：`175`

### 11.2 含重复的正式运行数

若采用：

- `O1` 每格 `2` 次
- `O2` 每格 `5` 次

则五作物主矩阵总运行数约为：

- 每作物 `16 × 2 + 16 × 5 = 112`
- 五作物共 `560`
- 再加 `B0/B1/B2` 与必要复评，第一阶段完整工作量约为 `600+` 次运行

若采用统一 `5` 次重复，则五作物主矩阵为：

- `160 × 5 = 800`

在算力充足前提下，后一种更利于做 rank stability 和 failure rate 的正式统计。

## 12. 推荐图表与主表

### 12.1 主表

- Table P1：第一阶段主矩阵组合与重复策略
- Table P2：五作物主结果汇总表
- Table P3：`G3 vs G1`、`S2 vs S1`、`O1 vs O2` 的配对差值表
- Table P4：`W × O` 交互表
- Table P5：负优化、失败率与边界命中表

### 12.2 主图

- Figure P1：第一阶段实验路线图
- Figure P2：五作物主矩阵热图
- Figure P3：`G3` 与 `G1` 的分组效应对比图
- Figure P4：`S2` 与 `S1` 的协议提升图
- Figure P5：`O1` 与 `O2` 在不同 `W` 下的交互图
- Figure P6：代表组合的 observed-simulated 散点与残差面板

## 13. 最终建议

第一阶段最值得避免的错误有三类：

1. **只看最低分，不看负优化、失败率和参数合理性**
2. **只保留运行摘要，不保留处理级长表与参数表**
3. **把不同引擎内部不同目标表达的结果直接并排，而不做统一复评**

因此，第一阶段最推荐的实践口径是：

- 先冻结契约
- 再做问题识别批次
- 再做五作物全矩阵确认
- 再做重复复验和统一复评
- 最后用“主分数 + 负优化 + 稳健性 + 参数合理性”四类证据共同决定主文结论

一句话概括：

> 第一阶段不是“刷一个最低分冠军”，而是用一个高重复、可复评、可后处理的正式实验矩阵，先把 `G`、`S`、`O` 和 `W × O` 这四类主问题回答清楚，并为后续论文主结果提供可以直接落表和落图的数据基础。
