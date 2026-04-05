# 实现细节与多作物扩展性审查

## 1. 评审结论

当前实现层最值得肯定的地方，是已经出现了若干真正适合作为长期基础设施的模块；最需要警惕的地方，则是**多作物逻辑仍然分散在“默认值、回退逻辑、局部硬编码”中**。

这意味着：

- 对 Wheat 和当前五作物主线，项目已经相当可用
- 对“未来支持 DSSAT 所有作物”这一长期目标，现在还不够系统

## 2. 值得保留的实现优点

## 2.1 固定宽度写回思路是正确的

`rewrite_cul_values()` 没有做简单字符串替换，而是先解析 header，再按原始字段宽度回写数值 [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L413-L498)。

这是 DSSAT 文件操作里非常关键的一点，说明这次重构没有破坏最重要的“固定宽度安全改写”原则。

## 2.2 参数边界优先级机制设计合理

`resolve_parameter_bounds()` 已明确区分：

- `custom`
- `official`
- `fallback`

并能输出 bounds report [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L744-L832)。

这对论文中的方法可复核性非常重要，因为它能解释：

- 某个参数边界来自哪里
- 是否使用了官方边界
- 是否发生了回退

## 2.3 运行时 case 管理已具备较强工程意识

`case_runtime.py` 已经把：

- case dir 解析
- runtime root 解析
- cultivar 路径改写
- DSSAT48.INP / INH 路径修补

