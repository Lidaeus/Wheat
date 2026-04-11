# 指标体系与评分体系梳理（现状）及与建议方案对比

本文档基于当前 `Phase1_Experiment` 分支代码，对项目中“运行时采集的数据 → 指标计算 → score 汇总 → 导出 TSV/后处理”的链路做一次可追溯的梳理，并与推荐的“Mean-normalized nRMSE + Bias + W×G 加权聚合”方案对比，标出当前实现的差异与可改进点（含 PEST-IES/GLM 数据留存建议）。

---

## 1. 数据从哪里来（运行时采集）

### 1.1 DSSAT 输出文件（run_model）

运行 DSSAT 后，会在 runtime 目录读取并使用下列输出文件：

- `Evaluate.OUT`, `Summary.OUT`, `PlantGro.OUT`, `PlantGr2.OUT`, `WARNING.OUT`
- 代码位置： [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py#L54-L55)

### 1.2 可对比指标的来源（观测 vs 模拟）

最终用于“评价/评分”的数据来自两部分：

- **观测（Observed）**
  - A 文件（如 `*.WHA/*.MZA/*.SBA`）：读取每个 TRT 的 `yield_var`/`laix_var` 及其它 summary 变量
  - T 文件（如 `*.WHT/*.MZT/*.SBT`）：读取时间序列点（当前主要用于 LAID/LWAD/SWAD 等）
  - 代码位置： [compare_eval.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/compare_eval.py)、[observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py)
- **模拟（Simulated）**
  - 从 DSSAT 输出中抽取与 A/T 文件同名（同 TRT）的指标值，写入 `pest_out.dat`（供 PEST/统一结果 schema 使用）
  - 代码位置： [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)

---

## 2. 单指标统计量如何计算（当前实现）

统一结果 schema 的入口是：

- `build_evaluation_result()`：将 `metrics_by_trt` 与 `observations_by_trt` 对齐后，按 split×metric 汇总出统计量
- 代码位置： [result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py)

本文档将“一个 metric 在一个 split 内的所有可用 TRT 点”的一组向量记为：

- `O = {obs_i}`（观测）
- `S = {sim_i}`（模拟）
- `N = len(O)`

### 2.1 RMSE（当前实现：变量内池化）

\[
RMSE = \sqrt{\frac{1}{N}\sum_{i=1}^N (S_i - O_i)^2}
\]

代码位置：`_single_metric_rmse()`  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L423-L431)

### 2.2 MAE（当前实现：变量内池化）

\[
MAE = \frac{1}{N}\sum_{i=1}^N |S_i - O_i|
\]

代码位置：`_single_metric_mae()`  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L433-L440)

### 2.3 nRMSE（当前实现：Mean-normalized）

当前实现使用 **均值归一化**：

\[
nRMSE = \frac{RMSE}{|\overline{O}| + \varepsilon}
\]

其中 \(\varepsilon=10^{-8}\) 防止分母为 0。

代码位置：`_single_metric_nrmse()`  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L503-L509)

说明：

- 这是“变量内池化（跨 TRT 合并）→ 再归一化”的口径，与建议方案一致。
- 注意：`eval.py` 中用于优化器目标函数的残差归一化目前仍用 `mean(abs(O))`（见 §5.1），与 schema 的 score 口径存在差异。

### 2.4 Bias（当前实现：归一化偏差）

当前 Bias 在 schema 中是一个 **归一化 bias**，分母使用 `mean(abs(O))`：

\[
Bias_{norm} = \frac{\overline{(S - O)}}{\overline{|O|} + \varepsilon}
\]

代码位置：`_single_metric_bias()`  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L511-L516)

对比建议方案：

- 建议里 Bias 通常是 **原单位偏差**：\(\overline{(S-O)}\)，更方便做“系统性高估/低估”的农学解释。
- 若要对齐论文叙述，建议同时导出 `bias_raw` 与 `bias_norm`（见 §6.2）。

### 2.5 Pearson correlation（r）

\[
r = \frac{\mathrm{cov}(O,S)}{\sigma_O\sigma_S}
\]

点数不足（N<2）或方差为 0 时返回 NaN。

代码位置：`_single_metric_pearson_r()`  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L442-L456)

### 2.6 NSE（Nash–Sutcliffe Efficiency）

