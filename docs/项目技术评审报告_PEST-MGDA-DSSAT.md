# 项目技术评审报告（批判性 Review）

## 1. 总览与结论
- 当前代码已跑通核心闭环：DSSAT → PEST++（JCO/REI）→ MGDA → 三方案对照评估（baseline/pest/mgda）。
- 批量与分步迭代机制初具形态，但仍存在工程一致性、配置化程度、评估口径与鲁棒性方面的系统性缺陷。
- 结论：在现状上可继续推进，但必须优先修复以下关键问题以避免误导性的结论与难以复盘的运行。

## 2. 关键问题与批评
- 评估口径与分组不完善
  - 问题：compare_three.py 的 _calc_summary 仅按 scenario 聚合；缺少按“品种/作物/处理(TRNO)”的过滤聚合；文档建议的 NRMSE 与 d-index 虽已在列名中体现，但多作物适配时口径不稳定。
  - 风险：跨品种/作物的指标被混合，导致结论失真；训练与验证划分虽有 split_by_trt，但对多作物的统一评估不完备。
  - 解决：在 compare_three.py 中增加“按 cultivar/species 过滤”的汇总管道；对 NRMSE_mean/NRMSE_range 与 d-index 口径进行单元测试固化，确保不同数据覆盖下稳定。
- 批量运行状态机与错误处理不一致
  - 问题：run_mvp.ps1 的批量模式中 meta.json 多处显示 run_status=success 但 stage 停在 run_pestpp=start；另有一例明确失败（exit -1）被正确写入，但成功口径不统一。
  - 风险：上层流水线难以判断批量是否真正完成，导致后续归档/汇总缺失。
  - 解决：统一 Set-IterStage 与 meta.json 的 run_end/run_status 写入逻辑；任何 stage 未完成时整个 run 标记为 failed，并写入 error_stage/error_log 指针；等待 JCO/REI 的超时与失败路径需在日志中追加详述（已有 Wait-ForAnyFile，需加强）。
- PEST-only 与 MGDA 的角色未完全解耦
  - 问题：多处运行使用 noptmax=5（估计模式），与文档推荐的 noptmax=-1（敏感性模式）混用；不同作物的配置文件未统一指定此策略。
  - 风险：评估中 mgda 与 pest 可能都在做估计更新，无法清晰对比“单目标 vs 多目标”的改进。
  - 解决：在 config 层明确策略：pest-only 场景使用 noptmax>0；mgda 场景的 J/残差生成使用 noptmax=-1；run_mvp.ps1 根据场景决定 noptmax 列表，防止混淆。
- 多作物适配与参数集管理不足
  - 问题：不同作物的 CUL 字段差异较大（如向日葵、甘蔗），compare_params.csv 中字段名不一致；run_model.py 的 CUL 重写函数与字段映射未抽象为作物家族层级。
  - 风险：跨作物输出对比时参数列混乱，评估不可比；容易出现“Unknown CUL columns”的错误。
  - 解决：建立“作物模型家族”映射层（CERES-Wheat/Barley/Maize…；CROPGRO/糖作物等），为每家族定义参数集与字段映射；compare_params 生成时按家族输出统一列集与空值占位。
- 观测规范与误差模型未工程化固化
  - 问题：观测分组与权重策略在代码与配置之间未完全一致；LAI/LAID/LWAD/SWAD 的时间序列对齐逻辑存在耦合与容错不足。
  - 风险：MGDA 的梯度构造不稳定；不同作物/试验数据质量差异导致评估波动大。
  - 解决：将观测定义（来源文件、字段名、分组、σ）完整配置化；在 compare_three 与 run_model 的解析层加入字段存在性检查与清晰失败信息；默认启用 σ 预白化与 L2 归一化，必要时对高频序列折减权重。
- 归档与复盘工件标准尚未完成
  - 问题：per_project_summaries 的生成在部分批量目录缺失；pareto_archive 与 run_manifest 尚未统一输出。
  - 风险：结果难以跨批量汇总；审核与回归测试成本高。
  - 解决：批量结束后统一执行“索引生成 + 归档复制”，产出 cases_summary.csv 与 overall_summary.csv；每次运行写全 ledger：params、pest、mgda、eval、meta。

