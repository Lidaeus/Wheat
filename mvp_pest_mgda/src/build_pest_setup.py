from __future__ import annotations

import math
import os
import random
import shutil
import subprocess
import time
from pathlib import Path

import pyemu

from dssat_io import extract_trts_from_filex, load_project_config, resolve_param_mapping


def _try_unlink(path: Path, tries: int = 10, sleep_s: float = 0.1) -> None:
    for _ in range(max(1, int(tries))):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(float(sleep_s))
    return


def _load_project_config(project_root: Path) -> dict:
    return load_project_config(project_root)


def _read_params(params_path: Path) -> dict[str, float]:
    params: dict[str, float] = {}
    for raw in params_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        params[parts[0].strip().lower()] = float(parts[1])
    return params


def _resolve_split(cfg: dict, trts: list[int]) -> dict[int, str]:
    split_cfg = cfg.get("split", {})
    mode = str(split_cfg.get("mode", "trt")).strip().lower()
    all_trts = [int(t) for t in trts]
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


def _extract_trt_from_obs_name(name: str) -> int | None:
    import re as _re
    m = _re.search(r"_t(\d{2})", str(name).lower())
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _resolve_obs_group_name(name: str, group_defs: dict, yield_prefix: str, laix_prefix: str) -> str:
    name_l = str(name).strip().lower()
    for gname, gspec in group_defs.items():
        pats = [str(p).lower() for p in (gspec.get("patterns") or [])]
        if any(name_l.startswith(p) for p in pats):
            return str(gname)
    if yield_prefix and name_l.startswith(str(yield_prefix).lower() + "_"):
        return "obs_yield"
    if laix_prefix and name_l.startswith(str(laix_prefix).lower() + "_"):
        return "obs_laix"
    if name_l.startswith("laid_"):
        return "obs_laid"
    if name_l.startswith("swad_"):
        return "obs_swad"
    if name_l.startswith("lwad_"):
        return "obs_lwad"
    return "obs"


def _calc_group_variances(
    meas: dict[str, float],
    split_by_trt: dict[int, str],
    group_defs: dict,
    yield_prefix: str,
    laix_prefix: str,
) -> dict[str, float]:
    group_vals: dict[str, list[float]] = {}
    for oname, oval in meas.items():
        trt = _extract_trt_from_obs_name(oname)
        if (trt is not None) and (split_by_trt.get(int(trt)) == "valid"):
            continue
        try:
            v = float(oval)
        except Exception:
            continue
        g = _resolve_obs_group_name(oname, group_defs, yield_prefix, laix_prefix)
        group_vals.setdefault(g, []).append(v)
    out: dict[str, float] = {}
    for g, vals in group_vals.items():
        if len(vals) < 2:
            out[g] = float("nan")
            continue
        mean = sum(vals) / float(len(vals))
        var = sum((x - mean) ** 2 for x in vals) / float(len(vals) - 1)
        out[g] = float(var)
    return out


def _extract_measured_from_obs_a(
    a_path: Path,
    trts: list[int],
    yield_var: str,
    laix_var: str | None,
    allow_missing: bool = False,
) -> dict[str, float]:
    if (not str(yield_var).strip()) and (not laix_var):
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
    need = {"TRNO"}
    if str(yield_var).strip():
        need.add(str(yield_var).strip().upper())
    if laix_var:
        need.add(str(laix_var).strip().upper())
    if not need.issubset(set(c.upper() for c in cols)):
        if allow_missing:
            return {}
        raise RuntimeError(f"Obs A columns missing {sorted(need)} in {a_path}: {cols}")
    i_trno = cols.index("TRNO")
    col_upper = [c.upper() for c in cols]
    i_y = col_upper.index(str(yield_var).strip().upper()) if str(yield_var).strip() else -1
    i_l = col_upper.index(str(laix_var).strip().upper()) if laix_var else -1

    rows: dict[int, dict[str, float]] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("!") or line.startswith("@") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) <= max([x for x in [i_trno, i_y, i_l] if x >= 0], default=i_trno):
            continue
        try:
            trno = int(parts[i_trno])
        except ValueError:
            continue
        try:
            rec: dict[str, float] = {}
            if i_y >= 0:
                rec[str(yield_var).strip().lower()] = float(parts[i_y])
            if i_l >= 0:
                rec[str(laix_var).strip().lower()] = float(parts[i_l])
            if not rec:
                continue
            rows[int(trno)] = rec
        except ValueError:
            continue

    out: dict[str, float] = {}
    for trt in trts:
        if int(trt) not in rows:
            continue
        if i_y >= 0:
            yk = str(yield_var).strip().lower()
            if yk in rows[int(trt)]:
                out[f"{yk}_t{int(trt):02d}"] = float(rows[int(trt)][yk])
        if laix_var:
            lk = str(laix_var).strip().lower()
            if lk in rows[int(trt)]:
                out[f"{lk}_t{int(trt):02d}"] = float(rows[int(trt)][lk])

    return out


