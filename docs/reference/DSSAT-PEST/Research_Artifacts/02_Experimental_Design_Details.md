# 实验设计详述 (v3.2 - 科学研究版)

## 1. 核心假说
1. **生理路径隔离 (PPI)**：阶段式率定（S2/S3）相比联合率定（S1）能显著降低参数间的代偿性（数值互补），提升模型在不同气象年份的泛化能力。
2. **算法适配性**：`pestpp-ies`（集合平滑）在处理具有高度非线性和跳变特征的物候参数时，优于传统的 `pestpp-glm`（梯度下降）。

## 2. 实验维度 (修订后的 4D Matrix: W × O × S × G)
旧版仅显式包含 **权重方案 (W)**、**优化器 (O)** 与 **率定序列 (S)**，但未将“**观测分组 (Grouping)**”独立为实验轴。根据 AgMIP Phase 4、PEST 工程实践、当前 `DSSAT_PEST.r` 的实现方式以及 DSSAT 自带 GLUE 的两轮率定逻辑，**分组不是附属设置，而是决定权重、公平性与参数可辨识性的主轴变量**。因此本版将四维矩阵明确修订为：

- **W**：权重与尺度转换策略，只放“真正的损失缩放/赋权公式”，不再把 AgMIP Phase 4 误归为单独的权重方案。
- **O**：优化器引擎，决定搜索机制与是否支持真正多目标。
- **S**：率定序列/协议，决定是否遵循物候 -> 冠层/生物量 -> 产量的生理因果链；**AgMIP Phase 4 归入这里，而不是 W**。
- **G**：观测分组策略，决定损失函数的构造边界与 PWTADJ / WLS 是否具备统计意义。
- **B0**：官方默认参数基准，不作为矩阵维度，而作为所有实验组合都必须对照的外部锚点；其作用是识别“负优化”。

### 2.1 权重与尺度逻辑 (W) - 处理量纲冲突、异方差与组间公平性
| ID | 名称 | 类别 | 核心公式/操作 | 研究角色与适用逻辑 | 风险与限制 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| W0 | Raw-Identity | 基准对照 | 不做任何缩放，`w_h = 1` | 仅用于对照“量纲霸凌”现象 | 极易被产量或高频序列主导 |
| W1 | Inverse-Variance | 经典统计 | `w_h = 1 / sigma_h^2` 或 `1 / sigma_h` | 当观测误差方差可可信估时，具备明确统计学解释 | 在存在结构性误差时常失真 |
| W2 | Inverse-RMSE | 动态惩罚 | `w_h = 1 / RMSE_h` | 以当前拟合误差反向惩罚差预测指标，适合迭代更新 | 早期迭代可能不稳定 |
| W3 | CV-based | 相对波动惩罚 | `w_h = 1 / CV_h`，`CV = sigma / mu` | 适合比较不同量纲、不同噪声等级的观测组 | 当 `mu` 接近 0 时不稳 |
| W4 | Min-Max Equal | 工程归一化 | 先做 `X' = (X - min) / (max - min)`，再设 `w_h = 1` | 消除量纲陷阱，使 Yield、LAI、Biomass 落入同一空间 | 对极值敏感，需固定缩放边界 |
| W5 | Mean-Normalization | NRMSE 口径 | `r_norm = (Obs - Sim) / mean(Obs)` | 与农学常用 NRMSE 一致，便于和文献横向对比 | 苗期 LAI 等低均值变量会数值爆炸 |
| W6 | Log-Transformation | 方差稳定化 | 对目标变量拟合 `ln(Y)` 或 `log10(Y)` | 专门处理 Biomass、LAI 等时序累积变量的异方差 | 仅适用于正值变量，需处理 0 值 |
| W7 | Equal-Contribution / PWTADJ1 | 动态平衡 | 先跑 Iteration 0，再按组调整权重使各组初始贡献相等 | 当前最具工程可行性的公平方案，尤其适合 PEST | 依赖高质量分组，且本质仍是标量化 |
| W8 | DSSAT-PEST Group-Max Scaling | 文献-工程双基线 | 对每个观测组执行 `weight_g = 1 / max(y_obs in group g)` | 既与当前 `DSSAT_PEST.r` 一致，又可作为外部高水平论文中的参考 baseline 之一，适合作为五作物主实验的首要参照组 | 只做尺度对齐，不等于统计最优 WLS；论文复现时需额外说明其“参考基线”而非“理论最优”定位 |
| W9 | Pareto / No Pre-Weight | 真多目标 | 不预设数学权重，直接输出帕累托前沿 | 将“定权重”延后给决策者，适合 Yield-LAI-水氮权衡 | 仅适用于多目标优化器，结果不是单一最优点 |

