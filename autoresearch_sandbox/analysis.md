## Autoresearch Evolution Analysis

Based on the automated testing of 9 weighting schemes plus the pure MGDA baseline across a highly constrained search space (`dual_annealing` maxiter=3 for sandbox speed), we observe the following:

### Score Rankings (Lower is better, True NRMSE metric)
1. **2_Inverse_RMSE:** `0.301632` 🏆 (Best)
2. **Pure_MGDA_Baseline:** `0.316909` 🥈
3. **6_Log_transformation:** `0.421870` 🥉
4. **8_AgMIP_Two_step_WLS:** `0.486574`
5. **1_Inverse_Variance:** `0.506532`
6. **3_CV_based_R_version:** `0.544377` (Stuck at initial guess)
7. **4_Min_Max_Normalization:** `0.544377` (Stuck at initial guess)
8. **5_Mean_Normalization_NRMSE:** `0.544377` (Stuck at initial guess)
9. **7_Equal_Contribution:** `0.544377` (Stuck at initial guess)
10. **9_Pareto_Dominance:** `0.636959`

### Key Insights

1. **Inverse RMSE is Highly Effective:** 
   The `2_Inverse_RMSE` strategy dynamically scales the errors of `Yield` and `LAI` by their respective baseline RMSE (which simplifies to normalizing by the mean squared magnitude of the observations). This prevents the large numerical scale of Yield (thousands) from completely dominating LAI (single digits), leading to the best global optimization result.

2. **Pure MGDA is a Strong Baseline:**
   The `Pure_MGDA_Baseline` (which uses a simple NRMSE sum without grouping) performed exceptionally well, scoring `0.316909`, very close to the best weighted strategy. This validates that when errors are properly normalized to the same scale, a pure multi-objective scalarization without subjective weighting is highly competitive.

3. **Log Transformation handles Scale Disparity:**
   The `6_Log_transformation` strategy also performed reasonably well (`0.421870`), proving that logarithmic scaling is another effective way to handle the massive scale differences between Yield and LAI.

4. **Optimization Stagnation on Certain Topologies:**
   Strategies 3, 4, 5, and 7 returned a score of `0.544377` with the final parameters exactly matching the `INITIAL_GUESS`. This suggests that these loss topologies were either completely flat (zero gradient) in the local neighborhood, or they created numerical instability (e.g., extremely small gradients) that caused the `Nelder-Mead` local search within `dual_annealing` to terminate prematurely. For instance, the R-version CV-based approach (`3_CV_based`) uses an exponential function which can quickly underflow to 0 if the initial guess is far from the truth, creating a completely flat loss landscape where the optimizer cannot find a direction to move.

### Next Steps
1. The **Inverse RMSE** logic or the **Pure MGDA (NRMSE Sum)** should be the foundation for our production strategy.
2. The flat-gradient issue with exponential fitness functions (like the R-version approach) highlights the danger of using heavily penalized exponential fitness without a very good initial guess.
3. In a production run, we will increase the `maxiter` of `dual_annealing` to allow deeper exploration of the parameter space.

## 2026-03-26 W8 negative_optimization 复盘

### 结论

- W8 在 sandbox 中被判定为 `negative_optimization`，主因不是 W8 本身失效，而是 baseline 比较口径与可行域口径不一致。
- sandbox 的 `B0 External Baseline` 直接使用了 DSSAT 官方参数 `INITIAL_GUESS = [9.33, 3.12, 331.4, 12.87, 62.22, 2.215, 86.00]`。
- 这组参数与当前 `project_wheat.json` 的边界不一致：`P5 >= 550`、`G2 <= 60`、`G3 <= 2.1`、`PHINT >= 95`。
- 也就是说，baseline 实际运行在“边界外”，而优化器只能在“边界内”搜索。此时把边界内最优结果与边界外参考值直接比较，会系统性制造 `negative_optimization`。

### 已验证的数值

- 外部 baseline（未裁剪官方参数）得分：`0.417561`
- 可行域 baseline（按 sandbox 边界裁剪后）得分：`0.469857`
- W8 + O1 + S2 + G3 得分：`0.463468`
- W8 + O2 + S2 + G3 得分：`0.370379`

这说明：

- 若对照“外部 baseline”，W8 + O1 会被错误标记为负优化，因为 `0.463468 > 0.417561`。
- 若对照“可行域 baseline”，W8 + O1 实际已经优于 baseline，因为 `0.463468 < 0.469857`。
- 新接入的 O2 pestpp-ies 在同一设置下进一步优于两类 baseline。

### 第二个原因：W8 权重实现曾与 DSSAT-PEST 不完全一致

- `eval.py` 原来的 W8 权重实现是把同组指标拼接后取整体最大值。
- `build_pest_setup.py` 的实现是先按 DSSAT-PEST 观测组分组，再取组内观测绝对值最大值。
- 两者在当前 G3 分组下虽然多数情况下数值接近，但语义并不完全一致，会造成 sandbox 与 DSSAT-PEST 的口径偏差。
- 当前已将 `eval.py` 的 W8 逻辑改为按组最大值计算，并与 PEST 建模侧保持一致。

