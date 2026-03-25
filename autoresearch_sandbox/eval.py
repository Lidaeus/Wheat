import os
import sys
import numpy as np
import subprocess
from pathlib import Path
from scipy.optimize import minimize, dual_annealing
import strategy

# =====================================================================
# Configuration & Setup
# =====================================================================
SANDBOX_DIR = Path(r"c:\DSSAT48\Wheat\autoresearch_sandbox")
PROJECT_CONFIG_PATH = SANDBOX_DIR / "project_wheat.json"
RUN_MODEL_PATH = Path(r"c:\DSSAT48\Wheat\mvp_pest_mgda\src\run_model.py")
PARAMS_PATH = SANDBOX_DIR / "params.dat"
PEST_OUT_PATH = SANDBOX_DIR / "pest_out.dat"

# Mode switch: "weighted" (uses strategy.py), "pure_mgda", "default_dssat", "pest_glm_native", "pest_glm_grouped"
EVAL_MODE = "pure_mgda" 

# True Observation Data from SWSW7501.WHA (Treatments 1, 2, 8, 9, 13, 14)
# -99.0 indicates missing observation
OBS_YIELD = np.array([1617.0, 1578.0, 2754.0, 3792.0, 5425.0, 4883.0])
OBS_LAI = np.array([1.22, 1.61, -99.0, 1.44, 3.23, 3.23])

# Parameter names and initial baseline values
PARAM_NAMES = ["p1v", "p1d", "p5", "g1", "g2", "g3", "phint"]
# INITIAL_GUESS from DSSAT official defaults for IB1500 (Manitou)
INITIAL_GUESS = [9.33, 3.12, 331.4, 12.87, 62.22, 2.215, 86.00]

# Bounds expanded slightly to accommodate the DSSAT defaults and R version bounds
BOUNDS = [
    (5.0, 65.0),     # p1v
    (0.0, 95.0),     # p1d
    (300.0, 999.0),  # p5
    (5.0, 45.0),     # g1
    (30.0, 65.0),    # g2
    (0.5, 2.5),      # g3
    (80.0, 167.0)    # phint
]