这里特别澄清：**AgMIP Phase 4 不是一个“权重公式”，而是一个“两步走率定协议”**。它内部会用到 WLS，但应归入 **S 维度**；而 `W8` 则对应当前仓库已经落地、且可作为文献参考 baseline 的组级缩放逻辑。

### 2.2 优化器引擎 (O) - 主流家族全覆盖
| ID | 家族 | 引擎 | 目标形式 | 路径/实现 | 适用逻辑 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| O1 | 梯度型 | **pestpp-glm** | 标量化损失 | `...\bin\pestpp-glm.exe` | 收敛快，适合 W1-W8；可输出 JCO 便于分析 Equifinality |
| O2 | 集合型 | **pestpp-ies** | 标量化损失 | `...\bin\pestpp-ies.exe` | 对非线性、跳变型物候参数更稳健，适合高噪声情景 |
| O3 | 全局型 | **Dual Annealing** | 标量化损失 | SciPy Implementation | 适合粗糙目标面与局部极值较多的问题 |
| O4 | 演化多目标型 | **NSGA-II** | 向量目标 | `pymoo` / Python workflow | 支持 W9，直接生成 Pareto Front，适合多目标权衡研究 |
| O5 | 梯度多目标型 | **MGDA** | 向量目标 + 公共下降方向 | Python workflow / autodiff wrapper | 本质是优化器而不是分组方案；适合少量、平滑、可微的组级目标 |

这里进一步澄清：当前沙盒中出现的 `Pure_MGDA_Baseline` 只是一个**实现命名上的折中**，不应在研究设计里继续被当作“权重方案”。在正式矩阵中，**MGDA 归入 O 维**；它使用哪一组目标、这些目标是否按组组织，则由 **G 维** 决定。

### 2.3 率定序列 (S) - 生理约束与参数可辨识性
| ID | 名称 | 执行路径 | 核心目的 | 备注 |
| :--- | :--- | :--- | :--- | :--- |
| S1 | Naive Joint | `Optimize(All Parameters Together)` | 构造“无生理约束”基准组 | 最易产生参数代偿，作为反例对照 |
| S2 | Sequential Phase | `Fix Phenology -> Optimize Canopy/Biomass -> Optimize Yield` | 强制遵循生理因果链，降低 Equifinality | 对应组 B，单品种主实验推荐路径 |
| S3 | WLS Joint | `Initial(S2) -> Global WLS(All Groups)` | 先利用 S2 获得机理上合理的初值，再做全量加权微调 | 对应组 C，也是 AgMIP Phase 4 在本项目中的落地方式 |

当前五作物主实验中，**S 轴只保留 `S1-S3`**，不纳入 `S4`，原因如下：

- 当前 `DSSAT-PEST` 这套五作物模板实际都是 **cultivar-level** 率定入口；`DSSAT_PEST.r` 直接按 `CultivarName` 定位 `.CUL` 中的品种行，并没有形成独立的 `ECO` 级参数估计管道。
- `MZCER046.tpl` 与 `RICER046.tpl` 还明确写出 `ECO# ... currently not used`，说明现有工程并未真正把 Ecotype 层纳入可估参数链路。
- 因此，对这五作物的当前实验而言，`S4` 不属于“暂时靠边的备选组”，而是**没有现实执行基础的超范围设计**；从当前矩阵中删除是合理的。
- 若未来扩展到**同一作物下多基因型、多环境联合率定**，再单独重建 `Ecotype -> Cultivar` 的层级实验即可。

