# PEST-MGDA-DSSAT 项目开发文档

## 1. 结论：是否可以开始实施

可以开始实施。

依据：在 [mvp_pest_mgda](file:///c:/DSSAT48/Wheat/mvp_pest_mgda) 目录已跑通最小闭环（PEST++ 生成 Jacobian/残差 → MGDA 计算更新 → DSSAT 以更新参数再运行一次），证明关键技术链路、文件接口与命令行执行可行。

## 2. 项目目标与范围

### 2.1 总体目标

- 面向 DSSAT（当前目录为 Wheat），实现“多目标率定”自动化流水线：
  - PEST/PEST++ 负责生成敏感性（Jacobian）与残差
  - MGDA 负责在多观测组之间求共同下降方向
  - 控制器负责更新参数并迭代，输出帕累托前沿或帕累托稳定解

### 2.2 MVP已覆盖范围

- 场景：KSAS8101（Wheat）
- 参数：土壤初始含水量（示例：sh2o_15、sh2o_30）
- 观测目标：2组（产量 HWAM、LAI LAIX）
- 迭代：单步 MGDA 更新

### 2.3 本项目开发范围（下一阶段）

- 多处理（treatment）与多场景批量运行（基于 DSSBatch.v48 或多目录复制）
- 多观测组扩展：产量/LAI/物候/土壤水分时间序列/氮素等
- 参数集扩展：遗传参数（CUL）、土壤水力参数（SOL）、管理参数（X 文件施肥/灌溉等）
- 迭代与收敛策略：步长自适应、回溯线搜索/信赖域、帕累托稳定判据
- 结果归档：每次迭代保存参数、观测误差、目标值与帕累托解集

## 3. 关键前置条件（进入正式开发前必须固化）

### 3.1 数据与文件

- 试验定义：明确要率定的 FileX（或多 FileX）与 treatment 编号
- 观测数据：每个观测必须能映射到 DSSAT 输出文件字段（Summary.OUT/Evaluate.OUT/PlantGro.OUT 等）
- 观测误差模型：至少给出每个观测组的标准差/权重策略（用于残差标准化）

### 3.2 运行环境

- DSSAT 可执行文件路径与运行方式固定（当前使用 DSCSM048.EXE 的 C 模式）
- PEST++ 可执行文件可用（pestpp-glm.exe 等）
- Python 依赖：pyemu、numpy、pandas（按需）

### 3.3 可重复性

- 禁止污染“主目录输入文件”：所有修改必须可回滚，或复制到 sandbox 目录运行
- 每次迭代必须生成可追溯工件：参数文件、JCO/JCB、REI、解析后的目标值

## 4. 系统架构与模块边界

### 4.1 模块划分

- Orchestrator（编排器）
  - 负责：迭代循环、工件目录、失败重试、收敛判定、保存结果
- DSSAT Adapter（模型适配器）
  - 负责：生成/修改输入文件、调用 DSSAT、清理输出、返回解析指标
- PEST++ Adapter（敏感性适配器）
  - 负责：生成 pst/tpl/ins，调用 pestpp-glm 生成 Jacobian 与 residual
- Objective & Parser（目标与解析器）
  - 负责：从 DSSAT 输出抽取观测对应的模拟值，组装为 PEST 输出或直接用于多目标
- MGDA Solver（多梯度求解器）
  - 负责：按观测组切分梯度，标准化，求最小范数组合，给出更新方向

### 4.2 运行数据流（每次迭代）

1) 写入/渲染参数（params.dat 或更一般的参数载体）
2) 运行 DSSAT，生成可解析的输出
3) 运行 PEST++（NOPTMAX=-1）生成 Jacobian/残差
4) MGDA 计算更新并写回参数
5) 保存工件并进入下一轮

## 5. 接口定义（文件接口 + 过程接口）

### 5.1 文件接口（强约束）

- 参数文件（推荐规范）
  - path: params.dat
  - format: 每行 `name value`
- 参数模板（PEST TPL）
  - path: params.tpl
  - format: `ptf ~`，占位符 `~name~`
- 观测输出（模型到 PEST）
  - path: pest_out.dat
  - format: 每行 `obs_name value`
- 观测指令（PEST INS）
  - path: pest_out.ins
  - format: `pif ~` + 对应读取规则

### 5.2 Python 过程接口（建议签名）

- `run_dssat(params: dict, scenario: str, trt: int, workdir: Path) -> dict[str, float]`
  - 输入：参数字典 + 场景 + treatment + 工作目录
  - 输出：与观测同名的模拟值字典

- `build_pest_case(workdir: Path, params: dict, obs_measured: dict, obs_groups: dict) -> Path`
  - 输出：pst 文件路径

- `run_pest_glm(workdir: Path, pst: Path) -> tuple[Path, Path]`
  - 输出：Jacobian（.jcb/.jco）与 residual（.rei）路径

- `mgda_update(workdir: Path, pst: Path, jco: Path, rei: Path, step: float) -> dict[str, float]`
  - 输出：新参数字典（并落盘）

### 5.3 错误处理与退出码

- DSSAT 运行失败：保存 stdout/stderr + WARNING.OUT，并返回非零退出
- PEST++ 失败：保存 .rec/.log 并返回非零退出
- 解析失败：输出文件与期望字段缺失时，明确报错并停止迭代

## 6. 配置管理

### 6.1 配置文件（建议）

- `project.yml`（后续开发新增）：
  - DSSAT 根目录
  - 场景列表（filex, trt）
  - 参数定义（边界、初值、变换、映射到文件的规则）
  - 观测定义（来源文件、字段、单位、权重/σ、分组）
  - 迭代设置（步长、最大迭代、收敛阈值、线搜索）

## 7. 质量保证（QA）

- 回归基线：同一 params.dat 下 pest_out.dat 必须可复现
- 物理约束：参数边界与文件写入必须遵守 DSSAT 定宽格式
- 自动检查：
  - 输出存在性检查
  - 字段完整性检查
  - 迭代工件归档完整性检查

## 8. 项目管理与里程碑

### 8.1 里程碑

- M0：闭环可跑（已完成）
- M1：配置化（将场景/参数/观测从代码迁移到配置）
- M2：多目标扩展（>=4个观测组，MGDA 支持 k>2）
- M3：批量场景（多处理、多年份/多站点）
- M4：结果管理（帕累托前沿、可视化、可追溯工件）

### 8.2 工作分支建议

- main：稳定可复现
- dev：集成分支
- feature/*：特性开发
- fix/*：缺陷修复

### 8.3 提交规范（建议）

- 提交粒度：一次提交只做一类改变（接口/算法/修复/配置）
- 提交信息：
  - `feat:` 新功能
  - `fix:` 修复
  - `refactor:` 重构
  - `chore:` 工程化/依赖/杂项

## 9. 当前代码基线入口

- 入口脚本（闭环）：[run_mvp.ps1](file:///c:/DSSAT48/Wheat/mvp_pest_mgda/run_mvp.ps1)
- DSSAT 运行与文件写入： [run_model.py](file:///c:/DSSAT48/Wheat/mvp_pest_mgda/run_model.py)
- PEST 控制文件生成： [build_pest_setup.py](file:///c:/DSSAT48/Wheat/mvp_pest_mgda/build_pest_setup.py)
- MGDA 更新： [mgda_update.py](file:///c:/DSSAT48/Wheat/mvp_pest_mgda/mgda_update.py)

