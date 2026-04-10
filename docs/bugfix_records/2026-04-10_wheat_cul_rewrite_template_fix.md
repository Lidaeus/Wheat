# 2026-04-10 Wheat：CUL 参数改写失败（malformed cultivar 行）修复复盘

## 背景与目标

目标是让自动率定流程在 Wheat 上稳定运行，并且能够“按 DSSAT 文件标准”正确改写 `.CUL` 中的 cultivar 参数（固定宽度/固定小数位/不产生粘连 token），避免 DSSAT 运行期因为格式错误导致参数未生效或模型异常。

本次复盘聚焦于以下报错链路：

- `rewrite_cul_values()` 抛错：`CUL rewrite failed to apply any updates ... Requested=['G1','G2','G3','P1D','P1V','P5','PHINT']`
- 导致 Phase1 job 直接失败：`score=NA`、`Summary TSV is empty`

## 症状与直接证据

### 1) Phase1 运行失败

复现命令（示例）：

```powershell
& $py $runner --batch BatchA --budget quick --workers 1 --repetitions 1 --crops Wheat --tag wheat_debug_weather_ok
```

表现为多个组合直接失败，堆栈定位到：

- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py) `_rewrite_cul_params`
- [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py) `rewrite_cul_values`

### 2) 运行时 WHCER048.CUL 中目标 cultivar 行已“损坏”

在 `.dssat_rt/.../Genotype/WHCER048.CUL` 内可见 `IB1500` 行格式异常（字段粘连、缺失字段、空洞占位等），例如：

- `IB1500 ... CAWH0117.080 9.330 3.12  331.4 12.87 62.22        2.215`

参考示例文件：  
[WHCER048.CUL](file:///d:/Wheat/Wheat/.dssat_rt/36873e2a62e4/Genotype/WHCER048.CUL#L21-L33)

该行对照 header：

- `@VAR# ... ECO#   P1V   P1D    P5    G1    G2    G3 PHINT`

明显不满足应有的 7 个数值字段（P1V/P1D/P5/G1/G2/G3/PHINT）与空格分隔规则。

## 根因分析

### 根因 A：`rewrite_cul_values()` 对“非标准行”不鲁棒

原实现存在关键假设：

- 若要应用 `P1V/P1D/P5/G1/G2/G3/PHINT` 的固定宽度数值替换，目标行本身需要能被解析出完整的 numeric block（或至少能通过 header spans / token spans 推断出列位置）。

但对于 Wheat 的 `IB1500` 这类“已损坏行”，既无法从 token 维度得到完整列，也无法从 fixed block scan 得到合法起始位置，结果是：

- `found_cultivar_row=True`
- 但 `applied_keys` 始终为空
- 最终抛错 `CUL rewrite failed to apply any updates`

### 根因 B：上游曾发生过 cultivar 行尾部 token 粘连，触发 DSSAT 转换警告

在排查过程里出现过 DSSAT warning：

- `Trying to convert: 80.05128.0`（PHINT 与其它数值粘连）

这类粘连一旦进入 runtime `.CUL`，就会进一步破坏 `rewrite_cul_values()` 的解析前提。

## 解决方案设计

核心思路：将 “改写逻辑” 从“依赖目标行自身的可解析性”转为“依赖同文件内的模板行（格式正确行）”，从而对 malformed 行具备自愈能力。

### 方案 1：模板行推断 numeric block 起始位置（Template Numeric Start）

在同一个 `.CUL` 文件里，通常存在格式完好的行，例如：

- `DFAULT`, `999991 MINIMA`, `999992 MAXIMA` 等

这些行具备完整的 numeric block，可通过 fixed-width scan 推断 numeric block 起始位置。得到 `template_numeric_start` 后：

- 对目标 cultivar 行：
  - 使用 `template_numeric_start` 作为 numeric 区域起点
  - 将 7 个参数按固定小数位格式化成 token（例如 P1V 3 位小数、P1D 2 位小数等）
  - 将目标行重写为：`<prefix> <token1> <token2> ... <token7>`
  - 使其满足 DSSAT 的“可读 token”规范，避免 `80.05128.0` 类粘连再次出现

实现位置：

- [rewrite_cul_values](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)

### 方案 2：运行时 `.CUL` 额外做一次“尾部粘连清洗”

为了避免历史 malformed 进一步污染运行，运行时在 `_rewrite_cul_params()` 后追加轻量清洗：

- 如果行尾出现 `(\d+\.\d{2})(\d+\.\d{2})` 的拼接模式，插入一个空格分隔

实现位置：

- [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py) `_sanitize_cul_concatenated_tail` / `_rewrite_cul_params`

## 验证与回归测试

### 1) 单测：损坏 Wheat 行可被修复并正确改写

新增测试用例：

- [test_rewrite_cul_values_can_repair_malformed_wheat_row_using_template](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py#L3756-L3788)

断言点：

- 目标行能被重写为 token 可解析形式
- 7 个参数按预期小数位输出（例如 `P1V=34.900`，`G3=80.000`）

### 2) 端到端：Phase1 BatchA Wheat 不再因 CUL 改写失败而中断

复现命令（示例）：

```powershell
& $py $runner --batch BatchA --budget quick --workers 1 --repetitions 1 --crops Wheat --tag wheat_debug_weather_ok_fix_cul_v1
```

结果：4 个 job 均完成并产出 score（不再 `NA`）。

## 经验沉淀：类似问题的排查 SOP

### Step 1：确认改写对象是“运行时拷贝”，避免污染官方 case

原则：

- 不直接改 `C:\DSSAT48\Wheat` / `C:\DSSAT48\Genotype`
- 只在 `.dssat_rt/...` 的 runtime copy 内做修改与诊断

### Step 2：遇到 score 全相同或大量 -99，先分离“模拟没跑完”与“读取/评分错误”

常见假象：

- `HWAM=-99` 触发 fallback（曾发生过将降水 PRCM 当作产量的错误）
- weather 缺失导致模拟提前结束（例如缺 `75251`）

建议：

- 固定抓取 `Evaluate.OUT / Summary.OUT / WARNING.OUT`（按 trt 落盘），优先用 DSSAT 输出文件事实判断

### Step 3：遇到 `.CUL` 改写失败，优先检查目标 cultivar 行是否 malformed

检查点：

- cultivar 行是否 token 数量不足
- 是否出现 `80.05128.0` 这类粘连
- 同文件内是否存在 `DFAULT/MINIMA/MAXIMA` 等可作为模板的标准行

### Step 4：改写策略要以“标准行模板”为基准，而不是以目标行的当前状态为基准

原因：

- 真实运行环境里目标行可能已被历史流程污染
- 以模板推断 numeric 区域，更能保证格式一致性和可恢复性

## 相关代码引用

- CUL 改写： [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)
- 运行期写入/清洗： [run_model.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/run_model.py)
- 回归测试： [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py)

