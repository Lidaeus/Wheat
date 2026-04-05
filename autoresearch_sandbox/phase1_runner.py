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

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=str, choices=["Baselines", "BatchA", "BatchB", "BatchC", "BatchD", "All"], default="All", help="Which batch to run")
    parser.add_argument("--repetitions", type=int, default=5, help="Number of repetitions per combination")
    parser.add_argument("--skip-postprocess", action="store_true", help="Skip postprocessing derived metrics")
    args = parser.parse_args()

    print("Starting Phase 1 Execution Roadmap...")
    print(f"Target: {args.batch}, Repetitions: {args.repetitions}")
    
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

    # RUN BASELINES
    if args.batch in ["Baselines", "All"]:
        print("--- Running Baselines (B0, B1, B2) ---")
        for crop_name, config_path in crop_configs.items():
            if not config_path.exists():
                print(f"Skipping baselines for {crop_name}, config not found.")
                continue
                
            baselines = [
                ("B0", "w0_raw_identity", "default_dssat", "s1_naive_joint", "g1_flat_all_in_one"),
                ("B1", "w0_raw_identity", "o1_least_squares", "s1_naive_joint", "g1_flat_all_in_one"),
                ("B2", "w0_raw_identity", "o6_pestpp_glm", "s1_naive_joint", "g1_flat_all_in_one")
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

    # RUN SPECIFIC BATCH
    if args.batch in BATCH_MAP:
        batches_to_run = [args.batch]
    elif args.batch == "All":
        batches_to_run = list(BATCH_MAP.keys())
    else:
        batches_to_run = []

    for batch_name in batches_to_run:
        run_batch(batch_name, BATCH_MAP[batch_name], crop_configs, eval_script, args.repetitions, summary_path)
    
    if not args.skip_postprocess:
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
