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

