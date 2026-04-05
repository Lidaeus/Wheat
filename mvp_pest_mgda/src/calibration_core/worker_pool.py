from __future__ import annotations

from pathlib import Path

from calibration_core.batch_models import WorkerSandbox


def build_worker_sandbox(base_dir: Path, worker_index: int) -> WorkerSandbox:
    resolved_base_dir = Path(base_dir).resolve()
    worker_id = f"worker_{worker_index + 1:03d}"
    root_dir = resolved_base_dir / worker_id
    sandbox_dir = root_dir / "sandbox"
    tasks_dir = root_dir / "tasks"
    logs_dir = root_dir / "logs"
    return WorkerSandbox(
        worker_id=worker_id,
        worker_index=worker_index,
        root_dir=root_dir,
        sandbox_dir=sandbox_dir,
        tasks_dir=tasks_dir,
        logs_dir=logs_dir,
        current_task_path=root_dir / "current_task.json",
        heartbeat_path=root_dir / "heartbeat.json",
        worker_state_path=root_dir / "worker_state.json",
        dssat_case_dir=sandbox_dir / "dssat_case",
    )


def build_worker_pool(base_dir: Path, worker_count: int) -> list[WorkerSandbox]:
    return [build_worker_sandbox(base_dir, worker_index) for worker_index in range(max(1, int(worker_count)))]