\[
NSE = 1 - \frac{\sum (S_i-O_i)^2}{\sum (O_i-\overline{O})^2}
\]

点数不足（N<2）或 \(\sum (O-\overline{O})^2=0\) 时返回 NaN。

代码位置：`_single_metric_nse()`  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L458-L469)

### 2.7 d-index（Modified d1）

采用 Modified d1（你已选定）：

\[
d1 = 1 - \frac{\sum |S_i-O_i|}{\sum \left(|S_i-\overline{O}| + |O_i-\overline{O}|\right)}
\]

分母为 0 且误差也为 0 时返回 1，否则 NaN。最终 clip 到 [0,1]。

代码位置：`_single_metric_d1()`  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L471-L487)

---

## 3. split 内如何聚合成一个总值（score / WCS / mean_nrmse）

### 3.1 mean_nrmse（当前 score 主口径）

`mean_nrmse` 的定义是：对该 split 的所有 comparable metrics，计算每个 metric 的 `nrmse`，然后取简单平均（忽略 NaN）：

\[
\mathrm{mean\_nrmse}_{split} = \mathrm{mean}\left(\{nRMSE_{metric}\}\right)
\]

代码位置：`build_evaluation_result()`  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L537-L607)

### 3.2 WCS（Weighted Composite Score：r/NSE/d1 综合）

单个 metric 的 WCS（当前实现：等权平均可用项）：

- \(r_{norm}=\mathrm{clip}_{[0,1]}(\max(0,r))\)
- \(NSE_{norm}=\mathrm{clip}_{[0,1]}(\max(0,NSE))\)
- \(d1_{norm}=\mathrm{clip}_{[0,1]}(d1)\)

\[
WCS_{metric} = \mathrm{mean}\left(\{r_{norm}, NSE_{norm}, d1_{norm}\}\ \text{中可用项}\right)
\]

代码位置：`_metric_wcs_score()`  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L488-L500)

split 总 WCS（当前实现：按“变量桶”静态权重聚合）：

- Phenology（ADAP/MDAP）：0.40
- Yield（HWAM/HWUM）：0.35
- Biomass/Process（LAIX/CWAM）：0.25
- 桶内均分，缺失项不计入分母（对可用权重归一化）

代码位置：`build_evaluation_result()` 权重分配段  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L541-L575)

### 3.3 Primary Score（W×G 的第一版落地：按变量桶权重对 nRMSE 加权）

当前代码中已引入一个与 `score/mean_nrmse` 并行输出的 `primary_score`（train/valid/all），用于表达“跨变量重要性权重”的聚合思想（与论文 W×G 的方向一致，但仍是第一版实现）。

定义：

- 先按指标重要性给每个 metric 分配权重并归一化（缺失则不计入分母）：
  - Phenology（ADAP/MDAP）：0.40（桶内均分）
  - Yield（HWAM/HWUM）：0.35（桶内均分）
  - Biomass/Process（LAIX/CWAM）：0.25（桶内均分）
- 再计算 split 的加权均值：

\[
\mathrm{primary\_score}_{split}=\frac{\sum w_{metric}\cdot nRMSE_{metric}}{\sum w_{metric}}
\]

代码位置：`build_evaluation_result()` 的 `primary_num/primary_den` 聚合段  
[result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L537-L617)

### 3.3 score（Phase1/实验汇总的 score 字段）

当前 `score` 仍以 `mean_nrmse` 为主：

- 若启用 validation：`score = valid_mean_nrmse`
- 否则：`score = all_mean_nrmse`

代码位置： [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L2124-L2134)

---

## 4. 指标是如何导出到 TSV 的（统一导出）

### 4.1 导出文件与字段

Phase1 导出（TSV）主要包括：

- `phase1_experiment_summary.tsv`：每次 run 一行（包含 score、train/valid/all mean_nrmse、train/valid/all wcs 等）
- `phase1_aggregate_metrics.tsv`：每次 run 的 split×metric 多行（包含 rmse/mae/nrmse/bias/pearson_r/nse/d1/wcs）
- `phase1_treatment_metrics.tsv`：每次 run 的 split×metric×trt 明细行（observed/simulated/error 等）
- `phase1_posterior_summary.tsv`：仅当优化器为 `pestpp-ies` 时导出（每个 run × 每个参数一行的 posterior 摘要）
- `phase1_ies_posterior/<run_id>/...`：仅 IES 导出（包含 `posterior_summary.csv` 与 plots/atlas 等诊断 artifacts）

