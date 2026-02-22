# 多作物 PEST+MGDA 验证实验方案

## 1. 目标

在多种作物类型上对比 baseline、PEST 与 PEST+MGDA 的率定效果，验证 PEST+MGDA 是否在多数作物上稳定优于或不弱于 PEST。

## 2. 代表作物与文件清单

以下清单来自 C:\DSSAT48 目录中已存在的 FileA/FileT/FileX 与 CUL 文件，覆盖谷物、叶菜、块根、块茎与豆科：

| 作物类型 | 作物 | FileA | FileT | FileX | CUL |
| --- | --- | --- | --- | --- | --- |
| 谷物 | 小麦 | C:\DSSAT48\Wheat\SWSW7501.WHA | C:\DSSAT48\Wheat\SWSW7501.WHT | C:\DSSAT48\Wheat\SWSW7501.WHX | C:\DSSAT48\Genotype\WHCER048.CUL |
| 谷物 | 玉米 | C:\DSSAT48\Maize\BRPI0202.MZA | C:\DSSAT48\Maize\BRPI0202.MZT | C:\DSSAT48\Maize\BRPI0202.MZX | C:\DSSAT48\Genotype\MZCER048.CUL |
| 谷物 | 水稻 | C:\DSSAT48\Rice\DTSP8502.RIA | C:\DSSAT48\Rice\DTSP8502.RIT | C:\DSSAT48\Rice\DTSP8502.RIX | C:\DSSAT48\Genotype\RICER048.CUL |
| 叶菜 | 白菜 | C:\DSSAT48\Cabbage\IBPF8601.CBA | C:\DSSAT48\Cabbage\IBPF8601.CBT | C:\DSSAT48\Cabbage\IBPF8601.CBX | C:\DSSAT48\Genotype\CBGRO048.CUL |
| 块根 | 木薯 | C:\DSSAT48\Cassava\CCPA7801.CSA | C:\DSSAT48\Cassava\CCPA7801.CST | C:\DSSAT48\Cassava\CCPA7801.CSX | C:\DSSAT48\Genotype\CSCAS048.CUL |
| 块茎 | 土豆 | C:\DSSAT48\Potato\AUCB7001.PTA | C:\DSSAT48\Potato\AUCB7001.PTT | C:\DSSAT48\Potato\AUCB7001.PTX | C:\DSSAT48\Genotype\PTSUB048.CUL |
| 豆科 | 大豆 | C:\DSSAT48\Soybean\CLMO8501.SBA | C:\DSSAT48\Soybean\CLMO8501.SBT | C:\DSSAT48\Soybean\CLMO8501.SBX | C:\DSSAT48\Genotype\SBGRO048.CUL |

说明：
- 甜菜目录下缺少对应的 FileA（仅见 BST/BSX），暂不纳入本轮代表作物；如需加入，可补齐具有 A/T/X 的甜菜试验后再纳入。

## 3. 观测指标与目标输出

每个作物优先使用以下观测组作为率定目标：

- 产量：Evaluate.OUT 或 Summary.OUT 中的产量指标
- LAI：Evaluate.OUT 或 PlantGro.OUT 中的 LAIX/LAID
- 物候：Summary.OUT 中的开花/成熟日期（如有）
- 生物量：PlantGro.OUT 中的 SWAD、LWAD（如有）

若某作物缺失某类观测，允许在该作物的目标中去除该观测组。

## 4. 率定参数选择

每个作物选取 CUL 中 4-8 个核心遗传参数作为率定对象，优先选择对产量、物候、LAI 敏感的参数。基本策略：

- 谷物：P1、P2、P5、G1、G2、G3 等
- 叶菜：叶面积扩展、叶片寿命、光合效率相关参数
- 块根/块茎：贮藏器官分配与灌浆速率相关参数
- 豆科：开花/结荚相关参数与产量构成参数

参数上限与下限以 CUL 文件列宽为约束，确保数值格式合法。

## 5. 实验设计与对比策略

### 5.1 处理数量控制

为降低计算量，每个作物从 FileX 中选择 6-12 个 TRT：

- 若 TRTs 数量较多，随机抽样或按灌溉/施肥强度分层抽样
- 训练/验证比例建议 80/20

### 5.2 对比方案

对每个作物分别运行三种方案：

1. baseline：初始参数直接模拟
2. PEST：NOPTMAX>=1 进行传统 GLM 率定
3. PEST+MGDA：按多目标 MGDA 计算更新方向

NOPTMAX 建议取值：
- 仅生成敏感度/残差供 MGDA 使用：NOPTMAX=-1
- 快速检查或单步更新：NOPTMAX=1
- 一般率定：NOPTMAX=3-5
- 参数数量较多或收敛较慢：NOPTMAX=5-10，建议结合收敛阈值与最大运行时间限制

### 5.3 结果输出

每作物输出以下结果：

- compare_summary.csv
- compare_by_trt.csv
- compare_params.csv

并按作物类型汇总形成跨作物对比表。

## 6. 运行流程建议

1. 为每个作物建立独立 project.json，配置 FileA/T/X、CUL 与目标变量
2. 运行 baseline、PEST、PEST+MGDA
3. 生成 compare_* 输出并归档
4. 汇总跨作物的 RMSE、R2、phi、phi_w

## 7. 评价判据

PEST+MGDA 若满足以下条件即可判定更优：

- 在 70% 以上作物上，phi 或 RMSE 优于 PEST
- 在剩余作物上不显著劣化或差异极小
- 训练与验证结果一致性更好或不差于 PEST

## 8. 通用筛选脚本逻辑（建议）

脚本目标：自动从 C:\DSSAT48 扫描作物目录，筛选含 A/T/X 的试验并生成清单。

逻辑要点：

- 枚举一级作物目录
- 在目录内匹配同名前缀的 *.A/*.T/*.X 文件组
- 对每组 A/T/X 生成候选记录
- 从 C:\DSSAT48\Genotype 中按作物类型匹配 CUL
- 导出 CSV 清单并按作物类型分组抽样

## 9. 风险与缺失处理

- 缺少 FileA 或 FileT 的作物不纳入本轮评估
- 缺少 WTH 文件时，剔除对应 TRT 或作物
- 对多观测组权重不均衡的作物，采用标准化残差或加权策略

## 10. 开发任务规划与执行

### 10.1 已开始执行

- 已实现多作物 A/T/X 扫描与清单生成工具（可在 dssat_io.py 中直接运行）

### 10.2 接下来的开发任务

- 生成跨作物试验清单并自动抽样 TRT
- 为每作物生成最小可运行的 project.json 模板
- 批量运行 baseline/PEST/PEST+MGDA 并产出 compare_* 结果
- 汇总跨作物对比表并输出整体结论

### 10.3 工具用法

从 C:\DSSAT48 扫描并生成 A/T/X 与 CUL 清单：

python c:\DSSAT48\Wheat\mvp_pest_mgda\src\dssat_io.py c:\DSSAT48 c:\DSSAT48\Wheat\mvp_pest_mgda\runs\_tmp_wht\dssat_trials.csv
