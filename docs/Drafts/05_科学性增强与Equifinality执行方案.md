# 科学性增强与 Equifinality 定量评估执行方案

## 1. 文档定位

本文件用于把“科学性增强”从一个宽泛愿景收缩成一条可落地、可交付、可在有限研究时间内完成的主线。它服务于三个直接目标：

1. 将“`S2` 可能降低参数代偿”改写为一个可检验、可分级表达的科学主张。
2. 将证据链从“误差是否更低”推进到“参数空间是否更收缩、参数相关是否更减弱、过程是否更一致”。
3. 将后续开发、分析、图表和论文回填压缩到一条最小可执行路径，避免任务继续发散。

本文件与以下文稿形成联动：

- [01_Paper_Outline copy.md](file:///d:/Wheat/Parallel_Exp/docs/Drafts/01_Paper_Outline%20copy.md)
- [03_Experiment_Design.md](file:///d:/Wheat/Parallel_Exp/docs/Drafts/03_Experiment_Design.md)
- [04_Phase1_实验实践指南.md](file:///d:/Wheat/Parallel_Exp/docs/Drafts/04_Phase1_%E5%AE%9E%E9%AA%8C%E5%AE%9E%E8%B7%B5%E6%8C%87%E5%8D%97.md)
- [PaperDraft.md](file:///d:/Wheat/Parallel_Exp/docs/Drafts/PaperDraft.md)
- [关于科学性增强的进一步讨论.md](file:///d:/Wheat/Parallel_Exp/docs/Drafts/%E5%85%B3%E4%BA%8E%E7%A7%91%E5%AD%A6%E6%80%A7%E5%A2%9E%E5%BC%BA%E7%9A%84%E8%BF%9B%E4%B8%80%E6%AD%A5%E8%AE%A8%E8%AE%BA.md)

## 2. 批评要点与主张边界

## 2.1 当前批评的实质

当前批评并不是否定研究方向，而是指出一个证据错位：

- 现有主证据仍然主要是 `NRMSE`、`MAE`、generalization gap 和 negative optimization。
- 这些指标可以支持“某协议更稳健”或“某协议误差更低”。
- 这些指标本身不能直接支持“参数代偿显著减弱”或“equifinality 显著降低”。

因此，若论文继续把 `S2` 写成“降低参数代偿”的主结论，而没有参数空间证据，审稿人会直接质疑主张强度与证据强度不匹配。

## 2.2 重写后的核心假说

建议将相关主张收敛为以下表述：

- `H2-revised`：在固定 `W × G × O` 条件下，`S2` 相比 `S1` 能在不牺牲验证表现的前提下，压缩行为参数集、减弱高相关参数结构，并提高过程一致性。
- `H2a`：若 `S2` 的标准化行为参数云体积更小、且高相关参数对占比下降，则可支持“参数代偿结构减弱”。
- `H2b`：若 `S2` 下“同样好”的参数组对应更收缩的中间过程轨迹包络，则可支持“equifinality 不仅在终点上收缩，也在过程上收缩”。
- `H2c`：若后续还有余力补充 Jacobian 或 GSA，则这些指标只作为增强性证据，不再作为首轮必须完成项。

## 2.3 本轮明确不做的强说法

- 不写“`S2` 证明性地消除了 equifinality”
- 不写“验证误差下降说明参数代偿被解决”
- 不把单个最优解当作参数可辨识性的代表
- 不把行为参数集直接等同于严格意义上的后验分布

## 2.4 必须提前承认的方法边界

吸收进一步讨论后，本轮方案增加以下约束：

1. **行为参数云不是通用后验分布。**
   - 对 `O1`，它更接近“多起点局部极小值分布”。
   - 对 `O2`，它更接近“IES 收缩集合”，可能存在 ensemble collapse。
   - 因此，不应把不同优化器产出的点云直接按“后验体积”做横向科学比较。
2. **参数空间结论只在固定优化器内成立。**
   - 本轮的主比较是固定 `O` 后比较 `S1` vs `S2`。
   - 不建议把 `O1`、`O2` 甚至未来 `O4` 的点云体积直接放在同一张表里做强比较。
3. **`O4` 不进入首轮主证据链。**
   - 多目标前沿上的参数散开，往往反映目标冲突而不是参数等效。
   - 若未来要分析 `O4`，必须先固定偏好方向或从帕累托前沿切出一个局部切片，再讨论相关性或体积。
4. **Jacobian 与 GSA 都是增强项，不是首轮门槛。**
   - `O2`、`O4` 不天然提供稳定 Jacobian。
   - 在 DSSAT 强非线性环境下，局部谱分析可能代价高、噪声大。
   - 有限研究时间下，不应把主线绑死在这些高成本模块上。

## 3. 有限精力下的总策略

本轮策略不是“把所有可做分析都做一遍”，而是遵守三个原则：

1. **固定维度后再比较。**
   - 固定 `W × G × O`，只比较 `S1` vs `S2`。
   - 先回答“阶段式率定是否改善参数代偿”，再考虑其他扩展轴。
2. **宁可缩小覆盖面，也要提高点云密度。**
   - 与其在很多组合上只有 5–10 次重复，不如在少数关键对子上做高密度重复。
   - equifinality 是参数空间问题，样本太少时，相关矩阵和 PCA 容易失真。
3. **优先使用稳健的全局几何证据。**
   - 主证据优先级为：行为参数云体积、相关结构、边界贴附率、过程轨迹包络。
   - Jacobian 和 GSA 只在主线跑通后再补。

## 3.1 本轮科学问题的最终定性

为避免后续编码和实验执行继续摇摆，本轮把科学问题最终定性如下：

1. **本研究的主问题不是单独证明 `S2`。**
   - 主研究仍然是协议结构研究，即在 `W × O × S × G` 框架下识别哪些协议轴真正改变结果。
   - `S2` 只是其中最重要、最值得做参数空间复核的一个轴。
2. **equifinality 评估是受控子模块，不是全文唯一主线。**
   - 它的任务是回答：`S2` 的收益是否超出“误差改善”，而进入“参数空间更干净”的层面。
   - 它不是要把全文改造成一篇完整的不确定性量化论文。
3. **首轮只追求“足以支撑主稿”的证据，不追求终局证明。**
   - 若主科学对子显示清楚的参数云收缩和过程包络收缩，则已经足够支撑论文主张升级。
   - 若只显示误差改善，则论文照样成立，只是相关表述必须降级。

## 3.1.1 关于 `S1`、`S2`、`S3` 的最终边界

针对后续实验和编码最容易混乱的问题，本轮在此明确：

1. **当前 equifinality 专项只把 `S1` 与 `S2` 作为主研究对象。**
   - 受控科学问题是：在固定 `W × G × O` 条件下，`S2` 相比 `S1` 是否更能收缩参数空间并减弱代偿结构。
   - 因此，首轮 behavioral 参数云、参数空间统计、过程轨迹包络和结论分级都围绕 `S1` vs `S2` 展开。
2. **`S3` 不进入首轮 equifinality 主证据链。**
   - `S3` 的本质是 `S2` 之后的联合细化或增强步骤。
   - 它更适合作为“搜索增强是否值得保留”的问题，而不是“阶段式率定是否优于朴素联合”的核心判别对象。
3. **整篇论文仍可保留 `S3`，但角色必须降级为扩展层。**
   - 若后续要研究 `S3`，应把它写成：`S2` 稳定后，进一步联合细化是否带来额外收益，以及这种收益是否会重新放大参数代偿。
   - 这类比较应放在主科学对子完成之后，不能与 `S1` vs `S2` 的第一轮证据混在一起。

一句话冻结规则如下：

> **当前专题研究 `S1` 与 `S2`；`S3` 保留为后续增强层，而不是首轮主研究对象。**

## 3.2 对后续编码工作的直接约束

从工程执行角度，后续所有脚本开发都必须服从以下约束：

1. **不先为所有可能分析搭框架。**
   - 先服务 `S1` vs `S2` 的受控对子，再考虑通用化。
2. **不先做图，再补指标。**
   - 必须先把 behavioral 规则、标准化方式、字段定义和汇总表固定。
3. **不先做高成本增强项。**
   - 首轮不优先开发 Jacobian、GSA、`O4` 相关分析代码。
4. **不让脚本输出依赖临时人工判断。**
   - 所有 behavioral 判定、underpowered 标记、top_k 筛选、边界标准化和 stop/go 规则都必须由脚本显式输出。
5. **不让 `S3` 逻辑提前侵入首轮脚本。**
   - 首轮脚本接口默认只需稳定支持 `S1` 与 `S2`。
   - 是否扩展到 `S3`，必须等 `S1` vs `S2` 主线跑通后再决定。

## 4. 最小可执行证据链

后续分析按“必做 / 重要 / 可选”三层组织，而不是把所有指标都写成刚性任务。

| 层级 | 是否首轮必须 | 目标 | 指标 |
| :--- | :--- | :--- | :--- |
| 拟合与稳健性层 | 必做 | 证明 `S2` 至少没有以更差泛化换取参数空间收缩 | `NRMSE`、`MAE`、generalization gap、negative optimization |
| 参数空间几何层 | 必做 | 回答“参数代偿结构是否收缩” | 标准化参数云、`IQR`、`log_det(cov)`、`mean_abs_corr`、`frac_abs_corr_gt_0_8`、`boundary_hit_rate` |
| 过程一致性层 | 重要 | 回答“是否仍存在终点同分、过程不同” | 物候节点、`LAIX`、`CWAM`、`HIAM` 等轨迹包络宽度 |
| 局部辨识性层 | 可选 | 为主结论补强机制解释 | Jacobian 奇异值谱、条件数、有效秩 |
| 全局敏感性层 | 可选 | 为“信号从噪声中脱颖而出”提供补强 | Sobol `S_i`、`S_Ti` 或其他 GSA 指数 |

## 4.1 主结论分级规则

为了避免论文用语过强，本轮采用分级表述：

1. **仅有误差改善**
   - 只能写：`S2` 改善了拟合或稳健性。
2. **误差不劣 + 参数云收缩**
   - 可以写：`S2` 在固定条件下表现出更弱的参数代偿结构。
3. **误差不劣 + 参数云收缩 + 过程包络收缩**
   - 可以写：`S2` 在测试设置下显示出 equifinality 减弱的更完整证据。
4. **再加 Jacobian 或 GSA 改善**
   - 可以写：`S2` 对可辨识性的改善获得了增强性机制支持。

这意味着：**首轮不必为了“能写出最强句子”而把所有高成本分析都做完。**

## 5. 必做指标的重新定义

## 5.1 行为参数集

后续分析不得只保留单个 best run。每个目标协议都必须形成一组 behavioral solutions。

首轮建议采用两层定义：

1. `behavioral_core`
   - `status = success`
   - `better_than_b0 = True` 或至少不显著劣于 `B0`
   - `primary_score <= best_primary_score_of_same_crop_combo_optimizer × 1.05`
2. `comparison_window`
   - 在 `behavioral_core` 内按 `primary_score` 排序
   - 若样本过多，则取固定 `top_k`
   - 若样本过少，则标记为 underpowered，不强行做几何结论

这样做的目的不是追求完美后验定义，而是避免单纯依赖一个相对阈值导致不同组合的样本量不可比。

首轮建议把以下字段视为 behavioral 判定的最小必备字段：

- `crop`
- `combo_key`
- `optimizer_key`
- `stage_key`
- `run_id`
- `status`
- `primary_score`
- `better_than_b0`
- `is_behavioral_core`
- `is_in_comparison_window`
- `underpowered_flag`

## 5.1.1 `behavioral_core` 的精确判定规则

为避免后续编码时同一概念被不同脚本重复解释，`behavioral_core` 建议按以下顺序逐步判定：

1. **先限定比较分层键**
   - 以 `crop × combo_key` 为最小比较单元
   - 若后处理表中 `combo_key` 已经内含 `W/O/S/G`，则不再额外拆分
2. **先做可运行性过滤**
   - 仅保留 `status = success`
   - 若存在运行异常、缺失主得分或关键参数缺失，则直接排除
3. **再做基线约束**
   - 若存在 `better_than_b0` 字段，则要求 `better_than_b0 = True`
   - 若暂时没有该布尔字段，则以 `primary_score <= b0_primary_score` 代替
4. **最后做组内相对阈值**
   - 在同一 `crop × combo_key` 内计算 `best_primary_score`
   - 定义 `behavioral_threshold_value = best_primary_score × 1.05`
   - 满足 `primary_score <= behavioral_threshold_value` 的运行，标记为 `is_behavioral_core = True`

建议冻结如下公式：

`is_behavioral_core = success_gate AND baseline_gate AND relative_score_gate`

其中：

- `success_gate = (status == "success")`
- `baseline_gate = (better_than_b0 == True)` 或其分数等价形式
- `relative_score_gate = (primary_score <= best_primary_score_of_same_crop_combo × 1.05)`

## 5.1.2 `comparison_window` 的精确判定规则

`comparison_window` 不是新的 behavioral 定义，而是为了让不同组合在几何统计时具备更可比的样本窗口。

建议规则如下：

1. 仅在 `behavioral_core` 内部排序
2. 按 `primary_score` 升序排列
3. 若 `n_behavioral_core <= target_behavioral_n`，则全部保留
4. 若 `n_behavioral_core > target_behavioral_n`，则仅保留前 `target_behavioral_n` 个
5. 建议首轮固定 `target_behavioral_n = 50`

因此：

- `is_in_comparison_window = True` 的前提一定是 `is_behavioral_core = True`
- `comparison_window` 的作用是控制窗口大小，不改变 behavioral 的科学定义

建议在 `manifest` 中同时冻结：

- `behavioral_relative_multiplier = 1.05`
- `target_behavioral_n = 50`

## 5.1.3 `sample_status` 与 `underpowered_flag` 的精确判定规则

建议对每个 `crop × combo_key` 基于 `n_behavioral_core` 和 `n_comparison_window` 同时输出：

1. `n_behavioral_core`
2. `n_comparison_window`
3. `sample_status`
4. `underpowered_flag`

建议判定如下：

- `sample_status = "ready_strong"`：`n_comparison_window >= 50`
- `sample_status = "ready_basic"`：`30 <= n_comparison_window < 50`
- `sample_status = "underpowered"`：`n_comparison_window < 30`

并同步定义：

- `underpowered_flag = (sample_status == "underpowered")`

使用口径：

- `ready_strong`：允许进入主图、主表和较强文字表述
- `ready_basic`：允许进入主分析，但必须保留样本限制说明
- `underpowered`：可以保留描述性结果，但不进入强结论图和强结论句

## 5.1.4 首轮推荐的默认参数

为减少反复讨论，首轮建议直接冻结以下默认值：

- `behavioral_relative_multiplier = 1.05`
- `target_behavioral_n = 50`
- `min_behavioral_n_for_geometry = 30`
- `sample_status_based_on = n_comparison_window`
- `comparison_window_sort_key = primary_score_ascending`

## 5.2 参数标准化

行为参数集做体积、相关和 PCA 之前，必须先做无量纲化。

首选标准化方式：

- 基于参数边界：`x_std = (x - lower) / (upper - lower)`

补充解释口径：

- 若需要给出“偏离基线多少”的解释，可再附加相对 `B0` 的变化率字段
- 但用于 `cov`、`log_det`、PCA 和距离计算的主字段，应统一使用边界标准化值

原因：

- 边界标准化更稳定，不依赖 `B0` 是否接近 0
- 不同参数量纲差异很大，未经标准化的协方差体积没有解释力

## 5.3 样本量门槛

吸收进一步讨论后，本轮明确提高样本量要求：

- 若只做误差汇总，少量重复仍可接受
- 若要做相关矩阵、PCA、`log_det(cov)`，则每个被比较组至少应有 `30` 个 behavioral solutions
- 更稳妥的目标是每组 `50` 个 behavioral solutions
- 若样本不足 `30`，只能报告“趋势”或“描述性现象”，不能将其写成强结论

本条是本轮最重要的执行约束之一：**优先补样本，不优先开新组合。**

为便于脚本执行，建议把样本状态强制离散成三档：

- `ready_strong`：`n_comparison_window >= 50`
- `ready_basic`：`30 <= n_comparison_window < 50`
- `underpowered`：`n_comparison_window < 30`

后续所有汇总表和图表都应显式携带该状态，避免人工解释时忘记样本边界。

## 5.4 参数空间主指标

首轮必须保留以下参数空间指标：

- `n_behavioral`
- 每个参数的标准化 `IQR`
- `log_det(cov)` 或其稳定替代值
- `mean_abs_corr`
- `frac_abs_corr_gt_0_8`
- `boundary_hit_rate`
- PCA 前两轴解释率及投影形状

推荐解释口径：

- `log_det` 更小：整体参数云更收缩
- `mean_abs_corr` 与 `frac_abs_corr_gt_0_8` 更低：强代偿结构减弱
- 点云由细长带状转向更集中团块：等效峡谷缩短
- `boundary_hit_rate` 很高：结果应降级解释为“数值可行但生理证据不足”

## 5.4.1 `eq_identifiability_summary.tsv` 的字段解释

为便于后续编码与论文写作对齐，建议对主汇总表中的字段口径做如下冻结：

- `crop`：作物名
- `combo_key`：唯一协议键，默认已包含 `W/O/S/G`
- `n_behavioral`：进入 `comparison_window` 的样本数
- `sample_status`：`ready_strong / ready_basic / underpowered`
- `log_det_cov`：标准化参数云协方差矩阵的对数行列式或稳定替代值
- `mean_abs_corr`：参数相关矩阵非对角元素绝对值的平均值
- `frac_abs_corr_gt_0_8`：满足 `|ρ| > 0.8` 的参数对占比
- `boundary_hit_rate`：进入 `comparison_window` 的参数点中，任一参数贴边的频率
- `pca_var_explained_pc1`：第一主成分方差解释率
- `pca_var_explained_pc2`：第二主成分方差解释率
- `interpretation_level`：对应主结论分级的机器可读标签

其中 `interpretation_level` 建议先输出以下四档：

- `fit_only`
- `fit_plus_geometry`
- `fit_plus_geometry_plus_process`
- `mechanism_enhanced`

首轮若尚未补过程层或机制层，也可以只输出前两档。

## 5.4.2 `eq_identifiability_summary.tsv` 的逐步计算流程

建议按固定顺序计算，避免后续脚本在不同环节重复做不一致处理：

1. **载入 behavioral 窗口**
   - 读取 `eq_parameter_cloud.tsv`
   - 仅保留 `is_in_comparison_window = True` 的记录
2. **按组重塑参数矩阵**
   - 以 `crop × combo_key × run_id` 形成样本
   - 以 `param_name` 形成列
   - 值使用 `param_value_std`
3. **计算样本规模字段**
   - `n_behavioral = number_of_unique_run_id`
   - `sample_status`
4. **若 `sample_status = underpowered`**
   - 仍可输出基础字段
   - 但 `interpretation_level` 默认不能高于 `fit_only`
5. **计算单参数离散度**
   - 对每个参数计算标准化 `IQR`
   - 可另存长表，但主汇总表只保留总体摘要字段
6. **计算协方差体积**
   - 对参数矩阵求协方差矩阵
   - 计算 `log_det_cov`
   - 若协方差矩阵近奇异，则采用稳定替代方案并记录到 notes
7. **计算相关结构**
   - 计算参数相关矩阵
   - 提取 `mean_abs_corr`
   - 提取 `frac_abs_corr_gt_0_8`
8. **计算边界贴附率**
   - 基于参数长表中的 `at_lower_bound / at_upper_bound`
   - 形成 `boundary_hit_rate`
9. **计算 PCA 摘要**
   - 对标准化参数矩阵做 PCA
   - 提取 `pca_var_explained_pc1`
   - 提取 `pca_var_explained_pc2`
10. **生成初步解释层级**
   - 结合 `sample_status`
   - 结合是否较 `S1` 显示更小体积和更弱相关结构
   - 输出 `interpretation_level`

## 5.4.3 `interpretation_level` 的推荐生成规则

建议先按“作物内、固定对子”的比较逻辑生成，不做跨作物平均后再判定。

对每个 `S1` vs `S2` 对子，若满足：

1. `sample_status` 至少为 `ready_basic`
2. `S2` 的 `log_det_cov` 小于 `S1`
3. `S2` 的 `mean_abs_corr` 不大于 `S1`
4. `S2` 的 `frac_abs_corr_gt_0_8` 不大于 `S1`

则可先赋值：

- `interpretation_level = "fit_plus_geometry"`

若后续再满足：

5. 过程轨迹包络未增加，且最好下降

则升级为：

- `interpretation_level = "fit_plus_geometry_plus_process"`

若再满足：

6. Jacobian 或 GSA 显示更强机制支持

则升级为：

- `interpretation_level = "mechanism_enhanced"`

若以上条件不满足，或样本不足，则保持：

- `interpretation_level = "fit_only"`

## 5.5 过程轨迹主指标

过程一致性层只保留最关键变量，不做过度扩张。

首轮建议仅保留：

- 物候节点
- `LAIX`
- `CWAM`
- `HIAM`

过程层的判断方式：

- 对 behavioral solutions 形成轨迹包络
- 比较 `S1` 与 `S2` 的包络宽度
- 若终点误差相近但过程包络仍然很宽，则不能宣称 equifinality 已被充分压缩

## 5.6 可选增强指标

下列指标保留为可选增强项：

- `O1` 代表性解附近的 Jacobian 奇异值谱
- 关键参数的 GSA 主效应与总效应

使用边界：

- Jacobian 只推荐在 `O1` 上做，不作为 `O2` 首轮硬指标
- GSA 只在主线结果已清楚、且仍需增强机制解释时再补
- 若时间有限，只需在 1–2 个代表作物上做，而不是五作物全铺开

## 6. 当前项目结构中的角色映射

为了避免新增工作再次散落，后续开发和分析建议按当前目录职责落位：

| 路径 | 当前角色 | 本方案中的新增职责 |
| :--- | :--- | :--- |
| [docs/Drafts](file:///d:/Wheat/Parallel_Exp/docs/Drafts) | 论文总控与研究设计草稿 | 维护假说边界、指标口径、图表清单与章节映射 |
| [docs](file:///d:/Wheat/Parallel_Exp/docs) | 阶段性研究记录与专题说明 | 存放复验纪要、方法决策与异常解释 |
| [autoresearch_sandbox](file:///d:/Wheat/Parallel_Exp/autoresearch_sandbox) | 实验调度、后处理、快速分析沙箱 | 承载 equifinality 复验脚本与后处理脚本 |
| [autoresearch_sandbox/phase1_runs](file:///d:/Wheat/Parallel_Exp/autoresearch_sandbox/phase1_runs) | Phase 1 结果目录 | 提供目标对子筛选与代表作物选择依据 |
| [mvp_pest_mgda/config/multi](file:///d:/Wheat/Parallel_Exp/mvp_pest_mgda/config/multi) | 项目配置 | 冻结 train/valid 划分、参数边界、观测映射版本 |
| [mvp_pest_mgda/src](file:///d:/Wheat/Parallel_Exp/mvp_pest_mgda/src) | 稳定核心实现 | 仅在分析逻辑稳定后迁移通用函数 |

## 6.1 目录使用原则

- **论文叙事先收口到 `docs/Drafts`**
- **探索性脚本优先放在 `autoresearch_sandbox`**
- **不为首轮专题过早新建太多正式模块**

## 7. 数据产品清单

吸收“聚焦主线”的原则后，首轮只要求以下最小数据产品：

| 文件名 | 是否必做 | 作用 |
| :--- | :--- | :--- |
| `eq_run_manifest.json` | 必做 | 冻结比较对子、作物、阈值、样本量和脚本版本 |
| `eq_behavioral_summary.tsv` | 必做 | 记录每个作物 × 组合 × 优化器的行为解数量与通过率 |
| `eq_parameter_cloud.tsv` | 必做 | 行为解级参数长表，供体积、相关和 PCA 使用 |
| `eq_identifiability_summary.tsv` | 必做 | 汇总参数空间核心指标 |
| `eq_process_trajectory.tsv` | 重要 | 存放代表作物的行为解轨迹长表 |
| `eq_jacobian_svals.tsv` | 可选 | 存放 `O1` 的谱分析结果 |
| `eq_analysis_notes.md` | 必做 | 记录阈值、例外作物和解释边界 |

## 7.1 每个数据产品最小字段约束

为了让后续编码直接可落地，建议现在就冻结最小字段口径：

1. `eq_run_manifest.json`
   - `session_name`
   - `created_at`
   - `source_phase1_session`
   - `selected_crops`
   - `selected_pairs`
   - `behavioral_rule`
   - `comparison_window_rule`
   - `min_behavioral_n`
   - `target_behavioral_n`
   - `parameter_standardization`
2. `eq_behavioral_summary.tsv`
   - `crop`
   - `combo_key`
   - `optimizer_key`
   - `stage_key`
   - `n_total`
   - `n_behavioral_core`
   - `n_comparison_window`
   - `sample_status`
   - `best_primary_score`
   - `behavioral_threshold_value`
3. `eq_parameter_cloud.tsv`
   - `crop`
   - `combo_key`
   - `run_id`
   - `param_name`
   - `param_value_raw`
   - `param_value_std`
   - `at_lower_bound`
   - `at_upper_bound`
   - `is_behavioral_core`
   - `is_in_comparison_window`
4. `eq_identifiability_summary.tsv`
   - `crop`
   - `combo_key`
   - `n_behavioral`
   - `sample_status`
   - `log_det_cov`
   - `mean_abs_corr`
   - `frac_abs_corr_gt_0_8`
   - `boundary_hit_rate`
   - `pca_var_explained_pc1`
   - `pca_var_explained_pc2`
   - `interpretation_level`
5. `eq_process_trajectory.tsv`
   - `crop`
   - `combo_key`
   - `run_id`
   - `variable_name`
   - `time_key`
   - `sim_value`
   - `is_behavioral_core`
   - `is_in_comparison_window`

这些字段不要求一步到位全部完美，但建议首轮脚本设计时直接兼容，避免后续反复改表头。

## 7.2 与现有数据产品的连接

首轮优先复用现有导出表：

- [phase1_runner.py](file:///d:/Wheat/Parallel_Exp/autoresearch_sandbox/phase1_runner.py)
- [phase1_postprocess.py](file:///d:/Wheat/Parallel_Exp/autoresearch_sandbox/phase1_postprocess.py)

已有表：

- `phase1_experiment_summary.tsv`
- `phase1_aggregate_metrics.tsv`
- `phase1_treatment_metrics.tsv`
- `phase1_parameters.tsv`
- `phase1_derived_metrics.tsv`
- `phase1_combo_summary.tsv`

新增工作优先只做三件事：

1. 打 behavioral 标记
2. 生成标准化参数云统计
3. 生成代表作物的过程轨迹包络数据

## 8. 可执行实验设计

## 8.1 首轮主比较范围

有限精力下，首轮不建议同时把 `O1`、`O2`、多组 `W`、多组 `G` 全部拉满。

建议首轮主线如下：

1. **主科学对子**
   - `W8 × G3 × O1` 下比较 `S1` vs `S2`
   - `W4 × G3 × O1` 下比较 `S1` vs `S2`
2. **稳健性复核对子**
   - 若主科学对子已有清晰信号，再补 `W8 × G3 × O2`
3. **暂缓项**
   - `S3`
   - `O4`
   - 过多额外 `W × G` 组合
   - 五作物同步高密度铺开

原因：

- `O1` 更适合做首轮科学论证，解释最直接
- `W8` 与 `W4` 已可覆盖主叙事中的工程基线与归一化对照
- 先证明“固定优化器下 `S2` 是否收缩参数云”，再谈算法扩展，逻辑最干净
- `S3` 若过早进入，会把“阶段式率定是否有效”和“阶段后联合细化是否值得”两个问题混在一起

## 8.2 作物选择策略

首轮不建议五作物同时高密度复验。建议先从 `Phase 1` 里挑 `2–3` 个代表作物：

- 一个 `S2` 已表现出拟合优势的作物
- 一个存在平台现象或结果胶着的作物
- 若仍有余力，再加一个例外作物

这样做的目的，是先回答“现象是否真实存在”，再决定是否值得跨作物扩张。

## 8.3 重复与样本量建议

为了支撑参数空间结论，首轮改为高密度重复：

- 主科学对子：每个作物 × 组合目标重复数以获得 `30–50` 个 behavioral solutions 为准
- 若行为解不足 `30`，优先继续加重复，不新增组合
- 只有当主科学对子形成稳定参数云后，才进入 `O2` 复核或跨作物扩张

这比“每个组合只跑 5–10 次”更符合 equifinality 研究的统计要求。

## 8.4 工作包拆解

### WP0：冻结比较契约

目标：

- 冻结作物列表、主科学对子、阈值规则、参数边界版本和 train/valid 口径

输出：

- `eq_run_manifest.json`
- 固定阈值说明

完成标准：

- 后续任何比较都不再临时改规则

### WP1：高密度行为参数云构建

目标：

- 在少数关键对子上形成足够密度的 behavioral solutions

输入：

- `phase1_experiment_summary.tsv`
- `phase1_parameters.tsv`
- 新一轮定向重复运行结果

输出：

- `eq_behavioral_summary.tsv`
- `eq_parameter_cloud.tsv`

完成标准：

- 主科学对子形成可用于几何分析的行为参数云

### WP2：参数空间核心统计

目标：

- 用稳健、低歧义的几何统计量回答“代偿结构是否收缩”

输出：

- `eq_identifiability_summary.tsv`
- 参数相关热图数据
- PCA 投影数据

完成标准：

- 至少能对代表作物形成 `S1` 与 `S2` 的体积、相关、边界和 PCA 对照

### WP3：过程轨迹复核

目标：

- 检查“终点同分、过程不同”是否在 `S2` 下减弱

输出：

- `eq_process_trajectory.tsv`
- 轨迹包络图数据

完成标准：

- 至少对 `1–2` 个代表作物完成 `S1` vs `S2` 的过程包络对照

### WP4：增强性机制分析

目标：

- 在主线已清晰时，再补充机制证据

可选输出：

- `eq_jacobian_svals.tsv`
- GSA 汇总表

完成标准：

- 仅在确有必要增强说服力时启动，不作为首轮刚性任务

### WP4.5：`S3` 扩展验证

目标：

- 在 `S1` vs `S2` 主线已经明确后，再判断 `S3` 是否值得作为增强协议保留

推荐问题：

- `S3` 是否在 `S2` 基础上带来稳定误差改善
- `S3` 是否重新放大参数云体积或高相关结构
- `S3` 的额外收益是否值得其更高工程复杂度

进入条件：

- `S1` vs `S2` 至少已有一个主科学对子形成清晰结论
- `S2` 已具备可复验的稳定行为参数云

说明：

- `S3` 的问题是“增强是否值得”，不是“阶段式率定是否成立”
- 因此 `S3` 的图表、表格和结论应与 `S1` vs `S2` 主证据分开呈现

## 8.5 Stop / Go 决策规则

为了减少“做到一半再临时改方向”，本轮建议增加明确门禁：

1. **WP0 → WP1**
   - 只有在 behavioral 规则、标准化方式、样本门槛三者被冻结后，才允许开始高密度复验。
2. **WP1 → WP2**
   - 只有当至少一个主科学对子达到 `ready_basic`，才进入参数空间统计。
   - 若全部对子仍为 `underpowered`，则继续补样本，不做强结论图。
3. **WP2 → WP3**
   - 只有当至少一个代表作物显示“误差不劣 + 参数云有收缩迹象”，才补过程轨迹包络。
4. **WP3 → WP4**
   - 只有当主稿仍需要更强机制解释时，才补 Jacobian 或 GSA。
   - 若参数云和过程包络已经足够支撑表述，则停止扩张，不再新增高成本任务。

## 9. 推荐实现路径

## 9.1 先复用，后专门化

为避免工程层继续发散，首轮不强制新建完整专题脚本体系。

优先顺序：

1. 先复用 [phase1_runner.py](file:///d:/Wheat/Parallel_Exp/autoresearch_sandbox/phase1_runner.py) 做定向高密度重复
2. 先在现有后处理基础上补 behavioral 标记和参数云统计
3. 只有当字段和流程稳定后，再考虑单独抽出 `equifinality_postprocess.py` 或 `equifinality_figures.py`

这意味着：**首轮重点是拿到可信证据，而不是先重构工程外壳。**

## 9.1.1 首轮最小编码清单

若以后续编码工作为导向，首轮建议只实现四类最小函数能力：

1. **行为解筛选函数**
   - 输入 `phase1_experiment_summary.tsv`
   - 输出 `is_behavioral_core`、`is_in_comparison_window`、`sample_status`
2. **参数标准化函数**
   - 输入参数原值和上下界
   - 输出 `param_value_std`、`at_lower_bound`、`at_upper_bound`
3. **参数空间统计函数**
   - 输入行为参数云
   - 输出 `IQR`、`log_det(cov)`、相关结构、PCA 摘要
4. **过程轨迹汇总函数**
   - 输入代表作物过程输出
   - 输出轨迹长表和包络宽度摘要

只要这四类能力稳定，首轮实验就可以完整推进。

补充约束：

- 首轮函数签名和数据结构可以保留 `stage_key` 字段，以兼容未来 `S3`
- 但首轮业务逻辑、默认过滤和统计汇总，只要求覆盖 `S1` 与 `S2`

## 9.1.2 首轮明确不优先编码的内容

以下内容建议暂缓，避免编码阶段失焦：

- 通用 Jacobian 框架
- 全局敏感性分析总框架
- `S3` 专用后处理分支
- `O4` 前沿切片与偏好方向分析
- 跨所有 Phase 的统一大而全分析管线
- 为未来论文附录一次性准备所有图表脚本

## 9.2 何时迁移到正式源码

只有当下列逻辑被证明可复用时，才迁移到 [mvp_pest_mgda/src](file:///d:/Wheat/Parallel_Exp/mvp_pest_mgda/src)：

- 参数边界标准化
- 行为参数集筛选
- 参数空间统计函数
- 过程轨迹包络汇总

## 9.3 推荐命令模板

若继续沿用现有沙箱运行方式，可参考：

```powershell
<python> autoresearch_sandbox\phase1_runner.py --batch All --combo-keys W8_O1_S1_G3,W8_O1_S2_G3 --budget standard --repetitions <high_repeat> --train-only --tag eq_pair_w8_o1_dense
```

```powershell
<python> autoresearch_sandbox\phase1_runner.py --batch All --combo-keys W4_O1_S1_G3,W4_O1_S2_G3 --budget standard --repetitions <high_repeat> --train-only --tag eq_pair_w4_o1_dense
```

```powershell
<python> autoresearch_sandbox\phase1_postprocess.py --input-dir <session_dir>
```

说明：

- `<high_repeat>` 的目标不是机械固定为 5 或 10，而是为了获得足够行为解样本
- `combo_key` 建议继续沿用 `W8_O1_S1_G3` 这一现有命名风格

## 10. 数据分析清单

## 10.1 先做现有结果诊断

- [ ] 读取 `phase1_combo_summary.tsv`，筛出 `S1` vs `S2` 的 `W8_G3_O1` 与 `W4_G3_O1`
- [ ] 标记哪些作物已显示 `S2` 优势，哪些作物仍处平台状态
- [ ] 选出 `2–3` 个代表作物进入首轮高密度复验
- [ ] 冻结阈值规则、标准化方式和最小样本量门槛

## 10.2 再做主科学对子复验

- [ ] 对代表作物执行高密度重复运行
- [ ] 记录全部 `run_id`、参数输出和处理级指标
- [ ] 生成 `behavioral_core` 与 `comparison_window`
- [ ] 若某组行为解不足 `30`，先补样本，不开新组合
- [ ] 明确首轮复验仅覆盖 `S1` 与 `S2`

## 10.3 形成参数空间汇总

- [ ] 计算 `n_behavioral`
- [ ] 计算每个参数的标准化 `IQR`
- [ ] 计算 `mean_abs_corr` 和 `frac_abs_corr_gt_0_8`
- [ ] 计算 `log_det(cov)`
- [ ] 统计 `boundary_hit_rate`
- [ ] 标记 `sample_status` 与 `interpretation_level`
- [ ] 形成 `eq_identifiability_summary.tsv`

## 10.4 做过程一致性复核

- [ ] 对代表作物导出 `LAIX`、`CWAM`、`HIAM` 和物候节点
- [ ] 生成 `S1` 与 `S2` 的轨迹包络图
- [ ] 标记哪些情形是“终点同分、过程不同”

## 10.5 再决定是否补增强项

- [ ] 仅在主线结果仍需加强时，才补 `O1` Jacobian
- [ ] 仅在需要额外机制解释时，才补关键参数的 GSA
- [ ] 仅在 `S1` vs `S2` 主线已经清楚时，才决定是否启动 `S3` 扩展验证
- [ ] 不把增强项变成新的主战场

## 11. 图表清单

首轮图表压缩为三张主图、一张可选补图：

| 图号建议 | 优先级 | 图类型 | 主要回答的问题 |
| :--- | :--- | :--- | :--- |
| Figure E1 | 必做 | 行为参数云 PCA 投影图 | `S2` 是否把 `S1` 的长条等效峡谷收缩为更集中团块 |
| Figure E2 | 必做 | 参数相关热图 | `S2` 是否减弱了强相关参数结构 |
| Figure E3 | 重要 | 过程轨迹包络图 | `S2` 是否减少了“终点同分、过程不同” |
| Figure E4 | 可选 | Jacobian 或 GSA 对照图 | 是否存在进一步的机制支持 |

## 11.1 每张图必须附带的信息

- 比较的是哪个固定 `W × G × O`
- 使用了什么 behavioral 规则
- 样本数是多少
- 该组属于 `ready_strong`、`ready_basic` 还是 `underpowered`
- 参数是否已经边界标准化
- 该图支持的是“参数空间结论”还是“过程一致性结论”

## 11.2 图表出图门槛

为避免后续画出“看起来很像结果、实际上证据不足”的图，建议增加出图门槛：

- PCA 参数云图：仅对 `ready_basic` 及以上的组出图
- 参数相关热图：仅对 `ready_basic` 及以上的组出图
- 过程轨迹包络图：至少需要代表作物在同一对子下拥有可比较的 behavioral solutions
- Jacobian / GSA 图：仅在增强性分析启动后出图

## 12. 论文改写映射

## 12.1 对大纲的修改

建议在 [01_Paper_Outline copy.md](file:///d:/Wheat/Parallel_Exp/docs/Drafts/01_Paper_Outline%20copy.md) 中：

- 在 `Evaluation Criteria` 下新增 `Parameter-space and identifiability evidence`
- 在结果部分新增 `Parameter-space contraction under S2`
- 图表清单优先加入 PCA 参数云图、相关热图和过程包络图

## 12.2 对实验设计文稿的修改

建议在 [03_Experiment_Design.md](file:///d:/Wheat/Parallel_Exp/docs/Drafts/03_Experiment_Design.md) 中：

- 明确“固定优化器后比较 `S1` vs `S2`”是 equifinality 主证据
- 明确高密度重复优先于大范围组合扩张
- 明确 Jacobian/GSA 是可选增强项而非首轮刚性项

## 12.3 对主稿方法部分的修改

建议在 [PaperDraft.md](file:///d:/Wheat/Parallel_Exp/docs/Drafts/PaperDraft.md) 中：

- 说明行为参数集是“近似行为云”，而不是严格后验
- 说明参数云体积与相关结构在固定优化器内解释
- 说明低误差不等于低 equifinality
- 说明为何优先采用高密度行为参数云分析而非只报告单个最优点

## 12.4 对主稿结果部分的修改

结果部分应从单纯“谁误差更低”改写为：

- `S2` 在哪些作物和对子上缩小了标准化参数云体积
- `S2` 在哪些作物和对子上降低了高相关参数对占比
- `S2` 是否在代表作物上同步缩小了过程轨迹包络
- 哪些情形只支持“误差改善”，尚不支持“equifinality 减弱”

## 13. 第一轮执行顺序

建议按以下顺序推进，而不是并行扩张所有任务：

1. 读取现有 `Phase 1` 结果，锁定 `W8_G3_O1` 与 `W4_G3_O1`
2. 选出 `2–3` 个代表作物
3. 冻结 behavioral 规则、标准化方式和样本量门槛
4. 对主科学对子做高密度重复运行
5. 先完成参数云、相关结构和边界贴附统计
6. 再对代表作物补过程轨迹包络
7. 仅在需要时补 Jacobian 或 GSA
8. 最后回填到大纲、实验设计与主稿

## 13.1 首轮交付优先级

从“先能编码、再能实验、最后能写作”的角度，建议把交付拆成三层：

1. **P0：可运行**
   - 能从现有 `Phase 1` 表中打出 behavioral 标记
   - 能生成 `eq_behavioral_summary.tsv`
2. **P1：可分析**
   - 能生成标准化参数云和 `eq_identifiability_summary.tsv`
   - 能给出 PCA 和相关结构所需长表
3. **P2：可写入论文**
   - 能对 `1–2` 个代表作物生成过程轨迹包络
   - 能把结论分级写成“仅误差改善 / 参数代偿结构减弱 / equifinality 更完整减弱”

## 13.2 `S3` 的后续纳入原则

若后续决定把 `S3` 纳入实验，应遵循以下顺序：

1. 先完成 `S1` vs `S2` 主线
2. 再选择少数 `S2` 已明显稳定的对子
3. 再比较 `S2` vs `S3`
4. 只把 `S3` 写成增强协议是否值得，而不重写首轮主结论

## 14. 完成标准

只有满足以下条件，本轮科学性增强工作才算完成：

- [ ] 已形成专项 `manifest` 与固定规则说明
- [ ] 已对主科学对子形成可分析的行为参数云
- [ ] 已生成 `eq_identifiability_summary.tsv`
- [ ] 已完成至少一张参数云 PCA 图和一张相关热图
- [ ] 已对至少 `1–2` 个代表作物完成过程包络复核
- [ ] 已明确哪些结果只支持“误差改善”，哪些支持“参数代偿结构减弱”
- [ ] 已将论文中的强主张降到与证据强度匹配的层级

## 15. 最终建议

本轮最重要的改进，不是继续增加更多优化器、更多指标、更多矩阵格点，而是把问题收缩为一条最强主线：

- 在固定优化器下比较 `S1` 与 `S2`
- 用高密度行为参数云证明参数空间是否收缩
- 用最少但关键的过程变量检查“终点同分、过程不同”是否减弱

若这一主线成立，论文就能更有力地回答：

- `S2` 是否真的压缩了等效参数解空间
- `S2` 是否真的减弱了高相关代偿结构
- `S2` 的改进是否不仅出现在误差层，也出现在过程一致性层

若这一主线尚不成立，则应诚实写成：

> `S2` 在当前设置下改善了拟合或稳健性，但对 equifinality 的系统性削弱仍需更强证据。

这比把任务发散到过多增强分析，更符合当前研究时间、算力配置和论文主问题的优先级。
