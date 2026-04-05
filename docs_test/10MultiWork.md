# 10MultiWork

## 目的

本文档用于跟踪方案 B 在当前项目中的实际落地进度，不再停留在纯设计稿层面。

当前判断：

- matrix 路径已经形成可用的 V1 批处理内核
- 重点能力已经覆盖：worker 池、任务落盘、单写者聚合、心跳监控、stale 回收、resume 恢复、批次报告
- 当前实现仍主要服务 `matrix_cell`
- 更通用的 batch service 抽象仍未完成

## 本轮更新

- 已补上 `resume_batch(batch_root)` 恢复入口
- 已补上 CLI 参数 `--resume`、`--batch-root`、`--retry-limit`
- 已补上批次状态 `aggregating`、`completed_with_failures`
- 已验证恢复批次时不会重置已有 worker 根目录
- 已新增恢复相关测试并通过全量测试
- 已确认 `pest_runner.update_json_artifact()` 现已走原子写，不再是旧版文档中的风险点
- 已把 `SchedulerConfig` 从 project JSON 注入到 matrix 调度路径
- 已把 `project_wheat.json` 增补 `scheduler` 配置段
- 已补齐 task 短暂过渡态 `pending`、`sandbox_ready`、`failed_retryable`
- 已补齐 worker 过渡态 `preparing`、`collecting`
- 已新增 `batch_state.json` 落盘，并在 `running/aggregating/completed/failed` 间更新

## 当前代码落点

