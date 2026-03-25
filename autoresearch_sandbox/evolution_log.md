# Autoresearch Evolution Log

## Session Started at 2026-03-25 05:29:20

### Strategy: 1_Inverse_Variance
**Score:** 0.506532
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
Optimization Success: True
Final Parameters:
  P1V: 32.10
  P1D: 7.26
  P5: 600.27
  G1: 8.38
  G2: 42.85
  G3: 1.01
  PHINT: 125.07
Final_Loss_Value: 2.760407
Final_Score: 0.506532

```
</details>

### Strategy: 2_Inverse_RMSE
**Score:** 0.301632
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
Optimization Success: True
Final Parameters:
  P1V: 26.23
  P1D: 51.30
  P5: 588.40
  G1: 18.48
  G2: 39.67
  G3: 0.82
  PHINT: 123.04
Final_Loss_Value: 0.561942
Final_Score: 0.301632

```
</details>

### Strategy: 3_CV_based_R_version
**Score:** 0.544377
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
Optimization Success: True
Final Parameters:
  P1V: 30.00
  P1D: 50.00
  P5: 700.00
  G1: 15.00
  G2: 45.00
  G3: 1.20
  PHINT: 120.00
Final_Loss_Value: 0.000023
Final_Score: 0.544377

```
</details>

### Strategy: 4_Min_Max_Normalization
**Score:** 0.544377
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
Optimization Success: True
Final Parameters:
  P1V: 30.00
  P1D: 50.00
  P5: 700.00
  G1: 15.00
  G2: 45.00
  G3: 1.20
  PHINT: 120.00
Final_Loss_Value: 0.610930
Final_Score: 0.544377

```
</details>

### Strategy: 5_Mean_Normalization_NRMSE
**Score:** 0.544377
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
Optimization Success: True
Final Parameters:
  P1V: 30.00
  P1D: 50.00
  P5: 700.00
  G1: 15.00
  G2: 45.00
  G3: 1.20
  PHINT: 120.00
Final_Loss_Value: 1.088777
Final_Score: 0.544377

```
</details>

### Strategy: 6_Log_transformation
**Score:** 0.42187
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
Optimization Success: True
Final Parameters:
  P1V: 13.57
  P1D: 84.15
  P5: 638.55
  G1: 15.82
  G2: 46.47
  G3: 1.47
  PHINT: 166.79
Final_Loss_Value: 0.440325
Final_Score: 0.421870

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
Optimization Success: True
Final Parameters:
  P1V: 30.00
  P1D: 50.00
  P5: 700.00
  G1: 15.00
  G2: 45.00
  G3: 1.20
  PHINT: 120.00
Final_Loss_Value: 0.001583
Final_Score: 0.544377

```
</details>

### Strategy: 8_AgMIP_Two_step_WLS
**Score:** 0.486574
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
Optimization Success: True
Final Parameters:
  P1V: 47.96
  P1D: 10.04
  P5: 593.84
  G1: 28.44
  G2: 57.40
  G3: 1.07
  PHINT: 121.70
Final_Loss_Value: 3.695875
Final_Score: 0.486574

```
</details>

### Strategy: 9_Pareto_Dominance
**Score:** 0.636959
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
Optimization Success: True
Final Parameters:
  P1V: 31.06
  P1D: 46.03
  P5: 556.76
  G1: 5.59
  G2: 36.02
  G3: 1.12
  PHINT: 99.68
Final_Loss_Value: 1.119381
Final_Score: 0.636959

```
</details>

