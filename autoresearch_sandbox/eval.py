import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
import functools
from pathlib import Path

import strategy
import numpy as np
_SCIPY_IMPORT_ERROR: ModuleNotFoundError | None
try:
    from scipy.optimize import dual_annealing, least_squares, minimize
except ModuleNotFoundError as exc:
    _SCIPY_IMPORT_ERROR = exc

    def _missing_scipy(*args: object, **kwargs: object) -> object:
        raise ModuleNotFoundError("scipy is required for optimization modes in autoresearch_sandbox.eval") from _SCIPY_IMPORT_ERROR

    dual_annealing = _missing_scipy
    least_squares = _missing_scipy
    minimize = _missing_scipy
else:
    _SCIPY_IMPORT_ERROR = None


LEGACY_WHEAT_PARAM_NAMES = ["p1v", "p1d", "p5", "g1", "g2", "g3", "phint"]
DEFAULT_PROJECT_CONFIG_CANDIDATES = ("project.json", "project_wheat.json")


@functools.lru_cache(maxsize=None)
def load_mvp_public_api(public_api_path: Path):
    resolved_public_api_path = Path(public_api_path).resolve()
    spec = importlib.util.spec_from_file_location(
        "mvp_public_api_runtime_eval",
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
class EvalPaths:
    sandbox_dir: Path
    mvp_root: Path
    public_api_path: Path
    project_config_path: Path
    runs_dir: Path
    runtime_dir: Path
    params_path: Path
    pest_out_path: Path
    case_template_dir: Path
    case_support_root: Path


def build_eval_paths(sandbox_dir: Path | None = None, mvp_root: Path | None = None) -> EvalPaths:
    sandbox_source: str | os.PathLike[str] = sandbox_dir or os.environ.get("AR_SANDBOX_DIR") or Path(__file__).resolve().parent
    resolved_sandbox_dir = Path(sandbox_source).resolve()
    mvp_root_source: str | os.PathLike[str] = (
        mvp_root or os.environ.get("AR_MVP_ROOT") or (resolved_sandbox_dir.parent / "mvp_pest_mgda")
    )
    resolved_mvp_root = Path(mvp_root_source).resolve()
    runs_dir = resolved_sandbox_dir / "runs"
    runtime_dir = runs_dir / "runtime"
    return EvalPaths(
        sandbox_dir=resolved_sandbox_dir,
        mvp_root=resolved_mvp_root,
        public_api_path=resolved_mvp_root / "public_api.py",
        project_config_path=resolve_sandbox_project_config_path(
            resolved_sandbox_dir,
            resolved_mvp_root / "public_api.py",
        ),
        runs_dir=runs_dir,
        runtime_dir=runtime_dir,
        params_path=runtime_dir / "params.dat",
        pest_out_path=runtime_dir / "pest_out.dat",
        case_template_dir=resolved_mvp_root / "scripts" / "dssat_case",
        case_support_root=resolved_sandbox_dir.parent,
    )


PATHS = build_eval_paths()
SANDBOX_DIR = PATHS.sandbox_dir
PROJECT_CONFIG_PATH = PATHS.project_config_path
PESTPP_ROOT = PATHS.mvp_root
SRC_DIR = PESTPP_ROOT / "src"
PUBLIC_API_PATH = PATHS.public_api_path
RUNS_DIR = PATHS.runs_dir
RUNTIME_DIR = PATHS.runtime_dir
RUN_MODEL_PATH = SRC_DIR / "run_model.py"
MGDA_UPDATE_PATH = SRC_DIR / "mgda_update.py"


_PUBLIC_API = load_mvp_public_api(PUBLIC_API_PATH)
_PEST_BUILDER_MODULE = _PUBLIC_API.pest_builder
run_build_pest_setup = _PEST_BUILDER_MODULE.run_build_pest_setup
_PEST_RUNNER_MODULE = _PUBLIC_API.pest_runner
build_run_model_env = _PEST_RUNNER_MODULE.build_run_model_env
runner_cleanup_pestpp_outputs = _PEST_RUNNER_MODULE.cleanup_pestpp_outputs
runner_parse_best_glm_result = _PEST_RUNNER_MODULE.parse_best_glm_result
runner_parse_best_ies_result = _PEST_RUNNER_MODULE.parse_best_ies_result
run_compare_model = _PEST_RUNNER_MODULE.run_compare_model
run_pestpp_cli = _PEST_RUNNER_MODULE.run_pestpp_cli
_RESULT_SCHEMA_MODULE = _PUBLIC_API.result_schema
aggregate_value_map = _RESULT_SCHEMA_MODULE.aggregate_value_map
build_evaluation_result = _RESULT_SCHEMA_MODULE.build_evaluation_result
build_evaluation_result_line = _RESULT_SCHEMA_MODULE.build_evaluation_result_line
iter_aggregate_value_records = _RESULT_SCHEMA_MODULE.iter_aggregate_value_records
_DSSAT_IO_MODULE = _PUBLIC_API.dssat_io
resolve_initial_parameter_values = _DSSAT_IO_MODULE.resolve_initial_parameter_values
resolve_parameter_bounds_pairs = _DSSAT_IO_MODULE.resolve_parameter_bounds_pairs
resolve_parameter_names = _DSSAT_IO_MODULE.resolve_parameter_names
resolve_dssat_case_dir = _DSSAT_IO_MODULE.resolve_dssat_case_dir
resolve_dssat_root = _DSSAT_IO_MODULE.resolve_dssat_root
resolve_dssat_genotype_dir = _DSSAT_IO_MODULE.resolve_dssat_genotype_dir

PARAMS_PATH = PATHS.params_path
PEST_OUT_PATH = PATHS.pest_out_path
CASE_TEMPLATE_DIR = PATHS.case_template_dir
CASE_SUPPORT_ROOT = PATHS.case_support_root


def ensure_runtime_dir() -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR


def migrate_legacy_runtime_files() -> dict[Path, Path]:
    ensure_runtime_dir()
    migrated: dict[Path, Path] = {}
    legacy_to_standard = (
        (SANDBOX_DIR / "params.dat", PARAMS_PATH),
        (SANDBOX_DIR / "pest_out.dat", PEST_OUT_PATH),
    )
    for legacy_path, standard_path in legacy_to_standard:
        resolved_legacy_path = legacy_path.resolve()
        resolved_standard_path = standard_path.resolve()
        if resolved_legacy_path == resolved_standard_path or not legacy_path.exists():
            continue
        if standard_path.exists():
            if standard_path.read_bytes() == legacy_path.read_bytes():
                legacy_path.unlink()
            continue
        legacy_path.replace(standard_path)
        migrated[resolved_legacy_path] = resolved_standard_path
    return migrated


def ensure_case_support_files(case_dir: Path) -> Path:
    case_dir.mkdir(parents=True, exist_ok=True)
    for name in ("DSSAT48.INP", "DSSAT48.INH"):
        dst = case_dir / name
        if dst.exists():
            continue
        for src in (CASE_TEMPLATE_DIR / name, CASE_SUPPORT_ROOT / name):
            if src.exists():
                shutil.copy2(src, dst)
                break
    geno_dir = case_dir / "GENOTYPE"
    geno_dir.mkdir(parents=True, exist_ok=True)
    for source_root in (CASE_TEMPLATE_DIR / "GENOTYPE", CASE_SUPPORT_ROOT / "GENOTYPE"):
        if not source_root.exists():
            continue
        for source_cul in source_root.glob("*.CUL"):
            dst_cul = geno_dir / source_cul.name
            if dst_cul.exists() and dst_cul.stat().st_size > 0:
                continue
            shutil.copy2(source_cul, dst_cul)
    return case_dir


def case_dir_supports_scenario(case_dir: Path) -> bool:
    with open(PROJECT_CONFIG_PATH, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    filex_name = str((cfg.get("scenario", {}) or {}).get("filex", "")).strip()
    if not filex_name:
        return case_dir.exists()
    return (case_dir / filex_name).exists()


def configured_case_dir() -> Path | None:
    with open(PROJECT_CONFIG_PATH, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    cfg_dir = str((cfg.get("paths", {}) or {}).get("dssat_case_dir", "")).strip()
    if not cfg_dir:
        return None
    candidate = resolve_dssat_case_dir(PESTPP_ROOT, cfg=cfg)
    if candidate.exists():
        return ensure_case_support_files(candidate)
    return None


def resolve_config_case_path(raw_path: str, cfg: dict) -> Path:
    candidate = Path(str(raw_path).strip())
    if candidate.is_absolute():
        return candidate
    return resolve_case_dir() / candidate


def resolve_config_genotype_path(raw_path: str, cfg: dict) -> Path:
    candidate = Path(str(raw_path).strip())
    if candidate.is_absolute():
        return candidate
    return resolve_dssat_genotype_dir(PESTPP_ROOT, cfg=cfg) / candidate.name


def resolve_case_dir() -> Path:
    env_case = os.environ.get("DSSAT_CASE_DIR", "").strip()
    if env_case:
        env_candidate = ensure_case_support_files(Path(env_case).resolve())
        if case_dir_supports_scenario(env_candidate):
            return env_candidate
    cfg_case = configured_case_dir()
    if cfg_case is not None and case_dir_supports_scenario(cfg_case):
        return cfg_case
    sandbox_case = ensure_case_support_files((SANDBOX_DIR / "dssat_case").resolve())
    if (sandbox_case / "DSSAT48.INP").exists() and (sandbox_case / "DSSAT48.INH").exists() and case_dir_supports_scenario(sandbox_case):
        return sandbox_case
    return ensure_case_support_files(CASE_TEMPLATE_DIR.resolve())


def resolve_cultivar_path() -> Path | None:
    cfg_cul_path = str((PROJECT_CONFIG.get("paths", {}) or {}).get("cul_path", "")).strip()
    if cfg_cul_path:
        candidate = resolve_config_genotype_path(cfg_cul_path, PROJECT_CONFIG)
        if candidate.exists():
            return candidate.resolve()
    geno_dir = CASE_DIR / "GENOTYPE"
    if not geno_dir.exists():
        return None
    culs = sorted(geno_dir.glob("*.CUL"))
    if not culs:
        return None
    return culs[0].resolve()


CASE_DIR = resolve_case_dir()


PROGRESS_ENABLED = os.environ.get("AR_PROGRESS_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
PROGRESS_EVERY = max(1, int(os.environ.get("AR_PROGRESS_EVERY", "1")))
EVAL_RUN_COUNTER = 0
CURRENT_STAGE_CONTEXT = {"index": 0, "total": 0, "name": "", "metrics": tuple(), "active": tuple()}
OPTIMIZATION_STARTED_AT = time.time()
RUN_MODEL_STATS_PATH = RUNTIME_DIR / "run_model_stats.jsonl"


def _progress_elapsed_seconds() -> float:
    return max(0.0, time.time() - OPTIMIZATION_STARTED_AT)


def progress_log(event: str, **fields: object) -> None:
    if not PROGRESS_ENABLED:
        return
    pieces = [f"[Progress][{event}]"]
    pieces.append(f"elapsed_sec={_progress_elapsed_seconds():.1f}")
    for key, value in fields.items():
        normalized_value = value
        if isinstance(normalized_value, (list, tuple)):
            normalized_value = ",".join(str(item) for item in normalized_value)
        pieces.append(f"{key}={normalized_value}")
    print(" ".join(pieces))


def summarize_run_model_stats(stats_path: Path) -> dict[str, float]:
    summary = {
        "run_model_invocations": 0.0,
        "dssat_treatment_calls": 0.0,
        "dssat_wall_sec": 0.0,
    }
    if not stats_path.exists():
        return summary
    for line in stats_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        summary["run_model_invocations"] += 1.0
        summary["dssat_treatment_calls"] += float(payload.get("dssat_calls", payload.get("treatment_calls", 0.0)) or 0.0)
        summary["dssat_wall_sec"] += float(payload.get("duration_sec", 0.0) or 0.0)
    return summary


def set_stage_context(stage: dict, stage_index: int, stage_total: int) -> None:
    CURRENT_STAGE_CONTEXT["index"] = int(stage_index)
    CURRENT_STAGE_CONTEXT["total"] = int(stage_total)
    CURRENT_STAGE_CONTEXT["name"] = str(stage.get("name", "")).strip()
    CURRENT_STAGE_CONTEXT["metrics"] = tuple(str(metric).strip() for metric in stage.get("metrics", []))
    CURRENT_STAGE_CONTEXT["active"] = tuple(active_stage_param_names(stage))


def log_stage_start(stage: dict, stage_index: int, stage_total: int, optimizer_mode: str) -> None:
    set_stage_context(stage, stage_index, stage_total)
    progress_log(
        "stage_start",
        stage=f"{stage_index}/{stage_total}",
        name=CURRENT_STAGE_CONTEXT["name"],
        optimizer=optimizer_mode,
        mode=stage.get("mode", ""),
        active_params=CURRENT_STAGE_CONTEXT["active"],
        metrics=CURRENT_STAGE_CONTEXT["metrics"],
    )


def log_stage_end(stage: dict, stage_index: int, stage_total: int, success: bool, stage_loss: float) -> None:
    progress_log(
        "stage_end",
        stage=f"{stage_index}/{stage_total}",
        name=str(stage.get("name", "")).strip(),
        success=bool(success),
        stage_loss=f"{float(stage_loss):.6f}",
    )

LEGACY_EVAL_MODE = os.getenv("AR_EVAL_MODE", "").strip().lower()
WEIGHT_MODE_ENV = os.getenv("AR_WEIGHTING", os.getenv("AR_WEIGHT", os.getenv("AR_OBJECTIVE_MODE", ""))).strip().lower()
ENGINE_MODE_ENV = os.getenv("AR_ENGINE", os.getenv("AR_SOLVER", os.getenv("AR_OPTIMIZER", ""))).strip().lower()
BUDGET_MODE = os.getenv("AR_BUDGET", "standard")
SEQUENCE_MODE_ENV = os.getenv("AR_SEQUENCE", "joint").strip().lower()
GROUPING_MODE_ENV = os.getenv("AR_GROUPING", "").strip().lower()
BASELINE_PARAM_SOURCE = os.getenv("AR_BASELINE_PARAM_SOURCE", "external").strip().lower()
RANDOM_SEED = int(os.getenv("AR_RANDOM_SEED", "42"))

BUDGET_PROFILES = {
    "quick": {
        "anneal_maxiter": 1,
        "local_maxiter": 4,
        "local_maxfev": 6,
        "ls_max_nfev": 20,
        "ls_diff_step": 0.15,
        "glm_noptmax": 1,
        "ies_noptmax": 1,
        "ies_num_reals": 12,
        "ies_subset_size": 4,
    },
    "standard": {
        "anneal_maxiter": 8,
        "local_maxiter": 20,
        "local_maxfev": 30,
        "ls_max_nfev": 120,
        "ls_diff_step": 0.1,
        "glm_noptmax": 3,
        "ies_noptmax": 3,
        "ies_num_reals": 40,
        "ies_subset_size": 12,
    },
    "matrix": {
        "anneal_maxiter": 12,
        "local_maxiter": 30,
        "local_maxfev": 40,
        "ls_max_nfev": 180,
        "ls_diff_step": 0.08,
        "glm_noptmax": 4,
        "ies_noptmax": 4,
        "ies_num_reals": 50,
        "ies_subset_size": 16,
    },
    "deep": {
        "anneal_maxiter": 20,
        "local_maxiter": 50,
        "local_maxfev": 60,
        "ls_max_nfev": 300,
        "ls_diff_step": 0.05,
        "glm_noptmax": 5,
        "ies_noptmax": 5,
        "ies_num_reals": 80,
        "ies_subset_size": 20,
    },
}

METRIC_SEQUENCE = ["hwam", "hwum", "laix", "cwam", "adap", "mdap"]
DATE_METRICS = {"adap", "mdap"}
PRIMARY_METRICS = ["hwam", "laix"]
AGMIP_METRICS = ["adap", "mdap", "laix", "cwam", "hwam", "hwum"]
AGMIP_EXTRA_SUMMARY_VARS = ["CWAM", "ADAP", "MDAP", "HWUM"]
METRIC_TO_IMPORTANCE_KEY = {
    "hwam": "yield",
    "hwum": "yield",
    "laix": "lai",
    "cwam": "cwam",
    "adap": "adap",
    "mdap": "mdap",
}

WEIGHT_MODE_ALIASES = {
    "": "w8_dssat_group_max",
    "configured": "w8_dssat_group_max",
    "weighted": "w_custom_strategy",
    "custom_strategy": "w_custom_strategy",
    "pure_mgda": "w5_mean_normalized",
    "raw": "w0_raw_identity",
    "w0": "w0_raw_identity",
    "raw_identity": "w0_raw_identity",
    "w0_raw_identity": "w0_raw_identity",
    "inverse_rmse": "w_custom_strategy",
    "w2": "w_custom_strategy",
    "w2_inverse_rmse": "w_custom_strategy",
    "cv_based": "w_custom_strategy",
    "w3": "w_custom_strategy",
    "w3_cv_based": "w_custom_strategy",
    "min_max_equal": "w_custom_strategy",
    "w4": "w_custom_strategy",
    "w4_min_max_equal": "w_custom_strategy",
    "mean_normalized": "w5_mean_normalized",
    "mean_normalization": "w5_mean_normalized",
    "nrmse": "w5_mean_normalized",
    "w5": "w5_mean_normalized",
    "w5_mean_normalized": "w5_mean_normalized",
    "log_transformation": "w_custom_strategy",
    "w6": "w_custom_strategy",
    "w6_log_transformation": "w_custom_strategy",
    "inverse_variance": "w1_inverse_variance",
    "w1": "w1_inverse_variance",
    "w1_inverse_variance": "w1_inverse_variance",
    "equal_contribution": "w7_equal_contribution",
    "pwtadj1": "w7_equal_contribution",
    "w7": "w7_equal_contribution",
    "w7_equal_contribution": "w7_equal_contribution",
    "group_max": "w8_dssat_group_max",
    "dssat_group_max": "w8_dssat_group_max",
    "w8": "w8_dssat_group_max",
    "w8_dssat_group_max": "w8_dssat_group_max",
    "pareto": "w9_pareto_no_preweight",
    "w9": "w9_pareto_no_preweight",
    "w9_pareto_no_preweight": "w9_pareto_no_preweight",
    "pest_glm_native": "w5_mean_normalized",
    "pest_glm_grouped": "w8_dssat_group_max",
}
ENGINE_MODE_ALIASES = {
    "": "o1_least_squares",
    "least_squares": "o1_least_squares",
    "scipy_ls": "o1_least_squares",
    "trf": "o1_least_squares",
    "o1": "o1_least_squares",
    "o1_least_squares": "o1_least_squares",
    "pest_glm_native": "o6_pestpp_glm",
    "pest_glm_grouped": "o6_pestpp_glm",
    "anneal_nm": "o3_anneal_nm",
    "dual_annealing": "o3_anneal_nm",
    "o3_anneal_nm": "o3_anneal_nm",
    "powell": "o3_powell",
    "o3_powell": "o3_powell",
    "o2": "o2_pestpp_ies",
    "o2_pestpp_ies": "o2_pestpp_ies",
    "pestpp_ies": "o2_pestpp_ies",
    "ies": "o2_pestpp_ies",
    "o4": "o4_nsga2",
    "o4_nsga2": "o4_nsga2",
    "nsga2": "o4_nsga2",
    "nsga-ii": "o4_nsga2",
    "o5": "o5_mgda",
    "o5_mgda": "o5_mgda",
    "mgda": "o5_mgda",
    "default_dssat": "default_dssat",
}
SEQUENCE_MODE_ALIASES = {
    "joint": "s1_naive_joint",
    "s1": "s1_naive_joint",
    "s1_naive_joint": "s1_naive_joint",
    "sequential_phase": "s2_sequential_phase",
    "s2": "s2_sequential_phase",
    "s2_sequential_phase": "s2_sequential_phase",
    "wls_joint": "s3_wls_joint",
    "s3": "s3_wls_joint",
    "s3_wls_joint": "s3_wls_joint",
    "agmip_two_step": "s3_wls_joint",
}
GROUPING_MODE_ALIASES = {
    "g1": "g1_flat_all_in_one",
    "flat": "g1_flat_all_in_one",
    "g1_flat_all_in_one": "g1_flat_all_in_one",
    "g2": "g3_dssat_extended",
    "three_block": "g3_dssat_extended",
    "g2_three_block": "g3_dssat_extended",
    "g3": "g3_dssat_extended",
    "extended": "g3_dssat_extended",
    "g3_dssat_extended": "g3_dssat_extended",
}
GROUPING_DEFINITIONS = {
    "g1_flat_all_in_one": {"all": ["adap", "mdap", "laix", "cwam", "hwam", "hwum"]},
    "g3_dssat_extended": {
        "phenology_time": ["adap", "mdap"],
        "biomass_total": ["cwam"],
        "canopy_state": ["laix"],
        "yield_total": ["hwam"],
        "yield_unit_weight": ["hwum"],
    },
}


def normalize_weight_mode(value):
    raw = str(value or "").strip().lower()
    return WEIGHT_MODE_ALIASES.get(raw, raw or WEIGHT_MODE_ALIASES[""])


def normalize_engine_mode(value):
    raw = str(value or "").strip().lower()
    return ENGINE_MODE_ALIASES.get(raw, raw or ENGINE_MODE_ALIASES[""])


def normalize_sequence_mode(value):
    raw = str(value or "").strip().lower()
    return SEQUENCE_MODE_ALIASES.get(raw, raw or "s1_naive_joint")


def default_grouping_for_sequence(sequence_mode):
    if sequence_mode == "s1_naive_joint":
        return "g1_flat_all_in_one"
    return "g3_dssat_extended"


def normalize_grouping_mode(value, sequence_mode):
    raw = str(value or "").strip().lower()
    if not raw:
        return default_grouping_for_sequence(sequence_mode)
    return GROUPING_MODE_ALIASES.get(raw, raw)


def legacy_grouping_hint(value, sequence_mode):
    raw = str(value or "").strip().lower()
    if raw == "pest_glm_native":
        return "g1_flat_all_in_one"
    if raw == "pest_glm_grouped":
        return default_grouping_for_sequence(sequence_mode)
    return ""


CALIBRATION_SEQUENCE = normalize_sequence_mode(SEQUENCE_MODE_ENV)
WEIGHT_MODE = normalize_weight_mode(WEIGHT_MODE_ENV or LEGACY_EVAL_MODE)
ENGINE_MODE = normalize_engine_mode(ENGINE_MODE_ENV or LEGACY_EVAL_MODE)
GROUPING_MODE = normalize_grouping_mode(
    GROUPING_MODE_ENV or legacy_grouping_hint(LEGACY_EVAL_MODE, CALIBRATION_SEQUENCE),
    CALIBRATION_SEQUENCE,
)


def load_project_config():
    with open(PROJECT_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_group_indices(raw_members, parameter_names):
    if not isinstance(raw_members, list):
        return []
    name_to_index = {name: idx for idx, name in enumerate(parameter_names)}
    indices = []
    for member in raw_members:
        if isinstance(member, int) and 0 <= member < len(parameter_names):
            indices.append(member)
            continue
        member_name = str(member).strip().lower()
        if member_name in name_to_index:
            indices.append(name_to_index[member_name])
    return list(dict.fromkeys(indices))


def resolve_param_groups(cfg, parameter_names):
    all_indices = list(range(len(parameter_names)))
    params_cfg = cfg.get("params", {}) or {}
    stage_groups_cfg = params_cfg.get("stage_groups", {}) or {}
    groups = {"all": all_indices}
    if isinstance(stage_groups_cfg, dict) and stage_groups_cfg:
        for group_name in ("lai_stage", "yield_stage", "phenology_stage", "biomass_stage", "yield_partition_stage"):
            groups[group_name] = _resolve_group_indices(stage_groups_cfg.get(group_name, []), parameter_names) or all_indices
        return groups
    name_to_index = {name: idx for idx, name in enumerate(parameter_names)}
    if all(name in name_to_index for name in LEGACY_WHEAT_PARAM_NAMES):
        groups["lai_stage"] = [name_to_index[name] for name in ("p1v", "p1d", "p5", "g1", "phint")]
        groups["yield_stage"] = [name_to_index[name] for name in ("g1", "g2", "g3")]
        groups["phenology_stage"] = [name_to_index[name] for name in ("p1v", "p1d", "p5", "phint")]
        groups["biomass_stage"] = [name_to_index["g1"]]
        groups["yield_partition_stage"] = [name_to_index[name] for name in ("g2", "g3")]
        return groups
    for group_name in ("lai_stage", "yield_stage", "phenology_stage", "biomass_stage", "yield_partition_stage"):
        groups[group_name] = all_indices
    return groups


PROJECT_CONFIG = load_project_config()
PARAM_NAMES = resolve_parameter_names(PROJECT_CONFIG, tuple(LEGACY_WHEAT_PARAM_NAMES))
INITIAL_GUESS = resolve_initial_parameter_values(PROJECT_CONFIG, PARAM_NAMES)
BOUNDS = resolve_parameter_bounds_pairs(PROJECT_CONFIG, PARAM_NAMES)
PARAM_GROUPS = resolve_param_groups(PROJECT_CONFIG, PARAM_NAMES)
SCENARIO_TRTS = [int(t) for t in PROJECT_CONFIG.get("scenario", {}).get("trts", [1, 2, 8, 9, 13, 14])]


def load_planting_doy(cfg):
    filex_name = str(cfg.get("scenario", {}).get("filex", "")).strip()
    case_dir = str(cfg.get("paths", {}).get("dssat_case_dir", "")).strip()
    if not filex_name or not case_dir:
        raise RuntimeError("Missing FileX path needed to derive planting date")
    filex_path = resolve_config_case_path(filex_name, cfg)
    if not filex_path.exists():
        raise FileNotFoundError(f"FileX not found: {filex_path}")

    lines = filex_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = None
    for line in lines:
        if line.startswith("@P "):
            header = line
            continue
        if header and line.strip() and not line.startswith("*") and not line.startswith("@") and not line.lstrip().startswith("!"):
            cols = [c.lstrip("@").strip().upper() for c in header.split()]
            parts = line.split()
            if "PDATE" not in cols:
                break
            idx = cols.index("PDATE")
            if len(parts) <= idx:
                break
            pdate = int(parts[idx])
            return int(pdate % 1000)
    raise RuntimeError(f"Could not derive planting date from {filex_path}")


def observation_metric_candidates(cfg):
    metrics_cfg = cfg.get("metrics", {}) or cfg.get("variables", {}) or {}
    yield_code = str(metrics_cfg.get("yield_var", "HWAM")).strip().upper() or "HWAM"
    laix_code = str(metrics_cfg.get("laix_var", "")).strip().upper()
    return {
        "hwam": [yield_code, "HWAM", "PWAM", "PWAD"],
        "hwum": ["HWUM"],
        "cwam": ["CWAM", "CWAD"],
        "laix": [laix_code, "LAIX", "LAID"],
        "adap": ["ADAP", "ADAT"],
        "mdap": ["MDAP", "MDAT"],
    }


def load_t_file_metric_fallbacks(cfg, trts):
    t_path_raw = (
        str(cfg.get("paths", {}).get("obs_t_path", "")).strip()
        or str(cfg.get("paths", {}).get("wht_path", "")).strip()
    )
    if not t_path_raw:
        return (
            {metric_name: {} for metric_name in METRIC_SEQUENCE},
            {metric_name: {} for metric_name in METRIC_SEQUENCE},
        )
    t_path = resolve_config_case_path(t_path_raw, cfg)
    if not t_path.exists():
        return (
            {metric_name: {} for metric_name in METRIC_SEQUENCE},
            {metric_name: {} for metric_name in METRIC_SEQUENCE},
        )

    lines = t_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = next((line for line in lines if line.startswith("@TRNO")), None)
    if not header:
        return (
            {metric_name: {} for metric_name in METRIC_SEQUENCE},
            {metric_name: {} for metric_name in METRIC_SEQUENCE},
        )

    cols = [c.lstrip("@").strip().upper() for c in header.split()]
    if "TRNO" not in cols:
        return (
            {metric_name: {} for metric_name in METRIC_SEQUENCE},
            {metric_name: {} for metric_name in METRIC_SEQUENCE},
        )
    idx_trno = cols.index("TRNO")
    idx_date = cols.index("DATE") if "DATE" in cols else -1
    candidate_codes = observation_metric_candidates(cfg)
    idx_by_metric = {}
    used_cols = set()
    for metric_name in ("hwam", "hwum", "cwam", "laix", "adap", "mdap"):
        for code in candidate_codes.get(metric_name, []):
            code_u = str(code).strip().upper()
            if not code_u or code_u in used_cols or code_u not in cols:
                continue
            idx_by_metric[metric_name] = cols.index(code_u)
            used_cols.add(code_u)
            break

    trt_set = {int(trt) for trt in trts}
    by_metric = {metric_name: {} for metric_name in METRIC_SEQUENCE}
    dates_by_metric = {metric_name: {} for metric_name in METRIC_SEQUENCE}
    planting_doy = load_planting_doy(cfg)
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
        for metric_name, idx_col in idx_by_metric.items():
            if len(parts) <= idx_col:
                continue
            try:
                raw_value = float(parts[idx_col])
            except ValueError:
                continue
            if raw_value == -99.0:
                continue
            value = raw_value - float(planting_doy) if metric_name in {"adap", "mdap"} and raw_value > 0.0 else raw_value
            entry_date = int(date) if date is not None else -1
            current = by_metric[metric_name].get(trt)
            if current is None or entry_date >= current[0]:
                by_metric[metric_name][trt] = (entry_date, float(value))
            if date is not None:
                dates_by_metric[metric_name].setdefault(trt, []).append(int(date))

    metric_values = {
        metric_name: {int(trt): float(value) for trt, (_, value) in values.items()}
        for metric_name, values in by_metric.items()
    }
    metric_dates = {
        metric_name: {
            int(trt): sorted(set(int(date) for date in dates))
            for trt, dates in per_trt.items()
        }
        for metric_name, per_trt in dates_by_metric.items()
    }
    return metric_values, metric_dates


def load_a_file_observations(cfg, trts):
    a_path_raw = (
        str(cfg.get("paths", {}).get("obs_a_path", "")).strip()
        or str(cfg.get("paths", {}).get("wha_path", "")).strip()
    )
    a_path = resolve_config_case_path(a_path_raw, cfg)
    if not a_path.exists():
        raise FileNotFoundError(f"Observation A-file not found: {a_path}")

    lines = a_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = None
    for line in lines:
        if line.startswith("@TRNO"):
            header = line
            break
    if not header:
        raise RuntimeError(f"Missing @TRNO header in {a_path}")

    cols = [c.lstrip("@").strip().upper() for c in header.split()]

    candidate_codes = observation_metric_candidates(cfg)
    yield_code = str(candidate_codes["hwam"][0]).strip().upper()

    planting_doy = load_planting_doy(cfg)
    trt_to_index = {int(trt): idx for idx, trt in enumerate(trts)}
    metrics = {name: np.full(len(trts), -99.0, dtype=float) for name in METRIC_SEQUENCE}

    idx_trno = cols.index("TRNO")
    idx_by_metric = {}
    used_cols = set()
    for metric_name in ("hwam", "hwum", "cwam", "laix", "adap", "mdap"):
        for code in candidate_codes.get(metric_name, []):
            code_u = str(code).strip().upper()
            if not code_u or code_u in used_cols or code_u not in cols:
                continue
            idx_by_metric[metric_name] = cols.index(code_u)
            used_cols.add(code_u)
            break

    if "hwam" not in idx_by_metric:
        raise RuntimeError(f"Observation A-file missing configured yield column {yield_code}: {a_path}")

    for line in lines:
        if not line.strip() or line.startswith("@") or line.startswith("*") or line.lstrip().startswith("!"):
            continue
        parts = line.split()
        if len(parts) <= max([idx_trno] + list(idx_by_metric.values())):
            continue
        try:
            trt = int(parts[idx_trno])
        except ValueError:
            continue
        if trt not in trt_to_index:
            continue
        pos = trt_to_index[trt]
        for metric_name, idx_col in idx_by_metric.items():
            try:
                raw_value = float(parts[idx_col])
                if metric_name in {"adap", "mdap"} and raw_value > 0.0:
                    metrics[metric_name][pos] = raw_value - float(planting_doy)
                else:
                    metrics[metric_name][pos] = raw_value
            except ValueError:
                metrics[metric_name][pos] = -99.0

    t_metric_values, _ = load_t_file_metric_fallbacks(cfg, trts)
    for metric_name, values_by_trt in t_metric_values.items():
        for trt, value in values_by_trt.items():
            pos = trt_to_index.get(int(trt))
            if pos is None:
                continue
            if metrics[metric_name][pos] == -99.0:
                metrics[metric_name][pos] = float(value)

    return metrics


def resolve_split(cfg, trts):
    split_cfg = cfg.get("split", {})
    mode = str(split_cfg.get("mode", "trt")).strip().lower()
    all_trts = [int(t) for t in trts]
    if str(os.environ.get("AR_FORCE_TRAIN_ONLY", "0")).strip().lower() in {"1", "true", "yes", "y", "on"}:
        return {int(trt): "train" for trt in all_trts}
    train = {int(t) for t in (split_cfg.get("train_trts") or []) if str(t).strip()}
    valid = {int(t) for t in (split_cfg.get("valid_trts") or []) if str(t).strip()}

    ratio = None
    if "valid_ratio" in split_cfg:
        try:
            ratio = float(split_cfg.get("valid_ratio"))
        except (TypeError, ValueError):
            ratio = None
    if ratio is None and not train and not valid and len(all_trts) > 1:
        ratio = 0.2

    if mode in {"ratio", "random"} and ratio is None:
        ratio = 0.2

    if ratio is not None and not train and not valid and all_trts:
        ratio = max(0.0, min(1.0, float(ratio)))
        if ratio > 0.0:
            seed = split_cfg.get("seed", split_cfg.get("random_seed", 0))
            rnd = random.Random(int(seed))
            shuffled = list(all_trts)
            rnd.shuffle(shuffled)
            n_valid = max(1, int(round(len(shuffled) * ratio)))
            valid = set(shuffled[:n_valid])
            train = set(shuffled[n_valid:])

    if not train and not valid:
        train = set(all_trts)
    else:
        if not train:
            train = set(all_trts) - set(valid)
        if not valid:
            valid = set(all_trts) - set(train)

    overlap = set(train) & set(valid)
    if overlap:
        train = set(train) - overlap

    return {int(trt): ("valid" if int(trt) in valid else "train") for trt in all_trts}


OBS_METRICS = load_a_file_observations(PROJECT_CONFIG, SCENARIO_TRTS)
OBS_T_FILE_METRICS, OBS_T_FILE_DATES = load_t_file_metric_fallbacks(PROJECT_CONFIG, SCENARIO_TRTS)
SPLIT_BY_TRT = resolve_split(PROJECT_CONFIG, SCENARIO_TRTS)
TRAIN_TRTS = [trt for trt in SCENARIO_TRTS if SPLIT_BY_TRT.get(int(trt), "train") == "train"]
VALID_TRTS = [trt for trt in SCENARIO_TRTS if SPLIT_BY_TRT.get(int(trt), "train") == "valid"]
TRAIN_MASK = np.array([int(trt) in set(TRAIN_TRTS) for trt in SCENARIO_TRTS], dtype=bool)
VALID_MASK = np.array([int(trt) in set(VALID_TRTS) for trt in SCENARIO_TRTS], dtype=bool)
ALL_MASK = np.ones(len(SCENARIO_TRTS), dtype=bool)


def get_budget_profile():
    return BUDGET_PROFILES.get(BUDGET_MODE, BUDGET_PROFILES["standard"])


def resolve_optimizer_mode():
    return ENGINE_MODE


def validate_experiment_configuration():
    optimizer_mode = resolve_optimizer_mode()
    known_weight_modes = {
        "w0_raw_identity",
        "w1_inverse_variance",
        "w4_min_max_equal",
        "w5_mean_normalized",
        "w6_log_transformation",
        "w7_equal_contribution",
        "w8_dssat_group_max",
        "w9_pareto_no_preweight",
        "w_custom_strategy",
    }
    known_engines = {
        "o1_least_squares",
        "o2_pestpp_ies",
        "o3_anneal_nm",
        "o3_powell",
        "o4_nsga2",
        "o5_mgda",
        "o6_pestpp_glm",
        "default_dssat",
    }
    known_sequences = {"s1_naive_joint", "s2_sequential_phase", "s3_wls_joint"}
    known_groupings = {"g1_flat_all_in_one", "g3_dssat_extended"}
    if WEIGHT_MODE not in known_weight_modes:
        return f"Unknown weight mode: {WEIGHT_MODE}"
    if optimizer_mode not in known_engines:
        return f"Unknown engine mode: {optimizer_mode}"
    if CALIBRATION_SEQUENCE not in known_sequences:
        return f"Unknown calibration sequence: {CALIBRATION_SEQUENCE}"
    if GROUPING_MODE not in known_groupings:
        return f"Unknown grouping mode: {GROUPING_MODE}"
    if CALIBRATION_SEQUENCE == "s3_wls_joint" and GROUPING_MODE != "g3_dssat_extended":
        return "S3/WLS joint requires g3_dssat_extended grouping"
    if WEIGHT_MODE == "w7_equal_contribution" and GROUPING_MODE != "g3_dssat_extended":
        return f"{WEIGHT_MODE} requires g3_dssat_extended grouping"
    if WEIGHT_MODE == "w8_dssat_group_max" and CALIBRATION_SEQUENCE == "s3_wls_joint" and GROUPING_MODE != "g3_dssat_extended":
        return f"{WEIGHT_MODE} requires g3_dssat_extended grouping for S3/WLS refinement"
    if WEIGHT_MODE == "w9_pareto_no_preweight" and optimizer_mode not in {"o4_nsga2", "o5_mgda"}:
        return "W9 Pareto / No Pre-Weight only supports O4 NSGA-II or O5 MGDA"
    if optimizer_mode == "o4_nsga2":
        return f"{optimizer_mode} is documented in the design but not yet implemented in this sandbox runtime"
    return ""


def print_configuration_failure(reason):
    print(f"Configuration_Error: {reason}")
    print("Optimization Success: False")
    print("Final Evaluation Failed.")
    train_score = 999.0
    valid_score = 999.0
    all_score = 999.0
    final_score = 999.0
    print("Final Parameters:")
    for name, val in zip(PARAM_NAMES, INITIAL_GUESS):
        print(f"  {name.upper()}: {val:.2f}")
    print("Final_Loss_Value: 999.000000")
    print(f"Final_Train_Score: {train_score:.6f}")
    print(f"Final_Valid_Score: {valid_score:.6f}")
    print(f"Final_All_Score: {all_score:.6f}")
    print(f"Final_Score: {final_score:.6f}")


def clip_params(params_array):
    clipped = np.array(params_array, dtype=float)
    for index, (lower, upper) in enumerate(BOUNDS):
        clipped[index] = np.clip(clipped[index], lower, upper)
    return clipped


def neutral_arrays():
    return np.ones(1, dtype=float), np.ones(1, dtype=float)


def split_mask(split_name):
    if split_name == "train":
        return TRAIN_MASK
    if split_name == "valid":
        return VALID_MASK
    return ALL_MASK


def grouping_definition(grouping_mode=None):
    mode = grouping_mode or GROUPING_MODE
    return GROUPING_DEFINITIONS.get(mode, GROUPING_DEFINITIONS["g3_dssat_extended"])


def ordered_unique_metrics(metrics):
    seen = set()
    ordered = []
    for metric_name in metrics:
        if metric_name in seen or metric_name not in OBS_METRICS:
            continue
        seen.add(metric_name)
        ordered.append(metric_name)
    return ordered


def comparable_metric_catalog():
    return ordered_unique_metrics(AGMIP_METRICS)


def selected_grouping_metrics(grouping_mode=None):
    metrics = []
    for group_metrics in grouping_definition(grouping_mode).values():
        metrics.extend(group_metrics)
    return ordered_unique_metrics(metrics)


def metric_group_name(metric_name, grouping_mode=None):
    for group_name, metrics in grouping_definition(grouping_mode).items():
        if metric_name in metrics:
            return group_name
    return metric_name


def group_metrics_for_selection(metrics, grouping_mode=None):
    selected = {}
    selected_names = set()
    metric_set = set(metrics)
    for group_name, group_metrics in grouping_definition(grouping_mode).items():
        subset = [metric_name for metric_name in group_metrics if metric_name in metric_set]
        if subset:
            selected[group_name] = subset
            selected_names.update(subset)
    for metric_name in metrics:
        if metric_name not in selected_names:
            selected[metric_name] = [metric_name]
    return selected


def grouped_metric_scale(metric_name, grouping_mode=None):
    group_name = metric_group_name(metric_name, grouping_mode)
    group_metrics = grouping_definition(grouping_mode).get(group_name, [metric_name])
    return float(1.0 / np.sqrt(max(len(group_metrics), 1)))


def normalize_metric_value(metric_name, value):
    val = float(value)
    if metric_name in DATE_METRICS and np.isfinite(val) and abs(val) >= 1000.0:
        return float(int(round(val)) % 1000)
    return val


def observed_metric_values(metric_name, split_name="all"):
    obs = OBS_METRICS[metric_name]
    mask = split_mask(split_name) & (obs != -99.0)
    return obs[mask]


def observed_group_max(group_metrics, split_name="all"):
    group_max = 0.0
    found = False
    for metric_name in group_metrics:
        obs_values = observed_metric_values(metric_name, split_name)
        if len(obs_values) == 0:
            continue
        local_max = float(np.max(np.abs(obs_values)))
        if np.isfinite(local_max):
            group_max = max(group_max, local_max)
            found = True
    if not found:
        return np.nan
    return group_max


def valid_metric_arrays(metric_name, sim_metrics, split_name="all"):
    obs = OBS_METRICS[metric_name]
    sim = sim_metrics[metric_name]
    mask = split_mask(split_name) & (obs != -99.0) & np.isfinite(sim)
    return obs[mask], sim[mask]


def normalize_residuals_for_weight_mode(weight_mode=None):
    return (weight_mode or WEIGHT_MODE) in {"w5_mean_normalized", "w_custom_strategy"}


def normalized_group_weights(group_weights):
    if not group_weights:
        return {}
    mean_weight = float(np.mean(list(group_weights.values())))
    scale = max(mean_weight, 1e-8)
    return {group_name: float(weight / scale) for group_name, weight in group_weights.items()}


def compute_metric_weights(valid_sim_y, valid_obs_y, valid_sim_l, valid_obs_l):
    if WEIGHT_MODE != "w_custom_strategy":
        return 1.0, 1.0
    neutral_sim, neutral_obs = neutral_arrays()
    try:
        yield_loss = float(strategy.calculate_loss(valid_sim_y, valid_obs_y, neutral_sim, neutral_obs))
        lai_loss = float(strategy.calculate_loss(neutral_sim, neutral_obs, valid_sim_l, valid_obs_l))
    except Exception:
        return 1.0, 1.0
    raw = np.clip(np.array([yield_loss, lai_loss], dtype=float), 1e-8, None)
    normalized = raw / np.mean(raw)
    bounded = np.clip(normalized, 0.25, 4.0)
    return float(bounded[0]), float(bounded[1])


def compute_group_base_weight(metrics, split_name="train", weight_mode=None, reference_sim_metrics=None, grouping_mode=None):
    mode = weight_mode or WEIGHT_MODE
    grouping = grouping_mode or GROUPING_MODE
    group_weights = {}
    for group_name, group_metrics in group_metrics_for_selection(metrics, grouping).items():
        if mode == "w0_raw_identity":
            base = 1.0
        elif mode == "w8_dssat_group_max":
            group_max = observed_group_max(group_metrics, split_name)
            if not np.isfinite(group_max):
                continue
            base = 1.0 / max(float(group_max), 1e-6)
        elif mode == "w1_inverse_variance":
            obs_values = [observed_metric_values(metric_name, split_name) for metric_name in group_metrics]
            obs_values = [vals for vals in obs_values if len(vals) > 0]
            if not obs_values:
                continue
            merged = np.concatenate(obs_values)
            base = 1.0 / max(float(np.var(merged)), 1e-6)
        elif mode == "w7_equal_contribution":
            if reference_sim_metrics is None:
                base = 1.0
            else:
                residuals = []
                for metric_name in group_metrics:
                    residual = metric_residual_array(metric_name, reference_sim_metrics, split_name=split_name, normalize=False)
                    if len(residual) > 0:
                        residuals.append(residual)
                if not residuals:
                    continue
                merged = np.concatenate(residuals)
                base = 1.0 / max(float(np.mean(merged**2)), 1e-6)
        else:
            base = 1.0
        group_weights[group_name] = float(base)
    return normalized_group_weights(group_weights)


def build_stage_metric_weights(metrics, split_name="train", weight_mode=None, grouping_mode=None, reference_sim_metrics=None, wls_weights=None):
    weights = {}
    grouping = grouping_mode or GROUPING_MODE
    group_weights = compute_group_base_weight(
        metrics,
        split_name=split_name,
        weight_mode=weight_mode,
        reference_sim_metrics=reference_sim_metrics,
        grouping_mode=grouping,
    )
    for group_name, group_metrics in group_metrics_for_selection(metrics, grouping).items():
        for metric_name in group_metrics:
            weights[metric_name] = group_weights.get(group_name, 1.0)
    if "hwam" in metrics and "laix" in metrics and (weight_mode or WEIGHT_MODE) == "w_custom_strategy" and reference_sim_metrics is not None:
        valid_obs_y, valid_sim_y = valid_metric_arrays("hwam", reference_sim_metrics, split_name)
        valid_obs_l, valid_sim_l = valid_metric_arrays("laix", reference_sim_metrics, split_name)
        if len(valid_obs_y) > 0 and len(valid_obs_l) > 0:
            weight_y, weight_l = compute_metric_weights(valid_sim_y, valid_obs_y, valid_sim_l, valid_obs_l)
            weights["hwam"] = weights.get("hwam", 1.0) * weight_y
            weights["laix"] = weights.get("laix", 1.0) * weight_l
    if wls_weights is not None:
        for metric_name in metrics:
            weights[metric_name] = weights.get(metric_name, 1.0) * max(float(wls_weights.get(metric_name, 1.0)), 1e-8)
    return weights


def metric_residual_array(metric_name, sim_metrics, split_name="train", normalize=True, metric_weights=None):
    obs = OBS_METRICS[metric_name]
    sim = sim_metrics[metric_name]
    mask = split_mask(split_name) & (obs != -99.0)
    valid_obs = obs[mask]
    valid_sim = sim[mask]
    if len(valid_obs) == 0:
        return np.empty(0, dtype=float)
    scale = np.mean(np.abs(valid_obs)) + 1e-8
    residual = valid_sim - valid_obs
    invalid = ~np.isfinite(valid_sim)
    if np.any(invalid):
        residual = residual.astype(float, copy=True)
        residual[invalid] = 10.0 * scale
    if normalize:
        residual = residual / scale
    if metric_weights is not None:
        residual = residual * np.sqrt(max(metric_weights.get(metric_name, 1.0), 1e-8))
    return residual


def single_metric_nrmse(valid_obs, valid_sim):
    if len(valid_obs) == 0:
        return np.nan
    return float(np.sqrt(np.mean((valid_obs - valid_sim) ** 2)) / (np.mean(np.abs(valid_obs)) + 1e-8))


def single_metric_bias(valid_obs, valid_sim):
    if len(valid_obs) == 0:
        return np.nan
    return float(np.mean(valid_sim - valid_obs) / (np.mean(np.abs(valid_obs)) + 1e-8))


def count_valid_points(metric_name, sim_metrics, split_name="all"):
    valid_obs, _ = valid_metric_arrays(metric_name, sim_metrics, split_name)
    return int(len(valid_obs))


def run_dssat_and_get_simulated(params_array):
    global EVAL_RUN_COUNTER
    EVAL_RUN_COUNTER += 1
    migrate_legacy_runtime_files()
    with open(PARAMS_PATH, "w") as f:
        for name, val in zip(PARAM_NAMES, params_array):
            f.write(f"{name} {val:.3f}\n")
    if EVAL_RUN_COUNTER == 1 or EVAL_RUN_COUNTER % PROGRESS_EVERY == 0:
        progress_log(
            "dssat_eval",
            count=EVAL_RUN_COUNTER,
            stage=f"{CURRENT_STAGE_CONTEXT['index']}/{CURRENT_STAGE_CONTEXT['total']}",
            stage_name=CURRENT_STAGE_CONTEXT["name"],
            metrics=CURRENT_STAGE_CONTEXT["metrics"],
        )

    env = build_run_model_env(
        params_path=PARAMS_PATH,
        trts=SCENARIO_TRTS,
        keep_outputs=False,
        base_env=os.environ,
        extra_env={"DSSAT_RUN_STATS_PATH": str(RUN_MODEL_STATS_PATH)},
        project_config_path=PROJECT_CONFIG_PATH,
        case_dir=CASE_DIR,
        cul_path=resolve_cultivar_path(),
        extra_summary_vars=AGMIP_EXTRA_SUMMARY_VARS,
    )

    try:
        sim_data = run_compare_model(
            work_dir=RUNTIME_DIR,
            params_path=PARAMS_PATH,
            trts=SCENARIO_TRTS,
            keep_outputs=False,
            python_executable=sys.executable,
            extra_env=env,
            failure_label="eval run_model.py",
            output_path=PEST_OUT_PATH,
        )
    except RuntimeError as exc:
        print("DSSAT Error:", exc)
        return None

    if not PEST_OUT_PATH.exists():
        print(f"Warning: {PEST_OUT_PATH} not found after run.")
        return None

    sim_metrics = {}
    for metric_name in METRIC_SEQUENCE:
        values = []
        candidate_codes = [str(code).strip().lower() for code in observation_metric_candidates(PROJECT_CONFIG).get(metric_name, []) if str(code).strip()]
        for trt in SCENARIO_TRTS:
            raw_value = np.nan
            for code in candidate_codes:
                key = f"{code}_t{int(trt):02d}"
                if key in sim_data:
                    raw_value = sim_data.get(key, np.nan)
                    break
            if not np.isfinite(raw_value):
                for code in candidate_codes:
                    for date in reversed(OBS_T_FILE_DATES.get(metric_name, {}).get(int(trt), [])):
                        key = f"{code}_t{int(trt):02d}_d{int(date)}"
                        if key in sim_data:
                            raw_value = sim_data.get(key, np.nan)
                            break
                    if np.isfinite(raw_value):
                        break
            values.append(normalize_metric_value(metric_name, raw_value))
        sim_metrics[metric_name] = np.array(values, dtype=float)

    return sim_metrics


def write_params_file(params_array):
    migrate_legacy_runtime_files()
    clipped = clip_params(params_array)
    with open(PARAMS_PATH, "w", encoding="utf-8") as f:
        for name, val in zip(PARAM_NAMES, clipped):
            f.write(f"{name} {float(val):.6f}\n")


def active_stage_param_names(stage):
    return [PARAM_NAMES[index] for index in stage["active"]]


def run_pestpp_executable(exe_name, env, pst_filename="ksas_mvp.pst", failure_label=None):
    ensure_runtime_dir()
    return run_pestpp_cli(
        exe_name=exe_name,
        pestpp_root=PESTPP_ROOT,
        work_dir=RUNTIME_DIR,
        env=env,
        pst_filename=pst_filename,
        failure_label=failure_label,
    )


def cleanup_pestpp_outputs():
    ensure_runtime_dir()
    runner_cleanup_pestpp_outputs(RUNTIME_DIR, stem="ksas_mvp")


def parse_best_ies_result(start_params):
    ensure_runtime_dir()
    return runner_parse_best_ies_result(
        RUNTIME_DIR,
        np.array(start_params, dtype=float),
        PARAM_NAMES,
        clip_params,
        stem="ksas_mvp",
    )


def parse_best_glm_result(start_params):
    ensure_runtime_dir()
    return runner_parse_best_glm_result(
        RUNTIME_DIR,
        np.array(start_params, dtype=float),
        PARAM_NAMES,
        clip_params,
        stem="ksas_mvp",
    )


def parse_named_params_file(path, start_params):
    params = np.array(start_params, dtype=float)
    resolved = Path(path)
    if not resolved.exists():
        raise RuntimeError(f"Missing parameter file: {resolved}")
    name_to_index = {str(name).strip().lower(): idx for idx, name in enumerate(PARAM_NAMES)}
    for raw in resolved.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = raw.split()
        if len(parts) < 2:
            continue
        idx = name_to_index.get(parts[0].strip().lower())
        if idx is None:
            continue
        try:
            params[idx] = float(parts[1])
        except ValueError:
            continue
    return clip_params(params)


def build_pest_stage_env(stage, budget_profile, optimizer_mode):
    migrate_legacy_runtime_files()
    pest_weight_mode = str(WEIGHT_MODE_ENV or WEIGHT_MODE).strip().lower()
    env = build_run_model_env(
        params_path=PARAMS_PATH,
        trts=SCENARIO_TRTS,
        keep_outputs=False,
        base_env=os.environ,
        extra_env={
            "PEST_ACTIVE_PARAMS": ",".join(active_stage_param_names(stage)),
            "PEST_ACTIVE_METRICS": ",".join(stage["metrics"]),
            "PEST_OBS_WEIGHT_MODE": pest_weight_mode,
            "DSSAT_RUN_STATS_PATH": str(RUN_MODEL_STATS_PATH),
            "PEST_NOPTMAX": str(
                int(
                    os.environ.get(
                        "PEST_NOPTMAX",
                        budget_profile["glm_noptmax"] if optimizer_mode == "glm" else budget_profile["ies_noptmax"],
                    )
                )
            ),
        },
        project_config_path=PROJECT_CONFIG_PATH,
        case_dir=CASE_DIR,
        cul_path=resolve_cultivar_path(),
        extra_summary_vars=AGMIP_EXTRA_SUMMARY_VARS,
    )
    if optimizer_mode == "ies":
        env["PESTPP_IES_NUM_REALS"] = str(int(os.environ.get("PESTPP_IES_NUM_REALS", budget_profile["ies_num_reals"])))
        env["PESTPP_IES_SUBSET_SIZE"] = str(int(os.environ.get("PESTPP_IES_SUBSET_SIZE", budget_profile["ies_subset_size"])))
    return env


def run_mgda_update(env):
    ensure_runtime_dir()
    mgda_params_path = RUNTIME_DIR / "params_mgda.dat"
    mgda_log_path = RUNTIME_DIR / "mgda_console.log"
    mgda_report_path = RUNTIME_DIR / "mgda_report.txt"
    for stale_path in (mgda_params_path, mgda_log_path, mgda_report_path):
        stale_path.unlink(missing_ok=True)
    process_env = os.environ.copy()
    process_env.update({str(k): str(v) for k, v in env.items()})
    process_env["OUT_PARAMS_PATH"] = str(mgda_params_path)
    pythonpath_parts = [str(SRC_DIR)]
    existing_pythonpath = str(process_env.get("PYTHONPATH", "")).strip()
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    process_env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    result = subprocess.run(
        [sys.executable, str(MGDA_UPDATE_PATH)],
        cwd=str(RUNTIME_DIR),
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    mgda_log_path.write_text(combined_output, encoding="utf-8")
    if result.returncode != 0:
        tail = (combined_output or "mgda_update failed without output")[-1000:]
        raise RuntimeError(f"mgda_update.py failed (exit {result.returncode}): {tail}")
    if not mgda_params_path.exists():
        raise RuntimeError("mgda_update.py did not produce params_mgda.dat")
    if not mgda_report_path.exists():
        raise RuntimeError("mgda_update.py did not produce mgda_report.txt")
    return mgda_params_path


def run_pestpp_ies_stage(start_params, stage, budget_profile):
    cleanup_pestpp_outputs()
    write_params_file(start_params)

    env = build_pest_stage_env(stage, budget_profile, optimizer_mode="ies")
    progress_log("pest_setup_start", optimizer="o2_pestpp_ies", stage=CURRENT_STAGE_CONTEXT["name"], runtime_dir=RUNTIME_DIR)

    run_build_pest_setup(working_dir=RUNTIME_DIR, env=env, python_executable=sys.executable)
    progress_log("pest_setup_done", optimizer="o2_pestpp_ies", stage=CURRENT_STAGE_CONTEXT["name"])

    progress_log("pest_solver_start", optimizer="o2_pestpp_ies", stage=CURRENT_STAGE_CONTEXT["name"])
    run_pestpp_executable("pestpp-ies.exe", env, pst_filename="ksas_mvp.pst", failure_label="pestpp-ies execution")
    progress_log("pest_solver_done", optimizer="o2_pestpp_ies", stage=CURRENT_STAGE_CONTEXT["name"])

    best_params, best_phi = parse_best_ies_result(start_params)
    return best_params, float(best_phi), True


def run_pestpp_glm_stage(start_params, stage, budget_profile, wls_weights=None):
    cleanup_pestpp_outputs()
    write_params_file(start_params)

    env = build_pest_stage_env(stage, budget_profile, optimizer_mode="glm")
    progress_log("pest_setup_start", optimizer="o6_pestpp_glm", stage=CURRENT_STAGE_CONTEXT["name"], runtime_dir=RUNTIME_DIR)

    run_build_pest_setup(working_dir=RUNTIME_DIR, env=env, python_executable=sys.executable)
    progress_log("pest_setup_done", optimizer="o6_pestpp_glm", stage=CURRENT_STAGE_CONTEXT["name"])

    progress_log("pest_solver_start", optimizer="o6_pestpp_glm", stage=CURRENT_STAGE_CONTEXT["name"])
    try:
        run_pestpp_executable("pestpp-glm.exe", env, pst_filename="ksas_mvp.pst", failure_label="pestpp-glm execution")
    except Exception as exc:
        message = str(exc)
        if "jacobian matrix has no non-zeros" in message or "all parameters at/near bounds" in message:
            progress_log(
                "pest_solver_fallback_to_stage_loss",
                optimizer="o6_pestpp_glm",
                stage=CURRENT_STAGE_CONTEXT["name"],
                reason="zero_jacobian_or_bound_lock",
            )
            metric_weights = stage_metric_weights(start_params, stage, wls_weights=wls_weights)
            fallback_loss = objective_function(
                start_params,
                metrics=stage["metrics"],
                split_name="train",
                metric_weights=metric_weights,
                normalize=normalize_residuals_for_weight_mode() and stage["mode"] != "wls",
            )
            return np.array(start_params, dtype=float), float(fallback_loss), False
        raise
    progress_log("pest_solver_done", optimizer="o6_pestpp_glm", stage=CURRENT_STAGE_CONTEXT["name"])

    best_params, best_phi = parse_best_glm_result(start_params)
    if np.isfinite(best_phi):
        return best_params, float(best_phi), True
    metric_weights = stage_metric_weights(best_params, stage, wls_weights=wls_weights)
    stage_loss = objective_function(
        best_params,
        metrics=stage["metrics"],
        split_name="train",
        metric_weights=metric_weights,
        normalize=normalize_residuals_for_weight_mode() and stage["mode"] != "wls",
    )
    return best_params, float(stage_loss), True


def metric_importance(metric_name):
    importance_cfg = PROJECT_CONFIG.get("params", {}).get("importance_exponent", {})
    key = METRIC_TO_IMPORTANCE_KEY.get(metric_name, metric_name)
    if key in importance_cfg:
        return float(importance_cfg[key])
    if metric_name == "cwam":
        return 5.0
    return 1.0


def stage_metrics_subset(candidates):
    selected = []
    grouping_metrics = set(selected_grouping_metrics(GROUPING_MODE))
    for metric_name in candidates:
        if metric_name not in OBS_METRICS:
            continue
        if grouping_metrics and metric_name not in grouping_metrics:
            continue
        if np.any(OBS_METRICS[metric_name] != -99.0):
            selected.append(metric_name)
    return ordered_unique_metrics(selected)


def sequence_stage_plan():
    if CALIBRATION_SEQUENCE == "s1_naive_joint":
        metrics = stage_metrics_subset(comparable_metric_catalog())
        return [{"name": "joint", "active": PARAM_GROUPS["all"], "metrics": metrics, "mode": "stage"}]

    stages = []
    phenology_metrics = stage_metrics_subset(["adap", "mdap"])
    biomass_metrics = stage_metrics_subset(["laix", "cwam"])
    yield_metrics = stage_metrics_subset(["hwam", "hwum"])
    final_metrics = stage_metrics_subset(comparable_metric_catalog())

    if phenology_metrics:
        stages.append({"name": "phenology", "active": PARAM_GROUPS["phenology_stage"], "metrics": phenology_metrics, "mode": "stage"})
    if biomass_metrics:
        stages.append({"name": "biomass", "active": PARAM_GROUPS["biomass_stage"], "metrics": biomass_metrics, "mode": "stage"})
    if yield_metrics:
        stages.append({"name": "yield", "active": PARAM_GROUPS["yield_partition_stage"], "metrics": yield_metrics, "mode": "stage"})
    if CALIBRATION_SEQUENCE == "s3_wls_joint" and final_metrics:
        stages.append({"name": "joint_wls", "active": PARAM_GROUPS["all"], "metrics": final_metrics, "mode": "wls"})
    return stages


def stage_scalar_loss(sim_metrics, metrics, split_name="train", normalize=True, metric_weights=None):
    metric_losses = []
    for metric_name in metrics:
        valid_obs, valid_sim = valid_metric_arrays(metric_name, sim_metrics, split_name)
        if len(valid_obs) == 0:
            continue
        residual = valid_sim - valid_obs
        if normalize:
            residual = residual / (np.mean(np.abs(valid_obs)) + 1e-8)
        if metric_weights is not None:
            residual = residual * np.sqrt(max(metric_weights.get(metric_name, 1.0), 1e-8))
        metric_losses.append(float(np.mean(residual**2)))
    if not metric_losses:
        return 1e9
    return float(np.mean(metric_losses))


def stage_residuals_from_sim(sim_metrics, metrics, split_name="train", normalize=True, metric_weights=None):
    residuals = []
    for metric_name in metrics:
        residual = metric_residual_array(
            metric_name,
            sim_metrics,
            split_name=split_name,
            normalize=normalize,
            metric_weights=metric_weights,
        )
        if len(residual) == 0:
            continue
        residuals.append(residual)
    if not residuals:
        return np.full(1, 1e9)
    return np.concatenate(residuals)


def compute_stage_variances(params_array, metrics):
    sim_metrics = run_dssat_and_get_simulated(clip_params(params_array))
    if sim_metrics is None:
        return {metric_name: 1.0 for metric_name in metrics}
    variances = {}
    for group_metrics in group_metrics_for_selection(metrics, GROUPING_MODE).values():
        residuals = []
        for metric_name in group_metrics:
            residual = metric_residual_array(metric_name, sim_metrics, "train", normalize=False)
            if len(residual) > 0:
                residuals.append(residual)
        if not residuals:
            continue
        group_mse = max(float(np.mean(np.concatenate(residuals) ** 2)), 1e-6)
        for metric_name in group_metrics:
            variances[metric_name] = group_mse
    return variances


def build_agmip_wls_weights(stage_variances):
    weights = {}
    for metric_name in comparable_metric_catalog():
        variance = max(float(stage_variances.get(metric_name, 1.0)), 1e-6)
        weights[metric_name] = float(metric_importance(metric_name) / variance)
    return weights


def stage_metric_weights(start_params, stage, wls_weights=None):
    reference_sim_metrics = run_dssat_and_get_simulated(clip_params(start_params))
    return build_stage_metric_weights(
        stage["metrics"],
        split_name="train",
        weight_mode=WEIGHT_MODE,
        grouping_mode=GROUPING_MODE,
        reference_sim_metrics=reference_sim_metrics,
        wls_weights=wls_weights,
    )


def objective_function(params_array, metrics, split_name="train", metric_weights=None, normalize=True):
    sim_metrics = run_dssat_and_get_simulated(clip_params(params_array))
    if sim_metrics is None:
        return 1e9
    total_loss = stage_scalar_loss(
        sim_metrics,
        metrics,
        split_name=split_name,
        normalize=normalize,
        metric_weights=metric_weights,
    )
    return 1e9 if not np.isfinite(total_loss) else total_loss


def run_scalar_stage(start_params, stage, optimizer_mode, budget_profile, wls_weights=None):
    active = stage["active"]
    sub_bounds = [BOUNDS[index] for index in active]
    x0 = clip_params(start_params)[active]
    metric_weights = stage_metric_weights(start_params, stage, wls_weights=wls_weights)
    normalize = normalize_residuals_for_weight_mode() and stage["mode"] != "wls"

    def stage_objective(sub_params):
        trial = np.array(start_params, dtype=float)
        trial[active] = sub_params
        return objective_function(
            trial,
            metrics=stage["metrics"],
            split_name="train",
            metric_weights=metric_weights,
            normalize=normalize,
        )

    if optimizer_mode == "o3_anneal_nm":
        result = dual_annealing(
            stage_objective,
            bounds=sub_bounds,
            x0=x0,
            maxiter=budget_profile["anneal_maxiter"],
            seed=RANDOM_SEED,
            minimizer_kwargs={
                "method": "Nelder-Mead",
                "options": {"maxiter": budget_profile["local_maxiter"], "maxfev": budget_profile["local_maxfev"]},
            },
        )
    elif optimizer_mode == "o3_powell":
        result = minimize(
            stage_objective,
            x0=x0,
            method="Powell",
            bounds=sub_bounds,
            options={"maxiter": budget_profile["local_maxiter"], "maxfev": budget_profile["local_maxfev"]},
        )
    else:
        result = minimize(
            stage_objective,
            x0=x0,
            method="Nelder-Mead",
            options={"maxiter": budget_profile["local_maxiter"], "maxfev": budget_profile["local_maxfev"]},
        )

    best_params = np.array(start_params, dtype=float)
    best_params[active] = result.x
    best_params = clip_params(best_params)
    return best_params, float(result.fun), bool(result.success)


def run_scalar_optimization(optimizer_mode):
    params = clip_params(INITIAL_GUESS)
    last_loss = 1e9
    success = True
    budget_profile = get_budget_profile()
    stage_variances = {}
    stage_plan = sequence_stage_plan()
    for stage_index, stage in enumerate(stage_plan, start=1):
        log_stage_start(stage, stage_index, len(stage_plan), optimizer_mode)
        wls_weights = build_agmip_wls_weights(stage_variances) if stage["mode"] == "wls" else None
        params, last_loss, stage_success = run_scalar_stage(params, stage, optimizer_mode, budget_profile, wls_weights=wls_weights)
        success = success and stage_success
        if stage["mode"] != "wls":
            stage_variances.update(compute_stage_variances(params, stage["metrics"]))
        log_stage_end(stage, stage_index, len(stage_plan), stage_success, last_loss)
    return params, last_loss, success


def run_least_squares_stage(start_params, stage, budget_profile, wls_weights=None):
    active = stage["active"]
    x0 = clip_params(start_params)[active]
    lb = np.array([BOUNDS[index][0] for index in active], dtype=float)
    ub = np.array([BOUNDS[index][1] for index in active], dtype=float)
    metric_weights = stage_metric_weights(start_params, stage, wls_weights=wls_weights)
    normalize = normalize_residuals_for_weight_mode() and stage["mode"] != "wls"

    def stage_residuals(sub_params):
        trial = np.array(start_params, dtype=float)
        trial[active] = sub_params
        sim_metrics = run_dssat_and_get_simulated(clip_params(trial))
        if sim_metrics is None:
            size = sum(int(np.sum((OBS_METRICS[m] != -99.0) & TRAIN_MASK)) for m in stage["metrics"])
            return np.full(max(size, 1), 1e9)
        return stage_residuals_from_sim(
            sim_metrics,
            stage["metrics"],
            split_name="train",
            normalize=normalize,
            metric_weights=metric_weights,
        )

    result = least_squares(
        stage_residuals,
        x0=x0,
        bounds=(lb, ub),
        method="trf",
        max_nfev=budget_profile["ls_max_nfev"],
        diff_step=budget_profile["ls_diff_step"],
    )

    best_params = np.array(start_params, dtype=float)
    best_params[active] = result.x
    best_params = clip_params(best_params)
    return best_params, float(result.cost), bool(result.success)


def run_least_squares_optimization():
    params = clip_params(INITIAL_GUESS)
    last_loss = 1e9
    success = True
    budget_profile = get_budget_profile()
    stage_variances = {}
    stage_plan = sequence_stage_plan()
    for stage_index, stage in enumerate(stage_plan, start=1):
        log_stage_start(stage, stage_index, len(stage_plan), "o1_least_squares")
        wls_weights = build_agmip_wls_weights(stage_variances) if stage["mode"] == "wls" else None
        params, last_loss, stage_success = run_least_squares_stage(params, stage, budget_profile, wls_weights=wls_weights)
        success = success and stage_success
        if stage["mode"] != "wls":
            stage_variances.update(compute_stage_variances(params, stage["metrics"]))
        log_stage_end(stage, stage_index, len(stage_plan), stage_success, last_loss)
    return params, last_loss, success


def run_pestpp_ies_optimization():
    params = clip_params(INITIAL_GUESS)
    last_loss = 1e9
    success = True
    budget_profile = get_budget_profile()
    stage_plan = sequence_stage_plan()
    for stage_index, stage in enumerate(stage_plan, start=1):
        log_stage_start(stage, stage_index, len(stage_plan), "o2_pestpp_ies")
        params, last_loss, stage_success = run_pestpp_ies_stage(params, stage, budget_profile)
        success = success and stage_success
        log_stage_end(stage, stage_index, len(stage_plan), stage_success, last_loss)
    return params, last_loss, success


def run_pestpp_glm_optimization():
    params = clip_params(INITIAL_GUESS)
    last_loss = 1e9
    success = True
    budget_profile = get_budget_profile()
    stage_variances = {}
    stage_plan = sequence_stage_plan()
    for stage_index, stage in enumerate(stage_plan, start=1):
        log_stage_start(stage, stage_index, len(stage_plan), "o6_pestpp_glm")
        wls_weights = build_agmip_wls_weights(stage_variances) if stage["mode"] == "wls" else None
        params, last_loss, stage_success = run_pestpp_glm_stage(params, stage, budget_profile, wls_weights=wls_weights)
        success = success and stage_success
        if stage["mode"] != "wls":
            stage_variances.update(compute_stage_variances(params, stage["metrics"]))
        log_stage_end(stage, stage_index, len(stage_plan), stage_success, last_loss)
    return params, last_loss, success


def run_mgda_stage(start_params, stage, budget_profile, wls_weights=None):
    cleanup_pestpp_outputs()
    write_params_file(start_params)

    env = build_pest_stage_env(stage, budget_profile, optimizer_mode="glm")
    progress_log("pest_setup_start", optimizer="o5_mgda", stage=CURRENT_STAGE_CONTEXT["name"], runtime_dir=RUNTIME_DIR)
    run_build_pest_setup(working_dir=RUNTIME_DIR, env=env, python_executable=sys.executable)
    progress_log("pest_setup_done", optimizer="o5_mgda", stage=CURRENT_STAGE_CONTEXT["name"])

    progress_log("pest_solver_start", optimizer="o5_mgda", stage=CURRENT_STAGE_CONTEXT["name"])
    try:
        run_pestpp_executable("pestpp-glm.exe", env, pst_filename="ksas_mvp.pst", failure_label="pestpp-glm execution for mgda")
    except Exception as exc:
        message = str(exc)
        if "jacobian matrix has no non-zeros" in message or "all parameters at/near bounds" in message:
            progress_log(
                "pest_solver_fallback_to_stage_loss",
                optimizer="o5_mgda",
                stage=CURRENT_STAGE_CONTEXT["name"],
                reason="zero_jacobian_or_bound_lock",
            )
            metric_weights = stage_metric_weights(start_params, stage, wls_weights=wls_weights)
            fallback_loss = objective_function(
                start_params,
                metrics=stage["metrics"],
                split_name="train",
                metric_weights=metric_weights,
                normalize=normalize_residuals_for_weight_mode() and stage["mode"] != "wls",
            )
            return np.array(start_params, dtype=float), float(fallback_loss), False
        raise
    progress_log("pest_solver_done", optimizer="o5_mgda", stage=CURRENT_STAGE_CONTEXT["name"])

    progress_log("mgda_update_start", optimizer="o5_mgda", stage=CURRENT_STAGE_CONTEXT["name"])
    mgda_params_path = run_mgda_update(env)
    progress_log("mgda_update_done", optimizer="o5_mgda", stage=CURRENT_STAGE_CONTEXT["name"])

    best_params = parse_named_params_file(mgda_params_path, start_params)
    metric_weights = stage_metric_weights(best_params, stage, wls_weights=wls_weights)
    stage_loss = objective_function(
        best_params,
        metrics=stage["metrics"],
        split_name="train",
        metric_weights=metric_weights,
        normalize=normalize_residuals_for_weight_mode() and stage["mode"] != "wls",
    )
    return best_params, float(stage_loss), True


def run_mgda_optimization():
    params = clip_params(INITIAL_GUESS)
    last_loss = 1e9
    success = True
    budget_profile = get_budget_profile()
    stage_variances = {}
    stage_plan = sequence_stage_plan()
    for stage_index, stage in enumerate(stage_plan, start=1):
        log_stage_start(stage, stage_index, len(stage_plan), "o5_mgda")
        wls_weights = build_agmip_wls_weights(stage_variances) if stage["mode"] == "wls" else None
        params, last_loss, stage_success = run_mgda_stage(params, stage, budget_profile, wls_weights=wls_weights)
        success = success and stage_success
        if stage["mode"] != "wls":
            stage_variances.update(compute_stage_variances(params, stage["metrics"]))
        log_stage_end(stage, stage_index, len(stage_plan), stage_success, last_loss)
    return params, last_loss, success


def score_metrics(sim_metrics, metrics, split_name="all"):
    metric_scores = []
    for metric_name in metrics:
        valid_obs, valid_sim = valid_metric_arrays(metric_name, sim_metrics, split_name)
        metric_score = single_metric_nrmse(valid_obs, valid_sim)
        if np.isfinite(metric_score):
            metric_scores.append(metric_score)
    if not metric_scores:
        return 999.0
    return float(np.mean(metric_scores))


def report_lines(sim_metrics, metrics, split_name):
    result = build_result_schema(sim_metrics, metrics)
    prefix = f"{str(split_name).strip().lower()}_"
    lines = []
    for record in iter_aggregate_value_records(result):
        if not record.name.lower().startswith(prefix):
            continue
        lines.append(f"{record.name}: {record.value:.6f}")
    return lines


def metrics_by_trt_from_sim(sim_metrics, metrics):
    out = {int(trt): {} for trt in SCENARIO_TRTS}
    for metric_name in metrics:
        values = sim_metrics.get(metric_name)
        if values is None:
            continue
        for index, trt in enumerate(SCENARIO_TRTS):
            if index >= len(values):
                continue
            value = float(values[index])
            if not np.isfinite(value):
                continue
            out[int(trt)][str(metric_name).strip().lower()] = value
    return out


def observations_by_trt_from_arrays(metrics):
    out = {int(trt): {} for trt in SCENARIO_TRTS}
    for metric_name in metrics:
        values = OBS_METRICS.get(metric_name)
        if values is None:
            continue
        for index, trt in enumerate(SCENARIO_TRTS):
            if index >= len(values):
                continue
            value = float(values[index])
            if value == -99.0 or not np.isfinite(value):
                continue
            out[int(trt)][str(metric_name).strip().lower()] = value
    return out


def build_result_schema(sim_metrics, metrics):
    return build_evaluation_result(
        metrics_by_trt=metrics_by_trt_from_sim(sim_metrics, metrics),
        observations_by_trt=observations_by_trt_from_arrays(metrics),
        split_by_trt=SPLIT_BY_TRT,
        comparable_metrics=metrics,
    )


def optimization_metrics_for_sequence():
    metrics = []
    for stage in sequence_stage_plan():
        metrics.extend(stage["metrics"])
    return ordered_unique_metrics(metrics)


def comparable_evaluation_metrics():
    return comparable_metric_catalog()


def _official_cul_baseline_params() -> np.ndarray | None:
    filex_name = str((PROJECT_CONFIG.get("scenario", {}) or {}).get("filex", "")).strip()
    if not filex_name:
        return None
    filex_path = resolve_config_case_path(filex_name, PROJECT_CONFIG)
    if not filex_path.exists():
        return None
    try:
        cultivar_code = extract_cultivar_code(filex_path)
    except Exception:
        return None
    cul_path = resolve_cultivar_path()
    if cul_path is None or not cul_path.exists():
        return None

    header_cols: list[str] | None = None
    values: dict[str, float] = {}
    for raw in cul_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("@"):
            header_cols = [c.lstrip("@").strip().upper() for c in stripped.split()]
            continue
        if stripped.startswith("*") or stripped.startswith("!"):
            continue
        if not header_cols:
            continue
        if not line.startswith(cultivar_code):
            continue
        tokens = line.split()
        for idx, col in enumerate(header_cols):
            if idx >= len(tokens):
                break
            try:
                values[col] = float(tokens[idx])
            except ValueError:
                continue
        break

    if not values:
        return None
    out: list[float] = []
    for idx, name in enumerate(PARAM_NAMES):
        key = str(name).strip().upper()
        if key in values:
            out.append(float(values[key]))
            continue
        out.append(float(INITIAL_GUESS[idx]) if idx < len(INITIAL_GUESS) else 0.0)
    return np.array(out, dtype=float)


def default_baseline_params():
    if BASELINE_PARAM_SOURCE == "clipped":
        return clip_params(INITIAL_GUESS)
    if BASELINE_PARAM_SOURCE in {"cul", "cul_official", "official_cul", "dssat_cul"}:
        resolved = _official_cul_baseline_params()
        if resolved is not None:
            return resolved
    return np.array(INITIAL_GUESS, dtype=float)


def main():
    global EVAL_RUN_COUNTER
    global OPTIMIZATION_STARTED_AT
    EVAL_RUN_COUNTER = 0
    OPTIMIZATION_STARTED_AT = time.time()
    print("Starting Official DSSAT-based Optimization Evaluation...")
    print(f"Current_WEIGHT_MODE: {WEIGHT_MODE}")
    optimizer_mode = resolve_optimizer_mode()
    print(f"Current_ENGINE_MODE: {optimizer_mode}")
    print(f"Current BUDGET_MODE: {BUDGET_MODE}")
    print(f"Current CALIBRATION_SEQUENCE: {CALIBRATION_SEQUENCE}")
    print(f"Current GROUPING_MODE: {GROUPING_MODE}")
    print(f"Train_TRTS: {TRAIN_TRTS}")
    print(f"Valid_TRTS: {VALID_TRTS}")
    print(f"Validation_Enabled: {bool(VALID_TRTS)}")
    print(f"Current_PROJECT_CONFIG: {PROJECT_CONFIG_PATH}")
    print(f"Current_CROP_FAMILY: {PROJECT_CONFIG.get('crop_family', '')}")
    print(f"Current_DSSAT_CASE_DIR: {CASE_DIR}")
    print(f"Progress_Every_Evaluations: {PROGRESS_EVERY}")

    config_error = validate_experiment_configuration()
    if config_error:
        print_configuration_failure(config_error)
        res_success = False
        res_fun = 999.0
        best_params = default_baseline_params()
        final_sim_metrics = None
        
    if not config_error:
        if optimizer_mode == "default_dssat":
            best_params = default_baseline_params()
            base_metrics = comparable_evaluation_metrics()
            base_weights = build_stage_metric_weights(
                base_metrics,
                split_name="train",
                weight_mode=WEIGHT_MODE,
                grouping_mode=GROUPING_MODE,
                reference_sim_metrics=run_dssat_and_get_simulated(clip_params(best_params)),
            )
            res_fun = objective_function(
                best_params,
                metrics=base_metrics,
                split_name="train",
                metric_weights=base_weights,
                normalize=normalize_residuals_for_weight_mode(),
            )
            res_success = True
        else:
            if optimizer_mode == "o1_least_squares":
                best_params, res_fun, res_success = run_least_squares_optimization()
            elif optimizer_mode == "o2_pestpp_ies":
                best_params, res_fun, res_success = run_pestpp_ies_optimization()
            elif optimizer_mode == "o5_mgda":
                best_params, res_fun, res_success = run_mgda_optimization()
            elif optimizer_mode == "o6_pestpp_glm":
                best_params, res_fun, res_success = run_pestpp_glm_optimization()
            else:
                best_params, res_fun, res_success = run_scalar_optimization(optimizer_mode)

    if not config_error:
        final_sim_metrics = run_dssat_and_get_simulated(best_params)
        
    if final_sim_metrics is None:
        print("Final Evaluation Failed.")
        train_score = 999.0
        valid_score = 999.0
        all_score = 999.0
        final_score = 999.0
        result_schema_view = None
    else:
        metrics = comparable_evaluation_metrics()
        train_score = score_metrics(final_sim_metrics, metrics, "train")
        all_score = score_metrics(final_sim_metrics, metrics, "all")
        valid_score = score_metrics(final_sim_metrics, metrics, "valid") if VALID_TRTS else all_score
        result_schema_view = build_result_schema(final_sim_metrics, metrics)
        aggregate_values = aggregate_value_map(result_schema_view)
        train_score = float(aggregate_values.get("TRAIN_MEAN_NRMSE", train_score))
        valid_score = float(aggregate_values.get("VALID_MEAN_NRMSE", valid_score))
        all_score = float(aggregate_values.get("ALL_MEAN_NRMSE", all_score))
        final_score = valid_score if VALID_TRTS else all_score

    print(f"Optimization Success: {res_success}")
    print("Final Parameters:")
    for name, val in zip(PARAM_NAMES, best_params):
        print(f"  {name.upper()}: {val:.2f}")
    print(f"Final_Loss_Value: {res_fun:.6f}")
    print(f"Final_Train_Score: {train_score:.6f}")
    print(f"Final_Valid_Score: {valid_score:.6f}")
    print(f"Final_All_Score: {all_score:.6f}")
    print(f"TRAIN_MEAN_NRMSE: {train_score:.6f}")
    print(f"VALID_MEAN_NRMSE: {valid_score:.6f}")
    print(f"ALL_MEAN_NRMSE: {all_score:.6f}")
    if result_schema_view is not None:
        comparable_metrics = comparable_evaluation_metrics()
        print(f"Comparable_Metrics: {','.join(metric.upper() for metric in comparable_metrics)}")
        print(f"Optimization_Metrics: {','.join(metric.upper() for metric in optimization_metrics_for_sequence())}")
        print(build_evaluation_result_line(result_schema_view))
        for line in report_lines(final_sim_metrics, comparable_metrics, "train"):
            print(line)
        if VALID_TRTS:
            for line in report_lines(final_sim_metrics, comparable_metrics, "valid"):
                print(line)
    print(f"Final_Score: {final_score:.6f}")

    if os.environ.get("AR_PHASE1_EXPORT") == "1":
        run_id = os.environ.get("AR_RUN_ID", "local")
        combo_key = os.environ.get("AR_COMBO_KEY", "combo")
        plan = os.environ.get("AR_PLAN", "plan")
        output_root = Path(os.environ.get("AR_PHASE1_OUTPUT_DIR", "").strip()).resolve() if os.environ.get("AR_PHASE1_OUTPUT_DIR", "").strip() else SANDBOX_DIR
        output_root.mkdir(parents=True, exist_ok=True)
        
        import sys
        mvp_root = str(os.environ.get("AR_MVP_ROOT", "")).strip()
        if mvp_root:
            sys.path.insert(0, str(Path(mvp_root).resolve().parent))
        else:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from mvp_pest_mgda.src.calibration_core.result_schema import (
            build_experiment_export_context,
            build_aggregate_metric_export_rows,
            build_aggregate_metric_export_value_map,
            build_treatment_comparison_records,
            build_treatment_metric_export_rows,
            build_treatment_metric_export_value_map,
            AGGREGATE_METRIC_EXPORT_FIELDNAMES,
            TREATMENT_METRIC_EXPORT_FIELDNAMES
        )
        import csv
        
        context = build_experiment_export_context(
            run_id=run_id,
            plan=plan,
            weight_name=WEIGHT_MODE,
            engine=optimizer_mode,
            budget=BUDGET_MODE,
            sequence=CALIBRATION_SEQUENCE,
            grouping=GROUPING_MODE,
            status="success" if res_success else "failed"
        )
        yield_tr_nrmse, yield_tr_bias = 999.0, 999.0
        yield_val_nrmse, yield_val_bias = 999.0, 999.0
        
        if result_schema_view is not None:
            yd_vars = {"hwam", "gwad", "cwam", "yield"}
            for r in result_schema_view.aggregate_metrics:
                if r.metric in yd_vars:
                    if r.split == "train":
                        yield_tr_nrmse, yield_tr_bias = r.nrmse, r.bias
                    elif r.split == "valid":
                        yield_val_nrmse, yield_val_bias = r.nrmse, r.bias
        run_model_stats = summarize_run_model_stats(RUN_MODEL_STATS_PATH)
                        
        lock_path = output_root / ".phase1_export.lock"
        for _ in range(3000): # wait up to 5 mins
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                time.sleep(0.1)
        try:
            summary_path = output_root / "phase1_experiment_summary.tsv"
            if summary_path.exists():
                with open(summary_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f, delimiter="\t")
                    writer.writerow([
                        run_id, combo_key, time.strftime("%Y-%m-%dT%H:%M:%S"), plan, WEIGHT_MODE, optimizer_mode, BUDGET_MODE,
                        CALIBRATION_SEQUENCE, GROUPING_MODE, "success" if res_success else "failed", final_score, 0, 0, 0,
                        "True" if final_score < 999.0 else "False", train_score, valid_score, all_score,
                        yield_tr_nrmse, yield_tr_bias, yield_val_nrmse, yield_val_bias,
                        time.time() - OPTIMIZATION_STARTED_AT, str(bool(VALID_TRTS)), str(TRAIN_TRTS), str(VALID_TRTS), str(CASE_DIR),
                        EVAL_RUN_COUNTER, int(run_model_stats["run_model_invocations"]), int(run_model_stats["dssat_treatment_calls"]), run_model_stats["dssat_wall_sec"]
                    ])
                    
            if result_schema_view is not None:
                agg_path = output_root / "phase1_aggregate_metrics.tsv"
                if agg_path.exists():
                    agg_rows = build_aggregate_metric_export_rows(context, result_schema_view.aggregate_metrics)
                    with open(agg_path, "a", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=AGGREGATE_METRIC_EXPORT_FIELDNAMES, delimiter="\t")
                        for row in agg_rows:
                            writer.writerow(build_aggregate_metric_export_value_map(row))
                            
                trt_path = output_root / "phase1_treatment_metrics.tsv"
                if trt_path.exists():
                    comp_records = build_treatment_comparison_records(
                        result_schema_view,
                        observations_by_trt=observations_by_trt_from_arrays(comparable_metrics),
                        split_by_trt=SPLIT_BY_TRT,
                        comparable_metrics=comparable_metrics
                    )
                    trt_rows = build_treatment_metric_export_rows(context, comp_records)
                    with open(trt_path, "a", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=TREATMENT_METRIC_EXPORT_FIELDNAMES, delimiter="\t")
                        for row in trt_rows:
                            writer.writerow(build_treatment_metric_export_value_map(row))

                fig_path = output_root / "phase1_figure_ready.tsv"
                if fig_path.exists():
                    with open(fig_path, "a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f, delimiter="\t")
                        agg_dict = {(r.split, r.metric): r for r in agg_rows}
                        for row in trt_rows:
                            agg_row = agg_dict.get((row.split, row.metric))
                            if not agg_row:
                                continue
                            writer.writerow([
                                run_id, "1", combo_key, plan, WEIGHT_MODE, optimizer_mode, BUDGET_MODE,
                                CALIBRATION_SEQUENCE, GROUPING_MODE, "success" if res_success else "failed", final_score,
                                row.metric, row.split, row.trt, f"{row.metric}|{row.split}", combo_key, 
                                f"{run_id}|{row.metric}|t{row.trt}",
                                row.observed, row.simulated, row.error, row.abs_error, row.relative_error,
                                agg_row.count, agg_row.nrmse, agg_row.bias
                            ])
                            
            param_path = output_root / "phase1_parameters.tsv"
            if param_path.exists():
                with open(param_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f, delimiter="\t")
                    b0_reference_params = np.array(INITIAL_GUESS, dtype=float)
                    for i, (name, val) in enumerate(zip(PARAM_NAMES, best_params)):
                        lb, ub = BOUNDS[i]
                        is_lb = (val - lb) <= 1e-4
                        is_ub = (ub - val) <= 1e-4
                        baseline_value = float(b0_reference_params[i]) if i < len(b0_reference_params) else float(val)
                        normalized = abs(float(val) - baseline_value) / (ub - lb + 1e-8)
                        writer.writerow([
                            run_id, PROJECT_CONFIG.get("crop_family", ""), combo_key, name, 
                            val, lb, ub, str(is_lb), str(is_ub), normalized
                        ])
        finally:
            try:
                os.unlink(lock_path)
            except OSError:
                pass

if __name__ == "__main__":
    main()
