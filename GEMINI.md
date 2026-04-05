# GEMINI.md - PEST-MGDA-DSSAT Project Context

## Project Overview
**PEST-MGDA-DSSAT** is an automated multi-objective calibration pipeline for the DSSAT crop model, currently evaluating a 4-dimensional robust calibration framework across five key crops (Wheat, Maize, Soybean, Rice, and Cotton). The primary goal of the current **Phase 1 Experiment** is not simply to find the single "best" calibration score, but to systematically quantify the importance of the *Calibration Protocol Structure* vs. the *Optimization Engine*.

We investigate an experimental matrix of:
- **W (Weighting):** e.g., W0, W4, W6, W8
- **O (Optimizer/Engine):** e.g., O1 (MGDA Hybrid), O2 (Global+Local Reference)
- **S (Protocol Sequence):** e.g., S1, S2
- **G (Grouping Strategies):** e.g., G1, G3

## Repository Guidelines & Rules
1. **Separation of Concerns:** 
   - Core capabilities and engine logic reside in `mvp_pest_mgda/`.
   - Experimental orchestration, AI-driven exploration, and **Phase 1 formal experimentation** logic should remain contained within `autoresearch_sandbox/` to prevent contamination of the stable core architecture unless necessary.
2. **Execution Environment:** Please use the virtual environment located at `mvp_pest_mgda/.venv` or `uv` to manage the local environment footprint consistently.
3. **Traceability:** Fine-grained output is mandatory. The architecture currently mandates recording structured outcomes (e.g., `phase1_experiment_summary.tsv`, `phase1_aggregate_metrics.tsv`, `phase1_treatment_metrics.tsv`). Ensure variables such as parameter hit rates, parameter shift, and structural vs. yield degradation are always recorded.

## Phase 1 Execution Roadmap
Phase 1 uses a layered confirmation architecture:
- **Batch A:** `G` Grouping Identification (W0/W4 x O1 x S1 x G1/G3)
- **Batch B:** `S` Sequence Identification (W8/W4 x O1/O2 x G3 x S1/S2)
- **Batch C:** `O` Optimizer Identification (W8/W4 x G3 x S2 x O1/O2)
- **Batch D:** Full Matrix Comparison & `W x O` Interactions.
Repeats are crucial: Ensure adequate repetitions to prove model stability (e.g., O1 ≥ 2 times, O2 ≥ 5 times).

## Formal Results Processing
A successful Phase 1 protocol must report:
1. Primary Valid Score and Negative Optimization Rate (vs B0 baseline).
2. Rank Stability and Cross-Crop consistency.
3. Trade-offs (Generalization Gap, Group Error Balance, Boundary Parameter Hit Rate).
Direct comparisons of un-standardized loss values across structurally distinct engines must be resolved with **Unified Re-evaluation**.

## Development Conventions
- **Config-First:** Calibration definitions should reside in `json` configs.
- **Commit Messages:** Follow standard prefixes: `feat:`, `fix:`, `docs:`, `chore:`.
- **Gold Standard Test:** Retain simpler baselines (`B0`, `B1`, `B2`) ensuring protocol evaluations remain anchored to well-tested references.
