# 论文初稿大纲（当前统一版）

## 1. 当前论文定位

当前论文最适合被写成一篇多作物方法学评估论文，而不是单一优化器竞赛报告。

全文主线固定为：

**在五作物 DSSAT 遗传参数率定中，将协议拆解为 `W × O × S × G` 四个设计轴，并进一步考察：`S × G` 是否比单独更换 `O` 更能改善验证表现与参数合理性，以及 `W × O` 交互是否会改变对优化器优劣的判断。**

其中：

- `W × G` 被解释为损失构造层
- `S × O` 被解释为求解执行层
- `W × G × S × O` 构成完整校准协议

这意味着文章的重点是协议结构，而不是某一个算法是否夺冠。

## 2. 当前已经锁定的前提

目前已经可以视为定稿级前提的内容包括：

- 主矩阵仍写作 `W × O × S × G`
- 机制解释采用 `W × G` 与 `S × O` 的层级口径
- `B0` 固定为外部基线
- 五作物边界固定为 Wheat、Maize、Soybean、Rice、Cotton
- `G3` 分组模板与缺失组裁剪规则已进入主稿
- `W8` 固定为文献-工程双基线
- `S1 / S2 / S3` 的角色边界已固定，且 `S3` 依赖 `S2`
- `NSGA-II` 与 `MGDA` 已统一归入 `O` 层
- 真多目标不再作为主矩阵中的 `W9` 活跃编号，而作为主矩阵之外的向量目标扩展

## 3. 术语与编号治理

当前论文统一采用以下治理规则：

- 主文中保留既有 `W/O/S/G` 编号，以降低与历史草稿、实验表和脚本命名的脱节
- 不再把 `W` 单独叫作“损失构造”，而改为把 `W × G` 共同称为损失构造层
- `W9` 仅作为历史说明保留，不再作为主矩阵中的活跃 `W` 轴编号
- `O4 = NSGA-II`，定位为向量目标下的前沿搜索优化器
- `O5 = MGDA`，定位为向量目标下的折中解搜索优化器

当前论文中建议保留的活跃编号为：

- `W`：`W0, W4, W6, W8` 为主矩阵；`W1, W7` 为扩展层
- `O`：`O1, O2` 为主矩阵；`O3` 为扩展层；`O4/O5` 为探索层
- `S`：`S1, S2` 为主矩阵；`S3` 为扩展层
- `G`：`G1, G3`

## 4. 题目方向

### 4.1 推荐主标题

**A Multi-Crop Protocol Framework for DSSAT Genetic Parameter Calibration: Loss Construction, Sequential Solving, and Optimizer Interaction**

### 4.2 偏工程实现标题

**From DSSAT-PEST Practice to a Unified Multi-Crop Calibration Protocol: Grouping, Weighting, Sequencing, and Solver Behavior**

### 4.3 偏研究问题标题

**Beyond Optimizer Comparison in DSSAT Calibration: A Multi-Crop Study of Loss Construction, Sequential Protocols, and `W × O` Interaction**

当前最推荐使用 **4.1**，因为它既保留了协议框架，又把 `W × O` 交互和 `S × G` 主线都留在标题逻辑里。

## 5. 摘要组织模板

摘要建议写成五句结构：

1. **背景句**
   - DSSAT 遗传参数率定不仅受优化器影响，还受损失构造与率定协议共同制约
2. **问题句**
   - 既有研究常把权重、分组、顺序和优化器混合改变，导致结果难解释、难迁移
3. **方法句**
   - 本研究在五作物 `DSSAT-PEST` 框架下构建 `W × O × S × G` 主矩阵，并将其进一步解释为 `W × G` 损失构造层与 `S × O` 求解执行层
4. **结果句**
   - 结果部分后续填入：`G3` 是否提升稳定性、`S2` 是否优于 `S1`、`W8` 是否能作为稳健基线、`W × O` 是否改变优化器结论
5. **贡献句**
   - 论文输出的是一套可复用的多作物率定协议，而不是一次性经验调参结果

## 6. 论文结构建议

