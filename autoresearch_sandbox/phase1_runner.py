import os
import sys
import subprocess
import time
import json
import uuid
import csv
from pathlib import Path
from datetime import datetime

SANDBOX_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SANDBOX_DIR.parent
MVP_ROOT = PROJECT_ROOT / "mvp_pest_mgda"

# Define matrix mapping
W_MAP = {"W0": "w0_raw_identity", "W4": "w4_min_max_equal", "W6": "w6_log_transformation", "W8": "w8_dssat_group_max"}
# Note: Phase 1 guide says "O1 (MGDA Hybrid)" which could correspond to mgda (o5). "O2" (Global+Local) could correspond to o3 (anneal_nm).
O_MAP = {"O1": "o5_mgda", "O2": "o3_anneal_nm"}
S_MAP = {"S1": "s1_naive_joint", "S2": "s2_sequential_phase"}
G_MAP = {"G1": "g1_flat_all_in_one", "G3": "g3_dssat_extended"}

# Define Batches as per rules
BATCH_A = [
    # W0/W4 x O1 x S1 x G1/G3
    ("W0", "O1", "S1", "G1"),
    ("W0", "O1", "S1", "G3"),
    ("W4", "O1", "S1", "G1"),
    ("W4", "O1", "S1", "G3"),
]

BATCH_B = [
    # W8/W4 x O1/O2 x G3 x S1/S2
    ("W8", "O1", "G3", "S1"), ("W8", "O1", "G3", "S2"),
    ("W8", "O2", "G3", "S1"), ("W8", "O2", "G3", "S2"),
    ("W4", "O1", "G3", "S1"), ("W4", "O1", "G3", "S2"),
]

BATCH_C = [
    # W8/W4 x G3 x S2 x O1/O2
    ("W8", "G3", "S2", "O1"), ("W8", "G3", "S2", "O2"),
    ("W4", "G3", "S2", "O1"), ("W4", "G3", "S2", "O2"),
]

def init_tsv(path, columns):
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(columns)

def main():
    print("Starting Phase 1 Execution Roadmap...")
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

    # For testing, we are using just Wheat project config, run only Batch A to verify pipeline works
    crop_configs = {
        "Wheat": SANDBOX_DIR / "project_wheat.json"
    }

    eval_script = SANDBOX_DIR / "eval.py"

    # RUN BASELINES (B0, B1, B2)
    print("--- Running Baselines ---")
    for crop_name, config_path in crop_configs.items():
        if not config_path.exists():
            continue
            
        baselines = [
            ("B0", "w0_raw_identity", "default_dssat", "s1_naive_joint", "g1_flat_all_in_one"),
            ("B1", "w0_raw_identity", "o1_least_squares", "s1_naive_joint", "g1_flat_all_in_one"), # Example B1 mapping
            ("B2", "w0_raw_identity", "o6_pestpp_glm", "s1_naive_joint", "g1_flat_all_in_one")    # Example B2 mapping
        ]
        for b_name, w, o, s, g in baselines:
            run_id = f"{b_name}_{crop_name}_0_{uuid.uuid4().hex[:6]}"
            combo_key = f"{b_name}"
            print(f"Running Baseline: {combo_key} for {crop_name}")
            
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

            cmd = [sys.executable, str(eval_script)]
            res = subprocess.run(cmd, env=env, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"Baseline {b_name} failed. Return code: {res.returncode}")
                print("Stderr:", res.stderr[-500:])

    run_batch("BatchA", BATCH_A, crop_configs, eval_script, 1, summary_path)
    
    print("--- Running Post-Processing to Derive Phase1 Metrics ---")
    try:
        import phase1_postprocess
        phase1_postprocess.main()
    except Exception as e:
        print(f"Error during post-processing: {e}")

def run_batch(batch_name, batch_combinations, crop_configs, eval_script, repetitions, summary_path):
    print(f"--- Running {batch_name} ---")
    for crop, config_path in crop_configs.items():
        if not config_path.exists():
            print(f"Warning: config for {crop} not found at {config_path}")
            continue

        for w, o, s, g in batch_combinations:
            combo_key = f"{w}_{o}_{s}_{g}"
            print(f"Running Combo: {combo_key} for {crop}")
            
            for rep in range(repetitions):
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

                start_time = time.time()
                
                # Execute eval.py
                cmd = [sys.executable, str(eval_script)]
                print(f"Executing: {' '.join(cmd)}")
                
                # We pipe stdout to see progress if any
                res = subprocess.run(cmd, env=env, capture_output=True, text=True)
                
                duration = time.time() - start_time
                status = "success" if res.returncode == 0 else "failed"

                if status == "failed":
                    print(f"Run failed for {run_id}. Return code: {res.returncode}")
                    print("Stdout:", res.stdout[-500:])
                    print("Stderr:", res.stderr[-500:])

if __name__ == "__main__":
    main()
