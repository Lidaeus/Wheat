# AutoResearch 研究资产提取与异机复验指南

## 1. 文档目的

本文从以下历史研究记录中提取可迁移的发现、方法、策略、实验框架、权重方案与待验证假设，供在另一台计算机上继续复验与扩展：

- `docs/第一轮AutoResearch审查与改进记录.md`
- `docs/第二轮AI自我创新搜索结论与四维矩阵实验框架.md`
- `docs/第三轮AI自我创新搜索结论_真实AgMIP两步链路.md`
- `docs/2026-03-26_第四轮AI自我创新搜索规划.md`
- `docs/2026-03-27_DSSAT-PEST边界与DSSAT官方范围一致性调研.md`
- `docs/2026-03-27_phase3参数边界与极端参数说明.md`
- `docs/2026-03-28_跨作物Maize推进总结与下一轮计划.md`
- `docs/2026-04-02_Maize下一轮实验记录.md`
- `docs/20260405_o2_phase3_formal_research_summary.md`
- `autoresearch_sandbox/analysis.md`

本文不是原始结果逐条复述，而是把其中对后续研究真正有价值的“可复验资产”抽取出来。

## 2. 使用原则

- 早期结果与后期正式结果不能直接横向比较，因为评分口径、baseline 口径、边界口径、预算和实现都发生过变化。
- 建议把历史信息分成三层使用：
  - **启发层**：用于生成候选方法，不直接当正式结论
  - **正式层**：仅使用统一口径、统一边界、统一输出表头的结果
  - **增强层**：用于解释机制、做稳健性分析、形成附录或后续探索线
- 后续异机复验时，应优先保留“问题定义、候选方法、实验框架、输出口径、待验证假设”，而不是死守某一轮的单次最低分

## 3. 当前最值得保留的高价值发现

### 3.1 权重与损失构造方面

- **消除量纲支配始终是核心问题**
  - 早期筛选和后续文档都反复支持：若产量与 LAI 不做合理尺度处理，Yield 的大数值会主导优化。
  - 因此“均值归一化 / NRMSE / 对数变换 / 组内缩放”不是可选修饰，而是联合率定的基础前提。

- **Log-transformation、NRMSE 类、MGDA 基线值得长期保留**
  - 第一轮中 `6_Log_transformation`、`5_Mean_Normalization_NRMSE`、`Pure_MGDA_Baseline` 都表现突出。
  - 早期 `analysis.md` 中 `2_Inverse_RMSE` 也表现很好。
  - 这些方案应视为后续所有新策略的稳健对照组，而不是一次性试验品。

- **动态权重并不天然更好**
  - `AgMIP 两步 WLS`、`CV-based` 等动态或伪方差型方案在无导数优化器下可能导致目标面抖动，诱发负优化或停滞。
  - 结论不是“它们永远无效”，而是：
    - 对优化器家族高度敏感
    - 必须在固定预算、固定顺序、固定目标语义下重新审视

- **sandbox 原生最优公式的结构值得长期保留**
  - 第二轮搜索与第四轮归因中，当前强 baseline 可概括为：
    - Yield：`SMAPE`
    - LAI：`log-RMSE`
    - 聚合器：`L2` 或 `0.5 mean + 0.5 max`
    - 形状系数：`1.15`
    - balance penalty：`0.25`
    - treatment variance penalty：`0.12`
    - cross penalty：`0.05`
  - 这类“尺度公平 + 平衡惩罚 + 跨处理波动惩罚 + 轻耦合约束”的组合，是 sandbox 原生 loss 最值得继续深挖的方向。

### 3.2 优化器与协议方面

- **优化器优劣具有明显问题依赖性**
  - 五作物矩阵显示：
    - Wheat / Soybean / Rice 更偏向 O1
    - Maize / Cotton 更偏向 O2
  - 这不支持“某个引擎普遍最优”，而支持“优化器表现依赖率定问题结构”的判断。

