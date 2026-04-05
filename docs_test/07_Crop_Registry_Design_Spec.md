# Crop Registry 设计规格

## 1. 目标

本规格用于把当前分散在配置文件、默认回退和局部硬编码中的 crop-specific 知识，统一为一个正式的 `crop_registry` 数据模型。

本规格服务的不是“立刻支持 DSSAT 所有作物”的验收目标，而是：

1. 先稳定 Wheat 主线与现有多作物雏形
2. 再为后续跨作物扩展提供统一抽象

## 1.1 当前前置条件

本规格在当前阶段具备了比上一版更清晰的落地条件：

- 研究层已进入正式 lint/typecheck 门禁，registry 后续接入不会再游离于自动检查之外
- [eval.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/eval.py) 与 [auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已具备稳定的 runtime/artifacts 布局，后续读取 registry 时不会再与目录迁移同时发生
- `.CUL` 固定宽度回写、`FileX` treatment/cultivar 解析、registry 驱动的 `params.dat` / `params.tpl` 顺序以及多作物 `FileX` / cultivar / bounds 对齐契约，已经进入稳定门禁
- 下一阻塞点已经从“协议对象与 registry 谁先落地”转为“如何把当前语义门禁收口为科研 acceptance，并在需要新增作物时低风险扩展”；当前建议仍然是协议与 registry 并行细化，但避免一次性大迁移

## 2. 为什么现在需要 `crop_registry`

当前项目已经具备多作物雏形，但作物知识仍分散在多个模块中：

- [scan_dssat_trials()](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L501-L553) 维护 trial 前缀到 `.CUL` 的映射
- [_build_project_config()](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/dssat_io.py#L840-L888) 直接生成默认观测组、指标和 `t_vars`
- [resolve_t_vars()](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py#L98-L105) 提供默认时序指标
- [resolve_primary_metric_codes()](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/observations.py#L107-L128) 处理主指标识别
- [build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 直到本轮之前仍内嵌 `SUMMARY_AFILE_COLUMN_MAP` 与 `DEFAULT_OBSERVATION_GROUPS`

这导致：

- 作物知识难以审计
- 默认行为难以统一解释
- 新增作物时容易在多个文件重复改逻辑

## 3. `crop_registry` 的最小职责

`crop_registry` 首轮不需要包办一切，但至少要统一以下信息：

### 3.1 标识层

- `crop_family`
- `display_name`
- `aliases`

### 3.2 遗传与基因型层

- `genotype_file_name`
- `genotype_locator`
- `parameter_aliases`

### 3.3 指标层

- `yield_metric`
- `lai_metric`
- `timeseries_metrics`
- `required_metrics`
- `optional_metrics`

### 3.4 分组与阶段层

- `grouping_profiles`
- `phase_templates`
- `default_parameter_group`
- `summary_afile_columns`

### 3.5 bounds 层

- `bounds_source`
- `official_source_path`
- `fallback_bounds_mode`

## 4. 建议数据结构

当前实现已经稳定为 dataclass，只读契约以 snapshot 字段名冻结：

```python
@dataclass(frozen=True)
class CropProfile:
    family: str
    display_name: str = ""
    aliases: tuple[str, ...] = ()
    trial_prefixes: tuple[str, ...] = ()
    cultivar_file: str = ""
    yield_metric: str = "HWAM"
    laix_metric: str = "LAIX"
    timeseries_metrics: tuple[str, ...] = ("LAID", "LWAD", "SWAD")
    observation_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()
    summary_afile_columns: tuple[tuple[str, str], ...] = ()
    grouping_profiles: tuple[tuple[str, tuple[str, ...]], ...] = ()
    phase_templates: tuple[tuple[str, tuple[str, ...]], ...] = ()
    parameter_order: tuple[str, ...] = ()
    official_bounds_source: str = ""
```

字段深度仍可继续扩展，但 `CROP_PROFILE_SNAPSHOT_FIELDNAMES` 对应的只读字段名应视为当前冻结契约。

## 5. 与现有模块的关系

## 5.1 `dssat_io.py`

从 `dssat_io.py` 迁出的优先对象：

- 作物前缀到 genotype 文件的映射
- `_build_project_config()` 中的默认指标和分组
- bounds 默认来源说明

`dssat_io.py` 后续应更多负责：

- 文件扫描
- 固定宽度读写
- bounds 应用

而不是声明大量作物语义。

## 5.2 `observations.py`

后续应从 registry 读取：

- `yield_metric`
- `lai_metric`
- `timeseries_metrics`
- `required_metrics`

这样 `resolve_primary_metric_codes()` 与 `resolve_t_vars()` 就不再依赖宽泛默认回退作为唯一逻辑。

## 5.3 `build_pest_setup.py`

当前已从 registry 或 profile 层读取：

- `SUMMARY_AFILE_COLUMN_MAP`
- 默认观测组

下一轮仍需继续迁移：

- metric family 与 grouping 对应关系
- stage/grouping profile
- 更显式的 summary metric alias 规范

这样工程层可以保留“装配器”角色，而不再内置大量 crop-specific 知识。

## 5.4 `auto_evolve.py`

后续应从 registry 读取：

- `S2/S3` 阶段模板
- `G1/G3` 默认 profile
- 某作物可用的指标视图

这样研究层就不需要自己隐式假设某个作物一定适配某种模板。

## 6. 推荐首批作物范围

首轮 registry 不建议追求 DSSAT 全作物，而应只覆盖当前已有基础的作物：

- Wheat
- Maize
- Rice
- Soybean
- Potato
- Cassava
- Cabbage
- Sunflower

这是对当前代码事实的收口，不是对未来扩展的封顶。

## 7. 指标模式建议

为避免“主指标缺失时到底算失败还是回退”的歧义，建议 registry 同时支持两层策略：

### strict mode

- 主矩阵 / 论文模式使用
- `required_metrics` 缺失可触发 `contract_invalid`

### exploratory mode

- 工程排障或探索实验使用
- 允许 fallback，但必须落盘到 `contract_report.json`

## 8. 分阶段落地方案

### Phase 1：只做注册，不改行为

先建立 `crop_registry` 并让它复述现有默认逻辑：

- 不改变现有 fallback
- 不改变现有组定义
- 不改变现有实验结果

建议首批只提供只读 API，例如：

- `get_crop_profile(crop_family)`
- `resolve_crop_alias(name)`
- `iter_supported_crops()`

### Phase 2：让 `observations.py` 和 `dssat_io.py` 读取 registry

把最常见的默认逻辑迁移出去：

- `yield_var / laix_var / t_vars`
- genotype 文件定位
- 默认 bounds 来源

当前状态：已完成。

### Phase 3：让 `build_pest_setup.py` 和 `auto_evolve.py` 也切换到 profile 驱动

再迁：

- grouping profile
- stage template
- crop metric family

当前状态：已完成第二轮最小接入并补上第一轮语义门禁。[build_pest_setup.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/src/build_pest_setup.py) 已改为从 registry 读取 summary A-file 列映射与默认观测组；[auto_evolve.py](file:///d:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 已改为从 registry 解析 `S2/S3` 阶段模板与 `G1/G3` profile；[test_grouping_contract.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_grouping_contract.py) 已补齐 registry 只读 API、snapshot contract、多作物 golden subset 以及 project config 与 registry 的 `FileX` / cultivar / bounds 对齐断言；[test_config_resolution.py](file:///d:/Wheat/Wheat/mvp_pest_mgda/tests/test_config_resolution.py) 已补 `.CUL` 固定宽度回写、`FileX` treatment/cultivar 解析、registry 参数顺序与 live Wheat 观测契约 smoke。下一入口转为把这些既有门禁收口为科研 acceptance，而不是继续扩字段。

## 8.1 当前建议的第一批实现边界

基于当前进度，registry 下一轮不要同时解决所有作物抽象，而应优先守住以下已稳定的只读契约：

1. `iter_supported_crops()` 返回的作物列表
2. crop alias / display name / trial prefix 解析
3. yield / lai / timeseries metric 口径
4. genotype 文件定位
5. summary A-file 列映射、`grouping_profiles`、`phase_templates`

`grouping_profiles` 与 `phase_templates` 已完成 Wheat 主线闭环，跨作物 snapshot/golden tests 与第一轮语义门禁也已证明这些字段具备基础稳定性；下一轮重点不再是继续堆 registry 字段，而是把当前门禁变成科研 acceptance，并在新增作物时遵循同一套准入标准。

## 9. 验收标准

首轮视为成功的标准不是“支持所有 DSSAT 作物”，而是：

1. 当前已支持的多作物知识有唯一注册位置
2. 新增一个已知作物时，不再需要同时修改多个默认逻辑入口
3. Wheat 主线行为不退化
4. 研究层和工程层可以读取同一份 crop profile
5. 已注册作物的 snapshot 字段顺序、别名解析与试验前缀解析可由 golden tests 稳定保护
6. `.CUL` 固定宽度回写、`FileX` treatment/cultivar 解析、registry 参数顺序与多作物 bounds 对齐至少有一轮稳定门禁

## 10. 本文件结论

`crop_registry` 的价值，不在于立刻把项目变成全作物平台，而在于把已经存在的多作物雏形从“多处默认逻辑”升级为“单处正式数据模型”。当前阶段这一抽象已经进入第二轮接入，并具备稳定的跨作物只读契约与第一轮农学语义门禁；下一步最重要的，不是再扩字段，而是把这些契约收口为科研 acceptance，并在真正需要新增作物时按同一模板低风险扩展。
