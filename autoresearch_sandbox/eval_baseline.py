import sys
import os
from pathlib import Path
import numpy as np
import subprocess

# Reuse paths and settings from eval.py
SANDBOX_DIR = Path(r"c:\DSSAT48\Wheat\autoresearch_sandbox")
sys.path.append(str(SANDBOX_DIR))

import eval

def run_default_baseline():
    print("Evaluating Official DSSAT Default Parameters...")
    
    # Default parameters for IB1500 MANITOU from WHCER048.CUL
    # P1V, P1D, P5, G1, G2, G3, PHINT
    default_params = [9.330, 3.12, 331.4, 12.87, 62.22, 2.215, 86.00]
    
    sim_yield, sim_lai = eval.run_dssat_and_get_simulated(default_params)
    
    if sim_yield is None:
        print("Failed to run DSSAT with default parameters.")
        return
        
    print(f"Sim Yield: {sim_yield}")
    print(f"Sim LAI: {sim_lai}")
    
    score = eval.calculate_true_nrmse(sim_yield, sim_lai)
    print(f"Default Parameters Final Score (True NRMSE): {score:.6f}")

if __name__ == "__main__":
    run_default_baseline()