def _extract_measured_from_wht(
    wht_path: Path, trts: list[int], allow_missing: bool = False
) -> tuple[dict[str, float], dict[int, list[int]], str]:
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
    required = {"TRNO", "DATE", "LAID"}
    if not required.issubset(set(cols)):
        raise RuntimeError(f"WHT columns missing {sorted(required)} in {wht_path}: {cols}")
    has_lwad = "LWAD" in cols
    has_swad = "SWAD" in cols
    second = "lwad" if has_lwad else ("swad" if has_swad else "")
    i_trno = cols.index("TRNO")
    i_date = cols.index("DATE")
    i_laid = cols.index("LAID")
    i_swad = cols.index("LWAD") if has_lwad else (cols.index("SWAD") if has_swad else -1)

    rows_by_trt: dict[int, list[tuple[int, float, float | None]]] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("!") or line.startswith("@") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) <= max(i_trno, i_date, i_laid, i_swad):
            continue
        try:
            trno = int(parts[i_trno])
            date = int(parts[i_date])
        except ValueError:
            continue
        try:
            laid = float(parts[i_laid])
            swad = float(parts[i_swad]) if i_swad >= 0 else None
        except ValueError:
            continue
        rows_by_trt.setdefault(int(trno), []).append((int(date), float(laid), None if swad is None else float(swad)))

    out: dict[str, float] = {}
    dates_by_trt: dict[int, list[int]] = {}
    for trt in trts:
        recs = rows_by_trt.get(int(trt))
        if not recs:
            continue
        recs_sorted = sorted(recs, key=lambda t: int(t[0]))
        dates_by_trt[int(trt)] = [int(d) for d, _, _ in recs_sorted]
        for d, laid, swad in recs_sorted:
            out[f"laid_t{int(trt):02d}_d{int(d)}"] = float(laid)
            if second and swad is not None:
                out[f"{second}_t{int(trt):02d}_d{int(d)}"] = float(swad)

    return out, dates_by_trt, second


def _read_pest_out(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0].strip().lower()] = float(parts[1])
    return out