- **分阶段率定 `S2` 是主线资产**
  - “先物候、后冠层/生物量、再产量”的链路一再被证明更有解释力。
  - 文献、AgMIP 思路与当前工程实践在这一点上是合流的。
  - 后续凡是继续做增强层实验，默认都应优先建立在 `S2` 可稳定运行的前提上。

- **分组 `G3` 与组内尺度处理有独立价值**
  - 分组不只是 `W8` 的附属品。
  - 它在抑制大数值变量支配、降低失败风险、建立生理过程解释方面具有独立方法学作用。

- **`MGDA -> O1` 混合框架是当前最有潜力的工程主线**
  - Maize 上已出现明确正证据：
    - 纯 MGDA 找到更好的盆地
    - 再用 O1 局部精修，可进一步降低综合 score
  - 这条主线比单纯扩大 O2 网格更值得继续投入。

- **O2 更适合做两类事情**
  - 某些作物上的正式候选引擎
  - 阈值/失稳机理诊断工具
  - 在 Maize 上，O2 阈值行为清楚地暴露了 ensemble 尺寸与 conflict / stagnation 的关系，这对解释为什么某些引擎不稳非常有价值。

### 3.3 边界与 baseline 方面

- **DSSAT-PEST 继承边界不是 DSSAT 官方合法域**
  - 这一点非常关键，且后续研究必须长期坚持。
  - 应明确区分三层语义：
    - 官方合法域
    - DSSAT-PEST 继承边界
    - 当前项目修订边界

- **baseline 必须与优化器处于同一可行域**
  - 过去 `negative_optimization` 误判的根因之一，就是 baseline 在边界外，优化器在边界内。
  - 这类比较口径错误会系统性污染结论。

- **Wheat 的项目修订边界调整具有明确研究价值**
  - 放宽 `P5 / G2 / G3 / PHINT` 并不是为了“让优化器赢”，而是为了把官方 cultivar 邻域重新纳入搜索空间。
  - 这类边界修订需要在异机复验时保留原始理由，而不是只复制数值。

### 3.4 观测与指标链路方面

- **物候指标链路必须被视为优先级极高的门禁项**
  - 当前已经出现过重要教训：观测侧用 `ADAT/MDAT`，模拟侧用 `ADAP/MDAP`，若别名不对齐，第一阶段会变成“空监督”。
  - 这类问题不只是 bug，而是会直接改变对 `S2` 是否有效的判断。

- **“当前阶段不设验证集”是一个明确研究边界，不是疏漏**
  - 多份文档都明确：当前主线阶段重在统一口径下的公平比较，而不是泛化结论。
  - 因此异机复验时可以继续采用 train-only，但必须在文档里明确写出该边界。

## 4. 值得保留的候选权重/损失方案池

### 4.1 稳健对照池

- `2_Inverse_RMSE`
- `5_Mean_Normalization_NRMSE`
- `6_Log_transformation`
- `Pure_MGDA_Baseline`
- `W8_DSSAT_PEST_Group_Max`

### 4.2 风险但值得重审的方案池

- `3_CV_based_R_version`
- `8_AgMIP_Two_step_WLS`
- `7_Equal_Contribution`

这些方案不应被简单丢弃，原因是：

- 早期表现差，可能来自预算过低、优化器不匹配或目标不平滑
- 它们更适合作为“增强层 / 条件性方案 / 目标家族诊断对象”

### 4.3 sandbox 原生 loss 候选 family

后续创新搜索最值得继续围绕以下结构做 bounded innovation：

- `mean_relative_error + imbalance_penalty`
- `nrmse_like + treatment_variance_penalty`
- `log_error + relative_yield_guard`
- `smape_like + max_component_guard`
- `mean + max` 复合聚合器
- 轻量 cross penalty

建议继续冻结的约束：

- 只输出有限标量
- 无 I/O、无随机隐藏状态
- 同一输入下确定性输出
- 不修改评分语义，只在 loss 结构内部创新