### 6.1 引言

引言建议按四段展开：

1. **现实问题**
   - 多量纲观测混合
   - 终产量变量的数值支配
   - 参数代偿与 equifinality
2. **文献不足**
   - 过度聚焦优化器比较
   - 很少将分组协议与阶段式率定纳入统一框架
   - 很少把负优化与参数合理性写成一等结果
3. **本文问题**
   - `S × G` 是否比单独更换 `O` 更重要
   - `W × O` 交互是否真实存在
   - 协议效应是否可跨五作物部分迁移
4. **本文贡献**
   - 将率定问题组织为 `W × O × S × G`
   - 将 `W × G` 明确为损失构造层
   - 将 `S × O` 明确为求解执行层
   - 重新定位 `W8`、`NSGA-II` 与 `MGDA` 的角色边界

### 6.2 材料与方法

材料与方法建议按“从边界到执行”的顺序写：

#### 6.2.1 Study System

- DSSAT v4.8+
- 五作物
- `DSSAT-PEST` 作为 cultivar-level calibration workflow

#### 6.2.2 Calibration Problem Definition

- 参数空间
- 观测空间
- `B0` 外部基线
- 负优化定义

#### 6.2.3 Terminology and Notation Governance

- `W × O × S × G` 主矩阵
- `W × G` 损失构造层
- `S × O` 求解执行层
- `W9` 停用与多目标扩展的独立定位

#### 6.2.4 Four-Dimensional Experimental Matrix

- `W`：权重与尺度处理方案
- `G`：观测分组策略
- `S`：校准顺序
- `O`：优化器类别
- 说明为何机制解释采用 `W × G` 与 `S × O`

#### 6.2.5 Observation Grouping and Cross-Crop Template

- 五作物 `G3` 字典
- 统一组号模板
- 缺失组裁剪规则

#### 6.2.6 Weighting Design

- `W0 / W4 / W6 / W8` 的主矩阵角色
- `W1 / W7` 的扩展层角色
- `W8` 的基线定位

#### 6.2.7 Sequential Calibration Protocol

- `S1`
- `S2`
- `S3`
- `S3` 对 `S2` 的依赖

#### 6.2.8 Phase-Wise Execution Strategy

- Phase 0：可执行性与流程完整性
- Phase 1：核心筛选
- Phase 1.5：预算敏感性
- Phase 1.6：初始化敏感性与混合搜索
- 扩展层：`W1 / W7 / S3`
- 探索层：向量目标扩展与 `O4/O5`

#### 6.2.9 Evaluation Criteria

- Validation error
- Negative optimization rate
- Parameter plausibility
- Error balance
- Engineering cost

### 6.3 结果

结果章建议按“问题 → 证据”顺序组织，而不按作物逐个罗列：

#### 6.3.1 Phase 0 Results: Executability and Pipeline Integrity

- 五作物是否都能跑通 `B0`
- `W8 × O1 × S1 × G1` 是否形成最小闭环
- 哪些作物需要模板或观测裁剪

#### 6.3.2 Phase 1 Results: Core Screening

- `G3` 相对 `G1` 是否提升稳定性
- `S2` 相对 `S1` 是否改善参数合理性与泛化
- `W8` 是否能作为稳健基线
- `O1` 与 `O2` 的优劣是否依赖协议环境

#### 6.3.3 Controlled `W × O` Interaction

- 在固定 `G3 × S2` 环境下，`W0 / W4 / W8` 是否改变 `O1` 与 `O2` 的相对排序
- 是否存在明显的 rank reversal 或差距缩小

#### 6.3.4 Cross-Crop Consistency and Exceptions

- 哪些模式跨作物成立
- 哪些是作物特异例外
- 例外是否与观测丰富度或组结构有关

#### 6.3.5 Parameter Plausibility and Negative Optimization

- 是否出现整体劣于 `B0`
- 是否存在明显参数漂移或边界吸附

#### 6.3.6 Scale Sensitivity of Selected Protocols

- 预算扩容是否改变代表性协议的表现
- 哪些协议适合作为低预算默认方案

