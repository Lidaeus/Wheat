from __future__ import annotations

import argparse
import ast
import concurrent.futures
import csv
import functools
import hashlib
import importlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from itertools import combinations, product
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from calibration_core.batch_models import WorkerSandbox as WorkerSandboxModel
    from calibration_core.task_store import TaskStore as TaskStoreModel


CALIBRATION_SRC = (Path(__file__).resolve().parents[1] / "mvp_pest_mgda" / "src").resolve()
if CALIBRATION_SRC.exists():
    calibration_src = str(CALIBRATION_SRC)
    if calibration_src not in sys.path:
        sys.path.insert(0, calibration_src)

_ATOMIC_IO_MODULE = importlib.import_module("calibration_core.atomic_io")
_BATCH_MODELS_MODULE = importlib.import_module("calibration_core.batch_models")
_SANDBOX_RUNTIME_MODULE = importlib.import_module("calibration_core.sandbox_runtime")
_TASK_STORE_MODULE = importlib.import_module("calibration_core.task_store")
_WORKER_POOL_MODULE = importlib.import_module("calibration_core.worker_pool")

atomic_write_json = _ATOMIC_IO_MODULE.atomic_write_json
atomic_write_text = _ATOMIC_IO_MODULE.atomic_write_text
BatchSpec = _BATCH_MODELS_MODULE.BatchSpec
SchedulerConfig = _BATCH_MODELS_MODULE.SchedulerConfig
TaskResultRecord = _BATCH_MODELS_MODULE.TaskResultRecord
TaskSpec = _BATCH_MODELS_MODULE.TaskSpec
TaskStateRecord = _BATCH_MODELS_MODULE.TaskStateRecord
WorkerState = _BATCH_MODELS_MODULE.WorkerState
WorkerSandbox = _BATCH_MODELS_MODULE.WorkerSandbox
archive_tree = _SANDBOX_RUNTIME_MODULE.archive_tree
reset_runtime_directory = _SANDBOX_RUNTIME_MODULE.reset_directory
TaskStore = _TASK_STORE_MODULE.TaskStore
build_worker_pool = _WORKER_POOL_MODULE.build_worker_pool


DEFAULT_PROJECT_CONFIG_CANDIDATES = ("project.json", "project_wheat.json")
MetricValueByTrt = dict[int, float]
MetricDateByTrt = dict[int, list[int]]
MetricValueWithDateByTrt = dict[int, tuple[int, float]]
ComparableMetricValues = dict[str, MetricValueByTrt]
ComparableMetricDates = dict[str, MetricDateByTrt]
ComparableMetricValuesWithDates = dict[str, MetricValueWithDateByTrt]


@functools.lru_cache(maxsize=None)
def load_mvp_public_api(public_api_path: Path):
    resolved_public_api_path = Path(public_api_path).resolve()
    spec = importlib.util.spec_from_file_location(
        "mvp_public_api_runtime_auto_evolve",
        resolved_public_api_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load public API from {resolved_public_api_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module.load_public_api()


def _fallback_project_config_path(sandbox_dir: Path) -> Path:
    env_project_config = os.environ.get("AR_PROJECT_CONFIG")
    if env_project_config:
        return Path(env_project_config).resolve()
    for candidate_name in resolve_project_config_candidates(sandbox_dir):
        candidate_path = (sandbox_dir / candidate_name).resolve()
        if candidate_path.exists():
            return candidate_path
    return (sandbox_dir / DEFAULT_PROJECT_CONFIG_CANDIDATES[0]).resolve()


def infer_legacy_crop_from_sandbox(sandbox_dir: Path) -> str:
    resolved_sandbox_dir = Path(sandbox_dir).resolve()
    if (resolved_sandbox_dir / "project.json").exists():
        return ""
    if (resolved_sandbox_dir / "project_wheat.json").exists():
        return "wheat"
    return ""


def resolve_project_config_candidates(sandbox_dir: Path, public_api_path: Path | None = None) -> tuple[str, ...]:
    resolved_sandbox_dir = Path(sandbox_dir).resolve()
    resolved_public_api_path = (
        Path(public_api_path).resolve()
        if public_api_path is not None and str(public_api_path).strip()
        else (resolved_sandbox_dir.parent / "mvp_pest_mgda" / "public_api.py").resolve()
    )
    if not resolved_public_api_path.exists():
        return DEFAULT_PROJECT_CONFIG_CANDIDATES
    dssat_io_module = load_mvp_public_api(resolved_public_api_path).dssat_io
    resolver = getattr(dssat_io_module, "resolve_project_config_candidates", None)
    if resolver is None:
        return DEFAULT_PROJECT_CONFIG_CANDIDATES
    try:
        return resolver(
            resolved_sandbox_dir,
            candidate_relatives=DEFAULT_PROJECT_CONFIG_CANDIDATES,
            crop=os.environ.get("PROJECT_CROP", ""),
        )
    except TypeError as exc:
        if "crop" not in str(exc):
            raise
        return resolver(
            resolved_sandbox_dir,
            candidate_relatives=DEFAULT_PROJECT_CONFIG_CANDIDATES,
        )


def resolve_sandbox_project_config_path(sandbox_dir: Path, public_api_path: Path | None = None) -> Path:
    resolved_sandbox_dir = Path(sandbox_dir).resolve()
    resolved_public_api_path = (
        Path(public_api_path).resolve()
        if public_api_path is not None and str(public_api_path).strip()
        else (resolved_sandbox_dir.parent / "mvp_pest_mgda" / "public_api.py").resolve()
    )
    if not resolved_public_api_path.exists():
        return _fallback_project_config_path(resolved_sandbox_dir)
    dssat_io_module = load_mvp_public_api(resolved_public_api_path).dssat_io
    resolved_mvp_root = resolved_public_api_path.parent
    resolved_crop = infer_legacy_crop_from_sandbox(resolved_sandbox_dir) or os.environ.get("PROJECT_CROP", "")
    try:
        kwargs: dict[str, object] = {
            "env_var": "AR_PROJECT_CONFIG",
            "candidate_relatives": ("config/project.json",),
        }
        if resolved_crop.strip():
            kwargs["crop"] = resolved_crop
        resolved_path = dssat_io_module.resolve_project_config_path(resolved_mvp_root, **kwargs)
    except TypeError as exc:
        if "crop" not in str(exc):
            raise
        resolved_path = dssat_io_module.resolve_project_config_path(
            resolved_mvp_root,
            env_var="AR_PROJECT_CONFIG",
            candidate_relatives=("config/project.json",),
        )
    if resolved_path is not None:
        return resolved_path
    candidate_relatives = resolve_project_config_candidates(resolved_sandbox_dir, resolved_public_api_path)
    try:
        kwargs = {
            "env_var": "AR_PROJECT_CONFIG",
            "candidate_relatives": candidate_relatives,
        }
        if resolved_crop.strip():
            kwargs["crop"] = resolved_crop
        resolved_path = dssat_io_module.resolve_project_config_path(resolved_sandbox_dir, **kwargs)
    except TypeError as exc:
        if "crop" not in str(exc):
            raise
        resolved_path = dssat_io_module.resolve_project_config_path(
            resolved_sandbox_dir,
            env_var="AR_PROJECT_CONFIG",
            candidate_relatives=candidate_relatives,
        )
    return resolved_path or _fallback_project_config_path(resolved_sandbox_dir)


@dataclass(frozen=True)
class SandboxPaths:
    sandbox_dir: Path
    mvp_root: Path
    public_api_path: Path
    strategy_path: Path
    eval_path: Path
    project_config_path: Path
    dssat_trts_path: Path
    runs_dir: Path
    runtime_dir: Path
    runtime_params_path: Path
    runtime_pest_out_path: Path
    artifacts_dir: Path
    log_path: Path
    matrix_log_path: Path
    matrix_tsv_path: Path
    experiment_runs_tsv_path: Path
    experiment_protocol_artifacts_tsv_path: Path
    experiment_params_tsv_path: Path
    experiment_metrics_long_tsv_path: Path
    experiment_aggregate_metrics_tsv_path: Path
    experiment_summary_tsv_path: Path
    experiment_scatter_1to1_tsv_path: Path
    experiment_heatmap_wide_tsv_path: Path
    experiment_metric_split_heatmap_tsv_path: Path
    experiment_residuals_wide_tsv_path: Path
    experiment_figure_ready_tsv_path: Path
    main_matrix_report_md_path: Path
    main_matrix_leaderboard_tsv_path: Path
    main_matrix_dimension_summary_tsv_path: Path
    main_matrix_baseline_summary_tsv_path: Path
    main_matrix_baseline_detail_tsv_path: Path
    main_matrix_key_indicator_table_tsv_path: Path
    main_matrix_baseline_winners_tsv_path: Path
    main_matrix_metric_snapshot_tsv_path: Path
    main_matrix_paper_summary_tsv_path: Path
    main_matrix_protocol_overview_tsv_path: Path
    main_matrix_protocol_dimension_summary_tsv_path: Path
    main_matrix_protocol_nested_dimension_summary_tsv_path: Path
    main_matrix_protocol_hotspot_summary_tsv_path: Path
    main_matrix_protocol_reason_summary_tsv_path: Path
    main_matrix_quality_gate_tsv_path: Path
    main_matrix_appendix_index_tsv_path: Path
    main_matrix_protocol_paper_table_tsv_path: Path
    main_matrix_paper_main_table_tsv_path: Path
    main_matrix_paper_appendix_table_tsv_path: Path
    main_matrix_paper_table_tsv_path: Path
    main_matrix_topk_overall_tsv_path: Path
    main_matrix_topk_by_engine_tsv_path: Path
    main_matrix_topk_by_weight_tsv_path: Path
    main_matrix_topk_by_sequence_tsv_path: Path
    main_matrix_topk_by_grouping_tsv_path: Path
    main_matrix_topk_validation_only_tsv_path: Path
    main_matrix_topk_by_budget_tsv_path: Path
    main_matrix_topk_by_validation_budget_tsv_path: Path
    main_matrix_topk_improvement_tsv_path: Path
    parallel_workers_dir: Path
    case_template_dir: Path
    case_support_root: Path


def build_sandbox_paths(sandbox_dir: Path | None = None, mvp_root: Path | None = None) -> SandboxPaths:
    sandbox_source: str | os.PathLike[str] = sandbox_dir or os.environ.get("AR_SANDBOX_DIR") or Path(__file__).resolve().parent
    resolved_sandbox_dir = Path(sandbox_source).resolve()
    mvp_root_source: str | os.PathLike[str] = (
        mvp_root or os.environ.get("AR_MVP_ROOT") or (resolved_sandbox_dir.parent / "mvp_pest_mgda")
    )
    resolved_mvp_root = Path(mvp_root_source).resolve()
    runs_dir = resolved_sandbox_dir / "runs"
    runtime_dir = runs_dir / "runtime"
    artifacts_dir = resolved_sandbox_dir / "artifacts"
    return SandboxPaths(
        sandbox_dir=resolved_sandbox_dir,
        mvp_root=resolved_mvp_root,
        public_api_path=resolved_mvp_root / "public_api.py",
        strategy_path=resolved_sandbox_dir / "strategy.py",
        eval_path=resolved_sandbox_dir / "eval.py",
        project_config_path=resolve_sandbox_project_config_path(
            resolved_sandbox_dir,
            resolved_mvp_root / "public_api.py",
        ),
        dssat_trts_path=resolved_sandbox_dir / "dssat_trts.txt",
        runs_dir=runs_dir,
        runtime_dir=runtime_dir,
        runtime_params_path=runtime_dir / "params.dat",
        runtime_pest_out_path=runtime_dir / "pest_out.dat",
        artifacts_dir=artifacts_dir,
        log_path=artifacts_dir / "evolution_log.md",
        matrix_log_path=artifacts_dir / "matrix_experiments.md",
        matrix_tsv_path=artifacts_dir / "matrix_results.tsv",
        experiment_runs_tsv_path=artifacts_dir / "experiment_runs.tsv",
        experiment_protocol_artifacts_tsv_path=artifacts_dir / "experiment_protocol_artifacts.tsv",
        experiment_params_tsv_path=artifacts_dir / "experiment_params.tsv",
        experiment_metrics_long_tsv_path=artifacts_dir / "experiment_metrics_long.tsv",
        experiment_aggregate_metrics_tsv_path=artifacts_dir / "experiment_aggregate_metrics.tsv",
        experiment_summary_tsv_path=artifacts_dir / "experiment_summary.tsv",
        experiment_scatter_1to1_tsv_path=artifacts_dir / "experiment_scatter_1to1.tsv",
        experiment_heatmap_wide_tsv_path=artifacts_dir / "experiment_heatmap_wide.tsv",
        experiment_metric_split_heatmap_tsv_path=artifacts_dir / "experiment_metric_split_heatmap.tsv",
        experiment_residuals_wide_tsv_path=artifacts_dir / "experiment_residuals_wide.tsv",
        experiment_figure_ready_tsv_path=artifacts_dir / "experiment_figure_ready.tsv",
        main_matrix_report_md_path=artifacts_dir / "main_matrix_report.md",
        main_matrix_leaderboard_tsv_path=artifacts_dir / "main_matrix_leaderboard.tsv",
        main_matrix_dimension_summary_tsv_path=artifacts_dir / "main_matrix_dimension_summary.tsv",
        main_matrix_baseline_summary_tsv_path=artifacts_dir / "main_matrix_baseline_summary.tsv",
        main_matrix_baseline_detail_tsv_path=artifacts_dir / "main_matrix_baseline_detail.tsv",
        main_matrix_key_indicator_table_tsv_path=artifacts_dir / "main_matrix_key_indicator_table.tsv",
        main_matrix_baseline_winners_tsv_path=artifacts_dir / "main_matrix_baseline_winners.tsv",
        main_matrix_metric_snapshot_tsv_path=artifacts_dir / "main_matrix_metric_snapshot.tsv",
        main_matrix_paper_summary_tsv_path=artifacts_dir / "main_matrix_paper_summary.tsv",
        main_matrix_protocol_overview_tsv_path=artifacts_dir / "main_matrix_protocol_overview.tsv",
        main_matrix_protocol_dimension_summary_tsv_path=artifacts_dir / "main_matrix_protocol_dimension_summary.tsv",
        main_matrix_protocol_nested_dimension_summary_tsv_path=artifacts_dir
        / "main_matrix_protocol_nested_dimension_summary.tsv",
        main_matrix_protocol_hotspot_summary_tsv_path=artifacts_dir / "main_matrix_protocol_hotspot_summary.tsv",
        main_matrix_protocol_reason_summary_tsv_path=artifacts_dir / "main_matrix_protocol_reason_summary.tsv",
        main_matrix_quality_gate_tsv_path=artifacts_dir / "main_matrix_quality_gate.tsv",
        main_matrix_appendix_index_tsv_path=artifacts_dir / "main_matrix_appendix_index.tsv",
        main_matrix_protocol_paper_table_tsv_path=artifacts_dir / "main_matrix_protocol_paper_table.tsv",
        main_matrix_paper_main_table_tsv_path=artifacts_dir / "main_matrix_paper_main_table.tsv",
        main_matrix_paper_appendix_table_tsv_path=artifacts_dir / "main_matrix_paper_appendix_table.tsv",
        main_matrix_paper_table_tsv_path=artifacts_dir / "main_matrix_paper_table.tsv",
        main_matrix_topk_overall_tsv_path=artifacts_dir / "main_matrix_topk_overall.tsv",
        main_matrix_topk_by_engine_tsv_path=artifacts_dir / "main_matrix_topk_by_engine.tsv",
        main_matrix_topk_by_weight_tsv_path=artifacts_dir / "main_matrix_topk_by_weight.tsv",
        main_matrix_topk_by_sequence_tsv_path=artifacts_dir / "main_matrix_topk_by_sequence.tsv",
        main_matrix_topk_by_grouping_tsv_path=artifacts_dir / "main_matrix_topk_by_grouping.tsv",
        main_matrix_topk_validation_only_tsv_path=artifacts_dir / "main_matrix_topk_validation_only.tsv",
        main_matrix_topk_by_budget_tsv_path=artifacts_dir / "main_matrix_topk_by_budget.tsv",
        main_matrix_topk_by_validation_budget_tsv_path=artifacts_dir / "main_matrix_topk_by_validation_budget.tsv",
        main_matrix_topk_improvement_tsv_path=artifacts_dir / "main_matrix_topk_improvement.tsv",
        parallel_workers_dir=runs_dir / "parallel_workers",
        case_template_dir=resolved_mvp_root / "scripts" / "dssat_case",
        case_support_root=resolved_sandbox_dir.parent,
    )


PATHS = build_sandbox_paths()
SANDBOX_DIR = PATHS.sandbox_dir
MVP_ROOT = PATHS.mvp_root
PUBLIC_API_PATH = PATHS.public_api_path


_PUBLIC_API = load_mvp_public_api(PUBLIC_API_PATH)
_CROP_REGISTRY_MODULE = _PUBLIC_API.crop_registry
_RESULT_SCHEMA_MODULE = _PUBLIC_API.result_schema
AGGREGATE_METRIC_EXPORT_FIELDNAMES = _RESULT_SCHEMA_MODULE.AGGREGATE_METRIC_EXPORT_FIELDNAMES
FIGURE_READY_EXPORT_FIELDNAMES = _RESULT_SCHEMA_MODULE.FIGURE_READY_EXPORT_FIELDNAMES
RESIDUAL_EXPORT_BASE_FIELDNAMES = _RESULT_SCHEMA_MODULE.RESIDUAL_EXPORT_BASE_FIELDNAMES
SCATTER_EXPORT_FIELDNAMES = _RESULT_SCHEMA_MODULE.SCATTER_EXPORT_FIELDNAMES
SUMMARY_EXPORT_FIELDNAMES = _RESULT_SCHEMA_MODULE.SUMMARY_EXPORT_FIELDNAMES
TREATMENT_METRIC_EXPORT_FIELDNAMES = _RESULT_SCHEMA_MODULE.TREATMENT_METRIC_EXPORT_FIELDNAMES
TreatmentComparisonRecord = _RESULT_SCHEMA_MODULE.TreatmentComparisonRecord
TreatmentMetricRow = _RESULT_SCHEMA_MODULE.TreatmentMetricExportRow
AggregateMetricRow = _RESULT_SCHEMA_MODULE.AggregateMetricExportRow
build_aggregate_metric_export_value_map = _RESULT_SCHEMA_MODULE.build_aggregate_metric_export_value_map
build_figure_ready_export_row = _RESULT_SCHEMA_MODULE.build_figure_ready_export_row
build_residual_export_fieldnames = _RESULT_SCHEMA_MODULE.build_residual_export_fieldnames
build_residual_export_row = _RESULT_SCHEMA_MODULE.build_residual_export_row
build_scatter_export_row = _RESULT_SCHEMA_MODULE.build_scatter_export_row
build_summary_export_row = _RESULT_SCHEMA_MODULE.build_summary_export_row
extract_evaluation_result = _RESULT_SCHEMA_MODULE.extract_evaluation_result
extract_matrix_summary_view = _RESULT_SCHEMA_MODULE.extract_matrix_summary_view
build_aggregate_metric_export_rows = _RESULT_SCHEMA_MODULE.build_aggregate_metric_export_rows
build_combo_key = _RESULT_SCHEMA_MODULE.build_combo_key
build_experiment_export_context = _RESULT_SCHEMA_MODULE.build_experiment_export_context
build_treatment_metric_export_value_map = _RESULT_SCHEMA_MODULE.build_treatment_metric_export_value_map
build_treatment_comparison_records = _RESULT_SCHEMA_MODULE.build_treatment_comparison_records
build_treatment_metric_export_rows = _RESULT_SCHEMA_MODULE.build_treatment_metric_export_rows
resolve_parameter_names = _PUBLIC_API.dssat_io.resolve_parameter_names
resolve_dssat_case_dir = _PUBLIC_API.dssat_io.resolve_dssat_case_dir

STRATEGY_PATH = PATHS.strategy_path
EVAL_PATH = PATHS.eval_path
PROJECT_CONFIG_PATH = PATHS.project_config_path
DSSAT_TRTS_PATH = PATHS.dssat_trts_path
RUNS_DIR = PATHS.runs_dir
RUNTIME_DIR = PATHS.runtime_dir
RUNTIME_PARAMS_PATH = PATHS.runtime_params_path
RUNTIME_PEST_OUT_PATH = PATHS.runtime_pest_out_path
ARTIFACTS_DIR = PATHS.artifacts_dir
LOG_PATH = PATHS.log_path
MATRIX_LOG_PATH = PATHS.matrix_log_path
MATRIX_TSV_PATH = PATHS.matrix_tsv_path
EXPERIMENT_RUNS_TSV_PATH = PATHS.experiment_runs_tsv_path
EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH = PATHS.experiment_protocol_artifacts_tsv_path
EXPERIMENT_PARAMS_TSV_PATH = PATHS.experiment_params_tsv_path
EXPERIMENT_METRICS_LONG_TSV_PATH = PATHS.experiment_metrics_long_tsv_path
EXPERIMENT_AGGREGATE_METRICS_TSV_PATH = PATHS.experiment_aggregate_metrics_tsv_path
EXPERIMENT_SUMMARY_TSV_PATH = PATHS.experiment_summary_tsv_path
EXPERIMENT_SCATTER_1TO1_TSV_PATH = PATHS.experiment_scatter_1to1_tsv_path
EXPERIMENT_HEATMAP_WIDE_TSV_PATH = PATHS.experiment_heatmap_wide_tsv_path
EXPERIMENT_METRIC_SPLIT_HEATMAP_TSV_PATH = PATHS.experiment_metric_split_heatmap_tsv_path
EXPERIMENT_RESIDUALS_WIDE_TSV_PATH = PATHS.experiment_residuals_wide_tsv_path
EXPERIMENT_FIGURE_READY_TSV_PATH = PATHS.experiment_figure_ready_tsv_path
MAIN_MATRIX_REPORT_MD_PATH = PATHS.main_matrix_report_md_path
MAIN_MATRIX_LEADERBOARD_TSV_PATH = PATHS.main_matrix_leaderboard_tsv_path
MAIN_MATRIX_DIMENSION_SUMMARY_TSV_PATH = PATHS.main_matrix_dimension_summary_tsv_path
MAIN_MATRIX_BASELINE_SUMMARY_TSV_PATH = PATHS.main_matrix_baseline_summary_tsv_path
MAIN_MATRIX_BASELINE_DETAIL_TSV_PATH = PATHS.main_matrix_baseline_detail_tsv_path
MAIN_MATRIX_KEY_INDICATOR_TABLE_TSV_PATH = PATHS.main_matrix_key_indicator_table_tsv_path
MAIN_MATRIX_BASELINE_WINNERS_TSV_PATH = PATHS.main_matrix_baseline_winners_tsv_path
MAIN_MATRIX_METRIC_SNAPSHOT_TSV_PATH = PATHS.main_matrix_metric_snapshot_tsv_path
MAIN_MATRIX_PAPER_SUMMARY_TSV_PATH = PATHS.main_matrix_paper_summary_tsv_path
MAIN_MATRIX_PROTOCOL_OVERVIEW_TSV_PATH = PATHS.main_matrix_protocol_overview_tsv_path
MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_TSV_PATH = PATHS.main_matrix_protocol_dimension_summary_tsv_path
MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_TSV_PATH = PATHS.main_matrix_protocol_nested_dimension_summary_tsv_path
MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_TSV_PATH = PATHS.main_matrix_protocol_hotspot_summary_tsv_path
MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH = PATHS.main_matrix_protocol_reason_summary_tsv_path
MAIN_MATRIX_QUALITY_GATE_TSV_PATH = PATHS.main_matrix_quality_gate_tsv_path
MAIN_MATRIX_APPENDIX_INDEX_TSV_PATH = PATHS.main_matrix_appendix_index_tsv_path
MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH = PATHS.main_matrix_protocol_paper_table_tsv_path
MAIN_MATRIX_PAPER_MAIN_TABLE_TSV_PATH = PATHS.main_matrix_paper_main_table_tsv_path
MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH = PATHS.main_matrix_paper_appendix_table_tsv_path
MAIN_MATRIX_PAPER_TABLE_TSV_PATH = PATHS.main_matrix_paper_table_tsv_path
MAIN_MATRIX_TOPK_OVERALL_TSV_PATH = PATHS.main_matrix_topk_overall_tsv_path
MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH = PATHS.main_matrix_topk_by_engine_tsv_path
MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH = PATHS.main_matrix_topk_by_weight_tsv_path
MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH = PATHS.main_matrix_topk_by_sequence_tsv_path
MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH = PATHS.main_matrix_topk_by_grouping_tsv_path
MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH = PATHS.main_matrix_topk_validation_only_tsv_path
MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH = PATHS.main_matrix_topk_by_budget_tsv_path
MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH = PATHS.main_matrix_topk_by_validation_budget_tsv_path
MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH = PATHS.main_matrix_topk_improvement_tsv_path
PARALLEL_WORKERS_DIR = PATHS.parallel_workers_dir
CASE_TEMPLATE_DIR = PATHS.case_template_dir
CASE_SUPPORT_ROOT = PATHS.case_support_root
STANDARD_ARTIFACT_PATHS = (
    LOG_PATH,
    MATRIX_LOG_PATH,
    MATRIX_TSV_PATH,
    EXPERIMENT_RUNS_TSV_PATH,
    EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH,
    EXPERIMENT_PARAMS_TSV_PATH,
    EXPERIMENT_METRICS_LONG_TSV_PATH,
    EXPERIMENT_AGGREGATE_METRICS_TSV_PATH,
    EXPERIMENT_SUMMARY_TSV_PATH,
    EXPERIMENT_SCATTER_1TO1_TSV_PATH,
    EXPERIMENT_HEATMAP_WIDE_TSV_PATH,
    EXPERIMENT_METRIC_SPLIT_HEATMAP_TSV_PATH,
    EXPERIMENT_RESIDUALS_WIDE_TSV_PATH,
    EXPERIMENT_FIGURE_READY_TSV_PATH,
    MAIN_MATRIX_REPORT_MD_PATH,
    MAIN_MATRIX_LEADERBOARD_TSV_PATH,
    MAIN_MATRIX_DIMENSION_SUMMARY_TSV_PATH,
    MAIN_MATRIX_BASELINE_SUMMARY_TSV_PATH,
    MAIN_MATRIX_BASELINE_DETAIL_TSV_PATH,
    MAIN_MATRIX_KEY_INDICATOR_TABLE_TSV_PATH,
    MAIN_MATRIX_BASELINE_WINNERS_TSV_PATH,
    MAIN_MATRIX_METRIC_SNAPSHOT_TSV_PATH,
    MAIN_MATRIX_PAPER_SUMMARY_TSV_PATH,
    MAIN_MATRIX_PROTOCOL_OVERVIEW_TSV_PATH,
    MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_TSV_PATH,
    MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_TSV_PATH,
    MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_TSV_PATH,
    MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH,
    MAIN_MATRIX_QUALITY_GATE_TSV_PATH,
    MAIN_MATRIX_APPENDIX_INDEX_TSV_PATH,
    MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH,
    MAIN_MATRIX_PAPER_MAIN_TABLE_TSV_PATH,
    MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH,
    MAIN_MATRIX_PAPER_TABLE_TSV_PATH,
    MAIN_MATRIX_TOPK_OVERALL_TSV_PATH,
    MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH,
    MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH,
    MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH,
    MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH,
    MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH,
    MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH,
    MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH,
    MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH,
)
DATE_METRICS = {"adap", "mdap"}
COMPARABLE_METRICS = ("adap", "mdap", "laix", "cwam", "hwam", "hwum")

BENCHMARK_STRATEGIES = {
    "1_Inverse_Variance": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    var_yield = np.var(obs_yield) if np.var(obs_yield) > 0 else 1.0
    var_lai = np.var(obs_lai) if np.var(obs_lai) > 0 else 1.0
    loss_yield = np.mean((sim_yield - obs_yield)**2) / var_yield
    loss_lai = np.mean((sim_lai - obs_lai)**2) / var_lai
    return float(loss_yield + loss_lai)
""",
    "2_Inverse_RMSE": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    rmse_yield_base = np.sqrt(np.mean(obs_yield**2)) + 1e-8
    rmse_lai_base = np.sqrt(np.mean(obs_lai**2)) + 1e-8
    rmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2))
    rmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2))
    return float((rmse_y / rmse_yield_base) + (rmse_l / rmse_lai_base))
""",
    "3_CV_based_R_version": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    eps = 1e-8
    mean_y = np.mean(np.abs(obs_yield)) + eps
    mean_l = np.mean(np.abs(obs_lai)) + eps
    cv_y = np.std(obs_yield) / mean_y
    cv_l = np.std(obs_lai) / mean_l
    nrmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2)) / mean_y
    nrmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2)) / mean_l
    weight_y = 1.0 / max(cv_y, 0.05)
    weight_l = 1.0 / max(cv_l, 0.05)
    norm = weight_y + weight_l
    return float(((weight_y * nrmse_y) + (weight_l * nrmse_l)) / norm)
""",
    "4_Min_Max_Normalization": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    err_y = np.abs(sim_yield - obs_yield)
    err_l = np.abs(sim_lai - obs_lai)
    max_err_y = np.max(obs_yield) + 1e-8
    max_err_l = np.max(obs_lai) + 1e-8
    norm_y = np.mean(err_y / max_err_y)
    norm_l = np.mean(err_l / max_err_l)
    return float(norm_y + norm_l)
""",
    "5_Mean_Normalization_NRMSE": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    nrmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2)) / (np.mean(obs_yield) + 1e-8)
    nrmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2)) / (np.mean(obs_lai) + 1e-8)
    return float(nrmse_y + nrmse_l)
""",
    "6_Log_transformation": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    log_sim_y = np.log(np.clip(sim_yield, 1e-8, None))
    log_obs_y = np.log(np.clip(obs_yield, 1e-8, None))
    log_sim_l = np.log(np.clip(sim_lai, 1e-8, None))
    log_obs_l = np.log(np.clip(obs_lai, 1e-8, None))
    loss_y = np.mean((log_sim_y - log_obs_y)**2)
    loss_l = np.mean((log_sim_l - log_obs_l)**2)
    return float(loss_y + loss_l)
""",
    "7_Equal_Contribution": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    loss_y = np.mean((sim_yield - obs_yield)**2)
    loss_l = np.mean((sim_lai - obs_lai)**2)
    weight_y = 1.0 / (loss_y + 1e-8)
    weight_l = 1.0 / (loss_l + 1e-8)
    sum_w = weight_y + weight_l
    weight_y /= sum_w
    weight_l /= sum_w
    return float(weight_y * loss_y + weight_l * loss_l)
""",
    "8_AgMIP_Two_step_WLS": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    var_y = np.var(sim_yield - obs_yield) + 1e-8
    var_l = np.var(sim_lai - obs_lai) + 1e-8
    loss_y = np.mean((sim_yield - obs_yield)**2) / var_y
    loss_l = np.mean((sim_lai - obs_lai)**2) / var_l
    return float(loss_y + loss_l)
""",
    "Legacy_Pareto_Surrogate": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    nrmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2)) / (np.mean(obs_yield) + 1e-8)
    nrmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2)) / (np.mean(obs_lai) + 1e-8)
    distance = np.sqrt(nrmse_y**2 + nrmse_l**2)
    imbalance = np.abs(nrmse_y - nrmse_l)
    return float(distance + 0.5 * imbalance)
