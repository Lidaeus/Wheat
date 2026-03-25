import os
import subprocess
import time
from pathlib import Path

SANDBOX_DIR = Path(r"c:\DSSAT48\Wheat\autoresearch_sandbox")
STRATEGY_PATH = SANDBOX_DIR / "strategy.py"
EVAL_PATH = SANDBOX_DIR / "eval.py"
LOG_PATH = SANDBOX_DIR / "evolution_log.md"

# Define the 9 strategies
STRATEGIES = {
    "1_Inverse_Variance": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    var_yield = np.var(obs_yield) if np.var(obs_yield) > 0 else 1.0
    var_lai = np.var(obs_lai) if np.var(obs_lai) > 0 else 1.0
    
    loss_yield = np.mean((sim_yield - obs_yield)**2) / var_yield
    loss_lai = np.mean((sim_lai - obs_lai)**2) / var_lai
    
    return loss_yield + loss_lai
""",

    "2_Inverse_RMSE": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    rmse_yield_base = np.sqrt(np.mean(obs_yield**2)) + 1e-8
    rmse_lai_base = np.sqrt(np.mean(obs_lai**2)) + 1e-8
    
    rmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2))
    rmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2))
    
    return (rmse_y / rmse_yield_base) + (rmse_l / rmse_lai_base)
""",

    "3_CV_based_R_version": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    # fitness = exp(-(sim - obs)^2 / (2 * (0.5 * obs)^2))
    sigma_y = 0.5 * obs_yield + 1e-8
    fitness_y = np.exp(-((sim_yield - obs_yield)**2) / (2 * sigma_y**2))
    
    sigma_l = 0.5 * obs_lai + 1e-8
    fitness_l = np.exp(-((sim_lai - obs_lai)**2) / (2 * sigma_l**2))
    
    # Exponents from IMPORTANCE_EXPONENT: yield=10, lai=1
    fit_y_penalized = fitness_y ** 10.0
    fit_l_penalized = fitness_l ** 1.0
    
    # minimize negative fitness
    total_loss = - (np.prod(fit_y_penalized) * np.prod(fit_l_penalized))
    return total_loss
""",

    "4_Min_Max_Normalization": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    err_y = np.abs(sim_yield - obs_yield)
    err_l = np.abs(sim_lai - obs_lai)
    
    max_err_y = np.max(obs_yield) + 1e-8
    max_err_l = np.max(obs_lai) + 1e-8
    
    norm_y = np.mean(err_y / max_err_y)
    norm_l = np.mean(err_l / max_err_l)
    
    return norm_y + norm_l
""",

    "5_Mean_Normalization_NRMSE": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    nrmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2)) / (np.mean(obs_yield) + 1e-8)
    nrmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2)) / (np.mean(obs_lai) + 1e-8)
    return nrmse_y + nrmse_l
""",

    "6_Log_transformation": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    log_sim_y = np.log(np.clip(sim_yield, 1e-8, None))
    log_obs_y = np.log(np.clip(obs_yield, 1e-8, None))
    
    log_sim_l = np.log(np.clip(sim_lai, 1e-8, None))
    log_obs_l = np.log(np.clip(obs_lai, 1e-8, None))
    
    loss_y = np.mean((log_sim_y - log_obs_y)**2)
    loss_l = np.mean((log_sim_l - log_obs_l)**2)
    
    return loss_y + loss_l
""",

    "7_Equal_Contribution": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    loss_y = np.mean((sim_yield - obs_yield)**2)
    loss_l = np.mean((sim_lai - obs_lai)**2)
    
    # Dynamically balance by multiplying each by the inverse of the other's loss to equalize gradients roughly
    weight_y = 1.0 / (loss_y + 1e-8)
    weight_l = 1.0 / (loss_l + 1e-8)
    
    # Normalize weights
    sum_w = weight_y + weight_l
    weight_y /= sum_w
    weight_l /= sum_w
    
    return weight_y * loss_y + weight_l * loss_l
