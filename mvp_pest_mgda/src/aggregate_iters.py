import pandas as pd
import os
import glob
from pathlib import Path

def aggregate_results(base_path):
    iter_dirs = sorted(glob.glob(os.path.join(base_path, "iter_*")))
    all_data = []
    
    for iter_dir in iter_dirs:
        iter_name = os.path.basename(iter_dir)
        csv_path = os.path.join(iter_dir, "compare_summary.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            df['iteration'] = iter_name
            all_data.append(df)
            
    if not all_data:
        print("No results found.")
        return
        
    combined = pd.concat(all_data, ignore_index=True)
    # Sort by iteration and scenario
    combined = combined.sort_values(['iteration', 'scenario'])
    
    output_path = os.path.join(base_path, "aggregated_compare_summary.csv")
    combined.to_csv(output_path, index=False)
    print(f"Aggregated results saved to {output_path}")
    
    # Display key metrics for summary
    rmse_y_col = 'rmse_yield' if 'rmse_yield' in combined.columns else 'rmse_hwam'
    r2_y_col = 'r2_yield' if 'r2_yield' in combined.columns else 'r2_hwam'
    summary = combined[['iteration', 'scenario', 'phi_w', 'train_phi_w', 'valid_phi_w', rmse_y_col, r2_y_col]]
    print("\nSummary of Key Metrics:")
    print(summary.to_string(index=False))

if __name__ == "__main__":
    # Find the latest run directory
    project_root = Path(__file__).resolve().parents[1]
    runs_dir = (project_root / "runs" / "_runs").resolve()
    if not runs_dir.exists():
        runs_dir = (project_root.parent / "autoresearch_sandbox" / "runs" / "_runs").resolve()
    subdirs = [os.path.join(str(runs_dir), d) for d in os.listdir(runs_dir) if os.path.isdir(os.path.join(runs_dir, d))] if runs_dir.exists() else []
    if not subdirs:
        print("No run directories found.")
    else:
        latest_run = max(subdirs, key=os.path.getmtime)
        print(f"Analyzing latest run: {latest_run}")
        aggregate_results(latest_run)