""",
}

ADDITIONAL_MODES = {
    "B0_DSSAT_Default_Params": {"AR_ENGINE": "default_dssat"},
    "W5_Scalar_NRMSE_Baseline": {"AR_WEIGHTING": "w5_mean_normalized", "AR_ENGINE": "o1_least_squares"},
    "Pure_MGDA_Baseline": {
        "AR_WEIGHTING": "w9_pareto_no_preweight",
        "AR_ENGINE": "o5_mgda",
        "AR_SEQUENCE": "s2_sequential_phase",
        "AR_GROUPING": "g3_dssat_extended",
    },
    "Native_PEST_GLM": {
        "AR_WEIGHTING": "w5_mean_normalized",
        "AR_ENGINE": "o1_least_squares",
        "AR_GROUPING": "g1_flat_all_in_one",
    },
    "Grouped_PEST_GLM": {
        "AR_WEIGHTING": "w8_dssat_group_max",
        "AR_ENGINE": "o1_least_squares",
        "AR_GROUPING": "g3_dssat_extended",
    },
}

TRANSFORMS = ("nrmse", "relative_mae", "smape", "log_rmse", "huber_rel")
AGGREGATORS = ("sum", "l2", "mean_max")
SHAPES = (1.0, 1.15, 1.35)
BALANCE_WEIGHTS = (0.0, 0.1, 0.25, 0.45)
TREATMENT_WEIGHTS = (0.0, 0.05, 0.12, 0.2)
CROSS_WEIGHTS = (0.0, 0.05, 0.12)


@dataclass(frozen=True)
class CandidateSpec:
    yield_transform: str
    lai_transform: str
    aggregator: str
    shape: float
    balance_weight: float
    treatment_weight: float
    cross_weight: float


@dataclass
class CandidateResult:
    name: str
    description: str
    score: float
    status: str
    source: str
    stdout: str
    spec: CandidateSpec | None = None
    train_score: float = float("nan")
    valid_score: float = float("nan")
    all_score: float = float("nan")
    train_mean_nrmse: float = float("nan")
    valid_mean_nrmse: float = float("nan")
    all_mean_nrmse: float = float("nan")
    yield_metric: str = ""
    valid_yield_nrmse: float = float("nan")
    valid_yield_bias: float = float("nan")
    negative_ref_score: float = float("nan")
    negative_optimization: bool = False


@dataclass(frozen=True)
class WeightCandidate:
    name: str
    description: str
    weight_mode: str
    source: str | None = None


@dataclass
class MatrixResult:
    run_id: str
    weight_name: str
    engine: str
    budget: str
    sequence: str
    grouping: str
    score: float
    status: str
    weight_mode: str
    stdout: str
    negative_ref_profile: str
    negative_ref_score: float
    train_mean_nrmse: float
    valid_mean_nrmse: float
    all_mean_nrmse: float
    yield_metric: str
    train_yield_nrmse: float
    train_yield_bias: float
    valid_yield_nrmse: float
    valid_yield_bias: float
    plan: str = ""
    executed_at: str = ""
    duration_sec: float = float("nan")
    workspace_dir: str = ""
    strategy_hash: str = ""
    eval_hash: str = ""
    auto_evolve_hash: str = ""
    max_workers: int = 1
    baseline_b0_score: float = float("nan")
    baseline_b1_score: float = float("nan")
    validation_enabled: bool = False
    train_trts: str = ""
    valid_trts: str = ""
    batch_id: str = ""
    batch_root: str = ""
    task_id: str = ""
    task_dir: str = ""
    worker_id: str = ""
    final_params: dict[str, float] = field(default_factory=dict)
    treatment_rows: list[object] = field(default_factory=list)
    aggregate_rows: list[object] = field(default_factory=list)


@dataclass(frozen=True)
class EvalExecutionResult:
    stdout: str
    stderr: str
    merged: str
    score: float
    returncode: int


_RUNNING_WORKER_PROCESSES_LOCK = threading.Lock()
_RUNNING_WORKER_PROCESSES: dict[str, subprocess.Popen[str]] = {}


def register_worker_process(worker_id: str, process: subprocess.Popen[str]) -> None:
    with _RUNNING_WORKER_PROCESSES_LOCK:
        _RUNNING_WORKER_PROCESSES[worker_id] = process


def unregister_worker_process(worker_id: str) -> None:
    with _RUNNING_WORKER_PROCESSES_LOCK:
        _RUNNING_WORKER_PROCESSES.pop(worker_id, None)


def terminate_worker_process(worker_id: str) -> bool:
    with _RUNNING_WORKER_PROCESSES_LOCK:
        process = _RUNNING_WORKER_PROCESSES.get(worker_id)
    if process is None or process.poll() is not None:
        return False
    try:
        process.terminate()
        return True
    except Exception:
        return False


EXPERIMENT_PROTOCOL_ARTIFACTS_FIELDNAMES = [
    "run_id",
    "executed_at",
    "plan",
    "weight",
    "engine",
    "budget",
    "sequence",
    "grouping",
    "status",
    "workspace_dir",
    "runtime_dir",
    "run_manifest_path",
    "contract_report_path",
    "crop",
    "filex_name",
    "trts",
    "protocol_weight",
    "protocol_engine",
    "protocol_budget",
    "protocol_sequence",
    "protocol_grouping",
    "protocol_weight_mode",
    "contract_status",
    "issue_count",
    "warning_count",
    "error_count",
    "issue_codes",
    "active_groups",
    "fallback_metrics",
    "dropped_groups",
    "weight_fallbacks",
    "zero_weight_observations",
    "requested_summary_metrics",
    "resolved_summary_metrics",
    "requested_t_vars",
    "resolved_t_vars",
    "active_metric_count",
    "active_observation_count",
    "dropped_group_count",
    "weight_fallback_count",
    "zero_weight_observation_count",
]


@dataclass(frozen=True)
class MatrixJob:
    index: int
    weight: WeightCandidate
    engine: str
    budget: str
    sequence: str
    grouping: str


MATRIX_PLAN_PRESETS: dict[str, dict[str, list[str]]] = {
    "phase0": {
        "weights": ["W8_DSSAT_PEST_Group_Max"],
        "engines": ["o1_least_squares"],
        "budgets": ["quick"],
        "sequences": ["s1_naive_joint", "s2_sequential_phase"],
        "groupings": ["g1_flat_all_in_one", "g3_dssat_extended"],
    },
    "phase1": {
        "weights": [
            "W0_Raw_Identity",
            "W1_Inverse_Variance",
            "W2_Inverse_RMSE",
            "W3_CV_Based",
            "W4_Min_Max_Equal",
            "W5_Mean_Normalization",
            "W6_Log_Transformation",
        ],
        "engines": ["o1_least_squares", "o2_pestpp_ies", "o3_anneal_nm"],
        "budgets": ["matrix"],
        "sequences": ["s1_naive_joint", "s2_sequential_phase"],
        "groupings": ["g1_flat_all_in_one", "g3_dssat_extended"],
    },
    "phase1_o1": {
        "weights": [
            "W0_Raw_Identity",
            "W1_Inverse_Variance",
            "W2_Inverse_RMSE",
            "W3_CV_Based",
            "W4_Min_Max_Equal",
            "W5_Mean_Normalization",
            "W6_Log_Transformation",
        ],
        "engines": ["o1_least_squares"],
        "budgets": ["matrix"],
        "sequences": ["s1_naive_joint", "s2_sequential_phase"],
        "groupings": ["g1_flat_all_in_one", "g3_dssat_extended"],
    },
    "phase1_o2": {
        "weights": [
            "W0_Raw_Identity",
            "W1_Inverse_Variance",
            "W2_Inverse_RMSE",
            "W3_CV_Based",
            "W4_Min_Max_Equal",
            "W5_Mean_Normalization",
            "W6_Log_Transformation",
        ],
        "engines": ["o2_pestpp_ies"],
        "budgets": ["matrix"],
        "sequences": ["s1_naive_joint", "s2_sequential_phase"],
        "groupings": ["g1_flat_all_in_one", "g3_dssat_extended"],
    },
    "phase1_o3": {
        "weights": [
            "W0_Raw_Identity",
            "W1_Inverse_Variance",
            "W2_Inverse_RMSE",
            "W3_CV_Based",
            "W4_Min_Max_Equal",
            "W5_Mean_Normalization",
            "W6_Log_Transformation",
        ],
        "engines": ["o3_anneal_nm"],
        "budgets": ["matrix"],
        "sequences": ["s1_naive_joint", "s2_sequential_phase"],
        "groupings": ["g1_flat_all_in_one", "g3_dssat_extended"],
    },
    "phase2": {
        "weights": ["W1_Inverse_Variance", "W7_Equal_Contribution", "W8_DSSAT_PEST_Group_Max"],
        "engines": ["o1_least_squares", "o2_pestpp_ies"],
        "budgets": ["quick"],
        "sequences": ["s2_sequential_phase", "s3_wls_joint"],
        "groupings": ["g3_dssat_extended"],
    },
    "phase3": {
        "weights": ["W9_Pareto_No_PreWeight"],
        "engines": ["o4_nsga2", "o5_mgda"],
        "budgets": ["quick"],
        "sequences": ["s2_sequential_phase"],
        "groupings": ["g3_dssat_extended"],
    },
    "core": {
        "weights": ["W0_Raw_Identity", "W4_Min_Max_Equal", "W6_Log_Transformation", "W7_Equal_Contribution", "W8_DSSAT_PEST_Group_Max", "W9_Pareto_No_PreWeight"],
        "engines": ["o1_least_squares", "o2_pestpp_ies", "o3_anneal_nm", "o4_nsga2"],
        "budgets": ["quick"],
        "sequences": ["s1_naive_joint", "s2_sequential_phase", "s3_wls_joint"],
        "groupings": ["g1_flat_all_in_one", "g3_dssat_extended"],
    },
    "frontier": {
        "weights": ["W1_Inverse_Variance", "W2_Inverse_RMSE", "W3_CV_Based", "W5_Mean_Normalization", "W9_Pareto_No_PreWeight"],
        "engines": ["o1_least_squares", "o2_pestpp_ies", "o3_anneal_nm", "o4_nsga2", "o5_mgda"],
        "budgets": ["quick"],
        "sequences": ["s1_naive_joint", "s2_sequential_phase", "s3_wls_joint"],
        "groupings": ["g1_flat_all_in_one", "g3_dssat_extended"],
    },
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str) -> None:
    atomic_write_text(path, content)


def migrate_legacy_root_artifacts() -> dict[Path, Path]:
    migrated: dict[Path, Path] = {}
    for standard_path in STANDARD_ARTIFACT_PATHS:
        legacy_root_path = SANDBOX_DIR / standard_path.name
        resolved_standard_path = standard_path.resolve()
        resolved_legacy_path = legacy_root_path.resolve()
        if resolved_legacy_path == resolved_standard_path or not legacy_root_path.exists():
            continue
        ensure_parent_dir(standard_path)
        if standard_path.exists():
            if standard_path.read_bytes() == legacy_root_path.read_bytes():
                legacy_root_path.unlink()
            continue
        legacy_root_path.replace(standard_path)
        migrated[resolved_legacy_path] = resolved_standard_path
    return migrated


def write_log(content: str) -> None:
    ensure_parent_dir(LOG_PATH)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(content + "\n")


def ensure_log_header() -> None:
    if not LOG_PATH.exists():
        write_text(LOG_PATH, "# Autoresearch Evolution Log\n\n")


def write_matrix_log(content: str) -> None:
    ensure_parent_dir(MATRIX_LOG_PATH)
    with MATRIX_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(content + "\n")


def ensure_matrix_header() -> None:
    if not MATRIX_LOG_PATH.exists():
        write_text(MATRIX_LOG_PATH, "# Four-Dimensional Matrix Experiments\n\n")


def extract_score(stdout: str) -> float:
    for line in stdout.splitlines():
        if "Final_Score:" not in line:
            continue
        try:
            return float(line.split(":")[-1].strip())
        except ValueError:
            break
    return 999.0


def set_eval_mode(source: str, mode: str) -> str:
    return re.sub(r'EVAL_MODE = ".*?"', f'EVAL_MODE = "{mode}"', source, count=1)


def run_eval(env_overrides: dict[str, str] | None = None) -> tuple[str, float]:
    return run_eval_in_workspace(EVAL_PATH, SANDBOX_DIR, env_overrides)


def run_eval_process_in_workspace(
    eval_path: Path,
    workspace: Path,
    env_overrides: dict[str, str] | None = None,
    heartbeat_callback: Callable[[], None] | None = None,
    heartbeat_interval_sec: float = 15.0,
    worker_id: str = "",
) -> EvalExecutionResult:
    env = os.environ.copy()
    if env_overrides:
        env.update({key: str(value) for key, value in env_overrides.items()})
    process = subprocess.Popen(
        [sys.executable, str(eval_path)],
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    if worker_id.strip():
        register_worker_process(worker_id, process)
    pulse_interval = max(0.25, float(heartbeat_interval_sec))
    last_pulse = time.monotonic()
    stdout = ""
    stderr = ""
    try:
        while process.poll() is None:
            now = time.monotonic()
            if heartbeat_callback is not None and now - last_pulse >= pulse_interval:
                heartbeat_callback()
                last_pulse = now
            time.sleep(min(0.5, pulse_interval))
        stdout, stderr = process.communicate()
    finally:
        if worker_id.strip():
            unregister_worker_process(worker_id)
    stdout = stdout or ""
    stderr = stderr or ""
    merged = stdout if not stderr else f"{stdout}\nSTDERR:\n{stderr}"
    return EvalExecutionResult(
        stdout=stdout,
        stderr=stderr,
        merged=merged,
        score=extract_score(stdout),
        returncode=int(process.returncode or 0),
    )


def run_eval_in_workspace(eval_path: Path, workspace: Path, env_overrides: dict[str, str] | None = None) -> tuple[str, float]:
    result = run_eval_process_in_workspace(eval_path, workspace, env_overrides)
    return result.merged, result.score


def reset_directory(path: Path) -> None:
    reset_runtime_directory(path)


def build_workspace_runtime_paths(workspace_dir: Path) -> tuple[Path, Path, Path]:
    runtime_dir = Path(workspace_dir).resolve() / "runs" / "runtime"
    return runtime_dir, runtime_dir / "params.dat", runtime_dir / "pest_out.dat"


def resolve_workspace_candidates(workspace_dir: Path) -> tuple[Path, ...]:
    resolved_workspace = Path(workspace_dir).resolve()
    ordered_candidates: list[Path] = []

    def append_candidate(path: Path) -> None:
        resolved_path = Path(path).resolve()
        if resolved_path not in ordered_candidates:
            ordered_candidates.append(resolved_path)

    append_candidate(resolved_workspace)
    if resolved_workspace.name == SANDBOX_DIR.name:
        append_candidate(SANDBOX_DIR)
    if resolved_workspace.parent.name == "parallel_workers":
        append_candidate(PARALLEL_WORKERS_DIR / resolved_workspace.name)
    return tuple(ordered_candidates)


def resolve_workspace_runtime_artifacts(workspace_dir_raw: str) -> tuple[Path, Path, Path, Path]:
    if not workspace_dir_raw:
        empty_path = Path()
        return empty_path, empty_path, empty_path, empty_path
    for workspace_dir in resolve_workspace_candidates(Path(workspace_dir_raw)):
        runtime_dir, _, _ = build_workspace_runtime_paths(workspace_dir)
        manifest_path = runtime_dir / "run_manifest.json"
        contract_path = runtime_dir / "contract_report.json"
        if manifest_path.exists() or contract_path.exists():
            return workspace_dir, runtime_dir, manifest_path, contract_path
    workspace_dir = resolve_workspace_candidates(Path(workspace_dir_raw))[0]
    runtime_dir, _, _ = build_workspace_runtime_paths(workspace_dir)
    return workspace_dir, runtime_dir, runtime_dir / "run_manifest.json", runtime_dir / "contract_report.json"


def prepare_matrix_workspace(job_index: int, strategy_source: str) -> Path:
    workspace = PARALLEL_WORKERS_DIR / f"job_{job_index:03d}"
    reset_directory(workspace)
    for src in (EVAL_PATH, PROJECT_CONFIG_PATH, DSSAT_TRTS_PATH):
        name = src.name
        if src.exists():
            shutil.copy2(src, workspace / name)
    case_src = preferred_case_dir()
    if case_src.exists():
        copy_case_dir_contents(case_src, workspace / "dssat_case")
    ensure_case_dir_complete(workspace / "dssat_case")
    build_workspace_runtime_paths(workspace)[0].mkdir(parents=True, exist_ok=True)
    write_text(workspace / "strategy.py", strategy_source)
    return workspace


def project_crop_name() -> str:
    env_crop = str(os.environ.get("PROJECT_CROP", "")).strip().lower()
    if env_crop:
        return env_crop
    config_name = PROJECT_CONFIG_PATH.stem.strip().lower()
    if config_name.startswith("project_"):
        return config_name[len("project_") :]
    return config_name or "unknown"


def build_matrix_batch_id(plan: str) -> str:
    normalized_plan = re.sub(r"[^a-z0-9]+", "_", str(plan).strip().lower()).strip("_") or "default"
    return f"{time.strftime('%Y%m%d_%H%M%S')}_matrix_{normalized_plan}"


def worker_case_template_dir(worker: WorkerSandboxModel) -> Path:
    return worker.root_dir / "case_template"


def initialize_worker_sandbox(worker: WorkerSandboxModel, *, reset_root: bool = True) -> WorkerSandboxModel:
    if reset_root:
        reset_directory(worker.root_dir)
    else:
        worker.root_dir.mkdir(parents=True, exist_ok=True)
    worker.logs_dir.mkdir(parents=True, exist_ok=True)
    worker.tasks_dir.mkdir(parents=True, exist_ok=True)
    worker.sandbox_dir.mkdir(parents=True, exist_ok=True)
    for src in (EVAL_PATH, PROJECT_CONFIG_PATH, DSSAT_TRTS_PATH):
        if src.exists():
            shutil.copy2(src, worker.sandbox_dir / src.name)
    case_src = preferred_case_dir()
    case_template_dir = worker_case_template_dir(worker)
    if case_src.exists():
        if reset_root or not case_template_dir.exists():
            copy_case_dir_contents(case_src, case_template_dir)
    ensure_case_dir_complete(case_template_dir)
    archive_tree(case_template_dir, worker.dssat_case_dir)
    build_workspace_runtime_paths(worker.sandbox_dir)[0].mkdir(parents=True, exist_ok=True)
    return worker


def prepare_worker_task_runtime(worker: WorkerSandboxModel, strategy_source: str) -> Path:
    case_template_dir = worker_case_template_dir(worker)
    archive_tree(case_template_dir, worker.dssat_case_dir)
    ensure_case_dir_complete(worker.dssat_case_dir)
    runtime_dir, _, _ = build_workspace_runtime_paths(worker.sandbox_dir)
    reset_directory(runtime_dir)
    write_text(worker.sandbox_dir / "strategy.py", strategy_source)
    return runtime_dir


def write_worker_status(
    task_store: TaskStoreModel,
    worker: WorkerSandboxModel,
    *,
    status: str,
    current_task_id: str = "",
    crop_affinity: str = "",
    failure_count: int = 0,
) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    payload = {
        "worker_id": worker.worker_id,
        "status": status,
        "timestamp": timestamp,
        "current_task_id": current_task_id,
        "crop_affinity": crop_affinity,
        "failure_count": failure_count,
    }
    atomic_write_json(worker.heartbeat_path, payload)
    task_store.write_worker_state(
        worker.worker_state_path,
        WorkerState(
            worker_id=worker.worker_id,
            status=status,
            sandbox_root=str(worker.sandbox_dir.resolve()),
            current_task_id=current_task_id,
            last_heartbeat_at=timestamp,
            crop_affinity=crop_affinity,
            failure_count=failure_count,
        ),
    )


def parse_worker_timestamp(timestamp: str) -> float | None:
    cleaned = str(timestamp).strip()
    if not cleaned:
        return None
    try:
        return time.mktime(time.strptime(cleaned, "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def worker_heartbeat_age_sec(worker: WorkerSandboxModel) -> float | None:
    payload = load_json_dict(worker.heartbeat_path)
    timestamp = parse_worker_timestamp(str(payload.get("timestamp", "")))
    if timestamp is None:
        return None
    return max(0.0, time.time() - timestamp)


def recover_stale_worker_task(
    task_store: TaskStoreModel,
    worker: WorkerSandboxModel,
    task_dir: Path,
    task_id: str,
    *,
    stale_timeout_sec: int,
    retry_count: int,
) -> bool:
    task_state_payload = load_json_dict(task_dir / "task_state.json")
    state = str(task_state_payload.get("state", "")).strip()
    if state not in {"assigned", "running"}:
        return False
    heartbeat_age = worker_heartbeat_age_sec(worker)
    if heartbeat_age is None or heartbeat_age < max(1, stale_timeout_sec):
        return False
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    task_store.write_task_state(
        task_dir,
        TaskStateRecord(
            task_id=task_id,
            state="stale",
            worker_id=worker.worker_id,
            assigned_at=str(task_state_payload.get("assigned_at", "")),
            started_at=str(task_state_payload.get("started_at", "")),
            finished_at=timestamp,
            retry_count=retry_count,
            error_code="E_STALE",
            error_summary=f"worker heartbeat stale after {heartbeat_age:.1f}s",
        ),
    )
    write_worker_status(
        task_store,
        worker,
        status="stale",
        current_task_id=task_id,
        crop_affinity=project_crop_name(),
        failure_count=retry_count,
    )
    task_store.write_current_task(worker.current_task_path, None)
    return True


def monitor_worker_pool(
    *,
    task_store: TaskStoreModel,
    worker_pool: list[WorkerSandboxModel],
    stale_timeout_sec: int,
    stop_event: threading.Event,
) -> None:
    poll_interval_sec = max(1.0, min(5.0, stale_timeout_sec / 4 if stale_timeout_sec > 0 else 1.0))
    while not stop_event.wait(poll_interval_sec):
        for worker in worker_pool:
            current_task_payload = load_json_dict(worker.current_task_path)
            task_id = str(current_task_payload.get("task_id", "")).strip()
            if not task_id:
                continue
            task_dir = worker.tasks_dir / task_id
            task_state_payload = load_json_dict(task_dir / "task_state.json")
            retry_count = int(task_state_payload.get("retry_count", 0) or 0)
            if recover_stale_worker_task(
                task_store,
                worker,
                task_dir,
                task_id,
                stale_timeout_sec=stale_timeout_sec,
                retry_count=retry_count,
            ):
                terminate_worker_process(worker.worker_id)


def classify_exception_error_code(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "E_IO_MISSING"
    if isinstance(exc, PermissionError):
        return "E_IO_PERMISSION"
    if isinstance(exc, TimeoutError):
        return "E_TIMEOUT"
    return "E_EXEC"


def execute_matrix_job_with_retry(
    job: MatrixJob,
    plan: str,
    negative_ref_profile: str,
    negative_ref_score: float,
    yield_metric: str,
    original_strategy: str,
    max_workers: int,
    worker_sandbox: WorkerSandboxModel | None = None,
    task_store: TaskStoreModel | None = None,
    batch_id: str = "",
    retry_limit: int = 0,
    heartbeat_interval_sec: int = 15,
    stale_timeout_sec: int = 1800,
) -> MatrixResult:
    task_id = f"task_{job.index:06d}"
    task_dir = worker_sandbox.tasks_dir / task_id if worker_sandbox is not None else None
    attempt = 0
    last_result: MatrixResult | None = None
    while attempt <= max(0, retry_limit):
        if worker_sandbox is not None and task_store is not None and task_dir is not None and attempt > 0:
            recover_stale_worker_task(
                task_store,
                worker_sandbox,
                task_dir,
                task_id,
                stale_timeout_sec=stale_timeout_sec,
                retry_count=attempt,
            )
        try:
            result = execute_matrix_job(
                job,
                plan,
                negative_ref_profile,
                negative_ref_score,
                yield_metric,
                original_strategy,
                max_workers,
                worker_sandbox=worker_sandbox,
                task_store=task_store,
                batch_id=batch_id,
                retry_index=attempt,
                heartbeat_interval_sec=heartbeat_interval_sec,
            )
        except Exception as exc:
            error_text = "".join(traceback.format_exception(exc))
            result = build_matrix_result(
                run_id=build_run_id(job),
                weight=job.weight,
                engine=job.engine,
                budget=job.budget,
                sequence=job.sequence,
                grouping=job.grouping,
                score=999.0,
                status="crash",
                stdout=error_text,
                negative_ref_profile=negative_ref_profile,
                negative_ref_score=negative_ref_score,
                yield_metric=yield_metric,
            )
            result.plan = plan
            result.executed_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            result.duration_sec = 0.0
            result.workspace_dir = str(worker_sandbox.sandbox_dir.resolve()) if worker_sandbox is not None else ""
            result.batch_id = batch_id
            result.batch_root = str(task_store.batch_root) if task_store is not None else ""
            result.task_id = task_id
            result.task_dir = str(task_dir.resolve()) if task_dir is not None else ""
            result.worker_id = worker_sandbox.worker_id if worker_sandbox is not None else ""
            result.eval_hash = sha1_of_file(EVAL_PATH)
            result.auto_evolve_hash = sha1_of_file(Path(__file__))
            result.max_workers = max_workers
            if worker_sandbox is not None and task_store is not None and task_dir is not None:
                stdout_path, stderr_path = write_task_stdout_stderr(task_dir, error_text, "")
                task_store.write_task_state(
                    task_dir,
                    TaskStateRecord(
                        task_id=task_id,
                        state="failed_fatal" if attempt >= max(0, retry_limit) else "failed_retryable",
                        worker_id=worker_sandbox.worker_id,
                        assigned_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                        retry_count=attempt,
                        error_code=classify_exception_error_code(exc),
                        error_summary=str(exc),
                    ),
                )
                task_store.write_task_result(
                    task_dir,
                    TaskResultRecord(
                        task_id=task_id,
                        status="crash",
                        exit_code=1,
                        duration_sec=0.0,
                        score=result.score,
                        stdout_path=str(stdout_path.resolve()),
                        stderr_path=str(stderr_path.resolve()),
                    ),
                )
                write_worker_status(
                    task_store,
                    worker_sandbox,
                    status="idle",
                    crop_affinity=project_crop_name(),
                    failure_count=attempt + 1,
                )
                task_store.write_current_task(worker_sandbox.current_task_path, None)
        last_result = result
        if result.status != "crash" or attempt >= max(0, retry_limit):
            return result
        if worker_sandbox is not None and task_store is not None and task_dir is not None:
            task_store.write_task_state(
                task_dir,
                TaskStateRecord(
                    task_id=task_id,
                    state="failed_retryable",
                    worker_id=worker_sandbox.worker_id,
                    assigned_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    retry_count=attempt,
                    error_code="E_RETRY",
                    error_summary=f"matrix task crash on attempt {attempt + 1}; retry will be scheduled",
                ),
            )
            task_store.write_task_state(
                task_dir,
                TaskStateRecord(
                    task_id=task_id,
                    state="retry_pending",
                    worker_id=worker_sandbox.worker_id,
                    assigned_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    retry_count=attempt + 1,
                    error_code="E_RETRY",
                    error_summary=f"matrix task retry scheduled after crash on attempt {attempt + 1}",
                ),
            )
            write_worker_status(
                task_store,
                worker_sandbox,
                status="retrying",
                current_task_id=task_id,
                crop_affinity=project_crop_name(),
                failure_count=attempt + 1,
            )
        attempt += 1
    return cast(MatrixResult, last_result)


def write_task_stdout_stderr(task_dir: Path, stdout: str, stderr: str) -> tuple[Path, Path]:
    stdout_path = task_dir / "stdout.txt"
    stderr_path = task_dir / "stderr.txt"
    write_text(stdout_path, stdout)
    write_text(stderr_path, stderr)
    return stdout_path, stderr_path


def execute_matrix_jobs_with_worker_pool(
    jobs: list[MatrixJob],
    *,
    plan: str,
    negative_ref_profile: str,
    negative_ref_score: float,
    yield_metric: str,
    original_strategy: str,
    max_workers: int,
    retry_limit: int = 0,
    batch_root_override: Path | None = None,
    batch_id_override: str = "",
    resume: bool = False,
    scheduler_config_override: SchedulerConfig | None = None,
) -> tuple[list[MatrixResult], Path, str]:
    batch_id = batch_id_override.strip() or build_matrix_batch_id(plan)
    batch_root = Path(batch_root_override).resolve() if batch_root_override is not None else (PARALLEL_WORKERS_DIR / batch_id)
    if resume:
        batch_root.mkdir(parents=True, exist_ok=True)
    else:
        reset_directory(batch_root)
    task_store = TaskStore(batch_root)
    scheduler_config = scheduler_config_override or SchedulerConfig(task_parallelism=max_workers, retry_limit=max(0, retry_limit))
    worker_pool = build_worker_pool(batch_root / "workers", scheduler_config.task_parallelism)
    existing_manifest = load_json_dict(batch_root / "batch_manifest.json") if resume else {}
    batch_spec = BatchSpec(
        batch_id=batch_id,
        batch_type="matrix",
        created_at=str(existing_manifest.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()))),
        project_root=str(SANDBOX_DIR.resolve()),
        scheduler_config=scheduler_config,
        task_count=len(jobs),
        crop_set=[project_crop_name()],
        quality_gate_mode="matrix",
        protocol_snapshot={"plan": plan},
        status="running",
    )
    task_store.write_batch_manifest(batch_spec)
    task_store.write_batch_state(
        build_batch_state_payload(
            batch_root=batch_root,
            batch_id=batch_id,
            status="running",
            total_jobs=len(jobs),
            created_at=batch_spec.created_at,
        )
    )
    for worker in worker_pool:
        initialize_worker_sandbox(worker, reset_root=not resume)
        write_worker_status(task_store, worker, status="idle", crop_affinity=project_crop_name())
        task_store.write_current_task(worker.current_task_path, None)
    buckets: list[list[MatrixJob]] = [[] for _ in worker_pool]
    for index, job in enumerate(jobs):
        buckets[index % len(worker_pool)].append(job)

    def run_worker_jobs(worker: WorkerSandboxModel, assigned_jobs: list[MatrixJob]) -> list[tuple[int, MatrixResult]]:
        results: list[tuple[int, MatrixResult]] = []
        for assigned_job in assigned_jobs:
            result = execute_matrix_job_with_retry(
                assigned_job,
                plan,
                negative_ref_profile,
                negative_ref_score,
                yield_metric,
                original_strategy,
                max_workers,
                worker_sandbox=worker,
                task_store=task_store,
                batch_id=batch_id,
                retry_limit=scheduler_config.retry_limit,
                heartbeat_interval_sec=scheduler_config.heartbeat_interval_sec,
                stale_timeout_sec=scheduler_config.stale_timeout_sec,
            )
            results.append((assigned_job.index, result))
        write_worker_status(task_store, worker, status="idle", crop_affinity=project_crop_name())
        task_store.write_current_task(worker.current_task_path, None)
        return results

    indexed_results: dict[int, MatrixResult] = {}
    monitor_stop_event = threading.Event()
    monitor_thread = threading.Thread(
        target=monitor_worker_pool,
        kwargs={
            "task_store": task_store,
            "worker_pool": worker_pool,
            "stale_timeout_sec": scheduler_config.stale_timeout_sec,
            "stop_event": monitor_stop_event,
        },
        name=f"matrix-monitor-{batch_id}",
        daemon=True,
    )
    monitor_thread.start()
    batch_status = "aggregating"
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(worker_pool)) as executor:
            future_map = {
                executor.submit(run_worker_jobs, worker, assigned_jobs): worker.worker_id
                for worker, assigned_jobs in zip(worker_pool, buckets, strict=False)
                if assigned_jobs
            }
            for future in concurrent.futures.as_completed(future_map):
                for job_index, result in future.result():
                    indexed_results[job_index] = result
    except Exception:
        batch_status = "failed"
        raise
    finally:
        monitor_stop_event.set()
        monitor_thread.join(timeout=5.0)
        task_store.write_batch_manifest(replace(batch_spec, status=batch_status))
        task_store.update_batch_state(
            **build_batch_state_payload(
                batch_root=batch_root,
                batch_id=batch_id,
                status=batch_status,
                total_jobs=len(jobs),
                results=[indexed_results[idx] for idx in sorted(indexed_results)],
                created_at=batch_spec.created_at,
            )
        )
    return [indexed_results[idx] for idx in sorted(indexed_results)], batch_root, batch_id


def strategy_hash(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]


def validate_strategy_source(source: str) -> None:
    tree = ast.parse(source)
    function_names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    if "calculate_loss" not in function_names:
        raise ValueError("strategy.py must define calculate_loss")
    banned_names = {
        "open",
        "eval",
        "exec",
        "__import__",
        "compile",
        "input",
        "subprocess",
        "pathlib",
        "os",
        "sys",
        "shutil",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {alias.name for alias in node.names}
            if names - {"numpy"}:
                raise ValueError("Only numpy imports are allowed")
        if isinstance(node, ast.ImportFrom):
            raise ValueError("from-import is not allowed in strategy.py")
        if isinstance(node, ast.Name) and node.id in banned_names:
            raise ValueError(f"Banned symbol found: {node.id}")
    namespace: dict[str, object] = {}
    exec(compile(tree, str(STRATEGY_PATH), "exec"), namespace)
    fn = cast(Callable[[object, object, object, object], object], namespace["calculate_loss"])
    np_module = cast(Any, namespace["np"])
    raw_score = fn(
            np_module.array([10.0, 12.0, 15.0]),
            np_module.array([9.0, 11.0, 14.0]),
            np_module.array([1.2, 1.6, 2.0]),
            np_module.array([1.1, 1.5, 2.2]),
        )
    score = float(cast(float, raw_score))
    if not np_module.isfinite(score):
        raise ValueError("calculate_loss returned a non-finite value")


def parse_csv_arg(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]


def project_crop_profile():
    config = load_project_config()
    resolved_case_dir = resolve_dssat_case_dir(MVP_ROOT, cfg=config) if isinstance(config.get("paths", {}), dict) else None
    return _CROP_REGISTRY_MODULE.resolve_crop_profile_from_context(config, resolved_case_dir)


def resolve_config_case_path(cfg: dict, raw_path: str) -> Path:
    candidate = Path(str(raw_path).strip())
    if candidate.is_absolute():
        return candidate
    return resolve_dssat_case_dir(MVP_ROOT, cfg=cfg) / candidate


def phase_sequences_for_plan(plan: str) -> list[str]:
    configured = list(_CROP_REGISTRY_MODULE.resolve_phase_template(load_project_config(), plan))
    if configured:
        return configured
    preset = MATRIX_PLAN_PRESETS.get(plan, {})
    return list(preset.get("sequences", []))


def resolve_report_registry_profile_summary(
    report_plan: str,
    leaderboard_rows: list[dict[str, str]],
) -> tuple[str, str, str, str]:
    profile = project_crop_profile()
    config = load_project_config()
    plan_sequences = phase_sequences_for_plan(report_plan)
    if not plan_sequences:
        plan_sequences = sorted(
            {
                str(row.get("sequence", "")).strip()
                for row in leaderboard_rows
                if str(row.get("sequence", "")).strip()
            }
        )
    default_groupings = [
        f"{sequence}:{_CROP_REGISTRY_MODULE.resolve_default_grouping(config, sequence)}"
        for sequence in plan_sequences
    ]
    return (
        profile.family,
        profile.resolved_display_name(),
        ",".join(plan_sequences) if plan_sequences else "all",
        ",".join(default_groupings) if default_groupings else "n/a",
    )


def resolve_matrix_scope(
    plan: str,
    weights: list[str],
    engines: list[str],
    budgets: list[str],
    sequences: list[str],
    groupings: list[str],
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    if plan == "custom":
        return weights, engines, budgets, sequences, groupings
    preset = MATRIX_PLAN_PRESETS[plan]
    resolved_sequences = phase_sequences_for_plan(plan) or list(preset["sequences"])
    return (
        list(preset["weights"]),
        list(preset["engines"]),
        list(preset["budgets"]),
        resolved_sequences,
        list(preset["groupings"]),
    )


def plan_allows_cell(plan: str, weight_mode: str, sequence: str, grouping: str) -> bool:
    if grouping not in compatible_groupings_for_sequence(sequence):
        return False
    plan_sequences = phase_sequences_for_plan(plan)
    if plan_sequences and sequence not in plan_sequences:
        return False
    if plan == "phase0":
        return (sequence, grouping) in {
            ("s1_naive_joint", "g1_flat_all_in_one"),
            ("s2_sequential_phase", "g3_dssat_extended"),
        }
    if plan == "phase2":
        if weight_mode == "w8_dssat_group_max":
            return sequence == "s2_sequential_phase" and grouping == "g3_dssat_extended"
        if weight_mode == "w7_equal_contribution":
            return grouping == "g3_dssat_extended" and sequence in {"s2_sequential_phase", "s3_wls_joint"}
        if weight_mode == "w1_inverse_variance":
            return sequence == "s3_wls_joint" and grouping == "g3_dssat_extended"
    if plan == "phase3":
        return sequence == "s2_sequential_phase" and grouping == "g3_dssat_extended"
    return True


WEIGHT_NAME_ALIASES = {
    "2_Inverse_RMSE": "W2_Inverse_RMSE",
    "3_CV_based_R_version": "W3_CV_Based",
    "4_Min_Max_Normalization": "W4_Min_Max_Equal",
    "5_Mean_Normalization_NRMSE": "W5_Mean_Normalization",
    "6_Log_transformation": "W6_Log_Transformation",
    "7_Equal_Contribution": "W7_Equal_Contribution",
    "8_AgMIP_Two_step_WLS": "W8_DSSAT_PEST_Group_Max",
    "9_Pareto_Dominance": "W9_Pareto_No_PreWeight",
    "Pure_MGDA_Baseline": "W9_Pareto_No_PreWeight",
}


def default_matrix_weights(current_source: str) -> list[WeightCandidate]:
    return [
        WeightCandidate("Current_AI_Winner", "current strategy.py winner", "w_custom_strategy", current_source),
        WeightCandidate("W0_Raw_Identity", "doc W0 raw-identity baseline", "w0_raw_identity", None),
        WeightCandidate("W1_Inverse_Variance", "doc W1 inverse-variance weighting", "w1_inverse_variance", None),
        WeightCandidate("W2_Inverse_RMSE", "doc W2 inverse-RMSE dynamic weighting", "w_custom_strategy", BENCHMARK_STRATEGIES["2_Inverse_RMSE"]),
        WeightCandidate("W3_CV_Based", "doc W3 CV-based relative-volatility weighting", "w_custom_strategy", BENCHMARK_STRATEGIES["3_CV_based_R_version"]),
        WeightCandidate("W4_Min_Max_Equal", "doc W4 min-max equalized loss", "w_custom_strategy", BENCHMARK_STRATEGIES["4_Min_Max_Normalization"]),
        WeightCandidate("W5_Mean_Normalization", "doc W5 mean-normalized NRMSE baseline", "w5_mean_normalized", None),
        WeightCandidate("W6_Log_Transformation", "doc W6 log-space variance-stabilized loss", "w_custom_strategy", BENCHMARK_STRATEGIES["6_Log_transformation"]),
        WeightCandidate("W7_Equal_Contribution", "doc W7 equal-contribution / PWTADJ1", "w7_equal_contribution", None),
        WeightCandidate("W8_DSSAT_PEST_Group_Max", "doc W8 DSSAT-PEST group-max scaling", "w8_dssat_group_max", None),
        WeightCandidate("W9_Pareto_No_PreWeight", "doc W9 true multi-objective without pre-weighting", "w9_pareto_no_preweight", None),
        WeightCandidate("Legacy_Pareto_Surrogate", "legacy scalar Pareto surrogate, not formal W9", "w_custom_strategy", BENCHMARK_STRATEGIES["Legacy_Pareto_Surrogate"]),
    ]


def select_weight_candidates(names: list[str], current_source: str) -> list[WeightCandidate]:
    catalog = {candidate.name: candidate for candidate in default_matrix_weights(current_source)}
    selected: list[WeightCandidate] = []
    for name in names:
        canonical_name = WEIGHT_NAME_ALIASES.get(name, name)
        if canonical_name not in catalog:
            raise ValueError(f"Unknown matrix weight candidate: {name}")
        selected.append(catalog[canonical_name])
    return selected


def normalize_sequence_name(sequence: str) -> str:
    mapping = {
        "joint": "s1_naive_joint",
        "agmip_two_step": "s3_wls_joint",
    }
    return mapping.get(sequence, sequence)


def normalize_engine_name(engine: str) -> str:
    mapping = {
        "anneal_nm": "o3_anneal_nm",
        "powell": "o3_powell",
        "pest_glm_native": "o1_least_squares",
        "pest_glm_grouped": "o1_least_squares",
    }
    return mapping.get(engine, engine)


def infer_grouping(sequence: str, weight_mode: str) -> str:
    if weight_mode == "w8_dssat_group_max":
        return "g3_dssat_extended"
    if sequence == "s1_naive_joint":
        return "g1_flat_all_in_one"
    return "g3_dssat_extended"


def normalize_weight_mode_name(mode: str) -> str:
    mapping = {
        "weighted": "w_custom_strategy",
        "pure_mgda": "w5_mean_normalized",
        "pest_glm_native": "w5_mean_normalized",
        "pest_glm_grouped": "w8_dssat_group_max",
        "w0": "w0_raw_identity",
        "w1": "w1_inverse_variance",
        "w5": "w5_mean_normalized",
        "w7": "w7_equal_contribution",
        "w8": "w8_dssat_group_max",
    }
    return mapping.get(mode, mode)


def load_project_config() -> dict:
    with PROJECT_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _coerce_scheduler_int(value: Any, default: int, *, minimum: int) -> int:
    if value is None or value == "":
        return default
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, resolved)


def _coerce_scheduler_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def resolve_scheduler_config(
    cfg: dict[str, Any] | None = None,
    *,
    max_workers: int | None = None,
    retry_limit: int | None = None,
) -> tuple[SchedulerConfig, str]:
    project_cfg = cfg if cfg is not None else load_project_config()
    scheduler_payload_raw = project_cfg.get("scheduler", {})
    scheduler_payload = scheduler_payload_raw if isinstance(scheduler_payload_raw, dict) else {}
    source = "defaults"
    if scheduler_payload:
        source = "project_config"
    task_parallelism = _coerce_scheduler_int(scheduler_payload.get("task_parallelism"), 1, minimum=1)
    crop_parallelism = _coerce_scheduler_int(scheduler_payload.get("crop_parallelism"), 1, minimum=1)
    resolved_retry_limit = _coerce_scheduler_int(scheduler_payload.get("retry_limit"), 0, minimum=0)
    heartbeat_interval_sec = _coerce_scheduler_int(scheduler_payload.get("heartbeat_interval_sec"), 15, minimum=1)
    stale_timeout_sec = _coerce_scheduler_int(scheduler_payload.get("stale_timeout_sec"), 1800, minimum=1)
    sandbox_reuse = _coerce_scheduler_bool(scheduler_payload.get("sandbox_reuse"), True)
    copy_case_once = _coerce_scheduler_bool(scheduler_payload.get("copy_case_once"), True)
    aggregate_write_mode = str(scheduler_payload.get("aggregate_write_mode", "single_writer")).strip() or "single_writer"
    override_keys: list[str] = []
    if max_workers is not None:
        task_parallelism = max(1, int(max_workers))
        override_keys.append("max_workers")
    if retry_limit is not None:
        resolved_retry_limit = max(0, int(retry_limit))
        override_keys.append("retry_limit")
    if override_keys:
        source = f"{source}+cli:{','.join(override_keys)}"
    return (
        SchedulerConfig(
            task_parallelism=task_parallelism,
            crop_parallelism=crop_parallelism,
            retry_limit=resolved_retry_limit,
            heartbeat_interval_sec=heartbeat_interval_sec,
            stale_timeout_sec=stale_timeout_sec,
            sandbox_reuse=sandbox_reuse,
            copy_case_once=copy_case_once,
            aggregate_write_mode=aggregate_write_mode,
        ),
        source,
    )


PROJECT_CONFIG = load_project_config()
FINAL_PARAM_NAMES = tuple(resolve_parameter_names(PROJECT_CONFIG))


def sha1_of_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def format_float_tsv(value: float) -> str:
    return f"{value:.6f}" if math.isfinite(value) else ""


def ensure_tsv_header(path: Path, expected_header: str) -> None:
    if not path.exists():
        write_text(path, expected_header + "\n")
        return
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        write_text(path, expected_header + "\n")
        return
    if lines[0].strip() == expected_header:
        return
    remaining = lines[1:] if len(lines) > 1 else []
    payload = "\n".join(remaining)
    if payload:
        write_text(path, expected_header + "\n" + payload + "\n")
        return
    write_text(path, expected_header + "\n")


def parse_named_list(stdout: str, key: str) -> list[str]:
    prefix = f"{key}:"
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        return [item.strip().lower() for item in line.split(":", 1)[1].split(",") if item.strip()]
    return []


def parse_final_parameters(stdout: str) -> dict[str, float]:
    params: dict[str, float] = {}
    capture = False
    for raw_line in stdout.splitlines():
        line = raw_line.rstrip()
        if line.strip() == "Final Parameters:":
            capture = True
            continue
        if not capture:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if not line.startswith("  ") or ":" not in stripped:
            break
        name, value = stripped.split(":", 1)
        try:
            params[name.strip().lower()] = float(value.strip())
        except ValueError:
            continue
    return params


def load_planting_doy(cfg: dict) -> int:
    filex_name = str(cfg.get("scenario", {}).get("filex", "")).strip()
    case_dir = str(cfg.get("paths", {}).get("dssat_case_dir", "")).strip()
    if not filex_name or not case_dir:
        raise RuntimeError("Missing FileX path needed to derive planting date")
    filex_path = resolve_config_case_path(cfg, filex_name)
    lines = filex_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = None
    for line in lines:
        if line.startswith("@P "):
            header = line
            continue
        if header and line.strip() and not line.startswith("*") and not line.startswith("@") and not line.lstrip().startswith("!"):
            cols = [col.lstrip("@").strip().upper() for col in header.split()]
            parts = line.split()
            if "PDATE" not in cols:
                break
            idx = cols.index("PDATE")
            if len(parts) <= idx:
                break
            return int(int(parts[idx]) % 1000)
    raise RuntimeError(f"Could not derive planting date from {filex_path}")


def observation_metric_candidates(cfg: dict) -> dict[str, list[str]]:
    metrics_cfg = cfg.get("metrics", {}) or cfg.get("variables", {}) or {}
    yield_code = str(metrics_cfg.get("yield_var", "HWAM")).strip().upper() or "HWAM"
    laix_code = str(metrics_cfg.get("laix_var", "")).strip().upper()
    return {
        "hwam": [yield_code, "HWAM", "PWAM", "PWAD"],
        "hwum": ["HWUM"],
        "cwam": ["CWAM", "CWAD"],
        "laix": [laix_code, "LAIX", "LAID"],
        "adap": ["ADAT"],
        "mdap": ["MDAT"],
    }


def load_t_file_metric_fallbacks(cfg: dict, trts: list[int]) -> tuple[ComparableMetricValues, ComparableMetricDates]:
    t_path_raw = str(cfg.get("paths", {}).get("obs_t_path", "")).strip() or str(cfg.get("paths", {}).get("wht_path", "")).strip()
    empty_values: ComparableMetricValues = {metric: {} for metric in COMPARABLE_METRICS}
    empty_dates: ComparableMetricDates = {metric: {} for metric in COMPARABLE_METRICS}
    if not t_path_raw:
        return empty_values, empty_dates
    t_path = resolve_config_case_path(cfg, t_path_raw)
    if not t_path.exists():
        return empty_values, empty_dates
    lines = t_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = next((line for line in lines if line.startswith("@TRNO")), "")
    if not header:
        return empty_values, empty_dates
    cols = [col.lstrip("@").strip().upper() for col in header.split()]
    if "TRNO" not in cols:
        return empty_values, empty_dates
    idx_trno = cols.index("TRNO")
    idx_date = cols.index("DATE") if "DATE" in cols else -1
    planting_doy = load_planting_doy(cfg)
    candidate_codes = observation_metric_candidates(cfg)
    col_map = {}
    used_cols = set()
    for metric_name in COMPARABLE_METRICS:
        for code in candidate_codes.get(metric_name, []):
            code_u = str(code).strip().upper()
            if not code_u or code_u in used_cols or code_u not in cols:
                continue
            col_map[metric_name] = cols.index(code_u)
            used_cols.add(code_u)
            break
    trt_set = {int(trt) for trt in trts}
    metrics: ComparableMetricValuesWithDates = {metric: {} for metric in COMPARABLE_METRICS}
    metric_dates: ComparableMetricDates = {metric: {} for metric in COMPARABLE_METRICS}
    for line in lines:
        if not line.strip() or line.startswith("@") or line.startswith("*") or line.lstrip().startswith("!"):
            continue
        parts = line.split()
        if len(parts) <= idx_trno:
            continue
        try:
            trt = int(parts[idx_trno])
        except ValueError:
            continue
        if trt not in trt_set:
            continue
        date = None
        if idx_date >= 0 and len(parts) > idx_date:
            try:
                date = int(parts[idx_date])
            except ValueError:
                date = None
        for metric_name, idx_col in col_map.items():
            if len(parts) <= idx_col:
                continue
            try:
                raw_value = float(parts[idx_col])
            except ValueError:
                continue
            if raw_value == -99.0:
                continue
            value = raw_value - float(planting_doy) if metric_name in DATE_METRICS and raw_value > 0.0 else raw_value
            current = metrics[metric_name].get(trt)
            current_date = current[0] if current is not None else None
            resolved_date = int(date) if date is not None else -1
            if current_date is None or resolved_date >= current_date:
                metrics[metric_name][trt] = (resolved_date, float(value))
            if date is not None:
                metric_dates[metric_name].setdefault(trt, []).append(int(date))
    resolved_metrics: ComparableMetricValues = {
        metric: {int(trt): float(value) for trt, (_, value) in values.items()}
        for metric, values in metrics.items()
    }
    resolved_dates: ComparableMetricDates = {
        metric: {int(trt): sorted(set(int(date) for date in dates)) for trt, dates in values.items()}
        for metric, values in metric_dates.items()
    }
    return resolved_metrics, resolved_dates


def load_project_observations(cfg: dict, trts: list[int]) -> dict[str, dict[int, float]]:
    a_path_raw = str(cfg.get("paths", {}).get("obs_a_path", "")).strip() or str(cfg.get("paths", {}).get("wha_path", "")).strip()
    a_path = resolve_config_case_path(cfg, a_path_raw)
    lines = a_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = next((line for line in lines if line.startswith("@TRNO")), "")
    if not header:
        raise RuntimeError(f"Missing @TRNO header in {a_path}")
    cols = [col.lstrip("@").strip().upper() for col in header.split()]
    planting_doy = load_planting_doy(cfg)
    candidate_codes = observation_metric_candidates(cfg)
    yield_code = str(candidate_codes["hwam"][0]).strip().upper()
    col_map = {}
    used_cols = set()
    for metric_name in ("hwam", "hwum", "cwam", "laix", "adap", "mdap"):
        for code in candidate_codes.get(metric_name, []):
            code_u = str(code).strip().upper()
            if not code_u or code_u in used_cols or code_u not in cols:
                continue
            col_map[metric_name] = cols.index(code_u)
            used_cols.add(code_u)
            break
    idx_trno = cols.index("TRNO")
    if "hwam" not in col_map:
        raise RuntimeError(f"Observation A-file missing configured yield column {yield_code}: {a_path}")
    trt_set = {int(trt) for trt in trts}
    metrics: dict[str, dict[int, float]] = {metric: {} for metric in COMPARABLE_METRICS}
    for line in lines:
        if not line.strip() or line.startswith("@") or line.startswith("*") or line.lstrip().startswith("!"):
            continue
        parts = line.split()
        if len(parts) <= max([idx_trno] + list(col_map.values())):
            continue
        try:
            trt = int(parts[idx_trno])
        except ValueError:
            continue
        if trt not in trt_set:
            continue
        for metric_name, idx_col in col_map.items():
            try:
                raw_value = float(parts[idx_col])
            except ValueError:
                continue
            if metric_name in DATE_METRICS and raw_value > 0.0:
                metrics[metric_name][trt] = raw_value - float(planting_doy)
            else:
                metrics[metric_name][trt] = raw_value
    t_metrics, _ = load_t_file_metric_fallbacks(cfg, trts)
    for metric_name, values_by_trt in t_metrics.items():
        for trt, value in values_by_trt.items():
            metrics.setdefault(metric_name, {})
            metrics[metric_name].setdefault(int(trt), float(value))
    return metrics


def resolve_project_split(cfg: dict, trts: list[int]) -> dict[int, str]:
    split_cfg = cfg.get("split", {})
    mode = str(split_cfg.get("mode", "trt")).strip().lower()
    train = {int(t) for t in (split_cfg.get("train_trts") or []) if str(t).strip()}
    valid = {int(t) for t in (split_cfg.get("valid_trts") or []) if str(t).strip()}
    ratio = None
    if "valid_ratio" in split_cfg:
        try:
            ratio = float(split_cfg.get("valid_ratio"))
        except (TypeError, ValueError):
            ratio = None
    if ratio is None and not train and not valid and len(trts) > 1:
        ratio = 0.2
    if mode in {"ratio", "random"} and ratio is None:
        ratio = 0.2
    if ratio is not None and not train and not valid and trts:
        ratio = max(0.0, min(1.0, float(ratio)))
        if ratio > 0.0:
            rnd = random.Random(int(split_cfg.get("seed", split_cfg.get("random_seed", 0))))
            shuffled = list(trts)
            rnd.shuffle(shuffled)
            n_valid = max(1, int(round(len(shuffled) * ratio)))
            valid = set(shuffled[:n_valid])
            train = set(shuffled[n_valid:])
    if not train and not valid:
        train = set(trts)
    else:
        if not train:
            train = set(trts) - valid
        if not valid:
            valid = set(trts) - train
    overlap = train & valid
    if overlap:
        train -= overlap
    return {int(trt): ("valid" if int(trt) in valid else "train") for trt in trts}


def project_observation_bundle() -> tuple[list[int], dict[int, str], dict[str, dict[int, float]]]:
    cache = getattr(project_observation_bundle, "_cache", None)
    if cache is not None:
        return cache
    cfg = load_project_config()
    trts = [int(t) for t in cfg.get("scenario", {}).get("trts", [1, 2, 8, 9, 13, 14])]
    split_by_trt = resolve_project_split(cfg, trts)
    obs_metrics = load_project_observations(cfg, trts)
    bundle = (trts, split_by_trt, obs_metrics)
    setattr(project_observation_bundle, "_cache", bundle)
    return bundle


def normalize_metric_value(metric_name: str, value: float) -> float:
    if metric_name in DATE_METRICS and math.isfinite(value) and abs(value) >= 1000.0:
        return float(int(round(value)) % 1000)
    return float(value)


def load_simulated_metrics(pest_out_path: Path) -> ComparableMetricValues:
    metrics_raw: dict[str, dict[int, float | tuple[int, float]]] = {metric: {} for metric in COMPARABLE_METRICS}
    if not pest_out_path.exists():
        return {metric: {} for metric in COMPARABLE_METRICS}
    cfg = load_project_config()
    trts = [int(t) for t in cfg.get("scenario", {}).get("trts", [1, 2, 8, 9, 13, 14])]
    _, metric_dates = load_t_file_metric_fallbacks(cfg, trts)
    candidate_codes = {
        metric_name: [str(code).strip().lower() for code in codes if str(code).strip()]
        for metric_name, codes in observation_metric_candidates(cfg).items()
    }
    pattern = re.compile(r"^(?P<metric>[a-z0-9]+)_t(?P<trt>\d+)(?:_(?P<suffix>\S+))?\s+(?P<value>[-+0-9.eE]+)")
    for raw_line in pest_out_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        metric_name = match.group("metric").lower()
        try:
            trt = int(match.group("trt"))
            value = float(match.group("value"))
        except ValueError:
            continue
        suffix = str(match.group("suffix") or "").strip().lower()
        for comparable_metric, aliases in candidate_codes.items():
            if metric_name not in aliases:
                continue
            if not suffix:
                metrics_raw[comparable_metric][trt] = normalize_metric_value(comparable_metric, value)
                continue
            expected_dates = set(metric_dates.get(comparable_metric, {}).get(int(trt), []))
            if suffix.startswith("d"):
                try:
                    metric_date = int(suffix[1:])
                except ValueError:
                    continue
                if metric_date in expected_dates:
                    current = metrics_raw[comparable_metric].get(trt)
                    current_date = current[0] if isinstance(current, tuple) else None
                    if current_date is None or metric_date >= current_date:
                        metrics_raw[comparable_metric][trt] = (metric_date, normalize_metric_value(comparable_metric, value))
    metrics: ComparableMetricValues = {}
    for metric_name, values_by_trt in metrics_raw.items():
        metrics[metric_name] = {
            int(trt): float(value[1] if isinstance(value, tuple) else value)
            for trt, value in values_by_trt.items()
        }
    return metrics


def build_treatment_metric_rows(
    run_id: str,
    plan: str,
    weight_name: str,
    engine: str,
    budget: str,
    sequence: str,
    grouping: str,
    status: str,
    stdout: str,
    workspace_dir: str,
) -> list[object]:
    trts, split_by_trt, obs_metrics = project_observation_bundle()
    evaluation_result = extract_evaluation_result(stdout)
    metric_names = parse_named_list(stdout, "Comparable_Metrics") or list(COMPARABLE_METRICS)
    export_context = build_experiment_export_context(
        run_id=run_id,
        plan=plan,
        weight_name=weight_name,
        engine=engine,
        budget=budget,
        sequence=sequence,
        grouping=grouping,
        status=status,
    )
    if evaluation_result is not None:
        result_comparison_records = build_treatment_comparison_records(
            evaluation_result,
            {
                trt: {
                    metric_name: float(metric_values[trt])
                    for metric_name, metric_values in obs_metrics.items()
                    if trt in metric_values
                }
                for trt in trts
            },
            split_by_trt,
            comparable_metrics=(
                list(evaluation_result.comparable_metrics)
                if evaluation_result.comparable_metrics
                else metric_names
            ),
        )
        return build_treatment_metric_export_rows(export_context, result_comparison_records)
    _, _, pest_out_path = build_workspace_runtime_paths(Path(workspace_dir))
    sim_metrics = load_simulated_metrics(pest_out_path)
    comparison_records: list[object] = []
    for metric_name in metric_names:
        obs_by_trt = obs_metrics.get(metric_name, {})
        sim_by_trt = sim_metrics.get(metric_name, {})
        for trt in trts:
            obs_value = obs_by_trt.get(trt)
            sim_value = sim_by_trt.get(trt)
            if obs_value is None or sim_value is None or not math.isfinite(sim_value):
                continue
            error = sim_value - obs_value
            abs_error = abs(error)
            relative_error = abs_error / (abs(obs_value) + 1e-8)
            comparison_records.append(
                TreatmentComparisonRecord(
                    trt=int(trt),
                    split=split_by_trt.get(trt, "train"),
                    metric=metric_name,
                    observed=float(obs_value),
                    simulated=float(sim_value),
                    error=float(error),
                    abs_error=float(abs_error),
                    relative_error=float(relative_error),
                )
            )
    return build_treatment_metric_export_rows(export_context, comparison_records)


def build_aggregate_metric_rows(
    run_id: str,
    plan: str,
    weight_name: str,
    engine: str,
    budget: str,
    sequence: str,
    grouping: str,
    status: str,
    stdout: str,
) -> list[object]:
    evaluation_result = extract_evaluation_result(stdout)
    if evaluation_result is None:
        return []
    export_context = build_experiment_export_context(
        run_id=run_id,
        plan=plan,
        weight_name=weight_name,
        engine=engine,
        budget=budget,
        sequence=sequence,
        grouping=grouping,
        status=status,
    )
    return build_aggregate_metric_export_rows(export_context, evaluation_result.aggregate_metrics)


def project_yield_metric() -> str:
    metrics = load_project_config().get("metrics", {})
    return str(metrics.get("yield_var", "HWAM")).strip().upper()


def negative_optimization_reference_profile() -> str:
    baselines = load_project_config().get("baselines", {})
    return str(baselines.get("negative_optimization_reference", "b0_official_frozen")).strip() or "b0_official_frozen"


def baseline_env_for_profile(profile_name: str) -> dict[str, str]:
    profile = profile_name.strip().lower()
    if profile == "b0_official_frozen":
        return {"AR_ENGINE": "default_dssat", "AR_BASELINE_PARAM_SOURCE": "external"}
    if profile == "b1_sandbox_feasible":
        return {"AR_ENGINE": "default_dssat", "AR_BASELINE_PARAM_SOURCE": "clipped"}
    raise ValueError(f"Unsupported baseline profile for sandbox runtime: {profile_name}")


def parse_named_float(stdout: str, key: str) -> float:
    prefix = f"{key}:"
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        try:
            return float(line.split(":", 1)[1].strip())
        except ValueError:
            return float("nan")
    return float("nan")


def build_candidate_result(
    name: str,
    description: str,
    score: float,
    status: str,
    source: str,
    stdout: str,
    negative_ref_score: float | None = None,
) -> CandidateResult:
    yield_metric = project_yield_metric()
    summary_view = extract_matrix_summary_view(stdout, yield_metric)
    reference_score = float("nan") if negative_ref_score is None else float(negative_ref_score)
    negative_optimization = bool(score > reference_score) if reference_score == reference_score else False
    return CandidateResult(
        name=name,
        description=description,
        score=score,
        status=status,
        source=source,
        stdout=stdout,
        train_score=summary_view.train_mean_nrmse if summary_view is not None else parse_named_float(stdout, "Final_Train_Score"),
        valid_score=summary_view.valid_mean_nrmse if summary_view is not None else parse_named_float(stdout, "Final_Valid_Score"),
        all_score=summary_view.all_mean_nrmse if summary_view is not None else parse_named_float(stdout, "Final_All_Score"),
        train_mean_nrmse=summary_view.train_mean_nrmse if summary_view is not None else parse_named_float(stdout, "TRAIN_MEAN_NRMSE"),
        valid_mean_nrmse=summary_view.valid_mean_nrmse if summary_view is not None else parse_named_float(stdout, "VALID_MEAN_NRMSE"),
        all_mean_nrmse=summary_view.all_mean_nrmse if summary_view is not None else parse_named_float(stdout, "ALL_MEAN_NRMSE"),
        yield_metric=yield_metric,
        valid_yield_nrmse=summary_view.valid_primary_nrmse if summary_view is not None else parse_named_float(stdout, f"VALID_{yield_metric}_NRMSE"),
        valid_yield_bias=summary_view.valid_primary_bias if summary_view is not None else parse_named_float(stdout, f"VALID_{yield_metric}_BIAS"),
        negative_ref_score=reference_score,
        negative_optimization=negative_optimization,
    )


def ensure_matrix_tsv_schema() -> None:
    expected_header = (
        "weight\tengine\tbudget\tsequence\tgrouping\tweight_mode\tscore\tstatus\t"
        "negative_ref_profile\tnegative_ref_score\ttrain_mean_nrmse\tvalid_mean_nrmse\tall_mean_nrmse\t"
        "yield_metric\ttrain_yield_nrmse\ttrain_yield_bias\tvalid_yield_nrmse\tvalid_yield_bias"
    )
    if not MATRIX_TSV_PATH.exists():
        write_text(MATRIX_TSV_PATH, expected_header + "\n")
        return
    lines = MATRIX_TSV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        write_text(MATRIX_TSV_PATH, expected_header + "\n")
        return
    if lines[0].strip() == expected_header:
        return
    migrated = [expected_header]
    for raw in lines[1:]:
        parts = raw.split("\t")
        if len(parts) == 18:
            migrated.append(raw)
            continue
        if len(parts) != 7:
            if len(parts) != 8:
                continue
            weight_name, optimizer, budget, sequence, grouping, eval_mode, score, status = parts
        else:
            weight_name, optimizer, budget, sequence, eval_mode, score, status = parts
            sequence_name = normalize_sequence_name(sequence)
            eval_mode = normalize_weight_mode_name(eval_mode)
            grouping = infer_grouping(sequence_name, eval_mode)
            migrated.append(
                "\t".join(
                    [
                        weight_name,
                        normalize_engine_name(optimizer),
                        budget,
                        sequence_name,
                        grouping,
                        eval_mode,
                        score,
                        status,
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                    ]
                )
            )
            continue
        sequence_name = normalize_sequence_name(sequence)
        weight_mode = normalize_weight_mode_name(eval_mode)
        migrated.append(
            "\t".join(
                [
                    weight_name,
                    normalize_engine_name(optimizer),
                    budget,
                    sequence_name,
                    grouping,
                    weight_mode,
                    score,
                    status,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
        )
    write_text(MATRIX_TSV_PATH, "\n".join(migrated) + "\n")


def append_matrix_tsv(result: MatrixResult) -> None:
    ensure_matrix_tsv_schema()
    with MATRIX_TSV_PATH.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{result.weight_name}\t{result.engine}\t{result.budget}\t{result.sequence}\t"
            f"{result.grouping}\t{result.weight_mode}\t{result.score:.6f}\t{result.status}\t"
            f"{result.negative_ref_profile}\t{result.negative_ref_score:.6f}\t"
            f"{result.train_mean_nrmse:.6f}\t{result.valid_mean_nrmse:.6f}\t{result.all_mean_nrmse:.6f}\t"
            f"{result.yield_metric}\t{result.train_yield_nrmse:.6f}\t{result.train_yield_bias:.6f}\t"
            f"{result.valid_yield_nrmse:.6f}\t{result.valid_yield_bias:.6f}\n"
        )


def ensure_experiment_runs_tsv_schema() -> None:
    expected_header = (
        "run_id\texecuted_at\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tweight_mode\tstatus\t"
        "score\tnegative_ref_profile\tnegative_ref_score\tbaseline_b0_score\tbaseline_b1_score\t"
        "yield_metric\ttrain_mean_nrmse\tvalid_mean_nrmse\tall_mean_nrmse\t"
        "train_yield_nrmse\ttrain_yield_bias\tvalid_yield_nrmse\tvalid_yield_bias\t"
        "duration_sec\tmax_workers\tvalidation_enabled\ttrain_trts\tvalid_trts\t"
        "workspace_dir\tstrategy_hash\teval_hash\tauto_evolve_hash"
    )
    ensure_tsv_header(EXPERIMENT_RUNS_TSV_PATH, expected_header)


def append_experiment_runs_tsv(result: MatrixResult) -> None:
    ensure_experiment_runs_tsv_schema()
    fields = [
        result.run_id,
        result.executed_at,
        result.plan,
        result.weight_name,
        result.engine,
        result.budget,
        result.sequence,
        result.grouping,
        result.weight_mode,
        result.status,
        format_float_tsv(result.score),
        result.negative_ref_profile,
        format_float_tsv(result.negative_ref_score),
        format_float_tsv(result.baseline_b0_score),
        format_float_tsv(result.baseline_b1_score),
        result.yield_metric,
        format_float_tsv(result.train_mean_nrmse),
        format_float_tsv(result.valid_mean_nrmse),
        format_float_tsv(result.all_mean_nrmse),
        format_float_tsv(result.train_yield_nrmse),
        format_float_tsv(result.train_yield_bias),
        format_float_tsv(result.valid_yield_nrmse),
        format_float_tsv(result.valid_yield_bias),
        format_float_tsv(result.duration_sec),
        str(result.max_workers),
        "true" if result.validation_enabled else "false",
        result.train_trts,
        result.valid_trts,
        result.workspace_dir,
        result.strategy_hash,
        result.eval_hash,
        result.auto_evolve_hash,
    ]
    with EXPERIMENT_RUNS_TSV_PATH.open("a", encoding="utf-8") as handle:
        handle.write("\t".join(fields) + "\n")


def load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def batch_aggregate_dir(batch_root: Path) -> Path:
    aggregate_dir = Path(batch_root).resolve() / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    return aggregate_dir


def collect_batch_task_state_counts(batch_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for state_path in Path(batch_root).glob("workers/worker_*/tasks/task_*/task_state.json"):
        state_payload = load_json_dict(state_path)
        state = str(state_payload.get("state", "")).strip() or "unknown"
        counts[state] = counts.get(state, 0) + 1
    return counts


def matrix_batch_has_failures(results: list[MatrixResult]) -> bool:
    return any(result.status == "crash" for result in results)


def build_batch_state_payload(
    *,
    batch_root: Path,
    batch_id: str,
    status: str,
    total_jobs: int,
    results: list[MatrixResult] | None = None,
    quality_gate_overall: str = "",
    quality_gate_decision: str = "",
    batch_report_path: str = "",
    created_at: str = "",
) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    resolved_results = list(results or [])
    completed_task_count = len(resolved_results)
    result_status_counts: dict[str, int] = {}
    for result in resolved_results:
        result_status_counts[result.status] = result_status_counts.get(result.status, 0) + 1
    failed_task_count = result_status_counts.get("crash", 0)
    payload: dict[str, Any] = {
        "batch_id": batch_id,
        "status": status,
        "task_count": total_jobs,
        "completed_task_count": completed_task_count,
        "pending_task_count": max(0, total_jobs - completed_task_count),
        "failed_task_count": failed_task_count,
        "result_status_counts": result_status_counts,
        "task_state_counts": collect_batch_task_state_counts(batch_root),
        "updated_at": now,
    }
    if created_at:
        payload["created_at"] = created_at
    if completed_task_count >= total_jobs and total_jobs > 0:
        payload["finished_at"] = now
    if quality_gate_overall:
        payload["quality_gate_overall"] = quality_gate_overall
    if quality_gate_decision:
        payload["quality_gate_decision"] = quality_gate_decision
    if batch_report_path:
        payload["batch_report_path"] = batch_report_path
    return payload


def snapshot_batch_aggregate_artifacts(batch_root: Path, report_outputs: dict[str, Path] | None = None) -> dict[str, str]:
    aggregate_dir = batch_aggregate_dir(batch_root)
    copied: dict[str, str] = {}
    artifact_map: dict[str, Path] = {
        "experiment_runs": EXPERIMENT_RUNS_TSV_PATH,
        "experiment_summary": EXPERIMENT_SUMMARY_TSV_PATH,
        "main_matrix_quality_gate": MAIN_MATRIX_QUALITY_GATE_TSV_PATH,
        "main_matrix_paper_table": MAIN_MATRIX_PAPER_TABLE_TSV_PATH,
    }
    if report_outputs:
        for key, path in report_outputs.items():
            artifact_map[key] = Path(path)
    for name, source_path in artifact_map.items():
        source = Path(source_path)
        if not source.exists():
            continue
        destination = aggregate_dir / source.name
        shutil.copy2(source, destination)
        copied[name] = str(destination.resolve())
    return copied


def mark_task_result_aggregated(result: MatrixResult) -> None:
    task_dir_raw = str(result.task_dir).strip()
    batch_root_raw = str(result.batch_root).strip()
    task_id = str(result.task_id).strip()
    if not task_dir_raw or not batch_root_raw or not task_id:
        return
    task_dir = Path(task_dir_raw)
    state_payload = load_json_dict(task_dir / "task_state.json")
    task_store = TaskStore(Path(batch_root_raw))
    task_store.write_task_state(
        task_dir,
        TaskStateRecord(
            task_id=task_id,
            state="aggregated",
            worker_id=str(state_payload.get("worker_id", result.worker_id)),
            assigned_at=str(state_payload.get("assigned_at", "")),
            started_at=str(state_payload.get("started_at", "")),
            finished_at=str(state_payload.get("finished_at", "")),
            retry_count=int(state_payload.get("retry_count", 0) or 0),
            error_code=str(state_payload.get("error_code", "")),
            error_summary=str(state_payload.get("error_summary", "")),
        ),
    )


def write_matrix_batch_report(
    *,
    batch_root: Path,
    batch_id: str,
    plan: str,
    results: list[MatrixResult],
    quality_gate_rows: list[dict[str, str]],
    report_outputs: dict[str, Path],
    final_status: str,
) -> Path:
    task_state_counts = collect_batch_task_state_counts(batch_root)
    result_status_counts: dict[str, int] = {}
    for result in results:
        result_status_counts[result.status] = result_status_counts.get(result.status, 0) + 1
    artifact_snapshot = snapshot_batch_aggregate_artifacts(batch_root, report_outputs)
    quality_gate_failures = [
        str(row.get("gate_key", "")).strip()
        for row in quality_gate_rows
        if str(row.get("status", "")).strip().lower() != "pass"
    ]
    payload = {
        "batch_id": batch_id,
        "plan": plan,
        "status": final_status,
        "task_count": len(results),
        "result_status_counts": result_status_counts,
        "task_state_counts": task_state_counts,
        "quality_gate": {
            "total_rows": len(quality_gate_rows),
            "failing_gate_keys": quality_gate_failures,
        },
        "artifacts": artifact_snapshot,
    }
    task_store = TaskStore(batch_root)
    return task_store.write_batch_report(payload)


def parse_task_index(task_id: str) -> int | None:
    match = re.fullmatch(r"task_(\d+)", str(task_id).strip())
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def resolve_resume_batch_root(batch_root: str = "") -> Path:
    if str(batch_root).strip():
        resolved = Path(batch_root).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"resume batch root not found: {resolved}")
        return resolved
    candidates = [path for path in PARALLEL_WORKERS_DIR.iterdir() if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"no matrix batch directories found under {PARALLEL_WORKERS_DIR}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_matrix_result_from_task_dir(
    task_dir: Path,
    *,
    negative_ref_profile: str,
    negative_ref_score: float,
    yield_metric: str,
    batch_root: Path,
    batch_id: str,
) -> MatrixResult | None:
    manifest_payload = load_json_dict(task_dir / "task_manifest.json")
    result_payload = load_json_dict(task_dir / "task_result.json")
    state_payload = load_json_dict(task_dir / "task_state.json")
    protocol_payload = manifest_payload.get("protocol", {})
    if not isinstance(protocol_payload, dict):
        return None
    run_id = str(protocol_payload.get("run_id", "")).strip()
    weight_name = str(protocol_payload.get("weight", "")).strip()
    weight_mode = str(protocol_payload.get("weight_mode", "")).strip()
    engine = str(protocol_payload.get("engine", "")).strip()
    budget = str(protocol_payload.get("budget", "")).strip()
    sequence = str(protocol_payload.get("sequence", "")).strip()
    grouping = str(protocol_payload.get("grouping", "")).strip()
    if not all((run_id, weight_name, engine, budget, sequence, grouping)):
        return None
    stdout_path = Path(str(result_payload.get("stdout_path", "")).strip()) if result_payload.get("stdout_path") else task_dir / "stdout.txt"
    stdout = stdout_path.read_text(encoding="utf-8", errors="ignore") if stdout_path.exists() else ""
    score_value = result_payload.get("score")
    try:
        score = float(score_value)
    except (TypeError, ValueError):
        score = extract_score(stdout)
    result = build_matrix_result(
        run_id=run_id,
        weight=WeightCandidate(weight_name, "resumed batch task", weight_mode, None),
        engine=engine,
        budget=budget,
        sequence=sequence,
        grouping=grouping,
        score=score,
        status=str(result_payload.get("status", state_payload.get("state", "unknown"))).strip() or "unknown",
        stdout=stdout,
        negative_ref_profile=negative_ref_profile,
        negative_ref_score=negative_ref_score,
        yield_metric=yield_metric,
    )
    result.plan = str(protocol_payload.get("plan", "")).strip()
    result.executed_at = str(state_payload.get("started_at", "") or state_payload.get("assigned_at", "")).strip()
    try:
        result.duration_sec = float(result_payload.get("duration_sec", float("nan")))
    except (TypeError, ValueError):
        result.duration_sec = float("nan")
    runtime_dir = str((result_payload.get("artifact_index", {}) or {}).get("runtime_dir", "")).strip()
    result.workspace_dir = runtime_dir
    result.batch_id = batch_id
    result.batch_root = str(batch_root.resolve())
    result.task_id = str(manifest_payload.get("task_id", task_dir.name)).strip() or task_dir.name
    result.task_dir = str(task_dir.resolve())
    result.worker_id = str(state_payload.get("worker_id", task_dir.parent.parent.name)).strip()
    return result


def classify_resume_task_state(task_dir: Path) -> str:
    state_payload = load_json_dict(task_dir / "task_state.json")
    return str(state_payload.get("state", "")).strip().lower()


def resolve_resumable_matrix_jobs(
    batch_root: Path,
    jobs: list[MatrixJob],
    *,
    negative_ref_profile: str,
    negative_ref_score: float,
    yield_metric: str,
) -> tuple[dict[int, MatrixResult], list[MatrixJob], str]:
    batch_manifest = load_json_dict(Path(batch_root) / "batch_manifest.json")
    batch_id = str(batch_manifest.get("batch_id", Path(batch_root).name)).strip() or Path(batch_root).name
    jobs_by_index = {job.index: job for job in jobs}
    completed_results: dict[int, MatrixResult] = {}
    pending_indices = set(jobs_by_index)
    for task_state_path in Path(batch_root).glob("workers/worker_*/tasks/task_*/task_state.json"):
        task_dir = task_state_path.parent
        task_state = classify_resume_task_state(task_dir)
        task_id = task_dir.name
        job_index = parse_task_index(task_id)
        if job_index is None or job_index not in jobs_by_index:
            continue
        if task_state in {"passed", "aggregated", "failed_fatal"}:
            loaded = load_matrix_result_from_task_dir(
                task_dir,
                negative_ref_profile=negative_ref_profile,
                negative_ref_score=negative_ref_score,
                yield_metric=yield_metric,
                batch_root=batch_root,
                batch_id=batch_id,
            )
            if loaded is not None:
                completed_results[job_index] = loaded
                pending_indices.discard(job_index)
            continue
        if task_state in {"assigned", "running", "retry_pending", "stale", "failed_retryable"}:
            continue
    pending_jobs = [jobs_by_index[index] for index in sorted(pending_indices)]
    return completed_results, pending_jobs, batch_id


def resume_batch(
    batch_root: str,
    jobs: list[MatrixJob],
    *,
    negative_ref_profile: str,
    negative_ref_score: float,
    yield_metric: str,
) -> tuple[Path, dict[int, MatrixResult], list[MatrixJob], str]:
    resolved_batch_root = resolve_resume_batch_root(batch_root)
    completed_results, pending_jobs, batch_id = resolve_resumable_matrix_jobs(
        resolved_batch_root,
        jobs,
        negative_ref_profile=negative_ref_profile,
        negative_ref_score=negative_ref_score,
        yield_metric=yield_metric,
    )
    return resolved_batch_root, completed_results, pending_jobs, batch_id


def _tsv_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int)):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.6f}"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value if str(item).strip())
    return str(value)


def _tsv_record_summary(
    records: Any,
    *,
    key_field: str,
    reason_field: str = "reason",
) -> str:
    if not isinstance(records, list):
        return ""
    parts: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        key_value = str(record.get(key_field, "")).strip()
        reason_value = str(record.get(reason_field, "")).strip()
        if key_value and reason_value:
            parts.append(f"{key_value}:{reason_value}")
        elif key_value:
            parts.append(key_value)
    return ",".join(parts)


def _parse_tsv_record_summary(value: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    for raw_part in str(value).split(","):
        part = raw_part.strip()
        if not part:
            continue
        key, _, reason = part.partition(":")
        normalized_key = key.strip()
        if normalized_key:
            parts.append((normalized_key, reason.strip()))
    return parts


def build_protocol_artifact_index_row(run_row: dict[str, str]) -> dict[str, str]:
    workspace_dir_raw = str(run_row.get("workspace_dir", "")).strip()
    workspace_dir, runtime_dir, manifest_path, contract_path = resolve_workspace_runtime_artifacts(workspace_dir_raw)
    manifest = load_json_dict(manifest_path)
    contract = load_json_dict(contract_path)
    scenario = manifest.get("scenario", {}) if isinstance(manifest.get("scenario"), dict) else {}
    observations = manifest.get("observations", {}) if isinstance(manifest.get("observations"), dict) else {}
    resolved_output = manifest.get("resolved_output", {}) if isinstance(manifest.get("resolved_output"), dict) else {}
    manifest_protocol = manifest.get("protocol", {}) if isinstance(manifest.get("protocol"), dict) else {}
    contract_protocol = contract.get("protocol", {}) if isinstance(contract.get("protocol"), dict) else {}
    requested = contract.get("requested", {}) if isinstance(contract.get("requested"), dict) else {}
    resolved = contract.get("resolved", {}) if isinstance(contract.get("resolved"), dict) else {}
    contract_summary = contract.get("summary", {}) if isinstance(contract.get("summary"), dict) else {}
    active_groups = contract.get("active_groups", resolved.get("active_groups", resolved_output.get("active_groups", [])))
    fallback_metrics = contract.get("fallback_metrics", contract_summary.get("fallback_metrics", []))
    dropped_groups = contract.get("dropped_groups", contract_summary.get("dropped_groups", []))
    weight_fallbacks = contract.get("weight_fallbacks", contract_summary.get("weight_fallbacks", []))
    zero_weight_observations = contract.get(
        "zero_weight_observations",
        contract_summary.get("zero_weight_observations", []),
    )
    issues = contract.get("issues", []) if isinstance(contract.get("issues"), list) else []
    issue_codes = [
        str(issue.get("code", "")).strip()
        for issue in issues
        if isinstance(issue, dict) and str(issue.get("code", "")).strip()
    ]
    warning_count = sum(
        1
        for issue in issues
        if isinstance(issue, dict) and str(issue.get("severity", "")).strip().lower() == "warning"
    )
    error_count = sum(
        1
        for issue in issues
        if isinstance(issue, dict) and str(issue.get("severity", "")).strip().lower() == "error"
    )
    protocol_payload = contract_protocol or manifest_protocol
    return {
        "run_id": str(run_row.get("run_id", "")).strip() or str(manifest.get("run_id", "")).strip(),
        "executed_at": str(run_row.get("executed_at", "")).strip(),
        "plan": str(run_row.get("plan", "")).strip(),
        "weight": str(run_row.get("weight", "")).strip(),
        "engine": str(run_row.get("engine", "")).strip(),
        "budget": str(run_row.get("budget", "")).strip(),
        "sequence": str(run_row.get("sequence", "")).strip(),
        "grouping": str(run_row.get("grouping", "")).strip(),
        "status": str(run_row.get("status", "")).strip(),
        "workspace_dir": str(workspace_dir) if workspace_dir_raw else "",
        "runtime_dir": str(runtime_dir) if workspace_dir_raw else "",
        "run_manifest_path": str(manifest_path) if manifest_path.exists() else "",
        "contract_report_path": str(contract_path) if contract_path.exists() else "",
        "crop": str(manifest.get("crop", "") or contract.get("crop", "")).strip(),
        "filex_name": str(scenario.get("filex_name", "")).strip(),
        "trts": _tsv_scalar(scenario.get("trts", [])),
        "protocol_weight": str(protocol_payload.get("weight", "")).strip(),
        "protocol_engine": str(protocol_payload.get("engine", "")).strip(),
        "protocol_budget": str(protocol_payload.get("budget", "")).strip(),
        "protocol_sequence": str(protocol_payload.get("sequence", "")).strip(),
        "protocol_grouping": str(protocol_payload.get("grouping", "")).strip(),
        "protocol_weight_mode": str(protocol_payload.get("weight_mode", "")).strip(),
        "contract_status": str(contract.get("status", "")).strip(),
        "issue_count": str(len(issues)),
        "warning_count": str(warning_count),
        "error_count": str(error_count),
        "issue_codes": _tsv_scalar(issue_codes),
        "active_groups": _tsv_scalar(active_groups),
        "fallback_metrics": _tsv_scalar(fallback_metrics),
        "dropped_groups": _tsv_record_summary(dropped_groups, key_field="group"),
        "weight_fallbacks": _tsv_record_summary(weight_fallbacks, key_field="group"),
        "zero_weight_observations": _tsv_record_summary(zero_weight_observations, key_field="obs_name"),
        "requested_summary_metrics": _tsv_scalar(requested.get("summary_metrics", observations.get("requested_summary_metrics", []))),
        "resolved_summary_metrics": _tsv_scalar(resolved.get("summary_metrics", resolved_output.get("summary_metrics", []))),
        "requested_t_vars": _tsv_scalar(requested.get("t_vars", observations.get("requested_t_vars", []))),
        "resolved_t_vars": _tsv_scalar(resolved.get("t_vars", resolved_output.get("t_vars", []))),
        "active_metric_count": _tsv_scalar(contract_summary.get("active_metric_count", "")),
        "active_observation_count": _tsv_scalar(contract_summary.get("active_observation_count", "")),
        "dropped_group_count": _tsv_scalar(contract_summary.get("dropped_group_count", len(dropped_groups) if isinstance(dropped_groups, list) else "")),
        "weight_fallback_count": _tsv_scalar(contract_summary.get("weight_fallback_count", len(weight_fallbacks) if isinstance(weight_fallbacks, list) else "")),
        "zero_weight_observation_count": _tsv_scalar(
            contract_summary.get(
                "zero_weight_observation_count",
                len(zero_weight_observations) if isinstance(zero_weight_observations, list) else "",
            )
        ),
    }


def rebuild_experiment_protocol_artifacts_index() -> None:
    run_rows = read_tsv_rows(EXPERIMENT_RUNS_TSV_PATH)
    protocol_rows = [
        build_protocol_artifact_index_row(run_row)
        for run_row in sorted(
            run_rows,
            key=lambda item: (
                str(item.get("executed_at", "")).strip(),
                summarize_combo_key(item),
                str(item.get("run_id", "")).strip(),
            ),
        )
    ]
    write_tsv_dict_rows(
        EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH,
        EXPERIMENT_PROTOCOL_ARTIFACTS_FIELDNAMES,
        protocol_rows,
    )


def ensure_experiment_params_tsv_schema() -> None:
    expected_header = (
        "run_id\texecuted_at\tplan\tweight\tengine\tbudget\tsequence\tgrouping\tstatus\t"
        + "\t".join(FINAL_PARAM_NAMES)
    )
    ensure_tsv_header(EXPERIMENT_PARAMS_TSV_PATH, expected_header)


def append_experiment_params_tsv(result: MatrixResult) -> None:
    ensure_experiment_params_tsv_schema()
    values = [
        result.run_id,
        result.executed_at,
        result.plan,
        result.weight_name,
        result.engine,
        result.budget,
        result.sequence,
        result.grouping,
        result.status,
    ]
    values.extend(format_float_tsv(result.final_params.get(name, float("nan"))) for name in FINAL_PARAM_NAMES)
    with EXPERIMENT_PARAMS_TSV_PATH.open("a", encoding="utf-8") as handle:
        handle.write("\t".join(values) + "\n")


def ensure_experiment_metrics_long_tsv_schema() -> None:
    expected_header = "\t".join(TREATMENT_METRIC_EXPORT_FIELDNAMES)
    ensure_tsv_header(EXPERIMENT_METRICS_LONG_TSV_PATH, expected_header)


def format_export_scalar(value: str | int | float) -> str:
    if isinstance(value, float):
        return format_float_tsv(value)
    return str(value)


def append_experiment_metrics_long_tsv(result: MatrixResult) -> None:
    ensure_experiment_metrics_long_tsv_schema()
    if not result.treatment_rows:
        return
    with EXPERIMENT_METRICS_LONG_TSV_PATH.open("a", encoding="utf-8") as handle:
        for row in result.treatment_rows:
            export_values = build_treatment_metric_export_value_map(row)
            handle.write(
                "\t".join(format_export_scalar(export_values[name]) for name in TREATMENT_METRIC_EXPORT_FIELDNAMES)
                + "\n"
            )


def ensure_experiment_aggregate_metrics_tsv_schema() -> None:
    expected_header = "\t".join(AGGREGATE_METRIC_EXPORT_FIELDNAMES)
    ensure_tsv_header(EXPERIMENT_AGGREGATE_METRICS_TSV_PATH, expected_header)


def append_experiment_aggregate_metrics_tsv(result: MatrixResult) -> None:
    ensure_experiment_aggregate_metrics_tsv_schema()
    if not result.aggregate_rows:
        return
    with EXPERIMENT_AGGREGATE_METRICS_TSV_PATH.open("a", encoding="utf-8") as handle:
        for row in result.aggregate_rows:
            export_values = build_aggregate_metric_export_value_map(row)
            handle.write(
                "\t".join(format_export_scalar(export_values[name]) for name in AGGREGATE_METRIC_EXPORT_FIELDNAMES)
                + "\n"
            )


def read_tsv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return [dict(row) for row in reader if row]


def parse_tsv_float(row: dict[str, str], key: str) -> float:
    raw_value = str(row.get(key, "")).strip()
    if not raw_value:
        return float("nan")
    try:
        return float(raw_value)
    except ValueError:
        return float("nan")


def parse_tsv_int(row: dict[str, str], key: str, default: int = 0) -> int:
    raw_value = str(row.get(key, "")).strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def parse_tsv_bool(row: dict[str, str], key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes", "y"}


def summarize_combo_key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    combo_key = build_combo_key(
        str(row.get("weight", "")).strip(),
        str(row.get("engine", "")).strip(),
        str(row.get("budget", "")).strip(),
        str(row.get("sequence", "")).strip(),
        str(row.get("grouping", "")).strip(),
    )
    parts = combo_key.split("|", 4)
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def summary_sort_key(row: dict[str, str]) -> tuple[str, str, str]:
    status = str(row.get("status", "")).strip().lower()
    status_rank = {
        "ok": "3",
        "degraded": "2",
        "warning": "1",
        "crash": "0",
    }.get(status, "0")
    return (
        status_rank,
        str(row.get("executed_at", "")).strip(),
        str(row.get("run_id", "")).strip(),
    )


def deduplicate_latest_runs(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    latest_by_combo: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for row in rows:
        key = summarize_combo_key(row)
        current = latest_by_combo.get(key)
        if current is None or summary_sort_key(row) >= summary_sort_key(current):
            latest_by_combo[key] = row
    return sorted(latest_by_combo.values(), key=lambda item: summarize_combo_key(item))


def write_tsv_dict_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    ensure_parent_dir(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: str(row.get(field, "")) for field in fieldnames})


def ensure_metric_split_bucket(
    metric_split_rows_by_run: dict[str, dict[str, str]],
    summary_row: dict[str, str],
    run_id: str,
) -> dict[str, str]:
    return metric_split_rows_by_run.setdefault(
        run_id,
        {
            "run_id": run_id,
            "score_rank": summary_row.get("score_rank", ""),
            "combo_key": summary_row.get("combo_key", ""),
            "weight": summary_row.get("weight", ""),
            "engine": summary_row.get("engine", ""),
            "budget": summary_row.get("budget", ""),
            "sequence": summary_row.get("sequence", ""),
            "grouping": summary_row.get("grouping", ""),
            "status": summary_row.get("status", ""),
            "score": summary_row.get("score", ""),
        },
    )


def build_aggregate_summary_by_run(rows: list[dict[str, str]]) -> dict[str, dict[str, object]]:
    summary_by_run: dict[str, dict[str, object]] = {}
    for row in rows:
        run_id = str(row.get("run_id", "")).strip()
        if not run_id:
            continue
        split = str(row.get("split", "")).strip().lower()
        metric = str(row.get("metric", "")).strip().lower()
        bucket = summary_by_run.setdefault(run_id, {"nrmse_by_split": {}, "metric_rows": {}})
        nrmse_by_split = cast(dict[str, list[float]], bucket["nrmse_by_split"])
        metric_rows = cast(dict[tuple[str, str], dict[str, str]], bucket["metric_rows"])
        nrmse = parse_tsv_float(row, "nrmse")
        if split and math.isfinite(nrmse):
            nrmse_by_split.setdefault(split, []).append(nrmse)
        if split and metric:
            metric_rows[(split, metric)] = row
    return summary_by_run


def resolve_summary_metrics_from_aggregate(
    aggregate_summary: dict[str, object] | None,
    primary_metric: str,
) -> dict[str, float]:
    if aggregate_summary is None:
        return {}
    nrmse_by_split = cast(dict[str, list[float]], aggregate_summary.get("nrmse_by_split", {}))
    metric_rows = cast(dict[tuple[str, str], dict[str, str]], aggregate_summary.get("metric_rows", {}))
    primary_key = str(primary_metric).strip().lower()
    values: dict[str, float] = {}
    for split in ("train", "valid", "all"):
        split_scores = [value for value in nrmse_by_split.get(split, []) if math.isfinite(value)]
        values[f"{split}_mean_nrmse"] = (
            sum(split_scores) / len(split_scores) if split_scores else float("nan")
        )
    train_primary = metric_rows.get(("train", primary_key), {})
    valid_primary = metric_rows.get(("valid", primary_key), {})
    values["train_yield_nrmse"] = parse_tsv_float(train_primary, "nrmse")
    values["train_yield_bias"] = parse_tsv_float(train_primary, "bias")
    values["valid_yield_nrmse"] = parse_tsv_float(valid_primary, "nrmse")
    values["valid_yield_bias"] = parse_tsv_float(valid_primary, "bias")
    return values


def resolve_aggregate_metric_row(
    aggregate_summary: dict[str, object] | None,
    split: str,
    metric: str,
) -> dict[str, str]:
    if aggregate_summary is None:
        return {}
    metric_rows = cast(dict[tuple[str, str], dict[str, str]], aggregate_summary.get("metric_rows", {}))
    return metric_rows.get((str(split).strip().lower(), str(metric).strip().lower()), {})


def rebuild_experiment_summary_exports() -> None:
    rebuild_experiment_protocol_artifacts_index()
    run_rows = read_tsv_rows(EXPERIMENT_RUNS_TSV_PATH)
    latest_rows = deduplicate_latest_runs(run_rows)
    summary_rows: list[dict[str, str]] = []
    latest_run_ids = {str(row.get("run_id", "")).strip() for row in latest_rows}
    aggregate_rows = read_tsv_rows(EXPERIMENT_AGGREGATE_METRICS_TSV_PATH)
    aggregate_summary_by_run = build_aggregate_summary_by_run(aggregate_rows)
    for row in latest_rows:
        score = parse_tsv_float(row, "score")
        b0_score = parse_tsv_float(row, "baseline_b0_score")
        b1_score = parse_tsv_float(row, "baseline_b1_score")
        negative_ref_score = parse_tsv_float(row, "negative_ref_score")
        combo_key = build_combo_key(
            str(row.get("weight", "")).strip(),
            str(row.get("engine", "")).strip(),
            str(row.get("budget", "")).strip(),
            str(row.get("sequence", "")).strip(),
            str(row.get("grouping", "")).strip(),
        )
        run_id = str(row.get("run_id", "")).strip()
        yield_metric = str(row.get("yield_metric", "")).strip()
        schema_metrics = resolve_summary_metrics_from_aggregate(
            aggregate_summary_by_run.get(run_id),
            yield_metric,
        )
        summary_rows.append(
            build_summary_export_row(
                row,
                combo_key=combo_key,
                score=score,
                baseline_b0_score=b0_score,
                baseline_b1_score=b1_score,
                negative_ref_score=negative_ref_score,
                schema_metrics=schema_metrics,
            )
        )
    ranked_summary_rows = sorted(
        summary_rows,
        key=lambda item: (
            parse_tsv_float(item, "score") if math.isfinite(parse_tsv_float(item, "score")) else float("inf"),
            item["run_id"],
        ),
    )
    for rank, row in enumerate(ranked_summary_rows, start=1):
        row["score_rank"] = str(rank)
    write_tsv_dict_rows(EXPERIMENT_SUMMARY_TSV_PATH, SUMMARY_EXPORT_FIELDNAMES, summary_rows)
    summary_by_run_id = {row["run_id"]: row for row in summary_rows}

    metrics_rows = read_tsv_rows(EXPERIMENT_METRICS_LONG_TSV_PATH)
    scatter_rows: list[dict[str, str]] = []
    latest_metric_rows: list[dict[str, str]] = []
    for row in metrics_rows:
        run_id = str(row.get("run_id", "")).strip()
        if run_id not in latest_run_ids:
            continue
        split = str(row.get("split", "")).strip()
        metric = str(row.get("metric", "")).strip()
        aggregate_metric_row = resolve_aggregate_metric_row(
            aggregate_summary_by_run.get(run_id),
            split,
            metric,
        )
        combo_key = build_combo_key(
            str(row.get("weight", "")).strip(),
            str(row.get("engine", "")).strip(),
            str(row.get("budget", "")).strip(),
            str(row.get("sequence", "")).strip(),
            str(row.get("grouping", "")).strip(),
        )
        scatter_row = build_scatter_export_row(row, aggregate_metric_row, combo_key)
        scatter_rows.append(scatter_row)
        latest_metric_rows.append(dict(scatter_row))
    scatter_rows.sort(
        key=lambda item: (
            item["weight"],
            item["engine"],
            item["budget"],
            item["sequence"],
            item["grouping"],
            item["metric"],
            parse_tsv_int(item, "trt"),
        )
    )
    write_tsv_dict_rows(EXPERIMENT_SCATTER_1TO1_TSV_PATH, SCATTER_EXPORT_FIELDNAMES, scatter_rows)

    heatmap_by_weight: dict[str, dict[str, str]] = {}
    heatmap_columns: list[str] = []
    for row in summary_rows:
        weight_name = row["weight"]
        column_key = "|".join([row["engine"], row["budget"], row["sequence"], row["grouping"]])
        bucket = heatmap_by_weight.setdefault(weight_name, {"weight": weight_name})
        bucket[column_key] = row["score"]
        if column_key not in heatmap_columns:
            heatmap_columns.append(column_key)
    heatmap_fieldnames = ["weight"] + sorted(heatmap_columns)
    heatmap_rows = [heatmap_by_weight[weight] for weight in sorted(heatmap_by_weight)]
    write_tsv_dict_rows(EXPERIMENT_HEATMAP_WIDE_TSV_PATH, heatmap_fieldnames, heatmap_rows)

    metric_split_rows_by_run: dict[str, dict[str, str]] = {}
    metric_split_columns: list[str] = []
    for row in aggregate_rows:
        run_id = str(row.get("run_id", "")).strip()
        if run_id not in latest_run_ids:
            continue
        summary_row = summary_by_run_id.get(run_id)
        if summary_row is None:
            continue
        bucket = ensure_metric_split_bucket(metric_split_rows_by_run, summary_row, run_id)
        metric = str(row.get("metric", "")).strip()
        split = str(row.get("split", "")).strip()
        base = f"{metric}|{split}"
        standardized_columns = [
            f"{base}|count",
            f"{base}|nrmse",
            f"{base}|bias",
        ]
        for column in standardized_columns:
            if column not in metric_split_columns:
                metric_split_columns.append(column)
        bucket[f"{base}|count"] = str(row.get("count", "")).strip()
        bucket[f"{base}|nrmse"] = str(row.get("nrmse", "")).strip()
        bucket[f"{base}|bias"] = str(row.get("bias", "")).strip()

    metric_split_groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in latest_metric_rows:
        key = (row["run_id"], row["metric"], row["split"])
        metric_split_groups.setdefault(key, []).append(row)
    for (run_id, metric, split), grouped_rows in metric_split_groups.items():
        summary_row = summary_by_run_id.get(run_id)
        if summary_row is None:
            continue
        bucket = ensure_metric_split_bucket(metric_split_rows_by_run, summary_row, run_id)
        errors = [parse_tsv_float(item, "error") for item in grouped_rows]
        abs_errors = [parse_tsv_float(item, "abs_error") for item in grouped_rows]
        relative_errors = [parse_tsv_float(item, "relative_error") for item in grouped_rows]
        valid_errors = [value for value in errors if math.isfinite(value)]
        valid_abs_errors = [value for value in abs_errors if math.isfinite(value)]
        valid_relative_errors = [value for value in relative_errors if math.isfinite(value)]
        base = f"{metric}|{split}"
        derived_columns = [
            f"{base}|mean_error",
            f"{base}|mae",
            f"{base}|mre",
            f"{base}|rmse",
            f"{base}|n",
        ]
        for column in derived_columns:
            if column not in metric_split_columns:
                metric_split_columns.append(column)
        mean_error = sum(valid_errors) / len(valid_errors) if valid_errors else float("nan")
        mean_abs_error = sum(valid_abs_errors) / len(valid_abs_errors) if valid_abs_errors else float("nan")
        mean_relative_error = sum(valid_relative_errors) / len(valid_relative_errors) if valid_relative_errors else float("nan")
        rmse = math.sqrt(sum(value * value for value in valid_errors) / len(valid_errors)) if valid_errors else float("nan")
        bucket[f"{base}|mean_error"] = format_float_tsv(mean_error)
        bucket[f"{base}|mae"] = format_float_tsv(mean_abs_error)
        bucket[f"{base}|mre"] = format_float_tsv(mean_relative_error)
        bucket[f"{base}|rmse"] = format_float_tsv(rmse)
        bucket[f"{base}|n"] = str(len(valid_errors))
    metric_split_fieldnames = [
        "run_id",
        "score_rank",
        "combo_key",
        "weight",
        "engine",
        "budget",
        "sequence",
        "grouping",
        "status",
        "score",
    ] + sorted(metric_split_columns)
    metric_split_rows = [
        metric_split_rows_by_run[run_id]
        for run_id in sorted(
            metric_split_rows_by_run,
            key=lambda item: parse_tsv_int(metric_split_rows_by_run[item], "score_rank", default=10**9),
        )
    ]
    write_tsv_dict_rows(EXPERIMENT_METRIC_SPLIT_HEATMAP_TSV_PATH, metric_split_fieldnames, metric_split_rows)

    trts, _, _ = project_observation_bundle()
    residual_rows_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    residual_fieldnames = build_residual_export_fieldnames(trts)
    for row in latest_metric_rows:
        run_id = row["run_id"]
        metric = row["metric"]
        split = row["split"]
        summary_row = summary_by_run_id.get(run_id)
        if summary_row is None:
            continue
        aggregate_metric_row = resolve_aggregate_metric_row(
            aggregate_summary_by_run.get(run_id),
            split,
            metric,
        )
        key = (run_id, metric, split)
        bucket = residual_rows_by_key.setdefault(
            key,
            build_residual_export_row(summary_row, metric, split, aggregate_metric_row),
        )
        bucket[f"trt_{parse_tsv_int(row, 'trt')}"] = row["error"]
    residual_rows = sorted(
        residual_rows_by_key.values(),
        key=lambda item: (parse_tsv_int(item, "score_rank", default=10**9), item["metric"], item["split"]),
    )
    write_tsv_dict_rows(EXPERIMENT_RESIDUALS_WIDE_TSV_PATH, residual_fieldnames, residual_rows)

    figure_ready_rows: list[dict[str, str]] = []
    for row in latest_metric_rows:
        summary_row = summary_by_run_id.get(row["run_id"])
        if summary_row is None:
            continue
        aggregate_metric_row = resolve_aggregate_metric_row(
            aggregate_summary_by_run.get(row["run_id"]),
            row["split"],
            row["metric"],
        )
        figure_ready_rows.append(build_figure_ready_export_row(summary_row, row, aggregate_metric_row))
    figure_ready_rows.sort(
        key=lambda item: (
            parse_tsv_int(item, "score_rank", default=10**9),
            item["metric"],
            item["split"],
            parse_tsv_int(item, "trt"),
        )
    )
    write_tsv_dict_rows(EXPERIMENT_FIGURE_READY_TSV_PATH, FIGURE_READY_EXPORT_FIELDNAMES, figure_ready_rows)


MAIN_MATRIX_REPORT_DIMENSIONS = ("weight", "engine", "sequence", "grouping")
MAIN_MATRIX_LEADERBOARD_FIELDNAMES = [
    "report_rank",
    "score_rank",
    "combo_key",
    "run_id",
    "plan",
    "weight",
    "engine",
    "budget",
    "sequence",
    "grouping",
    "status",
    "validation_enabled",
    "score",
    "delta_vs_b0",
    "delta_vs_b1",
    "delta_vs_negative_ref",
    "better_than_b0",
    "better_than_b1",
    "better_than_negative_ref",
    "yield_metric",
    "train_mean_nrmse",
    "valid_mean_nrmse",
    "all_mean_nrmse",
    "train_yield_nrmse",
    "train_yield_bias",
    "valid_yield_nrmse",
    "valid_yield_bias",
    "duration_sec",
    "executed_at",
    "workspace_dir",
]
MAIN_MATRIX_DIMENSION_SUMMARY_FIELDNAMES = [
    "dimension",
    "value",
    "total_runs",
    "ok_runs",
    "failed_runs",
    "best_report_rank",
    "best_score_rank",
    "best_score",
    "mean_score",
    "median_score",
    "worst_score",
    "better_than_b0_count",
    "better_than_b1_count",
    "better_than_negative_ref_count",
    "best_combo_key",
    "best_run_id",
    "best_plan",
    "best_budget",
    "best_weight",
    "best_engine",
    "best_sequence",
    "best_grouping",
    "best_status",
]
MAIN_MATRIX_BASELINE_SUMMARY_FIELDNAMES = [
    "comparison_target",
    "delta_field",
    "total_runs",
    "comparable_runs",
    "better_count",
    "better_rate",
    "best_delta",
    "mean_delta",
    "median_delta",
    "worst_delta",
    "best_combo_key",
    "best_run_id",
    "best_score",
    "best_valid_mean_nrmse",
]
MAIN_MATRIX_BASELINE_DETAIL_FIELDNAMES = [
    "comparison_target",
    "delta_field",
    "comparison_rank",
    "comparison_passed",
    "report_rank",
    "score_rank",
    "combo_key",
    "run_id",
    "plan",
    "weight",
    "engine",
    "budget",
    "sequence",
    "grouping",
    "status",
    "validation_enabled",
    "score",
    "comparison_delta",
    "valid_mean_nrmse",
    "train_mean_nrmse",
    "all_mean_nrmse",
    "executed_at",
]
MAIN_MATRIX_KEY_INDICATOR_TABLE_FIELDNAMES = [
    "selection_scope",
    "comparison_target",
    "indicator_key",
    "indicator_label",
    "available_runs",
    "best_value",
    "median_value",
    "best_combo_key",
    "best_run_id",
    "best_engine",
    "best_weight",
    "best_budget",
    "best_validation_enabled",
]
MAIN_MATRIX_BASELINE_WINNERS_FIELDNAMES = [
    "comparison_target",
    "delta_field",
    "winner_report_rank",
    "winner_combo_key",
    "winner_run_id",
    "winner_plan",
    "winner_score",
    "winner_valid_mean_nrmse",
    "winner_delta",
    "winner_engine",
    "winner_weight",
    "winner_budget",
    "winner_sequence",
    "winner_grouping",
    "winner_validation_enabled",
    "winner_status",
]
MAIN_MATRIX_METRIC_SNAPSHOT_FIELDNAMES = [
    "scope",
    "scope_label",
    "metric_key",
    "metric_label",
    "available_runs",
    "best_value",
    "mean_value",
    "median_value",
    "worst_value",
    "best_combo_key",
    "best_run_id",
]
MAIN_MATRIX_PAPER_SUMMARY_FIELDNAMES = [
    "selection_scope",
    "comparison_target",
    "selected_runs",
    "validation_runs",
    "best_score",
    "median_score",
    "best_valid_mean_nrmse",
    "median_valid_mean_nrmse",
    "best_comparison_delta",
    "median_comparison_delta",
    "better_than_target_count",
    "better_than_target_rate",
    "best_combo_key",
    "best_run_id",
    "best_engine",
    "best_weight",
]
MAIN_MATRIX_APPENDIX_INDEX_FIELDNAMES = [
    "panel_key",
    "panel_title",
    "output_key",
    "tsv_path",
    "selection_scope",
    "grouping_field",
    "panel_values",
    "row_count",
    "top_k",
]
MAIN_MATRIX_PAPER_MAIN_TABLE_FIELDNAMES = [
    "paper_rank",
    "combo_key",
    "score",
    "valid_mean_nrmse",
    "comparison_delta",
    "engine",
    "weight",
    "budget",
    "validation_enabled",
    "status",
]
MAIN_MATRIX_FROZEN_PAPER_MAIN_TABLE_FIELDNAMES = (
    "paper_rank",
    "combo_key",
    "score",
    "valid_mean_nrmse",
    "comparison_delta",
    "engine",
    "weight",
    "budget",
    "validation_enabled",
    "status",
)
MAIN_MATRIX_PROTOCOL_OVERVIEW_FIELDNAMES = [
    "selection_scope",
    "total_runs",
    "manifest_runs",
    "contract_runs",
    "ok_contract_runs",
    "degraded_contract_runs",
    "missing_contract_runs",
    "rows_with_warnings",
    "rows_with_errors",
    "total_issue_count",
    "rows_with_dropped_groups",
    "rows_with_weight_fallbacks",
    "rows_with_zero_weight_observations",
    "total_dropped_group_count",
    "total_weight_fallback_count",
    "total_zero_weight_observation_count",
    "dropped_group_run_rate",
    "weight_fallback_run_rate",
    "zero_weight_observation_run_rate",
    "mean_active_metric_count",
    "mean_active_observation_count",
]
MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_FIELDNAMES = [
    "selection_scope",
    "dimension",
    "value",
    "total_runs",
    "manifest_runs",
    "contract_runs",
    "ok_contract_runs",
    "degraded_contract_runs",
    "missing_contract_runs",
    "rows_with_warnings",
    "rows_with_errors",
    "total_issue_count",
    "rows_with_dropped_groups",
    "rows_with_weight_fallbacks",
    "rows_with_zero_weight_observations",
    "total_dropped_group_count",
    "total_weight_fallback_count",
    "total_zero_weight_observation_count",
    "dropped_group_run_rate",
    "weight_fallback_run_rate",
    "zero_weight_observation_run_rate",
    "mean_active_metric_count",
    "mean_active_observation_count",
]
MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_FIELDNAMES = [
    "selection_scope",
    "dimension_depth",
    "dimensions",
    "values",
    "slice_label",
    "total_runs",
    "manifest_runs",
    "contract_runs",
    "ok_contract_runs",
    "degraded_contract_runs",
    "missing_contract_runs",
    "rows_with_warnings",
    "rows_with_errors",
    "total_issue_count",
    "rows_with_dropped_groups",
    "rows_with_weight_fallbacks",
    "rows_with_zero_weight_observations",
    "total_dropped_group_count",
    "total_weight_fallback_count",
    "total_zero_weight_observation_count",
    "dropped_group_run_rate",
    "weight_fallback_run_rate",
    "zero_weight_observation_run_rate",
    "mean_active_metric_count",
    "mean_active_observation_count",
]
MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_FIELDNAMES = [
    "selection_scope",
    "source",
    "slice_label",
    "total_runs",
    "missing_contract_runs",
    "degraded_contract_runs",
    "total_dropped_group_count",
    "total_weight_fallback_count",
    "total_zero_weight_observation_count",
]
MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_FIELDNAMES = [
    "selection_scope",
    "reason_kind",
    "reason",
    "affected_runs",
    "total_occurrences",
    "affected_entities",
    "example_run_ids",
]
MAIN_MATRIX_QUALITY_GATE_FIELDNAMES = [
    "gate_key",
    "gate_label",
    "gate_level",
    "status",
    "expected",
    "actual",
    "detail",
]
MAIN_MATRIX_PROTOCOL_PANEL_FIELDNAMES = [
    "panel",
    "panel_value",
    "panel_rank",
    "paper_rank",
    "report_rank",
    "combo_key",
    "run_id",
    "score",
    "valid_mean_nrmse",
    "contract_status",
    "issue_count",
    "warning_count",
    "error_count",
    "active_metric_count",
    "active_observation_count",
    "dropped_group_count",
    "weight_fallback_count",
    "zero_weight_observation_count",
    "active_groups",
    "dropped_groups",
    "weight_fallbacks",
    "zero_weight_observations",
    "requested_summary_metrics",
    "resolved_summary_metrics",
    "requested_t_vars",
    "resolved_t_vars",
    "protocol_weight",
    "protocol_engine",
    "protocol_budget",
    "protocol_sequence",
    "protocol_grouping",
    "filex_name",
    "crop",
    "run_manifest_path",
    "contract_report_path",
]
MAIN_MATRIX_PAPER_TABLE_FIELDNAMES = [
    "paper_rank",
    "report_rank",
    "score_rank",
    "combo_key",
    "run_id",
    "plan",
    "weight",
    "engine",
    "budget",
    "sequence",
    "grouping",
    "status",
    "validation_enabled",
    "comparison_target",
    "comparison_delta",
    "comparison_passed",
    "score",
    "delta_vs_b0",
    "delta_vs_b1",
    "delta_vs_negative_ref",
    "better_than_b0",
    "better_than_b1",
    "better_than_negative_ref",
    "yield_metric",
    "train_mean_nrmse",
    "valid_mean_nrmse",
    "all_mean_nrmse",
    "train_yield_nrmse",
    "train_yield_bias",
    "valid_yield_nrmse",
    "valid_yield_bias",
    "duration_sec",
    "executed_at",
    "workspace_dir",
]
MAIN_MATRIX_FROZEN_PAPER_TABLE_FIELDNAMES = (
    "paper_rank",
    "report_rank",
    "score_rank",
    "combo_key",
    "run_id",
    "plan",
    "weight",
    "engine",
    "budget",
    "sequence",
    "grouping",
    "status",
    "validation_enabled",
    "comparison_target",
    "comparison_delta",
    "comparison_passed",
    "score",
    "delta_vs_b0",
    "delta_vs_b1",
    "delta_vs_negative_ref",
    "better_than_b0",
    "better_than_b1",
    "better_than_negative_ref",
    "yield_metric",
    "train_mean_nrmse",
    "valid_mean_nrmse",
    "all_mean_nrmse",
    "train_yield_nrmse",
    "train_yield_bias",
    "valid_yield_nrmse",
    "valid_yield_bias",
    "duration_sec",
    "executed_at",
    "workspace_dir",
)
MAIN_MATRIX_TOPK_PANEL_FIELDNAMES = [
    "panel",
    "panel_value",
    "panel_rank",
    *MAIN_MATRIX_PAPER_TABLE_FIELDNAMES,
]
MAIN_MATRIX_DIMENSION_LABELS = {
    "weight": "W",
    "engine": "O",
    "sequence": "S",
    "grouping": "G",
}
MAIN_MATRIX_BASELINE_TARGETS = (
    ("b0", "delta_vs_b0", "better_than_b0"),
    ("b1", "delta_vs_b1", "better_than_b1"),
    ("negative_ref", "delta_vs_negative_ref", "better_than_negative_ref"),
)
MAIN_MATRIX_METRIC_SNAPSHOT_SPECS = (
    ("score", "Score"),
    ("train_mean_nrmse", "Train Mean NRMSE"),
    ("valid_mean_nrmse", "Valid Mean NRMSE"),
    ("all_mean_nrmse", "All Mean NRMSE"),
    ("train_yield_nrmse", "Train Yield NRMSE"),
    ("valid_yield_nrmse", "Valid Yield NRMSE"),
    ("delta_vs_b0", "Δ vs B0"),
    ("delta_vs_b1", "Δ vs B1"),
    ("delta_vs_negative_ref", "Δ vs Negative Ref"),
)
MAIN_MATRIX_METRIC_SCOPE_ORDER = ("leaderboard_all", "paper_selected", "validation_selected")
MAIN_MATRIX_METRIC_SCOPE_LABELS = {
    "leaderboard_all": "Leaderboard All",
    "paper_selected": "Paper Selected",
    "validation_selected": "Validation Selected",
}
MAIN_MATRIX_APPENDIX_PANEL_SPECS = (
    ("paper_appendix_table", "Appendix: Paper Full Table", "paper_selected", "paper_rank"),
    ("protocol_paper_table", "Appendix: Protocol Coverage", "paper_selected", "contract_status"),
    ("protocol_reason_summary", "Appendix: Protocol Detail Reasons", "paper_selected", "reason_kind"),
    ("topk_by_engine", "Appendix: Top-K By Engine", "paper_selected", "engine"),
    ("topk_by_weight", "Appendix: Top-K By Weight", "paper_selected", "weight"),
    ("topk_by_sequence", "Appendix: Top-K By Sequence", "paper_selected", "sequence"),
    ("topk_by_grouping", "Appendix: Top-K By Grouping", "paper_selected", "grouping"),
    ("topk_validation_only", "Appendix: Validation-Only Top-K", "validation_selected", "validation_enabled"),
    ("topk_by_budget", "Appendix: Budget Split Top-K", "paper_selected", "budget"),
    ("topk_by_validation_budget", "Appendix: Validation × Budget Top-K", "paper_candidates", "validation_budget"),
    ("topk_improvement", "Appendix: Top-K Improvement", "paper_selected", "comparison_target"),
)
MAIN_MATRIX_APPENDIX_PANEL_KEYS = tuple(spec[0] for spec in MAIN_MATRIX_APPENDIX_PANEL_SPECS)
MAIN_MATRIX_REPORT_OUTPUT_KEYS = (
    "report",
    "leaderboard",
    "dimension_summary",
    "baseline_summary",
    "baseline_detail",
    "key_indicator_table",
    "baseline_winners",
    "metric_snapshot",
    "paper_summary",
    "protocol_overview",
    "protocol_dimension_summary",
    "protocol_nested_dimension_summary",
    "protocol_hotspot_summary",
    "protocol_reason_summary",
    "quality_gate",
    "appendix_index",
    "protocol_paper_table",
    "paper_main_table",
    "paper_appendix_table",
    "paper_table",
    "topk_overall",
    "topk_by_engine",
    "topk_by_weight",
    "topk_by_sequence",
    "topk_by_grouping",
    "topk_validation_only",
    "topk_by_budget",
    "topk_by_validation_budget",
    "topk_improvement",
)
MAIN_MATRIX_FROZEN_PROTOCOL_PAPER_TABLE_FIELDNAMES = (
    "panel",
    "panel_value",
    "panel_rank",
    "paper_rank",
    "report_rank",
    "combo_key",
    "run_id",
    "score",
    "valid_mean_nrmse",
    "contract_status",
    "issue_count",
    "warning_count",
    "error_count",
    "active_metric_count",
    "active_observation_count",
    "dropped_group_count",
    "weight_fallback_count",
    "zero_weight_observation_count",
    "active_groups",
    "dropped_groups",
    "weight_fallbacks",
    "zero_weight_observations",
    "requested_summary_metrics",
    "resolved_summary_metrics",
    "requested_t_vars",
    "resolved_t_vars",
    "protocol_weight",
    "protocol_engine",
    "protocol_budget",
    "protocol_sequence",
    "protocol_grouping",
    "filex_name",
    "crop",
    "run_manifest_path",
    "contract_report_path",
)
MAIN_MATRIX_PAPER_FACING_SCHEMA_SPECS = (
    (
        "paper_main_table_schema",
        "Paper Main Table Schema",
        MAIN_MATRIX_PAPER_MAIN_TABLE_FIELDNAMES,
        MAIN_MATRIX_FROZEN_PAPER_MAIN_TABLE_FIELDNAMES,
    ),
    (
        "paper_appendix_table_schema",
        "Paper Appendix Table Schema",
        MAIN_MATRIX_PAPER_TABLE_FIELDNAMES,
        MAIN_MATRIX_FROZEN_PAPER_TABLE_FIELDNAMES,
    ),
    (
        "protocol_paper_table_schema",
        "Protocol Paper Table Schema",
        MAIN_MATRIX_PROTOCOL_PANEL_FIELDNAMES,
        MAIN_MATRIX_FROZEN_PROTOCOL_PAPER_TABLE_FIELDNAMES,
    ),
)


def resolve_existing_artifact_path(preferred_path: Path) -> Path:
    resolved_path = Path(preferred_path).resolve()
    return resolved_path


def report_score_sort_key(row: dict[str, str]) -> tuple[int, float, int, str, str]:
    score = parse_tsv_float(row, "score")
    return (
        0 if math.isfinite(score) else 1,
        score if math.isfinite(score) else float("inf"),
        parse_tsv_int(row, "score_rank", default=10**9),
        str(row.get("executed_at", "")).strip(),
        str(row.get("run_id", "")).strip(),
    )


def compute_report_median(values: list[float]) -> float:
    ordered = sorted(value for value in values if math.isfinite(value))
    if not ordered:
        return float("nan")
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def filter_report_summary_rows(rows: list[dict[str, str]], report_plan: str = "") -> list[dict[str, str]]:
    if not report_plan.strip():
        return rows
    target_plan = report_plan.strip().lower()
    return [row for row in rows if str(row.get("plan", "")).strip().lower() == target_plan]


def parse_iso_timestamp(value: str) -> float:
    normalized = value.strip()
    if not normalized:
        return 0.0
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(normalized, pattern))
        except ValueError:
            continue
    return 0.0


def build_main_matrix_leaderboard_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    leaderboard_rows: list[dict[str, str]] = []
    for report_rank, row in enumerate(sorted(rows, key=report_score_sort_key), start=1):
        leaderboard_rows.append(
            {
                "report_rank": str(report_rank),
                "score_rank": str(row.get("score_rank", "")).strip(),
                "combo_key": str(row.get("combo_key", "")).strip(),
                "run_id": str(row.get("run_id", "")).strip(),
                "plan": str(row.get("plan", "")).strip(),
                "weight": str(row.get("weight", "")).strip(),
                "engine": str(row.get("engine", "")).strip(),
                "budget": str(row.get("budget", "")).strip(),
                "sequence": str(row.get("sequence", "")).strip(),
                "grouping": str(row.get("grouping", "")).strip(),
                "status": str(row.get("status", "")).strip(),
                "validation_enabled": str(row.get("validation_enabled", "")).strip(),
                "score": str(row.get("score", "")).strip(),
                "delta_vs_b0": str(row.get("delta_vs_b0", "")).strip(),
                "delta_vs_b1": str(row.get("delta_vs_b1", "")).strip(),
                "delta_vs_negative_ref": str(row.get("delta_vs_negative_ref", "")).strip(),
                "better_than_b0": str(row.get("better_than_b0", "")).strip(),
                "better_than_b1": str(row.get("better_than_b1", "")).strip(),
                "better_than_negative_ref": str(row.get("better_than_negative_ref", "")).strip(),
                "yield_metric": str(row.get("yield_metric", "")).strip(),
                "train_mean_nrmse": str(row.get("train_mean_nrmse", "")).strip(),
                "valid_mean_nrmse": str(row.get("valid_mean_nrmse", "")).strip(),
                "all_mean_nrmse": str(row.get("all_mean_nrmse", "")).strip(),
                "train_yield_nrmse": str(row.get("train_yield_nrmse", "")).strip(),
                "train_yield_bias": str(row.get("train_yield_bias", "")).strip(),
                "valid_yield_nrmse": str(row.get("valid_yield_nrmse", "")).strip(),
                "valid_yield_bias": str(row.get("valid_yield_bias", "")).strip(),
                "duration_sec": str(row.get("duration_sec", "")).strip(),
                "executed_at": str(row.get("executed_at", "")).strip(),
                "workspace_dir": str(row.get("workspace_dir", "")).strip(),
            }
        )
    return leaderboard_rows


def build_main_matrix_dimension_summary_rows(leaderboard_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    summary_rows: list[dict[str, str]] = []
    for dimension in MAIN_MATRIX_REPORT_DIMENSIONS:
        grouped_rows: dict[str, list[dict[str, str]]] = {}
        for row in leaderboard_rows:
            value = str(row.get(dimension, "")).strip()
            if not value:
                continue
            grouped_rows.setdefault(value, []).append(row)
        for value, rows in sorted(grouped_rows.items()):
            best_row = min(rows, key=report_score_sort_key)
            scores = [parse_tsv_float(row, "score") for row in rows]
            valid_scores = [score for score in scores if math.isfinite(score)]
            ok_runs = [row for row in rows if str(row.get("status", "")).strip().lower() == "ok"]
            summary_rows.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "total_runs": str(len(rows)),
                    "ok_runs": str(len(ok_runs)),
                    "failed_runs": str(len(rows) - len(ok_runs)),
                    "best_report_rank": str(best_row.get("report_rank", "")).strip(),
                    "best_score_rank": str(best_row.get("score_rank", "")).strip(),
                    "best_score": str(best_row.get("score", "")).strip(),
                    "mean_score": format_float_tsv(sum(valid_scores) / len(valid_scores)) if valid_scores else "",
                    "median_score": format_float_tsv(compute_report_median(valid_scores)) if valid_scores else "",
                    "worst_score": format_float_tsv(max(valid_scores)) if valid_scores else "",
                    "better_than_b0_count": str(
                        sum(str(row.get("better_than_b0", "")).strip().lower() == "true" for row in rows)
                    ),
                    "better_than_b1_count": str(
                        sum(str(row.get("better_than_b1", "")).strip().lower() == "true" for row in rows)
                    ),
                    "better_than_negative_ref_count": str(
                        sum(
                            str(row.get("better_than_negative_ref", "")).strip().lower() == "true"
                            for row in rows
                        )
                    ),
                    "best_combo_key": str(best_row.get("combo_key", "")).strip(),
                    "best_run_id": str(best_row.get("run_id", "")).strip(),
                    "best_plan": str(best_row.get("plan", "")).strip(),
                    "best_budget": str(best_row.get("budget", "")).strip(),
                    "best_weight": str(best_row.get("weight", "")).strip(),
                    "best_engine": str(best_row.get("engine", "")).strip(),
                    "best_sequence": str(best_row.get("sequence", "")).strip(),
                    "best_grouping": str(best_row.get("grouping", "")).strip(),
                    "best_status": str(best_row.get("status", "")).strip(),
                }
            )
    return sorted(
        summary_rows,
        key=lambda item: (
            MAIN_MATRIX_REPORT_DIMENSIONS.index(str(item.get("dimension", "")).strip()),
            parse_tsv_float({"score": str(item.get("best_score", ""))}, "score"),
            parse_tsv_int({"score_rank": str(item.get("best_report_rank", ""))}, "score_rank", default=10**9),
            str(item.get("value", "")).strip(),
        ),
    )


def build_main_matrix_baseline_summary_rows(leaderboard_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    summary_rows: list[dict[str, str]] = []
    for comparison_target, delta_field, comparison_flag in MAIN_MATRIX_BASELINE_TARGETS:
        comparable_rows = [
            row for row in leaderboard_rows if math.isfinite(parse_tsv_float(row, delta_field))
        ]
        deltas = [parse_tsv_float(row, delta_field) for row in comparable_rows]
        better_count = sum(parse_tsv_bool(row, comparison_flag) for row in comparable_rows)
        best_row = (
            min(
                comparable_rows,
                key=lambda item: (
                    parse_tsv_float(item, delta_field),
                    report_score_sort_key(item),
                ),
            )
            if comparable_rows
            else {}
        )
        summary_rows.append(
            {
                "comparison_target": comparison_target,
                "delta_field": delta_field,
                "total_runs": str(len(leaderboard_rows)),
                "comparable_runs": str(len(comparable_rows)),
                "better_count": str(better_count),
                "better_rate": format_float_tsv(
                    better_count / len(comparable_rows) if comparable_rows else float("nan")
                ),
                "best_delta": format_float_tsv(min(deltas)) if deltas else "",
                "mean_delta": format_float_tsv(sum(deltas) / len(deltas)) if deltas else "",
                "median_delta": format_float_tsv(compute_report_median(deltas)) if deltas else "",
                "worst_delta": format_float_tsv(max(deltas)) if deltas else "",
                "best_combo_key": str(best_row.get("combo_key", "")).strip(),
                "best_run_id": str(best_row.get("run_id", "")).strip(),
                "best_score": str(best_row.get("score", "")).strip(),
                "best_valid_mean_nrmse": str(best_row.get("valid_mean_nrmse", "")).strip(),
            }
        )
    return summary_rows


def build_main_matrix_baseline_detail_rows(leaderboard_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    detail_rows: list[dict[str, str]] = []
    for comparison_target, delta_field, comparison_flag in MAIN_MATRIX_BASELINE_TARGETS:
        comparable_rows = [
            row for row in leaderboard_rows if math.isfinite(parse_tsv_float(row, delta_field))
        ]
        sorted_rows = sorted(
            comparable_rows,
            key=lambda item: (
                parse_tsv_float(item, delta_field),
                report_score_sort_key(item),
            ),
        )
        for comparison_rank, row in enumerate(sorted_rows, start=1):
            detail_rows.append(
                {
                    "comparison_target": comparison_target,
                    "delta_field": delta_field,
                    "comparison_rank": str(comparison_rank),
                    "comparison_passed": str(row.get(comparison_flag, "")).strip(),
                    "report_rank": str(row.get("report_rank", "")).strip(),
                    "score_rank": str(row.get("score_rank", "")).strip(),
                    "combo_key": str(row.get("combo_key", "")).strip(),
                    "run_id": str(row.get("run_id", "")).strip(),
                    "plan": str(row.get("plan", "")).strip(),
                    "weight": str(row.get("weight", "")).strip(),
                    "engine": str(row.get("engine", "")).strip(),
                    "budget": str(row.get("budget", "")).strip(),
                    "sequence": str(row.get("sequence", "")).strip(),
                    "grouping": str(row.get("grouping", "")).strip(),
                    "status": str(row.get("status", "")).strip(),
                    "validation_enabled": str(row.get("validation_enabled", "")).strip(),
                    "score": str(row.get("score", "")).strip(),
                    "comparison_delta": str(row.get(delta_field, "")).strip(),
                    "valid_mean_nrmse": str(row.get("valid_mean_nrmse", "")).strip(),
                    "train_mean_nrmse": str(row.get("train_mean_nrmse", "")).strip(),
                    "all_mean_nrmse": str(row.get("all_mean_nrmse", "")).strip(),
                    "executed_at": str(row.get("executed_at", "")).strip(),
                }
            )
    return detail_rows


def build_main_matrix_key_indicator_table_rows(
    paper_rows: list[dict[str, str]],
    *,
    comparison_target: str,
) -> list[dict[str, str]]:
    indicator_specs = (
        ("score", "Score"),
        ("valid_mean_nrmse", "Valid Mean NRMSE"),
        ("comparison_delta", f"Δ vs {comparison_target}"),
        ("train_mean_nrmse", "Train Mean NRMSE"),
        ("all_mean_nrmse", "All Mean NRMSE"),
    )
    indicator_rows: list[dict[str, str]] = []
    for indicator_key, indicator_label in indicator_specs:
        numeric_rows = [row for row in paper_rows if math.isfinite(parse_tsv_float(row, indicator_key))]
        values = [parse_tsv_float(row, indicator_key) for row in numeric_rows]
        best_row = (
            min(
                numeric_rows,
                key=lambda item: (
                    parse_tsv_float(item, indicator_key),
                    paper_row_sort_key(item, "comparison_delta"),
                ),
            )
            if numeric_rows
            else {}
        )
        indicator_rows.append(
            {
                "selection_scope": "paper_selected",
                "comparison_target": comparison_target,
                "indicator_key": indicator_key,
                "indicator_label": indicator_label,
                "available_runs": str(len(numeric_rows)),
                "best_value": format_float_tsv(min(values)) if values else "",
                "median_value": format_float_tsv(compute_report_median(values)) if values else "",
                "best_combo_key": str(best_row.get("combo_key", "")).strip(),
                "best_run_id": str(best_row.get("run_id", "")).strip(),
                "best_engine": str(best_row.get("engine", "")).strip(),
                "best_weight": str(best_row.get("weight", "")).strip(),
                "best_budget": str(best_row.get("budget", "")).strip(),
                "best_validation_enabled": str(best_row.get("validation_enabled", "")).strip(),
            }
        )
    return indicator_rows


def build_main_matrix_baseline_winner_rows(leaderboard_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    winner_rows: list[dict[str, str]] = []
    for comparison_target, delta_field, _comparison_flag in MAIN_MATRIX_BASELINE_TARGETS:
        comparable_rows = [
            row for row in leaderboard_rows if math.isfinite(parse_tsv_float(row, delta_field))
        ]
        best_row = (
            min(
                comparable_rows,
                key=lambda item: (
                    parse_tsv_float(item, delta_field),
                    report_score_sort_key(item),
                ),
            )
            if comparable_rows
            else {}
        )
        winner_rows.append(
            {
                "comparison_target": comparison_target,
                "delta_field": delta_field,
                "winner_report_rank": str(best_row.get("report_rank", "")).strip(),
                "winner_combo_key": str(best_row.get("combo_key", "")).strip(),
                "winner_run_id": str(best_row.get("run_id", "")).strip(),
                "winner_plan": str(best_row.get("plan", "")).strip(),
                "winner_score": str(best_row.get("score", "")).strip(),
                "winner_valid_mean_nrmse": str(best_row.get("valid_mean_nrmse", "")).strip(),
                "winner_delta": str(best_row.get(delta_field, "")).strip(),
                "winner_engine": str(best_row.get("engine", "")).strip(),
                "winner_weight": str(best_row.get("weight", "")).strip(),
                "winner_budget": str(best_row.get("budget", "")).strip(),
                "winner_sequence": str(best_row.get("sequence", "")).strip(),
                "winner_grouping": str(best_row.get("grouping", "")).strip(),
                "winner_validation_enabled": str(best_row.get("validation_enabled", "")).strip(),
                "winner_status": str(best_row.get("status", "")).strip(),
            }
        )
    return winner_rows


def build_main_matrix_metric_snapshot_rows(
    metric_scope_rows: list[tuple[str, list[dict[str, str]]]],
) -> list[dict[str, str]]:
    snapshot_rows: list[dict[str, str]] = []
    for scope, rows in metric_scope_rows:
        scope_label = MAIN_MATRIX_METRIC_SCOPE_LABELS.get(scope, scope.replace("_", " ").title())
        for metric_key, metric_label in MAIN_MATRIX_METRIC_SNAPSHOT_SPECS:
            numeric_rows = [
                row for row in rows if math.isfinite(parse_tsv_float(row, metric_key))
            ]
            values = [parse_tsv_float(row, metric_key) for row in numeric_rows]
            best_row = (
                min(
                    numeric_rows,
                    key=lambda item: (
                        parse_tsv_float(item, metric_key),
                        paper_row_sort_key(item, metric_key),
                    ),
                )
                if numeric_rows
                else {}
            )
            snapshot_rows.append(
                {
                    "scope": scope,
                    "scope_label": scope_label,
                    "metric_key": metric_key,
                    "metric_label": metric_label,
                    "available_runs": str(len(numeric_rows)),
                    "best_value": format_float_tsv(min(values)) if values else "",
                    "mean_value": format_float_tsv(sum(values) / len(values)) if values else "",
                    "median_value": format_float_tsv(compute_report_median(values)) if values else "",
                    "worst_value": format_float_tsv(max(values)) if values else "",
                    "best_combo_key": str(best_row.get("combo_key", "")).strip(),
                    "best_run_id": str(best_row.get("run_id", "")).strip(),
                }
            )
    return sorted(
        snapshot_rows,
        key=lambda item: (
            MAIN_MATRIX_METRIC_SCOPE_ORDER.index(str(item.get("scope", "")).strip())
            if str(item.get("scope", "")).strip() in MAIN_MATRIX_METRIC_SCOPE_ORDER
            else len(MAIN_MATRIX_METRIC_SCOPE_ORDER),
            next(
                (
                    index
                    for index, (metric_key, _) in enumerate(MAIN_MATRIX_METRIC_SNAPSHOT_SPECS)
                    if metric_key == str(item.get("metric_key", "")).strip()
                ),
                len(MAIN_MATRIX_METRIC_SNAPSHOT_SPECS),
            ),
        ),
    )


def build_main_matrix_paper_summary_rows(
    paper_rows: list[dict[str, str]],
    *,
    comparison_target: str,
) -> list[dict[str, str]]:
    score_values = [
        parse_tsv_float(row, "score") for row in paper_rows if math.isfinite(parse_tsv_float(row, "score"))
    ]
    valid_values = [
        parse_tsv_float(row, "valid_mean_nrmse")
        for row in paper_rows
        if math.isfinite(parse_tsv_float(row, "valid_mean_nrmse"))
    ]
    comparison_values = [
        parse_tsv_float(row, "comparison_delta")
        for row in paper_rows
        if math.isfinite(parse_tsv_float(row, "comparison_delta"))
    ]
    best_row = min(paper_rows, key=lambda item: paper_row_sort_key(item, "comparison_delta")) if paper_rows else {}
    better_than_target_count = sum(parse_tsv_bool(row, "comparison_passed") for row in paper_rows)
    return [
        {
            "selection_scope": "paper_selected",
            "comparison_target": comparison_target,
            "selected_runs": str(len(paper_rows)),
            "validation_runs": str(sum(parse_tsv_bool(row, "validation_enabled") for row in paper_rows)),
            "best_score": format_float_tsv(min(score_values)) if score_values else "",
            "median_score": format_float_tsv(compute_report_median(score_values)) if score_values else "",
            "best_valid_mean_nrmse": format_float_tsv(min(valid_values)) if valid_values else "",
            "median_valid_mean_nrmse": format_float_tsv(compute_report_median(valid_values)) if valid_values else "",
            "best_comparison_delta": format_float_tsv(min(comparison_values)) if comparison_values else "",
            "median_comparison_delta": format_float_tsv(compute_report_median(comparison_values))
            if comparison_values
            else "",
            "better_than_target_count": str(better_than_target_count),
            "better_than_target_rate": format_float_tsv(
                better_than_target_count / len(paper_rows) if paper_rows else float("nan")
            ),
            "best_combo_key": str(best_row.get("combo_key", "")).strip(),
            "best_run_id": str(best_row.get("run_id", "")).strip(),
            "best_engine": str(best_row.get("engine", "")).strip(),
            "best_weight": str(best_row.get("weight", "")).strip(),
        }
    ]


def build_main_matrix_appendix_index_rows(
    appendix_outputs: list[tuple[str, str, str, Path, list[dict[str, str]], str]],
    *,
    top_k: int,
) -> list[dict[str, str]]:
    index_rows: list[dict[str, str]] = []
    for output_key, panel_title, selection_scope, tsv_path, rows, grouping_field in appendix_outputs:
        panel_values = sorted(
            {
                str(row.get("panel_value", "")).strip() or str(row.get(grouping_field, "")).strip()
                for row in rows
                if str(row.get("panel_value", "")).strip() or str(row.get(grouping_field, "")).strip()
            }
        )
        index_rows.append(
            {
                "panel_key": output_key,
                "panel_title": panel_title,
                "output_key": output_key,
                "tsv_path": str(tsv_path.resolve()),
                "selection_scope": selection_scope,
                "grouping_field": grouping_field,
                "panel_values": ",".join(panel_values) if panel_values else "all",
                "row_count": str(len(rows)),
                "top_k": str(max(1, top_k)),
            }
        )
    return index_rows


def build_main_matrix_report_output_map() -> dict[str, Path]:
    output_map = {
        "report": MAIN_MATRIX_REPORT_MD_PATH,
        "leaderboard": MAIN_MATRIX_LEADERBOARD_TSV_PATH,
        "dimension_summary": MAIN_MATRIX_DIMENSION_SUMMARY_TSV_PATH,
        "baseline_summary": MAIN_MATRIX_BASELINE_SUMMARY_TSV_PATH,
        "baseline_detail": MAIN_MATRIX_BASELINE_DETAIL_TSV_PATH,
        "key_indicator_table": MAIN_MATRIX_KEY_INDICATOR_TABLE_TSV_PATH,
        "baseline_winners": MAIN_MATRIX_BASELINE_WINNERS_TSV_PATH,
        "metric_snapshot": MAIN_MATRIX_METRIC_SNAPSHOT_TSV_PATH,
        "paper_summary": MAIN_MATRIX_PAPER_SUMMARY_TSV_PATH,
        "protocol_overview": MAIN_MATRIX_PROTOCOL_OVERVIEW_TSV_PATH,
        "protocol_dimension_summary": MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_TSV_PATH,
        "protocol_nested_dimension_summary": MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_TSV_PATH,
        "protocol_hotspot_summary": MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_TSV_PATH,
        "protocol_reason_summary": MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH,
        "quality_gate": MAIN_MATRIX_QUALITY_GATE_TSV_PATH,
        "appendix_index": MAIN_MATRIX_APPENDIX_INDEX_TSV_PATH,
        "protocol_paper_table": MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH,
        "paper_main_table": MAIN_MATRIX_PAPER_MAIN_TABLE_TSV_PATH,
        "paper_appendix_table": MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH,
        "paper_table": MAIN_MATRIX_PAPER_TABLE_TSV_PATH,
        "topk_overall": MAIN_MATRIX_TOPK_OVERALL_TSV_PATH,
        "topk_by_engine": MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH,
        "topk_by_weight": MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH,
        "topk_by_sequence": MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH,
        "topk_by_grouping": MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH,
        "topk_validation_only": MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH,
        "topk_by_budget": MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH,
        "topk_by_validation_budget": MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH,
        "topk_improvement": MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH,
    }
    return {output_key: output_map[output_key] for output_key in MAIN_MATRIX_REPORT_OUTPUT_KEYS}


def build_main_matrix_appendix_output_map() -> dict[str, Path]:
    output_map = {
        "paper_appendix_table": MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH,
        "protocol_paper_table": MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH,
        "protocol_reason_summary": MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH,
        "topk_by_engine": MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH,
        "topk_by_weight": MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH,
        "topk_by_sequence": MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH,
        "topk_by_grouping": MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH,
        "topk_validation_only": MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH,
        "topk_by_budget": MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH,
        "topk_by_validation_budget": MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH,
        "topk_improvement": MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH,
    }
    return {output_key: output_map[output_key] for output_key in MAIN_MATRIX_APPENDIX_PANEL_KEYS}


def build_main_matrix_appendix_row_map(
    *,
    paper_rows: list[dict[str, str]],
    protocol_panel_rows: list[dict[str, str]],
    protocol_reason_rows: list[dict[str, str]],
    topk_by_engine_rows: list[dict[str, str]],
    topk_by_weight_rows: list[dict[str, str]],
    topk_by_sequence_rows: list[dict[str, str]],
    topk_by_grouping_rows: list[dict[str, str]],
    validation_only_rows: list[dict[str, str]],
    topk_by_budget_rows: list[dict[str, str]],
    topk_by_validation_budget_rows: list[dict[str, str]],
    topk_improvement_rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    row_map = {
        "paper_appendix_table": paper_rows,
        "protocol_paper_table": protocol_panel_rows,
        "protocol_reason_summary": protocol_reason_rows,
        "topk_by_engine": topk_by_engine_rows,
        "topk_by_weight": topk_by_weight_rows,
        "topk_by_sequence": topk_by_sequence_rows,
        "topk_by_grouping": topk_by_grouping_rows,
        "topk_validation_only": validation_only_rows,
        "topk_by_budget": topk_by_budget_rows,
        "topk_by_validation_budget": topk_by_validation_budget_rows,
        "topk_improvement": topk_improvement_rows,
    }
    return {output_key: row_map[output_key] for output_key in MAIN_MATRIX_APPENDIX_PANEL_KEYS}


def build_main_matrix_appendix_panel_inputs(
    *,
    paper_rows: list[dict[str, str]],
    protocol_panel_rows: list[dict[str, str]],
    protocol_reason_rows: list[dict[str, str]],
    topk_by_engine_rows: list[dict[str, str]],
    topk_by_weight_rows: list[dict[str, str]],
    topk_by_sequence_rows: list[dict[str, str]],
    topk_by_grouping_rows: list[dict[str, str]],
    validation_only_rows: list[dict[str, str]],
    topk_by_budget_rows: list[dict[str, str]],
    topk_by_validation_budget_rows: list[dict[str, str]],
    topk_improvement_rows: list[dict[str, str]],
) -> list[tuple[str, str, str, Path, list[dict[str, str]], str]]:
    output_map = build_main_matrix_appendix_output_map()
    row_map = build_main_matrix_appendix_row_map(
        paper_rows=paper_rows,
        protocol_panel_rows=protocol_panel_rows,
        protocol_reason_rows=protocol_reason_rows,
        topk_by_engine_rows=topk_by_engine_rows,
        topk_by_weight_rows=topk_by_weight_rows,
        topk_by_sequence_rows=topk_by_sequence_rows,
        topk_by_grouping_rows=topk_by_grouping_rows,
        validation_only_rows=validation_only_rows,
        topk_by_budget_rows=topk_by_budget_rows,
        topk_by_validation_budget_rows=topk_by_validation_budget_rows,
        topk_improvement_rows=topk_improvement_rows,
    )
    return [
        (
            output_key,
            panel_title,
            selection_scope,
            output_map[output_key],
            row_map[output_key],
            grouping_field,
        )
        for output_key, panel_title, selection_scope, grouping_field in MAIN_MATRIX_APPENDIX_PANEL_SPECS
    ]


def build_protocol_artifact_rows_by_run_id(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {
        run_id: row
        for row in rows
        if (run_id := str(row.get("run_id", "")).strip())
    }


def summarize_main_matrix_protocol_rows(
    selection_scope: str,
    rows: list[dict[str, str]],
    protocol_rows_by_run_id: dict[str, dict[str, str]],
) -> dict[str, str]:
    total_runs = len(rows)
    manifest_runs = 0
    contract_runs = 0
    ok_contract_runs = 0
    degraded_contract_runs = 0
    missing_contract_runs = 0
    rows_with_warnings = 0
    rows_with_errors = 0
    total_issue_count = 0
    rows_with_dropped_groups = 0
    rows_with_weight_fallbacks = 0
    rows_with_zero_weight_observations = 0
    total_dropped_group_count = 0
    total_weight_fallback_count = 0
    total_zero_weight_observation_count = 0
    active_metric_counts: list[float] = []
    active_observation_counts: list[float] = []
    for row in rows:
        protocol_row = protocol_rows_by_run_id.get(str(row.get("run_id", "")).strip(), {})
        manifest_path = str(protocol_row.get("run_manifest_path", "")).strip()
        contract_path = str(protocol_row.get("contract_report_path", "")).strip()
        contract_status = str(protocol_row.get("contract_status", "")).strip().lower()
        if manifest_path:
            manifest_runs += 1
        if contract_path:
            contract_runs += 1
        else:
            missing_contract_runs += 1
        if contract_status == "ok":
            ok_contract_runs += 1
        elif contract_status:
            degraded_contract_runs += 1
        warning_count = parse_tsv_int(protocol_row, "warning_count")
        error_count = parse_tsv_int(protocol_row, "error_count")
        issue_count = parse_tsv_int(protocol_row, "issue_count")
        if warning_count > 0:
            rows_with_warnings += 1
        if error_count > 0:
            rows_with_errors += 1
        total_issue_count += issue_count
        dropped_group_count = parse_tsv_int(protocol_row, "dropped_group_count")
        weight_fallback_count = parse_tsv_int(protocol_row, "weight_fallback_count")
        zero_weight_observation_count = parse_tsv_int(protocol_row, "zero_weight_observation_count")
        if dropped_group_count > 0:
            rows_with_dropped_groups += 1
        if weight_fallback_count > 0:
            rows_with_weight_fallbacks += 1
        if zero_weight_observation_count > 0:
            rows_with_zero_weight_observations += 1
        total_dropped_group_count += dropped_group_count
        total_weight_fallback_count += weight_fallback_count
        total_zero_weight_observation_count += zero_weight_observation_count
        active_metric_count = parse_tsv_float(protocol_row, "active_metric_count")
        active_observation_count = parse_tsv_float(protocol_row, "active_observation_count")
        if math.isfinite(active_metric_count):
            active_metric_counts.append(active_metric_count)
        if math.isfinite(active_observation_count):
            active_observation_counts.append(active_observation_count)
    return {
        "selection_scope": selection_scope,
        "total_runs": str(total_runs),
        "manifest_runs": str(manifest_runs),
        "contract_runs": str(contract_runs),
        "ok_contract_runs": str(ok_contract_runs),
        "degraded_contract_runs": str(degraded_contract_runs),
        "missing_contract_runs": str(missing_contract_runs),
        "rows_with_warnings": str(rows_with_warnings),
        "rows_with_errors": str(rows_with_errors),
        "total_issue_count": str(total_issue_count),
        "rows_with_dropped_groups": str(rows_with_dropped_groups),
        "rows_with_weight_fallbacks": str(rows_with_weight_fallbacks),
        "rows_with_zero_weight_observations": str(rows_with_zero_weight_observations),
        "total_dropped_group_count": str(total_dropped_group_count),
        "total_weight_fallback_count": str(total_weight_fallback_count),
        "total_zero_weight_observation_count": str(total_zero_weight_observation_count),
        "dropped_group_run_rate": format_float_tsv(
            rows_with_dropped_groups / total_runs if total_runs else float("nan")
        ),
        "weight_fallback_run_rate": format_float_tsv(
            rows_with_weight_fallbacks / total_runs if total_runs else float("nan")
        ),
        "zero_weight_observation_run_rate": format_float_tsv(
            rows_with_zero_weight_observations / total_runs if total_runs else float("nan")
        ),
        "mean_active_metric_count": format_float_tsv(
            sum(active_metric_counts) / len(active_metric_counts) if active_metric_counts else float("nan")
        ),
        "mean_active_observation_count": format_float_tsv(
            sum(active_observation_counts) / len(active_observation_counts)
            if active_observation_counts
            else float("nan")
        ),
    }


def build_main_matrix_protocol_overview_rows(
    scoped_rows: list[tuple[str, list[dict[str, str]]]],
    protocol_rows_by_run_id: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    return [
        summarize_main_matrix_protocol_rows(selection_scope, rows, protocol_rows_by_run_id)
        for selection_scope, rows in scoped_rows
    ]


def build_main_matrix_protocol_dimension_summary_rows(
    scoped_rows: list[tuple[str, list[dict[str, str]]]],
    protocol_rows_by_run_id: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    dimension_rows: list[dict[str, str]] = []
    scope_order = {scope: index for index, (scope, _) in enumerate(scoped_rows)}
    for selection_scope, rows in scoped_rows:
        for dimension in MAIN_MATRIX_REPORT_DIMENSIONS:
            grouped_rows: dict[str, list[dict[str, str]]] = {}
            for row in rows:
                value = str(row.get(dimension, "")).strip()
                if not value:
                    continue
                grouped_rows.setdefault(value, []).append(row)
            for value, grouped_dimension_rows in sorted(grouped_rows.items()):
                dimension_rows.append(
                    {
                        "dimension": dimension,
                        "value": value,
                        **summarize_main_matrix_protocol_rows(
                            selection_scope,
                            grouped_dimension_rows,
                            protocol_rows_by_run_id,
                        ),
                    }
                )
    return sorted(
        dimension_rows,
        key=lambda row: (
            scope_order.get(str(row.get("selection_scope", "")).strip(), len(scope_order)),
            MAIN_MATRIX_REPORT_DIMENSIONS.index(str(row.get("dimension", "")).strip()),
            str(row.get("value", "")).strip(),
        ),
    )


def iter_main_matrix_nested_dimension_combinations() -> list[tuple[str, ...]]:
    return [
        dimension_combo
        for dimension_depth in range(2, len(MAIN_MATRIX_REPORT_DIMENSIONS) + 1)
        for dimension_combo in combinations(MAIN_MATRIX_REPORT_DIMENSIONS, dimension_depth)
    ]


def build_main_matrix_protocol_nested_dimension_summary_rows(
    scoped_rows: list[tuple[str, list[dict[str, str]]]],
    protocol_rows_by_run_id: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    nested_rows: list[dict[str, str]] = []
    scope_order = {scope: index for index, (scope, _) in enumerate(scoped_rows)}
    dimension_combinations = iter_main_matrix_nested_dimension_combinations()
    combo_order = {dimension_combo: index for index, dimension_combo in enumerate(dimension_combinations)}
    for selection_scope, rows in scoped_rows:
        for dimension_combo in dimension_combinations:
            grouped_rows: dict[tuple[str, ...], list[dict[str, str]]] = {}
            for row in rows:
                values: list[str] = []
                for dimension in dimension_combo:
                    value = str(row.get(dimension, "")).strip()
                    if not value:
                        values = []
                        break
                    values.append(value)
                if not values:
                    continue
                grouped_rows.setdefault(tuple(values), []).append(row)
            for value_tuple, grouped_dimension_rows in sorted(grouped_rows.items()):
                nested_rows.append(
                    {
                        "dimension_depth": str(len(dimension_combo)),
                        "dimensions": "|".join(dimension_combo),
                        "values": "|".join(value_tuple),
                        "slice_label": ", ".join(
                            f"{dimension}={value}"
                            for dimension, value in zip(dimension_combo, value_tuple, strict=False)
                        ),
                        **summarize_main_matrix_protocol_rows(
                            selection_scope,
                            grouped_dimension_rows,
                            protocol_rows_by_run_id,
                        ),
                    }
                )
    return sorted(
        nested_rows,
        key=lambda row: (
            scope_order.get(str(row.get("selection_scope", "")).strip(), len(scope_order)),
            parse_tsv_int(row, "dimension_depth", default=10**9),
            combo_order.get(tuple(str(row.get("dimensions", "")).split("|")), len(combo_order)),
            str(row.get("values", "")).strip(),
        ),
    )


def build_main_matrix_protocol_reason_summary_rows(
    scoped_rows: list[tuple[str, list[dict[str, str]]]],
    protocol_rows_by_run_id: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    reason_kind_order = {
        "dropped_group": 0,
        "weight_fallback": 1,
        "zero_weight_observation": 2,
    }
    field_specs = (
        ("dropped_group", "dropped_groups"),
        ("weight_fallback", "weight_fallbacks"),
        ("zero_weight_observation", "zero_weight_observations"),
    )
    rows: list[dict[str, str]] = []
    for selection_scope, selected_rows in scoped_rows:
        aggregates: dict[tuple[str, str], dict[str, object]] = {}
        for row in selected_rows:
            run_id = str(row.get("run_id", "")).strip()
            protocol_row = protocol_rows_by_run_id.get(run_id, {})
            for reason_kind, field_name in field_specs:
                for entity, reason in _parse_tsv_record_summary(str(protocol_row.get(field_name, "")).strip()):
                    normalized_reason = reason or "unspecified"
                    aggregate = aggregates.setdefault(
                        (reason_kind, normalized_reason),
                        {
                            "affected_runs": set(),
                            "affected_entities": [],
                            "example_run_ids": [],
                            "total_occurrences": 0,
                        },
                    )
                    cast(set[str], aggregate["affected_runs"]).add(run_id)
                    if entity and entity not in cast(list[str], aggregate["affected_entities"]):
                        cast(list[str], aggregate["affected_entities"]).append(entity)
                    if run_id and run_id not in cast(list[str], aggregate["example_run_ids"]):
                        cast(list[str], aggregate["example_run_ids"]).append(run_id)
                    aggregate["total_occurrences"] = cast(int, aggregate["total_occurrences"]) + 1
        for (reason_kind, reason), aggregate in sorted(
            aggregates.items(),
            key=lambda item: (
                reason_kind_order.get(item[0][0], len(reason_kind_order)),
                -len(cast(set[str], item[1]["affected_runs"])),
                -cast(int, item[1]["total_occurrences"]),
                item[0][1],
            ),
        ):
            rows.append(
                {
                    "selection_scope": selection_scope,
                    "reason_kind": reason_kind,
                    "reason": reason,
                    "affected_runs": str(len(cast(set[str], aggregate["affected_runs"]))),
                    "total_occurrences": str(cast(int, aggregate["total_occurrences"])),
                    "affected_entities": ",".join(cast(list[str], aggregate["affected_entities"])[:5]),
                    "example_run_ids": ",".join(cast(list[str], aggregate["example_run_ids"])[:5]),
                }
            )
    return rows


def build_main_matrix_protocol_panel_rows(
    paper_rows: list[dict[str, str]],
    protocol_rows_by_run_id: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    panel_rows: list[dict[str, str]] = []
    panel_order = {"ok": 0, "degraded": 1, "missing": 2}
    for paper_row in paper_rows:
        protocol_row = protocol_rows_by_run_id.get(str(paper_row.get("run_id", "")).strip(), {})
        contract_status = str(protocol_row.get("contract_status", "")).strip().lower() or "missing"
        panel_rows.append(
            {
                "panel": "protocol_status",
                "panel_value": contract_status,
                "panel_rank": "",
                "paper_rank": str(paper_row.get("paper_rank", "")).strip(),
                "report_rank": str(paper_row.get("report_rank", "")).strip(),
                "combo_key": str(paper_row.get("combo_key", "")).strip(),
                "run_id": str(paper_row.get("run_id", "")).strip(),
                "score": str(paper_row.get("score", "")).strip(),
                "valid_mean_nrmse": str(paper_row.get("valid_mean_nrmse", "")).strip(),
                "contract_status": contract_status,
                "issue_count": str(protocol_row.get("issue_count", "")).strip() or "0",
                "warning_count": str(protocol_row.get("warning_count", "")).strip() or "0",
                "error_count": str(protocol_row.get("error_count", "")).strip() or "0",
                "active_metric_count": str(protocol_row.get("active_metric_count", "")).strip(),
                "active_observation_count": str(protocol_row.get("active_observation_count", "")).strip(),
                "dropped_group_count": str(protocol_row.get("dropped_group_count", "")).strip(),
                "weight_fallback_count": str(protocol_row.get("weight_fallback_count", "")).strip(),
                "zero_weight_observation_count": str(protocol_row.get("zero_weight_observation_count", "")).strip(),
                "active_groups": str(protocol_row.get("active_groups", "")).strip(),
                "dropped_groups": str(protocol_row.get("dropped_groups", "")).strip(),
                "weight_fallbacks": str(protocol_row.get("weight_fallbacks", "")).strip(),
                "zero_weight_observations": str(protocol_row.get("zero_weight_observations", "")).strip(),
                "requested_summary_metrics": str(protocol_row.get("requested_summary_metrics", "")).strip(),
                "resolved_summary_metrics": str(protocol_row.get("resolved_summary_metrics", "")).strip(),
                "requested_t_vars": str(protocol_row.get("requested_t_vars", "")).strip(),
                "resolved_t_vars": str(protocol_row.get("resolved_t_vars", "")).strip(),
                "protocol_weight": str(protocol_row.get("protocol_weight", "")).strip(),
                "protocol_engine": str(protocol_row.get("protocol_engine", "")).strip(),
                "protocol_budget": str(protocol_row.get("protocol_budget", "")).strip(),
                "protocol_sequence": str(protocol_row.get("protocol_sequence", "")).strip(),
                "protocol_grouping": str(protocol_row.get("protocol_grouping", "")).strip(),
                "filex_name": str(protocol_row.get("filex_name", "")).strip(),
                "crop": str(protocol_row.get("crop", "")).strip(),
                "run_manifest_path": str(protocol_row.get("run_manifest_path", "")).strip(),
                "contract_report_path": str(protocol_row.get("contract_report_path", "")).strip(),
            }
        )
    sorted_rows = sorted(
        panel_rows,
        key=lambda row: (
            panel_order.get(str(row.get("panel_value", "")).strip().lower(), len(panel_order)),
            parse_tsv_int(row, "paper_rank", default=10**6),
            parse_tsv_int(row, "report_rank", default=10**6),
            str(row.get("run_id", "")).strip(),
        ),
    )
    ranks_by_panel: dict[str, int] = {}
    for row in sorted_rows:
        panel_value = str(row.get("panel_value", "")).strip().lower() or "missing"
        ranks_by_panel[panel_value] = ranks_by_panel.get(panel_value, 0) + 1
        row["panel_rank"] = str(ranks_by_panel[panel_value])
    return sorted_rows


def resolve_paper_comparison_target(require_better_than: str) -> tuple[str, str]:
    target = require_better_than.strip().lower() or "b0"
    mapping = {
        "b0": ("delta_vs_b0", "better_than_b0"),
        "b1": ("delta_vs_b1", "better_than_b1"),
        "negative_ref": ("delta_vs_negative_ref", "better_than_negative_ref"),
    }
    return mapping.get(target, mapping["b0"])


def resolve_report_protocol_status_filter(paper_protocol_status: str) -> str:
    normalized = paper_protocol_status.strip().lower()
    if normalized in {"", "auto"}:
        return "auto"
    if normalized in {"any", "ok", "degraded", "missing"}:
        return normalized
    return "auto"


def resolve_protocol_contract_status(
    row: dict[str, str],
    protocol_rows_by_run_id: dict[str, dict[str, str]],
) -> str:
    run_id = str(row.get("run_id", "")).strip()
    protocol_row = protocol_rows_by_run_id.get(run_id, {})
    status = str(protocol_row.get("contract_status", "")).strip().lower()
    return status or "missing"


def filter_rows_by_protocol_status(
    rows: list[dict[str, str]],
    protocol_rows_by_run_id: dict[str, dict[str, str]],
    *,
    paper_protocol_status: str = "auto",
) -> list[dict[str, str]]:
    normalized = resolve_report_protocol_status_filter(paper_protocol_status)
    if normalized == "any":
        return list(rows)
    if normalized == "auto":
        ok_rows = [
            row for row in rows if resolve_protocol_contract_status(row, protocol_rows_by_run_id) == "ok"
        ]
        return ok_rows or list(rows)
    return [
        row for row in rows if resolve_protocol_contract_status(row, protocol_rows_by_run_id) == normalized
    ]


def build_main_matrix_quality_gate_rows(
    *,
    leaderboard_rows: list[dict[str, str]],
    paper_rows: list[dict[str, str]],
    protocol_overview_rows: list[dict[str, str]],
    appendix_index_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    protocol_overview_by_scope = {
        str(row.get("selection_scope", "")).strip(): row for row in protocol_overview_rows
    }

    def append_gate(
        gate_key: str,
        gate_label: str,
        gate_level: str,
        passed: bool,
        expected: str,
        actual: str,
        detail: str,
    ) -> None:
        rows.append(
            {
                "gate_key": gate_key,
                "gate_label": gate_label,
                "gate_level": gate_level,
                "status": "pass" if passed else "fail",
                "expected": expected,
                "actual": actual,
                "detail": detail,
            }
        )

    for gate_key, gate_label, actual_fieldnames, expected_fieldnames in MAIN_MATRIX_PAPER_FACING_SCHEMA_SPECS:
        actual_schema = tuple(actual_fieldnames)
        expected_schema = tuple(expected_fieldnames)
        append_gate(
            gate_key,
            gate_label,
            "required",
            actual_schema == expected_schema,
            "|".join(expected_schema),
            "|".join(actual_schema),
            f"field_count={len(actual_schema)}",
        )

    output_keys = tuple(build_main_matrix_report_output_map())
    append_gate(
        "report_output_contract",
        "Report Output Contract",
        "required",
        output_keys == MAIN_MATRIX_REPORT_OUTPUT_KEYS and len(set(output_keys)) == len(output_keys),
        str(len(MAIN_MATRIX_REPORT_OUTPUT_KEYS)),
        str(len(output_keys)),
        "|".join(output_keys),
    )
    appendix_panel_keys = tuple(str(row.get("panel_key", "")).strip() for row in appendix_index_rows)
    append_gate(
        "appendix_panel_contract",
        "Appendix Panel Contract",
        "required",
        appendix_panel_keys == MAIN_MATRIX_APPENDIX_PANEL_KEYS,
        "|".join(MAIN_MATRIX_APPENDIX_PANEL_KEYS),
        "|".join(appendix_panel_keys),
        f"panel_count={len(appendix_index_rows)}",
    )
    append_gate(
        "leaderboard_rows_present",
        "Leaderboard Rows Present",
        "required",
        len(leaderboard_rows) > 0,
        ">0",
        str(len(leaderboard_rows)),
        "main matrix leaderboard candidate count",
    )
    append_gate(
        "paper_rows_present",
        "Paper Rows Present",
        "required",
        len(paper_rows) > 0,
        ">0",
        str(len(paper_rows)),
        "paper selection after validation and comparison filters",
    )
    paper_protocol_row = protocol_overview_by_scope.get("paper_selected", {})
    paper_missing_contract_runs = parse_tsv_int(paper_protocol_row, "missing_contract_runs")
    paper_degraded_contract_runs = parse_tsv_int(paper_protocol_row, "degraded_contract_runs")
    append_gate(
        "paper_protocol_contract",
        "Paper Protocol Contract",
        "required",
        paper_missing_contract_runs == 0 and paper_degraded_contract_runs == 0 and bool(paper_protocol_row),
        "missing=0,degraded=0",
        f"missing={paper_missing_contract_runs},degraded={paper_degraded_contract_runs}",
        "paper_selected protocol readiness",
    )
    leaderboard_protocol_row = protocol_overview_by_scope.get("leaderboard_all", {})
    leaderboard_missing_contract_runs = parse_tsv_int(leaderboard_protocol_row, "missing_contract_runs")
    leaderboard_degraded_contract_runs = parse_tsv_int(leaderboard_protocol_row, "degraded_contract_runs")
    append_gate(
        "leaderboard_protocol_coverage",
        "Leaderboard Protocol Coverage",
        "advisory",
        leaderboard_missing_contract_runs == 0 and bool(leaderboard_protocol_row),
        "missing=0",
        f"missing={leaderboard_missing_contract_runs},degraded={leaderboard_degraded_contract_runs}",
        "leaderboard_all protocol manifest and contract coverage",
    )
    return rows


def resolve_main_matrix_quality_gate_overall_status(rows: list[dict[str, str]]) -> str:
    if any(
        str(row.get("gate_level", "")).strip().lower() == "required"
        and str(row.get("status", "")).strip().lower() != "pass"
        for row in rows
    ):
        return "fail"
    if any(str(row.get("status", "")).strip().lower() != "pass" for row in rows):
        return "warn"
    return "pass"


def normalize_main_matrix_quality_gate_stop_level(stop_level: str) -> str:
    normalized = stop_level.strip().lower()
    if normalized in {"", "required"}:
        return "required"
    if normalized in {"advisory", "warn"}:
        return "advisory"
    if normalized in {"off", "none"}:
        return "off"
    return "required"


def resolve_main_matrix_quality_gate_batch_decision(
    rows: list[dict[str, str]],
    *,
    stop_level: str = "required",
) -> str:
    normalized = normalize_main_matrix_quality_gate_stop_level(stop_level)
    overall_status = resolve_main_matrix_quality_gate_overall_status(rows)
    if normalized == "off":
        return "go"
    if normalized == "advisory":
        return "stop" if overall_status in {"warn", "fail"} else "go"
    return "stop" if overall_status == "fail" else "go"


def collect_main_matrix_paper_candidate_rows(
    leaderboard_rows: list[dict[str, str]],
    *,
    paper_plan: str = "",
    paper_budget: str = "",
    paper_status: str = "ok",
    paper_yield_metric: str = "",
    paper_require_better_than: str = "",
) -> list[dict[str, str]]:
    _, comparison_flag = resolve_paper_comparison_target(paper_require_better_than)
    candidate_rows: list[dict[str, str]] = []
    for row in leaderboard_rows:
        if paper_plan.strip() and str(row.get("plan", "")).strip().lower() != paper_plan.strip().lower():
            continue
        if paper_budget.strip() and str(row.get("budget", "")).strip().lower() != paper_budget.strip().lower():
            continue
        if paper_status.strip() and str(row.get("status", "")).strip().lower() != paper_status.strip().lower():
            continue
        if paper_yield_metric.strip() and str(row.get("yield_metric", "")).strip().lower() != paper_yield_metric.strip().lower():
            continue
        if not math.isfinite(parse_tsv_float(row, "score")):
            continue
        if paper_require_better_than.strip() and not parse_tsv_bool(row, comparison_flag):
            continue
        candidate_rows.append(row)
    return candidate_rows


def filter_main_matrix_paper_rows(
    leaderboard_rows: list[dict[str, str]],
    *,
    paper_plan: str = "",
    paper_budget: str = "",
    paper_status: str = "ok",
    paper_yield_metric: str = "",
    paper_require_validation: bool = False,
    paper_require_better_than: str = "",
) -> list[dict[str, str]]:
    filtered_rows = collect_main_matrix_paper_candidate_rows(
        leaderboard_rows,
        paper_plan=paper_plan,
        paper_budget=paper_budget,
        paper_status=paper_status,
        paper_yield_metric=paper_yield_metric,
        paper_require_better_than=paper_require_better_than,
    )
    if paper_require_validation:
        return [row for row in filtered_rows if parse_tsv_bool(row, "validation_enabled")]
    validation_rows = [row for row in filtered_rows if parse_tsv_bool(row, "validation_enabled")]
    return validation_rows or filtered_rows


def paper_row_sort_key(row: dict[str, str], comparison_delta_key: str) -> tuple[int, float, int, float, int, float, float, str]:
    score = parse_tsv_float(row, "score")
    valid_mean_nrmse = parse_tsv_float(row, "valid_mean_nrmse")
    comparison_delta = parse_tsv_float(row, comparison_delta_key)
    return (
        0 if math.isfinite(score) else 1,
        score if math.isfinite(score) else float("inf"),
        0 if math.isfinite(valid_mean_nrmse) else 1,
        valid_mean_nrmse if math.isfinite(valid_mean_nrmse) else float("inf"),
        0 if math.isfinite(comparison_delta) else 1,
        comparison_delta if math.isfinite(comparison_delta) else float("inf"),
        -parse_iso_timestamp(str(row.get("executed_at", ""))),
        str(row.get("run_id", "")).strip(),
    )


def build_main_matrix_paper_table_rows(
    leaderboard_rows: list[dict[str, str]],
    *,
    comparison_target: str,
    comparison_delta_key: str,
) -> list[dict[str, str]]:
    paper_rows: list[dict[str, str]] = []
    for paper_rank, row in enumerate(sorted(leaderboard_rows, key=lambda item: paper_row_sort_key(item, comparison_delta_key)), start=1):
        paper_rows.append(
            {
                "paper_rank": str(paper_rank),
                "report_rank": str(row.get("report_rank", "")).strip(),
                "score_rank": str(row.get("score_rank", "")).strip(),
                "combo_key": str(row.get("combo_key", "")).strip(),
                "run_id": str(row.get("run_id", "")).strip(),
                "plan": str(row.get("plan", "")).strip(),
                "weight": str(row.get("weight", "")).strip(),
                "engine": str(row.get("engine", "")).strip(),
                "budget": str(row.get("budget", "")).strip(),
                "sequence": str(row.get("sequence", "")).strip(),
                "grouping": str(row.get("grouping", "")).strip(),
                "status": str(row.get("status", "")).strip(),
                "validation_enabled": str(row.get("validation_enabled", "")).strip(),
                "comparison_target": comparison_target,
                "comparison_delta": str(row.get(comparison_delta_key, "")).strip(),
                "comparison_passed": str(row.get(f"better_than_{comparison_target}", "")).strip(),
                "score": str(row.get("score", "")).strip(),
                "delta_vs_b0": str(row.get("delta_vs_b0", "")).strip(),
                "delta_vs_b1": str(row.get("delta_vs_b1", "")).strip(),
                "delta_vs_negative_ref": str(row.get("delta_vs_negative_ref", "")).strip(),
                "better_than_b0": str(row.get("better_than_b0", "")).strip(),
                "better_than_b1": str(row.get("better_than_b1", "")).strip(),
                "better_than_negative_ref": str(row.get("better_than_negative_ref", "")).strip(),
                "yield_metric": str(row.get("yield_metric", "")).strip(),
                "train_mean_nrmse": str(row.get("train_mean_nrmse", "")).strip(),
                "valid_mean_nrmse": str(row.get("valid_mean_nrmse", "")).strip(),
                "all_mean_nrmse": str(row.get("all_mean_nrmse", "")).strip(),
                "train_yield_nrmse": str(row.get("train_yield_nrmse", "")).strip(),
                "train_yield_bias": str(row.get("train_yield_bias", "")).strip(),
                "valid_yield_nrmse": str(row.get("valid_yield_nrmse", "")).strip(),
                "valid_yield_bias": str(row.get("valid_yield_bias", "")).strip(),
                "duration_sec": str(row.get("duration_sec", "")).strip(),
                "executed_at": str(row.get("executed_at", "")).strip(),
                "workspace_dir": str(row.get("workspace_dir", "")).strip(),
            }
        )
    return paper_rows


def build_main_matrix_paper_main_rows(paper_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "paper_rank": str(row.get("paper_rank", "")).strip(),
            "combo_key": str(row.get("combo_key", "")).strip(),
            "score": str(row.get("score", "")).strip(),
            "valid_mean_nrmse": str(row.get("valid_mean_nrmse", "")).strip(),
            "comparison_delta": str(row.get("comparison_delta", "")).strip(),
            "engine": str(row.get("engine", "")).strip(),
            "weight": str(row.get("weight", "")).strip(),
            "budget": str(row.get("budget", "")).strip(),
            "validation_enabled": str(row.get("validation_enabled", "")).strip(),
            "status": str(row.get("status", "")).strip(),
        }
        for row in paper_rows
    ]


def build_main_matrix_topk_panel_rows(
    paper_rows: list[dict[str, str]],
    *,
    panel: str,
    panel_field: str | None,
    top_k: int,
    comparison_delta_key: str,
    sort_mode: str = "paper",
) -> list[dict[str, str]]:
    if not paper_rows:
        return []
    grouped_rows: dict[str, list[dict[str, str]]] = {}
    if panel_field is None:
        grouped_rows["all"] = list(paper_rows)
    else:
        for row in paper_rows:
            panel_value = str(row.get(panel_field, "")).strip()
            if not panel_value:
                continue
            grouped_rows.setdefault(panel_value, []).append(row)
    panel_rows: list[dict[str, str]] = []
    for panel_value in sorted(grouped_rows):
        rows = grouped_rows[panel_value]
        if sort_mode == "improvement":
            sorted_rows = sorted(
                rows,
                key=lambda item: (
                    0 if math.isfinite(parse_tsv_float(item, comparison_delta_key)) else 1,
                    parse_tsv_float(item, comparison_delta_key)
                    if math.isfinite(parse_tsv_float(item, comparison_delta_key))
                    else float("inf"),
                    paper_row_sort_key(item, comparison_delta_key),
                ),
            )
        else:
            sorted_rows = sorted(rows, key=lambda item: paper_row_sort_key(item, comparison_delta_key))
        for panel_rank, row in enumerate(sorted_rows[: max(1, top_k)], start=1):
            panel_rows.append(
                {
                    "panel": panel,
                    "panel_value": panel_value,
                    "panel_rank": str(panel_rank),
                    **{field: str(row.get(field, "")).strip() for field in MAIN_MATRIX_PAPER_TABLE_FIELDNAMES},
                }
            )
    return panel_rows


def build_main_matrix_validation_budget_panel_rows(
    candidate_paper_rows: list[dict[str, str]],
    *,
    top_k: int,
    comparison_delta_key: str,
) -> list[dict[str, str]]:
    panel_source_rows = [
        {
            **row,
            "validation_budget": (
                f"{'validated' if parse_tsv_bool(row, 'validation_enabled') else 'non_validated'}"
                f"|{str(row.get('budget', '')).strip() or 'unknown'}"
            ),
        }
        for row in candidate_paper_rows
    ]
    return build_main_matrix_topk_panel_rows(
        panel_source_rows,
        panel="validation_budget",
        panel_field="validation_budget",
        top_k=top_k,
        comparison_delta_key=comparison_delta_key,
    )


def markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def build_markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return ["_无数据_"]
    header_line = "| " + " | ".join(markdown_cell(item) for item in headers) + " |"
    divider_line = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = ["| " + " | ".join(markdown_cell(item) for item in row) + " |" for row in rows]
    return [header_line, divider_line, *body_lines]


def build_protocol_hotspot_preview_rows(
    protocol_dimension_rows: list[dict[str, str]],
    protocol_nested_dimension_rows: list[dict[str, str]],
    *,
    top_n: int = 8,
) -> list[dict[str, str]]:
    hotspot_rows: list[dict[str, str]] = []
    for row in protocol_dimension_rows:
        if not any(
            (
                parse_tsv_int(row, "missing_contract_runs"),
                parse_tsv_int(row, "degraded_contract_runs"),
                parse_tsv_int(row, "total_dropped_group_count"),
                parse_tsv_int(row, "total_weight_fallback_count"),
                parse_tsv_int(row, "total_zero_weight_observation_count"),
            )
        ):
            continue
        hotspot_rows.append(
            {
                "selection_scope": str(row.get("selection_scope", "")).strip(),
                "source": "dimension",
                "slice_label": f"{str(row.get('dimension', '')).strip()}={str(row.get('value', '')).strip()}",
                "total_runs": str(row.get("total_runs", "")).strip(),
                "missing_contract_runs": str(row.get("missing_contract_runs", "")).strip(),
                "degraded_contract_runs": str(row.get("degraded_contract_runs", "")).strip(),
                "total_dropped_group_count": str(row.get("total_dropped_group_count", "")).strip(),
                "total_weight_fallback_count": str(row.get("total_weight_fallback_count", "")).strip(),
                "total_zero_weight_observation_count": str(row.get("total_zero_weight_observation_count", "")).strip(),
            }
        )
    for row in protocol_nested_dimension_rows:
        if not any(
            (
                parse_tsv_int(row, "missing_contract_runs"),
                parse_tsv_int(row, "degraded_contract_runs"),
                parse_tsv_int(row, "total_dropped_group_count"),
                parse_tsv_int(row, "total_weight_fallback_count"),
                parse_tsv_int(row, "total_zero_weight_observation_count"),
            )
        ):
            continue
        hotspot_rows.append(
            {
                "selection_scope": str(row.get("selection_scope", "")).strip(),
                "source": f"nested_d{str(row.get('dimension_depth', '')).strip() or '0'}",
                "slice_label": (
                    f"{str(row.get('dimensions', '')).strip()}="
                    f"{str(row.get('values', '')).strip()}"
                ),
                "total_runs": str(row.get("total_runs", "")).strip(),
                "missing_contract_runs": str(row.get("missing_contract_runs", "")).strip(),
                "degraded_contract_runs": str(row.get("degraded_contract_runs", "")).strip(),
                "total_dropped_group_count": str(row.get("total_dropped_group_count", "")).strip(),
                "total_weight_fallback_count": str(row.get("total_weight_fallback_count", "")).strip(),
                "total_zero_weight_observation_count": str(row.get("total_zero_weight_observation_count", "")).strip(),
            }
        )
    ranked_rows = sorted(
        hotspot_rows,
        key=lambda row: (
            -parse_tsv_int(row, "missing_contract_runs"),
            -parse_tsv_int(row, "degraded_contract_runs"),
            -parse_tsv_int(row, "total_zero_weight_observation_count"),
            -parse_tsv_int(row, "total_weight_fallback_count"),
            -parse_tsv_int(row, "total_dropped_group_count"),
            -parse_tsv_int(row, "total_runs"),
            str(row.get("source", "")).strip(),
            str(row.get("selection_scope", "")).strip(),
            str(row.get("slice_label", "")).strip(),
        ),
    )
    return ranked_rows[: max(1, top_n)]


def render_main_matrix_report_markdown(
    leaderboard_rows: list[dict[str, str]],
    dimension_rows: list[dict[str, str]],
    baseline_summary_rows: list[dict[str, str]],
    baseline_detail_rows: list[dict[str, str]],
    key_indicator_rows: list[dict[str, str]],
    baseline_winner_rows: list[dict[str, str]],
    metric_snapshot_rows: list[dict[str, str]],
    paper_summary_rows: list[dict[str, str]],
    protocol_overview_rows: list[dict[str, str]],
    protocol_dimension_rows: list[dict[str, str]],
    protocol_nested_dimension_rows: list[dict[str, str]],
    protocol_reason_rows: list[dict[str, str]],
    quality_gate_rows: list[dict[str, str]],
    appendix_index_rows: list[dict[str, str]],
    protocol_panel_rows: list[dict[str, str]],
    paper_main_rows: list[dict[str, str]],
    paper_rows: list[dict[str, str]],
    topk_overall_rows: list[dict[str, str]],
    topk_by_engine_rows: list[dict[str, str]],
    topk_by_weight_rows: list[dict[str, str]],
    topk_by_sequence_rows: list[dict[str, str]],
    topk_by_grouping_rows: list[dict[str, str]],
    validation_only_rows: list[dict[str, str]],
    topk_by_budget_rows: list[dict[str, str]],
    topk_by_validation_budget_rows: list[dict[str, str]],
    topk_improvement_rows: list[dict[str, str]],
    summary_source: Path,
    protocol_source: Path,
    report_plan: str,
    paper_plan: str,
    paper_budget: str,
    paper_status: str,
    paper_yield_metric: str,
    paper_require_validation: bool,
    paper_require_better_than: str,
    paper_protocol_status: str,
    paper_max_rows: int,
    top_n: int,
    top_k_per_panel: int,
    protocol_hotspot_rows: list[dict[str, str]] | None = None,
) -> str:
    filtered_plan = report_plan.strip() or "all"
    filtered_paper_plan = paper_plan.strip() or filtered_plan
    comparison_target = paper_require_better_than.strip() or "b0"
    ok_count = sum(str(row.get("status", "")).strip().lower() == "ok" for row in leaderboard_rows)
    failed_count = len(leaderboard_rows) - ok_count
    quality_gate_overall_status = resolve_main_matrix_quality_gate_overall_status(quality_gate_rows)
    crop_family, crop_display_name, registry_plan_sequences, registry_default_groupings = (
        resolve_report_registry_profile_summary(filtered_plan, leaderboard_rows)
    )
    if protocol_hotspot_rows is None:
        protocol_hotspot_rows = build_protocol_hotspot_preview_rows(
            protocol_dimension_rows,
            protocol_nested_dimension_rows,
        )
    lines = [
        "# Main Matrix Report",
        "",
        "## Report Metadata",
        "",
        f"- summary_source: {summary_source.resolve()}",
        f"- protocol_source: {protocol_source.resolve()}",
        f"- crop_family: {crop_family}",
        f"- crop_display_name: {crop_display_name}",
        f"- report_plan: {filtered_plan}",
        f"- registry_plan_sequences: {registry_plan_sequences}",
        f"- registry_default_groupings: {registry_default_groupings}",
        f"- total_combos: {len(leaderboard_rows)}",
        f"- ok_runs: {ok_count}",
        f"- failed_runs: {failed_count}",
        f"- paper_plan: {filtered_paper_plan}",
        f"- paper_budget: {paper_budget.strip() or 'all'}",
        f"- paper_status: {paper_status.strip() or 'all'}",
        f"- paper_yield_metric: {paper_yield_metric.strip() or 'all'}",
        f"- paper_protocol_status: {resolve_report_protocol_status_filter(paper_protocol_status)}",
        f"- paper_require_validation: {'true' if paper_require_validation else 'false'}",
        f"- paper_comparison_target: {comparison_target}",
        f"- paper_selected_rows: {len(paper_rows)}",
        f"- paper_main_table_rows: {len(paper_main_rows)}",
        f"- quality_gate_overall: {quality_gate_overall_status}",
        f"- top_n: {top_n}",
        f"- paper_max_rows: {paper_max_rows}",
        f"- top_k_per_panel: {top_k_per_panel}",
        "- appendix_panels: paper_full_table, protocol_coverage, protocol_detail_reasons, by_engine, by_weight, by_sequence, by_grouping, validation_only, budget_split, validation_budget, improvement",
        "",
        "## Research Quality Gates",
        "",
    ]
    lines.extend(
        build_markdown_table(
            ["Gate", "Level", "Status", "Expected", "Actual", "Detail"],
            [
                [
                    row.get("gate_label", ""),
                    row.get("gate_level", ""),
                    row.get("status", ""),
                    row.get("expected", ""),
                    row.get("actual", ""),
                    row.get("detail", ""),
                ]
                for row in quality_gate_rows
            ],
        )
    )
    lines.extend(["", "## Baseline Comparison Summary", ""])
    lines.extend(
        build_markdown_table(
            ["Baseline", "Better", "Comparable", "Rate", "Best Δ", "Median Δ", "Best Combo"],
            [
                [
                    row.get("comparison_target", ""),
                    row.get("better_count", ""),
                    row.get("comparable_runs", ""),
                    row.get("better_rate", ""),
                    row.get("best_delta", ""),
                    row.get("median_delta", ""),
                    row.get("best_combo_key", ""),
                ]
                for row in baseline_summary_rows
            ],
        )
    )
    lines.extend(["", "## Baseline Detail Preview", ""])
    baseline_preview_rows: list[list[object]] = []
    for comparison_target, _, _ in MAIN_MATRIX_BASELINE_TARGETS:
        target_rows = [
            row for row in baseline_detail_rows if str(row.get("comparison_target", "")).strip() == comparison_target
        ]
        baseline_preview_rows.extend(
            [
                [
                    row.get("comparison_target", ""),
                    row.get("comparison_rank", ""),
                    row.get("combo_key", ""),
                    row.get("comparison_delta", ""),
                    row.get("comparison_passed", ""),
                    row.get("score", ""),
                    row.get("valid_mean_nrmse", ""),
                    row.get("engine", ""),
                    row.get("weight", ""),
                ]
                for row in target_rows[:3]
            ]
        )
    lines.extend(
        build_markdown_table(
            ["Baseline", "Rank", "Combo", "Δ", "Passed", "Score", "Valid", "Engine", "Weight"],
            baseline_preview_rows,
        )
    )
    lines.extend([
        "",
        "## Key Metric Snapshot",
        "",
    ])
    lines.extend(
        build_markdown_table(
            ["Scope", "Metric", "Best", "Median", "Mean", "Worst", "Available", "Best Combo"],
            [
                [
                    row.get("scope_label", ""),
                    row.get("metric_label", ""),
                    row.get("best_value", ""),
                    row.get("median_value", ""),
                    row.get("mean_value", ""),
                    row.get("worst_value", ""),
                    row.get("available_runs", ""),
                    row.get("best_combo_key", ""),
                ]
                for row in metric_snapshot_rows
            ],
        )
    )
    lines.extend(["", "## Paper-Facing Summary", ""])
    lines.extend(
        build_markdown_table(
            [
                "Scope",
                "Target",
                "Rows",
                "Valid Rows",
                "Best Score",
                "Median Valid",
                "Best Δ",
                "Pass Rate",
                "Best Combo",
            ],
            [
                [
                    row.get("selection_scope", ""),
                    row.get("comparison_target", ""),
                    row.get("selected_runs", ""),
                    row.get("validation_runs", ""),
                    row.get("best_score", ""),
                    row.get("median_valid_mean_nrmse", ""),
                    row.get("best_comparison_delta", ""),
                    row.get("better_than_target_rate", ""),
                    row.get("best_combo_key", ""),
                ]
                for row in paper_summary_rows
            ],
        )
    )
    lines.extend(["", "## Protocol Quality Overview", ""])
    lines.extend(
        build_markdown_table(
            [
                "Scope",
                "Runs",
                "Manifest",
                "Contract",
                "OK",
                "Degraded",
                "Missing",
                "Warn Rows",
                "Error Rows",
                "Issues",
                "Drop Rows",
                "Fallback Rows",
                "Zero Rows",
                "Dropped",
                "Fallbacks",
                "Zero Obs",
                "Mean Active Metrics",
                "Mean Active Obs",
            ],
            [
                [
                    row.get("selection_scope", ""),
                    row.get("total_runs", ""),
                    row.get("manifest_runs", ""),
                    row.get("contract_runs", ""),
                    row.get("ok_contract_runs", ""),
                    row.get("degraded_contract_runs", ""),
                    row.get("missing_contract_runs", ""),
                    row.get("rows_with_warnings", ""),
                    row.get("rows_with_errors", ""),
                    row.get("total_issue_count", ""),
                    row.get("rows_with_dropped_groups", ""),
                    row.get("rows_with_weight_fallbacks", ""),
                    row.get("rows_with_zero_weight_observations", ""),
                    row.get("total_dropped_group_count", ""),
                    row.get("total_weight_fallback_count", ""),
                    row.get("total_zero_weight_observation_count", ""),
                    row.get("mean_active_metric_count", ""),
                    row.get("mean_active_observation_count", ""),
                ]
                for row in protocol_overview_rows
            ],
        )
    )
    lines.extend(["", "## Protocol Quality By Dimension", ""])
    lines.extend(
        build_markdown_table(
            [
                "Scope",
                "Dimension",
                "Value",
                "Runs",
                "OK",
                "Degraded",
                "Missing",
                "Drop Rows",
                "Fallback Rows",
                "Zero Rows",
                "Dropped",
                "Fallbacks",
                "Zero Obs",
            ],
            [
                [
                    row.get("selection_scope", ""),
                    row.get("dimension", ""),
                    row.get("value", ""),
                    row.get("total_runs", ""),
                    row.get("ok_contract_runs", ""),
                    row.get("degraded_contract_runs", ""),
                    row.get("missing_contract_runs", ""),
                    row.get("rows_with_dropped_groups", ""),
                    row.get("rows_with_weight_fallbacks", ""),
                    row.get("rows_with_zero_weight_observations", ""),
                    row.get("total_dropped_group_count", ""),
                    row.get("total_weight_fallback_count", ""),
                    row.get("total_zero_weight_observation_count", ""),
                ]
                for row in protocol_dimension_rows
            ],
        )
    )
    lines.extend(["", "## Protocol Quality Nested Slices", ""])
    lines.extend(
        build_markdown_table(
            [
                "Scope",
                "Depth",
                "Dimensions",
                "Values",
                "Runs",
                "OK",
                "Degraded",
                "Missing",
                "Dropped",
                "Fallbacks",
                "Zero Obs",
            ],
            [
                [
                    row.get("selection_scope", ""),
                    row.get("dimension_depth", ""),
                    row.get("dimensions", ""),
                    row.get("values", ""),
                    row.get("total_runs", ""),
                    row.get("ok_contract_runs", ""),
                    row.get("degraded_contract_runs", ""),
                    row.get("missing_contract_runs", ""),
                    row.get("total_dropped_group_count", ""),
                    row.get("total_weight_fallback_count", ""),
                    row.get("total_zero_weight_observation_count", ""),
                ]
                for row in protocol_nested_dimension_rows
            ],
        )
    )
    lines.extend(["", "## Protocol Risk Hotspots", ""])
    lines.extend(
        build_markdown_table(
            ["Scope", "Source", "Slice", "Runs", "Missing", "Degraded", "Dropped", "Fallbacks", "Zero Obs"],
            [
                [
                    row.get("selection_scope", ""),
                    row.get("source", ""),
                    row.get("slice_label", ""),
                    row.get("total_runs", ""),
                    row.get("missing_contract_runs", ""),
                    row.get("degraded_contract_runs", ""),
                    row.get("total_dropped_group_count", ""),
                    row.get("total_weight_fallback_count", ""),
                    row.get("total_zero_weight_observation_count", ""),
                ]
                for row in protocol_hotspot_rows
            ],
        )
    )
    lines.extend(["", "## Protocol Detail Reason Breakdown", ""])
    lines.extend(
        build_markdown_table(
            ["Scope", "Kind", "Reason", "Affected Runs", "Occurrences", "Entities", "Example Runs"],
            [
                [
                    row.get("selection_scope", ""),
                    row.get("reason_kind", ""),
                    row.get("reason", ""),
                    row.get("affected_runs", ""),
                    row.get("total_occurrences", ""),
                    row.get("affected_entities", ""),
                    row.get("example_run_ids", ""),
                ]
                for row in protocol_reason_rows
            ],
        )
    )
    lines.extend(["", "## Paper Key Indicator Table", ""])
    lines.extend(
        build_markdown_table(
            ["Indicator", "Best", "Median", "Available", "Best Combo", "Engine", "Weight", "Budget", "Validated"],
            [
                [
                    row.get("indicator_label", ""),
                    row.get("best_value", ""),
                    row.get("median_value", ""),
                    row.get("available_runs", ""),
                    row.get("best_combo_key", ""),
                    row.get("best_engine", ""),
                    row.get("best_weight", ""),
                    row.get("best_budget", ""),
                    row.get("best_validation_enabled", ""),
                ]
                for row in key_indicator_rows
            ],
        )
    )
    lines.extend(["", "## Baseline Winners", ""])
    lines.extend(
        build_markdown_table(
            ["Baseline", "Rank", "Combo", "Δ", "Score", "Valid", "Engine", "Weight", "Budget"],
            [
                [
                    row.get("comparison_target", ""),
                    row.get("winner_report_rank", ""),
                    row.get("winner_combo_key", ""),
                    row.get("winner_delta", ""),
                    row.get("winner_score", ""),
                    row.get("winner_valid_mean_nrmse", ""),
                    row.get("winner_engine", ""),
                    row.get("winner_weight", ""),
                    row.get("winner_budget", ""),
                ]
                for row in baseline_winner_rows
            ],
        )
    )
    lines.extend(["", "## Appendix Index", ""])
    lines.extend(
        build_markdown_table(
            ["Panel", "Scope", "Group By", "Values", "Rows", "Top-K", "TSV"],
            [
                [
                    row.get("panel_title", ""),
                    row.get("selection_scope", ""),
                    row.get("grouping_field", ""),
                    row.get("panel_values", ""),
                    row.get("row_count", ""),
                    row.get("top_k", ""),
                    row.get("tsv_path", ""),
                ]
                for row in appendix_index_rows
            ],
        )
    )
    lines.extend(["", "## Appendix: Protocol Coverage Preview", ""])
    lines.extend(
        build_markdown_table(
            [
                "Status",
                "Panel Rank",
                "Paper Rank",
                "Combo",
                "Issues",
                "Warn",
                "Error",
                "Dropped",
                "Fallbacks",
                "Zero Obs",
                "Active Metrics",
                "Active Obs",
            ],
            [
                [
                    row.get("contract_status", ""),
                    row.get("panel_rank", ""),
                    row.get("paper_rank", ""),
                    row.get("combo_key", ""),
                    row.get("issue_count", ""),
                    row.get("warning_count", ""),
                    row.get("error_count", ""),
                    row.get("dropped_group_count", ""),
                    row.get("weight_fallback_count", ""),
                    row.get("zero_weight_observation_count", ""),
                    row.get("active_metric_count", ""),
                    row.get("active_observation_count", ""),
                ]
                for row in protocol_panel_rows[: max(1, paper_max_rows)]
            ],
        )
    )
    lines.extend([
        "",
        "## Overall Leaderboard",
        "",
    ])
    top_rows = leaderboard_rows[: max(1, top_n)]
    lines.extend(
        build_markdown_table(
            ["Rank", "Combo", "Score", "ΔB0", "Train", "Valid", "Status"],
            [
                [
                    row.get("report_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("delta_vs_b0", ""),
                    row.get("train_mean_nrmse", ""),
                    row.get("valid_mean_nrmse", ""),
                    row.get("status", ""),
                ]
                for row in top_rows
            ],
        )
    )
    lines.extend(["", "## Paper Main Table", ""])
    lines.extend(
        build_markdown_table(
            ["Paper Rank", "Combo", "Score", "Valid", "ΔTarget", "Engine", "Weight", "Budget", "Validated", "Status"],
            [
                [
                    row.get("paper_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("valid_mean_nrmse", ""),
                    row.get("comparison_delta", ""),
                    row.get("engine", ""),
                    row.get("weight", ""),
                    row.get("budget", ""),
                    row.get("validation_enabled", ""),
                    row.get("status", ""),
                ]
                for row in paper_main_rows[: max(1, paper_max_rows)]
            ],
        )
    )
    lines.extend(["", "## Appendix: Paper Full Table Preview", ""])
    lines.extend(
        build_markdown_table(
            ["Paper Rank", "Combo", "Score", "Valid", "ΔTarget", "Engine", "Weight", "Budget", "Sequence", "Grouping"],
            [
                [
                    row.get("paper_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("valid_mean_nrmse", ""),
                    row.get("comparison_delta", ""),
                    row.get("engine", ""),
                    row.get("weight", ""),
                    row.get("budget", ""),
                    row.get("sequence", ""),
                    row.get("grouping", ""),
                ]
                for row in paper_rows[: max(1, paper_max_rows)]
            ],
        )
    )
    lines.extend(["", "## Top-K Overall", ""])
    lines.extend(
        build_markdown_table(
            ["Rank", "Combo", "Score", "ΔTarget", "Valid", "Engine", "Weight"],
            [
                [
                    row.get("panel_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("comparison_delta", ""),
                    row.get("valid_mean_nrmse", ""),
                    row.get("engine", ""),
                    row.get("weight", ""),
                ]
                for row in topk_overall_rows
            ],
        )
    )
    lines.extend(["", "## Top-K By Engine", ""])
    lines.extend(
        build_markdown_table(
            ["Engine", "Rank", "Combo", "Score", "ΔTarget", "Valid"],
            [
                [
                    row.get("panel_value", ""),
                    row.get("panel_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("comparison_delta", ""),
                    row.get("valid_mean_nrmse", ""),
                ]
                for row in topk_by_engine_rows
            ],
        )
    )
    lines.extend(["", "## Top-K By Weight", ""])
    lines.extend(
        build_markdown_table(
            ["Weight", "Rank", "Combo", "Score", "ΔTarget", "Valid"],
            [
                [
                    row.get("panel_value", ""),
                    row.get("panel_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("comparison_delta", ""),
                    row.get("valid_mean_nrmse", ""),
                ]
                for row in topk_by_weight_rows
            ],
        )
    )
    lines.extend(["", "## Appendix: Top-K By Sequence", ""])
    lines.extend(
        build_markdown_table(
            ["Sequence", "Rank", "Combo", "Score", "ΔTarget", "Valid"],
            [
                [
                    row.get("panel_value", ""),
                    row.get("panel_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("comparison_delta", ""),
                    row.get("valid_mean_nrmse", ""),
                ]
                for row in topk_by_sequence_rows
            ],
        )
    )
    lines.extend(["", "## Appendix: Top-K By Grouping", ""])
    lines.extend(
        build_markdown_table(
            ["Grouping", "Rank", "Combo", "Score", "ΔTarget", "Valid"],
            [
                [
                    row.get("panel_value", ""),
                    row.get("panel_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("comparison_delta", ""),
                    row.get("valid_mean_nrmse", ""),
                ]
                for row in topk_by_grouping_rows
            ],
        )
    )
    lines.extend(["", "## Appendix: Validation-Only Top-K", ""])
    lines.extend(
        build_markdown_table(
            ["Rank", "Combo", "Score", "ΔTarget", "Valid", "Engine", "Weight"],
            [
                [
                    row.get("panel_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("comparison_delta", ""),
                    row.get("valid_mean_nrmse", ""),
                    row.get("engine", ""),
                    row.get("weight", ""),
                ]
                for row in validation_only_rows
            ],
        )
    )
    lines.extend(["", "## Appendix: Budget Split Top-K", ""])
    lines.extend(
        build_markdown_table(
            ["Budget", "Rank", "Combo", "Score", "ΔTarget", "Valid"],
            [
                [
                    row.get("panel_value", ""),
                    row.get("panel_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("comparison_delta", ""),
                    row.get("valid_mean_nrmse", ""),
                ]
                for row in topk_by_budget_rows
            ],
        )
    )
    lines.extend(["", "## Appendix: Validation × Budget Top-K", ""])
    lines.extend(
        build_markdown_table(
            ["Validation|Budget", "Rank", "Combo", "Score", "ΔTarget", "Valid", "Engine"],
            [
                [
                    row.get("panel_value", ""),
                    row.get("panel_rank", ""),
                    row.get("combo_key", ""),
                    row.get("score", ""),
                    row.get("comparison_delta", ""),
                    row.get("valid_mean_nrmse", ""),
                    row.get("engine", ""),
                ]
                for row in topk_by_validation_budget_rows
            ],
        )
    )
    lines.extend(["", "## Top-K Improvement", ""])
    lines.extend(
        build_markdown_table(
            ["Rank", "Combo", "ΔTarget", "Score", "Valid", "Comparison"],
            [
                [
                    row.get("panel_rank", ""),
                    row.get("combo_key", ""),
                    row.get("comparison_delta", ""),
                    row.get("score", ""),
                    row.get("valid_mean_nrmse", ""),
                    row.get("comparison_target", ""),
                ]
                for row in topk_improvement_rows
            ],
        )
    )
    for dimension in MAIN_MATRIX_REPORT_DIMENSIONS:
        label = MAIN_MATRIX_DIMENSION_LABELS[dimension]
        dimension_subset = [row for row in dimension_rows if str(row.get("dimension", "")).strip() == dimension]
        lines.extend(
            [
                "",
                f"## {label} Summary",
                "",
            ]
        )
        lines.extend(
            build_markdown_table(
                ["Value", "Best Score", "Mean Score", "Best Rank", ">B0", "Best Combo"],
                [
                    [
                        row.get("value", ""),
                        row.get("best_score", ""),
                        row.get("mean_score", ""),
                        row.get("best_report_rank", ""),
                        row.get("better_than_b0_count", ""),
                        row.get("best_combo_key", ""),
                    ]
                    for row in dimension_subset
                ],
            )
        )
    return "\n".join(lines) + "\n"


def build_main_matrix_report(
    report_plan: str = "",
    top_n: int = 10,
    paper_plan: str = "",
    paper_budget: str = "",
    paper_status: str = "ok",
    paper_yield_metric: str = "",
    paper_require_validation: bool = False,
    paper_require_better_than: str = "",
    paper_protocol_status: str = "auto",
    paper_max_rows: int = 20,
    top_k_per_panel: int = 3,
) -> dict[str, Path]:
    migrate_legacy_root_artifacts()
    summary_path = resolve_existing_artifact_path(EXPERIMENT_SUMMARY_TSV_PATH)
    protocol_source_path = resolve_existing_artifact_path(EXPERIMENT_PROTOCOL_ARTIFACTS_TSV_PATH)
    summary_rows = deduplicate_latest_runs(filter_report_summary_rows(read_tsv_rows(summary_path), report_plan))
    if not summary_rows:
        raise FileNotFoundError(f"No experiment summary rows available for report source: {summary_path}")
    protocol_rows_by_run_id = build_protocol_artifact_rows_by_run_id(read_tsv_rows(protocol_source_path))
    leaderboard_rows = build_main_matrix_leaderboard_rows(summary_rows)
    dimension_rows = build_main_matrix_dimension_summary_rows(leaderboard_rows)
    baseline_summary_rows = build_main_matrix_baseline_summary_rows(leaderboard_rows)
    baseline_detail_rows = build_main_matrix_baseline_detail_rows(leaderboard_rows)
    baseline_winner_rows = build_main_matrix_baseline_winner_rows(leaderboard_rows)
    effective_paper_plan = paper_plan.strip() or report_plan.strip()
    comparison_target = paper_require_better_than.strip().lower() or "b0"
    comparison_delta_key, _ = resolve_paper_comparison_target(paper_require_better_than)
    paper_candidate_source_rows = collect_main_matrix_paper_candidate_rows(
        leaderboard_rows,
        paper_plan=effective_paper_plan,
        paper_budget=paper_budget,
        paper_status=paper_status,
        paper_yield_metric=paper_yield_metric,
        paper_require_better_than=paper_require_better_than,
    )
    paper_candidate_source_rows = filter_rows_by_protocol_status(
        paper_candidate_source_rows,
        protocol_rows_by_run_id,
        paper_protocol_status=paper_protocol_status,
    )
    paper_source_rows = filter_main_matrix_paper_rows(
        leaderboard_rows,
        paper_plan=effective_paper_plan,
        paper_budget=paper_budget,
        paper_status=paper_status,
        paper_yield_metric=paper_yield_metric,
        paper_require_validation=paper_require_validation,
        paper_require_better_than=paper_require_better_than,
    )
    paper_source_rows = filter_rows_by_protocol_status(
        paper_source_rows,
        protocol_rows_by_run_id,
        paper_protocol_status=paper_protocol_status,
    )
    paper_rows = build_main_matrix_paper_table_rows(
        paper_source_rows,
        comparison_target=comparison_target,
        comparison_delta_key=comparison_delta_key,
    )
    paper_main_rows = build_main_matrix_paper_main_rows(paper_rows)
    key_indicator_rows = build_main_matrix_key_indicator_table_rows(
        paper_rows,
        comparison_target=comparison_target,
    )
    topk_overall_rows = build_main_matrix_topk_panel_rows(
        paper_rows,
        panel="overall",
        panel_field=None,
        top_k=top_k_per_panel,
        comparison_delta_key="comparison_delta",
    )
    topk_by_engine_rows = build_main_matrix_topk_panel_rows(
        paper_rows,
        panel="engine",
        panel_field="engine",
        top_k=top_k_per_panel,
        comparison_delta_key="comparison_delta",
    )
    topk_by_weight_rows = build_main_matrix_topk_panel_rows(
        paper_rows,
        panel="weight",
        panel_field="weight",
        top_k=top_k_per_panel,
        comparison_delta_key="comparison_delta",
    )
    topk_by_sequence_rows = build_main_matrix_topk_panel_rows(
        paper_rows,
        panel="sequence",
        panel_field="sequence",
        top_k=top_k_per_panel,
        comparison_delta_key="comparison_delta",
    )
    topk_by_grouping_rows = build_main_matrix_topk_panel_rows(
        paper_rows,
        panel="grouping",
        panel_field="grouping",
        top_k=top_k_per_panel,
        comparison_delta_key="comparison_delta",
    )
    validation_only_source_rows = filter_main_matrix_paper_rows(
        leaderboard_rows,
        paper_plan=effective_paper_plan,
        paper_budget=paper_budget,
        paper_status=paper_status,
        paper_yield_metric=paper_yield_metric,
        paper_require_validation=True,
        paper_require_better_than=paper_require_better_than,
    )
    validation_only_source_rows = filter_rows_by_protocol_status(
        validation_only_source_rows,
        protocol_rows_by_run_id,
        paper_protocol_status=paper_protocol_status,
    )
    validation_only_paper_rows = build_main_matrix_paper_table_rows(
        validation_only_source_rows,
        comparison_target=comparison_target,
        comparison_delta_key=comparison_delta_key,
    )
    validation_only_rows = build_main_matrix_topk_panel_rows(
        validation_only_paper_rows,
        panel="validation_only",
        panel_field=None,
        top_k=top_k_per_panel,
        comparison_delta_key="comparison_delta",
    )
    metric_snapshot_rows = build_main_matrix_metric_snapshot_rows(
        [
            ("leaderboard_all", leaderboard_rows),
            ("paper_selected", paper_rows),
            ("validation_selected", validation_only_paper_rows),
        ]
    )
    paper_summary_rows = build_main_matrix_paper_summary_rows(
        paper_rows,
        comparison_target=comparison_target,
    )
    protocol_overview_rows = build_main_matrix_protocol_overview_rows(
        [("leaderboard_all", leaderboard_rows), ("paper_selected", paper_rows)],
        protocol_rows_by_run_id,
    )
    protocol_dimension_rows = build_main_matrix_protocol_dimension_summary_rows(
        [("leaderboard_all", leaderboard_rows), ("paper_selected", paper_rows)],
        protocol_rows_by_run_id,
    )
    protocol_nested_dimension_rows = build_main_matrix_protocol_nested_dimension_summary_rows(
        [("leaderboard_all", leaderboard_rows), ("paper_selected", paper_rows)],
        protocol_rows_by_run_id,
    )
    protocol_hotspot_rows = build_protocol_hotspot_preview_rows(
        protocol_dimension_rows,
        protocol_nested_dimension_rows,
    )
    protocol_reason_rows = build_main_matrix_protocol_reason_summary_rows(
        [("leaderboard_all", leaderboard_rows), ("paper_selected", paper_rows)],
        protocol_rows_by_run_id,
    )
    protocol_panel_rows = build_main_matrix_protocol_panel_rows(paper_rows, protocol_rows_by_run_id)
    topk_by_budget_rows = build_main_matrix_topk_panel_rows(
        paper_rows,
        panel="budget",
        panel_field="budget",
        top_k=top_k_per_panel,
        comparison_delta_key="comparison_delta",
    )
    candidate_paper_rows = build_main_matrix_paper_table_rows(
        paper_candidate_source_rows,
        comparison_target=comparison_target,
        comparison_delta_key=comparison_delta_key,
    )
    topk_by_validation_budget_rows = build_main_matrix_validation_budget_panel_rows(
        candidate_paper_rows,
        top_k=top_k_per_panel,
        comparison_delta_key="comparison_delta",
    )
    topk_improvement_rows = build_main_matrix_topk_panel_rows(
        paper_rows,
        panel="improvement",
        panel_field=None,
        top_k=top_k_per_panel,
        comparison_delta_key="comparison_delta",
        sort_mode="improvement",
    )
    write_tsv_dict_rows(MAIN_MATRIX_LEADERBOARD_TSV_PATH, MAIN_MATRIX_LEADERBOARD_FIELDNAMES, leaderboard_rows)
    write_tsv_dict_rows(
        MAIN_MATRIX_DIMENSION_SUMMARY_TSV_PATH,
        MAIN_MATRIX_DIMENSION_SUMMARY_FIELDNAMES,
        dimension_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_BASELINE_SUMMARY_TSV_PATH,
        MAIN_MATRIX_BASELINE_SUMMARY_FIELDNAMES,
        baseline_summary_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_BASELINE_DETAIL_TSV_PATH,
        MAIN_MATRIX_BASELINE_DETAIL_FIELDNAMES,
        baseline_detail_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_KEY_INDICATOR_TABLE_TSV_PATH,
        MAIN_MATRIX_KEY_INDICATOR_TABLE_FIELDNAMES,
        key_indicator_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_BASELINE_WINNERS_TSV_PATH,
        MAIN_MATRIX_BASELINE_WINNERS_FIELDNAMES,
        baseline_winner_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_METRIC_SNAPSHOT_TSV_PATH,
        MAIN_MATRIX_METRIC_SNAPSHOT_FIELDNAMES,
        metric_snapshot_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_PAPER_SUMMARY_TSV_PATH,
        MAIN_MATRIX_PAPER_SUMMARY_FIELDNAMES,
        paper_summary_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_PROTOCOL_OVERVIEW_TSV_PATH,
        MAIN_MATRIX_PROTOCOL_OVERVIEW_FIELDNAMES,
        protocol_overview_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_TSV_PATH,
        MAIN_MATRIX_PROTOCOL_DIMENSION_SUMMARY_FIELDNAMES,
        protocol_dimension_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_TSV_PATH,
        MAIN_MATRIX_PROTOCOL_NESTED_DIMENSION_SUMMARY_FIELDNAMES,
        protocol_nested_dimension_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_TSV_PATH,
        MAIN_MATRIX_PROTOCOL_HOTSPOT_SUMMARY_FIELDNAMES,
        protocol_hotspot_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_TSV_PATH,
        MAIN_MATRIX_PROTOCOL_REASON_SUMMARY_FIELDNAMES,
        protocol_reason_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_PROTOCOL_PAPER_TABLE_TSV_PATH,
        MAIN_MATRIX_PROTOCOL_PANEL_FIELDNAMES,
        protocol_panel_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_PAPER_MAIN_TABLE_TSV_PATH,
        MAIN_MATRIX_PAPER_MAIN_TABLE_FIELDNAMES,
        paper_main_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_PAPER_APPENDIX_TABLE_TSV_PATH,
        MAIN_MATRIX_PAPER_TABLE_FIELDNAMES,
        paper_rows,
    )
    write_tsv_dict_rows(MAIN_MATRIX_PAPER_TABLE_TSV_PATH, MAIN_MATRIX_PAPER_TABLE_FIELDNAMES, paper_rows)
    write_tsv_dict_rows(MAIN_MATRIX_TOPK_OVERALL_TSV_PATH, MAIN_MATRIX_TOPK_PANEL_FIELDNAMES, topk_overall_rows)
    write_tsv_dict_rows(MAIN_MATRIX_TOPK_BY_ENGINE_TSV_PATH, MAIN_MATRIX_TOPK_PANEL_FIELDNAMES, topk_by_engine_rows)
    write_tsv_dict_rows(MAIN_MATRIX_TOPK_BY_WEIGHT_TSV_PATH, MAIN_MATRIX_TOPK_PANEL_FIELDNAMES, topk_by_weight_rows)
    write_tsv_dict_rows(MAIN_MATRIX_TOPK_BY_SEQUENCE_TSV_PATH, MAIN_MATRIX_TOPK_PANEL_FIELDNAMES, topk_by_sequence_rows)
    write_tsv_dict_rows(MAIN_MATRIX_TOPK_BY_GROUPING_TSV_PATH, MAIN_MATRIX_TOPK_PANEL_FIELDNAMES, topk_by_grouping_rows)
    write_tsv_dict_rows(
        MAIN_MATRIX_TOPK_VALIDATION_ONLY_TSV_PATH,
        MAIN_MATRIX_TOPK_PANEL_FIELDNAMES,
        validation_only_rows,
    )
    write_tsv_dict_rows(MAIN_MATRIX_TOPK_BY_BUDGET_TSV_PATH, MAIN_MATRIX_TOPK_PANEL_FIELDNAMES, topk_by_budget_rows)
    write_tsv_dict_rows(
        MAIN_MATRIX_TOPK_BY_VALIDATION_BUDGET_TSV_PATH,
        MAIN_MATRIX_TOPK_PANEL_FIELDNAMES,
        topk_by_validation_budget_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_TOPK_IMPROVEMENT_TSV_PATH,
        MAIN_MATRIX_TOPK_PANEL_FIELDNAMES,
        topk_improvement_rows,
    )
    appendix_index_rows = build_main_matrix_appendix_index_rows(
        build_main_matrix_appendix_panel_inputs(
            paper_rows=paper_rows,
            protocol_panel_rows=protocol_panel_rows,
            protocol_reason_rows=protocol_reason_rows,
            topk_by_engine_rows=topk_by_engine_rows,
            topk_by_weight_rows=topk_by_weight_rows,
            topk_by_sequence_rows=topk_by_sequence_rows,
            topk_by_grouping_rows=topk_by_grouping_rows,
            validation_only_rows=validation_only_rows,
            topk_by_budget_rows=topk_by_budget_rows,
            topk_by_validation_budget_rows=topk_by_validation_budget_rows,
            topk_improvement_rows=topk_improvement_rows,
        ),
        top_k=top_k_per_panel,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_APPENDIX_INDEX_TSV_PATH,
        MAIN_MATRIX_APPENDIX_INDEX_FIELDNAMES,
        appendix_index_rows,
    )
    quality_gate_rows = build_main_matrix_quality_gate_rows(
        leaderboard_rows=leaderboard_rows,
        paper_rows=paper_rows,
        protocol_overview_rows=protocol_overview_rows,
        appendix_index_rows=appendix_index_rows,
    )
    write_tsv_dict_rows(
        MAIN_MATRIX_QUALITY_GATE_TSV_PATH,
        MAIN_MATRIX_QUALITY_GATE_FIELDNAMES,
        quality_gate_rows,
    )
    report_text = render_main_matrix_report_markdown(
        leaderboard_rows,
        dimension_rows,
        baseline_summary_rows,
        baseline_detail_rows,
        key_indicator_rows,
        baseline_winner_rows,
        metric_snapshot_rows,
        paper_summary_rows,
        protocol_overview_rows,
        protocol_dimension_rows,
        protocol_nested_dimension_rows,
        protocol_reason_rows,
        quality_gate_rows,
        appendix_index_rows,
        protocol_panel_rows,
        paper_main_rows,
        paper_rows,
        topk_overall_rows,
        topk_by_engine_rows,
        topk_by_weight_rows,
        topk_by_sequence_rows,
        topk_by_grouping_rows,
        validation_only_rows,
        topk_by_budget_rows,
        topk_by_validation_budget_rows,
        topk_improvement_rows,
        summary_source=summary_path,
        protocol_source=protocol_source_path,
        report_plan=report_plan,
        paper_plan=effective_paper_plan,
        paper_budget=paper_budget,
        paper_status=paper_status,
        paper_yield_metric=paper_yield_metric,
        paper_require_validation=paper_require_validation,
        paper_require_better_than=paper_require_better_than,
        paper_protocol_status=paper_protocol_status,
        paper_max_rows=max(1, paper_max_rows),
        top_n=max(1, top_n),
        top_k_per_panel=max(1, top_k_per_panel),
        protocol_hotspot_rows=protocol_hotspot_rows,
    )
    ensure_parent_dir(MAIN_MATRIX_REPORT_MD_PATH)
    MAIN_MATRIX_REPORT_MD_PATH.write_text(report_text, encoding="utf-8")
    return build_main_matrix_report_output_map()


def rebuild_main_matrix_report_artifacts(
    report_plan: str = "",
    top_n: int = 10,
    paper_plan: str = "",
    paper_budget: str = "",
    paper_status: str = "ok",
    paper_yield_metric: str = "",
    paper_require_validation: bool = False,
    paper_require_better_than: str = "",
    paper_protocol_status: str = "auto",
    paper_max_rows: int = 20,
    top_k_per_panel: int = 3,
) -> dict[str, Path]:
    rebuild_experiment_summary_exports()
    return build_main_matrix_report(
        report_plan=report_plan,
        top_n=top_n,
        paper_plan=paper_plan,
        paper_budget=paper_budget,
        paper_status=paper_status,
        paper_yield_metric=paper_yield_metric,
        paper_require_validation=paper_require_validation,
        paper_require_better_than=paper_require_better_than,
        paper_protocol_status=paper_protocol_status,
        paper_max_rows=paper_max_rows,
        top_k_per_panel=top_k_per_panel,
    )


def canonical_engine_name(engine: str) -> str:
    mapping = {
        "o1": "o1_least_squares",
        "o2": "o2_pestpp_ies",
        "o3": "o3_anneal_nm",
        "o4": "o4_nsga2",
        "o5": "o5_mgda",
        "powell": "o3_powell",
    }
    return mapping.get(engine, engine)


def case_dir_is_complete(path: Path) -> bool:
    return (path / "DSSAT48.INP").exists() and (path / "DSSAT48.INH").exists()


def case_dir_supports_scenario(path: Path) -> bool:
    filex_name = str((load_project_config().get("scenario", {}) or {}).get("filex", "")).strip()
    if not filex_name:
        return path.exists()
    return (path / filex_name).exists()


def ensure_case_dir_complete(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in ("DSSAT48.INP", "DSSAT48.INH"):
        dst = path / name
        if dst.exists():
            continue
        for src in (CASE_TEMPLATE_DIR / name, CASE_SUPPORT_ROOT / name):
            if src.exists():
                shutil.copy2(src, dst)
                break
    geno_dir = path / "GENOTYPE"
    geno_dir.mkdir(parents=True, exist_ok=True)
    template_cul = CASE_TEMPLATE_DIR / "GENOTYPE" / "WHCER048.CUL"
    dst_cul = geno_dir / "WHCER048.CUL"
    if template_cul.exists() and (not dst_cul.exists() or dst_cul.stat().st_size == 0):
        shutil.copy2(template_cul, dst_cul)
    return path


def copy_case_dir_contents(source: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.is_file():
            shutil.copy2(child, destination / child.name)
            continue
        if child.name.upper() != "GENOTYPE":
            continue
        for genotype_file in child.rglob("*"):
            if not genotype_file.is_file():
                continue
            relative_path = genotype_file.relative_to(child)
            target_path = destination / "GENOTYPE" / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(genotype_file, target_path)
    return destination


def configured_case_dir() -> Path | None:
    cfg_dir = str((load_project_config().get("paths", {}) or {}).get("dssat_case_dir", "")).strip()
    if not cfg_dir:
        return None
    candidate = Path(cfg_dir).resolve()
    if candidate.exists():
        return ensure_case_dir_complete(candidate)
    return None


def preferred_case_dir() -> Path:
    cfg_case = configured_case_dir()
    if cfg_case is not None and case_dir_supports_scenario(cfg_case):
        return cfg_case
    sandbox_case = SANDBOX_DIR / "dssat_case"
    ensure_case_dir_complete(sandbox_case)
    if case_dir_is_complete(sandbox_case) and case_dir_supports_scenario(sandbox_case):
        return sandbox_case
    return ensure_case_dir_complete(CASE_TEMPLATE_DIR)


def runtime_supported_engine(engine: str) -> bool:
    return engine in {"o1_least_squares", "o2_pestpp_ies", "o3_anneal_nm", "o3_powell"}


def validate_matrix_combination(weight: WeightCandidate, engine: str, sequence: str, grouping: str) -> str | None:
    canonical_engine = canonical_engine_name(engine)
    if grouping not in compatible_groupings_for_sequence(sequence):
        return f"Incompatible sequence/grouping: {sequence} x {grouping}"
    if weight.weight_mode == "w7_equal_contribution" and grouping != "g3_dssat_extended":
        return f"{weight.name} requires g3_dssat_extended grouping"
    if weight.weight_mode == "w7_equal_contribution" and sequence not in {"s2_sequential_phase", "s3_wls_joint"}:
        return f"{weight.name} is only aligned with S2/S3 grouped protocols"
    if weight.weight_mode == "w8_dssat_group_max" and sequence == "s3_wls_joint" and grouping != "g3_dssat_extended":
        return f"{weight.name} requires g3_dssat_extended grouping for S3 WLS refinement"
    if weight.weight_mode == "w9_pareto_no_preweight" and canonical_engine not in {"o4_nsga2", "o5_mgda"}:
        return "W9 Pareto / No Pre-Weight only supports O4 NSGA-II or O5 MGDA"
    if weight.weight_mode == "w9_pareto_no_preweight" and sequence != "s2_sequential_phase":
        return "W9 official matrix runs are restricted to S2 sequential phase"
    if weight.weight_mode == "w9_pareto_no_preweight" and grouping != "g3_dssat_extended":
        return "W9 official matrix runs require g3_dssat_extended grouping"
    if weight.weight_mode in {"w7_equal_contribution", "w8_dssat_group_max"} and canonical_engine in {"o4_nsga2", "o5_mgda"}:
        return f"{weight.name} should not be paired with vector-objective engines {canonical_engine}"
    if weight.name == "Legacy_Pareto_Surrogate" and canonical_engine in {"o4_nsga2", "o5_mgda"}:
        return "Legacy_Pareto_Surrogate is a scalar proxy and should not be used as formal multi-objective W9"
    if not runtime_supported_engine(canonical_engine):
        return f"{canonical_engine} is documented but not yet implemented in this sandbox runtime"
    return None


def run_baseline_reference(profile_name: str) -> tuple[str, float]:
    return run_eval(baseline_env_for_profile(profile_name))


def build_run_id(job: MatrixJob) -> str:
    timestamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    spec = f"{job.weight.name}|{job.engine}|{job.budget}|{job.sequence}|{job.grouping}|{job.index}|{time.time_ns()}"
    digest = hashlib.sha1(spec.encode("utf-8")).hexdigest()[:10]
    return f"{timestamp}_{job.index:03d}_{digest}"


def build_matrix_result(
    run_id: str,
    weight: WeightCandidate,
    engine: str,
    budget: str,
    sequence: str,
    grouping: str,
    score: float,
    status: str,
    stdout: str,
    negative_ref_profile: str,
    negative_ref_score: float,
    yield_metric: str,
) -> MatrixResult:
    summary_view = extract_matrix_summary_view(stdout, yield_metric)

    return MatrixResult(
        run_id=run_id,
        weight_name=weight.name,
        engine=engine,
        budget=budget,
        sequence=sequence,
        grouping=grouping,
        score=score,
        status=status,
        weight_mode=weight.weight_mode,
        stdout=stdout,
        negative_ref_profile=negative_ref_profile,
        negative_ref_score=negative_ref_score,
        train_mean_nrmse=summary_view.train_mean_nrmse if summary_view is not None else parse_named_float(stdout, "TRAIN_MEAN_NRMSE"),
        valid_mean_nrmse=summary_view.valid_mean_nrmse if summary_view is not None else parse_named_float(stdout, "VALID_MEAN_NRMSE"),
        all_mean_nrmse=summary_view.all_mean_nrmse if summary_view is not None else parse_named_float(stdout, "ALL_MEAN_NRMSE"),
        yield_metric=yield_metric,
        train_yield_nrmse=summary_view.train_primary_nrmse if summary_view is not None else parse_named_float(stdout, f"TRAIN_{str(yield_metric).strip().upper()}_NRMSE"),
        train_yield_bias=summary_view.train_primary_bias if summary_view is not None else parse_named_float(stdout, f"TRAIN_{str(yield_metric).strip().upper()}_BIAS"),
        valid_yield_nrmse=summary_view.valid_primary_nrmse if summary_view is not None else parse_named_float(stdout, f"VALID_{str(yield_metric).strip().upper()}_NRMSE"),
        valid_yield_bias=summary_view.valid_primary_bias if summary_view is not None else parse_named_float(stdout, f"VALID_{str(yield_metric).strip().upper()}_BIAS"),
    )


def write_matrix_result_log(result: MatrixResult) -> None:
    yield_metric = result.yield_metric
    write_matrix_log(f"### {result.weight_name} | {result.engine} | {result.budget} | {result.sequence} | {result.grouping}")
    write_matrix_log(f"- Weight mode: {result.weight_mode}")
    write_matrix_log(f"- Score: {result.score:.6f}")
    write_matrix_log(f"- Status: {result.status}")
    write_matrix_log(f"- Negative reference: {result.negative_ref_profile} ({result.negative_ref_score:.6f})")
    write_matrix_log(f"- TRAIN_MEAN_NRMSE: {result.train_mean_nrmse:.6f}")
    write_matrix_log(f"- VALID_MEAN_NRMSE: {result.valid_mean_nrmse:.6f}")
    write_matrix_log(f"- ALL_MEAN_NRMSE: {result.all_mean_nrmse:.6f}")
    write_matrix_log(f"- TRAIN_{yield_metric}_NRMSE: {result.train_yield_nrmse:.6f}")
    write_matrix_log(f"- TRAIN_{yield_metric}_BIAS: {result.train_yield_bias:.6f}")
    if result.valid_yield_nrmse == result.valid_yield_nrmse:
        write_matrix_log(f"- VALID_{yield_metric}_NRMSE: {result.valid_yield_nrmse:.6f}")
    if result.valid_yield_bias == result.valid_yield_bias:
        write_matrix_log(f"- VALID_{yield_metric}_BIAS: {result.valid_yield_bias:.6f}")
    write_matrix_log(f"<details><summary>Output</summary>\n\n```\n{result.stdout}\n```\n</details>\n")


def execute_matrix_job(
    job: MatrixJob,
    plan: str,
    negative_ref_profile: str,
    negative_ref_score: float,
    yield_metric: str,
    original_strategy: str,
    max_workers: int,
    worker_sandbox: WorkerSandboxModel | None = None,
    task_store: TaskStoreModel | None = None,
    batch_id: str = "",
    retry_index: int = 0,
    heartbeat_interval_sec: int = 15,
) -> MatrixResult:
    started_at = time.time()
    executed_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started_at))
    run_id = build_run_id(job)
    weight = job.weight
    task_id = f"task_{job.index:06d}"
    task_dir = worker_sandbox.tasks_dir / task_id if worker_sandbox is not None else None
    task_spec = None
    if worker_sandbox is not None and task_store is not None and batch_id:
        assert task_dir is not None
        task_spec = TaskSpec(
            task_id=task_id,
            batch_id=batch_id,
            task_type="matrix_cell",
            crop=project_crop_name(),
            priority=job.index,
            project_config_path=str(PROJECT_CONFIG_PATH.resolve()),
            protocol={
                "plan": plan,
                "weight": weight.name,
                "weight_mode": weight.weight_mode,
                "engine": job.engine,
                "budget": job.budget,
                "sequence": job.sequence,
                "grouping": job.grouping,
                "run_id": run_id,
            },
            input_refs={
                "eval_path": str(EVAL_PATH.resolve()),
                "strategy_path": str((worker_sandbox.sandbox_dir / "strategy.py").resolve()),
            },
            expected_outputs=["run_manifest.json", "contract_report.json"],
            runtime_env={"AR_RUN_ID": run_id},
            retry_index=retry_index,
        )
        task_store.write_task_manifest(task_dir, task_spec)
        task_store.write_task_state(
            task_dir,
            TaskStateRecord(
                task_id=task_id,
                state="pending",
                retry_count=retry_index,
            ),
        )
        task_store.write_current_task(worker_sandbox.current_task_path, task_spec)
        task_store.write_task_state(
            task_dir,
            TaskStateRecord(
                task_id=task_id,
                state="assigned",
                worker_id=worker_sandbox.worker_id,
                assigned_at=executed_at,
                retry_count=retry_index,
            ),
        )
        write_worker_status(
            task_store,
            worker_sandbox,
            status="preparing",
            current_task_id=task_id,
            crop_affinity=project_crop_name(),
            failure_count=retry_index,
        )
    incompatibility = validate_matrix_combination(weight, job.engine, job.sequence, job.grouping)
    print(
        f"Running matrix cell: weight={weight.name}, engine={job.engine}, "
        f"budget={job.budget}, sequence={job.sequence}, grouping={job.grouping}"
    )
    if incompatibility is not None:
        result = build_matrix_result(
            run_id=run_id,
            weight=weight,
            engine=job.engine,
            budget=job.budget,
            sequence=job.sequence,
            grouping=job.grouping,
            score=999.0,
            status="skipped",
            stdout=incompatibility,
            negative_ref_profile=negative_ref_profile,
            negative_ref_score=negative_ref_score,
            yield_metric=yield_metric,
        )
        result.plan = plan
        result.executed_at = executed_at
        result.duration_sec = time.time() - started_at
        result.batch_id = batch_id
        result.batch_root = str(task_store.batch_root) if task_store is not None else ""
        result.task_id = task_id
        result.task_dir = str(task_dir.resolve()) if task_dir is not None else ""
        result.worker_id = worker_sandbox.worker_id if worker_sandbox is not None else ""
        result.max_workers = max_workers
        result.eval_hash = sha1_of_file(EVAL_PATH)
        result.auto_evolve_hash = sha1_of_file(Path(__file__))
        if worker_sandbox is not None and task_store is not None and task_dir is not None:
            stdout_path, stderr_path = write_task_stdout_stderr(task_dir, incompatibility, "")
            task_store.write_task_state(
                task_dir,
                TaskStateRecord(
                    task_id=task_id,
                    state="passed",
                    worker_id=worker_sandbox.worker_id,
                    assigned_at=executed_at,
                    started_at=executed_at,
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    retry_count=retry_index,
                ),
            )
            task_store.write_task_result(
                task_dir,
                TaskResultRecord(
                    task_id=task_id,
                    status="skipped",
                    exit_code=0,
                    duration_sec=result.duration_sec,
                    score=result.score,
                    stdout_path=str(stdout_path.resolve()),
                    stderr_path=str(stderr_path.resolve()),
                ),
            )
            write_worker_status(
                task_store,
                worker_sandbox,
                status="idle",
                crop_affinity=project_crop_name(),
                failure_count=retry_index,
            )
            task_store.write_current_task(worker_sandbox.current_task_path, None)
        return result
    strategy_source = weight.source if weight.source is not None else original_strategy
    if strategy_source is not None:
        validate_strategy_source(strategy_source)
    env = {
        "AR_RUN_ID": run_id,
        "AR_WEIGHTING": weight.weight_mode,
        "AR_ENGINE": job.engine,
        "AR_BUDGET": job.budget,
        "AR_SEQUENCE": job.sequence,
        "AR_GROUPING": job.grouping,
    }
    workspace_dir = SANDBOX_DIR
    eval_execution: EvalExecutionResult | None = None
    if worker_sandbox is not None:
        workspace_dir = worker_sandbox.sandbox_dir
        prepare_worker_task_runtime(worker_sandbox, strategy_source)
        env["AR_SANDBOX_DIR"] = str(workspace_dir.resolve())
        env["DSSAT_CASE_DIR"] = str(worker_sandbox.dssat_case_dir.resolve())
        env["DSSAT_SKIP_TASKKILL"] = "1"
        if task_store is not None and task_dir is not None:
            task_store.write_task_state(
                task_dir,
                TaskStateRecord(
                    task_id=task_id,
                    state="sandbox_ready",
                    worker_id=worker_sandbox.worker_id,
                    assigned_at=executed_at,
                    retry_count=retry_index,
                ),
            )
            task_store.write_task_state(
                task_dir,
                TaskStateRecord(
                    task_id=task_id,
                    state="running",
                    worker_id=worker_sandbox.worker_id,
                    assigned_at=executed_at,
                    started_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    retry_count=retry_index,
                ),
            )
        eval_execution = run_eval_process_in_workspace(
            EVAL_PATH,
            workspace_dir,
            env,
            heartbeat_callback=(
                lambda: write_worker_status(
                    task_store,
                    worker_sandbox,
                    status="running",
                    current_task_id=task_id,
                    crop_affinity=project_crop_name(),
                    failure_count=retry_index,
                )
            )
            if task_store is not None
            else None,
            heartbeat_interval_sec=heartbeat_interval_sec,
            worker_id=worker_sandbox.worker_id,
        )
        stdout = eval_execution.merged
        score = eval_execution.score
    elif max_workers > 1:
        workspace = prepare_matrix_workspace(job.index, strategy_source)
        workspace_dir = workspace
        env["AR_SANDBOX_DIR"] = str(workspace.resolve())
        env["DSSAT_CASE_DIR"] = str((workspace / "dssat_case").resolve())
        env["DSSAT_SKIP_TASKKILL"] = "1"
        stdout, score = run_eval_in_workspace(EVAL_PATH, workspace, env)
    else:
        if weight.source is not None:
            write_text(STRATEGY_PATH, weight.source)
        env["DSSAT_CASE_DIR"] = str(preferred_case_dir().resolve())
        stdout, score = run_eval(env)
    if score >= 999.0:
        status = "crash"
    elif score > negative_ref_score:
        status = "negative_optimization"
    else:
        status = "ok"
    result = build_matrix_result(
        run_id=run_id,
        weight=weight,
        engine=job.engine,
        budget=job.budget,
        sequence=job.sequence,
        grouping=job.grouping,
        score=score,
        status=status,
        stdout=stdout,
        negative_ref_profile=negative_ref_profile,
        negative_ref_score=negative_ref_score,
        yield_metric=yield_metric,
    )
    trts, split_by_trt, _ = project_observation_bundle()
    result.plan = plan
    result.executed_at = executed_at
    result.duration_sec = time.time() - started_at
    result.workspace_dir = str(workspace_dir.resolve())
    result.batch_id = batch_id
    result.batch_root = str(task_store.batch_root) if task_store is not None else ""
    result.task_id = task_id
    result.task_dir = str(task_dir.resolve()) if task_dir is not None else ""
    result.worker_id = worker_sandbox.worker_id if worker_sandbox is not None else ""
    result.strategy_hash = strategy_hash(strategy_source)
    result.eval_hash = sha1_of_file(EVAL_PATH)
    result.auto_evolve_hash = sha1_of_file(Path(__file__))
    result.max_workers = max_workers
    result.validation_enabled = any(label == "valid" for label in split_by_trt.values())
    result.train_trts = ",".join(str(trt) for trt in trts if split_by_trt.get(trt, "train") == "train")
    result.valid_trts = ",".join(str(trt) for trt in trts if split_by_trt.get(trt, "train") == "valid")
    result.final_params = parse_final_parameters(stdout)
    result.treatment_rows = build_treatment_metric_rows(
        run_id=run_id,
        plan=plan,
        weight_name=weight.name,
        engine=job.engine,
        budget=job.budget,
        sequence=job.sequence,
        grouping=job.grouping,
        status=status,
        stdout=stdout,
        workspace_dir=str(workspace_dir.resolve()),
    )
    result.aggregate_rows = build_aggregate_metric_rows(
        run_id=run_id,
        plan=plan,
        weight_name=weight.name,
        engine=job.engine,
        budget=job.budget,
        sequence=job.sequence,
        grouping=job.grouping,
        status=status,
        stdout=stdout,
    )
    if worker_sandbox is not None and task_store is not None and task_dir is not None:
        stdout_raw = eval_execution.stdout if eval_execution is not None else stdout
        stderr_raw = eval_execution.stderr if eval_execution is not None else ""
        stdout_path, stderr_path = write_task_stdout_stderr(task_dir, stdout_raw, stderr_raw)
        write_worker_status(
            task_store,
            worker_sandbox,
            status="collecting",
            current_task_id=task_id,
            crop_affinity=project_crop_name(),
            failure_count=retry_index,
        )
        runtime_archive = archive_tree(build_workspace_runtime_paths(workspace_dir)[0], task_dir / "runtime")
        manifest_path = runtime_archive / "run_manifest.json"
        contract_path = runtime_archive / "contract_report.json"
        contract_payload = load_json_dict(contract_path)
        contract_status = str(contract_payload.get("status", "")).strip()
        task_error_code = ""
        task_error_summary = ""
        if status != "ok":
            if contract_status and contract_status.lower() != "ok":
                task_error_code = "E_CONTRACT"
                task_error_summary = contract_status
            else:
                task_error_code = "E_DSSAT_EXEC"
                task_error_summary = f"matrix job finished with status={status}"
        task_store.write_task_state(
            task_dir,
            TaskStateRecord(
                task_id=task_id,
                state="collecting",
                worker_id=worker_sandbox.worker_id,
                assigned_at=executed_at,
                started_at=executed_at,
                retry_count=retry_index,
            ),
        )
        task_store.write_task_state(
            task_dir,
            TaskStateRecord(
                task_id=task_id,
                state="passed" if status == "ok" else "failed_fatal",
                worker_id=worker_sandbox.worker_id,
                assigned_at=executed_at,
                started_at=executed_at,
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                retry_count=retry_index,
                error_code=task_error_code,
                error_summary=task_error_summary,
            ),
        )
        task_store.write_task_result(
            task_dir,
            TaskResultRecord(
                task_id=task_id,
                status=status,
                exit_code=eval_execution.returncode if eval_execution is not None else 0,
                duration_sec=result.duration_sec,
                score=result.score,
                contract_status=contract_status,
                artifact_index={
                    "runtime_dir": str(runtime_archive.resolve()),
                    "run_manifest": str(manifest_path.resolve()),
                    "contract_report": str(contract_path.resolve()),
                },
                manifest_path=str(manifest_path.resolve()),
                contract_report_path=str(contract_path.resolve()),
                stdout_path=str(stdout_path.resolve()),
                stderr_path=str(stderr_path.resolve()),
            ),
        )
        write_worker_status(
            task_store,
            worker_sandbox,
            status="idle",
            crop_affinity=project_crop_name(),
        )
        task_store.write_current_task(worker_sandbox.current_task_path, None)
    return result


def candidate_name(spec: CandidateSpec) -> str:
    pieces = [
        spec.yield_transform[:3],
        spec.lai_transform[:3],
        spec.aggregator,
        f"s{str(spec.shape).replace('.', '')}",
        f"b{str(spec.balance_weight).replace('.', '')}",
        f"t{str(spec.treatment_weight).replace('.', '')}",
        f"c{str(spec.cross_weight).replace('.', '')}",
    ]
    return "AI_" + "_".join(pieces)


def candidate_description(spec: CandidateSpec) -> str:
    return (
        f"yield={spec.yield_transform}, lai={spec.lai_transform}, "
        f"agg={spec.aggregator}, shape={spec.shape}, "
        f"balance={spec.balance_weight}, treatment={spec.treatment_weight}, "
        f"cross={spec.cross_weight}"
    )


def render_strategy(spec: CandidateSpec) -> str:
    return f"""import numpy as np