## 3. 证据与代码参考
- 批量运行状态机与日志
  - 参考：run_mvp.ps1 的 RunMain 段（[run_mvp.ps1:L612-L706](file:///d:/Wheat/Wheat/mvp_pest_mgda/scripts/run_mvp.ps1#L612-L706)）
  - 失败样例：_batch/20260207_044528（pestpp-glm.exe failed），成功样例的 meta.json 多显示 run_pestpp=start（[meta.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/runs/_batch/20260207_052000_multi/001_project/meta.json)）
- 对比评估实现
  - 参考：compare_three.py 的 _calc_summary 与汇总导出（[compare_three.py:L60-L252](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/compare_three.py#L60-L252)，[compare_three.py:L741-L928](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/compare_three.py#L741-L928)）
- DSSAT 运行与观测解析
  - 参考：run_model.py 的 FileX 渲染与 Evaluate/PlantGro 解析（[run_model.py:L637-L668](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py#L637-L668)）
- 文档要求与现状差异
  - 参考：项目开发文档第 10 节的“极致方案”与调参优化方案第 5 节风险点（[项目开发文档_PEST-MGDA-DSSAT.md](file:///c:/DSSAT48/Wheat/docs/项目开发文档_PEST-MGDA-DSSAT.md)，[PEST-MGDA 调参优化方案.md](file:///c:/DSSAT48/Wheat/docs/PEST-MGDA%20%E8%B0%83%E5%8F%82%E4%BC%98%E5%8C%96%E6%96%B9%E6%A1%88.md)）

## 4. 建议的修复与改进方案（分优先级）
- 高优先级（立即执行）
  - 统一 noptmax 策略：mgda 迭代的 PEST++ 必须用 noptmax=-1，仅生成 J/残差；pest-only 用 noptmax>0 做估计。配置与脚本一致。
  - 强化状态机与 meta.json：每轮 stage 完成/失败必须一致写回；批量 run_status=success 仅在所有 iter 阶段完成后写入。
  - 增加“按物种/品种”的评估汇总：在 compare_three.py 输出 compare_summary_by_species_cultivar.csv；run_mvp.ps1 批量末尾强制生成索引与合并。
- 中优先级（一周内）
  - 作物家族参数映射层：抽象 CUL 字段映射与参数集，compare_params 使用统一列集；遇到未知列写占位与告警。
  - 观测配置化与 σ 预白化：把权重与 σ 的策略写入配置，并在 MGDA 梯度构造端固化；加单元测试验证指标口径。
  - 归档标准：加入 pareto_archive 与 run_manifest；批量生成 cases_summary.csv 与 overall_summary.csv。
- 低优先级（迭代推进）
  - 两阶段率定与步长限幅：先稳住物候，再进入 MGDA；MGDA 默认开启回溯 line search 与限幅，防止参数跳变。
  - 多起点策略：实现 LHS/IES 多起点，维护非支配集（ND set）与汇总统计（胜率、中位数、IQR）。

## 5. 验收与质量保障
- 单元测试：定宽写入器、解析器、指标计算（RMSE/R²/NRMSE/d-index）与分组汇总。
- 集成测试：最小 case（金标准）闭环跑通，检查工件完整性与 phi_w 复现。
- 运行时自检：文件存在性、列名匹配、数值有限性、J/残差等待超时告警。

## 6. 结语
- 项目技术路线正确，已有闭环基础。若按本评审的改进方案推进，可显著提升跨作物的可比性、运行的可复盘性与结果的鲁棒性，从而满足“多物种/多品种/多处理”的研究与生产应用需求。

## 7. 准确性与正当性核查（证据复盘）
- 评估口径问题
  - compare_three.py 的汇总仅以 scenario 为键，未按 cultivar/species 过滤；代码显示按 rows 全量聚合（见 [compare_three.py:L741-L835](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/compare_three.py#L741-L835)），与文档“分品种评估”不一致。
  - 向日葵与甘蔗的 compare_params 字段差异明显（示例：向日葵为 ppsen/slavr/xfrt…，甘蔗为 maxparce/stkpfmax/suca…），当前 compare_params 无统一列集，跨作物难以对比（见 [sunflower compare_params.csv](file:///d:/Wheat/Wheat/mvp_pest_mgda/runs/_batch/20260207_052000_multi/003_project_sunflower_ucco9301/iter_000/compare_params.csv)、[sugarcane compare_params.csv](file:///d:/Wheat/Wheat/mvp_pest_mgda/runs/_batch/20260207_053500_multi2/002_project_sugarcane_sato8902/iter_000/compare_params.csv)）。
- 批量运行状态机与 meta 口径
  - 多个批量目录的 meta.json 显示 run_status=success 而 stage 停在 run_pestpp=start（例如 [001_project meta.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/runs/_batch/20260207_052000_multi/001_project/meta.json)），与成功定义不一致；另有失败样例正确记录（exit -1）。
- noptmax 策略混用
  - 观察到 nopt_list 既有 5 也有 -1 的记录，且跨作物目录混用，未与“pest-only vs mgda 生成 J/残差”清晰绑定，影响对比的正当性。
- 观测与误差模型
  - run_model.py 的时间序列采集依赖 wht_dates 配置与 PlantGro.OUT 字段存在性，容错有限；未见统一的 σ 预白化与有效样本量折减在 MGDA 端的固化实现，存在数值不公平风险。
- 归档缺失
  - 部分批量没有统一 per_project_summaries 索引输出（人工脚本可补，但应由批量流程保证），降低复盘效率与审核可信度。

## 8. 解决方案设计细化（可执行方案）
- compare_three 分品种/作物汇总设计
  - 增加 species/cultivar 解析：读取项目快照 config 的 dssat_case_dir 与 filex；从 FileX 的 *CULTIVARS 段解析 cultivar code。
  - 汇总管道：在现有 summary_rows 与 param_rows 外增设 by_species_cultivar 版本，键包含 species/cultivar/project_tag；输出 compare_summary_by_species_cultivar.csv 与 compare_params_by_species_cultivar.csv。
  - 指标口径：统一计算 RMSE、R²、NRMSE_mean/NRMSE_range、d-index；对空/缺失进行显式 NaN 并在导出前校验列齐全；为口径写最小单元测试。
- run_mvp.ps1 状态机与 meta 统一
  - 规则：仅当 iter 的五个阶段（render_inputs/run_pestpp/mgda_update/evaluate/archive）全部标记为 done 时，写 run_end 与 run_status=success；否则标记 failed 并写 error_stage、指向日志（glm_console_est.log/mgda_console.log/compare_console.log）。
  - PEST++ 运行：显式解析 pestpp-glm 路径；运行后检查 ksas_mvp.par/jco/rei 文件存在；将 stderr 追加到 glm_console_est.log；出现 non-zero exit 或缺文件直接 fail-fast。
  - 批量索引：批量结束后扫描 compare_summary.csv/compare_params.csv，复制到 per_project_summaries 并写 index.csv 与 *_by_species_cultivar.csv。
- noptmax 策略配置化
  - 在每个 project.json 增加 pest_mode 字段（estimation 或 sensitivity）；estimation → noptmax>0；sensitivity → noptmax=-1。
  - run_mvp.ps1 根据 pest_mode 构造 nopt_list；mgda 流程使用 sensitivity 生成 J/残差；pest-only 流程使用 estimation。
- 作物家族参数映射层
  - 设计 crop_family 映射：为 CERES、CROPGRO、糖作物等定义“统一参数键集合”与“CUL 字段映射”；compare_params 导出使用统一列集，并为缺失字段写空值。
  - CUL 重写器：在 run_model/build_pest_setup 中以家族映射写字段切片，确保定宽与 round-trip 校验。
- 观测与误差模型工程化
  - 配置扩展：为每观测组写 σ/单位/量纲；MGDA 端按组执行 σ 预白化与 L2 归一化；时间序列目标提供有效样本量折减策略（权重折减或代表日期抽样）。
  - 失败可诊断：解析缺列/缺文件时，明确报错包含文件名、字段、TRT/DATE，停止迭代并写失败码。
- 归档与复盘标准
  - Run Ledger：在 iter_xxx 下标准化 pest/mgda/eval/meta 结构；生成 pareto_archive 与 run_manifest.csv。
  - 批量汇总：产出 cases_summary.csv（每 case 的 valid 指标）与 overall_summary.csv（跨 case 的中位数/IQR/胜率），方便复盘与结论发布。

## 9. 实施步骤与里程碑（建议）
- 里程碑 M1：状态机与 meta 修复、noptmax 策略统一、分品种汇总落地。
- 里程碑 M2：作物家族映射与 compare_params 统一列集、观测配置化与 σ 预白化。
- 里程碑 M3：归档标准（pareto_archive、cases/overall 汇总）、多起点与 ND 集统计。