## 5. 值得保留的实验框架

### 5.1 主矩阵框架

- 主矩阵固定为：`W × O × S × G`
- 当前主矩阵核心层：
  - `W = {W0, W4, W6, W8}`
  - `O = {O1, O2}`
  - `S = {S1, S2}`
  - `G = {G1, G3}`

这个框架的价值是：

- 把“权重 / 优化器 / 顺序 / 分组”四类效应拆开
- 避免把局部技巧误写成普遍方法学结论

### 5.2 分阶段框架

- Phase 0：可执行性与链路闭环
- Phase 1：主矩阵核心筛选
- Phase 1.5：预算敏感性
- Phase 1.6：初始化敏感性与混合搜索
- 扩展层：`W1 / W7 / S3`
- 探索层：`O4(NSGA-II)` / `O5(MGDA)`

这个层级框架非常值得带到另一台机器，因为它能有效防止“组合爆炸 + 叙事混乱”。

### 5.3 当前最值得复现的 Phase 2 思路

Phase 2 不应重新扩成全矩阵，而应聚焦四类问题：

- 稳健性
- 增强协议
- 跨作物迁移
- 算力-收益

建议把以下字段固定为增强层统一输出：

- `Final_Score`
- `TRAIN/ALL_MEAN_NRMSE`
- 关键指标 `NRMSE / Bias`
- 失败率
- 参数合理性
- 边界贴附率
- `eval_call_count`
- `run_model_invocations`
- `dssat_treatment_calls`
- `dssat_wall_sec`

## 6. 现在最值得继续验证的研究假设

### 6.1 结构性假设

- **H-A**：决定 O1/O2 排序的不是作物名称，而是率定问题结构
- **H-B**：当前引擎差异中混有“算法差异”和“目标表达路径差异”
- **H-C**：边界吸附与固定参数比例会显著改变 O1/O2 排序
- **H-D**：少数关键指标可能主导最终排序
- **H-E**：当前 quick / standard 差异不是主导因素，搜索机制与目标结构匹配更关键

### 6.2 MGDA / Phase3 假设

- **H-F**：默认起点会让 MGDA 掉入低产保守盆地，LHS 多起点可显著改善 Pareto 质量
- **H-G**：`score-best` 与 `phenology-best` 在某些作物上可能重合，说明物候改善不一定与综合目标冲突
- **H-H**：`MGDA -> O1` 可把“找到好盆地”和“局部精修”两种能力耦合成更有效流程
- **H-I**：O2 的 ensemble 尺寸存在清晰阈值区间，过大可能导致 conflict 激增与停滞

### 6.3 sandbox 原生策略假设

- **H-J**：当前 `strategy.py` 已是强 baseline，不应假设继续盲搜必然还能显著改进
- **H-K**：真正有价值的创新不是继续发明任意公式，而是在固定评价契约下发现“更稳、更平衡、更可解释”的 loss

## 7. 异机复验时最值得优先跑的实验包

### 7.1 工作包 A：主矩阵正式复验

目标：

- 用统一 train-only 口径重建 `W × O × S × G` 主矩阵核心层

建议：

- 先跑 `standard`
- 先做 5 作物、1 repetition
- 统一输出结构化 summary 与 long table

### 7.2 工作包 B：目标一致性对照

目标：

- 判断 O1/O2 差异有多少来自目标路径不完全同构

设计：

- 收集 O1 与 O2 的代表参数
- 用统一评分逻辑重新复评两者
- 比较 `Final_Score` 排名与 O2 内部 `phi` 排名

### 7.3 工作包 C：边界敏感性实验

目标：

- 判断结论是否被边界结构放大

设计：

- 至少准备三层边界：
  - 当前项目修订边界
  - DSSAT-PEST 继承边界
  - 官方合法域内的适度扩展边界

### 7.4 工作包 D：指标消融与权重扰动

目标：

