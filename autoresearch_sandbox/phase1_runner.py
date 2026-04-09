import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

SANDBOX_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SANDBOX_DIR.parent
MVP_ROOT = PROJECT_ROOT / "mvp_pest_mgda"
MULTI_CONFIG_DIR = MVP_ROOT / "config" / "multi"
CURRENT_STRATEGY_PATH = SANDBOX_DIR / "strategy.py"
EVAL_PATH = SANDBOX_DIR / "eval.py"
PHASE1_RUNS_DIR = SANDBOX_DIR / "phase1_runs"

W_MAP = {
    "W0": "w0_raw_identity",
    "W2": "w2_inverse_rmse",
    "W4": "w4_min_max_equal",
    "W5": "w5_mean_normalized",
    "W6": "w6_log_transformation",
    "W8": "w8_dssat_group_max",
    "W9": "w9_pareto_no_preweight",
}
O_MAP = {
    "O1": "o6_pestpp_glm",
    "O2": "o2_pestpp_ies",
    "O5": "o5_mgda",
}
S_MAP = {
    "S1": "s1_naive_joint",
    "S2": "s2_sequential_phase",
}
G_MAP = {
    "G1": "g1_flat_all_in_one",
    "G3": "g3_dssat_extended",
}

CURRENT_STRATEGY_SOURCE = CURRENT_STRATEGY_PATH.read_text(encoding="utf-8")
BENCHMARK_STRATEGIES = {
    "W2": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    eps = 1e-8
    rmse_y = np.sqrt(np.mean((sim_yield - obs_yield) ** 2))
    rmse_l = np.sqrt(np.mean((sim_lai - obs_lai) ** 2))
    scale_y = np.sqrt(np.mean(np.square(obs_yield))) + eps
    scale_l = np.sqrt(np.mean(np.square(obs_lai))) + eps
    norm_y = rmse_y / scale_y
    norm_l = rmse_l / scale_l
    return float(norm_y + norm_l)
""",
    "W4": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    err_y = np.abs(sim_yield - obs_yield)
    err_l = np.abs(sim_lai - obs_lai)
    max_err_y = np.max(obs_yield) + 1e-8
    max_err_l = np.max(obs_lai) + 1e-8
    norm_y = np.mean(err_y / max_err_y)
    norm_l = np.mean(err_l / max_err_l)
    return float(norm_y + norm_l)
""",
    "W6": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    log_sim_y = np.log(np.clip(sim_yield, 1e-8, None))
    log_obs_y = np.log(np.clip(obs_yield, 1e-8, None))
    log_sim_l = np.log(np.clip(sim_lai, 1e-8, None))
    log_obs_l = np.log(np.clip(obs_lai, 1e-8, None))
    loss_y = np.mean((log_sim_y - log_obs_y) ** 2)
    loss_l = np.mean((log_sim_l - log_obs_l) ** 2)
    return float(loss_y + loss_l)
""",
}

BATCH_A = [
    ("W0", "O1", "S1", "G1"),
    ("W0", "O1", "S1", "G3"),
    ("W4", "O1", "S1", "G1"),
    ("W4", "O1", "S1", "G3"),
]
BATCH_B = [
    ("W8", "O1", "S1", "G3"),
    ("W8", "O1", "S2", "G3"),
    ("W8", "O2", "S1", "G3"),
    ("W8", "O2", "S2", "G3"),
    ("W4", "O1", "S1", "G3"),
    ("W4", "O1", "S2", "G3"),
]
BATCH_C = [
    ("W8", "O1", "S2", "G3"),
    ("W8", "O2", "S2", "G3"),
    ("W4", "O1", "S2", "G3"),
    ("W4", "O2", "S2", "G3"),
]
BATCH_D = [(w, o, s, g) for w in ("W0", "W4", "W6", "W8") for o in ("O1", "O2") for s in ("S1", "S2") for g in ("G1", "G3")]
LEGACY_CORE = [(w, o, "S2", "G3") for w in ("W2", "W5") for o in ("O1", "O2")]
LEGACY_MGDA = [("W9", "O5", "S2", "G3")]
BATCH_MAP = {
    "BatchA": BATCH_A,
    "BatchB": BATCH_B,
    "BatchC": BATCH_C,
    "BatchD": BATCH_D,
    "LegacyCore": LEGACY_CORE,
    "LegacyMGDA": LEGACY_MGDA,
}

SUMMARY_FIELDS = [
    "run_id", "combo_key", "executed_at", "plan", "weight", "engine", "budget",
    "sequence", "grouping", "status", "score", "delta_vs_b0", "delta_vs_b1", "delta_vs_negative_ref",
    "better_than_b0", "train_mean_nrmse", "valid_mean_nrmse", "all_mean_nrmse",
    "train_yield_nrmse", "train_yield_bias", "valid_yield_nrmse", "valid_yield_bias",
    "duration_sec", "validation_enabled", "train_trts", "valid_trts", "workspace_dir",
    "eval_call_count", "run_model_invocations", "dssat_treatment_calls", "dssat_wall_sec",
]
AGG_FIELDS = ["run_id", "plan", "weight", "engine", "budget", "sequence", "grouping", "status", "split", "metric", "count", "nrmse", "bias"]
TRT_FIELDS = ["run_id", "plan", "weight", "engine", "budget", "sequence", "grouping", "status", "trt", "split", "metric", "observed", "simulated", "error", "abs_error", "relative_error"]
PARAM_FIELDS = ["run_id", "crop", "combo_key", "param_name", "param_value", "lower_bound", "upper_bound", "is_at_lower_bound", "is_at_upper_bound", "normalized_distance_to_b0"]
FIG_FIELDS = [
    "run_id", "score_rank", "combo_key", "plan", "weight", "engine", "budget", "sequence", "grouping",
    "status", "score", "metric", "split", "trt", "panel_key", "series_key", "point_key",
    "x_observed", "y_simulated", "residual", "abs_residual", "relative_error", "panel_count", "panel_nrmse", "panel_bias",
]


def init_tsv(path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle, delimiter="\t").writerow(columns)


def resolve_crop_configs() -> dict[str, Path]:
    candidates = {
        "Wheat": [SANDBOX_DIR / "project_wheat.json", MULTI_CONFIG_DIR / "project_wheat.json"],
        "Maize": [MULTI_CONFIG_DIR / "project_maize.json"],
        "Soybean": [MULTI_CONFIG_DIR / "project_soybean.json"],
        "Rice": [MULTI_CONFIG_DIR / "project_rice.json"],
        "Cotton": [MULTI_CONFIG_DIR / "project_cotton.json"],
    }
    resolved: dict[str, Path] = {}
    for crop, paths in candidates.items():
        for path in paths:
            if path.exists():
                resolved[crop] = path
                break
    return resolved


def python_executable() -> str:
    windows_python = MVP_ROOT / ".venv" / "Scripts" / "python.exe"
    posix_python = MVP_ROOT / ".venv" / "bin" / "python"
    if windows_python.exists():
        return str(windows_python)
    if posix_python.exists():
        return str(posix_python)
    return sys.executable


def resolve_pestpp_env() -> dict[str, str]:
    env_updates: dict[str, str] = {"PESTPP_ROOT": str(MVP_ROOT)}
    glm_candidates = [
        MVP_ROOT / "pestpp-glm.exe",
        MVP_ROOT / "bin" / "pestpp-glm.exe",
        MVP_ROOT / "vendor" / "pestpp_5.2.16_iwin" / "bin" / "pestpp-glm.exe",
    ]
    ies_candidates = [
        MVP_ROOT / "pestpp-ies.exe",
        MVP_ROOT / "bin" / "pestpp-ies.exe",
        MVP_ROOT / "vendor" / "pestpp_5.2.16_iwin" / "bin" / "pestpp-ies.exe",
    ]
    for candidate in glm_candidates:
        if candidate.exists():
            env_updates["PESTPP_GLM"] = str(candidate)
            break
    for candidate in ies_candidates:
        if candidate.exists():
            env_updates["PESTPP_IES"] = str(candidate)
            break
    return env_updates


def strategy_source_for_weight(weight_code: str) -> str:
    return BENCHMARK_STRATEGIES.get(weight_code, CURRENT_STRATEGY_SOURCE)


def load_project_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_case_dir_contents(source: Path, destination: Path) -> None:
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


def phase0_readiness_reason(config_path: Path) -> str | None:
    config = load_project_config(config_path)
    paths = config.get("paths", {}) or {}
    case_dir = Path(str(paths.get("dssat_case_dir", "")).strip())
    if not case_dir.exists():
        return f"missing_case_dir:{case_dir}"
    required_file_keys = ("obs_a_path", "obs_t_path", "cul_path", "dssat_exe")
    for key in required_file_keys:
        raw_value = str(paths.get(key, "")).strip()
        if raw_value and not Path(raw_value).exists():
            return f"missing_{key}:{raw_value}"
    return None


def prepare_workspace(session_root: Path, run_id: str, config_path: Path, strategy_source: str) -> tuple[Path, Path]:
    workspace_dir = session_root / "workspaces" / run_id
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EVAL_PATH, workspace_dir / "eval.py")
    local_config_path = workspace_dir / config_path.name
    shutil.copy2(config_path, local_config_path)
    (workspace_dir / "strategy.py").write_text(strategy_source, encoding="utf-8")
    config = load_project_config(config_path)
    source_case_dir = Path(config.get("paths", {}).get("dssat_case_dir", "")).resolve()
    case_dir = workspace_dir / "dssat_case"
    if source_case_dir.exists():
        copy_case_dir_contents(source_case_dir, case_dir)
    return workspace_dir, local_config_path


def create_session_root(batch: str, budget: str, tag: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_name = f"{timestamp}_phase1_{batch.lower()}_{budget.lower()}_{tag.lower()}".replace("-", "_")
    session_root = PHASE1_RUNS_DIR / session_name
    session_root.mkdir(parents=True, exist_ok=True)
    return session_root


def runtime_root_for_run(run_id: str) -> Path:
    token = hashlib.sha1(str(run_id).encode("utf-8")).hexdigest()[:12]
    return PROJECT_ROOT / ".dssat_rt" / token


def initialize_output_tables(session_root: Path) -> None:
    init_tsv(session_root / "phase1_experiment_summary.tsv", SUMMARY_FIELDS)
    init_tsv(session_root / "phase1_aggregate_metrics.tsv", AGG_FIELDS)
    init_tsv(session_root / "phase1_treatment_metrics.tsv", TRT_FIELDS)
    init_tsv(session_root / "phase1_parameters.tsv", PARAM_FIELDS)
    init_tsv(session_root / "phase1_figure_ready.tsv", FIG_FIELDS)


def baseline_jobs() -> list[tuple[str, str, str, str, str, str | None, str | None]]:
    return [
        ("B0", "w0_raw_identity", "default_dssat", "s1_naive_joint", "g1_flat_all_in_one", "external", None),
        ("B1", "w0_raw_identity", "default_dssat", "s1_naive_joint", "g1_flat_all_in_one", "clipped", None),
        ("B2", "w8_dssat_group_max", "o6_pestpp_glm", "s2_sequential_phase", "g3_dssat_extended", "external", "standard"),
    ]


def build_jobs(
    session_root: Path,
    batch: str,
    repetitions: int,
    budget: str,
    crops: list[str],
    combo_keys: set[str] | None = None,
    train_only: bool = True,
) -> tuple[list[dict], dict[str, str]]:
    crop_configs = resolve_crop_configs()
    jobs: list[dict] = []
    skipped_crops: dict[str, str] = {}
    seen_combo_instances: set[tuple[str, str, int]] = set()
    if batch in {"Baselines", "All", "LegacyCore", "LegacyMGDA"}:
        for crop in crops:
            config_path = crop_configs.get(crop)
            if not config_path:
                skipped_crops[crop] = "missing_project_config"
                continue
            reason = phase0_readiness_reason(config_path)
            if reason is not None:
                skipped_crops[crop] = reason
                continue
            for baseline_name, weight, engine, sequence, grouping, baseline_source, min_budget in baseline_jobs():
                if combo_keys and baseline_name not in combo_keys:
                    continue
                run_id = f"{baseline_name}_{crop.lower()}_rep0_{uuid.uuid4().hex[:6]}"
                effective_budget = min_budget if min_budget and budget == "quick" else budget
                jobs.append({
                    "run_id": run_id,
                    "combo_key": baseline_name,
                    "crop": crop,
                    "config_path": config_path,
                    "weight_code": "W8" if baseline_name == "B2" else "W0",
                    "weight": weight,
                    "engine": engine,
                    "sequence": sequence,
                    "grouping": grouping,
                    "plan": "Baselines",
                    "baseline_source": baseline_source,
                    "budget": effective_budget,
                    "random_seed": 42,
                    "train_only": train_only,
                })
    batches_to_run = [batch] if batch in BATCH_MAP else list(BATCH_MAP.keys()) if batch == "All" else []
    for batch_name in batches_to_run:
        for crop in crops:
            config_path = crop_configs.get(crop)
            if not config_path:
                skipped_crops[crop] = "missing_project_config"
                continue
            reason = phase0_readiness_reason(config_path)
            if reason is not None:
                skipped_crops[crop] = reason
                continue
            for w, o, s, g in BATCH_MAP[batch_name]:
                combo_key = f"{w}_{o}_{s}_{g}"
                combo_aliases = {"PM_O5_S2_G3"} if combo_key == "W9_O5_S2_G3" else set()
                if combo_keys and combo_key not in combo_keys and combo_aliases.isdisjoint(combo_keys):
                    continue
                for rep in range(repetitions):
                    combo_instance = (str(crop).strip().lower(), combo_key, int(rep))
                    if combo_instance in seen_combo_instances:
                        continue
                    seen_combo_instances.add(combo_instance)
                    run_id = f"{combo_key}_{crop.lower()}_rep{rep}_{uuid.uuid4().hex[:6]}"
                    jobs.append({
                        "run_id": run_id,
                        "combo_key": combo_key,
                        "crop": crop,
                        "config_path": config_path,
                        "weight_code": w,
                        "weight": W_MAP[w],
                        "engine": O_MAP[o],
                        "sequence": S_MAP[s],
                        "grouping": G_MAP[g],
                        "plan": batch_name,
                        "baseline_source": None,
                        "budget": budget,
                        "random_seed": 42 + rep,
                        "train_only": train_only,
                    })
    return jobs, skipped_crops


def write_manifest(session_root: Path, payload: dict) -> None:
    (session_root / "phase1_run_manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_job(job: dict, session_root: Path) -> dict:
    logs_dir = session_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / f"{job['run_id']}.stdout.log"
    stderr_path = logs_dir / f"{job['run_id']}.stderr.log"
    started = time.time()
    try:
        workspace_dir, local_config_path = prepare_workspace(session_root, job["run_id"], Path(job["config_path"]), strategy_source_for_weight(str(job["weight_code"])))
        env = os.environ.copy()
        env["AR_WEIGHTING"] = str(job["weight"])
        env["AR_ENGINE"] = str(job["engine"])
        env["AR_SEQUENCE"] = str(job["sequence"])
        env["AR_GROUPING"] = str(job["grouping"])
        env["AR_PROJECT_CONFIG"] = str(local_config_path)
        env["AR_RANDOM_SEED"] = str(job["random_seed"])
        env["AR_BUDGET"] = str(job["budget"])
        env["AR_PHASE1_EXPORT"] = "1"
        env["AR_PHASE1_OUTPUT_DIR"] = str(session_root)
        env["AR_RUN_ID"] = str(job["run_id"])
        env["AR_COMBO_KEY"] = str(job["combo_key"])
        env["AR_PLAN"] = str(job["plan"])
        env["AR_SANDBOX_DIR"] = str(workspace_dir)
        env["DSSAT_CASE_DIR"] = str(workspace_dir / "dssat_case")
        env["DSSAT_RUNTIME_ROOT"] = str(runtime_root_for_run(str(job["run_id"])))
        env["DSSAT_SKIP_TASKKILL"] = "1"
        env["AR_MVP_ROOT"] = str(MVP_ROOT)
        env["PEST_RUN_MODEL_PYTHON"] = python_executable()
        env.update(resolve_pestpp_env())
        env["AR_FORCE_TRAIN_ONLY"] = "1" if job.get("train_only", True) else "0"
        if job.get("baseline_source"):
            env["AR_BASELINE_PARAM_SOURCE"] = str(job["baseline_source"])
        result = subprocess.run([python_executable(), str(workspace_dir / "eval.py")], env=env, cwd=str(workspace_dir), capture_output=True, text=True)
        stdout_path.write_text(result.stdout or "", encoding="utf-8")
        stderr_path.write_text(result.stderr or "", encoding="utf-8")
        duration = time.time() - started
        status = "success" if result.returncode == 0 else "failed"
        if status == "success":
            print(f"[{time.strftime('%H:%M:%S')}] completed {job['combo_key']} for {job['crop']} in {duration:.1f}s", flush=True)
        else:
            print(f"[{time.strftime('%H:%M:%S')}] failed {job['combo_key']} for {job['crop']} rc={result.returncode}", flush=True)
            tail = (result.stderr or result.stdout or "")[-500:]
            if tail:
                print(tail, flush=True)
        return {"run_id": job["run_id"], "status": status, "returncode": result.returncode}
    except Exception as exc:
        stderr_path.write_text(str(exc), encoding="utf-8")
        print(f"[{time.strftime('%H:%M:%S')}] exception {job['combo_key']} for {job['crop']}: {exc}", flush=True)
        return {"run_id": job["run_id"], "status": "failed", "returncode": -1}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", choices=["Baselines", "BatchA", "BatchB", "BatchC", "BatchD", "LegacyCore", "LegacyMGDA", "All"], default="All")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--workers", type=int, default=14)
    parser.add_argument("--budget", choices=["quick", "standard", "matrix", "phase3_formal"], default="quick")
    parser.add_argument("--tag", default="trial")
    parser.add_argument("--crops", default="Wheat,Maize,Soybean,Rice,Cotton")
    parser.add_argument("--combo-keys", default="")
    split_mode = parser.add_mutually_exclusive_group()
    split_mode.add_argument("--train-only", dest="train_only", action="store_true")
    split_mode.add_argument("--with-validation", dest="train_only", action="store_false")
    parser.set_defaults(train_only=True)
    parser.add_argument("--skip-postprocess", action="store_true")
    args = parser.parse_args()

    crops = [item.strip() for item in args.crops.split(",") if item.strip()]
    combo_keys = {item.strip() for item in args.combo_keys.split(",") if item.strip()}
    session_root = create_session_root(args.batch, args.budget, args.tag)
    initialize_output_tables(session_root)
    jobs, skipped_crops = build_jobs(session_root, args.batch, args.repetitions, args.budget, crops, combo_keys=combo_keys or None, train_only=bool(args.train_only))
    write_manifest(session_root, {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "batch": args.batch,
        "budget": args.budget,
        "workers": args.workers,
        "repetitions": args.repetitions,
        "crops": crops,
        "combo_keys": sorted(combo_keys),
        "train_only": bool(args.train_only),
        "job_count": len(jobs),
        "skipped_crops": skipped_crops,
    })

    print("==========================================")
    print("Starting Phase 1 Execution Roadmap")
    print(f"   Target: {args.batch}")
    print(f"   Budget: {args.budget}")
    print(f"   Repetitions: {args.repetitions}")
    print(f"   Concurrency: {args.workers} workers")
    print(f"   Train Only: {bool(args.train_only)}")
    print(f"   Session Root: {session_root}")
    print(f"   Jobs: {len(jobs)}")
    if combo_keys:
        print(f"   Combo Keys: {sorted(combo_keys)}")
    if skipped_crops:
        print(f"   Skipped Crops: {skipped_crops}")
    print("==========================================")

    failures: list[dict] = []
    if jobs:
        try:
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [executor.submit(run_job, job, session_root) for job in jobs]
                for future in as_completed(futures):
                    result = future.result()
                    if result["status"] != "success":
                        failures.append(result)
        except KeyboardInterrupt:
            print("Execution interrupted.", flush=True)
            raise

    if not args.skip_postprocess:
        subprocess.run(
            [python_executable(), str(SANDBOX_DIR / "phase1_postprocess.py"), "--input-dir", str(session_root)],
            cwd=str(SANDBOX_DIR),
            check=False,
        )

    if failures:
        write_manifest(session_root, {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "batch": args.batch,
            "budget": args.budget,
            "workers": args.workers,
            "repetitions": args.repetitions,
            "crops": crops,
            "combo_keys": sorted(combo_keys),
            "train_only": bool(args.train_only),
            "job_count": len(jobs),
            "skipped_crops": skipped_crops,
            "failure_count": len(failures),
            "failures": failures,
        })
    print(f"Phase 1 session finished: {session_root}", flush=True)


if __name__ == "__main__":
    main()