字段定义：

- TSV header： [phase1_runner.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/phase1_runner.py#L169-L206)
- 导出行写入： [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L2215-L2236)
- value_map 构造： [result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L727-L760)

---

## 5. 与推荐方案对比：一致点与关键差异

### 5.1 一致点（已经满足）

- **变量内池化（Intra-variable Pooling）**：当前实现对每个 metric 在一个 split 内跨 TRT 合并后再计算 RMSE/nRMSE，符合推荐方案的第 1 步。
- **Mean-normalized nRMSE**：当前 schema 使用 `abs(mean(obs))+eps` 作为分母，符合“均值归一化”主流做法。
- **多指标可解释输出**：当前以 split×metric 粒度输出明细行，便于定位是哪个指标拖累。

### 5.2 关键差异（建议重点优化）

1) **score 当前没有显式体现 W×G 的“损失构造层”**  
   - 当前 score = valid_mean_nrmse（简单均值）
   - W×G（权重/分组）更多体现在“优化器内部残差权重/PEST 观测权重”，而不是统一 score
   - 建议：将推荐方案的 Primary Score 落地为 `primary_score`（或替代 score），并保留 `mean_nrmse` 作为可比的 baseline 指标（见 §6.1）

2) **优化器目标函数与最终 score 的 nRMSE 口径不一致**  
   - `eval.py` 的残差归一化当前使用 `mean(abs(obs))`：见 `metric_residual_array()`  
     [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py#L1242-L1260)
   - schema 的 nRMSE 使用 `abs(mean(obs))`
   - 建议：统一为同一口径（推荐 `abs(mean(obs))`），否则会出现“优化器在最小化 A，但你在报告 B”的偏差

3) **Bias 建议同时导出 raw 与 normalized**  
   - 当前导出的是 normalized bias（便于跨量纲对比）
   - 论文解释往往需要 raw bias（单位解释更直观）

---

## 6. 推荐的下一步改造清单（按收益/风险排序）

### 6.1 引入“Primary Score（W×G 加权聚合）”，并与现有 score 并行输出

建议新增：

- `primary_score_train/valid/all`：按你论文的 W×G 规则（组权重×组内变量权重）聚合 `nRMSE_metric`
- `score` 可以保持为 `valid_mean_nrmse`（向后兼容），也可以切换为 `primary_score_valid`（与论文一致）

落地方式建议：

- 在 `result_schema.py` 中新增字段并序列化/导出（与 `mean_nrmse/wcs` 同级）
- 在 Phase1 summary TSV 中增加列（类似已加入的 `*_wcs`）

### 6.2 Bias / nRMSE 口径统一与扩展

- 将 `eval.py` 与 `result_schema.py` 的 nRMSE 归一化口径统一（推荐 `abs(mean(obs))+eps`）
- 在 aggregate_metrics 导出中增加：
  - `bias_raw = mean(sim-obs)`
  - 保留 `bias`（当前 bias_norm）

### 6.3 PEST-IES / GLM 优化器结果的“留存策略”升级

现状：

- GLM：解析 `*.par` 得到单点最优参数（无解集）  
  [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py#L710-L728)
- IES：从 `*.phi.actual.csv` 找最佳 realization，再从 `*.par.csv` 抽取该 realization 的参数（但不导出整个 ensemble）  
  [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py#L756-L813)

建议：

- 对 IES：
  - **保存最优解集**：保留本次迭代的 `*.par.csv`、`*.phi.actual.csv` 到 Phase1 workspace 的 artifacts 目录
  - **导出 posterior 摘要**：均值/分位数/最优 real 的参数表（项目里已有 `export-posterior` 子命令基础设施，可直接集成）
- 对 GLM：
  - 保留 `*.par`（单点）即可，同时可补充保存 `*.rec` 或关键日志（便于复现）

---

## 7. 快速索引（代码位置）

- 统一指标计算/序列化： [result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py)
- Phase1 run 汇总 TSV header： [phase1_runner.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/phase1_runner.py)
- Phase1 导出写入： [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py)
- PEST 结果解析与 IES posterior 导出能力： [pest_runner.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py)