### 2.4 观测分组策略 (G) - 将“分组”提升为独立实验轴
| ID | 名称 | 观测组构造 | 典型变量 | 研究用途 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| G1 | Flat-All-in-One | 不分组，全部观测合并为单一损失 | HWAM, GWAM, ADAT, MDAT, LAIX, CWAM, SWAD, NIAD | 仅用于证明“混合全局率定”的缺陷 | 只建议与 S1 联用 |
| G3 | DSSAT-PEST Extended Grouping | 物候组 / 冠层-生物量组 / 产量构成组 / 状态变量组 | `ADAT, MDAT` / `LAIX, CWAM` / `HWAM, GWAM, G#` / `SWAD, NIAD` | 为 PWTADJ1 与 WLS 提供最完整分组框架 | 支持 W7、W8 |

当前仓库的 **DSSAT-PEST 实装细节** 需要作为 G 维的落地依据：

- `ParameterOutput.csv` 中，**输出行第 4 列**控制该观测是否参与率定，**第 6 列**作为分组编号。
- `DSSAT_PEST.r` 会读取 `Out_Mark <- rbind(ParameterOutput_Out0[,3], as.numeric(ParameterOutput_Out0[,6]))`，再用观测名前 4 个字符将 `nash.pst` 中的观测条目映射回组号。
- 当前脚本对每组统一执行 `weight_g = 1 / max(y_obs in group g)`，然后整块回写 `nash.pst` 的 `* observation data` 区域。

为了让五作物实验在实现层面完全对齐 `DSSAT-PEST`，这里把 **G3 组号字典** 直接按 `ParameterOutput.csv` 的输出定义固化下来。以下映射采用“**源文件原样对齐**”原则：即便个别作物的组号语义略有漂移，也不做人工统一改写，以免后续 `nash.pst` 权重回写与实际脚本不一致。

**五种作物的 G3 分组映射表**

| 作物 | 组号 | 组内指标 |
| :--- | :--- | :--- |
| Maize | 1 | `EDAP, ADAP, PD1P, PDFP, MDAP` |
| Maize | 2 | `HWAM, CWAM, BWAM, CWAA` |
| Maize | 3 | `GNAM, CNAM, SNAM, CNAA` |
| Maize | 4 | `LAIX` |
| Maize | 5 | `HIAM, THAM, GN%M` |
| Maize | 6 | `HWUM` |
| Maize | 7 | `H#AM, H#UM` |
| Maize | 8 | `PWAM` |
| Maize | 9 | `L#SM` |
| Wheat | 1 | `EDAP, DRAP, TSAP, ADAP, MDAP` |
| Wheat | 2 | `HWAM, CWAM, VWAM` |
| Wheat | 3 | `CNAM, HNAM` |
| Wheat | 4 | `LAIX` |
| Wheat | 5 | `HIAM, HN%M, VN%M, HINM` |
| Wheat | 6 | `HWUM` |
| Wheat | 7 | `H#AM, H#GM, T#AM` |
| Wheat | 9 | `L#SM` |
| Soybean | 1 | `EDAP, ADAP, PD1P, PDFP, MDAP` |
| Soybean | 2 | `HWAM, CWAM, BWAM, CWAA` |
| Soybean | 3 | `GNAM, CNAM, SNAM, GN%M, CNAA` |
| Soybean | 4 | `LAIX` |
| Soybean | 5 | `HIAM` |
| Soybean | 6 | `HWUM, H#UM` |
| Soybean | 7 | `H#AM` |
| Soybean | 8 | `PWAM` |
| Soybean | 9 | `L#SM` |
| Soybean | 10 | `CHTA` |
| Soybean | 11 | `THAM, GL%M` |
| Rice | 1 | `EDAP, IDAP, ADAP, MDAP` |
| Rice | 2 | `HWAM, CWAA, CWAM, BWAM` |
| Rice | 3 | `GNAM, CNAA, CNAM, SNAM, GN%M` |
| Rice | 4 | `LAIX` |
| Rice | 5 | `HIAM` |
| Rice | 6 | `HWUM` |
| Rice | 7 | `H#AM, P#AM` |
| Rice | 9 | `L#SM` |
| Cotton | 1 | `EDAP, ADAP, PD1P, PDFP, MDAP, R8AP` |
| Cotton | 2 | `HWAM, CWAM, BWAM` |
| Cotton | 3 | `GNAM, CNAM, SNAM, GN%M, CNAA` |
| Cotton | 4 | `LAIX, CWAA` |
| Cotton | 5 | `HIAM` |
| Cotton | 6 | `HWUM` |
| Cotton | 7 | `H#AM, H#UM` |
| Cotton | 8 | `PWAM` |
| Cotton | 9 | `L#SM` |
| Cotton | 10 | `CHTA` |
| Cotton | 11 | `THAM, GL%M` |

