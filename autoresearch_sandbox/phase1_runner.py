import os
import sys
import subprocess
import time
import json
import uuid
import csv
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

SANDBOX_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SANDBOX_DIR.parent
MVP_ROOT = PROJECT_ROOT / "mvp_pest_mgda"

# Define matrix mapping (strictly adhering to 02_Terminology_and_Notation.md Table 4.2)
W_MAP = {
    "W0": "w0_raw_identity",       # Raw-Identity
    "W4": "w4_min_max_equal",      # Min-Max Equal
    "W6": "w6_log_transformation", # Log-Transformation
    "W8": "w8_dssat_group_max"     # DSSAT-PEST Group-Max Scaling
}
O_MAP = {
    "O1": "o6_pestpp_glm",         # pestpp-glm (Deterministic, requires fewer reps)
    "O2": "o2_pestpp_ies"          # pestpp-ies (Ensemble smoothed, requires multiple reps)
}
S_MAP = {
    "S1": "s1_naive_joint",        # Naive Joint
    "S2": "s2_sequential_phase"    # Sequential Phase
}
G_MAP = {
    "G1": "g1_flat_all_in_one",    # Flat-All-in-One
    "G3": "g3_dssat_extended"      # DSSAT-PEST Extended Grouping
}

# Define Batches as per rules
BATCH_A = [
    ("W0", "O1", "S1", "G1"), ("W0", "O1", "S1", "G3"),
    ("W4", "O1", "S1", "G1"), ("W4", "O1", "S1", "G3"),
]

BATCH_B = [
    ("W8", "O1", "G3", "S1"), ("W8", "O1", "G3", "S2"),
    ("W8", "O2", "G3", "S1"), ("W8", "O2", "G3", "S2"),
    ("W4", "O1", "G3", "S1"), ("W4", "O1", "G3", "S2"),
]

BATCH_C = [
    ("W8", "O1", "S2", "G3"), ("W8", "O2", "S2", "G3"),
    ("W4", "O1", "S2", "G3"), ("W4", "O2", "S2", "G3"),
]

BATCH_D = []
for w in ["W0", "W4", "W6", "W8"]:
    for o in ["O1", "O2"]:
        for s in ["S1", "S2"]:
            for g in ["G1", "G3"]:
                BATCH_D.append((w, o, s, g))

BATCH_MAP = {
    "BatchA": BATCH_A,
    "BatchB": BATCH_B,
    "BatchC": BATCH_C,
    "BatchD": BATCH_D,
}

def init_tsv(path, columns):
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(columns)

