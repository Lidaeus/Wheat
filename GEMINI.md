# PEST-MGDA-DSSAT Project Context

## 1. Project Overview
**PEST-MGDA-DSSAT** is an automated multi-objective calibration pipeline for the DSSAT crop model. It evaluates a robust calibration framework across key crops (Wheat, Maize, Soybean, Rice, Cotton). 
The core capability revolves around using the real DSSAT engine paired with optimization strategies to refine crop genetic parameters.

The project focuses on standardizing the calibration protocol into a four-dimensional experimental matrix `W × O × S × G`:
- **`W` (Weighting & Scaling)** & **`G` (Grouping)**: The **Loss Construction Layer**.
- **`S` (Sequential Protocol)** & **`O` (Optimizer)**: The **Solving Execution Layer**.
The primary scientific question is whether `S × G` (protocol structure) is more critical for improving parameter identifiability and reducing negative optimization than simply replacing the optimizer `O`, and whether `W × O` interactions exist.

## 2. Terminology and Notation
- **Main Matrix**: `W × O × S × G`
- **W (Weighting/Scaling)**: `W0` (Raw-Identity), `W4` (Min-Max Equal), `W6` (Log-Transformation), `W8` (DSSAT-PEST Group-Max Scaling, Main Baseline). `W1`, `W7` are for extension layers. `W9` (True Multi-objective) is deprecated as a W-axis and moved to a separate vector-objective extension.
- **O (Optimizer)**: `O1` (pestpp-glm), `O2` (pestpp-ies). `O4` (NSGA-II) and `O5` (MGDA) are for the vector-objective extension layer.
- **S (Sequence)**: `S1` (Naive Joint), `S2` (Sequential Phase - Phenology -> Growth -> Yield). `S3` (Joint refinement after S2) is an extension.
- **G (Grouping)**: `G1` (Flat-All-in-One), `G3` (DSSAT-PEST Extended Grouping).
- **Baselines**: `B0` is the official external baseline (sole anchor for negative optimization). `B1` is for feasibility diagnosis. `B2` is an external benchmark.

## 3. Directory Structure & Separation of Concerns
- **`mvp_pest_mgda/`**: Core capabilities and engine logic (PEST bindings, DSSAT runners). **Do not contaminate this stable core architecture with experimental code unless necessary.**
- **`autoresearch_sandbox/`**: Experimental orchestration, AI-driven exploration, and formal experimentation logic (e.g., `auto_evolve.py`, `eval.py`, `strategy.py`, `phase1_runner.py`, `equifinality_postprocess.py`).
- **`docs/Drafts/`**: Master control for paper writing, experiment design, and hypothesis boundaries.
- **`local_dssat/`**: Local DSSAT run environments and parameters.

## 4. Development Environment
- **Python Environment:** The project is a Python project. Use the virtual environment located at `.venv` or use `uv` for package management.
- **Linters & Type Checkers:** The project uses `ruff` (for linting and formatting) and `mypy` (for type checking). Configuration is in `mvp_pest_mgda/pyproject.toml`.

## 5. Building, Running, and Testing
- **AI Auto-Evolution:** To run a bounded innovation session:
  ```bash
  cd autoresearch_sandbox
  python auto_evolve.py --mode innovate --rounds 2 --beam-width 2 --seed-limit 4
  ```
- **Phase 1 Runner:** Use `phase1_runner.py` for formal experiments with high repetitions (e.g., 5-10+) to build dense behavioral parameter clouds.
- **Postprocessing:** `phase1_postprocess.py` and `equifinality_postprocess.py` (to be developed) handle generating standardized outputs and parameter space metrics.
- **Testing:** The project is building a functional test suite in `mvp_pest_mgda/tests/functional/` to verify W/G/S/O application and post-processing correctly. `mvp_pest_mgda/tests/acceptance/` holds live DSSAT acceptance tests. Ensure these pass.

## 6. Execution Roadmap & Scientific Evidence
The project executes in phased batches:
- **Phase 0:** Executability and baseline (`B0`) verification across all 5 crops.
- **Phase 1 (Core Screening):**
  - **Batch A (G Identification):** `W0/W4 × O1 × S1 × G1` vs `G3`.
  - **Batch B (S Identification):** `W8/W4 × G3 × O1/O2 × S1` vs `S2`.
  - **Batch C (O Identification):** `W8/W4 × G3 × S2 × O1` vs `O2`.
  - **Batch D (W × O Interaction):** `W0/W4/W6/W8 × O1/O2` fixed at `G3 × S2`.

### Equifinality & Scientific Enhancement (WP1-WP4)
To prove `S2` reduces equifinality, the evidence must move beyond just `NRMSE` or `Final_Score`:
1. **High-Density Behavioral Parameter Clouds:** Run high repetitions (e.g., 50+) for fixed `W × G × O` pairs comparing `S1` vs `S2`.
2. **Behavioral Definition:** Filter runs where `status = success`, `better_than_b0 = True`, and `score <= best_score * 1.05`.
3. **Parameter Standardization:** Standardize parameters based on their bounds: `(x - lower) / (upper - lower)` before statistical analysis to avoid scale distortion.
4. **Key Metrics:** Compute `log_det(cov)` (volume), `mean_abs_corr`, `frac_abs_corr_gt_0.8`, `boundary_hit_rate`, and PCA variance explained.
5. **Process Trajectory Consistency:** Compare the trajectory envelopes for intermediate variables (e.g., LAIX, CWAM) to detect "same endpoint, different process" equifinality.
6. **Global Sensitivity Analysis (GSA):** (Optional/Enhancement) Use Sobol indices on the behavioral cloud to prove the primary sensitivity (`S_i`) of key parameters (e.g., phenology) increases in `S2`, decoupling them from noise.

## 7. Data Products & Artifacts (Phase 1)
Ensure fine-grained output is maintained. Key required files in `autoresearch_sandbox/`:
- `eq_run_manifest.json` (Experiment contract)
- `phase1_experiment_summary.tsv` (Run-level summary)
- `phase1_treatment_metrics.tsv` (Treatment-level details)
- `eq_parameter_cloud.tsv` (Behavioral parameter values, raw and standardized)
- `eq_identifiability_summary.tsv` (Parameter space metrics like volume, correlation)
- `eq_process_trajectory.tsv` (Process variable envelopes)

## 8. Development Conventions & Rules
- **Config-First:** Calibration definitions should reside in `json` configs.
- **Commit Messages:** Follow standard conventional commits prefixes: `feat:`, `fix:`, `docs:`, `chore:`.
- **Testing Priorities:** Focus on offline functional tests verifying weight modes (`W`), protocol matrix routing, and the `phase1_postprocess.py` pipeline.
- **Scientific Boundaries:** 
  - Never use `O4` (NSGA-II) front parameters directly for correlation analysis without selecting a specific preference vector first.
  - Do not claim `S2` eliminates equifinality; state it reduces the compensation structure if supported by reduced parameter cloud volume and weaker correlations.