做成了相对独立的能力 [case_runtime.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/case_runtime.py#L98-L204)。

这是后续并行运行、多 case 隔离、多作物运行的基础。

## 2.4 结果 schema 设计非常适合论文产物

`MatrixSummaryView`、`ExperimentExportContext`、`TreatmentMetricExportRow`、`AggregateMetricExportRow` 等对象已经明显在为：

- leaderboard
- heatmap
- scatter
- appendix table

服务 [result_schema.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/result_schema.py#L52-L123)。

这比“最后再从日志拼图表”要成熟得多。

## 3. 实现层主要问题

## 3.1 多作物配置仍然不是真正的数据模型

虽然已有：

- [config/project.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/project.json)
- [config/multi/project_maize.json](file:///d:/Wheat/Wheat/mvp_pest_mgda/config/multi/project_maize.json)
- 其他 `config/multi/*.json`

但项目目前仍主要依赖“每个 crop 一份 JSON + 运行时代码自行解释”。这有两个问题：

1. 作物知识分散
2. 不同模块可能各自实现一套默认逻辑

### 直接证据

`_build_project_config()` 直接生成默认：

- 观测分组
- 指标变量
- `t_vars`

参考：[dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L840-L888)

这说明“多作物项目配置生成”仍然内含一套默认农学假设，而不是完全由注册表驱动。

## 3.2 当前指标体系仍偏向“产量 + LAI + 少量时序”的通路

`resolve_primary_metric_codes()` 当前主要围绕：

- `yield_var`
- `laix_var`

工作 [observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py#L107-L128)。

`resolve_t_vars()` 默认回退为：

- `LAID`
- `LWAD`
- `SWAD`

参考：[observations.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py#L98-L105)

这对当前 Wheat 主线很自然，但对未来全作物来说至少有三个风险：

1. 某些作物的关键表型不在这条默认链上
2. 不同作物的“主产量指标”不应靠回退猜测
3. 论文中会需要更明确地区分“共享评价指标”和“作物特异指标”

### 建议

把指标体系拆成三层：

- `core_metrics`：跨作物统一可比指标
- `crop_required_metrics`：该作物必须具备的主指标
- `crop_optional_metrics`：可用于扩展分析但不影响主矩阵准入

## 3.3 观测分组与权重逻辑仍含局部硬编码

`DEFAULT_OBSERVATION_GROUPS` 当前写在 `build_pest_setup.py` [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py#L37-L43)。

这会带来一个结构性问题：

- G 维本应是研究方法主轴
- 但它当前的一部分默认知识仍埋在工程实现里

如果未来扩展作物或扩展组协议，最容易发生的情况就是：

- 配置写了一套
- 工程层又保留一套默认影子
- 最终谁生效不直观

### 建议

让 `G1`、`G3` 都变成显式 profile：

- `grouping_profiles/g1_flat.json`
- `grouping_profiles/g3_dssat_extended/<crop>.json`

工程层只负责应用，不再内置分组语义。

## 3.4 产量变量回退策略对研究语义有潜在污染

`pick_eval_value()` 在产量变量缺失时会按：

- `HWAM`
- `CWAM`
- `PRCM`
- `HWUM`
- `HWAH`

依次尝试 [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L375-L410)。

这在工程上很实用，并不构成代码错误；但在研究上存在语义风险：

- 不同变量并不总是同一种“产量”
- 跨作物比较时可能引入不可见口径差

### 建议

对论文主矩阵应使用更严格策略：

- 若 `crop_required_metrics` 中的主指标不存在，组合应标记为 `contract_invalid`
- exploratory / 宽松工程模式下仍可保留这种回退

## 3.5 多作物扫描器还只是“有限映射”

`scan_dssat_trials()` 当前依赖一张前缀到 `.CUL` 文件名的映射表 [dssat_io.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L501-L553)。

这张表目前只覆盖若干常见作物：

- Wheat
- Maize
- Rice
- Cabbage
- Cassava
- Potato
- Soybean

这并不能支撑“DSSAT 所有作物”。

### 建议

未来应优先把“作物发现”从硬编码映射升级为：

1. 基于 DSSAT 安装目录扫描
2. 基于 FileX/Genotype 元数据识别
3. 基于注册表补充规则

## 3.6 S2/S3 的跨作物阶段模板尚未正式对象化

研究路线图已经非常明确地指出，`S2` 不能继续被理解为 Wheat 参数名模板，而要理解为：

- 物候
- 冠层/营养生长
- 产量形成

但从当前实现结构看，这个阶段语义还没有变成一个正式的数据模型；更多仍是在研究层计划组合里被引用，而不是在平台层被注册。

### 建议

为每个作物建立：

- `phase_template`
- `param_group_template`

例如：

- Wheat：`phenology -> canopy -> yield`
- Maize：`phenology -> biomass -> yield`
- Rice：`phenology -> tiller/canopy -> grain`

这样 `S2` 才真正从“经验脚本顺序”升级为“平台级研究协议”。

## 3.7 质量门禁覆盖面不足

`pyproject.toml` 当前只对 `src` 开启 ruff/mypy [pyproject.toml](file:///d:/Wheat/Wheat/mvp_pest_mgda/pyproject.toml#L1-L10)。

这意味着：

- `autoresearch_sandbox` 不在主类型检查范围内
- 最容易变化的研究层代码反而最缺自动门禁

### 建议

至少增加一套对研究层的轻量门禁：

- `ruff check autoresearch_sandbox`
- `mypy autoresearch_sandbox`
- 或把研究层逐步包化

## 4. 对关键模块的逐项建议

## 4.1 `dssat_io.py`

### 优点

- 参数边界解析成熟
- cultivar 重写方法可靠
- trial 扫描与项目生成有工程价值

### 问题

- 模块职责过重，既负责 I/O，又负责配置生成，又负责 crop fallback
- 含有较多多作物默认假设

### 建议

拆分为：

- `bounds.py`
- `cultivar_io.py`
- `trial_discovery.py`
- `project_scaffold.py`
- `crop_registry.py`

## 4.2 `observations.py`

### 优点

- 将 observation runtime 与 output contract 区分开了
- 基本接口简洁

### 问题

- 主指标解析逻辑仍较窄
- 缺失指标时缺少足够结构化的解释

### 建议

增加：

- `required/optional` 标识
- `contract_validation_result`
- 按 crop profile 决定主指标和时序指标

## 4.3 `build_pest_setup.py`

### 优点

- 已经成为 PEST 工作流总装配点
- 支持 split、grouping、weight mode、MGDA alpha

### 问题

- 模块承担了过多策略解释职责
- 默认观测组仍内嵌

### 建议

保留其“装配器”角色，但把以下知识外移：

- 组定义 profile
- 权重策略 profile
- crop metric profile

## 4.4 `result_schema.py`

### 优点

- 当前最像“平台级稳定资产”
- 非常适合作为论文导出接口

### 建议

继续保持稳定，不建议频繁改字段含义；如果后续要扩展，优先采用：

- 新增字段
- profile 化导出

不要轻易改写现有主字段语义。

## 5. 面向“DSSAT 全作物”长期目标的具体改造路线

### 第一步：建立作物注册表

至少统一以下对象：

- `cultivar_file`
- `filex_suffix_family`
- `required_metrics`
- `optional_metrics`
- `grouping_profiles`
- `phase_templates`
- `parameter_aliases`
- `bounds_source`

### 第二步：把当前默认逻辑迁移到注册表

迁移对象包括：

- `SUMMARY_AFILE_COLUMN_MAP`
- `DEFAULT_OBSERVATION_GROUPS`
- `yield_var / laix_var / t_vars`
- `scan_dssat_trials` 中的前缀映射

### 第三步：把工程层改为“纯应用注册表”

目标状态应该是：

- 工程层不再声明作物知识
- 工程层只读取 crop profile 并执行

## 6. 本文件结论

当前实现细节已经能支撑当前研究推进，尤其足以支撑 Wheat 主线与多作物雏形；但若面向长期的“全作物平台”目标，它还没有达到相应抽象层次。最大的问题不是代码质量差，而是**作物知识还没有成为正式数据模型**。只要把这一层补齐，当前重构成果就有机会从“五作物项目”进一步升级为“DSSAT 遗传率定平台”。