### O2 pestpp-ies 运行层问题与修复

- 初次接入 O2 时，`build_pest_setup.py` 在表型阶段报错 `No usable observations`。
- 根因是 IES 分阶段运行时只设置了 `PEST_ACTIVE_METRICS`，但没有同步注入 `DSSAT_EXTRA_SUMMARY_VARS`，导致 A 文件中的 `ADAP/MDAP/CWAM/HWUM` 未被纳入观测提取。
- 结果是第一阶段只生成了 `LAID` 这类 T 文件观测，而这些观测又被阶段过滤置零，最终变成“没有可用观测”。
- 当前已在 sandbox 的 O2 运行入口中补充 `DSSAT_EXTRA_SUMMARY_VARS=ADAP,MDAP,CWAM,HWUM`，O2 顺利完成整条 S2 顺序标定链。

### 当前实现调整

- `eval.py`
  - 增加 O2 `pestpp-ies` 真实执行通道
  - 增加 W8 组最大值权重对齐逻辑
  - 增加 `AR_BASELINE_PARAM_SOURCE`，支持区分外部 baseline 与可行域 baseline
  - 增加 IES 阶段参数、观测、预算和结果回收逻辑
- `auto_evolve.py`
  - 保留 `B0 External Baseline` 作为对外复现实验参考
  - 新增 `B0 Feasible Sandbox Baseline`
  - `negative_optimization` 判定改为对照可行域 baseline，而不是边界外 baseline

### 现阶段判断

- `DSSAT-PEST` 中 W8 优于官方参数，与 sandbox 当前结果并不矛盾。
- 真正矛盾的是：sandbox 之前把“边界外官方参数”当成了“边界内优化实验”的统一基线。
- 修正比较口径后，W8 的表现恢复为合理状态；进一步接入 O2 后，W8 还能继续提升。

## 2026-03-27 第四轮实验总结

### 是否应该先做总结

- 应该，而且要优先做。
- 原因不是“为了留档”，而是当前实验已经进入“平台期识别”阶段：如果不先把前几轮的口径、配置、结果和结论整理清楚，后续再做 phase3、多目标优化或论文写作时，很容易把不同评分口径、不同边界条件、不同 baseline 的结果混在一起。
- 这份总结将同时承担三类用途：后续探索的决策依据、论文方法与结果部分的素材池、以及复现实验时的口径说明。

### 口径说明

- 2026-03-25 的早期 sandbox 权重筛选，主要用于“方法启发”，不宜与当前第四轮正式矩阵结果直接横向比较。
- 主要原因有三点：
  - 当时搜索空间与求解预算更受限。
  - baseline 与可行域口径后来发生了修正。
  - W8 权重实现和 O2 观测提取逻辑后来都做过对齐与修复。
- 因此，早期结果适合回答“哪些方法值得继续保留”，而第四轮结果才适合回答“在当前正式口径下谁更优”。

### 前几轮结果归纳

#### 第一类：早期权重与求解器筛选

- 早期快速筛选表明，Inverse RMSE、Pure MGDA、Log Transformation 是最值得保留的方法族。
- 与之相对，CV-based、Equal Contribution 等策略在当时更容易出现平坦梯度、停在初值附近或缺乏稳定改进。
- 这一步的价值不在于给出最终结论，而在于帮助我们缩小后续正式矩阵的候选空间。

#### 第二类：W8 负优化问题复盘

- 这一轮的核心结论是：此前的 `negative_optimization` 很大程度上来自比较口径不一致，而不是 W8 本身失败。
- 关键数值如下：
  - 外部 baseline：`0.417561`
  - 可行域 baseline：`0.469857`
  - W8 + O1 + S2 + G3：`0.463468`
  - W8 + O2 + S2 + G3：`0.370379`
- 这一轮带来的直接收益有三项：
  - 明确了“边界外官方参数”不能再直接充当“边界内优化实验”的统一基线。
  - 将 W8 的权重实现与 DSSAT-PEST 分组最大值口径对齐。
  - 为 O2 `pestpp-ies` 补齐额外 summary 指标注入，使顺序标定链可以稳定运行。

### 第四轮正式实验归纳

#### 第四轮共同基线

- 当前第四轮正式矩阵实验统一以 `b0_official_frozen` 作为对照，分数为 `0.295629`。
- 在当前正式口径下，`B1 Sandbox Feasible Baseline` 也同样为 `0.295629`。
- 这说明当前正式边界与评分口径已经不再制造“外部 baseline 更优、可行域 baseline 更差”的系统偏差。

#### 第四轮分批结果