其中有三点需要特别固定：

- **Wheat** 仍是本项目最规整的参考模板，最适合定义 `S2` 的“物候 → 冠层/生物量 → 产量”阶段切分。
- **Soybean、Rice、Cotton** 虽共享大部分组号语义，但并不强求每个组都存在；缺失组应视为“该作物无此观测域”，而不是需要补齐的空槽位。
- **Cotton 的 `CWAA` 被放在组 4 而非组 2，Maize 的 `THAM` 与 `GN%M` 被放在组 5**；这些都是现有 `ParameterOutput.csv` 的原始定义。若目标是与 `DSSAT-PEST` 完全一致，就应原样继承，而不在研究设计阶段先做人为归并。

为了便于后续**批量实验配置生成**，还可以把上面的逐作物字典再压缩成一张统一摘要表。

**跨五作物统一组号语义总表**

| 组号 | 统一语义 | 代表指标 | 五作物覆盖情况 |
| :--- | :--- | :--- | :--- |
| 1 | 物候 / 发育时间组 | `EDAP, ADAP, MDAP, PD1P, PDFP, DRAP, TSAP, IDAP, R8AP` | 五种作物均存在 |
| 2 | 产量 / 地上部生物量总量组 | `HWAM, CWAM, BWAM, VWAM, CWAA` | 五种作物均存在 |
| 3 | 氮素总量组 | `GNAM, CNAM, SNAM, CNAA, HNAM, GN%M` | 五种作物均存在 |
| 4 | 冠层 / 结构状态组 | `LAIX`，以及 Cotton 中的 `CWAA` | 五种作物均存在 |
| 5 | 比例 / 品质 / 指数组 | `HIAM, HN%M, VN%M, HINM, THAM, GN%M` | 五种作物均存在 |
| 6 | 单位器官重组 | `HWUM, H#UM` | 五种作物均存在 |
| 7 | 数量结构组 | `H#AM, H#UM, H#GM, T#AM, P#AM` | 五种作物均存在 |
| 8 | 穗 / 荚 / 经济器官产量组 | `PWAM` | Maize、Soybean、Cotton 存在；Wheat、Rice 缺失 |
| 9 | 叶片数组 | `L#SM` | 五种作物均存在 |
| 10 | 株高组 | `CHTA` | Soybean、Cotton 存在；Maize、Wheat、Rice 缺失 |
| 11 | 脱粒率 / 组分类比例组 | `THAM, GL%M` | Soybean、Cotton 存在；Maize、Wheat、Rice 缺失 |

上表可以直接作为后续脚本生成批量配置时的“**统一组号模板**”：先按组号 `1-11` 建标准组集合，再按作物裁剪掉不存在的组。

**各作物缺失组清单（相对于统一组号 1-11）**

| 作物 | 缺失组号 | 说明 |
| :--- | :--- | :--- |
| Maize | `10, 11` | 无株高组、无脱粒率/组分类比例组 |
| Wheat | `8, 10, 11` | 无 `PWAM` 组、无株高组、无脱粒率/组分类比例组 |
| Soybean | 无 | 已覆盖 `1-11` 全部组号 |
| Rice | `8, 10, 11` | 无 `PWAM` 组、无株高组、无脱粒率/组分类比例组 |
| Cotton | 无 | 已覆盖 `1-11` 全部组号 |