# =====================================================================
# Real DSSAT Execution Wrapper
# =====================================================================
def run_dssat_and_get_simulated(params_array):
    """
    Writes parameters, calls the official DSSAT wrapper, and extracts results.
    """
    # 1. Write params.dat
    with open(PARAMS_PATH, "w") as f:
        for name, val in zip(PARAM_NAMES, params_array):
            f.write(f"{name} {val:.3f}\n")
            
    # 2. Run DSSAT using the MVP run_model.py
    env = os.environ.copy()
    env["PROJECT_CONFIG"] = str(PROJECT_CONFIG_PATH)
    env["PARAMS_PATH"] = str(PARAMS_PATH)
    env["DSSAT_KEEP_OUTPUTS"] = "0"
    env["DSSAT_TRTS"] = "1,2,8,9,13,14"
    
    # We use a subprocess call to ensure clean execution just like in production
    cp = subprocess.run(
        [sys.executable, str(RUN_MODEL_PATH)], 
        cwd=str(SANDBOX_DIR), 
        capture_output=True, 
        text=True, 
        env=env
    )
    
    if cp.returncode != 0:
        print("DSSAT Error:", cp.stderr)
        print("DSSAT Stdout:", cp.stdout)
        return None, None
        
    # 3. Parse pest_out.dat
    if not PEST_OUT_PATH.exists():
        print(f"Warning: {PEST_OUT_PATH} not found after run.")
        print("Stdout:", cp.stdout)
        print("Stderr:", cp.stderr)
        return None, None
        
    sim_data = {}
    with open(PEST_OUT_PATH, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                sim_data[parts[0].lower()] = float(parts[1])
                
    # 4. Extract Yield and LAI for the target treatments
    trts = [1, 2, 8, 9, 13, 14]
    try:
        sim_yield = np.array([sim_data[f"hwam_t{t:02d}"] for t in trts])
        sim_lai = np.array([sim_data[f"laix_t{t:02d}"] for t in trts])
        return sim_yield, sim_lai
    except KeyError:
        return None, None

# =====================================================================
# Optimization and Evaluation Logic
# =====================================================================
def objective_function(params_array):
    """
    The function that the optimizer calls. It uses `strategy.py` to calculate Loss.
    """
    sim_yield, sim_lai = run_dssat_and_get_simulated(params_array)
    
    # Penalty for model crash
    if sim_yield is None or sim_lai is None:
        return 1e9
        
    # 1. Missing Value Masking
    mask_yield = OBS_YIELD != -99.0
    mask_lai = OBS_LAI != -99.0
    
    valid_obs_y, valid_sim_y = OBS_YIELD[mask_yield], sim_yield[mask_yield]
    valid_obs_l, valid_sim_l = OBS_LAI[mask_lai], sim_lai[mask_lai]
    
    # 2. Pure MGDA Baseline vs Weighted Strategy
    if EVAL_MODE == "pure_mgda":
        # In a pure MGDA scalarization (simplified here as Min-Max normalized sum without grouping logic)
        # Real MGDA would dynamically solve for pareto gradients, but for derivative-free,
        # we scalarize by normalizing errors so they are on the exact same scale, 
        # avoiding subjective grouping.
        nrmse_y = np.sqrt(np.mean((valid_obs_y - valid_sim_y)**2)) / np.mean(valid_obs_y)
        nrmse_l = np.sqrt(np.mean((valid_obs_l - valid_sim_l)**2)) / np.mean(valid_obs_l)
        base_loss = nrmse_y + nrmse_l
    else:
        try:
            # Call the AI-modified strategy file to get the weighted loss
            # Pass importance_exponent via **kwargs if strategy supports it, else handle it.
            # For backward compatibility with setup.md contract, we pass arrays.
            base_loss = strategy.calculate_loss(valid_sim_y, valid_obs_y, valid_sim_l, valid_obs_l)
        except Exception as e:
            return 1e9 # Return huge penalty on crash

    # 3. Treatment Sensitivity (处理间一致性惩罚)
    # Calculate variance of normalized errors across treatments
    err_y = np.abs(valid_obs_y - valid_sim_y) / valid_obs_y
    err_l = np.abs(valid_obs_l - valid_sim_l) / valid_obs_l
    cross_treatment_variance = np.var(err_y) + np.var(err_l)
    
    # 4. Apply Importance Exponent (if in weighted mode and not handled by strategy natively)
    # If strategy.py is basic, we can apply a post-multiplier based on exponents, 
    # though ideally strategy.py uses IMPORTANCE_EXPONENT directly.
    # Here we just add the cross_treatment_variance as a penalty.
    penalty_weight = 0.1
    total_loss = base_loss + penalty_weight * cross_treatment_variance
        
    if not np.isfinite(total_loss):
        return 1e9
        
    return total_loss

def calculate_true_nrmse(sim_yield, sim_lai):
    """
    The ultimate evaluation metric (Objective Truth).
    Calculates the unweighted Mean NRMSE across Yield and LAI (masked).
    Lower is better.
    """
    mask_y = OBS_YIELD != -99.0
    mask_l = OBS_LAI != -99.0
    
    nrmse_yield = np.sqrt(np.mean((OBS_YIELD[mask_y] - sim_yield[mask_y])**2)) / np.mean(OBS_YIELD[mask_y])
    nrmse_lai = np.sqrt(np.mean((OBS_LAI[mask_l] - sim_lai[mask_l])**2)) / np.mean(OBS_LAI[mask_l])
    
    return (nrmse_yield + nrmse_lai) / 2.0

def main():
    print("Starting Official DSSAT-based Optimization Evaluation...")
    print(f"Current EVAL_MODE: {EVAL_MODE}")
    
    if EVAL_MODE == "default_dssat":
        best_params = INITIAL_GUESS
        print("Running DSSAT Official Default Parameters...")
        res_fun = objective_function(best_params)
        res_success = True
    elif EVAL_MODE in ["pest_glm_native", "pest_glm_grouped"]:
        from scipy.optimize import least_squares
        
        def residuals(params_array):
            sim_yield, sim_lai = run_dssat_and_get_simulated(params_array)
            if sim_yield is None or sim_lai is None:
                return np.full(len(OBS_YIELD) + len(OBS_LAI), 1e9)
                
            mask_y = OBS_YIELD != -99.0
            mask_l = OBS_LAI != -99.0
            
            valid_obs_y, valid_sim_y = OBS_YIELD[mask_y], sim_yield[mask_y]
            valid_obs_l, valid_sim_l = OBS_LAI[mask_l], sim_lai[mask_l]
            
            res_y = valid_sim_y - valid_obs_y
            res_l = valid_sim_l - valid_obs_l
            
            if EVAL_MODE == "pest_glm_grouped":
                # Apply scaling to group them roughly equally (Inverse Mean normalization)
                res_y = res_y / (np.mean(valid_obs_y) + 1e-8)
                res_l = res_l / (np.mean(valid_obs_l) + 1e-8)
                
            return np.concatenate((res_y, res_l))
            
        print("Running PEST-GLM (Levenberg-Marquardt / TRF)...")
        lb = [b[0] for b in BOUNDS]
        ub = [b[1] for b in BOUNDS]
        # PEST generally requires many evaluations
        res = least_squares(residuals, x0=INITIAL_GUESS, bounds=(lb, ub), method='trf', max_nfev=100, diff_step=0.1)
        print(f"Least Squares Status: {res.status}, Message: {res.message}")
        best_params = res.x
        res_fun = res.cost
        res_success = res.success
    else:
        # Run the optimizer (Simulating PEST/MGDA)
        # We use dual_annealing (Simulated Annealing) as a global optimization strategy 
        # Increased maxiter to 15 (from 3) and maxfev to 30 to give strategies a fair chance
        res = dual_annealing(
            objective_function, 
            bounds=BOUNDS,
            x0=INITIAL_GUESS,
            maxiter=5,  # Global search iterations (reduced for faster run)
            minimizer_kwargs={
                "method": "Nelder-Mead", # Local search method
                "options": {"maxiter": 15, "maxfev": 20}
            }
        )
        best_params = res.x
        res_fun = res.fun
        res_success = res.success
    
    final_sim_yield, final_sim_lai = run_dssat_and_get_simulated(best_params)
    
    if final_sim_yield is None:
        print("Final Evaluation Failed.")
        final_score = 999.0
    else:
        final_score = calculate_true_nrmse(final_sim_yield, final_sim_lai)
    
    print(f"Optimization Success: {res_success}")
    print("Final Parameters:")
    for name, val in zip(PARAM_NAMES, best_params):
        print(f"  {name.upper()}: {val:.2f}")
    print(f"Final_Loss_Value: {res_fun:.6f}")
    
    # This is the line that Autoresearch will track
    print(f"Final_Score: {final_score:.6f}")

if __name__ == "__main__":
    main()