| 子轮 | 计划 | 并行度 | 最优组合 | 最优分数 | 观察结论 |
| --- | --- | --- | --- | --- | --- |
| 4.1 | phase1_o1 | 4 | W0 + O1 + matrix + s1 + g1 | 0.295629 | 28 个 cell 全部可运行，结果全部持平 |
| 4.2 | phase1_o2 | 6 | W0 + O2 + matrix + s1 + g1 | 0.295629 | 28 个 cell 全部可运行，锁文件问题未再复现 |
| 4.3 | phase1_o3 | 8 | W0 + O3 + matrix + s1 + g1 | 0.295629 | 28 个 cell 全部可运行，继续维持平台 |
| 4.4 | phase2 | 8 | W1 + O1 + quick + s3 + g3 | 0.295629 | 聚焦搜索仍未打破平台，说明差异主要不是来自这组权重/引擎切换 |

#### 第四轮科学含义

- 当前最重要的结论不是“谁赢了”，而是“几乎所有正式组合都收敛到同一分数 `0.295629`”。
- 这说明当前实验体系已经出现明显平台：
  - 要么目标函数对不同权重/引擎的区分度不足；
  - 要么当前训练处理集合已经把最优区域压缩到了同一个局部盆地；
  - 要么输出指标过于聚合，掩盖了处理间与变量间的细微差异。
- 因此，后续探索的重点不应再是简单追加同层矩阵，而应转向：
  - 引入更能区分解的输出指标；
  - 切入 phase3 的多目标实验；
  - 或增加按处理、按指标、按阶段的误差拆解。

#### 第四轮工程含义

- 并行运行已经从 4 workers 稳定提升到 6，再到 8。
- 这说明此前 Windows 下的运行时准备与文件锁问题，已经不再是当前主矛盾。
- 从现在开始，瓶颈更偏向“实验设计与结果表达”，而不是“运行能否成功”。

### 当前输出是否满足论文写作

#### 当前输出已经具备的优点

- 已经有面向人工阅读的过程日志：`matrix_experiments.md`
- 已经有面向程序汇总的结构化表：`matrix_results.tsv`
- 已经记录了核心配置维度：weight、engine、budget、sequence、grouping
- 已经记录了核心评分维度：总分、negative reference、平均 NRMSE、产量指标 NRMSE 与偏差

#### 当前输出距离论文可直接使用还差什么

- 还不够，尤其不够支撑“结果部分”和“补充材料”。
- 当前最明显的不足有八项：
  - 缺少统一的 `run_id`、时间戳、代码版本、配置快照，后续复现和论文附录追踪不够稳。
  - `matrix_results.tsv` 只保留聚合后的总分与少量摘要指标，没有把最终参数向量单独结构化导出。
  - 缺少按处理编号拆解的误差表，无法直接支持“哪些处理改进了、哪些处理退化了”的论文叙述。
  - 缺少按观测变量拆解的完整指标表，目前更像运行摘要，而不是论文结果表。
  - 缺少模拟值与实测值的成对导出，无法直接画论文最常用的散点图、1:1 图、残差图。
  - 缺少运行代价与收敛信息，例如迭代次数、函数评估次数、运行时长、失败重试信息。
  - 当前 `Validation_Enabled: False`，`Valid_TRTS` 为空，意味着现有结果本质上仍是训练集口径，不足以支撑强结论的泛化表述。
  - 当前结果文件会累积历史记录，存在重复组合多次出现的情况，适合研发追踪，但不适合直接作为论文主表。

### 后续输出建议

#### 建议补充四类机器可读结果表

- `experiment_runs.tsv`
  - 每次运行一行，保存 `run_id`、时间、计划名、并行度、baseline 口径、代码版本、是否成功、运行时长。
- `experiment_params.tsv`
  - 每个运行的最终参数单独成表，保存 `P1V/P1D/P5/G1/G2/G3/PHINT`。
- `experiment_metrics_long.tsv`
  - 采用长表结构，保存 `run_id / trt / variable / obs / sim / error / nrmse / bias / split(train/valid)`。
- `experiment_summary.tsv`
  - 保存论文主表需要的精简字段，例如最佳分数、关键变量误差、是否优于 baseline、最优组合标签。

#### 建议补充四类论文图表素材

- 处理级观测值-模拟值 1:1 散点图数据
- 各指标 NRMSE/Bias 的分组柱状图数据
- 不同权重与引擎的热图矩阵数据
- phase3 多目标实验的 Pareto 前沿数据

#### 建议补充一个“可横比数据集”约束

- 后续所有正式实验，统一要求：
  - 固定数据划分口径；
  - 固定 baseline 口径；
  - 固定评分公式版本；
  - 固定参数边界版本；
  - 固定输出表头。
- 只有满足这五项的结果，才进入论文主分析表。

### 下一步建议

- 第一，继续保留这份总结并在每次正式批次结束后增量更新。
- 第二，下一阶段优先进入 phase3，但不要只看最终总分，要同步设计更细粒度输出。
- 第三，在进入论文写作前，最好先把结果导出链路改成“运行日志 + 结构化总表 + 处理级长表 + 图表原始数据”四层结构。
- 第四，如果后续要面向论文交付，结果输出模块本身应被视为正式研究基础设施，而不是单纯调试附属物。
