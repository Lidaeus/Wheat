# 2026-04-11 Maize：CUL 改写误用 token 对齐导致写坏 fixed-width 行（IPVAR/宽度溢出）复盘

## 背景与目标

目标是让 Maize 在 Phase1（尤其是 `B2` / `pestpp-glm`）流程中稳定运行：构建 PEST setup 时会触发一次 baseline `run_model`，该 run 需要正确改写 `.CUL` 中 cultivar 参数（不破坏 fixed-width 结构、不产生 DSSAT 无法解析的行）。

本次复盘重点沉淀一条可复用经验：

- **DSSAT fixed-width 文件（如 `.CUL`）不要用 `split()`/token 对齐作为主路径**；token 对齐只能作为“坏行兜底”，且必须带强条件与防御性处理。

## 症状与直接证据

### 1) Maize 在 B2（pestpp-glm）阶段快速失败

复现命令（示例）：

```powershell
& $py $runner --batch Baselines --budget quick --workers 1 --repetitions 1 --crops Maize --tag maize_repro_v1
```

表现为：

- `B0/B0_OFFICIAL/B1` 可运行
- `B2` 在 “build_pest_setup -> baseline run_model” 处失败（还没开始 DSSAT treatment 调用）

### 2) 关键堆栈：CUL 改写阶段 ValueError（宽度溢出）

报错日志（示例）：  
[B2_maize_rep0_5c53c4.stderr.log](file:///d:/Wheat/Wheat/autoresearch_sandbox/phase1_runs/20260411_121557_phase1_baselines_quick_maize_repro_v1/logs/B2_maize_rep0_5c53c4.stderr.log#L52-L66)

核心异常：

- `ValueError: Value 228.0 exceeds DSSAT width 1 for column '.'`

这说明改写逻辑将一个应该写入数值列（如 `P1=228`）的值，尝试写进了一个宽度为 1 的字段（`"."`），而这个 `"."` 通常来自 `.CUL` 行内的占位/空列 token，被 `\S+` 抓成了一个独立 token。

## 根因分析

### 根因 A：fixed-width 行被当成 token 序列处理，列-位置错位

`.CUL` 文件属于 DSSAT 的典型 fixed-width 文本：

- 列边界由 header 行的“字符起始位置（starts）”决定
- 同一列内部允许空格填充
- 行内可能存在占位（如 `.`）以及多个连续空白

如果用 `split()` 或 `re.finditer(r"\S+")` 解析：

- 会丢失“空列”的存在感（连续空格被压缩）
- 会把占位 `.` 当成一个 token
- token 列表长度、顺序与 header 列并不必然 1:1 对齐

当代码试图用 token 的 index 反推列宽（`width = end-start`）并按该宽度格式化写回时，就会出现：

- `width` 过小（如 `"."` 的宽度为 1）
- 数值无法塞进该宽度 -> 抛 `ValueError`

### 根因 B：Rice 修复引入的“尾部 token 回退策略”误触发到了 Maize

Rice `.CUL` 的现实情况是：

- header 未列出 `G4`，但行尾多了一个数值 token（常见表现为“额外的 G4”）
- 因此需要一个“仅对坏行”的 fallback：按 `ECO#` 后的 numeric 尾部 token 去定点替换

但是在 Maize 的标准行上：

- header_starts/fixed-width 路径本来足够正确
- 误触发 token fallback 会在 fixed-width 行上产生错位风险

## 解决方案设计

核心原则：**固定宽度主路径必须优先且完整，token fallback 只能用于 malformed 行，并且要 fail-soft。**

### 方案 1：主路径坚持用 header_starts（fixed-width spans）替换

实现策略：

- 先通过 header 行构建 `starts` 与 `bounds`
- 对每个要更新的列（如 `P1/P2/P5/G2/G3/PHINT`），在 `(a,b)` 范围内做固定宽度替换或按 existing 精度替换
- 这种方式不依赖 token 数量，天然适配 DSSAT fixed-width 文件规范

### 方案 2：token fallback 加强触发条件，只在“明显坏行”时启用

token fallback 触发条件收紧为：

- **只有当 `len(token_matches) < len(header_cols)`**（行 token 明显少于 header 列，强烈暗示坏行/缺列）并且
- 前面的 fixed-width / 模板策略没有应用任何更新

同时 fallback 内部改为防御性处理：

- 若 `_format_like_existing()` 抛 `ValueError`，不再让整次改写失败，而是跳过该列继续

实现位置：

- [rewrite_cul_values](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)

## 验证与回归测试

### 1) 端到端：Maize Baselines quick 可完成（包含 B2）

复现命令（示例）：

```powershell
& $py $runner --batch Baselines --budget quick --workers 1 --repetitions 1 --crops Maize --tag maize_repro_after_tailfix_v1
```

结果：

- `B0/B0_OFFICIAL/B1/B2` 全部完成
- 不再出现 `build_pest_setup run_model.py failed` 或 `ValueError width 1`

### 2) 单测：Maize 标准行不应走 token fallback 并保持可改写

新增用例：

- [test_rewrite_cul_values_maize_does_not_use_tail_token_fallback_for_standard_row](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py#L3822-L3838)

断言点：

- 对标准行更新 `P1` 不抛异常
- 输出仍包含更新后的数值（行未被破坏）

## 经验沉淀：fixed-width 文件的排查与修复 SOP

### Step 1：先判断文件格式类型

- `.CUL/.SOL/.WTH` 多为 fixed-width（或强格式约束）
- 对 fixed-width，首选“按 header starts / 列边界”处理

### Step 2：不要用 split/token 推断列宽作为主策略

典型风险：

- token 列表无法表达空列
- token 的宽度只反映当前 token 的字符长度，不是列宽
- 占位 `.` / `-99` 等会干扰对齐

### Step 3：token fallback 只能在“坏行证据充分”时启用，并保证 fail-soft

推荐触发条件：

- `len(tokens) < len(header_cols)` 或明确缺列/粘连证据
- 主路径未能应用任何 update

推荐防御：

- 单列失败不应导致整次改写失败（除非必须保证全部生效）

## 相关代码引用

- CUL 改写主逻辑： [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py)
- Maize 回归测试： [test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py)

