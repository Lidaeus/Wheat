# PEST 校准机制与输出结果

## 1. 先回答一个核心问题

为什么这个项目不是直接把 DSSAT 跑完就结束，而是还要生成一整套 PEST 文件？

答案是：DSSAT 只能“给定参数做模拟”，但不能高效完成“基于观测数据自动反推最优参数”。PEST 正是用来做这件事的。

所以这套工程实际上是在做：

- DSSAT 提供前向模型
- PEST 提供反演/估计能力
- R 提供中间胶水层

## 2. PEST 所需文件在本项目中如何落地

## 2.1 tpl：模板文件

`tpl` 的作用是告诉 PEST：模型输入文件中，哪些位置是可调参数。

在本项目中：

- 模板来自目标 `.CUL` 文件
- 待优化参数被替换成 `^...^` 标记

对应代码：

- [DSSAT_PEST.r:L217-L227](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L217-L227)

样例文件：

- [MZCER046.tpl](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/MZCER046.tpl)

## 2.2 pmt 与 par：参数名和初值

`pmt` 是参数名列表，`par` 是参数初值文件。

对应代码：

- [DSSAT_PEST.r:L247-L258](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L247-L258)

样例：

- [MZCER046.pmt](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/MZCER046.pmt#L1-L6)
- `MZCER046.par`

## 2.3 ins：输出提取指令

`ins` 的作用是告诉 PEST：模型运行结束后，到输出文件的哪些字符位置抓取模拟结果或观测结果。

对应代码：

- [DSSAT_PEST.r:L271-L331](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L271-L331)

样例：

- [Evaluate.ins](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/Evaluate.ins#L1-L4)
- [Measure.ins](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/Measure.ins#L1-L4)

## 2.4 pst：控制文件

`pst` 是 PEST 的总控制文件，里面定义：

- 控制参数
- 参数组
- 参数初值与边界
- 观测值与权重
- 模型命令
- 模型输入输出映射

样例见 [nash.pst](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/nash.pst#L1-L49)。

## 2.5 bat：模型命令包装

PEST 不直接懂 DSSAT 项目结构，所以脚本还生成了批处理文件：

- [nash.bat](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/nash.bat#L1-L3)
- `pest1.bat`
- `pest2.bat`
- `pest3.bat`
- `pest4.bat`

这些文件负责把 PEST 工具和 DSSAT 模型接起来。

## 3. 当前样例的 PEST 控制链

如果用一句话描述当前玉米样例的执行链，就是：

`PEST -> nash.pst -> nash.bat -> DSCSM046.EXE -> Evaluate.OUT -> Evaluate.ins`

对应关系可以在 [nash.pst:L44-L48](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/nash.pst#L44-L48) 里直接看到：

- model command line 指向 `nash.bat`
- model input/output 里指定 `MZCER046.tpl -> MZCER046.CUL`
- 以及 `Evaluate.ins -> Evaluate.OUT`

## 4. 权重机制怎么做的

这是项目中一个很有意思的细节。

脚本不是给每个观测值随便写权重，而是先“分组”，再“按组赋权”。

## 4.1 权重逻辑入口在哪里

核心代码在：

- [DSSAT_PEST.r:L429-L453](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L429-L453)

而分组元数据来自：

- [DSSAT_PEST.r:L45-L49](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L45-L49)
- [ParameterOutput.csv](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/ParameterOutput.csv#L9-L30)

这里有两个关键变量：

- `Out_user <- as.numeric(ParameterOutput_Out0[,5])`
- `Out_Mark <- rbind(ParameterOutput_Out0[,3], as.numeric(ParameterOutput_Out0[,6]))`

可以这样理解：

- `Out_user` 读入了输出定义表中的第 5 列
- `Out_Mark` 的第一行是输出变量名，第二行是分组编号

在当前权重实现里，真正决定“谁和谁属于同一组”的是第 6 列，也就是 `Out_Mark` 的第二行。

## 4.2 脚本如何识别观测指标属于哪一组

脚本会先读取 `nash.pst` 中 `* observation data` 到 `* model command line` 之间的观测定义区，再把每条观测的名字取前 4 个字符：

- `adap1` -> `adap`
- `mdap1` -> `mdap`
- `hwam2` -> `hwam`

对应代码：

- [DSSAT_PEST.r:L429-L438](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L429-L438)

然后用这 4 个字符去匹配 `Out_Mark` 中保存的输出变量名，从而找到该观测对应的分组号。

这一步的效果可以理解为：

1. 从 `ParameterOutput.csv` 读取输出分组标识
2. 把 `nash.pst` 中的具体观测记录映射回这些分组
3. 让同组观测共享同一套权重尺度

## 4.3 当前玉米样例的分组结果

结合 [ParameterOutput.csv](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/ParameterOutput.csv#L9-L30)、[Evaluate.ins](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/Evaluate.ins#L1-L4) 和 [pst_weight.txt](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/pst_weight.txt#L1-L16)，当前真正参与拟合的玉米指标可理解为：

| 指标 | 分组编号 | 观测值样例 | 组内最大观测值 | 最终权重 |
|---|---:|---|---:|---:|
| `ADAP` | 1 | 78, 78 | 141 | 1 / 141 = 0.0070921986 |
| `MDAP` | 1 | 141, 141 | 141 | 1 / 141 = 0.0070921986 |
| `HWAM` | 2 | 10960, 7560 | 23970 | 1 / 23970 = 4.1718815e-05 |
| `CWAM` | 2 | 23970, 19950 | 23970 | 1 / 23970 = 4.1718815e-05 |
| `HWUM` | 6 | 0.309, 0.264 | 0.309 | 1 / 0.309 = 3.23624595 |
| `H#UM` | 7 | 531, 476 | 531 | 1 / 531 = 0.00188323917 |
| `LAIX` | 4 | 6.15, 5.06 | 6.15 | 1 / 6.15 = 0.1626016260 |
| `HIAM` | 5 | 0.46, 0.39 | 0.46 | 1 / 0.46 = 2.1739130435 |

这里最关键的是第 1 组和第 2 组：

- `ADAP` 与 `MDAP` 共享同一个权重，因为它们都属于组 1
- `HWAM` 与 `CWAM` 共享同一个权重，因为它们都属于组 2

这能从 [pst_weight.txt](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/pst_weight.txt#L1-L16) 中直接验证。

## 4.4 权重公式到底是什么

对每个组，脚本执行的是：

1. 找出该组全部观测值
2. 计算该组的 `max(observation)`
3. 给该组所有观测统一赋值 `weight = 1 / max(observation)`

对应代码：

- [DSSAT_PEST.r:L443-L448](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L443-L448)

可以写成：

`weight_g = 1 / max(y_obs in group g)`

然后对组内所有观测 `i`：

`weight_i = weight_g`

## 4.5 这种设计的直觉是什么

这意味着：

- 单位大、数量级大的变量会被缩小影响
- 单位小、数量级小的变量不会被大变量完全压制

本质上是一种量纲尺度平衡。

更具体一点说：

- 如果直接用原始值，`HWAM` 这种上万量级指标会压过 `HIAM` 这种小数指标
- 现在先按组取最大观测值倒数，相当于把每组变量缩放到相近量级
- 组内多个指标再共享同一缩放因子，可以保持同类指标的一致性

## 4.6 跨作物检查后，可以看到一套“半通用分组体系”

在继续检查其他作物样例后，可以发现这个仓库并不是只在玉米上偶然这么分组，而是在多个作物上复用了相近的组号语义。

可直接对照：

- 小麦：[ParameterOutput.csv:L40-L59](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/ParameterOutput.csv#L40-L59)
- 大豆：[ParameterOutput.csv:L80-L104](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/ParameterOutput.csv#L80-L104)
- 水稻：[ParameterOutput.csv:L177-L195](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/ParameterOutput.csv#L177-L195)

从这些作物里可以归纳出如下规律：

| 组号 | 跨作物常见指标 | 我对其业务语义的理解 |
|---|---|---|
| `1` | `EDAP`、`ADAP`、`MDAP`、`PD1P`、`PDFP`、`DRAP`、`TSAP` | 物候与发育阶段时间 |
| `2` | `HWAM`、`CWAM`、`BWAM`、`VWAM`、`CWAA` | 产量、地上部生物量、干物质量 |
| `3` | `GNAM`、`CNAM`、`SNAM`、`CNAA`、`HNAM` | 氮素累积量 |
| `4` | `LAIX` | 冠层大小或叶面积 |
| `5` | `HIAM`、`HN%M`、`VN%M`、`HINM` | 指数、比例、浓度类指标 |
| `6` | `HWUM` | 单位粒重、单位器官重 |
| `7` | `H#AM`、`H#UM`、`H#GM`、`T#AM`、`P#AM` | 数量型指标 |
| `8` | `PWAM` | 穗/荚/穗部相关产量 |
| `9` | `L#SM` | 叶片数 |
| `10` | `CHTA` | 株高 |
| `11` | `THAM`、`GL%M` | 脱粒率或组分类比例 |

这个发现非常重要，因为它说明当前项目实际上已经隐含了一套“指标分类学”：

- 先按生理含义分域
- 再在每个域内做量纲平衡
- 最终避免某一个大数值域垄断率定结果

## 4.7 但不同作物的配置完整度并不一致

继续往后看会发现，项目里并不是每个作物都像玉米、小麦、大豆、水稻这样配得完整。

例如：

- 大麦：[ParameterOutput.csv:L115-L134](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/ParameterOutput.csv#L115-L134)
- 高粱：[ParameterOutput.csv:L212-L234](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/ParameterOutput.csv#L212-L234)

这些区段里的很多 `Output` 行只有启用标志，后续第 5、6 列是空的。也就是说：

- 指标名列出来了
- 但“粗筛权重”和“PEST 分组键”并没有完善配置

这对实际率定有两个启发：

- 仓库里“列出指标”不等于“已经设计好权重方案”
- 在复用某个作物模板前，必须先检查输出定义是否完整

## 4.8 因此，设计分组时更合理的思路是什么

从跨作物配置看，这个项目比较推荐的不是“每个指标单独一个组”，而是“按观测域分组”。

更适合的分组思路通常是：

### 第一层：物候组

典型指标：

- `EDAP`
- `ADAP`
- `MDAP`
- `PD1P`
- `PDFP`

这些指标共同约束的是发育进程和阶段时序。

### 第二层：产量与生物量组

典型指标：

- `HWAM`
- `CWAM`
- `BWAM`
- `VWAM`
- `CWAA`

这些指标共同约束的是碳同化、分配与最终产量形成。

### 第三层：氮素组

典型指标：

- `GNAM`
- `CNAM`
- `SNAM`
- `CNAA`
- `HNAM`

这些指标共同约束氮吸收、分配与积累。

### 第四层：结构组

典型指标：

- `LAIX`
- `L#SM`
- `CHTA`
- 计数类指标如 `H#AM`、`T#AM`

这些指标更偏向株型、冠层和器官数量结构。

### 第五层：比例与品质组

典型指标：

- `HIAM`
- `HN%M`
- `VN%M`
- `HINM`
- `THAM`
- `GL%M`

这些指标是比值、浓度或品质结果，通常不适合和大尺度质量指标直接共权。

## 4.9 在实际参数率定里，怎样设计分组更稳妥

基于这个仓库的实现方式，我建议把分组设计原则理解成 5 条：

1. 同一生理过程的指标尽量同组，例如 `ADAP` 和 `MDAP`
2. 强相关且量纲相近的指标尽量同组，例如 `HWAM` 和 `CWAM`
3. 量纲差异特别大的指标不要混组，例如 `HWAM` 不应和 `HIAM` 同组
4. 比率类与总量类尽量分开，例如 `HIAM` 与 `HWAM`
5. 计数类与质量类尽量分开，例如 `H#AM` 与 `HWAM`

如果用一句话概括，就是：

不是按“文件里有多少指标”来分组，而是按“这些指标在生理意义上是否在约束同一个模型行为”来分组。

## 4.10 在实际参数率定里，怎样设计权重更稳妥

当前脚本给出的工程化思路是：

- 先按组
- 再以组内最大观测值倒数归一化

这是一种很实用的默认策略，但在真正率定时，建议再加上下面这些判断：

1. 如果某类指标实验误差大，不要只因为量纲小就给它过高权重
2. 如果某组里指标很多，要警惕“同一信息被重复计算”
3. 如果某组对研究目标最关键，可以在粗筛阶段提高其指数权重
4. 如果某组只是辅助约束，可以保留，但不必给过强影响
5. 如果某个指标数据缺测多、`-99` 多，不应放在核心组里

所以更完整的做法其实是两层组合：

- 第一层用“分组”处理量纲和平衡问题
- 第二层用“研究目标优先级”处理业务重要性问题

## 4.11 这个权重和前面 fitness 里的指数权重不是一回事

这点很容易混淆。

在项目里其实同时存在两层“权重”概念：

### 第一层：粗筛阶段的指数权重

来自：

- [DSSAT_PEST.r:L146-L148](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L146-L148)
- [DSSAT_PEST.r:L189-L191](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L189-L191)

这里用的是 `ParameterOutput.csv` 第 5 列的数值，进入 `OUT_fitness11 <- OUT_fitness1^OUTFile5[,4]`，更像“每个输出指标的重要性指数”。

### 第二层：PEST 观测权重

来自：

- [DSSAT_PEST.r:L429-L453](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L429-L453)

这里用的是 `nash.pst` 里的 observation weight 列，属于 PEST 控制文件的标准权重。

所以要特别注意：

- 第 5 列在粗筛阶段会参与 fitness 指数加权
- 第 6 列在 PEST 阶段会决定“按哪个组统一赋权”

这也意味着，真正好的指标设计通常是：

- 第 6 列先把指标分成合理的生理组
- 第 5 列再表达你希望粗筛阶段更偏向哪些观测目标

## 4.12 当前实现里的一个可疑点

现有代码里有一句：

- [DSSAT_PEST.r:L431-L431](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L431-L431)

它把 `observation data` 区块拼接了两遍：

`weight_Line <- c(obs_lines, obs_lines)`

从结果看，最终权重文件 [pst_weight.txt](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/pst_weight.txt#L1-L32) 里也确实出现了重复记录。

这不影响我们理解“分组 + 统一赋权”的总体思想，但它提示当前实现可能存在一个历史遗留问题：

- 分组与权重思想本身是清楚的
- 具体落盘实现仍有进一步清理空间

## 5. 结果文件怎么看

## 5.1 Cultivar Coefficients all.txt

[Cultivar Coefficients all.txt](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/PEST_Files/Cultivar%20Coefficients%20all.txt#L1-L11) 记录的是随机粗筛阶段所有候选参数及其 fitness。

可以把它理解成：

- 搜索过哪些初值
- 哪些初值比较好
- 原始 cultivar 值在这些随机样本里的相对表现如何

## 5.2 Cultivar Coefficients.txt

[Cultivar Coefficients.txt](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/Cultivar%20Coefficients.txt#L1-L7) 是最终结果汇总。

当前文件包含：

- 参数表头
- 若干候选估计结果
- `Best Cultivar Coefficients` 区块

这份文件是项目最终最值得保留的结果之一。

## 5.3 Evaluate.OUT

[Evaluate.OUT](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_Files/Evaluate.OUT#L1-L5) 是连接 DSSAT 与 PEST 的桥梁文件。

它的关键特征是：

- 一行头部列名
- 后续每一行同时包含模拟值与观测值
- 变量名通常成对出现，如 `ADAPS / ADAPM`

这里：

- `S` 一般代表 simulated
- `M` 一般代表 measured

也正因为如此，脚本才能在一个文件里同时抓取模拟值和观测值。

## 6. 为什么要“多初值 + 多次 PEST”

代码中这一逻辑位于 [DSSAT_PEST.r:L494-L570](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/DSSAT_PEST.r#L494-L570)。

它的意义是：

- PEST 可能对初始值敏感
- 不同初值可能收敛到不同局部最优
- 所以脚本把随机筛选后留下的多个较优候选都拿来做一次 PEST

这其实是一个非常实用的工程策略：先随机找好起点，再局部精调。

## 7. 当前结果可以怎么解读

从 [Cultivar Coefficients.txt](file:///d:/Wheat/Wheat/docs/reference/DSSAT-PEST/Cultivar%20Coefficients.txt#L1-L7) 看，当前样例已经得到一组玉米 `ZA0002` 的较优参数。

例如最佳样例显示：

- `P1 = 285.2`
- `P2 = .3000`
- `P5 = 795.1`
- `G2 = 756.4`
- `G3 = 5.948`
- `PHINT = 50.23`

并带有 fitness 值 `0.986069561073752`。

这说明当前样例流程至少已经完整跑通过一次。

## 8. 一句话结论

这个项目中的 PEST 不是附属功能，而是项目真正的“校准引擎”；R 代码的主要价值，就是把 DSSAT 变成一个可被 PEST 自动驱动的模型。

