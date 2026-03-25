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