def _metric_loss(sim, obs, kind):
    eps = 1e-8
    err = sim - obs
    abs_obs = np.abs(obs) + eps
    rel = np.abs(err) / abs_obs
    if kind == "nrmse":
        return float(np.sqrt(np.mean(err**2)) / (np.mean(np.abs(obs)) + eps))
    if kind == "relative_mae":
        return float(np.mean(rel))
    if kind == "smape":
        return float(np.mean((2.0 * np.abs(err)) / (np.abs(sim) + np.abs(obs) + eps)))
    if kind == "log_rmse":
        log_sim = np.log(np.clip(sim, eps, None))
        log_obs = np.log(np.clip(obs, eps, None))
        return float(np.sqrt(np.mean((log_sim - log_obs)**2)))
    delta = 0.25
    huber = np.where(rel <= delta, 0.5 * rel**2, delta * (rel - 0.5 * delta))
    return float(np.mean(huber))

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    eps = 1e-8
    loss_y = _metric_loss(sim_yield, obs_yield, "{spec.yield_transform}")
    loss_l = _metric_loss(sim_lai, obs_lai, "{spec.lai_transform}")
    shaped = np.power(np.clip(np.array([loss_y, loss_l], dtype=float), eps, None), {spec.shape})
    if "{spec.aggregator}" == "sum":
        base = float(np.sum(shaped))
    elif "{spec.aggregator}" == "l2":
        base = float(np.sqrt(np.sum(shaped**2)))
    else:
        base = float(0.5 * np.mean(shaped) + 0.5 * np.max(shaped))
    imbalance = float(np.abs(shaped[0] - shaped[1]))
    rel_y = np.abs(sim_yield - obs_yield) / (np.abs(obs_yield) + eps)
    rel_l = np.abs(sim_lai - obs_lai) / (np.abs(obs_lai) + eps)
    treatment_penalty = float(np.var(rel_y) + np.var(rel_l))
    cross_penalty = float(np.sqrt(np.clip(loss_y * loss_l, eps, None)))
    total = base + ({spec.balance_weight} * imbalance) + ({spec.treatment_weight} * treatment_penalty) + ({spec.cross_weight} * cross_penalty)
    return float(total if np.isfinite(total) else 1e9)