""",

    "8_AgMIP_Two_step_WLS": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    # Step 1: pseudo-variances
    var_y = np.var(sim_yield - obs_yield) + 1e-8
    var_l = np.var(sim_lai - obs_lai) + 1e-8
    
    # Step 2: WLS
    loss_y = np.mean((sim_yield - obs_yield)**2) / var_y
    loss_l = np.mean((sim_lai - obs_lai)**2) / var_l
    
    return loss_y + loss_l
""",

    "9_Pareto_Dominance": """import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    nrmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2)) / (np.mean(obs_yield) + 1e-8)
    nrmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2)) / (np.mean(obs_lai) + 1e-8)
    
    # Scalarize pareto logic: distance to origin (0,0) + penalty for imbalance
    distance = np.sqrt(nrmse_y**2 + nrmse_l**2)
    imbalance = np.abs(nrmse_y - nrmse_l)
    
    return distance + 0.5 * imbalance
"""
}

def run_git_command(cmd):
    subprocess.run(cmd, cwd=r"c:\DSSAT48\Wheat", shell=True, capture_output=True)

def write_log(content):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(content + "\n")

def run_eval():
    result = subprocess.run(["python", str(EVAL_PATH)], cwd=str(SANDBOX_DIR), capture_output=True, text=True)
    out = result.stdout
    score = None
    for line in out.splitlines():
        if "Final_Score:" in line:
            try:
                score = float(line.split(":")[-1].strip())
            except:
                pass
    return out, score

def main():
    if not LOG_PATH.exists():
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write("# Autoresearch Evolution Log\n\n")

    write_log(f"## Session Started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 1. Run the 9 Weighting Schemes
    for name, code in STRATEGIES.items():
        print(f"Running strategy: {name}...")
        
        # Write strategy
        with open(STRATEGY_PATH, "w", encoding="utf-8") as f:
            f.write(code)
            
        # Ensure EVAL_MODE is "weighted"
        with open(EVAL_PATH, "r", encoding="utf-8") as f:
            eval_code = f.read()
        import re
        eval_code = re.sub(r'EVAL_MODE = ".*?"', 'EVAL_MODE = "weighted"', eval_code)
        with open(EVAL_PATH, "w", encoding="utf-8") as f:
            f.write(eval_code)

        # Run eval
        out, score = run_eval()
        
        # Log
        write_log(f"### Strategy: {name}")
        write_log(f"**Score:** {score}")
        write_log(f"```python\n{code}\n```")
        write_log(f"<details><summary>Output</summary>\n\n```\n{out}\n```\n</details>\n")
        
        # Git commit
        run_git_command("git add .")
        run_git_command(f'git commit -m "Autoresearch: Evaluate Strategy {name}"')

    # 2. Run Other Baselines and PEST-GLM strategies
    additional_modes = {
        "Pure_MGDA_Baseline": "pure_mgda",
        "DSSAT_Default_Params": "default_dssat",
        "Native_PEST_GLM": "pest_glm_native",
        "Grouped_PEST_GLM": "pest_glm_grouped"
    }

    for mode_name, mode_val in additional_modes.items():
        print(f"Running {mode_name}...")
        with open(EVAL_PATH, "r", encoding="utf-8") as f:
            eval_code = f.read()
            
        # Regex or simple replace for EVAL_MODE
        # Since it might have been left as "weighted" from the loop
        import re
        eval_code_mod = re.sub(r'EVAL_MODE = ".*?"', f'EVAL_MODE = "{mode_val}"', eval_code)
        
        with open(EVAL_PATH, "w", encoding="utf-8") as f:
            f.write(eval_code_mod)
            
        out, score = run_eval()
        
        write_log(f"### Strategy: {mode_name}")
        write_log(f"**Score:** {score}")
        write_log(f"<details><summary>Output</summary>\n\n```\n{out}\n```\n</details>\n")
        
        # Git commit
        run_git_command("git add .")
        run_git_command(f'git commit -m "Autoresearch: Evaluate {mode_name}"')

    # Restore EVAL_PATH
    with open(EVAL_PATH, "w", encoding="utf-8") as f:
        f.write(eval_code)
    
    print("Evolution complete. Log written to evolution_log.md")

if __name__ == "__main__":
    main()
