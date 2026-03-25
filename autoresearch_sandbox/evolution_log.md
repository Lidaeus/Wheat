# Autoresearch Evolution Log

## Session Started at 2026-03-25 06:21:04

### Strategy: 1_Inverse_Variance
**Score:** 0.428645
```python
import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    var_yield = np.var(obs_yield) if np.var(obs_yield) > 0 else 1.0
    var_lai = np.var(obs_lai) if np.var(obs_lai) > 0 else 1.0
    
    loss_yield = np.mean((sim_yield - obs_yield)**2) / var_yield
    loss_lai = np.mean((sim_lai - obs_lai)**2) / var_lai
    
    return loss_yield + loss_lai

```
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: weighted
Optimization Success: True
Final Parameters:
  P1V: 43.28
  P1D: 14.33
  P5: 398.21
  G1: 6.28
  G2: 60.57
  G3: 2.46
  PHINT: 122.43
Final_Loss_Value: 2.010142
Final_Score: 0.428645

```
</details>

### Strategy: 2_Inverse_RMSE
**Score:** 0.383508
```python
import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    rmse_yield_base = np.sqrt(np.mean(obs_yield**2)) + 1e-8
    rmse_lai_base = np.sqrt(np.mean(obs_lai**2)) + 1e-8
    
    rmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2))
    rmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2))
    
    return (rmse_y / rmse_yield_base) + (rmse_l / rmse_lai_base)

```
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: weighted
Optimization Success: True
Final Parameters:
  P1V: 34.91
  P1D: 65.45
  P5: 408.38
  G1: 8.32
  G2: 52.19
  G3: 2.18
  PHINT: 88.43
Final_Loss_Value: 0.708944
Final_Score: 0.383508

```
</details>

### Strategy: 3_CV_based_R_version
**Score:** 1.089177
```python
import numpy as np

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

```
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: weighted
Optimization Success: True
Final Parameters:
  P1V: 38.30
  P1D: 57.36
  P5: 889.36
  G1: 14.50
  G2: 49.34
  G3: 1.66
  PHINT: 103.01
Final_Loss_Value: -0.000000
Final_Score: 1.089177

```
</details>

### Strategy: 4_Min_Max_Normalization
**Score:** 0.504086
```python
import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    err_y = np.abs(sim_yield - obs_yield)
    err_l = np.abs(sim_lai - obs_lai)
    
    max_err_y = np.max(obs_yield) + 1e-8
    max_err_l = np.max(obs_lai) + 1e-8
    
    norm_y = np.mean(err_y / max_err_y)
    norm_l = np.mean(err_l / max_err_l)
    
    return norm_y + norm_l

```
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: weighted
Optimization Success: True
Final Parameters:
  P1V: 6.88
  P1D: 44.93
  P5: 446.49
  G1: 32.57
  G2: 48.33
  G3: 1.80
  PHINT: 121.67
Final_Loss_Value: 0.519223
Final_Score: 0.504086

```
</details>

### Strategy: 5_Mean_Normalization_NRMSE
**Score:** 0.32027
```python
import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    nrmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2)) / (np.mean(obs_yield) + 1e-8)
    nrmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2)) / (np.mean(obs_lai) + 1e-8)
    return nrmse_y + nrmse_l

```
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: weighted
Optimization Success: True
Final Parameters:
  P1V: 61.75
  P1D: 7.49
  P5: 515.52
  G1: 19.44
  G2: 64.81
  G3: 2.01
  PHINT: 91.96
Final_Loss_Value: 0.643187
Final_Score: 0.320270

```
</details>

### Strategy: 6_Log_transformation
**Score:** 0.314199
```python
import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    log_sim_y = np.log(np.clip(sim_yield, 1e-8, None))
    log_obs_y = np.log(np.clip(obs_yield, 1e-8, None))
    
    log_sim_l = np.log(np.clip(sim_lai, 1e-8, None))
    log_obs_l = np.log(np.clip(obs_lai, 1e-8, None))
    
    loss_y = np.mean((log_sim_y - log_obs_y)**2)
    loss_l = np.mean((log_sim_l - log_obs_l)**2)
    
    return loss_y + loss_l