def _run_single_subprocess(cmd, env, run_id, combo_key):
    start_time = time.time()
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        duration = time.time() - start_time
        status = "success" if res.returncode == 0 else "failed"
        crop = run_id.split('_')[1] if len(run_id.split('_')) > 1 else "Unknown"
        
        if status == "failed":
            print(f"[{time.strftime('%H:%M:%S')}] ❌ FAILED {combo_key} for {crop} (RC: {res.returncode})", flush=True)
            print(f"Stderr tail: {res.stderr[-500:]}", flush=True)
        else:
            print(f"[{time.strftime('%H:%M:%S')}] ✅ Completed {combo_key} for {crop} in {duration:.1f}s", flush=True)
    except Exception as e:
        status = "failed"
        print(f"[{time.strftime('%H:%M:%S')}] ❌ EXCEPTION {combo_key}: {e}", flush=True)
    return status

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=str, choices=["Baselines", "BatchA", "BatchB", "BatchC", "BatchD", "All"], default="All", help="Which batch to run")
    parser.add_argument("--repetitions", type=int, default=5, help="Number of repetitions per combination")
    parser.add_argument("--workers", type=int, default=14, help="Maximum concurrent processes")
    parser.add_argument("--skip-postprocess", action="store_true", help="Skip postprocessing derived metrics")
    args = parser.parse_args()

    print("==========================================")
    print("🌾 Starting Phase 1 Execution Roadmap")
    print(f"   Target: {args.batch}")
    print(f"   Repetitions: {args.repetitions}")
    print(f"   Concurrency: {args.workers} workers")
    print("==========================================")
    
    # Setup TSV outputs
    summary_path = SANDBOX_DIR / "phase1_experiment_summary.tsv"
    init_tsv(summary_path, [
        "run_id", "combo_key", "executed_at", "plan", "weight", "engine", "budget",
        "sequence", "grouping", "status", "score", "delta_vs_b0", "delta_vs_b1", "delta_vs_negative_ref",
        "better_than_b0", "train_mean_nrmse", "valid_mean_nrmse", "all_mean_nrmse",
        "train_yield_nrmse", "train_yield_bias", "valid_yield_nrmse", "valid_yield_bias",
        "duration_sec", "validation_enabled", "train_trts", "valid_trts", "workspace_dir"
    ])

    agg_path = SANDBOX_DIR / "phase1_aggregate_metrics.tsv"
    init_tsv(agg_path, [
        "run_id", "plan", "weight", "engine", "budget", "sequence", "grouping", "status",
        "split", "metric", "count", "nrmse", "bias"
    ])

    trt_path = SANDBOX_DIR / "phase1_treatment_metrics.tsv"
    init_tsv(trt_path, [
        "run_id", "plan", "weight", "engine", "budget", "sequence", "grouping", "status",
        "trt", "split", "metric", "observed", "simulated", "error", "abs_error", "relative_error"
    ])

    param_path = SANDBOX_DIR / "phase1_parameters.tsv"
    init_tsv(param_path, [
        "run_id", "crop", "combo_key", "param_name", "param_value", "lower_bound", "upper_bound",
        "is_at_lower_bound", "is_at_upper_bound", "normalized_distance_to_b0"
    ])

    fig_path = SANDBOX_DIR / "phase1_figure_ready.tsv"
    init_tsv(fig_path, [
        "run_id", "score_rank", "combo_key", "plan", "weight", "engine", "budget", "sequence", "grouping", 
        "status", "score", "metric", "split", "trt", "panel_key", "series_key", "point_key", 
        "x_observed", "y_simulated", "residual", "abs_residual", "relative_error", 
        "panel_count", "panel_nrmse", "panel_bias"
    ])

    # Crop Configs
    crop_configs = {
        "Wheat": SANDBOX_DIR / "project_wheat.json",
        "Maize": SANDBOX_DIR / "project_maize.json",
        "Soybean": SANDBOX_DIR / "project_soybean.json",
        "Rice": SANDBOX_DIR / "project_rice.json",
        "Cotton": SANDBOX_DIR / "project_cotton.json"
    }

    eval_script = SANDBOX_DIR / "eval.py"

    # VENV Python Executable Lock
    venv_python = MVP_ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = MVP_ROOT / ".venv" / "bin" / "python"
    executable = str(venv_python) if venv_python.exists() else sys.executable

    jobs_to_run = []

    # 1. BASELINES QUEUE
    if args.batch in ["Baselines", "All"]:
        for crop_name, config_path in crop_configs.items():
            if not config_path.exists():
                print(f"Skipping baselines for {crop_name}, config not found.", flush=True)
                continue
                
            baselines = [
                ("B0", "w0_raw_identity", "default_dssat", "s1_naive_joint", "g1_flat_all_in_one"),
                ("B1", "w0_raw_identity", "o1_least_squares", "s1_naive_joint", "g1_flat_all_in_one"),
                ("B2", "w0_raw_identity", "o6_pestpp_glm", "s1_naive_joint", "g1_flat_all_in_one")
            ]
            for b_name, w, o, s, g in baselines:
                run_id = f"{b_name}_{crop_name}_0_{uuid.uuid4().hex[:6]}"
                combo_key = f"{b_name}"
                
                env = os.environ.copy()
                env["AR_WEIGHTING"] = w
                env["AR_ENGINE"] = o
                env["AR_SEQUENCE"] = s
                env["AR_GROUPING"] = g
                env["AR_PROJECT_CONFIG"] = str(config_path)
                env["AR_RANDOM_SEED"] = "42"
                env["AR_PHASE1_EXPORT"] = "1"
                env["AR_RUN_ID"] = run_id
                env["AR_COMBO_KEY"] = combo_key
                env["AR_PLAN"] = "Baselines"

                cmd = [executable, str(eval_script)]
                jobs_to_run.append((cmd, env, run_id, combo_key))

    # 2. GRID QUEUE
    if args.batch in BATCH_MAP:
        batches_to_run = [args.batch]
    elif args.batch == "All":
        batches_to_run = list(BATCH_MAP.keys())
    else:
        batches_to_run = []

    for batch_name in batches_to_run:
        batch_combinations = BATCH_MAP[batch_name]
        for crop, config_path in crop_configs.items():
            if not config_path.exists():
                continue
            for w, o, s, g in batch_combinations:
                combo_key = f"{w}_{o}_{s}_{g}"
                for rep in range(args.repetitions):
                    run_id = f"{combo_key}_{crop}_{rep}_{uuid.uuid4().hex[:6]}"
                    
                    env = os.environ.copy()
                    env["AR_WEIGHTING"] = W_MAP.get(w, w)
                    env["AR_ENGINE"] = O_MAP.get(o, o)
                    env["AR_SEQUENCE"] = S_MAP.get(s, s)
                    env["AR_GROUPING"] = G_MAP.get(g, g)
                    env["AR_PROJECT_CONFIG"] = str(config_path)
                    env["AR_RANDOM_SEED"] = str(42 + rep)

                    env["AR_PHASE1_EXPORT"] = "1"
                    env["AR_RUN_ID"] = run_id
                    env["AR_COMBO_KEY"] = combo_key
                    env["AR_PLAN"] = batch_name
                    
                    cmd = [executable, str(eval_script)]
                    jobs_to_run.append((cmd, env, run_id, combo_key))

    # 3. DISPATCHER
    if jobs_to_run:
        print(f"\n🚀 Dispatched {len(jobs_to_run)} total models for evaluation...", flush=True)
        try:
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [executor.submit(_run_single_subprocess, c, e, r, k) for c, e, r, k in jobs_to_run]
                for i, f in enumerate(as_completed(futures)):
                    pass # Output is handled strictly by the worker to avoid overlap
        except KeyboardInterrupt:
            print("\n🚨 Execution Interrupted by User! Waiting for active workers to shut down...", flush=True)
            executor.shutdown(wait=False, cancel_futures=True)
            sys.exit(1)

    print("\n🏁 All processes finished.", flush=True)

    if not args.skip_postprocess:
        print("--- Running Post-Processing to Derive Phase1 Metrics ---", flush=True)
        try:
            import phase1_postprocess
            phase1_postprocess.main()
        except Exception as e:
            print(f"Error during post-processing: {e}")

if __name__ == "__main__":
    main()