"""


def seed_specs() -> list[CandidateSpec]:
    return [
        CandidateSpec("nrmse", "nrmse", "sum", 1.0, 0.1, 0.05, 0.0),
        CandidateSpec("log_rmse", "log_rmse", "sum", 1.0, 0.0, 0.05, 0.0),
        CandidateSpec("nrmse", "log_rmse", "l2", 1.15, 0.1, 0.12, 0.05),
        CandidateSpec("smape", "log_rmse", "l2", 1.15, 0.25, 0.12, 0.05),
        CandidateSpec("relative_mae", "huber_rel", "mean_max", 1.35, 0.25, 0.12, 0.12),
        CandidateSpec("huber_rel", "nrmse", "mean_max", 1.15, 0.45, 0.2, 0.05),
    ]


def next_value(values: tuple[float | str, ...], current: float | str, shift: int) -> float | str:
    idx = values.index(current)
    return values[(idx + shift) % len(values)]


def mutate_spec(spec: CandidateSpec, round_index: int) -> list[CandidateSpec]:
    shift = round_index + 1
    mutants = [
        replace(spec, yield_transform=str(next_value(TRANSFORMS, spec.yield_transform, shift))),
        replace(spec, lai_transform=str(next_value(TRANSFORMS, spec.lai_transform, shift))),
        replace(
            spec,
            aggregator=str(next_value(AGGREGATORS, spec.aggregator, 1)),
            balance_weight=float(next_value(BALANCE_WEIGHTS, spec.balance_weight, shift)),
        ),
        replace(
            spec,
            shape=float(next_value(SHAPES, spec.shape, 1)),
            treatment_weight=float(next_value(TREATMENT_WEIGHTS, spec.treatment_weight, shift)),
        ),
        replace(
            spec,
            yield_transform=str(next_value(TRANSFORMS, spec.yield_transform, shift)),
            lai_transform=str(next_value(TRANSFORMS, spec.lai_transform, shift + 1)),
            cross_weight=float(next_value(CROSS_WEIGHTS, spec.cross_weight, 1)),
        ),
    ]
    unique: list[CandidateSpec] = []
    seen: set[CandidateSpec] = set()
    for mutant in mutants:
        if mutant in seen:
            continue
        unique.append(mutant)
        seen.add(mutant)
    return unique


def evaluate_candidate(
    name: str,
    description: str,
    source: str,
    best_score: float,
    best_source: str,
    env_overrides: dict[str, str] | None = None,
    negative_ref_score: float | None = None,
) -> CandidateResult:
    try:
        validate_strategy_source(source)
        write_text(STRATEGY_PATH, source)
        stdout, score = run_eval(env_overrides)
        status = "keep" if score < best_score else "discard"
    except Exception as exc:
        stdout = f"{type(exc).__name__}: {exc}"
        score = 999.0
        status = "crash"
    if status != "keep":
        write_text(STRATEGY_PATH, best_source)
    result = build_candidate_result(
        name=name,
        description=description,
        score=score,
        status=status,
        source=source,
        stdout=stdout,
        negative_ref_score=negative_ref_score,
    )
    write_log(f"### Strategy: {name}")
    write_log(f"**Description:** {description}")
    write_log(f"**Score:** {score}")
    write_log(f"**Status:** {status}")
    write_log(f"**Hash:** {strategy_hash(source)}")
    if result.train_score == result.train_score:
        write_log(f"**Final_Train_Score:** {result.train_score:.6f}")
    if result.valid_score == result.valid_score:
        write_log(f"**Final_Valid_Score:** {result.valid_score:.6f}")
    if result.all_score == result.all_score:
        write_log(f"**Final_All_Score:** {result.all_score:.6f}")
    if result.train_mean_nrmse == result.train_mean_nrmse:
        write_log(f"**TRAIN_MEAN_NRMSE:** {result.train_mean_nrmse:.6f}")
    if result.valid_mean_nrmse == result.valid_mean_nrmse:
        write_log(f"**VALID_MEAN_NRMSE:** {result.valid_mean_nrmse:.6f}")
    if result.all_mean_nrmse == result.all_mean_nrmse:
        write_log(f"**ALL_MEAN_NRMSE:** {result.all_mean_nrmse:.6f}")
    if result.valid_yield_nrmse == result.valid_yield_nrmse:
        write_log(f"**VALID_{result.yield_metric}_NRMSE:** {result.valid_yield_nrmse:.6f}")
    if result.valid_yield_bias == result.valid_yield_bias:
        write_log(f"**VALID_{result.yield_metric}_BIAS:** {result.valid_yield_bias:.6f}")
    if result.negative_ref_score == result.negative_ref_score:
        write_log(f"**Negative_Ref_Score:** {result.negative_ref_score:.6f}")
        write_log(f"**Negative_Optimization:** {str(result.negative_optimization).lower()}")
    write_log(f"```python\n{source}\n```")
    write_log(f"<details><summary>Output</summary>\n\n```\n{stdout}\n```\n</details>\n")
    return result


def run_benchmark() -> None:
    migrate_legacy_root_artifacts()
    ensure_log_header()
    original_strategy = read_text(STRATEGY_PATH)
    write_log(f"## Benchmark Session Started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    try:
        for name, code in BENCHMARK_STRATEGIES.items():
            print(f"Running benchmark: {name}...")
            result = evaluate_candidate(
                name,
                "static benchmark",
                code,
                float("inf"),
                original_strategy,
                {"AR_WEIGHTING": "w_custom_strategy"},
            )
            write_text(STRATEGY_PATH, original_strategy if result.status == "discard" else code)
        for mode_name, mode_val in ADDITIONAL_MODES.items():
            print(f"Running baseline mode: {mode_name}...")
            stdout, score = run_eval(mode_val)
            write_log(f"### Strategy: {mode_name}")
            write_log(f"**Score:** {score}")
            write_log(f"<details><summary>Output</summary>\n\n```\n{stdout}\n```\n</details>\n")
    finally:
        write_text(STRATEGY_PATH, original_strategy)
    print(f"Benchmark complete. Log written to {LOG_PATH}")


def run_innovate(rounds: int, beam_width: int, seed_limit: int) -> None:
    migrate_legacy_root_artifacts()
    ensure_log_header()
    original_strategy = read_text(STRATEGY_PATH)
    write_log(f"## Innovation Session Started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    best_source = original_strategy
    best_score = 999.0
    results: list[CandidateResult] = []
    seen_sources: set[str] = set()
    try:
        negative_ref_profile = negative_optimization_reference_profile()
        negative_ref_stdout, negative_ref_score = run_baseline_reference(negative_ref_profile)
        write_log("### Negative Optimization Reference")
        write_log(f"**Profile:** {negative_ref_profile}")
        write_log(f"**Score:** {negative_ref_score:.6f}")
        write_log(f"<details><summary>Output</summary>\n\n```\n{negative_ref_stdout}\n```\n</details>\n")
        baseline = evaluate_candidate(
            "Current_Strategy_Baseline",
            "user-provided starting point",
            original_strategy,
            float("inf"),
            original_strategy,
            {"AR_WEIGHTING": "w_custom_strategy"},
            negative_ref_score=negative_ref_score,
        )
        baseline.status = "keep"
        best_score = baseline.score
        best_source = original_strategy
        results.append(baseline)
        seen_sources.add(strategy_hash(original_strategy))

        initial_specs = seed_specs()[: max(1, seed_limit)]
        for spec in initial_specs:
            source = render_strategy(spec)
            code_hash = strategy_hash(source)
            if code_hash in seen_sources:
                continue
            result = evaluate_candidate(
                candidate_name(spec),
                candidate_description(spec),
                source,
                best_score,
                best_source,
                {"AR_WEIGHTING": "w_custom_strategy"},
                negative_ref_score=negative_ref_score,
            )
            result.spec = spec
            results.append(result)
            seen_sources.add(code_hash)
            if result.score < best_score:
                best_score = result.score
                best_source = source

        for round_index in range(rounds):
            ranked_specs = [item for item in sorted(results, key=lambda item: item.score) if item.spec is not None][: max(1, beam_width)]
            if not ranked_specs:
                break
            for parent in ranked_specs:
                parent_spec = parent.spec
                if parent_spec is None:
                    continue
                for spec in mutate_spec(parent_spec, round_index):
                    source = render_strategy(spec)
                    code_hash = strategy_hash(source)
                    if code_hash in seen_sources:
                        continue
                    result = evaluate_candidate(
                        candidate_name(spec),
                        candidate_description(spec),
                        source,
                        best_score,
                        best_source,
                        {"AR_WEIGHTING": "w_custom_strategy"},
                        negative_ref_score=negative_ref_score,
                    )
                    result.spec = spec
                    results.append(result)
                    seen_sources.add(code_hash)
                    if result.score < best_score:
                        best_score = result.score
                        best_source = source

        write_text(STRATEGY_PATH, best_source)
        best_name = min(results, key=lambda item: item.score).name if results else "None"
        eligible = [
            item for item in results if not item.negative_optimization and item.valid_score == item.valid_score
        ]
        write_log("### Innovation Winner")
        write_log(f"**Best Strategy:** {best_name}")
        write_log(f"**Best Score:** {best_score}\n")
        if eligible:
            best_guardrail = min(eligible, key=lambda item: item.score)
            write_log("### Round4 Guardrail Winner")
            write_log(f"**Strategy:** {best_guardrail.name}")
            write_log(f"**Score:** {best_guardrail.score:.6f}")
            write_log(f"**Final_Valid_Score:** {best_guardrail.valid_score:.6f}")
            if best_guardrail.all_mean_nrmse == best_guardrail.all_mean_nrmse:
                write_log(f"**ALL_MEAN_NRMSE:** {best_guardrail.all_mean_nrmse:.6f}")
            if best_guardrail.valid_yield_nrmse == best_guardrail.valid_yield_nrmse:
                write_log(f"**VALID_{best_guardrail.yield_metric}_NRMSE:** {best_guardrail.valid_yield_nrmse:.6f}")
            if best_guardrail.valid_yield_bias == best_guardrail.valid_yield_bias:
                write_log(f"**VALID_{best_guardrail.yield_metric}_BIAS:** {best_guardrail.valid_yield_bias:.6f}")
        print(f"Best strategy: {best_name}")
        print(f"Best score: {best_score:.6f}")
    finally:
        write_text(STRATEGY_PATH, best_source)
    print(f"Innovation loop complete. Log written to {LOG_PATH}")


def compatible_groupings_for_sequence(sequence: str) -> list[str]:
    configured = list(_CROP_REGISTRY_MODULE.resolve_groupings_for_sequence(load_project_config(), sequence))
    if configured:
        return configured
    return ["g1_flat_all_in_one", "g3_dssat_extended"]


def run_matrix(
    weights: list[str],
    engines: list[str],
    budgets: list[str],
    sequences: list[str],
    groupings: list[str],
    plan: str = "custom",
    max_workers: int | None = None,
    report_plan: str = "",
    top_n: int = 10,
    paper_plan: str = "",
    paper_budget: str = "",
    paper_status: str = "ok",
    paper_yield_metric: str = "",
    paper_protocol_status: str = "auto",
    paper_require_validation: bool = False,
    paper_require_better_than: str = "",
    paper_max_rows: int = 20,
    top_k_per_panel: int = 3,
    quality_gate_stop_level: str = "required",
    retry_limit: int | None = None,
    resume: bool = False,
    batch_root_override: str = "",
) -> None:
    migrate_legacy_root_artifacts()
    ensure_matrix_header()
    original_strategy = read_text(STRATEGY_PATH)
    weights, engines, budgets, sequences, groupings = resolve_matrix_scope(
        plan,
        weights,
        engines,
        budgets,
        sequences,
        groupings,
    )
    selected_weights = select_weight_candidates(weights, original_strategy)
    normalized_engines = [canonical_engine_name(engine) for engine in engines]
    yield_metric = project_yield_metric()
    negative_ref_profile = negative_optimization_reference_profile()
    write_matrix_log(f"## Matrix Session Started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    write_matrix_log(f"- Plan: {plan}")
    write_matrix_log(f"- Weights: {', '.join(weights)}")
    write_matrix_log(f"- Engines: {', '.join(normalized_engines)}")
    write_matrix_log(f"- Budgets: {', '.join(budgets)}")
    write_matrix_log(f"- Sequences: {', '.join(sequences)}\n")
    write_matrix_log(f"- Groupings: {', '.join(groupings)}\n")
    scheduler_config, scheduler_config_source = resolve_scheduler_config(
        PROJECT_CONFIG,
        max_workers=max_workers,
        retry_limit=retry_limit,
    )
    write_matrix_log(f"- Max workers: {scheduler_config.task_parallelism}\n")
    write_matrix_log(f"- Retry limit: {scheduler_config.retry_limit}\n")
    write_matrix_log(f"- Scheduler config source: {scheduler_config_source}\n")
    write_matrix_log(f"- Heartbeat interval sec: {scheduler_config.heartbeat_interval_sec}\n")
    write_matrix_log(f"- Stale timeout sec: {scheduler_config.stale_timeout_sec}\n")
    results: list[MatrixResult] = []
    batch_root: Path | None = None
    batch_id = ""
    try:
        b0_stdout, b0_score = run_baseline_reference("b0_official_frozen")
        b1_stdout, b1_score = run_baseline_reference("b1_sandbox_feasible")
        negative_ref_stdout, negative_ref_score = run_baseline_reference(negative_ref_profile)
        write_matrix_log("## B0 Official Frozen Baseline")
        write_matrix_log(f"- Score: {b0_score:.6f}")
        write_matrix_log(f"<details><summary>Output</summary>\n\n```\n{b0_stdout}\n```\n</details>\n")
        write_matrix_log("## B1 Sandbox Feasible Baseline")
        write_matrix_log(f"- Score: {b1_score:.6f}")
        write_matrix_log(f"<details><summary>Output</summary>\n\n```\n{b1_stdout}\n```\n</details>\n")
        write_matrix_log("## Negative Optimization Reference")
        write_matrix_log(f"- Profile: {negative_ref_profile}")
        write_matrix_log(f"- Score: {negative_ref_score:.6f}")
        write_matrix_log(f"<details><summary>Output</summary>\n\n```\n{negative_ref_stdout}\n```\n</details>\n")
        jobs: list[MatrixJob] = []
        job_index = 0
        for weight, engine, budget, sequence in product(selected_weights, normalized_engines, budgets, sequences):
            allowed_groupings = [grouping for grouping in groupings if grouping in compatible_groupings_for_sequence(sequence)]
            for grouping in allowed_groupings:
                if not plan_allows_cell(plan, weight.weight_mode, sequence, grouping):
                    continue
                jobs.append(
                    MatrixJob(
                        index=job_index,
                        weight=weight,
                        engine=engine,
                        budget=budget,
                        sequence=sequence,
                        grouping=grouping,
                    )
                )
                job_index += 1
        resumed_results_by_index: dict[int, MatrixResult] = {}
        if resume:
            batch_root, resumed_results_by_index, jobs, batch_id = resume_batch(
                batch_root_override,
                jobs,
                negative_ref_profile=negative_ref_profile,
                negative_ref_score=negative_ref_score,
                yield_metric=yield_metric,
            )
            write_matrix_log(f"- Resume batch root: {batch_root}")
            write_matrix_log(f"- Resume recovered tasks: {len(resumed_results_by_index)}")
            write_matrix_log(f"- Resume pending tasks: {len(jobs)}\n")
        effective_max_workers = scheduler_config.task_parallelism
        if effective_max_workers > 1 or resume:
            ordered_results, batch_root, batch_id = execute_matrix_jobs_with_worker_pool(
                jobs,
                plan=plan,
                negative_ref_profile=negative_ref_profile,
                negative_ref_score=negative_ref_score,
                yield_metric=yield_metric,
                original_strategy=original_strategy,
                max_workers=effective_max_workers,
                retry_limit=scheduler_config.retry_limit,
                batch_root_override=batch_root,
                batch_id_override=batch_id,
                resume=resume,
                scheduler_config_override=scheduler_config,
            )
        else:
            ordered_results = [
                execute_matrix_job_with_retry(
                    job,
                    plan,
                    negative_ref_profile,
                    negative_ref_score,
                    yield_metric,
                    original_strategy,
                    effective_max_workers,
                    retry_limit=scheduler_config.retry_limit,
                    heartbeat_interval_sec=scheduler_config.heartbeat_interval_sec,
                    stale_timeout_sec=scheduler_config.stale_timeout_sec,
                )
                for job in jobs
            ]
        if resumed_results_by_index:
            indexed_by_job: dict[int, MatrixResult] = {index: result for index, result in resumed_results_by_index.items()}
            for result in ordered_results:
                task_index = parse_task_index(result.task_id)
                if task_index is not None:
                    indexed_by_job[task_index] = result
            ordered_results = [indexed_by_job[index] for index in sorted(indexed_by_job)]
        for result in ordered_results:
            result.baseline_b0_score = b0_score
            result.baseline_b1_score = b1_score
            results.append(result)
            append_matrix_tsv(result)
            append_experiment_runs_tsv(result)
            append_experiment_params_tsv(result)
            append_experiment_metrics_long_tsv(result)
            append_experiment_aggregate_metrics_tsv(result)
            write_matrix_result_log(result)
            mark_task_result_aggregated(result)
        rebuild_experiment_summary_exports()
        if results:
            report_outputs = rebuild_main_matrix_report_artifacts(
                report_plan=report_plan,
                top_n=max(1, top_n),
                paper_plan=paper_plan,
                paper_budget=paper_budget,
                paper_status=paper_status,
                paper_yield_metric=paper_yield_metric,
                paper_protocol_status=paper_protocol_status,
                paper_require_validation=paper_require_validation,
                paper_require_better_than=paper_require_better_than,
                paper_max_rows=max(1, paper_max_rows),
                top_k_per_panel=max(1, top_k_per_panel),
            )
            quality_gate_rows = read_tsv_rows(report_outputs["quality_gate"])
            overall_status = resolve_main_matrix_quality_gate_overall_status(quality_gate_rows)
            decision = resolve_main_matrix_quality_gate_batch_decision(
                quality_gate_rows,
                stop_level=quality_gate_stop_level,
            )
            normalized_stop_level = normalize_main_matrix_quality_gate_stop_level(quality_gate_stop_level)
            failing_gate_keys = "|".join(
                str(row.get("gate_key", "")).strip()
                for row in quality_gate_rows
                if str(row.get("status", "")).strip().lower() != "pass"
            ) or "none"
            write_matrix_log("## Matrix Quality Gate")
            write_matrix_log(f"- Stop level: {normalized_stop_level}")
            write_matrix_log(f"- Overall status: {overall_status}")
            write_matrix_log(f"- Decision: {decision}")
            write_matrix_log(f"- Failing gates: {failing_gate_keys}")
            write_matrix_log(f"- Quality gate TSV: {report_outputs['quality_gate']}\n")
            print(
                "Matrix quality gate: "
                f"stop_level={normalized_stop_level} overall={overall_status} decision={decision}"
            )
            if batch_root is not None and batch_id:
                final_batch_status = "completed_with_failures" if matrix_batch_has_failures(results) else "completed"
                task_store = TaskStore(batch_root)
                task_store.update_batch_manifest(status=final_batch_status)
                report_path = write_matrix_batch_report(
                    batch_root=batch_root,
                    batch_id=batch_id,
                    plan=plan,
                    results=results,
                    quality_gate_rows=quality_gate_rows,
                    report_outputs=report_outputs,
                    final_status=final_batch_status,
                )
                task_store.update_batch_manifest(batch_report_path=str(report_path.resolve()))
                task_store.update_batch_state(
                    **build_batch_state_payload(
                        batch_root=batch_root,
                        batch_id=batch_id,
                        status=final_batch_status,
                        total_jobs=len(results),
                        results=results,
                        quality_gate_overall=overall_status,
                        quality_gate_decision=decision,
                        batch_report_path=str(report_path.resolve()),
                        created_at=str(load_json_dict(batch_root / "batch_state.json").get("created_at", "")),
                    )
                )
            if decision == "stop":
                if batch_root is not None:
                    task_store = TaskStore(batch_root)
                    task_store.update_batch_manifest(status="failed")
                    task_store.update_batch_state(
                        **build_batch_state_payload(
                            batch_root=batch_root,
                            batch_id=batch_id,
                            status="failed",
                            total_jobs=len(results),
                            results=results,
                            quality_gate_overall=overall_status,
                            quality_gate_decision=decision,
                            batch_report_path=str((batch_root / "batch_report.json").resolve()),
                            created_at=str(load_json_dict(batch_root / "batch_state.json").get("created_at", "")),
                        )
                    )
                raise RuntimeError(
                    "Main matrix quality gate blocked publish decision: "
                    f"stop_level={normalized_stop_level}, overall={overall_status}, failing_gates={failing_gate_keys}"
                )
    finally:
        write_text(STRATEGY_PATH, original_strategy)
    if results:
        best = min(results, key=lambda item: item.score)
        write_matrix_log("## Matrix Best Cell")
        write_matrix_log(
            f"- {best.weight_name} | {best.engine} | {best.budget} | {best.sequence} | {best.grouping} | "
            f"score={best.score:.6f}\n"
        )
        print(
            f"Best matrix cell: {best.weight_name} | {best.engine} | "
            f"{best.budget} | {best.sequence} | {best.grouping} | {best.score:.6f}"
        )
    print(
        "Matrix loop complete. Artifacts written to "
        f"{ARTIFACTS_DIR} "
        "(matrix_experiments.md, matrix_results.tsv, experiment_runs.tsv, experiment_protocol_artifacts.tsv, experiment_params.tsv, "
        "experiment_metrics_long.tsv, experiment_aggregate_metrics.tsv, experiment_summary.tsv, "
        "experiment_scatter_1to1.tsv, experiment_heatmap_wide.tsv, experiment_metric_split_heatmap.tsv, "
        "experiment_residuals_wide.tsv, experiment_figure_ready.tsv)"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("innovate", "benchmark", "matrix", "report"), default="innovate")
    parser.add_argument(
        "--plan",
        choices=("custom", "phase0", "phase1", "phase1_o1", "phase1_o2", "phase1_o3", "phase2", "phase3", "core", "frontier"),
        default="phase1",
    )
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--beam-width", type=int, default=2)
    parser.add_argument("--seed-limit", type=int, default=4)
    parser.add_argument(
        "--weights",
        default="W0_Raw_Identity,W1_Inverse_Variance,W2_Inverse_RMSE,W3_CV_Based,W4_Min_Max_Equal,W5_Mean_Normalization,W6_Log_Transformation,W7_Equal_Contribution,W8_DSSAT_PEST_Group_Max,W9_Pareto_No_PreWeight",
    )
    parser.add_argument("--engines", default="o1_least_squares,o2_pestpp_ies,o3_anneal_nm,o4_nsga2")
    parser.add_argument("--budgets", default="quick")
    parser.add_argument("--sequences", default="s1_naive_joint,s2_sequential_phase,s3_wls_joint")
    parser.add_argument("--groupings", default="g1_flat_all_in_one,g3_dssat_extended")
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument("--report-plan", default="")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--paper-plan", default="")
    parser.add_argument("--paper-budget", default="")
    parser.add_argument("--paper-status", default="ok")
    parser.add_argument("--paper-yield-metric", default="")
    parser.add_argument("--paper-protocol-status", choices=("auto", "any", "ok", "degraded", "missing"), default="auto")
    parser.add_argument("--paper-require-validation", action="store_true")
    parser.add_argument("--paper-require-better-than", choices=("b0", "b1", "negative_ref"), default="")
    parser.add_argument("--paper-max-rows", type=int, default=20)
    parser.add_argument("--top-k-per-panel", type=int, default=3)
    parser.add_argument("--quality-gate-stop-level", choices=("off", "required", "advisory"), default="required")
    parser.add_argument("--retry-limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--batch-root", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "benchmark":
        run_benchmark()
        return
    if args.mode == "matrix":
        run_matrix(
            weights=parse_csv_arg(args.weights),
            engines=parse_csv_arg(args.engines),
            budgets=parse_csv_arg(args.budgets),
            sequences=parse_csv_arg(args.sequences),
            groupings=parse_csv_arg(args.groupings),
            plan=args.plan,
            max_workers=max(1, args.max_workers) if args.max_workers is not None else None,
            report_plan=args.report_plan,
            top_n=max(1, args.top_n),
            paper_plan=args.paper_plan,
            paper_budget=args.paper_budget,
            paper_status=args.paper_status,
            paper_yield_metric=args.paper_yield_metric,
            paper_protocol_status=args.paper_protocol_status,
            paper_require_validation=args.paper_require_validation,
            paper_require_better_than=args.paper_require_better_than,
            paper_max_rows=max(1, args.paper_max_rows),
            top_k_per_panel=max(1, args.top_k_per_panel),
            quality_gate_stop_level=args.quality_gate_stop_level,
            retry_limit=max(0, args.retry_limit) if args.retry_limit is not None else None,
            resume=args.resume,
            batch_root_override=args.batch_root,
        )
        return
    if args.mode == "report":
        outputs = rebuild_main_matrix_report_artifacts(
            report_plan=args.report_plan,
            top_n=max(1, args.top_n),
            paper_plan=args.paper_plan,
            paper_budget=args.paper_budget,
            paper_status=args.paper_status,
            paper_yield_metric=args.paper_yield_metric,
            paper_protocol_status=args.paper_protocol_status,
            paper_require_validation=args.paper_require_validation,
            paper_require_better_than=args.paper_require_better_than,
            paper_max_rows=max(1, args.paper_max_rows),
            top_k_per_panel=max(1, args.top_k_per_panel),
        )
        print(
            "Main matrix report written to "
            f"{outputs['report']}, {outputs['leaderboard']}, {outputs['dimension_summary']}, "
            f"{outputs['baseline_summary']}, {outputs['baseline_detail']}, {outputs['key_indicator_table']}, "
            f"{outputs['baseline_winners']}, {outputs['metric_snapshot']}, {outputs['paper_summary']}, "
            f"{outputs['protocol_overview']}, {outputs['appendix_index']}, {outputs['protocol_paper_table']}, "
            f"{outputs['paper_main_table']}, {outputs['paper_appendix_table']}, {outputs['paper_table']}, {outputs['topk_overall']}, "
            f"{outputs['topk_by_engine']}, {outputs['topk_by_weight']}, {outputs['topk_by_sequence']}, "
            f"{outputs['topk_by_grouping']}, {outputs['topk_validation_only']}, "
            f"{outputs['topk_by_budget']}, {outputs['topk_by_validation_budget']}, and {outputs['topk_improvement']}"
        )
        return
    run_innovate(rounds=max(1, args.rounds), beam_width=max(1, args.beam_width), seed_limit=max(1, args.seed_limit))


if __name__ == "__main__":
    main()
