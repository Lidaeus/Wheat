from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from typing import cast

import pyemu

import compare_eval
from crop_registry import resolve_parameter_priority
from pest_runner import (
    read_pst_observation_weights,
    resolve_compare_param_files,
    run_compare_model,
    run_compare_scenarios,
)
from dssat_io import load_project_config, resolve_crop_family
from result_schema import build_compare_summary_fieldnames

TrtRow = compare_eval.TrtRow
_calc_summary = compare_eval.calc_summary
build_summary_rows = compare_eval.build_summary_rows
build_trt_rows = compare_eval.build_trt_rows
load_measurements = compare_eval.load_measurements

def _read_obs_weights(work_dir: Path) -> dict[str, float]:
    pst_path = work_dir / "ksas_mvp.pst"
    return read_pst_observation_weights(pyemu, pst_path)

def _resolve_family_param_keys(cfg: dict, dssat_dir: Path, keys: list[str]) -> list[str]:
    family = resolve_crop_family(cfg, dssat_dir)
    normalized = [str(key).strip().lower() for key in keys if str(key).strip()]
    priority = list(resolve_parameter_priority(family))
    ordered = [key for key in priority if key in normalized]
    remainder = [key for key in normalized if key not in ordered]
    return ordered + remainder

def _run_one(work_dir: Path, _dssat_dir: Path, params_path: Path, trts: list[int]) -> dict[str, float]:
    return run_compare_model(
        work_dir=work_dir,
        params_path=params_path,
        trts=trts,
        keep_outputs=False,
        failure_label="compare_three run_model.py",
    )


def main() -> None:
    is_tournament = "--tournament" in sys.argv
    is_progress = "--progress" in sys.argv

    work_dir = Path.cwd()
    project_root = Path(__file__).resolve().parents[1]
    cfg = load_project_config(project_root, crop=os.environ.get("PROJECT_CROP", ""))
    dssat_dir = Path(cfg["paths"]["dssat_case_dir"])

    trts = [int(t) for t in cfg.get("scenario", {}).get("trts", [1,2,3,4,8,9,10,11])]

    mode = "tournament" if is_tournament else "progress" if is_progress else "standard"
    param_files = resolve_compare_param_files(mode, work_dir, project_root, env=cast(dict[str, str], dict(os.environ)))
    if mode == "progress":
        mgda_p = param_files["mgda"]
        print(f">>> Progress Mode: Evaluating {mgda_p.name} only <<<")

    def run_selected_scenario(_: str, scen_dir: Path, params_path: Path) -> dict[str, float]:
        return _run_one(scen_dir, dssat_dir, params_path, trts)

    sim_results = run_compare_scenarios(param_files, work_dir, run_selected_scenario)

    yield_var = cfg.get("metrics", {}).get("yield_var", "HWAM")
    laix_var = cfg.get("metrics", {}).get("laix_var", "LAIX")
    a_path = dssat_dir / cfg["paths"]["wha_path"]
    wht_path = dssat_dir / cfg["paths"]["wht_path"]

    meas, wht_dates = load_measurements(a_path, wht_path, trts, yield_var, laix_var)
    weights = _read_obs_weights(work_dir)
    rows = build_trt_rows(sim_results, meas, weights, trts, yield_var, laix_var, wht_dates)
    summary_rows = build_summary_rows(list(sim_results.keys()), rows)

    if summary_rows:
        summary_path = work_dir / "compare_summary.csv"
        with summary_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=build_compare_summary_fieldnames(summary_rows))
            writer.writeheader()
            writer.writerows(summary_rows)
        print(f"Results saved to {summary_path}")


if __name__ == "__main__":
    main()
