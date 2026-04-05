from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from calibration_core.atomic_io import atomic_write_json
from calibration_core.batch_models import BatchSpec, TaskResultRecord, TaskSpec, TaskStateRecord, WorkerState


class TaskStore:
    def __init__(self, batch_root: Path) -> None:
        self.batch_root = Path(batch_root).resolve()
        self.batch_root.mkdir(parents=True, exist_ok=True)

    def write_batch_manifest(self, batch_spec: BatchSpec) -> Path:
        return atomic_write_json(self.batch_root / "batch_manifest.json", batch_spec.to_payload())

    def write_batch_state(self, payload: dict[str, Any]) -> Path:
        return atomic_write_json(self.batch_root / "batch_state.json", payload)

    def update_batch_manifest(self, **updates: Any) -> Path:
        manifest_path = self.batch_root / "batch_manifest.json"
        payload: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                loaded = {}
            if isinstance(loaded, dict):
                payload = loaded
        payload.update(updates)
        return atomic_write_json(manifest_path, payload)

    def update_batch_state(self, **updates: Any) -> Path:
        state_path = self.batch_root / "batch_state.json"
        payload: dict[str, Any] = {}
        if state_path.exists():
            try:
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                loaded = {}
            if isinstance(loaded, dict):
                payload = loaded
        payload.update(updates)
        return atomic_write_json(state_path, payload)

    def write_batch_report(self, payload: dict[str, Any]) -> Path:
        return atomic_write_json(self.batch_root / "batch_report.json", payload)

    def write_worker_state(self, worker_state_path: Path, state: WorkerState) -> Path:
        return atomic_write_json(worker_state_path, state.to_payload())

    def write_current_task(self, current_task_path: Path, task: TaskSpec | None) -> Path:
        payload = {} if task is None else task.to_payload()
        return atomic_write_json(current_task_path, payload)

    def write_task_manifest(self, task_dir: Path, spec: TaskSpec) -> Path:
        return atomic_write_json(Path(task_dir) / "task_manifest.json", spec.to_payload())

    def write_task_state(self, task_dir: Path, state: TaskStateRecord) -> Path:
        return atomic_write_json(Path(task_dir) / "task_state.json", state.to_payload())

    def write_task_result(self, task_dir: Path, result: TaskResultRecord) -> Path:
        return atomic_write_json(Path(task_dir) / "task_result.json", result.to_payload())
