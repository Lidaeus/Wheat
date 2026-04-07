# 2026-04-05 O2 phase3_formal 探索总结

## 1. 本轮目标

本轮工作的核心目标有四个：

1. 为 O2（PEST-IES）建立更稳定的 `phase3_formal` 正式预设。
2. 验证 `noptmax=5, num_reals=60, subset_size=16~24` 的敏感性。
3. 修复若干会污染优化结论的运行与评估问题。
4. 为后续 O2、O5、O2->O1、O5->O1 的继续探索保留一份可追溯的研究记录。

## 2. 最终结论

### 2.1 O2 正式预设

将 `phase3_formal` 的 O2 预设固定为：

- `ies_noptmax = 5`
- `ies_num_reals = 60`
- `ies_subset_size = 16`

原因：

- `subset_size=16, 20, 24` 三组在本轮试验中得到完全一致的最终结果。
- 在结果一致的前提下，`subset_size=16` 的计算成本最低。
- 因此 `5 / 60 / 16` 是当前最合适的 O2 `phase3_formal` 正式基线。

### 2.2 subset 敏感性结论

在保持以下条件不变时：

- `engine = o2`
- `budget = phase3_formal`
- `noptmax = 5`
- `num_reals = 60`

比较 `subset_size = 16, 20, 24`：

| crop | subset=16 | subset=20 | subset=24 | 结论 |
| --- | ---: | ---: | ---: | --- |
| wheat | 0.295629 | 0.295629 | 0.295629 | 完全一致 |
| maize | 1.065664 | 1.065664 | 1.065664 | 完全一致 |
| soybean | 0.237884 | 0.237884 | 0.237884 | 完全一致 |
| rice | 0.100538 | 0.100538 | 0.100538 | 完全一致 |
| cotton | 0.501479 | 0.501479 | 0.501479 | 完全一致 |

说明：

- 当前问题上，`subset_size` 在 `16~24` 区间内不是控制最终解质量的主因子。
- O2 在 `5 / 60 / 16` 下已经能够到达与更大 subset 相同的稳定解。
- 继续增大 subset 只会增加计算成本，不会带来更好的最终结果。

## 3. 本轮关键运行记录

### 3.1 主要批处理

执行过的关键矩阵命令如下：

```powershell
python .\autoresearch_sandbox\build_crop_engine_matrix.py --budgets quick,standard,phase3_formal --engines o2 --jobs 14 --force --pest-noptmax 5 --ies-num-reals 60 --ies-subset-size 20
```

```powershell
python .\autoresearch_sandbox\build_crop_engine_matrix.py --budgets phase3_formal --engines o2 --jobs 14 --force --pest-noptmax 5 --ies-num-reals 60 --ies-subset-size 16
```

```powershell
python .\autoresearch_sandbox\build_crop_engine_matrix.py --budgets phase3_formal --engines o2 --jobs 14 --force --pest-noptmax 5 --ies-num-reals 60 --ies-subset-size 24
```

### 3.2 并行执行结论

- `build_crop_engine_matrix.py` 的 14 进程并发链路已验证通过。
- `ThreadPoolExecutor` + 隔离工作区的方案可稳定运行多作物 O2 矩阵批处理。
- `cotton_phase3_formal_o2` 最终也能正确排队并执行，不存在永久漏跑现象。

## 4. 本轮关键修复

### 4.1 Rice canopy 目标异常修复

问题：

- rice O5 结果中出现 `TRAIN_OBJ_CANOPY_NRMSE=1000000`。
- 根因不是模型发散，而是某些观测文件中 `LAIX` 为 `-99`，但 phase3 目标组仍然把 canopy 目标纳入优化。

处理：

- 增加“该 metric 是否有有效观测”的判断。
- 构造 phase3 objective groups 时，只保留有真实观测值的指标。

影响：

- 避免把“缺失观测”误判成“巨大 canopy 误差”。
- 让 rice 的 O5 / phase3 结果恢复可解释性。

### 4.2 Soybean / Cotton LFMAX≤0 风险控制

问题：

- 大豆与棉花优化时，某些 cultivar 参数会逼近或越过 DSSAT 可接受下界，触发运行错误。

处理：

