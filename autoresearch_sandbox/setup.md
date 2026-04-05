# Autoresearch Setup for DSSAT Parameter Calibration

## 1. Project Objective
We are optimizing DSSAT crop genetic parameters with the real DSSAT engine. The current focus is no longer limited to replaying a fixed list of human-written weighting schemes. The new goal is to let an autonomous research loop invent, test, reject, and refine new `strategy.py` loss functions under strict scientific and engineering constraints.

## 2. Current Granularity
This project is now operating at the **AI self-innovation** level.

The loop should:
1. Start from a valid existing `strategy.py`
2. Generate new candidate loss functions
3. Enforce safety and interface constraints
4. Evaluate every candidate with the official DSSAT-based `eval.py`
5. Keep only candidates that improve `Final_Score`
6. Restore the current best strategy after every failed trial

## 3. Editable Surface
The scientific search surface is intentionally narrow:
- `strategy.py` is the evolving hypothesis
- `eval.py` is the read-mostly measurement harness
- `auto_evolve.py` is the autonomous scientist and experiment manager

The loop must treat `eval.py` as the metric oracle and must not change the meaning of `Final_Score`.

## 4. `strategy.py` Contract
Every candidate must define exactly one valid loss function:

```python
import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    return float(...)
```

Requirements:
- Input arrays are already masked for missing observations by `eval.py`
- Output must be a single finite scalar
- Only `numpy` may be imported
- No file I/O, subprocess, randomness, hidden state, global caches, or environment access
- The function must remain deterministic for the same inputs

## 5. Scientific Boundary Conditions
The autonomous search must stay inside these agronomic and numerical boundaries:

### A. Scale fairness
Yield and LAI live on very different numerical scales. Candidate losses must explicitly or implicitly correct that imbalance through normalization, transformation, robust percentage-style errors, or balanced scalarization.

### B. Treatment consistency
A candidate that fits one treatment very well and fails badly on another is scientifically weaker than a candidate with slightly worse mean fit but stronger cross-treatment consistency.

### C. Smoothness for noisy Fortran models
Loss surfaces should remain stable enough for derivative-free search. Avoid highly discontinuous or numerically flat formulations that cause DSSAT calibration to stall.

### D. Respect the real engine
All conclusions must come from real DSSAT runs. No surrogate model, no fake evaluator, no replacement of the official simulation step.

## 6. Innovation Directions
The autonomous loop should search for useful combinations of the following building blocks:
- Error transforms: NRMSE, relative absolute error, SMAPE, log-domain RMSE, Huber-style relative error
- Aggregation rules: additive, L2 distance, mixed mean-max
- Balance control: penalties on metric imbalance
- Robustness control: penalties on treatment-to-treatment error variance
- Cross-metric coupling: light penalties that discourage solving one metric by sacrificing the other

The target is not mathematical novelty for its own sake. The target is a lower `Final_Score` with interpretable behavior.

## 7. What Success Looks Like
An acceptable autonomous innovation run should produce:
- A reproducible evaluation log in `evolution_log.md`
- A final `strategy.py` that is the best-performing candidate discovered in the run
- A clear comparison against the user-provided starting strategy

## 8. Execution Command
Use:

```bash
python auto_evolve.py --mode innovate --rounds 2 --beam-width 2 --seed-limit 4
```

This performs a bounded innovation session with elite selection, mutation, DSSAT evaluation, and automatic keep/discard behavior.

## 9. Round 4 Campaign Profile
The current campaign is **Round 4: attribution-first controlled innovation**.

Round 4 must keep the following boundaries fixed:
- `B0` remains the only negative-optimization reference
- `B1` is diagnostic only
- `B2` remains an external benchmark and is not counted as sandbox-native innovation
- The editable scientific surface remains centered on `strategy.py`
- `eval.py` remains the metric oracle and must keep the meaning of `Final_Score`

Round 4 should compare the evolving native strategy against:
- `B0 Official Frozen`
- `Current_Strategy_Baseline`
- `W4_Min_Max_Equal`
- `W6_Log_Transformation`
- `W8_DSSAT_PEST_Group_Max`

Round 4 reporting should not stop at `Final_Score`. It should also inspect:
- `Final_Valid_Score`
- `TRAIN/VALID/ALL_MEAN_NRMSE`
- Yield-fit diagnostics such as `VALID_HWAM_NRMSE` and `VALID_HWAM_BIAS`
- Whether a candidate is negative optimization relative to `B0`

Round 4 success is defined as:
- A lower or competitive `Final_Score`
- No deterioration serious enough to invalidate validation behavior
- No clear worsening of overall NRMSE or yield-fit diagnostics
- Clear attribution that the gain comes from sandbox-native loss design rather than borrowed external strategy contracts
