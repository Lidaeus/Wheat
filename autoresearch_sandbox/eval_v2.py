import os
import sys
import numpy as np
import subprocess
from pathlib import Path
from scipy.optimize import least_squares, dual_annealing
import time

# =====================================================================
# Configuration & Setup
# =====================================================================
SANDBOX_DIR = Path(r"c:\DSSAT48\Wheat\autoresearch_sandbox")
PROJECT_CONFIG_PATH = SANDBOX_DIR / "project_wheat.json"
RUN_MODEL_PATH = Path(r"c:\DSSAT48\Wheat\mvp_pest_mgda\src\run_model.py")
PARAMS_PATH = SANDBOX_DIR / "params.dat"
PEST_OUT_PATH = SANDBOX_DIR / "pest_out.dat"

# True Observation Data
OBS_YIELD = np.array([1617.0, 1578.0, 2754.0, 3792.0, 5425.0, 4883.0])
OBS_LAI = np.array([1.22, 1.61, -99.0, 1.44, 3.23, 3.23])

# Expert weights
IMPORTANCE_EXPONENT = {
    "yield": 10.0,
    "lai": 1.0
}

# Parameter names
PARAM_NAMES = ["p1v", "p1d", "p5", "g1", "g2", "g3", "phint"]

# Start from Official Default MANITOU parameters (to avoid local optima of bad initial guess)
INITIAL_GUESS = [9.330, 3.12, 331.4, 12.87, 62.22, 2.215, 86.00]

# Expanded Bounds to cover the default parameters and allow realistic variation
BOUNDS_LIST = [
    (5.0, 60.0),     # p1v
    (0.0, 95.0),     # p1d
    (300.0, 999.0),  # p5
    (5.0, 30.0),     # g1
    (30.0, 80.0),    # g2
    (0.5, 5.0),      # g3
    (60.0, 167.0)    # phint
]
LOWER_BOUNDS = [b[0] for b in BOUNDS_LIST]
UPPER_BOUNDS = [b[1] for b in BOUNDS_LIST]

def run_dssat_and_get_simulated(params_array):
    with open(PARAMS_PATH, "w") as f:
        for name, val in zip(PARAM_NAMES, params_array):
            f.write(f"{name} {val:.3f}\n")
            
    env = os.environ.copy()
    env["PROJECT_CONFIG"] = str(PROJECT_CONFIG_PATH)
    env["PARAMS_PATH"] = str(PARAMS_PATH)
    env["DSSAT_KEEP_OUTPUTS"] = "0"
    env["DSSAT_TRTS"] = "1,2,8,9,13,14"
    
    cp = subprocess.run(
        [sys.executable, str(RUN_MODEL_PATH)], 
        cwd=str(SANDBOX_DIR), capture_output=True, text=True, env=env
    )
    
    if cp.returncode != 0 or not PEST_OUT_PATH.exists():
        return None, None
        
    sim_data = {}
    with open(PEST_OUT_PATH, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                sim_data[parts[0].lower()] = float(parts[1])
                
    trts = [1, 2, 8, 9, 13, 14]
    try:
        sim_yield = np.array([sim_data[f"hwam_t{t:02d}"] for t in trts])
        sim_lai = np.array([sim_data[f"laix_t{t:02d}"] for t in trts])
        return sim_yield, sim_lai
    except KeyError:
        return None, None

def calculate_true_nrmse(sim_yield, sim_lai):
    mask_y = OBS_YIELD != -99.0
    mask_l = OBS_LAI != -99.0
    nrmse_y = np.sqrt(np.mean((OBS_YIELD[mask_y] - sim_yield[mask_y])**2)) / np.mean(OBS_YIELD[mask_y])
    nrmse_l = np.sqrt(np.mean((OBS_LAI[mask_l] - sim_lai[mask_l])**2)) / np.mean(OBS_LAI[mask_l])
    return (nrmse_y + nrmse_l) / 2.0

def pest_glm_residuals(params_array, use_groups=False):
    sim_yield, sim_lai = run_dssat_and_get_simulated(params_array)
    
    if sim_yield is None:
        return np.ones(10) * 1e6 # 5 valid yield + 5 valid lai = 10 residuals
        
    mask_y = OBS_YIELD != -99.0
    mask_l = OBS_LAI != -99.0
    
    valid_obs_y, valid_sim_y = OBS_YIELD[mask_y], sim_yield[mask_y]
    valid_obs_l, valid_sim_l = OBS_LAI[mask_l], sim_lai[mask_l]
    
    # Native PEST uses observation weights (typically 1/observation to normalize)
    res_y = (valid_obs_y - valid_sim_y) / np.mean(valid_obs_y)
    res_l = (valid_obs_l - valid_sim_l) / np.mean(valid_obs_l)
    
    if use_groups:
        # Grouped PEST applies importance exponents
        # least_squares squares the residuals, so we multiply by sqrt(weight)
        res_y *= np.sqrt(IMPORTANCE_EXPONENT["yield"])
        res_l *= np.sqrt(IMPORTANCE_EXPONENT["lai"])
        
    return np.concatenate([res_y, res_l])

def run_strategy(name, use_groups):
    print(f"\n--- Running {name} ---")
    start_time = time.time()
    
    # Run PEST-GLM (Levenberg-Marquardt equivalent via least_squares with bounds -> uses trf)
    # TRF (Trust Region Reflective) is robust for bounded non-linear least squares
    res = least_squares(
        pest_glm_residuals,
        INITIAL_GUESS,
        bounds=(LOWER_BOUNDS, UPPER_BOUNDS),
        args=(use_groups,),
        method='trf',
        max_nfev=50 # Increased evaluation budget for proper convergence
    )
    
    sim_yield, sim_lai = run_dssat_and_get_simulated(res.x)
    score = calculate_true_nrmse(sim_yield, sim_lai)
    
    print(f"Optimization Success: {res.success}")
    print(f"Final Score (True NRMSE): {score:.6f}")
    print("Final Parameters:")
    for n, v in zip(PARAM_NAMES, res.x):
        print(f"  {n.upper()}: {v:.3f}")
    print(f"Elapsed Time: {time.time() - start_time:.1f}s")
    return score

if __name__ == "__main__":
    print("Evaluating Baseline Default...")
    y, l = run_dssat_and_get_simulated(INITIAL_GUESS)
    base_score = calculate_true_nrmse(y, l)
    print(f"Default Parameters Score: {base_score:.6f}")

    run_strategy("Native PEST-GLM (No Group Weights)", use_groups=False)
    run_strategy("Grouped PEST-GLM (With Expert Weights)", use_groups=True)
