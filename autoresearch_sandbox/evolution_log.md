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

