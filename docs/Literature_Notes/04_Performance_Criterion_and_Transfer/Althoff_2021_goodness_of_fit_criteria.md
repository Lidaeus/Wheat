# Althoff and Rodrigues (2021) — Goodness-of-fit criteria for hydrological models

## 1. 文献信息

- **标题**：*Goodness-of-fit criteria for hydrological models: Model calibration and performance assessment*
- **作者**：Daniel Althoff, Lineu Neiva Rodrigues
- **期刊**：*Journal of Hydrology*
- **年份**：2021
- **DOI**：`10.1016/j.jhydrol.2021.126674`
- **出版商链接**：[https://doi.org/10.1016/j.jhydrol.2021.126674](https://doi.org/10.1016/j.jhydrol.2021.126674)
- **证据等级**：`E3` (全文通读提取，重点核验了指标综述和评价部分)

## 2. 本轮提取说明

- **提取目标**：全面梳理水文模型中常用的各种评价指标（如 RMSE, MAE, NSE, KGE）的数学特性与优化偏好，支撑本项目中关于“评价体系（Evaluation Criteria）重构”的论证。
- **关联主线**：属于 `04_Performance_Criterion_and_Transfer`（性能指标塑造率定偏好及相邻领域迁移）。

## 3. 这篇文章为什么与你的课题高度相关

1. **彻底解构了传统评价指标的缺陷**：文章指出使用 `RMSE` 或 `NSE`（Nash-Sutcliffe）作为单一目标函数，会因为其对误差平方的敏感性，不可避免地导致模型偏向于高数值观测（peak flows），而低估甚至忽略低数值观测（low flows）。这完全契合作物模型率定中“终产量垄断目标函数”的痛点，并为你引入其他评价指标（如 MAE、对数/相对误差）提供了水文学界的权威依据。
2. **KGE 指标的跨界潜力**：文章推荐了 KGE (Kling-Gupta efficiency) 作为 NSE 的更稳健替代品。虽然 KGE 目前主要用于水文，但它将误差分解为相关性、偏倚和变异性的思想，对你构建多作物、多维度的综合评价体系有很大启发。
3. **多目标与相对误差 (W 维度支撑)**：为了平衡高低数值，文章提出使用基于相对误差的指标（如 $NSE_{rel}$ 或 $MARE$）来提高模型对小数值部分的敏感度。这从另一个角度印证了你在 `W` 轴中设计 CV-based 或 NRMSE 策略（如 `W3` 和 `W5`）的正确性。

## 4. 可直接引用的原文片段

> "The poor overall performance from the NSE is an outcome of squaring errors, which makes the model insensitive to low-flow conditions... Optimizing NSE resulted in the general underestimation of peak-flows and over-estimation of low-flows."

- **用途**：在讨论使用原始均方误差（或不对变量做尺度对齐的 `W0` 方案）的坏处时，引用此句作为相邻领域的有力证据：即平方误差会导致对大数值的过拟合和对小数值的系统性偏差。

> "Therefore, putting more emphasis on relative errors during calibration will generally lead to better streamflow predictions for low flows. Although $NSE_{rel}$ squares the relative errors, as an objective function it performed close to MARE under low-flow conditions."

- **用途**：用于解释 `W5` (Mean-Normalization / NRMSE 口径) 或其他比例类加权方案为何能够平衡产量（大数值）和 LAI 早期动态（小数值）的拟合。

## 5. 面向研究设计的结构化提取

### 5.1 核心问题
探讨水文模型校准中应该使用何种拟合优度准则（Goodness-of-fit criteria），并分析不同准则（尤其是传统准则和新兴准则）在偏向高/低流量预测上的内在数学属性。

### 5.2 各类评价指标的数学偏好分析
- **均方根误差 (RMSE/MSE)** & **NSE**: 核心运算是“平方”，因此极度敏感于异常值或大数值的拟合误差（在水文里是洪峰，在作物里是最终产量和生物量）。
- **平均绝对误差 (MAE/mNSE)**: 不使用平方，因此对高低数值的敏感度更为平衡。
- **相对/对数误差 (MARE, $NSE_{rel}$, $NSE_{log}$)**: 由于分母除以了观测值或取了对数，小数值区间被显式放大，这使得优化器被迫关注小数值的拟合（在作物里相当于强行兼顾早期的 LAI 或叶片数等）。
- **Kling-Gupta Efficiency (KGE)**: 从相关系数、均值比、变异性（标准差）比三个独立维度计算欧氏距离，是一种内嵌的多目标折中。

### 5.3 结论推荐
- **避免单一使用 NSE/RMSE** 作为目标函数。
- **推荐 KGE** 作为全局优化目标。
- 强调相对误差型指标在小数值区间段的优势。

## 6. 对当前实验框架的直接启发

1. **评价体系的重构**：你的项目设计中已经指出“不要只看单一拟合优度”，要拆分 NRMSE, MAE 等。这篇文章给了你把 `MAE` 和 `RMSE` 分开报告的坚实理论支撑——`MAE` 更能反映真实分布的绝对误差，而 `RMSE` 更容易暴露是否存在异常烂的拟合点。
2. **KGE 在 DSSAT 中的潜在应用**：如果后续 `W9` (多目标) 分析觉得帕累托前沿难以单值化，你可以尝试在 DSSAT-PEST 的评价体系里引入水文学的 KGE 思想：即不要把所有残差揉在一起求和，而是分别计算各观测组的相关性、均值偏倚和方差，最后组合，这或许是一个比简单加权（W7/W8）更鲁棒的折中方案。
3. **“指标塑造了率定偏好”**：优化器（O）是瞎的，它只追求你给它的指标的极致。因此，出现负优化或代偿，不能怪 `O1` 或 `O2`，只能怪你给它的 `W` 和 `G`（损失构造）有漏洞。

## 7. 写论文时最可能用到的内容

- 在方法章节 (Methods) 中的 `Evaluation Criteria` 辩护段落，引用此文说明为何引入 MAE（对于物候日序等）和 NRMSE（相对误差形式）作为补充甚至核心指标。
- 在讨论章节 (Discussion)，将作物模型率定中由于未做尺度缩放导致产量主导的现象，与水文学界长期被 NSE/RMSE 主导导致基流拟合极差的现象进行跨学科类比，升华你的框架价值。

## 8. 代码、数据、软件与可追踪链接

- 该文基于 R 语言 (hydroPSO 包) 和 GR5J 水文模型。由于是综述兼应用文章，评价指标的公式（Eq. 1 - Eq. 17）是其核心价值，可以直接复用到 Python 数据处理流程中。

## 9. 是否推荐阅读原文

**推荐等级：中 (Medium)**

- 它是一篇很好的“指标手册”。对于你的作物课题，最有用的是 **Table 1** (各种指标优缺点总结) 和 **Section 2** 的理论解析。你不需要阅读它的 Cerrado 案例研究细节。

## 10. 如果阅读原文，应重点关注什么

- 关注 **Table 1** 对 NSE, mNSE, KGE, PBIAS, RMSE, MARE 的极简优缺点总结。
- **Eq 9** (KGE 的公式定义)，看是否可能被你的后处理脚本借鉴。

## 11. 对下一步工作的建议

- 你的 `Evaluation Criteria` 清单中已经有 NRMSE, MAE 和 Bias。你可以考虑从本文中吸取营养，确保在汇报物候偏差（如开花期）时坚决使用 MAE，而在对比产量/生物量等巨大数量级差异时使用 NRMSE/MARE。

## 12. 一句话结论

**水文学界对传统拟合优度指标（如 RMSE 和 NSE）的系统性反思表明，平方误差类指标必然导致优化器严重偏袒大数值观测；这一结论跨学科地支持了作物模型多量纲联合校准中引入尺度转换（W维）和相对误差评价的科学必然性。**