- 检查某些引擎优势是否由少数关键指标主导

建议优先消融：

- `HWUM`
- `LAIX`
- `CWAM`
- 物候指标组

### 7.5 工作包 E：`MGDA -> O1` 主流程复验

目标：

- 验证该框架是否具备跨作物稳定性

最小设计：

- `default / lhs / random` 多起点
- 保存 MGDA best、代表解、O1 refined
- 统计 5 作物平均 score、方差、排名稳定性

### 7.6 工作包 F：O2 阈值诊断

目标：

- 不再把 O2 当唯一主率定器，而是研究其失稳边界

建议输出：

- `ensemble size -> failures / conflict / stagnation / final_score`

## 8. 异机复验时必须保留的工程要点

- **固定宽度文件写回必须严格受控**
  - CUL / FileX 的列对齐问题是真实风险源，不是小问题

- **每个 worker 必须使用独立工作区与独立 case**
  - 共享工作目录会污染 DSSAT/PEST 结果

- **禁止把内部 loss 值当跨引擎比较指标**
  - O1 残差、O2 `phi`、O5 多目标 scalar 不是同一标度
  - 公平比较应继续以统一 `Final_Score` 为主

- **观测变量别名必须对齐**
  - 特别是 `ADAT/MDAT <-> ADAP/MDAP`

- **baseline 口径必须先写清**
  - 官方 baseline
  - 可行域 baseline
  - 外部 benchmark
  - 不能混用

- **train-only 必须显式写入运行口径**
  - 若不做验证集，就不能在结果叙事里偷偷使用“泛化更好”的说法

## 9. 建议在另一台电脑上优先保存和比对的结果表

建议至少统一导出以下四类表：

- `experiment_runs.tsv`
  - `run_id / time / crop / batch / worker / success / duration`

- `experiment_params.tsv`
  - `run_id / param_name / value`

- `experiment_metrics_long.tsv`
  - `run_id / crop / trt / metric / split / obs / sim / error / nrmse / bias`

- `experiment_summary.tsv`
  - `run_id / combo_key / final_score / key_metric_nrmse / baseline_delta / dssat_calls / dssat_wall_sec`

若继续做多目标实验，还应统一保留：

- `pareto_archive.tsv`
- `representative_solutions.tsv`
- `hybrid_refinement_summary.tsv`

## 10. 可直接继承的研究叙事

后续论文或报告可继续沿用下面这条主叙事：

- 主矩阵回答：
  - 哪类 `W × O × S × G` 组合值得推荐
  - 哪些差异属于协议结构主效应

- 增强层回答：
  - 预算、初始化、混合搜索是否只是在某些条件下增强主协议

- sandbox 自创新回答：
  - 在固定评价契约下，sandbox 原生 loss 是否能产生可归因的增益

- phase3 / 多目标回答：
  - 单目标最优是否掩盖了物候、冠层、生物量、产量之间的 trade-off
  - `MGDA -> O1` 是否能构成兼具精度、稳定性与可解释性的框架

## 11. 当前最推荐的复验优先级

### 第一优先级

- 五作物 `All + standard + train-only` 主矩阵正式复验
- 统一导出结构化结果表

### 第二优先级

- Wheat / Maize / Cotton 的 O1/O2 目标一致性与边界敏感性实验

### 第三优先级

- `MGDA -> O1` 的五作物复验
- Pareto 代表解拆解

### 第四优先级

- O2 阈值诊断补点
- sandbox 原生 loss 的 bounded innovation

## 12. 一句话摘要

从这批 AutoResearch 记录中真正值得带到另一台机器继续探索的，不是某一次偶然最低分，而是一整套已经逐步成形的研究资产：**统一的 `W × O × S × G` 主矩阵框架、明确分层的边界语义、以 train-only 为当前正式口径的公平比较原则、以尺度公平与组级解释为核心的损失构造思路、以及当前最有潜力的 `MGDA -> O1` 混合率定主线。**