def _write_pest_out_ins(
    path: Path,
    trts: list[int],
    yield_var: str,
    laix_var: str | None,
    obs_trts_yield: set[int] | None = None,
    obs_trts_laix: set[int] | None = None,
    wht_dates_by_trt: dict[int, list[int]] | None = None,
    wht_second: str = "",
) -> None:
    lines = ["pif ~"]
    for trt in trts:
        if str(yield_var).strip() and (obs_trts_yield is None or int(trt) in obs_trts_yield):
            yk = str(yield_var).strip().lower()
            lines.append(f"l1 w !{yk}_t{int(trt):02d}!")
        if laix_var and (obs_trts_laix is None or int(trt) in obs_trts_laix):
            lk = str(laix_var).strip().lower()
            lines.append(f"l1 w !{lk}_t{int(trt):02d}!")
        if wht_dates_by_trt and int(trt) in wht_dates_by_trt:
            for d in wht_dates_by_trt[int(trt)]:
                lines.append(f"l1 w !laid_t{int(trt):02d}_d{int(d)}!")
                if wht_second:
                    lines.append(f"l1 w !{str(wht_second).strip().lower()}_t{int(trt):02d}_d{int(d)}!")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ensure_case_files(case_dir: Path, project_root: Path, cfg: dict) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)

    params_dat = case_dir / "params.dat"
    dssat_dir_raw = str(cfg.get("paths", {}).get("dssat_case_dir", "")).strip()
    dssat_dir = Path(dssat_dir_raw) if dssat_dir_raw else None
    param_map, _ = resolve_param_mapping(cfg, dssat_dir)
    bounds = cfg.get("params", {}).get("bounds", {})
    desired: dict[str, tuple[float, float]] = {}
    if isinstance(bounds, dict) and bounds:
        for k, v in bounds.items():
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                k_l = str(k).strip().lower()
                mapped = param_map.get(k_l, k_l)
                desired[mapped] = (float(v[0]), float(v[1]))

    rewrite = False
    existing: dict[str, float] = {}
    if params_dat.exists():
        try:
            existing = _read_params(params_dat)
        except Exception:
            existing = {}

    if desired:
        if not params_dat.exists():
            rewrite = True
        else:
            desired_keys = set(desired.keys())
            existing_keys = set(existing.keys())
            if not desired_keys.issubset(existing_keys):
                rewrite = True
            if any(k not in desired_keys for k in existing_keys):
                rewrite = True

        if rewrite:
            vals: dict[str, float] = {}
            for k, (lb, ub) in desired.items():
                if k in existing:
                    vals[k] = float(existing[k])
                else:
                    vals[k] = float((lb + ub) / 2.0)
            params_dat.write_text(
                "\n".join([f"{k} {vals[k]:.6f}" for k in sorted(vals.keys())]) + "\n",
                encoding="utf-8",
            )
    else:
        if not params_dat.exists():
            seed = project_root / "work" / "params.dat"
            if seed.exists():
                params_dat.write_text(seed.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
            else:
                params_dat.write_text(
                    "\n".join(
                        [
                            "sh2o_15 0.205",
                            "sh2o_30 0.170",
                            "p1v 48.0",
                            "p1d 90.0",
                            "p5 505.0",
                            "g1 35.0",
                            "g2 22.0",
                            "g3 1.0",
                            "phint 116.0",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

    params_tpl = case_dir / "params.tpl"
    if (not params_tpl.exists()) or rewrite:
        keys = list(_read_params(params_dat).keys())
        if not keys:
            keys = ["sh2o_15", "sh2o_30"]
        lines = ["ptf ~"]
        for k in keys:
            k2 = str(k).strip()
            lines.append(f"{k2:<12} ~{k2:<12}~")
        lines.append("")
        params_tpl.write_text("\n".join(lines), encoding="utf-8")


def _stage_dssat_case(work_dir: Path, project_root: Path, cfg: dict) -> Path:
    template_root = cfg.get("paths", {}).get("dssat_case_dir", "")
    template = (Path(template_root).resolve() if template_root else (project_root / "data" / "dssat").resolve())
    fallback = (project_root / "data" / "dssat").resolve()
    case_dir = (work_dir / "dssat_case").resolve()
    case_dir.mkdir(parents=True, exist_ok=True)

    filex_name = cfg.get("scenario", {}).get("filex", "KSAS8101.WHX")
    base_filex = cfg.get("scenario", {}).get("base_filex", "KSAS8101_base.WHX")

    required = ["DSSAT48.INP", "DSSAT48.INH", filex_name, base_filex]
    for name in required:
        tried = [template / name]
        if fallback != template:
            tried.append(fallback / name)
        src = None
        for cand in tried:
            if cand.exists():
                src = cand
                break
        dst = case_dir / name
        if src is None:
            raise FileNotFoundError(f"Missing DSSAT template file: {name}. Tried: {', '.join(str(p) for p in tried)}")
        if not dst.exists():
            shutil.copy2(src, dst)

    geno_dir = case_dir / "GENOTYPE"
    geno_dir.mkdir(parents=True, exist_ok=True)
    inp = case_dir / "DSSAT48.INP"
    cul_file_name = None
    cul_src_dir = None
    if inp.exists():
        for raw in inp.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not raw.startswith("CULTIVAR"):
                continue
            if ".CUL" not in raw.upper():
                continue
            toks = raw.split()
            for tok in toks:
                if tok.upper().endswith(".CUL"):
                    cul_file_name = tok.strip()
                    break
            if "C:\\" in raw:
                cul_src_dir = raw[raw.index("C:\\") :].strip()
            break

    cfg_paths = cfg.get("paths", {})
    cul_env = os.environ.get("CUL_PATH", "").strip() or os.environ.get("WH_CUL_PATH", "").strip()
    src_cul: Path | None = None
    if cul_env:
        src_cul = Path(cul_env)
    else:
        cfg_cul = str(cfg_paths.get("cul_path", "")).strip() or str(cfg_paths.get("wh_cul_path", "")).strip()
        src_cul = Path(cfg_cul) if cfg_cul else None
        if (src_cul is None or not src_cul.exists()) and cul_src_dir and cul_file_name:
            try:
                src_cul = (Path(cul_src_dir) / cul_file_name).resolve()
            except Exception:
                src_cul = None

    if src_cul and src_cul.exists():
        dst_name = cul_file_name or src_cul.name
        dst_cul = geno_dir / dst_name
        shutil.copy2(src_cul, dst_cul)

    new_dir = str(geno_dir.resolve()) + "\\"
    for p in [case_dir / "DSSAT48.INP", case_dir / "DSSAT48.INH"]:
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        out: list[str] = []
        changed = False
        for line in lines:
            row = line.rstrip("\r\n")
            ending = line[len(row) :]
            if p.name.upper().endswith(".INP"):
                if row.startswith("CULTIVAR") and ".CUL" in row.upper() and "C:\\" in row:
                    idx = row.index("C:\\")
                    old_tail = row[idx:]
                    repl = new_dir.ljust(len(old_tail))[: len(old_tail)]
                    row = row[:idx] + repl
                    changed = True
            else:
                if ".CUL" in row.upper() and "C:\\" in row:
                    idx = row.index("C:\\")
                    old_tail = row[idx:]
                    repl = new_dir.ljust(len(old_tail))[: len(old_tail)]
                    row = row[:idx] + repl
                    changed = True
            out.append(row + ending)
        if changed:
            p.write_text("".join(out), encoding="utf-8")

    return case_dir


def main() -> None:
    cwd = Path.cwd()
    template_dir = Path(__file__).resolve().parent
    project_root = template_dir.parent
    cfg = _load_project_config(project_root)
    _ensure_case_files(cwd, project_root, cfg)

    dssat_dir = _stage_dssat_case(cwd, project_root, cfg)
    param_map, _ = resolve_param_mapping(cfg, dssat_dir)

    run_model_path = template_dir / "run_model.py"

    filex_name = cfg.get("scenario", {}).get("filex", "KSAS8101.WHX")
    filex_path = dssat_dir / filex_name
    trts = extract_trts_from_filex(filex_path)
    trts_env = os.environ.get("DSSAT_TRTS", "").strip()
    if trts_env:
        trts = [int(t) for t in trts_env.replace(";", ",").replace(" ", ",").split(",") if t.strip()]
    else:
        cfg_trts = cfg.get("scenario", {}).get("trts", [])
        if cfg_trts:
            trts = [int(t) for t in cfg_trts]

    metrics_cfg = cfg.get("metrics", {}) or cfg.get("variables", {}) or {}
    yield_var = str(metrics_cfg.get("yield_var", "HWAM")).strip().upper()
    laix_var_raw = str(metrics_cfg.get("laix_var", "LAIX")).strip().upper()
    laix_var = laix_var_raw if laix_var_raw else None

    cfg_paths = cfg.get("paths", {})
    a_path_env = os.environ.get("DSSAT_OBS_A_PATH") if "DSSAT_OBS_A_PATH" in os.environ else None
    a_path_raw = str(a_path_env).strip() if a_path_env is not None else (str(cfg_paths.get("obs_a_path", "")).strip() or str(cfg_paths.get("wha_path", "")).strip())
    a_path = None
    if a_path_raw and not str(a_path_raw).strip().lower().startswith("__skip__"):
        a_path = Path(a_path_raw)
        if not a_path.is_absolute():
            a_path = dssat_dir / a_path
    if a_path is None:
        suf = filex_path.suffix
        if suf.upper().endswith("X") and len(suf) >= 2:
            a_path = filex_path.with_suffix(suf[:-1] + "A")
        else:
            a_path = filex_path.with_suffix(".A")
    if a_path.exists():
        try:
            header = None
            for line in a_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("@TRNO"):
                    header = line
                    break
            if header:
                cols_u = {c.lstrip("@").strip().upper() for c in header.split()}
                if yield_var and yield_var.upper() not in cols_u:
                    yield_var = ""
                if laix_var and laix_var.upper() not in cols_u:
                    laix_var = None
            else:
                yield_var = ""
                laix_var = None
        except Exception:
            yield_var = ""
            laix_var = None
    else:
        yield_var = ""
        laix_var = None

    t_path_env = os.environ.get("DSSAT_OBS_T_PATH") if "DSSAT_OBS_T_PATH" in os.environ else None
    t_path_raw = str(t_path_env).strip() if t_path_env is not None else (str(cfg_paths.get("obs_t_path", "")).strip() or str(cfg_paths.get("wht_path", "")).strip())
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
    allow_missing_obs_files = str(os.environ.get("DSSAT_ALLOW_MISSING_OBS_FILES", "")).strip().lower() in {"1", "true", "yes", "y"} or bool(
        (cfg.get("observations", {}) or {}).get("allow_missing_obs_files", False)
    )
    wht_meas: dict[str, float] = {}
    wht_dates_by_trt: dict[int, list[int]] = {}
    wht_second = ""
    try:
        wht_meas, wht_dates_by_trt, wht_second = _extract_measured_from_wht(wht_path, trts, allow_missing=allow_missing_obs_files)
    except Exception:
        if not allow_missing_obs_files:
            raise
        wht_meas = {}
        wht_dates_by_trt = {}
        wht_second = ""

    a_meas = _extract_measured_from_obs_a(a_path, trts, yield_var, laix_var, allow_missing=allow_missing_obs_files)
    obs_trts_yield: set[int] | None = None
    obs_trts_laix: set[int] | None = None
    if str(yield_var).strip():
        y_prefix = f"{str(yield_var).strip().lower()}_t"
        obs_trts_yield = set()
        for k in a_meas.keys():
            if not str(k).startswith(y_prefix):
                continue
            t = _extract_trt_from_obs_name(k)
            if t is not None:
                obs_trts_yield.add(int(t))
    if laix_var:
        l_prefix = f"{str(laix_var).strip().lower()}_t"
        obs_trts_laix = set()
        for k in a_meas.keys():
            if not str(k).startswith(l_prefix):
                continue
            t = _extract_trt_from_obs_name(k)
            if t is not None:
                obs_trts_laix.add(int(t))

    (cwd / "dssat_trts.txt").write_text(",".join([str(int(t)) for t in trts]) + "\n", encoding="utf-8")
    _write_pest_out_ins(cwd / "pest_out.ins", trts, yield_var, laix_var, obs_trts_yield, obs_trts_laix, wht_dates_by_trt, wht_second)

    # Multi-start seeding (LHS)
    start_mode = os.environ.get("MGDA_START_MODE", "").strip().lower()
    start_count = int(os.environ.get("MGDA_START_COUNT", "1"))
    start_index = int(os.environ.get("MGDA_START_INDEX", "0"))
    if start_mode == "lhs" and start_count > 1:
        bounds_seed: dict[str, tuple[float, float]] = {
            "sh2o_15": (0.05, 0.40),
            "sh2o_30": (0.05, 0.40),
            "p1v": (0.0, 60.0),
            "p1d": (0.0, 200.0),
            "p5": (100.0, 999.0),
            "phint": (30.0, 150.0),
            "g1": (10.0, 50.0),
            "g2": (10.0, 80.0),
            "g3": (0.5, 8.0),
        }
        cfg_bounds = cfg.get("params", {}).get("bounds", {})
        for k, v in cfg_bounds.items():
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                k_l = str(k).strip().lower()
                mapped = param_map.get(k_l, k_l)
                bounds_seed[mapped] = (float(v[0]), float(v[1]))
        s = max(0, min(start_index, max(0, start_count - 1)))
        x = (s + 0.5) / float(start_count)
        params_seed: dict[str, float] = {}
        for k, (lb, ub) in bounds_seed.items():
            params_seed[k] = float(lb + x * (ub - lb))
        # Preserve any existing keys not in bounds
        try:
            existing = _read_params(cwd / "params.dat")
        except Exception:
            existing = {}
        for k, v in existing.items():
            params_seed.setdefault(k, float(v))
        (cwd / "params.dat").write_text("\n".join([f"{k} {params_seed[k]:.6f}" for k in sorted(params_seed.keys())]) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["DSSAT_KEEP_OUTPUTS"] = "1"
    env["DSSAT_CASE_DIR"] = str(dssat_dir)
    env["DSSAT_TRTS"] = ",".join([str(int(t)) for t in trts])
    env["MGDA_START_MODE"] = start_mode if start_mode else env.get("MGDA_START_MODE", "")
    env["MGDA_START_COUNT"] = str(start_count)
    env["MGDA_START_INDEX"] = str(start_index)
    if allow_missing_obs_files:
        env["DSSAT_ALLOW_MISSING_WHT_DATES"] = "1"
    geno_dir = dssat_dir / "GENOTYPE"
    cul_name = None
    inp = dssat_dir / "DSSAT48.INP"
    if inp.exists():
        for raw in inp.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not raw.startswith("CULTIVAR"):
                continue
            if ".CUL" not in raw.upper():
                continue
            for tok in raw.split():
                if tok.upper().endswith(".CUL"):
                    cul_name = tok.strip()
                    break
            break
    cul_path = None
    if cul_name:
        cand = geno_dir / cul_name
        if cand.exists():
            cul_path = cand
    if cul_path is None and geno_dir.exists():
        culs = sorted(geno_dir.glob("*.CUL"))
        if culs:
            cul_path = culs[0]
    if cul_path is not None:
        env["CUL_PATH"] = str(cul_path)
        env["WH_CUL_PATH"] = str(cul_path)
    subprocess.run(["python", str(run_model_path)], cwd=str(cwd), check=True, env=env)
    meas = dict(a_meas)
    meas.update(wht_meas)

    for p in ["Evaluate.OUT", "Summary.OUT", "WARNING.OUT"]:
        _try_unlink(dssat_dir / p)
    params = _read_params(cwd / "params.dat")

    pst = pyemu.utils.helpers.pst_from_io_files(
        tpl_files=["params.tpl"],
        in_files=["params.dat"],
        ins_files=["pest_out.ins"],
        out_files=["pest_out.dat"],
        pst_filename="ksas_mvp.pst",
    )

    pst.model_command = [f'python "{run_model_path}"']
    pst.control_data.noptmax = int(os.environ.get("PEST_NOPTMAX", "10"))
    pst.control_data.pestmode = "estimation"

    bounds = {
        "sh2o_15": (0.05, 0.40, "g_sh2o"),
        "sh2o_30": (0.05, 0.40, "g_sh2o"),
        "p1v": (0.0, 60.0, "g_cul_pheno"),
        "p1d": (0.0, 200.0, "g_cul_pheno"),
        "p5": (100.0, 999.0, "g_cul_pheno"),
        "phint": (30.0, 150.0, "g_cul_pheno"),
        "g1": (10.0, 50.0, "g_cul_grain"),
        "g2": (10.0, 80.0, "g_cul_grain"),
        "g3": (0.5, 8.0, "g_cul_grain"),
    }
    cfg_bounds = cfg.get("params", {}).get("bounds", {})
    for k, v in cfg_bounds.items():
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            k_l = str(k).strip().lower()
            mapped = param_map.get(k_l, k_l)
            bounds[mapped] = (float(v[0]), float(v[1]), str(v[2]))

    for p, (lb, ub, grp) in bounds.items():
        if p not in pst.parameter_data.index:
            continue
        pst.parameter_data.loc[p, "parlbnd"] = lb
        pst.parameter_data.loc[p, "parubnd"] = ub
        pst.parameter_data.loc[p, "pargp"] = grp
        pst.parameter_data.loc[p, "partrans"] = "none"
        pst.parameter_data.loc[p, "parval1"] = float(params.get(p, pst.parameter_data.loc[p, "parval1"]))

    pst.parameter_groups.index = pst.parameter_groups.pargpnme

    base_group = pst.parameter_groups.iloc[0].copy()
    group_defaults = {
        "derinclb": 0.0,
        "forcen": "switch",
        "derincmul": 2.0,
        "dermthd": "parabolic",
        "splitthresh": 1.0e-5,
        "splitreldiff": 0.5,
        "splitaction": "smaller",
    }

    group_specs = {
        "g_sh2o": ("absolute", 0.02),
        "g_cul_pheno": ("relative", 0.03),
        "g_cul_grain": ("relative", 0.05),
    }
    cfg_groups = cfg.get("params", {}).get("groups", {})
    for g, spec in cfg_groups.items():
        if isinstance(spec, dict) and "inctyp" in spec and "derinc" in spec:
            group_specs[str(g)] = (str(spec["inctyp"]), float(spec["derinc"]))

    for grp, (inctyp, derinc) in group_specs.items():
        if grp not in pst.parameter_groups.index:
            pst.parameter_groups.loc[grp, :] = base_group
            pst.parameter_groups.loc[grp, "pargpnme"] = grp
        pst.parameter_groups.loc[grp, "inctyp"] = inctyp
        pst.parameter_groups.loc[grp, "derinc"] = derinc
        for k, v in group_defaults.items():
            pst.parameter_groups.loc[grp, k] = v

    for oname, oval in meas.items():
        if oname in pst.observation_data.index:
            pst.observation_data.loc[oname, "obsval"] = float(oval)

    cfg_obs = cfg.get("observations", {})
    group_defs = cfg_obs.get("groups", {})
    weights_overrides = {str(k).strip().lower(): float(v) for k, v in cfg_obs.get("weights", {}).items()}
    mgda_cfg = (cfg.get("optimization", {}) or {}).get("mgda", {}) or {}
    sigma_prewhiten = bool(cfg_obs.get("sigma_prewhiten", mgda_cfg.get("sigma_prewhiten", mgda_cfg.get("sigma_whiten", False))))
    split_by_trt = _resolve_split(cfg, trts)
    yield_prefix = str(yield_var).strip().lower() if yield_var else ""
    laix_prefix = str(laix_var).strip().lower() if laix_var else ""
    group_variances = _calc_group_variances(meas, split_by_trt, group_defs, yield_prefix, laix_prefix)
    group_weights: dict[str, float] = {}
    for gname, var in group_variances.items():
        fallback = float(group_defs.get(gname, {}).get("weight", 1.0))
        if math.isfinite(var) and var > 0.0:
            base = float(1.0 / var)
        else:
            base = float(fallback)
        if sigma_prewhiten:
            try:
                sigma = float(group_defs.get(gname, {}).get("sigma", 1.0))
            except (TypeError, ValueError):
                sigma = 1.0
            if math.isfinite(sigma) and sigma > 0.0:
                base = float(base / (sigma * sigma))
        group_weights[gname] = float(base)

    for oname in pst.observation_data.index.astype(str).tolist():
        name_l = oname.lower()
        gname = _resolve_obs_group_name(oname, group_defs, yield_prefix, laix_prefix)
        pst.observation_data.loc[oname, "obgnme"] = str(gname)
        pst.observation_data.loc[oname, "weight"] = float(group_weights.get(gname, 1.0))
        if name_l in weights_overrides:
            pst.observation_data.loc[oname, "weight"] = float(weights_overrides[name_l])
        trt = _extract_trt_from_obs_name(oname)
        if (trt is not None) and (split_by_trt.get(int(trt)) == "valid"):
            pst.observation_data.loc[oname, "weight"] = 0.0
        if oname not in meas:
            pst.observation_data.loc[oname, "weight"] = 0.0

    if not any(float(w) > 0.0 for w in pst.observation_data.weight.astype(float).tolist()):
        raise RuntimeError("No usable observations: A/T files missing or empty after filtering")

    pst.write(cwd / "ksas_mvp.pst")


if __name__ == "__main__":
    main()