- 在 CUL 写回时先扫描 `MINIMA` / `MAXIMA` 行。
- 更新参数时把写入值夹在 DSSAT 合法区间内。

影响：

- 避免 `LFMAX`、`XFRT` 之类参数穿透到非法区间。
- 提高 O2 / O5 在豆类与棉花上的鲁棒性。

### 4.3 O2->O1 工作流重构

重构目标：

- 过去 O2 只拿单个 seed 继续做 O1 精修，容易把单点噪声当成真实优势。

新策略：

1. 从 O2 IES 结果中挑 3 个代表性 seed。
2. 每个代表性 seed 都走一遍 O1 标准精修。
3. 用 winner-take-all 选最终 refined winner。

影响：

- 降低 O2 单个 realization 偶然性的影响。
- 让 O2->O1 的比较更公平，也更适合与 O5->O1 做对照。

## 5. 对结果的解释

### 5.1 为什么 subset 变化没有影响最终解

这通常意味着：

- `num_reals=60` 已经足够支持稳定的 ensemble 更新。
- `noptmax=5` 已经给了 IES 足够的迭代深度。
- 当前作物问题在 `subset=16~24` 的范围内，对 lambda 选择的估计误差已经不再敏感。

也就是说，本轮结果反映的不是“subset 完全不重要”，而是：

- 在当前数据、边界、目标组和 ensemble 尺度下，`16` 已经足够大。
- 后续如果再探索 subset，除非降到很小或者换成完全不同的数据结构，否则大概率不会改变最终排名。

### 5.2 目前最难的作物

从 final score 看：

- rice 最好：`0.100538`
- soybean 次之：`0.237884`
- wheat 稳定：`0.295629`
- cotton 较难：`0.501479`
- maize 最难：`1.065664`

这说明后续若继续创新，优先级应放在：

1. maize
2. cotton

因为这两者继续加大 subset 并没有改善结果，后续更值得检查：

- 参数边界是否过紧
- 目标函数是否仍缺少关键观测
- 是否需要 O5 / MGDA 的多目标起点引导

## 6. 推荐的后续路线

### 6.1 O2 路线

- 把 `phase3_formal` 的 O2 正式基线固定为 `5 / 60 / 16`。
- 后续所有 O2 主表结果优先使用这一组设置。

### 6.2 O2->O1 路线

- 继续沿用“3 representative seeds -> O1 -> winner-take-all”。
- 特别关注 maize / cotton 是否能通过 refinement 拉回一部分误差。

### 6.3 O5 路线

- 在 rice canopy 缺失观测问题修复后，重新审视 O5 与 O2 的公平对比。
- 若 O5 在 maize / cotton 上优于 O2，应进一步放大 MGDA 的正式预算测试。

## 7. 本轮涉及的重要文件

- 预算预设与 phase3 objective 逻辑：`autoresearch_sandbox/eval.py`
- O2 矩阵批处理：`autoresearch_sandbox/build_crop_engine_matrix.py`
- O2->O1 / O5->O1 比较：`autoresearch_sandbox/compare_hybrid_refinements.py`
- DSSAT CUL 改写与参数约束：`mvp_pest_mgda/src/dssat_io.py`
- 结果表：`autoresearch_sandbox/crop_engine_matrix.tsv`
- 对比表：`autoresearch_sandbox/hybrid_refinement_comparison.tsv`

## 8. 可直接复用的建议

如果未来重新开始 O2 正式跑表，建议优先使用：

```powershell
python .\autoresearch_sandbox\build_crop_engine_matrix.py --budgets phase3_formal --engines o2 --jobs 14 --force --pest-noptmax 5 --ies-num-reals 60 --ies-subset-size 16
```

如果未来重新开始 O2->O1 对比，建议保留：

- `o2_representatives = 3`
- `o2_representative_pool = 12`
- `o2_pest_noptmax = 5`
- `o2_ies_num_reals = 60`
- `o2_ies_subset_size = 16`

## 9. 一句话总结

本轮探索的核心产出是：

- 修复了会误导优化结论的评估与运行问题。
- 验证了 14 进程并行 O2 批处理链路。
- 用实证结果证明 `phase3_formal` 下 O2 的正式推荐配置应为 `5 / 60 / 16`。
