from __future__ import annotations

import csv
import math
import os
import random
import re
import subprocess
import sys
import shutil
import argparse
from typing import TypedDict
from pathlib import Path

import pyemu

from dssat_io import extract_cultivar_code, extract_trts_from_filex, load_project_config, resolve_param_mapping, resolve_crop_family

def _read_kv_params(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    if not path.exists(): return out
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith(("*", "!")): continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                out[parts[0].strip().lower()] = float(parts[1])
            except ValueError: continue
    return out

def _read_obs_weights(work_dir: Path) -> dict[str, float]:
    pst_path = work_dir / "ksas_mvp.pst"
    if not pst_path.exists(): return {}
    try:
        pst = pyemu.Pst(str(pst_path))
        return {str(oname).strip().lower(): float(row.weight) for oname, row in pst.observation_data.iterrows()}
    except: return {}

def _resolve_split(cfg: dict, trts: list[int]) -> dict[int, str]:
    split_cfg = cfg.get("split", {})
    mode = str(split_cfg.get("mode", "trt")).strip().lower()
    if mode in {"none", "all"}: return {int(t): "train" for t in trts}
    # Simplified for tournament: default all to train unless specified
    return {int(t): "train" for t in trts}

class TrtRow(TypedDict):
    scenario: str; trt: int; obs_yield: float; sim_yield: float; obs_laix: float; sim_laix: float;
    phi: float; phi_w: float; n_wht_dates: int; phi_laid: float; n_wht_swad: int

def _calc_summary(rows: list[TrtRow]) -> dict[str, float | int]:
    if not rows: return {"n_trt": 0, "rmse_yield": float("nan"), "rmse_laix": float("nan"), "phi_w": 0.0}
    y_rows = [r for r in rows if math.isfinite(r["obs_yield"]) and math.isfinite(r["sim_yield"])]
    l_rows = [r for r in rows if math.isfinite(r["obs_laix"]) and math.isfinite(r["sim_laix"])]
    
    rmse_y = (sum((r["sim_yield"] - r["obs_yield"])**2 for r in y_rows)/len(y_rows))**0.5 if y_rows else float("nan")
    mae_y = (sum(abs(r["sim_yield"] - r["obs_yield"]) for r in y_rows)/len(y_rows)) if y_rows else float("nan")
    mean_oy = (sum(r["obs_yield"] for r in y_rows)/len(y_rows)) if y_rows else 0.0
    re_y = (mae_y / mean_oy * 100.0) if (y_rows and mean_oy != 0) else float("nan")

    rmse_l = (sum((r["sim_laix"] - r["obs_laix"])**2 for r in l_rows)/len(l_rows))**0.5 if l_rows else float("nan")
    mae_l = (sum(abs(r["sim_laix"] - r["obs_laix"]) for r in l_rows)/len(l_rows)) if l_rows else float("nan")
    mean_ol = (sum(r["obs_laix"] for r in l_rows)/len(l_rows)) if l_rows else 0.0
    re_l = (mae_l / mean_ol * 100.0) if (l_rows and mean_ol != 0) else float("nan")

    return {
        "n_trt": len(rows), "rmse_yield": rmse_y, "re_yield": re_y, "rmse_laix": rmse_l, "re_laix": re_l,
        "phi": sum(r["phi"] for r in rows), "phi_w": sum(r["phi_w"] for r in rows),
        "n_wht": sum(r["n_wht_dates"] for r in rows)
    }

def _run_one(work_dir: Path, run_model_path: Path, dssat_dir: Path, params_path: Path, trts: list[int]) -> dict[str, float]:
    env = os.environ.copy()
    env["PARAMS_PATH"] = str(params_path)
    env["DSSAT_TRTS"] = ",".join(map(str, trts))
    env["DSSAT_KEEP_OUTPUTS"] = "0"
    cp = subprocess.run([sys.executable, str(run_model_path)], cwd=str(work_dir), capture_output=True, text=True, env=env)
    out_p = work_dir / "pest_out.dat"
    return _read_kv_params(out_p) if out_p.exists() else {}

def main() -> None:
    is_tournament = "--tournament" in sys.argv
    work_dir = Path.cwd()
    project_root = Path(__file__).resolve().parents[1]
    cfg = load_project_config(project_root)
    dssat_dir = Path(cfg["paths"]["dssat_case_dir"])
    run_model_path = project_root / "src" / "run_model.py"
    
    trts = [int(t) for t in cfg.get("scenario", {}).get("trts", [1,2,3,4,8,9,10,11])]
    
    param_files = {}
    if is_tournament:
        param_files = {
            "baseline": Path(os.environ.get("TOURNAMENT_BASELINE", project_root / "work" / "params.dat")),
            "pest": Path(os.environ.get("TOURNAMENT_PEST", project_root / "results" / "final_pest_params.dat")),
            "mgda": Path(os.environ.get("TOURNAMENT_MGDA", project_root / "results" / "final_mgda_params.dat"))
        }
    else:
        param_files = {
            "baseline": work_dir / "params_baseline.dat",
            "pest": work_dir / "ksas_mvp_est.par",
            "mgda": work_dir / "params_mgda.dat"
        }

    sim_results = {}
    for scen, pfile in param_files.items():
        if not pfile.exists(): continue
        scen_dir = work_dir / scen
        scen_dir.mkdir(exist_ok=True)
        p_dat = scen_dir / "params.dat"
        if pfile.suffix == ".par":
            lines = pfile.read_text().splitlines()
            kv = []
            for l in lines:
                parts = l.strip().split()
                if not parts: continue
                # DEBUG: Trace the parsing process
                if parts[0].startswith("!"): continue
                if parts[0].lower() in {"single", "point", "parameter"}: continue
                
                if len(parts) >= 2:
                    try: 
                        val = float(parts[1])
                        kv.append(f"{parts[0].lower()} {val}")
                    except ValueError:
                        print(f"DEBUG: Skipping unparseable line in {pfile}: {l}")
                        continue
            p_dat.write_text("\n".join(kv) + "\n")
        else:
            shutil.copy(pfile, p_dat)
        sim_results[scen] = _run_one(scen_dir, run_model_path, dssat_dir, p_dat, trts)

    yield_var, laix_var = cfg.get("metrics", {}).get("yield_var", "HWAM"), cfg.get("metrics", {}).get("laix_var", "LAIX")
    a_path = dssat_dir / cfg["paths"]["wha_path"]
    wht_path = dssat_dir / cfg["paths"]["wht_path"]
    
    # Obs data loading
    def _read_a(p, ts, yv, lv):
        if not p.exists(): return {}
        lines = p.read_text().splitlines()
        h = next((l for l in lines if l.startswith("@TRNO")), None)
        if not h: return {}
        cols = [c.lstrip("@").upper() for c in h.split()]
        i_trno, i_y = cols.index("TRNO"), cols.index(yv.upper())
        i_l = cols.index(lv.upper()) if lv.upper() in cols else -1
        out = {}
        for l in lines:
            if not l.strip() or l.startswith(("@", "*", "!")): continue
            parts = l.split()
            if len(parts) <= max(i_trno, i_y, i_l): continue
            try:
                trno = int(parts[i_trno])
            except ValueError: continue # Skip comment or malformed rows
            if trno in ts:
                out[f"{yv.lower()}_t{trno:02d}"] = float(parts[i_y])
                if i_l >= 0: out[f"{lv.lower()}_t{trno:02d}"] = float(parts[i_l])
        return out

    meas = _read_a(a_path, trts, yield_var, laix_var)
    
    # Simplified WHT loading
    wht_dates = {}
    if wht_path.exists():
        lines = wht_path.read_text().splitlines()
        h = next((l for l in lines if l.startswith("@TRNO")), None)
        if h:
            cols = [c.lstrip("@").upper() for c in h.split()]
            i_trno, i_date, i_laid = cols.index("TRNO"), cols.index("DATE"), cols.index("LAID")
            for l in lines:
                if not l.strip() or l.startswith(("@", "*", "!")): continue
                parts = l.split()
                try:
                    trno, date = int(parts[i_trno]), int(parts[i_date])
                except (ValueError, IndexError): continue # Skip comments or incomplete rows
                if trno in trts:
                    wht_dates.setdefault(trno, []).append(date)
                    meas[f"laid_t{trno:02d}_d{date}"] = float(parts[i_laid])

    rows = []
    weights = _read_obs_weights(work_dir)
    for scen, sim in sim_results.items():
        if not sim: continue
        for trt in trts:
            yk, lk = f"{yield_var.lower()}_t{trt:02d}", f"{laix_var.lower()}_t{trt:02d}"
            oy, sy = meas.get(yk, float("nan")), sim.get(yk, float("nan"))
            ol, sl = meas.get(lk, float("nan")), sim.get(lk, float("nan"))
            wy, wl = weights.get(yk, 1.0), weights.get(lk, 1.0)
            p_y = ((sy-oy)*wy)**2 if math.isfinite(sy-oy) else 0.0
            p_l = ((sl-ol)*wl)**2 if math.isfinite(sl-ol) else 0.0
            p_ts, p_w_ts, n_ts = 0.0, 0.0, 0
            for d in wht_dates.get(trt, []):
                mk = f"laid_t{trt:02d}_d{d}"
                if mk in sim and mk in meas:
                    e = sim[mk] - meas[mk]
                    w = weights.get(mk, 1.0)
                    p_ts += e*e; p_w_ts += (e*w)**2; n_ts += 1
            rows.append({
                "scenario": scen, "trt": trt, "obs_yield": oy, "sim_yield": sy, "obs_laix": ol, "sim_laix": sl,
                "phi": (sy-oy)**2 + (sl-ol)**2 + p_ts if math.isfinite(sy-oy) else p_ts,
                "phi_w": p_y + p_l + p_w_ts, "n_wht_dates": n_ts, "phi_laid": p_ts, "n_wht_swad": 0
            })

    summary_rows = []
    for scen in sim_results.keys():
        scen_rows = [r for r in rows if r["scenario"] == scen]
        if not scen_rows: continue
        sum_row = _calc_summary(scen_rows)
        sum_row["scenario"] = scen
        summary_rows.append(sum_row)

    if summary_rows:
        summary_path = work_dir / "compare_summary.csv"
        with summary_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=summary_rows[0].keys())
            writer.writeheader()
            writer.writerows(summary_rows)
        print(f"Results saved to {summary_path}")

if __name__ == "__main__":
    main()