因此，若后续要程序化生成五作物实验矩阵，建议采用以下规则：

- **统一主模板**：先定义 `groups = [1,2,3,4,5,6,7,8,9,10,11]`
- **作物级裁剪**：对每个作物按“缺失组清单”删除空组
- **指标级展开**：再从对应作物的 `G3` 字典中展开组内指标
- **权重级落地**：最终仍以 `ParameterOutput.csv` 第 6 列和 `DSSAT_PEST.r` 的回写逻辑为准，不额外发明新组号

据此，当前实验设计里真正保留的分组实现应收敛为：

- **G3 / DSSAT-PEST Extended Grouping**：直接保留现有细分组号，用于 PWTADJ1 或 S3 的全量 WLS 微调。

这里需要把“实验轴”和“解释视角”分开：

- **G3** 是**工程实现层**：尽量保留 `ParameterOutput.csv` 里已有的细分组号，便于复用当前 `DSSAT-PEST` 的组权重、`PWTADJ1` 与 `nash.pst` 回写逻辑。
- **当前主实验的 G 轴只保留 `G1` 与 `G3`**：`G1` 负责无分组反例，`G3` 负责所有正式分组实验。
- **G2 不再作为矩阵维度**：若后续需要把 `G3` 的细分组号向上投影成“物候 / 动态 / 产量”三大块，那只是**结果解释视角**，不是独立运行一套新的分组协议。
- **DSSAT-PEST 当前项目实际采用的是 `G3` 风格**，因此把主实验完全对齐到 `G3` 是合理且更稳的选择。
- **DSSAT 自带 GLUE 更接近 `G2` 的两块简化版**：`MeasurementVariance_*.csv` 用 `Flag = 1` 选择物候类指标、`Flag = 2` 选择生长/产量类指标，两轮分别率定，并没有保留 `G3` 这种扩展细分组结构。

### 2.5 率定序列组 B / 组 C 的具体实现方案
本研究的“生理路径隔离 (Physiological Path Isolation)”不写成抽象口号，而是直接复用现有工程机制：**参数子集通过 `ParameterOutput.csv` 的参数行第 4 列开关控制，观测子集通过输出行第 4 列控制，分组通过输出行第 6 列控制，最终仍由现有 `DSSAT_PEST.r` 生成并重写 `nash.pst`**。

#### 组 A (S1: Naive Joint)
- 启用全部 7 个小麦品种参数：`P1V, P1D, P5, G1, G2, G3, PHINT`
- 启用全部核心观测：`ADAP, MDAP, LAIX, CWAM, HWAM, HWUM`
- 使用单次全参数率定，作为“无机理隔离”基准组

#### 组 B (S2: Sequential Phase)
**Phase B1 - Phenology / 时间轴锁定**

- **启用参数**：`P1V, P1D, P5, PHINT`
- **冻结参数**：`G1, G2, G3`
- **启用观测**：优先 `ADAP, MDAP`；若数据完整，可附加 `EDAP, DRAP, TSAP`
- **实现方式**：将参数行中 `G1, G2, G3` 的第 4 列置为 `0`，输出行中非物候组的第 4 列置为 `0`
- **目标**：先把发育进程与生命周期卡准，建立“时间轴”

**Phase B2 - Canopy / Biomass**

- **启用参数**：`G1`
- **冻结参数**：`P1V, P1D, P5, PHINT, G2, G3`
- **启用观测**：核心使用 `LAIX, CWAM`；若观测齐全，可追加 `VWAM, L#SM`
- **实现方式**：沿用 B1 的最优参数作为初值，重新生成阶段性 `nash.pst`，仅放开 `G1`
- **目标**：在不破坏物候期的前提下，校正冠层扩展与生物量累积

**Phase B3 - Yield**

