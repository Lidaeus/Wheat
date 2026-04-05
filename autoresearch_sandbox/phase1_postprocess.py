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
            
    # Calculate derived metrics
    for row in runs:
        crop = row.get("workspace_dir", "Unknown")
        
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
            generalization_gap = valid_mean - train_mean
        except ValueError:
            generalization_gap = 0.0
            
        row["better_than_b0"] = "True" if (b0 != 999.0 and score < b0) else "False"
        row["generalization_gap"] = f"{generalization_gap:.6f}"
        
    derived_path = sandbox_dir / "phase1_derived_metrics.tsv"
    if not runs:
        return
        
    fieldnames = list(runs[0].keys())
    if "generalization_gap" not in fieldnames:
        fieldnames.append("generalization_gap")
        
    with open(derived_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(runs)
        
    print(f"Derived metrics successfully generated and persisted to {derived_path.name}")

if __name__ == "__main__":
    main()