- 批处理数据模型： [batch_models.py](file:///D:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/batch_models.py)
- 原子写工具： [atomic_io.py](file:///D:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/atomic_io.py)
- 任务状态存储： [task_store.py](file:///D:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/task_store.py)
- worker 池： [worker_pool.py](file:///D:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/worker_pool.py)
- matrix 批处理主入口： [auto_evolve.py](file:///D:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py)
- runtime manifest / contract： [pest_runner.py](file:///D:/Wheat/Wheat/mvp_pest_mgda/src/calibration_core/pest_runner.py)

## 总体状态

| 模块/能力 | 状态 | 说明 |
| --- | --- | --- |
| Task/Batch 数据模型 | 已完成 | 已有 `BatchSpec`、`TaskSpec`、`TaskStateRecord`、`TaskResultRecord`、`WorkerState`、`WorkerSandbox` |
| 原子写 | 已完成 | `atomic_write_text()`、`atomic_write_json()` 已落地，并被 `TaskStore` 与 `pest_runner` 使用 |
| 固定 worker 池 | 已完成 | 已有 `build_worker_pool()` 与按 worker 目录隔离的执行结构 |
| WorkerSandbox 复用 | 已完成 | 已支持初始化一次后按 task 复用；resume 时可避免重置根目录 |
| task manifest/state/result | 已完成 | `task_manifest.json`、`task_state.json`、`task_result.json` 已落地 |
| heartbeat / stale 检测 | 已完成 | 已有 heartbeat 文件、stale 检测、进程终止与状态回收 |
| retry 基础能力 | 已完成 | 已有 `execute_matrix_job_with_retry()`，并支持 CLI 覆盖 `retry_limit` |
| resume 恢复 | 已完成 | 已有 `resume_batch()`、`resolve_resumable_matrix_jobs()`、`--resume`、`--batch-root` |
| 单写者聚合 | 已完成 | worker 写本地 task 结果，聚合由 coordinator 侧收口 |
| batch report | 已完成 | 已有 `batch_report.json` 与 aggregate 产物快照 |
| batch 状态 `aggregating` | 已完成 | 批次执行后进入 `aggregating`，最终进入 `completed` 或 `completed_with_failures` |
| batch 状态 `completed_with_failures` | 已完成 | 已按结果集状态判定 |
| CLI 覆盖项 | 已完成 | 已有 `--max-workers`、`--resume`、`--batch-root`、`--retry-limit`、`--quality-gate-stop-level`，且未显式传参时可回落到 project config |
| matrix 之外的统一 task 提交 | 未完成 | 当前仍主要面向 `matrix_cell` |
| queue JSONL / batch_state.json | 部分完成 | `batch_state.json` 已落地；`pending.jsonl`、`completed.jsonl`、`failed.jsonl` 仍未引入 |
| 独立 BatchScheduler / BatchAggregator 模块 | 未完成 | 能力散布在 `auto_evolve.py` 与 `TaskStore`，尚未抽成独立服务层 |
| scheduler 配置从项目 JSON 解析 | 已完成 | `run_matrix()` 已解析 `project_wheat.json` 中的 `scheduler`，CLI 仅作为覆盖项 |
| priority queue / crop affinity 调度 | 未完成 | 当前仍是简单分桶调度 |
| formal/multistart/MOO 统一接入 | 未完成 | 设计已定，执行层尚未统一 |

## 已完成项

### 0. 协议与目录先行

- [x] 已抽出公共模型层：
  - `SchedulerConfig`
  - `BatchSpec`
  - `TaskSpec`
  - `TaskStateRecord`
  - `TaskResultRecord`
  - `WorkerState`
  - `WorkerSandbox`
- [x] 已抽出原子写工具
- [x] 已引入 `TaskStore`
- [x] 已在运行流程中落盘：
  - `task_manifest.json`
  - `task_state.json`
  - `task_result.json`
  - `run_manifest.json`
  - `contract_report.json`

### 1. 固定 worker 池

- [x] 已有独立 `worker_001`, `worker_002`, ... 目录
- [x] 已有 `sandbox/`、`tasks/`、`logs/`、`current_task.json`、`heartbeat.json`
- [x] 已由 worker 目录隔离 DSSAT case 与 runtime
- [x] 已将 matrix 并发执行切换到 worker pool 模式

### 2. 恢复与回收

- [x] 已有 heartbeat 写入
- [x] 已有 stale 检测与运行中任务终止逻辑
- [x] 已有 `retry_pending`
- [x] 已有 `resume_batch(batch_root)`
- [x] 已有 `--resume`
- [x] 已有 `--batch-root`
- [x] 已有 `--retry-limit`
- [x] 已有 `completed_with_failures`

### 3. 聚合与报告

- [x] 已由 coordinator 统一聚合总表
- [x] 已有 batch 级 quality gate 决策
- [x] 已有 `batch_report.json`
- [x] 已将 aggregate 产物复制到批次目录

## 部分完成项

### 任务模型

- [x] `task_type` 字段已经存在
- [~] 当前实际只使用 `matrix_cell`
- [ ] `formal_run`
- [ ] `multistart_chain`
- [ ] `moo_candidate`

### 状态机

已实现或已使用的状态：

- Batch:
  - [x] `running`
  - [x] `aggregating`
  - [x] `completed`
  - [x] `completed_with_failures`
  - [x] `failed`
- Worker:
  - [x] `idle`
  - [x] `running`
  - [x] `retrying`
  - [x] `preparing`
  - [x] `collecting`
  - [ ] `quarantined`
  - [ ] `offline`
- Task:
  - [x] `assigned`
  - [x] `running`
  - [x] `collecting`
  - [x] `passed`
  - [x] `failed_fatal`
  - [x] `stale`
  - [x] `retry_pending`
  - [x] `aggregated`
  - [x] `pending`
  - [x] `sandbox_ready`
  - [x] `failed_retryable`

说明：

- 代码已经具备恢复与重试能力，但状态机还没有完全扩展成设计稿中的全量枚举
- 当前更偏向“面向 matrix 场景足够稳定”，还不是“通用批服务的完整状态机”

### 写入策略

- [x] `TaskStore` 使用原子写
- [x] `pest_runner.update_json_artifact()` 使用原子写
- [~] TSV 总表仍由 coordinator 串行 append/rebuild，而不是统一封装到独立 `BatchAggregator`

## 本轮补齐的剩余工作

本轮实际额外完成：

- [x] 把 `--retry-limit` 接入 CLI
- [x] 把 `retry_limit` 接入 `run_matrix()`
- [x] 把 `retry_limit` 接入 `execute_matrix_jobs_with_worker_pool()`
- [x] 在单线程 matrix 路径下也统一走 `execute_matrix_job_with_retry()`
- [x] 新增对应测试覆盖参数解析与 manifest 写入
- [x] 把 `SchedulerConfig` 接入 `run_matrix()` 默认调度参数解析
- [x] 允许 `--max-workers` / `--retry-limit` 仅作为覆盖项，不传时回落 project config
- [x] 为 `project_wheat.json` 增补 `scheduler` 配置段
- [x] 新增 scheduler 配置解析测试
- [x] 在 worker 执行路径中补齐 `pending -> assigned -> sandbox_ready -> running -> collecting -> passed/failed_*`
- [x] 在 retry 流程中补齐 `failed_retryable -> retry_pending`
- [x] 新增状态流转测试
- [x] 新增 `batch_state.json`，记录批次状态、完成数、失败数、quality gate 决策与报告路径
- [x] 新增 `batch_state.json` 回归测试

## 仍未实现的内容

### A. 通用调度服务层

- [ ] 独立 `BatchScheduler`
- [ ] 独立 `BatchAggregator`
- [ ] 将 `auto_evolve.py` 真正瘦身为 task producer / adapter

当前情况：

- 这部分逻辑已经“事实存在”，但仍耦合在 [auto_evolve.py](file:///D:/Wheat/Wheat/autoresearch_sandbox/auto_evolve.py) 中
- 从运行能力看已够用
- 从模块边界看仍需后续重构

### B. 队列持久化

- [ ] `queue/tasks_index.json`
- [ ] `queue/pending.jsonl`
- [ ] `queue/completed.jsonl`
- [ ] `queue/failed.jsonl`
- [ ] `batch_state.json`

当前情况：

- 现在主要依赖 `task_state.json`、`task_result.json`、`batch_manifest.json`、`batch_report.json`
- resume 已经可用，因此这组 JSONL 队列文件不再是“功能阻塞项”
- 但若后续要做更强的审计和跨进程调度，这部分仍值得补齐

### C. 调度策略增强

- [ ] 优先级队列
- [ ] crop affinity
- [x] 从 project config 读取 scheduler 配置
- [x] heartbeat / stale / retry 等参数统一配置化

当前情况：

- `SchedulerConfig` 现已支持从 project config 读取：
  - `task_parallelism`
  - `crop_parallelism`
  - `retry_limit`
  - `heartbeat_interval_sec`
  - `stale_timeout_sec`
  - `sandbox_reuse`
  - `copy_case_once`
  - `aggregate_write_mode`
- 当前仍未完成的是更复杂的调度策略，而不是配置注入本身

### D. 扩展到更多 task 类型

- [ ] formal batch 接入同一调度器
- [ ] multi-start MGDA 接入同一调度器
- [ ] NSGA-II / MOO candidate 接入同一调度器

### E. 错误分类体系

- [~] 已有部分错误码：
  - `E_STALE`
  - `E_TIMEOUT`
  - `E_CONTRACT`
  - `E_DSSAT_EXEC`
  - 以及若干执行/I/O 类错误码
- [ ] 尚未完全扩展到设计稿中的统一错误分类字典

## 这一轮不建议继续硬做的内容

以下内容属于“下一阶段重构”而不是“本轮小补丁”：

- `auto_evolve.py` 大规模拆分
- 新建完整 `BatchScheduler` / `BatchAggregator` 服务层
- 将 formal / multistart / MOO 全部迁入统一调度框架
- 引入 queue JSONL 与更复杂的持久化调度协议

原因：

- 当前 matrix 路径已经形成稳定可测的 V1
- 继续在这一轮强推大重构，会显著提高回归风险
- 更合理的顺序是先锁定现有 matrix 批处理协议，再分阶段推广到其他实验类型

## 建议的下一阶段顺序

1. 抽出 `BatchScheduler` 与 `BatchAggregator`
2. 让 formal batch 复用同一批处理内核
3. 再推进 multi-start / MOO
4. 最后补优先级队列与 crop affinity

## 验证状态

本轮变更后已验证：

- `python -m unittest discover -s tests` 通过
- `python -m ruff check src` 通过
- `python -m mypy src` 通过

## 结论

结论更新为：

- 方案 B 的 matrix V1 已经落地，不再只是设计草案
- 恢复、聚合、批次状态、worker 池、任务落盘已经可用
- 调度参数现在也已经能从 project JSON 统一注入
- 当前最大的剩余工作不再是“补功能缺口”，而是“把已实现能力从 matrix 专用脚本中继续抽象出来”
- 因此下一步重点应从“补单点能力”切换到“模块解耦与多任务类型接入”