#### 6.3.7 Initialization Sensitivity and Hybrid Search Gain

- 哪些协议对初值敏感
- 多启动与全局-局部混合是否提供可复现增益

### 6.4 讨论

讨论建议围绕六个问题展开：

1. **为什么必须把 `W × G` 视为损失构造层**
   - `W` 决定缩放与平衡
   - `G` 决定聚合边界
2. **为什么不能只比优化器**
   - `O` 的表现依赖损失构造与顺序结构
3. **为什么 `S × G` 仍然是主主线**
   - 它们更直接影响参数可辨识性与代偿路径
4. **为什么 `W × O` 必须被保留为主问题之一**
   - 优化器优劣并非脱离权重环境而成立
5. **为什么预算与初始化必须分层**
   - 它们影响搜索暴露度，但不应重写主协议边界
6. **为什么多目标扩展不应进入主矩阵**
   - 它改变的是目标对象，而不是标量权重

### 6.5 结论

结论只回答三件事：

1. 是否建立了比“只换优化器”更有效的 DSSAT 率定研究框架
2. 哪类协议在五作物中表现最稳健
3. 哪些方法应留在扩展层或探索层，而不是写成主结论

## 7. 图表清单建议

### 7.1 必要图件

- Figure 1：`W × G` 与 `S × O` 的层级框架图
- Figure 2：五作物 `G3` 统一组号模板图
- Figure 3：`S1 / S2 / S3` 协议流程图
- Figure 4：Phase 0 → Phase 1.6 执行路线图
- Figure 5：Phase 1 核心筛选结果图
- Figure 6：`W × O` 交互对比图
- Figure 7：预算敏感性图
- Figure 8：初始化敏感性或混合搜索收益图

### 7.2 必要表格

- Table 1：五作物与观测空间概览
- Table 2：术语与编号统一表
- Table 3：主矩阵活跃组合与兼容性约束
- Table 4：五作物 `S2` 阶段映射表
- Table 5：Phase 0 执行记录表
- Table 6：Phase 1 核心结果汇总表
- Table 7：受控 `W × O` 交互结果表
- Table 8：预算与初始化稳健性结果表

## 8. 写作推进建议

### 8.1 立即可写部分

- 引言完整初稿
- 材料与方法主体
- Figure 1–4 的结构草图
- Table 1–5 的空表头与说明文字

### 8.2 需要等待 Phase 0 后补写的部分

- 流程可执行性结果
- 作物间模板或观测修复差异
- 进入主比较前的裁剪说明

### 8.3 需要等待 Phase 1 后补写的部分

- `G3` 是否优于 `G1`
- `S2` 是否优于 `S1`
- `W8` 是否站得住
- `O1/O2` 的受控比较
- `W × O` 是否存在显著交互

### 8.4 需要等待稳健性分析后补写的部分

- 预算扩张是否改变方法结论
- 初值与混合搜索是否只是增强协议

### 8.5 最后收口部分

- 跨作物一致性与例外
- 推荐协议组合
- 摘要、标题与结论最终表述

## 9. 当前版本的三个总控文件

当前建议以三个文件共同控制写作：

1. [PaperDraft.md](file:///d:/Research_Artifacts/Drafts/PaperDraft.md)
2. [02_Terminology_and_Notation.md](file:///d:/Research_Artifacts/Drafts/02_Terminology_and_Notation.md)
3. [03_Experiment_Design.md](file:///d:/Research_Artifacts/Drafts/03_Experiment_Design.md)

其中：

- `PaperDraft.md` 负责论文正文
- `02_Terminology_and_Notation.md` 负责全文术语、编号与多目标定位
- `03_Experiment_Design.md` 负责实验设计、阶段安排与证据路径

## 10. 当前版本的写作目标

这份大纲的目标不是一次性定稿，而是作为后续写作与实验填充的总控文件：

1. 先写出术语一致、结构稳定的方法学主稿
2. 再按 Phase 0、Phase 1 与稳健性层逐块填入结果
3. 最后根据真实结果收束题目、摘要与结论