- **启用参数**：`G2, G3`
- **冻结参数**：`P1V, P1D, P5, PHINT, G1`
- **启用观测**：核心使用 `HWAM`；建议把 `HWUM` 作为辅助约束，必要时加入 `HIAM`
- **实现方式**：沿用 B2 的最优参数作为初值，生成第三阶段 `nash.pst`
- **目标**：只在“数值轴”上调整籽粒形成与分配，不再改动时间轴

这种三阶段方案与 DSSAT 自带 **GLUE** 的两轮机制是一致扩展：GLUE 在第一轮只动 **P 类物候参数**，第二轮再动 **G 类生长参数**；本项目把第二轮进一步拆成“冠层/生物量”和“最终产量”两个子阶段，从而更贴合 Wheat 的 `G1 / G2 / G3` 生理分工。

#### 组 C (S3: WLS Joint)
组 C 不是“再来一次普通全参数率定”，而是 **以组 B 结果为起点的全量加权微调协议**：

1. **初值来源**：把 B3 结束后的参数组合作为 `nash.pst` 参数初值。
2. **重新启用参数**：`P1V, P1D, P5, G1, G2, G3, PHINT` 全部恢复为可调。
3. **缩小边界**：各参数边界不再使用原始全局上下界，而是在 B 组最优值附近做局部收缩，再与原始边界取交集。
4. **重新启用观测组**：至少启用 `ADAP, MDAP, LAIX, CWAM, HWAM, HWUM`，并根据数据完整性决定是否加入 `HIAM, CNAM, HNAM`。
5. **权重构造**：不再使用“凭经验手调”的静态权重，而是从 B1/B2/B3 的阶段残差估计组方差 `sigma_g^2`，再写成全量 WLS 权重。
6. **落地位置**：复用当前 `DSSAT_PEST.r` 的 `* observation data` 重写入口，只把组权重计算公式从 `1 / max(y_obs)` 替换为 `1 / sigma_g^2` 或其标准化形式。

因此，**AgMIP Phase 4 在本项目中的定义应写成：S3 = “先 S2，再按组残差做全量 WLS 微调”**，而不是把它单列为某一种 W。

### 2.6 组合约束与主实验裁剪
为避免组合爆炸，本研究不执行完全笛卡尔积，而是采用“**核心对照层 + 前沿扩展层**”：

- **外部基线 B0**：先直接运行 DSSAT 官方默认参数，不做任何优化，输出与主实验完全相同的评分表；任何组合若整体劣于 B0，应标记为“负优化”。
- **核心对照层**：`{W0, W4, W6, W7, W8, W9} × {O1, O2, O3, O4} × {S1, S2, S3} × {G1, G3}`。
- **前沿扩展层**：`W1, W2, W3, W5, O5` 仅在核心层结果明确后纳入，以验证统计权重与 MGDA 是否带来额外增益。
- **兼容性约束 1**：`W7, W8` 仅在 `G3` 下有意义，因为需要先定义观测组贡献。
- **兼容性约束 2**：`W9` 仅与真正的多目标优化器联用，即 `O4 (NSGA-II)` 或 `O5 (MGDA)`；若使用 `O1-O3`，就必须先把多目标重新标量化，因此已不再是 W9。
- **兼容性约束 3**：`O5 (MGDA)` 只建议与**静态、平滑、可微**的目标定义联用；因此优先适配 `W5/W9 + G3`，不建议与 `W7/W8` 这类会在迭代中动态改权的方案直接混用。
- **兼容性约束 4**：`O3 (Dual Annealing)` 更适合静态标量损失；对 `W7/W8` 这类动态调权或两步重构目标的方案，只能做探索性试验，不能假设与 `O1/O2` 等价兼容。
- **兼容性约束 5**：`S3` 依赖 `S2` 的阶段最优值与阶段残差，因此它不是可独立启动的“平行组”，而是组 C 协议。
- **推荐的三类组合族**：
  - **标量静态族**：`W0-W6 × O1-O3`，用于主流单目标比较。
  - **分组加权族**：`W7-W8 × O1-O2 × G3`，用于检验 PWTADJ/WLS 的工程收益。
  - **真多目标族**：`W9 × O4/O5 × G3`，用于把“权重”后移给决策阶段。