```
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: weighted
Optimization Success: True
Final Parameters:
  P1V: 44.63
  P1D: 39.27
  P5: 572.03
  G1: 28.92
  G2: 63.55
  G3: 1.20
  PHINT: 85.72
Final_Loss_Value: 0.212381
Final_Score: 0.314199

```
</details>

### Strategy: 7_Equal_Contribution
**Score:** 0.544377
```python
import numpy as np

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

```
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: weighted
Optimization Success: True
Final Parameters:
  P1V: 28.09
  P1D: 20.42
  P5: 862.42
  G1: 19.89
  G2: 30.69
  G3: 1.52
  PHINT: 86.02
Final_Loss_Value: 0.001583
Final_Score: 0.544377

```
</details>

### Strategy: 8_AgMIP_Two_step_WLS
**Score:** 0.659128
```python
import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    # Step 1: pseudo-variances
    var_y = np.var(sim_yield - obs_yield) + 1e-8
    var_l = np.var(sim_lai - obs_lai) + 1e-8
    
    # Step 2: WLS
    loss_y = np.mean((sim_yield - obs_yield)**2) / var_y
    loss_l = np.mean((sim_lai - obs_lai)**2) / var_l
    
    return loss_y + loss_l

```
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: weighted
Optimization Success: True
Final Parameters:
  P1V: 12.75
  P1D: 30.77
  P5: 527.84
  G1: 37.29
  G2: 45.88
  G3: 1.92
  PHINT: 107.17
Final_Loss_Value: 3.472284
Final_Score: 0.659128

```
</details>

### Strategy: 9_Pareto_Dominance
**Score:** 0.547266
```python
import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    nrmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2)) / (np.mean(obs_yield) + 1e-8)
    nrmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2)) / (np.mean(obs_lai) + 1e-8)
    
    # Scalarize pareto logic: distance to origin (0,0) + penalty for imbalance
    distance = np.sqrt(nrmse_y**2 + nrmse_l**2)
    imbalance = np.abs(nrmse_y - nrmse_l)
    
    return distance + 0.5 * imbalance

```
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: weighted
Optimization Success: True
Final Parameters:
  P1V: 9.43
  P1D: 2.89
  P5: 346.38
  G1: 14.67
  G2: 63.35
  G3: 2.06
  PHINT: 86.40
Final_Loss_Value: 0.834525
Final_Score: 0.547266

```
</details>

### Strategy: Pure_MGDA_Baseline
**Score:** 0.319164
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: pure_mgda
Optimization Success: True
Final Parameters:
  P1V: 16.29
  P1D: 67.29
  P5: 388.16
  G1: 19.91
  G2: 55.45
  G3: 0.85
  PHINT: 87.36
Final_Loss_Value: 0.650011
Final_Score: 0.319164

```
</details>

### Strategy: DSSAT_Default_Params
**Score:** 0.587981
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: default_dssat
Running DSSAT Official Default Parameters...
Optimization Success: True
Final Parameters:
  P1V: 9.33
  P1D: 3.12
  P5: 331.40
  G1: 12.87
  G2: 62.22
  G3: 2.21
  PHINT: 86.00
Final_Loss_Value: 1.104841
Final_Score: 0.587981

```
</details>

### Strategy: Native_PEST_GLM
**Score:** 0.383784
<details><summary>Output</summary>

```
Starting Official DSSAT-based Optimization Evaluation...
Current EVAL_MODE: pest_glm_native
Running PEST-GLM (Levenberg-Marquardt / TRF)...
Least Squares Status: 3, Message: `xtol` termination condition is satisfied.
Optimization Success: True
Final Parameters:
  P1V: 8.16
  P1D: 49.85
  P5: 449.66
  G1: 18.56
  G2: 62.71
  G3: 2.21
  PHINT: 82.98
Final_Loss_Value: 1968796.174950
Final_Score: 0.383784

```
</details>

