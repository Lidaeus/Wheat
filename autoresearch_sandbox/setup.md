# Autoresearch Setup for DSSAT Parameter Calibration

## 1. Project Objective
We are optimizing crop genetic parameters for the DSSAT (Decision Support System for Agrotechnology Transfer) agricultural model. Our goal is to discover the best **mathematical weighting scheme** (Loss Function) to balance multiple conflicting observation metrics (e.g., Yield vs. LAI) across different experimental treatments.

## 2. Your Task as an AI Researcher
Your task is to iteratively modify the `strategy.py` file. This file must contain a single function `calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai)` that takes in numpy arrays of simulated and observed data, applies a specific weighting strategy, and returns a single scalar loss value to be minimized.

You should systematically explore the 9 advanced weighting schemes provided below.

## 3. Data Interface (`strategy.py` contract)
You must strictly adhere to this function signature in `strategy.py`:

```python
import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    \"\"\"
    Calculate the combined loss for Yield and LAI.
    
    Args:
        sim_yield (np.ndarray): Simulated Yield values.
        obs_yield (np.ndarray): Observed Yield values.
        sim_lai (np.ndarray): Simulated Leaf Area Index (LAI) values.
        obs_lai (np.ndarray): Observed Leaf Area Index (LAI) values.
        
    Returns:
        float: A single scalar loss value. (Lower is better)
    \"\"\"
    # YOUR WEIGHTING STRATEGY LOGIC HERE
    pass
```

## 4. The 9 Weighting Schemes to Explore
Please generate code for these strategies one by one in your iterations:

1.  **Inverse Variance Weighting**: Weight = 1 / Variance(obs).
2.  **Inverse RMSE Weighting**: Weight = 1 / Baseline_RMSE.
3.  **CV-based Weighting (The R-version approach)**: 
    - Compute fitness: `fitness = exp(-(sim - obs)^2 / (2 * (0.5 * obs)^2))`
    - Apply user exponent penalty: `fitness_yield = fitness ^ 1`, `fitness_lai = fitness ^ 10`
    - Total loss = `-prod(fitness_yield) * prod(fitness_lai)` (minimize negative fitness)
4.  **Min-Max Normalization Weighting**: Map all errors to [0, 1] bounds.
5.  **Mean Normalization Weighting (NRMSE)**: Divide RMSE by the mean of the observations.
6.  **Log-transformation Weighting**: Loss = (log(sim) - log(obs))^2. Good for large scale differences.
7.  **Equal Contribution Dynamic Balance**: Dynamically adjust weights during iteration so `Weight_yield * Loss_yield == Weight_lai * Loss_lai`.
8.  **AgMIP Two-step WLS**: Step 1 calculates unweighted variances, Step 2 uses them as weights.
9.  **Pareto Dominance (Scalarized)**: Convert multi-objective pareto logic into a penalty-based scalar loss.

## 5. Constraints
- Only modify `strategy.py`.
- Do not modify `eval.py` or `eval_fast.py`.
- Use `numpy` for all array operations.
- Ensure the function never returns NaN or Infinity (add small epsilons `1e-8` to denominators if necessary).
- You will be evaluated based on the `Final_Score` printed by the evaluation script.

## 6. Indicator Grouping & Sequencing Guidelines (Future Architecture)
Based on crop modeling principles (e.g., AgMIP and standard DSSAT protocols) and the metric types defined in `ParameterOutput.csv`, metrics should be handled logically rather than just dumping them into a single mathematical formula.

### A. Metric Grouping
Metrics should be clustered into three functional groups. This prevents scale dominance and allows assigning group-level weights:
1.  **Phenology (物候):** `ADAP` (Anthesis Date), `MDAP` (Maturity Date). Unit: Days.
2.  **Growth/Canopy (生长/冠层):** `LAIX` (Max LAI), `CWAM` (Tops weight at maturity/Biomass). Unit: Index or kg/ha.
3.  **Yield (产量):** `HWAM` (Grain yield), `HWUM` (Unit weight). Unit: kg/ha or g/unit.

### B. Sequential Calibration (先物候、后生长、最后产量) & Autoresearch Role
Instead of optimizing all 7 parameters simultaneously (which creates high dimensionality and equifinality/异物同效 issues), a sequential pipeline is recommended. **Autoresearch's primary value is to explore and evaluate different weighting schemes across these phases**, not just in a final fine-tuning step.
- **Phase 1 (Phenology):** Fix G1, G2, G3. Optimize `P1V`, `P1D`, `P5`, `PHINT` using ONLY `ADAP` and `MDAP` loss.
- **Phase 2 (Growth):** Freeze phenology parameters. Optimize `G1` (or canopy parameters) using ONLY `LAIX` and `CWAM` loss.
- **Phase 3 (Yield):** Freeze phenology and growth. Optimize `G2`, `G3` using ONLY `HWAM` and `HWUM` loss.

### C. Pure MGDA Scheme (Baseline Comparison)
In addition to testing the grouped weighting schemes above, you must also design a **Pure MGDA (Multiple Gradient Descent Algorithm)** scheme.
- This scheme should **not** group observation indicators (i.e., it optimizes Yield and LAI directly together without artificial clustering).
- Its purpose is to serve as a pure mathematical baseline to compare against the grouped strategies.

### D. Real-World Robustness (Checklist)
- **Treatment Sensitivity (处理间一致性):** Ensure loss functions penalize high variance in errors across treatments. A parameter set that performs perfectly in a well-watered treatment but terribly in a drought treatment is worse than one that performs reasonably well in both.
- **Zero or Missing Observations:** Metrics like `LAI` might not be observed in all treatments (represented as `-99.0` in DSSAT files). The evaluation logic safely masks missing data, but your weighting schemes should not divide by zero if an array is empty.
- **Crop-Specific Exponents:** We have reserved an `importance_exponent` field in the crop JSON configuration. Agricultural experts use this to subjectively bias the optimization (e.g., Yield ^ 10, LAI ^ 1). Your weighting scheme should be able to accept these exponent parameters to tilt the loss landscape according to expert knowledge.