- **建议主比较路径**：`B0` 对比 `(W8, O1/O2, S1, G1)` 与 `(W8, O1/O2, S2, G3)`，再用 `(W7 或 W1, O1/O2, S3, G3)` 检验 WLS 微调是否在不破坏物候的前提下降低产量误差；最后以 `(W9, O4/O5, S2, G3)` 作为真多目标对照。

### 2.7 组合决策表（允许 / 禁止 / 仅探索性）
下表用于在真正开跑矩阵前先裁剪掉“理论上能拼、实际上不应拼”的组合，避免后续反复讨论。

| 组合模式 | 决策 | 原因 | 备注 |
| :--- | :--- | :--- | :--- |
| `B0 × 任意评分协议` | 允许 | 统一基线，识别负优化 | 不属于优化矩阵格点，但必须先跑 |
| `W0-W6 × O1-O3 × S1/S2 × G1/G3` | 允许 | 静态标量损失，数值行为最稳定 | 作为主实验主体 |
| `W7-W8 × O1/O2 × S2/S3 × G3` | 允许 | 分组加权、PWTADJ、WLS 与 PEST 家族最匹配 | 是工程主线 |
| `W9 × O4/O5 × S2 × G3` | 允许 | 真多目标与多目标优化器匹配 | 作为前沿对照 |
| `W9 × O1-O3` | 禁止 | 一旦求和标量化，就不再是 W9 | 应改归 `W0-W8` 体系 |
| `W7-W8 × O4` | 禁止 | NSGA-II 需要稳定目标向量，动态组权会改变目标定义 | 除非另行重写为固定向量目标 |
| `W7-W8 × O3` | 仅探索性 | 动态调权会让全局无导数搜索看到移动目标面 | 可做小预算试验，不进主结论 |
| `W9 × O5 × G1` | 仅探索性 | 无分组时，多目标向量过于粗糙，MGDA 价值有限 | 优先改用 G3 |
| `S3 × 无 S2 初值` | 禁止 | S3 依赖阶段最优值与组残差，脱离 S2 无法成立 | 属于协议依赖，而非独立序列 |
| `S2/S3 × O5` | 仅探索性 | MGDA 更依赖平滑、可微的阶段目标定义 | 需先确认目标可导且组数不宜过多 |

实际执行时，优先顺序应固定为：

- **第一批**：`B0` + `W0-W6 × O1-O3 × S1/S2 × G1/G3`
- **第二批**：`W7-W8 × O1/O2 × S2/S3 × G3`
- **第三批**：`W9 × O4/O5 × S2 × G3`

## 3. 诊断与评价体系
- **NRMSE / RRMSE (Train)**：基础主指标，分别对 Yield、Phenology、Dynamics 各组统计；与 DSSAT-PEST 论文里的 relative root mean square error 口径保持一致。
- **MAE for Phenology**：对 `ADAP, MDAP` 等物候日序单独报告绝对误差（天）；相较相对误差更直观，也避免“几天偏差被百分比夸大”。
- **AREs (Supplementary)**：按 `AREs = (100 / n) * sum(abs((Sim_i - Obs_i) / Obs_i))` 计算，作为与 DSSAT-PEST 文献对比的补充指标；仅用于严格正值且不接近 0 的变量，不作为主排序指标。
- **Bias / NMBE**：区分系统性高估与低估，防止仅看绝对误差而忽略方向性偏差。
- **Group Contribution Balance**：检查各观测组在目标函数中的初始与收敛后贡献占比，验证 W7/W8 是否真正实现公平。
- **Pareto Hypervolume / Spread**：仅用于 O4，评价帕累托前沿的覆盖度与均匀性。
- **Equifinality Index**：基于 JCO 或参数协方差结构分析参数补偿与相关性。
- **Parameter Plausibility**：参数是否落入作物生理推荐范围，防止“拟合对了、机理错了”。
- **Generalization Gap**：训练环境与验证环境误差差值，用于检验阶段式率定的泛化性。
- **Hydrology Proxy**：物候期偏差作为水文模拟中“起始流量时间”的代理指标。
