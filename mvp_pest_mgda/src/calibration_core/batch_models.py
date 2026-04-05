from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SchedulerConfig:
    task_parallelism: int
    crop_parallelism: int = 1
    retry_limit: int = 0
    heartbeat_interval_sec: int = 15
    stale_timeout_sec: int = 1800
    sandbox_reuse: bool = True
    copy_case_once: bool = True
    aggregate_write_mode: str = "single_writer"

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BatchSpec:
    batch_id: str
    batch_type: str
    created_at: str
    project_root: str
    scheduler_config: SchedulerConfig
    task_count: int
    crop_set: list[str] = field(default_factory=list)
    quality_gate_mode: str = ""
    protocol_snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "created"

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scheduler_config"] = self.scheduler_config.to_payload()
        return payload


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    batch_id: str
    task_type: str
    crop: str
    priority: int
    project_config_path: str
    protocol: dict[str, Any] = field(default_factory=dict)
    input_refs: dict[str, Any] = field(default_factory=dict)
    expected_outputs: list[str] = field(default_factory=list)
    runtime_env: dict[str, str] = field(default_factory=dict)
    retry_index: int = 0

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerState:
    worker_id: str
    status: str
    sandbox_root: str
    current_task_id: str = ""
    last_heartbeat_at: str = ""
    crop_affinity: str = ""
    failure_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskStateRecord:
    task_id: str
    state: str
    worker_id: str = ""
    assigned_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    retry_count: int = 0
    error_code: str = ""
    error_summary: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskResultRecord:
    task_id: str
    status: str
    exit_code: int
    duration_sec: float
    score: float
    quality_gate_status: str = ""
    contract_status: str = ""
    artifact_index: dict[str, str] = field(default_factory=dict)
    manifest_path: str = ""
    contract_report_path: str = ""
    stdout_path: str = ""
    stderr_path: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerSandbox:
    worker_id: str
    worker_index: int
    root_dir: Path
    sandbox_dir: Path
    tasks_dir: Path
    logs_dir: Path
    current_task_path: Path
    heartbeat_path: Path
    worker_state_path: Path
    dssat_case_dir: Path
