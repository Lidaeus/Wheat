import csv
from pathlib import Path
from collections import defaultdict

def main():
    sandbox_dir = Path(__file__).resolve().parent
    summary_path = sandbox_dir / "phase1_experiment_summary.tsv"
    
    if not summary_path.exists():
        print("Summary TSV not found. Please run experiments first.")
        return
        
    runs = []
    with open(summary_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            runs.append(row)
            
    # Find baselines by crop (from workspace_dir or parsing plan)
    b0_scores = {}
    b1_scores = {}
    
    for row in runs:
        plan = row.get("plan", "")
        combo_key = row.get("combo_key", "")
        # Assuming crop can be extracted from workspace_dir, or we just use a global baseline for simplicity
        crop = row.get("workspace_dir", "Unknown") 
        if "B0" in combo_key:
            b0_scores[crop] = float(row.get("score", 999.0))
        if "B1" in combo_key:
            b1_scores[crop] = float(row.get("score", 999.0))
            
    # Load parameters
    param_path = sandbox_dir / "phase1_parameters.tsv"
    run_params = defaultdict(list)
    if param_path.exists():
        with open(param_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for r in reader:
                if len(r) < 10: continue
                run_id, crop, combo, pname, pval, lb, ub, is_lb, is_ub, norm = r
                if pname == "param_name": continue
                run_params[run_id].append({
                    "name": pname, "norm": float(norm),
                    "hit_bound": (is_lb == "True" or is_ub == "True")
                })
                
    # Load aggregates for Group Balance
    agg_path = sandbox_dir / "phase1_aggregate_metrics.tsv"
    run_aggs = defaultdict(list)
    if agg_path.exists():
        with open(agg_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for r in reader:
                run_aggs[r["run_id"]].append(r)

    # Pre-compute B0 params
    b0_params = {}
    for r in runs:
        if "B0" in r.get("combo_key", "") and r.get("run_id") in run_params:
            b0_params[r.get("workspace_dir", "Unknown")] = {p["name"]: p["norm"] for p in run_params[r["run_id"]]}
            
    # Calculate derived metrics
    for row in runs:
        crop = row.get("workspace_dir", "Unknown")
        run_id = row.get("run_id", "")
        
        # Parse score safely
        try:
            score = float(row.get("score", 999.0))
        except ValueError:
            score = 999.0
            
        b0 = b0_scores.get(crop, 999.0)
        b1 = b1_scores.get(crop, 999.0)
        
        row["delta_vs_b0"] = f"{(score - b0):.6f}" if b0 != 999.0 else "0.0"
        row["delta_vs_b1"] = f"{(score - b1):.6f}" if b1 != 999.0 else "0.0"
        
        try:
            train_mean = float(row.get("train_mean_nrmse", "999.0") or 999.0)
            valid_mean = float(row.get("valid_mean_nrmse", "999.0") or 999.0)
            generalization_gap = valid_mean - train_mean if train_mean != 999.0 and valid_mean != 999.0 else 0.0
        except ValueError:
            generalization_gap = 0.0
            
        row["better_than_b0"] = "True" if (b0 != 999.0 and score < b0) else "False"
        row["generalization_gap"] = f"{generalization_gap:.6f}"
        
        # Parameter metrics
        params = run_params.get(run_id, [])
        if params:
            hit_rate = sum(1 for p in params if p["hit_bound"]) / len(params)
            row["boundary_hit_rate"] = f"{hit_rate:.4f}"
            
            # Param shift
            ref_params = b0_params.get(crop, {})
            if ref_params:
                shifts = [abs(p["norm"] - ref_params.get(p["name"], p["norm"])) for p in params]
                row["param_shift_norm"] = f"{(sum(shifts) / len(shifts)):.4f}"
            else:
                row["param_shift_norm"] = "0.0"
        else:
            row["boundary_hit_rate"] = "0.0"
            row["param_shift_norm"] = "0.0"
            
        # Group balance
        aggs = [a for a in run_aggs.get(run_id, []) if a.get("split") == "train"]
        if aggs:
            import statistics
            try:
                nrmses = [float(a.get("nrmse", 0)) for a in aggs]
                row["group_balance_index"] = f"{statistics.stdev(nrmses):.4f}" if len(nrmses) > 1 else "0.0"
            except Exception:
                row["group_balance_index"] = "0.0"
        else:
            row["group_balance_index"] = "0.0"
        
    derived_path = sandbox_dir / "phase1_derived_metrics.tsv"
    if not runs:
        return
        
    fieldnames = list(runs[0].keys())
    for f in ["generalization_gap", "boundary_hit_rate", "param_shift_norm", "group_balance_index"]:
        if f not in fieldnames:
            fieldnames.append(f)
        
    with open(derived_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(runs)
        
    print(f"Derived metrics successfully generated and persisted to {derived_path.name}")

if __name__ == "__main__":
    main()
