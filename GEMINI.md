# GEMINI.md - PEST-MGDA-DSSAT Project Context

## Project Overview
**PEST-MGDA-DSSAT** is an automated multi-objective calibration pipeline for the DSSAT crop model (currently focused on Wheat). It aims to find optimal parameter sets that balance multiple observation goals (e.g., Yield, LAI, Phenology) by combining PEST++'s sensitivity analysis with the Multiple Gradient Descent Algorithm (MGDA).

- **Core Technology Stack:** 
  - **Model:** DSSAT (Decision Support System for Agrotechnology Transfer) v4.8.
  - **Optimization Engine:** PEST++ (specifically `pestpp-glm`) for Jacobian and residual generation.
  - **Algorithm:** MGDA (Multiple Gradient Descent Algorithm) for finding common descent directions across multiple objectives.
  - **Orchestration:** PowerShell scripts (`.ps1`) for workflow management and Python (`src/*.py`) for model adapters and optimization logic.

## Directory Structure
- `docs/`: Comprehensive technical documentation, experimental plans, and user manuals.
- `mvp_pest_mgda/`: The core implementation directory.
  - `src/`: Python source code for the calibration lifecycle.
    - `build_pest_setup.py`: Generates PEST control files (`.pst`), templates (`.tpl`), and instructions (`.ins`).
    - `run_model.py`: Adapter to run DSSAT and extract simulated values.
    - `mgda_update.py`: Computes the common descent direction and updates parameters.
    - `compare_three.py`: Comparative analysis of baseline vs. PEST vs. MGDA results.
  - `config/`: JSON configuration files defining scenarios, parameters, and observation groups.
  - `scripts/`: Entry point scripts (e.g., `run_mvp.ps1`).
  - `vendor/`: Bundled binaries for PEST++.
  - `runs/`: Output directory for "Run Ledgers" (traceable iteration artifacts).

## Key Workflows & Commands

### Running a Calibration
The main entry point is the `run_mvp.ps1` script. It handles batch processing, multi-start initialization, and iterative optimization.

```powershell
# Run the MVP calibration with default project config
cd mvp_pest_mgda
.\scripts\run_mvp.ps1
```

### Environment Configuration
The system relies on several environment variables for fine-tuning, though defaults are provided:
- `PROJECT_CONFIG`: Path to the project JSON (default: `config/project.json`).
- `MGDA_MAX_ITER`: Maximum number of optimization iterations (default: 15).
- `PESTPP_GLM`: Path to the `pestpp-glm` executable.
- `BATCH_PROJECT_CONFIGS`: List of configurations for batch runs.

## Development Conventions
- **Traceability:** Every iteration is stored in a timestamped folder under `runs/_runs/<stamp>/iter_xxx/`. Each folder contains a `meta.json` with the iteration's state.
- **Modular Adapters:** Any changes to how DSSAT is run should be made in `src/run_model.py`.
- **Config-First:** Scenarios, parameters, and observation groups should be defined in JSON configs within `mvp_pest_mgda/config/` rather than hardcoded in Python.
- **Commit Messages:** Follow the convention: `feat:`, `fix:`, `refactor:`, `chore:`.

## Technical Integrity Standards
- **Validation:** Every parameter update must be verified against DSSAT's fixed-width formatting requirements.
- **Regression:** A "Gold Standard" case (minimal TRT/FileX) should be used to verify that new changes don't break the end-to-end loop.
- **Error Handling:** Errors in DSSAT or PEST++ execution must be captured and logged in the iteration's `meta.json` with appropriate error codes (e.g., `E_RUN_DSSAT`, `E_PESTPP`).


