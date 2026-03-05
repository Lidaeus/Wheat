from __future__ import annotations

import csv
import math
import os
import random
import re
import subprocess
import sys
from typing import TypedDict
from pathlib import Path

import pyemu

from dssat_io import extract_cultivar_code, extract_trts_from_filex, load_project_config, resolve_param_mapping, resolve_crop_family

def _read_kv_params(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            out[parts[0].strip().lower()] = float(parts[1])
        except ValueError:
            continue
    return out

def _resolve_family_param_keys(cfg: dict, dssat_dir: Path, keys: list[str]) -> list[str]:
    family = resolve_crop_family(cfg, dssat_dir)
    kset = [str(k).strip().lower() for k in keys if str(k).strip()]
    kset_u = sorted(set(kset))
    ordered: list[str] = []
    preferred: list[str] = []
    f = family.lower()
    if ("sunflower" in f) or f.startswith("sunflower"):
        preferred = ["ppsen", "sfdur", "slavr", "wtpsd", "xfrt", "sh2o_15", "sh2o_30"]
    elif ("wheat" in f) or ("ceres" in f) or f.startswith("wh"):
        preferred = ["sh2o_15", "sh2o_30", "p1v", "p1d", "p5", "phint", "g1", "g2", "g3"]
    elif ("sugarcane" in f) or ("sugar" in f):
        preferred = ["sh2o_15", "sh2o_30", "maxparce", "stkpfmax", "suca"]
    for k in preferred:
        if k not in ordered:
            ordered.append(k)
    for k in kset_u:
        if k not in ordered:
            ordered.append(k)
    return ordered


def _read_obs_weights(work_dir: Path) -> dict[str, float]:
    pst_path = work_dir / "ksas_mvp.pst"
    if not pst_path.exists():
        return {}
    pst = pyemu.Pst(str(pst_path))
    w: dict[str, float] = {}
    for oname, row in pst.observation_data.iterrows():
        try:
            w[str(oname).strip().lower()] = float(row.weight)
        except Exception:
            continue
    return w


def _load_project_config(project_root: Path) -> dict:
    return load_project_config(project_root)


def _resolve_group_and_weight(name: str, cfg: dict) -> tuple[str | None, float | None]:
    cfg_obs = cfg.get("observations", {})
    group_defs = cfg_obs.get("groups", {})
    name_l = str(name).strip().lower()
    for gname, gspec in group_defs.items():
        pats = [str(p).lower() for p in (gspec.get("patterns") or [])]
        if any(name_l.startswith(p) for p in pats):
            return str(gname), float(gspec.get("weight", 1.0))
    return None, None


def _resolve_split(cfg: dict, trts: list[int]) -> dict[int, str]:
    split_cfg = cfg.get("split", {})
    mode = str(split_cfg.get("mode", "trt")).strip().lower()
    all_trts = [int(t) for t in trts]

    # mode='none' or 'all' → every TRT is training, no validation
    if mode in {"none", "all"}:
        return {int(t): "train" for t in all_trts}

    train = {int(t) for t in (split_cfg.get("train_trts") or []) if str(t).strip()}
    valid = {int(t) for t in (split_cfg.get("valid_trts") or []) if str(t).strip()}

    ratio = None
    if "valid_ratio" in split_cfg:
        try:
            ratio = float(split_cfg.get("valid_ratio"))
        except (TypeError, ValueError):
            ratio = None

    if mode in {"ratio", "random"} and ratio is None:
        ratio = 0.2

    if ratio is not None and not train and not valid and all_trts:
        ratio = max(0.0, min(1.0, float(ratio)))
        if ratio > 0.0:
            seed = split_cfg.get("seed", split_cfg.get("random_seed", 0))
            rnd = random.Random(int(seed))
            shuffled = list(all_trts)
            rnd.shuffle(shuffled)
            n_valid = max(1, int(round(len(shuffled) * ratio)))
            valid = set(shuffled[:n_valid])
            train = set(shuffled[n_valid:])

    if not train and not valid:
        train = set(all_trts)
    else:
        if not train:
            train = set(all_trts) - set(valid)
        if not valid:
            valid = set(all_trts) - set(train)

    overlap = set(train) & set(valid)
    if overlap:
        train = set(train) - overlap

    split_by_trt: dict[int, str] = {}
    for trt in all_trts:
        split_by_trt[int(trt)] = "valid" if int(trt) in valid else "train"
    return split_by_trt


class TrtRow(TypedDict):
    scenario: str
    trt: int
    split: str
    obs_yield: float
    sim_yield: float
    err_yield: float
    obs_laix: float
    sim_laix: float
    err_laix: float
    n_wht_dates: int
    n_wht_lwad: int
    n_wht_swad: int
    phi_yield: float
    phi_laix: float
    phi_laid: float
    phi_lwad: float
    phi_swad: float
    phi: float
    phi_w: float


def _calc_summary(rows: list[TrtRow]) -> dict[str, float | int]:
    if not rows:
        return {
            "n_trt": 0,
            "n_wht": 0,
            "n_wht_swad": 0,
            "rmse_yield": float("nan"),
            "rrmse_yield": float("nan"),
            "mae_yield": float("nan"),
            "r2_yield": float("nan"),
            "nse_yield": float("nan"),
            "nrmse_mean_yield": float("nan"),
            "nrmse_range_yield": float("nan"),
            "dindex_yield": float("nan"),
            "rmse_laix": float("nan"),
            "rrmse_laix": float("nan"),
            "mae_laix": float("nan"),
            "r2_laix": float("nan"),
            "nse_laix": float("nan"),
            "nrmse_mean_laix": float("nan"),
            "nrmse_range_laix": float("nan"),
            "dindex_laix": float("nan"),
            "rmse_laid": float("nan"),
            "rmse_lwad": float("nan"),
            "rmse_swad": float("nan"),
            "bias_yield": float("nan"),
            "bias_laix": float("nan"),
            "phi": float("nan"),
            "phi_w": float("nan"),
        }
    y_rows = [
        r
        for r in rows
        if math.isfinite(float(r["obs_yield"]))
        and math.isfinite(float(r["sim_yield"]))
        and math.isfinite(float(r["err_yield"]))
    ]
    l_rows = [
        r
        for r in rows
        if math.isfinite(float(r["obs_laix"]))
        and math.isfinite(float(r["sim_laix"]))
        and math.isfinite(float(r["err_laix"]))
    ]

    n_y = len(y_rows)
    errs_y = [float(r["err_yield"]) for r in y_rows]
    obs_y = [float(r["obs_yield"]) for r in y_rows]
    sim_y = [float(r["sim_yield"]) for r in y_rows]
    rmse_y = (sum((e ** 2) for e in errs_y) / n_y) ** 0.5 if n_y > 0 else float("nan")
    bias_y = (sum(errs_y) / n_y) if n_y > 0 else float("nan")
    mae_y = (sum(abs(e) for e in errs_y) / n_y) if n_y > 0 else float("nan")
    mean_obs_y = (sum(obs_y) / n_y) if n_y > 0 else float("nan")
    range_obs_y = (max(obs_y) - min(obs_y)) if n_y > 0 else float("nan")
    sst_y = sum((oy - mean_obs_y) ** 2 for oy in obs_y) if n_y > 0 and math.isfinite(mean_obs_y) else 0.0
    ssr_y = sum((e ** 2) for e in errs_y) if n_y > 0 else 0.0
    r2_y = 1.0 - (ssr_y / sst_y) if sst_y > 0.0 else float("nan")
    std_y = math.sqrt(sst_y / n_y) if sst_y > 0.0 else float("nan")
    rrmse_y = (rmse_y / std_y) if (math.isfinite(rmse_y) and math.isfinite(std_y) and std_y > 0.0) else float("nan")
    nrmse_mean_y = (rmse_y / mean_obs_y) if (math.isfinite(rmse_y) and math.isfinite(mean_obs_y) and mean_obs_y != 0.0) else float("nan")
    nrmse_range_y = (rmse_y / range_obs_y) if (math.isfinite(rmse_y) and math.isfinite(range_obs_y) and range_obs_y > 0.0) else float("nan")
    denom_y = (
        sum((abs(s - mean_obs_y) + abs(o - mean_obs_y)) ** 2 for s, o in zip(sim_y, obs_y))
        if n_y > 0 and math.isfinite(mean_obs_y)
        else 0.0
    )
    dindex_y = 1.0 - (ssr_y / denom_y) if denom_y > 0.0 else float("nan")

    n_l = len(l_rows)
    errs_l = [float(r["err_laix"]) for r in l_rows]
    obs_l = [float(r["obs_laix"]) for r in l_rows]
    sim_l = [float(r["sim_laix"]) for r in l_rows]
    rmse_l = (sum((e ** 2) for e in errs_l) / n_l) ** 0.5 if n_l > 0 else float("nan")
    bias_l = (sum(errs_l) / n_l) if n_l > 0 else float("nan")
    mae_l = (sum(abs(e) for e in errs_l) / n_l) if n_l > 0 else float("nan")
    mean_obs_l = (sum(obs_l) / n_l) if n_l > 0 else float("nan")
    range_obs_l = (max(obs_l) - min(obs_l)) if n_l > 0 else float("nan")
    sst_l = sum((ol - mean_obs_l) ** 2 for ol in obs_l) if n_l > 0 and math.isfinite(mean_obs_l) else 0.0
    ssr_l = sum((e ** 2) for e in errs_l) if n_l > 0 else 0.0
    r2_l = 1.0 - (ssr_l / sst_l) if sst_l > 0.0 else float("nan")
    std_l = math.sqrt(sst_l / n_l) if sst_l > 0.0 else float("nan")
    rrmse_l = (rmse_l / std_l) if (math.isfinite(rmse_l) and math.isfinite(std_l) and std_l > 0.0) else float("nan")
    nrmse_mean_l = (rmse_l / mean_obs_l) if (math.isfinite(rmse_l) and math.isfinite(mean_obs_l) and mean_obs_l != 0.0) else float("nan")
    nrmse_range_l = (rmse_l / range_obs_l) if (math.isfinite(rmse_l) and math.isfinite(range_obs_l) and range_obs_l > 0.0) else float("nan")
    denom_l = (
        sum((abs(s - mean_obs_l) + abs(o - mean_obs_l)) ** 2 for s, o in zip(sim_l, obs_l))
        if n_l > 0 and math.isfinite(mean_obs_l)
        else 0.0
    )
    dindex_l = 1.0 - (ssr_l / denom_l) if denom_l > 0.0 else float("nan")
    nse_y = (1.0 - ssr_y / sst_y) if sst_y > 0.0 else float("nan")
    nse_l = (1.0 - ssr_l / sst_l) if sst_l > 0.0 else float("nan")
    n_wht = sum(r["n_wht_dates"] for r in rows)
    n_wht_lwad = sum(r["n_wht_lwad"] for r in rows)
    n_wht_swad = sum(r["n_wht_swad"] for r in rows)
    rmse_laid = (sum(r["phi_laid"] for r in rows) / n_wht) ** 0.5 if n_wht > 0 else float("nan")
    rmse_lwad = (sum(r["phi_lwad"] for r in rows) / n_wht_lwad) ** 0.5 if n_wht_lwad > 0 else float("nan")
    rmse_swad = (sum(r["phi_swad"] for r in rows) / n_wht_swad) ** 0.5 if n_wht_swad > 0 else float("nan")
    phi = sum(r["phi"] for r in rows)
    phi_w = sum(r["phi_w"] for r in rows)
    return {
        "n_trt": len(rows),
        "n_wht": n_wht,
        "n_wht_lwad": n_wht_lwad,
        "n_wht_swad": n_wht_swad,
        "rmse_yield": rmse_y,
        "rrmse_yield": rrmse_y,
        "mae_yield": mae_y,
        "r2_yield": r2_y,
        "nse_yield": nse_y,
        "nrmse_mean_yield": nrmse_mean_y,
        "nrmse_range_yield": nrmse_range_y,
        "dindex_yield": dindex_y,
        "rmse_laix": rmse_l,
        "rrmse_laix": rrmse_l,
        "mae_laix": mae_l,
        "r2_laix": r2_l,
        "nse_laix": nse_l,
        "nrmse_mean_laix": nrmse_mean_l,
        "nrmse_range_laix": nrmse_range_l,
        "dindex_laix": dindex_l,
        "rmse_laid": rmse_laid,
        "rmse_lwad": rmse_lwad,
        "rmse_swad": rmse_swad,
        "bias_yield": bias_y,
        "bias_laix": bias_l,
        "phi": phi,
        "phi_w": phi_w,
    }


def _read_cul_params(cul_path: Path, cultivar_code: str, cols: list[str]) -> dict[str, float]:
    want = {str(c).strip().upper() for c in cols if str(c).strip()}
    if not want:
        return {}
    header_cols: list[str] | None = None
    for raw in cul_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        if stripped.startswith("@"):
            header_cols = [c.lstrip("@").strip().upper() for c in stripped.split()]
            continue
        if stripped.startswith("*"):
            header_cols = None
            continue
        if not line.startswith(cultivar_code):
            continue
        if not header_cols:
            raise RuntimeError(f"Missing header before cultivar row {cultivar_code} in {cul_path}")
        parts = line.split()
        if len(parts) != len(header_cols):
            n_tail = len(header_cols) - 4
            if n_tail > 0 and len(parts) >= (1 + n_tail + 2):
                var_num = parts[0]
                tail = parts[-n_tail:]
                mid = parts[1:-n_tail]
                if len(mid) >= 2:
                    expno = mid[-2]
                    eco = mid[-1]
                    var_name = " ".join(mid[:-2]) if len(mid) > 2 else mid[0]
                    fixed_parts = [var_num, var_name, expno, eco] + tail
                    if len(fixed_parts) != len(header_cols):
                        raise RuntimeError(f"Unexpected cultivar row format for {cultivar_code} in {cul_path}: {line}")
                    parts = fixed_parts
                else:
                    raise RuntimeError(f"Unexpected cultivar row format for {cultivar_code} in {cul_path}: {line}")
            else:
                raise RuntimeError(f"Unexpected cultivar row format for {cultivar_code} in {cul_path}: {line}")
        row = {k: v for k, v in zip(header_cols, parts)}
        out: dict[str, float] = {}
        for k in want:
            if k not in row:
                raise RuntimeError(f"Missing CUL column {k} for {cultivar_code} in {cul_path}")
            try:
                out[k.lower()] = float(row[k])
            except ValueError as e:
                raise RuntimeError(f"Non-numeric {k} for {cultivar_code} in {cul_path}: {row[k]}") from e
        return out
    raise RuntimeError(f"Cultivar code {cultivar_code} not found in {cul_path}")


def _read_sh2o_defaults(filex_base: Path) -> dict[str, float]:
    lines = filex_base.read_text(encoding="utf-8", errors="ignore").splitlines()
    in_table = False
    sh2o: dict[int, float] = {}
    for line in lines:
        if line.startswith("@C") and "ICBL" in line and "SH2O" in line:
            in_table = True
            continue
        if in_table:
            if line.startswith("*") or line.startswith("@"):
                break
            if not line.strip() or line.lstrip().startswith("!"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                icbl = int(parts[1])
                val = float(parts[2])
            except ValueError:
                continue
            sh2o[int(icbl)] = float(val)
    if 15 not in sh2o or 30 not in sh2o:
        return {}
    return {"sh2o_15": float(sh2o[15]), "sh2o_30": float(sh2o[30])}


def _read_measured_from_obs_a(
    a_path: Path,
    trts: list[int],
    yield_var: str,
    laix_var: str | None,
    allow_missing: bool = False,
) -> dict[str, float]:
    if str(a_path).strip().lower().startswith("__skip__"):
        return {}
    if not a_path.exists():
        if allow_missing:
            return {}
        raise RuntimeError(f"Obs A file missing: {a_path}")
    lines = a_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = None
    for line in lines:
        if line.startswith("@TRNO"):
            header = line
            break
    if not header:
        raise RuntimeError(f"Missing @TRNO header in {a_path}")

    cols = [c.lstrip("@").strip() for c in header.split()]
    col_upper = [c.upper() for c in cols]
    yield_need = {"TRNO", str(yield_var).strip().upper()}
    if not yield_need.issubset(set(col_upper)):
        raise RuntimeError(f"Obs A columns missing {sorted(yield_need)} in {a_path}: {cols}")
    i_trno = cols.index("TRNO")
    i_y = col_upper.index(str(yield_var).strip().upper())
    laix_use = None
    if laix_var and str(laix_var).strip().upper() in set(col_upper):
        laix_use = str(laix_var).strip()
    i_l = col_upper.index(str(laix_use).strip().upper()) if laix_use else -1

    table: dict[int, dict[str, float]] = {}
    for line in lines:
        if not line.strip() or line.startswith("@") or line.startswith("*") or line.lstrip().startswith("!"):
            continue
        parts = line.split()
        if len(parts) <= max([x for x in [i_trno, i_y, i_l] if x >= 0]):
            continue
        try:
            trno = int(parts[i_trno])
        except ValueError:
            continue
        try:
            rec: dict[str, float] = {str(yield_var).strip().lower(): float(parts[i_y])}
            if i_l >= 0:
                rec[str(laix_use).strip().lower()] = float(parts[i_l])
            table[int(trno)] = rec
        except ValueError:
            continue

    out: dict[str, float] = {}
    missing: list[int] = []
    for trt in trts:
        if int(trt) not in table:
            missing.append(int(trt))
            continue
        out[f"{str(yield_var).strip().lower()}_t{int(trt):02d}"] = float(table[int(trt)][str(yield_var).strip().lower()])
        if laix_use:
            lk = str(laix_use).strip().lower()
            if lk in table[int(trt)]:
                out[f"{lk}_t{int(trt):02d}"] = float(table[int(trt)][lk])
    if missing:
        if allow_missing:
            return out
        raise RuntimeError(f"TRNO not found in {a_path}: {missing}")
    return out


def _read_measured_from_wht(
    wht_path: Path,
    trts: list[int],
    allow_missing: bool = False,
) -> tuple[dict[str, float], dict[int, list[int]], str]:
    if str(wht_path).strip().lower().startswith("__skip__"):
        return {}, {}, ""
    if not wht_path.exists():
        if allow_missing:
            return {}, {}, ""
        raise RuntimeError(f"WHT file missing: {wht_path}")
    lines = wht_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = None
    for line in lines:
        if line.startswith("@TRNO"):
            header = line
            break
    if not header:
        raise RuntimeError(f"Missing @TRNO header in {wht_path}")

    cols = [c.lstrip("@").strip() for c in header.split()]
    need = {"TRNO", "DATE", "LAID"}
    if not need.issubset(set(cols)):
        raise RuntimeError(f"WHT columns missing {sorted(need)} in {wht_path}: {cols}")
    has_lwad = "LWAD" in cols
    has_swad = "SWAD" in cols
    second = "lwad" if has_lwad else ("swad" if has_swad else "")
    i_trno = cols.index("TRNO")
    i_date = cols.index("DATE")
    i_laid = cols.index("LAID")
    i_swad = cols.index("LWAD") if has_lwad else (cols.index("SWAD") if has_swad else -1)

    recs_by_trt: dict[int, list[tuple[int, float, float | None]]] = {}
    for line in lines:
        if not line.strip() or line.startswith("@") or line.startswith("*") or line.lstrip().startswith("!"):
            continue
        parts = line.split()
        if len(parts) <= max(i_trno, i_date, i_laid, i_swad):
            continue
        try:
            trno = int(parts[i_trno])
            date = int(parts[i_date])
            laid = float(parts[i_laid])
            swad = float(parts[i_swad]) if i_swad >= 0 else None
        except ValueError:
            continue
        recs_by_trt.setdefault(int(trno), []).append((int(date), float(laid), None if swad is None else float(swad)))

    out: dict[str, float] = {}
    dates_by_trt: dict[int, list[int]] = {}
    missing: list[int] = []
    for trt in trts:
        recs = recs_by_trt.get(int(trt))
        if not recs:
            missing.append(int(trt))
            continue
        recs_sorted = sorted(recs, key=lambda t: int(t[0]))
        dates_by_trt[int(trt)] = [int(d) for d, _, _ in recs_sorted]
        for d, laid, swad in recs_sorted:
            out[f"laid_t{int(trt):02d}_d{int(d)}"] = float(laid)
            if second and swad is not None:
                out[f"{second}_t{int(trt):02d}_d{int(d)}"] = float(swad)

    if missing:
        if allow_missing:
            return out, dates_by_trt, second
        raise RuntimeError(f"TRNO not found in {wht_path}: {missing}")

    return out, dates_by_trt, second


def _read_pest_best_params(work_dir: Path) -> dict[str, float]:
    candidates = [
        work_dir / "ksas_mvp_est.par",
        work_dir / "ksas_mvp.par",
        work_dir / "ksas_mvp.par.csv",
        work_dir / "ksas_mvp.post.par",
        work_dir / "ksas_mvp.post.par.csv",
    ]
    for p in candidates:
        if not p.exists():
            continue
        if p.suffix.lower() == ".csv":
            with p.open("r", encoding="utf-8", errors="ignore", newline="") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                continue
            row = rows[-1]
            out_csv: dict[str, float] = {}
            for k, v in row.items():
                if v is None:
                    continue
                k2 = k.strip().lower()
                try:
                    out_csv[k2] = float(v)
                except ValueError:
                    continue
            if out_csv:
                return out_csv
        else:
            out_txt: dict[str, float] = {}
            for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("*"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                k = parts[0].strip().lower()
                try:
                    out_txt[k] = float(parts[1])
                except ValueError:
                    continue
            if out_txt:
                return out_txt
    raise FileNotFoundError(f"No PEST parameter file found in {work_dir}")


def _write_params(path: Path, params: dict[str, float]) -> None:
    keys = sorted(params.keys())
    text = "\n".join([f"{k} {params[k]:.6f}" for k in keys]) + "\n"
    path.write_text(text, encoding="utf-8")


def _run_one(work_dir: Path, run_model_path: Path, dssat_dir: Path, params_path: Path, trts: list[int]) -> dict[str, float]:
    env = os.environ.copy()
    env["PARAMS_PATH"] = str(params_path)
    env["DSSAT_CASE_DIR"] = str(dssat_dir)
    env["DSSAT_TRTS"] = ",".join([str(int(t)) for t in trts])
    env["DSSAT_KEEP_OUTPUTS"] = "0"
    env["DSSAT_ALLOW_MISSING_WHT_DATES"] = "1"
    cp = subprocess.run([sys.executable, str(run_model_path)], cwd=str(work_dir), capture_output=True, text=True, env=env)
    if cp.returncode != 0:
        raise RuntimeError(f"run_model.py failed: {cp.returncode}\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}")
    out = _read_kv_params(work_dir / "pest_out.dat")
    return out


def main() -> None:
    work_dir = Path.cwd()
    project_root = Path(__file__).resolve().parents[1]
    cfg = _load_project_config(project_root)
    dssat_dir = Path(os.environ.get("DSSAT_CASE_DIR", cfg.get("paths", {}).get("dssat_case_dir", str(project_root / "data" / "dssat")))).resolve()
    run_model_path = project_root / "src" / "run_model.py"

    filex_name = cfg.get("scenario", {}).get("filex", "KSAS8101.WHX")
    base_filex = cfg.get("scenario", {}).get("base_filex", "KSAS8101_base.WHX")
    filex_path = dssat_dir / filex_name
    filex_base = dssat_dir / base_filex
    cfg_paths = cfg.get("paths", {})

    metrics_cfg = cfg.get("metrics", {}) or cfg.get("variables", {}) or {}
    yield_var = str(metrics_cfg.get("yield_var", "HWAM")).strip().upper()
    laix_raw = str(metrics_cfg.get("laix_var", "LAIX")).strip().upper()
    laix_var = laix_raw if laix_raw else None

    a_path_raw = str(cfg_paths.get("obs_a_path", "")).strip() or str(cfg_paths.get("wha_path", "")).strip()
    a_path_env = os.environ.get("DSSAT_OBS_A_PATH") if "DSSAT_OBS_A_PATH" in os.environ else None
    if a_path_env is not None:
        a_path_raw = str(a_path_env).strip()
    if a_path_raw:
        if str(a_path_raw).strip().lower().startswith("__skip__"):
            a_path = Path("__skip__")
        else:
            a_path = Path(a_path_raw)
            if not a_path.is_absolute():
                a_path = dssat_dir / a_path
    else:
        suf = filex_path.suffix
        if suf.upper().endswith("X") and len(suf) >= 2:
            a_path = filex_path.with_suffix(suf[:-1] + "A")
        else:
            a_path = filex_path.with_suffix(".A")

    t_path_raw = str(cfg_paths.get("obs_t_path", "")).strip() or str(cfg_paths.get("wht_path", "")).strip()
    t_path_env = os.environ.get("DSSAT_OBS_T_PATH") if "DSSAT_OBS_T_PATH" in os.environ else None
    if t_path_env is not None:
        t_path_raw = str(t_path_env).strip()
    if t_path_raw:
        if str(t_path_raw).strip().lower().startswith("__skip__"):
            wht_path = Path("__skip__")
        else:
            wht_path = Path(t_path_raw)
            if not wht_path.is_absolute():
                wht_path = dssat_dir / wht_path
    else:
        suf = filex_path.suffix
        if suf.upper().endswith("X") and len(suf) >= 2:
            wht_path = filex_path.with_suffix(suf[:-1] + "T")
        else:
            wht_path = filex_path.with_suffix(".T")

    trts_env = os.environ.get("DSSAT_TRTS", "").strip()
    if trts_env:
        trts = [int(t) for t in re.split(r"[\s,;]+", trts_env) if t.strip()]
    else:
        cfg_trts = cfg.get("scenario", {}).get("trts", [])
        trts = [int(t) for t in cfg_trts] if cfg_trts else extract_trts_from_filex(filex_path)

    cultivar_code = extract_cultivar_code(filex_path)
    cfg_cul = str(cfg_paths.get("cul_path", "")).strip() or str(cfg_paths.get("wh_cul_path", "")).strip()
    cul_path = Path(os.environ.get("CUL_PATH", os.environ.get("WH_CUL_PATH", cfg_cul or r"C:\DSSAT48\Genotype\WHCER048.CUL")))

    param_map, _ = resolve_param_mapping(cfg, dssat_dir)
    sh2o = _read_sh2o_defaults(filex_base)
    bound_keys_raw = list((cfg.get("params", {}) or {}).get("bounds", {}).keys())
    bound_keys: list[str] = []
    seen = set()
    for k in bound_keys_raw:
        k_l = str(k).strip().lower()
        if not k_l:
            continue
        mapped = param_map.get(k_l, k_l)
        if mapped and mapped not in seen:
            bound_keys.append(mapped)
            seen.add(mapped)
    cul_cols = [str(k).strip().upper() for k in bound_keys if str(k).strip() and not str(k).strip().lower().startswith("sh2o_")]
    baseline = _read_cul_params(cul_path, cultivar_code, cul_cols) | sh2o

    pest_best = _read_pest_best_params(work_dir)
    local_mgda_path = work_dir / "params_mgda.dat"
    env_mgda_path = Path(os.environ.get("MGDA_PARAMS_PATH", "")).expanduser() if os.environ.get("MGDA_PARAMS_PATH") else None
    mgda_path = local_mgda_path if local_mgda_path.exists() else env_mgda_path
    mgda = _read_kv_params(mgda_path) if (mgda_path and mgda_path.exists()) else _read_kv_params(work_dir / "params.dat")

    for k, v in sh2o.items():
        pest_best.setdefault(k, v)
        mgda.setdefault(k, v)

    params_files = {
        "baseline": work_dir / "params_baseline.dat",
        "pest": work_dir / "params_pest.dat",
        "mgda": work_dir / "params_mgda_for_eval.dat",
    }
    _write_params(params_files["baseline"], baseline)
    _write_params(params_files["pest"], pest_best)
    _write_params(params_files["mgda"], mgda)

    allow_missing_obs_files = str(os.environ.get("DSSAT_ALLOW_MISSING_OBS_FILES", "")).strip().lower() in {"1", "true", "yes", "y"} or bool(
        (cfg.get("observations", {}) or {}).get("allow_missing_obs_files", False)
    )
    allow_missing_wht = str(os.environ.get("DSSAT_ALLOW_MISSING_WHT_DATES", "")).strip().lower() in {"1", "true", "yes", "y"} or allow_missing_obs_files

    try:
        meas = _read_measured_from_obs_a(a_path, trts, yield_var, laix_var, allow_missing=allow_missing_obs_files)
    except Exception:
        if not allow_missing_obs_files:
            raise
        meas = {}
    if laix_var and not any(k.startswith(f"{str(laix_var).strip().lower()}_t") for k in meas.keys()):
        laix_var = None
    wht_dates_by_trt: dict[int, list[int]] = {}
    wht_second = ""
    try:
        wht_meas, wht_dates_by_trt, wht_second = _read_measured_from_wht(wht_path, trts, allow_missing=allow_missing_wht)
        meas.update(wht_meas)
    except Exception:
        if not allow_missing_wht:
            raise
        wht_dates_by_trt = {}
        wht_second = ""

    split_by_trt = _resolve_split(cfg, trts)

    weights = _read_obs_weights(work_dir)
    cfg_weights = {str(k).strip().lower(): float(v) for k, v in cfg.get("observations", {}).get("weights", {}).items()}

    sim_by_scenario: dict[str, dict[str, float]] = {}
    for scen, pfile in params_files.items():
        sim_by_scenario[scen] = _run_one(work_dir, run_model_path, dssat_dir, pfile, trts)

    valid_trts: list[int] = []
    base_sim = sim_by_scenario.get("baseline", {})
    if base_sim:
        seen_trts: set[int] = set()
        for k in base_sim.keys():
            m = re.search(r"_t(\d{2})\b", k)
            if m:
                try:
                    seen_trts.add(int(m.group(1)))
                except ValueError:
                    pass
        if seen_trts:
            valid_trts = sorted(seen_trts)
    if valid_trts:
        trts = valid_trts

    rows: list[TrtRow] = []
    for scen, sim in sim_by_scenario.items():
        for trt in trts:
            yk = f"{str(yield_var).strip().lower()}_t{int(trt):02d}" if str(yield_var).strip() else ""
            lk = f"{str(laix_var).strip().lower()}_t{int(trt):02d}" if laix_var else ""
            oy = float(meas.get(yk, float("nan"))) if yk else float("nan")
            ol = float(meas.get(lk, float("nan"))) if lk else float("nan")
            sy = float(sim.get(yk, float("nan"))) if yk else float("nan")
            sl = float(sim.get(lk, float("nan"))) if lk else float("nan")
            ey = (sy - oy) if (math.isfinite(oy) and math.isfinite(sy)) else float("nan")
            el = (sl - ol) if (lk and math.isfinite(ol) and math.isfinite(sl)) else float("nan")
            grp_y, w_y = _resolve_group_and_weight(yk, cfg)
            grp_l, w_l = _resolve_group_and_weight(lk, cfg) if lk else (None, None)
            wy = float(cfg_weights.get(yk.lower(), w_y if w_y is not None else weights.get(yk.lower(), 1.0)))
            wl = float(cfg_weights.get(lk.lower(), w_l if w_l is not None else weights.get(lk.lower(), 1.0))) if lk else 0.0
            phi_y = (ey * ey) if math.isfinite(ey) else 0.0
            phi_l = (el * el) if math.isfinite(el) else 0.0
            phi_w_y = ((ey * wy) ** 2) if math.isfinite(ey) and math.isfinite(wy) else 0.0
            phi_w_l = ((el * wl) ** 2) if math.isfinite(el) and math.isfinite(wl) else 0.0

            phi_laid = 0.0
            phi_lwad = 0.0
            phi_swad = 0.0
            phi_w_laid = 0.0
            phi_w_lwad = 0.0
            phi_w_swad = 0.0
            n_wht = 0
            n_wht_lwad = 0
            n_wht_swad = 0
            for d in wht_dates_by_trt.get(int(trt), []):
                k_laid = f"laid_t{int(trt):02d}_d{int(d)}"
                k_lwad = f"lwad_t{int(trt):02d}_d{int(d)}"
                k_swad = f"swad_t{int(trt):02d}_d{int(d)}"
                if k_laid not in sim:
                    continue
                o_laid = float(meas[k_laid])
                s_laid = float(sim[k_laid])
                e_laid = s_laid - o_laid
                grp_laid, w_laid_cfg = _resolve_group_and_weight(k_laid, cfg)
                w_laid = float(cfg_weights.get(k_laid.lower(), w_laid_cfg if w_laid_cfg is not None else weights.get(k_laid.lower(), 1.0)))
                phi_laid += e_laid * e_laid
                phi_w_laid += (e_laid * w_laid) ** 2
                n_wht += 1

                if wht_second == "lwad" and k_lwad in meas and k_lwad in sim:
                    o_lwad = float(meas[k_lwad])
                    s_lwad = float(sim[k_lwad])
                    e_lwad = s_lwad - o_lwad
                    grp_lwad, w_lwad_cfg = _resolve_group_and_weight(k_lwad, cfg)
                    w_lwad = float(cfg_weights.get(k_lwad.lower(), w_lwad_cfg if w_lwad_cfg is not None else weights.get(k_lwad.lower(), 1.0)))
                    phi_lwad += e_lwad * e_lwad
                    phi_w_lwad += (e_lwad * w_lwad) ** 2
                    n_wht_lwad += 1
                if wht_second == "swad" and k_swad in meas and k_swad in sim:
                    o_swad = float(meas[k_swad])
                    s_swad = float(sim[k_swad])
                    e_swad = s_swad - o_swad
                    grp_swad, w_swad_cfg = _resolve_group_and_weight(k_swad, cfg)
                    w_swad = float(cfg_weights.get(k_swad.lower(), w_swad_cfg if w_swad_cfg is not None else weights.get(k_swad.lower(), 1.0)))
                    phi_swad += e_swad * e_swad
                    phi_w_swad += (e_swad * w_swad) ** 2
                    n_wht_swad += 1

            phi = phi_y + phi_l + phi_laid + phi_lwad + phi_swad
            phi_w = phi_w_y + phi_w_l + phi_w_laid + phi_w_lwad + phi_w_swad
            rows.append(
                {
                    "scenario": scen,
                    "trt": int(trt),
                    "split": split_by_trt.get(int(trt), "train"),
                    "obs_yield": oy,
                    "sim_yield": sy,
                    "err_yield": ey,
                    "obs_laix": ol,
                    "sim_laix": sl,
                    "err_laix": el,
                    "n_wht_dates": n_wht,
                    "n_wht_lwad": n_wht_lwad,
                    "n_wht_swad": n_wht_swad,
                    "phi_yield": phi_y,
                    "phi_laix": phi_l,
                    "phi_laid": phi_laid,
                    "phi_lwad": phi_lwad,
                    "phi_swad": phi_swad,
                    "phi": phi,
                    "phi_w": phi_w,
                }
            )

    by_trt_path = work_dir / "compare_by_trt.csv"
    with by_trt_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "scenario",
                "trt",
                "split",
                "obs_yield",
                "sim_yield",
                "err_yield",
                "obs_laix",
                "sim_laix",
                "err_laix",
                "n_wht_dates",
                "n_wht_lwad",
                "n_wht_swad",
                "phi_yield",
                "phi_laix",
                "phi_laid",
                "phi_lwad",
                "phi_swad",
                "phi",
                "phi_w",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    summary_rows: list[dict[str, object]] = []
    for scen in sorted(sim_by_scenario.keys()):
        scen_rows = [r for r in rows if r["scenario"] == scen]
        overall = _calc_summary(scen_rows)
        train_rows = [r for r in scen_rows if r.get("split") == "train"]
        valid_rows = [r for r in scen_rows if r.get("split") == "valid"]
        train = _calc_summary(train_rows)
        valid = _calc_summary(valid_rows)
        summary_rows.append(
            {
                "scenario": scen,
                "n_trt": overall["n_trt"],
                "n_wht": overall["n_wht"],
                "rmse_yield": overall["rmse_yield"],
                "rrmse_yield": overall["rrmse_yield"],
                "mae_yield": overall["mae_yield"],
                "r2_yield": overall["r2_yield"],
                "nrmse_mean_yield": overall["nrmse_mean_yield"],
                "nrmse_range_yield": overall["nrmse_range_yield"],
                "dindex_yield": overall["dindex_yield"],
                "rmse_laix": overall["rmse_laix"],
                "rrmse_laix": overall["rrmse_laix"],
                "mae_laix": overall["mae_laix"],
                "r2_laix": overall["r2_laix"],
                "nrmse_mean_laix": overall["nrmse_mean_laix"],
                "nrmse_range_laix": overall["nrmse_range_laix"],
                "dindex_laix": overall["dindex_laix"],
                "rmse_laid": overall["rmse_laid"],
                "rmse_lwad": overall["rmse_lwad"],
                "rmse_swad": overall["rmse_swad"],
                "bias_yield": overall["bias_yield"],
                "bias_laix": overall["bias_laix"],
                "phi": overall["phi"],
                "phi_w": overall["phi_w"],
                "train_n_trt": train["n_trt"],
                "train_n_wht": train["n_wht"],
                "train_rmse_yield": train["rmse_yield"],
                "train_rrmse_yield": train["rrmse_yield"],
                "train_mae_yield": train["mae_yield"],
                "train_r2_yield": train["r2_yield"],
                "train_nrmse_mean_yield": train["nrmse_mean_yield"],
                "train_nrmse_range_yield": train["nrmse_range_yield"],
                "train_dindex_yield": train["dindex_yield"],
                "train_rmse_laix": train["rmse_laix"],
                "train_rrmse_laix": train["rrmse_laix"],
                "train_mae_laix": train["mae_laix"],
                "train_r2_laix": train["r2_laix"],
                "train_nrmse_mean_laix": train["nrmse_mean_laix"],
                "train_nrmse_range_laix": train["nrmse_range_laix"],
                "train_dindex_laix": train["dindex_laix"],
                "train_rmse_laid": train["rmse_laid"],
                "train_rmse_lwad": train["rmse_lwad"],
                "train_rmse_swad": train["rmse_swad"],
                "train_bias_yield": train["bias_yield"],
                "train_bias_laix": train["bias_laix"],
                "train_phi": train["phi"],
                "train_phi_w": train["phi_w"],
                "valid_n_trt": valid["n_trt"],
                "valid_n_wht": valid["n_wht"],
                "valid_rmse_yield": valid["rmse_yield"],
                "valid_rrmse_yield": valid["rrmse_yield"],
                "valid_mae_yield": valid["mae_yield"],
                "valid_r2_yield": valid["r2_yield"],
                "valid_nrmse_mean_yield": valid["nrmse_mean_yield"],
                "valid_nrmse_range_yield": valid["nrmse_range_yield"],
                "valid_dindex_yield": valid["dindex_yield"],
                "valid_rmse_laix": valid["rmse_laix"],
                "valid_rrmse_laix": valid["rrmse_laix"],
                "valid_mae_laix": valid["mae_laix"],
                "valid_r2_laix": valid["r2_laix"],
                "valid_nrmse_mean_laix": valid["nrmse_mean_laix"],
                "valid_nrmse_range_laix": valid["nrmse_range_laix"],
                "valid_dindex_laix": valid["dindex_laix"],
                "valid_rmse_laid": valid["rmse_laid"],
                "valid_rmse_lwad": valid["rmse_lwad"],
                "valid_rmse_swad": valid["rmse_swad"],
                "valid_bias_yield": valid["bias_yield"],
                "valid_bias_laix": valid["bias_laix"],
                "valid_phi": valid["phi"],
                "valid_phi_w": valid["phi_w"],
            }
        )

    summary_fields = [
        "scenario",
        "n_trt",
        "n_wht",
        "rmse_yield",
        "rrmse_yield",
        "mae_yield",
        "r2_yield",
        "nrmse_mean_yield",
        "nrmse_range_yield",
        "dindex_yield",
        "rmse_laix",
        "rrmse_laix",
        "mae_laix",
        "r2_laix",
        "nrmse_mean_laix",
        "nrmse_range_laix",
        "dindex_laix",
        "rmse_laid",
        "rmse_lwad",
        "rmse_swad",
        "bias_yield",
        "bias_laix",
        "phi",
        "phi_w",
        "train_n_trt",
        "train_n_wht",
        "train_rmse_yield",
        "train_rrmse_yield",
        "train_mae_yield",
        "train_r2_yield",
        "train_nrmse_mean_yield",
        "train_nrmse_range_yield",
        "train_dindex_yield",
        "train_rmse_laix",
        "train_rrmse_laix",
        "train_mae_laix",
        "train_r2_laix",
        "train_nrmse_mean_laix",
        "train_nrmse_range_laix",
        "train_dindex_laix",
        "train_rmse_laid",
        "train_rmse_lwad",
        "train_rmse_swad",
        "train_bias_yield",
        "train_bias_laix",
        "train_phi",
        "train_phi_w",
        "valid_n_trt",
        "valid_n_wht",
        "valid_rmse_yield",
        "valid_rrmse_yield",
        "valid_mae_yield",
        "valid_r2_yield",
        "valid_nrmse_mean_yield",
        "valid_nrmse_range_yield",
        "valid_dindex_yield",
        "valid_rmse_laix",
        "valid_rrmse_laix",
        "valid_mae_laix",
        "valid_r2_laix",
        "valid_nrmse_mean_laix",
        "valid_nrmse_range_laix",
        "valid_dindex_laix",
        "valid_rmse_laid",
        "valid_rmse_lwad",
        "valid_rmse_swad",
        "valid_bias_yield",
        "valid_bias_laix",
        "valid_phi",
        "valid_phi_w",
    ]
    summary_path = work_dir / "compare_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        w.writeheader()
        w.writerows(summary_rows)

    species = dssat_dir.name
    summary_by_group = []
    for row in summary_rows:
        out: dict[str, object] = {"species": species, "cultivar": cultivar_code}
        out.update(row)
        summary_by_group.append(out)
    summary_by_path = work_dir / "compare_summary_by_species_cultivar.csv"
    with summary_by_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["species", "cultivar"] + summary_fields)
        w.writeheader()
        w.writerows(summary_by_group)

    param_keys = [str(k).strip().lower() for k in bound_keys if str(k).strip()]
    for k in ["sh2o_15", "sh2o_30"]:
        if k not in param_keys:
            param_keys.append(k)
    param_keys = _resolve_family_param_keys(cfg, dssat_dir, param_keys)

    param_rows: list[dict[str, object]] = []
    for scen, pfile in params_files.items():
        p = _read_kv_params(pfile)
        prow: dict[str, object] = {"scenario": scen}
        for k in param_keys:
            prow[k] = p.get(k)
        param_rows.append(prow)

    params_path = work_dir / "compare_params.csv"
    with params_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["scenario"] + param_keys)
        w.writeheader()
        w.writerows(param_rows)

    params_by_group = []
    for prow in param_rows:
        out_params: dict[str, object] = {"species": species, "cultivar": cultivar_code}
        out_params.update(prow)
        params_by_group.append(out_params)
    params_by_path = work_dir / "compare_params_by_species_cultivar.csv"
    with params_by_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["species", "cultivar", "scenario"] + param_keys)
        w.writeheader()
        w.writerows(params_by_group)

    print(f"Wrote: {by_trt_path.name}, {summary_path.name}, {params_path.name}, {summary_by_path.name}, {params_by_path.name}")


if __name__ == "__main__":
    main()
