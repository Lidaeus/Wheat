# Lee and Choi (2022) — A rebalanced performance criterion for hydrological model calibration

## 1. 文献信息

- **标题**：*A rebalanced performance criterion for hydrological model calibration*
- **作者**：Jong Seok Lee, Hyun Il Choi
- **期刊**：*Journal of Hydrology*
- **年份**：2022
- **DOI**：`10.1016/j.jhydrol.2021.127372`
- **出版商链接**：[https://doi.org/10.1016/j.jhydrol.2021.127372](https://doi.org/10.1016/j.jhydrol.2021.127372)
- **证据等级**：`E3` (全文通读提取，核验了理论框架、评价准则的公式和研究对比结论)

## 2. 本轮提取说明

- **提取目标**：理解不同性能指标（NSE, KGE, LME, LCE）在水文模型校准中的内在偏差和重平衡机制，支持本项目在多维观测冲突和“评价体系（Evaluation Criteria）”设计上的探讨。
- **关联主线**：属于 `04_Performance_Criterion_and_Transfer`（性能指标的特性及相邻领域迁移）。

## 3. 这篇文章为什么与你的课题高度相关

1. **深入剖析了流行指标（NSE、KGE）的系统性缺陷**：文章用理论推导展示了，由于指标构成的数学性质，NSE 优化通常倾向于低估水流的变异性（underestimate flow variability），而 KGE 优化同样受限于其对相关系数的依赖。这种“指标自带的系统偏差”正是你在作物模型联合率定时常常面临的：当你只优化 RMSE 时，极容易高估某一部分（如产量），低估另一部分（如早期LAI变异）。
2. **“重平衡”思想的启示 (W和G维度支撑)**：为了克服不同评价成分（相关性 $r$、变异比 $\alpha$、偏差比 $\beta$）之间的代偿，作者提出了 LCE (Least-squares Combined Efficiency)，通过双向回归强迫模型在不同维度间进行妥协。虽然你的作物研究中并不一定直接使用 LCE，但这种在数学上对各项误差源进行“Rebalance”的哲学，非常契合你设计 `W`（权重/尺度对齐）轴的根本目的——防止单一目标主导。
3. **参数代偿的可视化**：雷达图（Radar charts，Fig. 5）清楚地展现了当使用不同目标函数时，最终获得的参数（如 $\alpha$ 和 $\beta$）分布截然不同。这也说明了优化器并非在找“绝对真理”，而是在响应指标的偏好。

## 4. 可直接引用的原文片段

> "If there is a systematic bias... in the streamflow simulation results... even when optimizing with one of the popular performance criteria, it will significantly reduce the validity and reliability on the use of the LSMs... The Nash and Sutcliffe Efficiency (NSE) most commonly used... tends to select the underestimated variability in the model streamflow because the optimal NSE is likely to occurs when $\alpha$ is equal to $r$ (which cannot achieve its ideal value of unity)."

- **用途**：引用此段论证为什么在作物模型率定中，如果直接使用类似 NSE 的全局均方误差，不仅掩盖了生物量与产量的矛盾，还会带来模型在某些变量上的系统性平滑（低估变异性）。这也是你为何需要进一步分解 MAE 和 NRMSE 的理由。

> "Gupta et al. (2009) decomposed the NSE into three distinctive components... the KGE implicitly based on the equally weighted three metric measures has been used... However, it has been found that the KGE criterion still tends to underestimate peak flows..."

- **用途**：论述任何预设了权重的综合指标（如 KGE 或作物率定里的简单加和）仍然可能带有偏好。这构成了你对 `W0-W9` 及多目标优化的深刻反思背景。

## 5. 面向研究设计的结构化提取

### 5.1 核心问题
探讨水文/陆面模型（LSM）在长期流量模拟中，因为目标函数（如 NSE, KGE, LME）本身的缺陷导致的系统性偏差（尤其是对流量峰值/低谷的估计不足或过度估计），并提出一个重平衡的指标 LCE。

### 5.2 各类评价指标的数学解构
- **NSE**：由相关系数($r$)、相对变异率($\alpha$)、标准化偏差($\beta_n$)组成。由于理想条件无法实现（$r<1$），为了使 NSE 最大化，优化器被迫使 $\alpha$ 向 $r$ 靠拢，导致 $\alpha < 1$（低估变异性）。
- **KGE**：将三者在帕累托空间中求欧氏距离，平衡了三者的比重，变异性比 NSE 更好，但在很多情况下仍然轻微低估高峰流量。
- **LME (Liu Mean Efficiency)**：基于单向线性回归，往往走向 $\alpha > 1$ 的另一极端，导致流量变异性被显著高估。
- **LCE**：结合正向和反向回归统计量的组合效率，作为一种对 LME 过拟合倾向的修正和对 KGE 低估倾向的重平衡。

### 5.3 实验验证
- 韩国四个大坝流域 30 年的模拟。
- 结果表明，优化器对不同的性能评价指标极其敏感；同一优化算法，仅仅是换了目标函数（从 NSE 换到 LCE），得出的陆面参数（衰减因子 $f$ 和 各向异性比 $\zeta$）就有系统性的不同。

## 6. 对当前实验框架的直接启发

1. **评价指标的透明化**：在你的实验中，如果出现 `O1/O2` 优化出的结果虽然 Train Fit 很好，但某些参数跑偏，或者 Validation Gap 很大的情况。不要觉得这是优化器坏了，这正是因为你的损失函数（基于 `W` 组合）有它的偏好。
2. **多目标折中的本质**：KGE 和 LCE 的本质是在相关性、变异性和偏差这“三个冲突目标”之间建立一个静态的几何平衡（欧氏距离）。你的 `W7` (Equal-Contribution) 和 `W9` (Pareto) 也是在做类似的事情，只不过针对的是不同类型的物理观测（Yield vs LAI）。

## 7. 写论文时最可能用到的内容

- 在讨论为何“不能仅仅把所有的变量塞进一个 RMSE 里去求最优解”时，引用此文。说明在模型率定中，**单目标的残差求和（类似 NSE）在数学结构上注定会导致对变异性（或某些特定组分）的系统性偏差**。
- 这不仅是优化领域的常识，在气候和水文领域也是多年研究的痛点。将其与你自己的 `S2`（隔离生理阶段）和 `G3`（细致分组）结合，证明你的实验设计是对抗这种系统性偏差的最佳工程策略。

## 8. 代码、数据、软件与可追踪链接

- 论文基于理论推导和 Common Land Model (CoLM) 的独立模拟，未在正文中附带开放的代码仓库链接。

## 9. 是否推荐阅读原文

**推荐等级：中 (Medium)**

- 这篇文章的理论性很强，详细的偏导数推导（Eq 6 及其相关部分）对非水文专业可能有些繁琐。重点理解其思想：**“综合指标在数学上会诱导参数补偿，导致模型在某些物理特性（如变异性）上的退化。”**

## 10. 如果阅读原文，应重点关注什么

- 关注 **2.1. Overview of NSE, KGE, and LME** 这一节，这是对经典水文指标缺陷最精辟的理论总结。
- 关注 **Fig 5** 的雷达图，它直观地展现了参数是如何为了迎合不同评价指标而改变分布形状的。

## 11. 对下一步工作的建议

- 你的论文应当在 Discussion 部分单独开辟一个小节，讨论“目标函数/评价指标的偏好”。在这个小节里，集中引用 Wallach (2011), Althoff (2021) 和 Lee (2022) 这三篇跨领域文献，以展现你研究视角的高度。

## 12. 一句话结论

**水文模型中流行评价指标（如 NSE 和 KGE）的代数解构表明，它们在数学层面上具有不可避免的系统偏差偏好（如牺牲变异性来换取相关性），这从底层逻辑上支撑了我们在作物率定中采用尺度转换（W）、观测分组（G）与阶段隔离（S）来重平衡多物理目标折中的必要性。**