from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from dssat_io import (
    extract_cultivar_code,
    load_project_config,
    pick_eval_value,
    read_eval_row,
    read_table_row,
    resolve_param_mapping,
    rewrite_cul_values,
)


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
        key = parts[0].strip()
        val = float(parts[1])
        params[key] = val
    return params


def _sh2o_token(value: float) -> str:
    v = max(0.001, min(0.999, float(value)))
    s = f"{v:.3f}"
    if s.startswith("0"):
        s = s[1:]
    return s


def _rewrite_initial_sh2o(filex_in: Path, filex_out: Path, sh2o_by_icbl: dict[int, float]) -> None:
    updates = [{"ICBL": int(k), "SH2O": float(v)} for k, v in sh2o_by_icbl.items()]
    _rewrite_fixed_block_from_template(
        filex_in,
        filex_out,
        "@C",
        ["ICBL"],
        updates,
        required_cols={"ICBL", "SH2O"},
    )


def _run_dssat(filex: str, trt: int, cwd: Path, cfg: dict) -> None:
    cfg_exe = cfg.get("paths", {}).get("dssat_exe", "")
    exe = Path(os.environ.get("DSSAT_EXE", cfg_exe or r"C:\DSSAT48\DSCSM048.EXE"))
    cmd = [str(exe), "C", filex, str(trt)]
    cp = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if cp.returncode != 0:
        raise RuntimeError(f"DSSAT failed: {cp.returncode}\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}")


def _choose_case_dir(cwd: Path, project_root: Path, cfg: dict) -> Path:
    env_dir = os.environ.get("DSSAT_CASE_DIR", "").strip()
    if env_dir:
        return Path(env_dir).resolve()
    cfg_dir = cfg.get("paths", {}).get("dssat_case_dir", "")
    if cfg_dir:
        return Path(cfg_dir).resolve()
    local = (cwd / "dssat_case").resolve()
    if local.exists():
        return local
    return (project_root / "data" / "dssat").resolve()


def _patch_cultivar_dir_in_inp_inh(dssat_dir: Path, cultivar_dir: Path) -> None:
    new_dir = str(cultivar_dir.resolve()) + "\\"
    targets = [dssat_dir / "DSSAT48.INP", dssat_dir / "DSSAT48.INH"]
    for p in targets:
        if not p.exists():
            continue
        raw = p.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        out: list[str] = []
        changed = False
        for line in raw:
            row = line.rstrip("\r\n")
            ending = line[len(row) :]
            if p.name.upper().endswith(".INP"):
                if row.startswith("CULTIVAR") and ".CUL" in row.upper() and "C:\\" in row:
                    idx = row.index("C:\\")
                    old_tail = row[idx:]
                    repl = new_dir.ljust(len(old_tail))[: len(old_tail)]
                    orig_len = len(row)
                    row = row[:idx] + repl
                    if len(row) != orig_len:
                        raise RuntimeError("DSSAT48.INP row length mismatch after path replace")
                    if row[idx : idx + len(old_tail)] != repl:
                        raise RuntimeError("DSSAT48.INP path slice mismatch after replace")
                    changed = True
            else:
                if ".CUL" in row.upper() and "C:\\" in row:
                    idx = row.index("C:\\")
                    old_tail = row[idx:]
                    repl = new_dir.ljust(len(old_tail))[: len(old_tail)]
                    orig_len = len(row)
                    row = row[:idx] + repl
                    if len(row) != orig_len:
                        raise RuntimeError("DSSAT48.INH row length mismatch after path replace")
                    if row[idx : idx + len(old_tail)] != repl:
                        raise RuntimeError("DSSAT48.INH path slice mismatch after replace")
                    changed = True
            out.append(row + ending)
        if changed:
            p.write_text("".join(out), encoding="utf-8")


def _parse_fixed_header_spans(header: str) -> dict[str, tuple[int, int]]:
    matches = list(re.finditer(r"\S+", header))
    cols = [m.group(0).lstrip("@").strip() for m in matches]
    return {c: (matches[i].start(), matches[i].end()) for i, c in enumerate(cols)}


def _format_like_field(existing: str, width: int, value: float) -> str:
    s = existing.strip()
    if not s:
        out = f"{value:>{width}.2f}"
    elif "." in s:
        decimals = len(s.split(".", 1)[1])
        out = f"{value:>{width}.{decimals}f}"
        stripped = out.strip()
        if s.startswith(".") or s.startswith("-."):
            if stripped.startswith("-0."):
                stripped = "-." + stripped[3:]
            elif stripped.startswith("0."):
                stripped = "." + stripped[2:]
            out = stripped.rjust(width)
    else:
        out = f"{int(round(value)):>{width}d}"
    if len(out) > width:
        raise RuntimeError(f"Value {value} does not fit width {width}")
    return out


def _apply_fixed_block_updates(
    raw: list[str],
    header_prefix: str,
    key_cols: list[str],
    updates: list[dict[str, float]],
    required_cols: set[str] | None = None,
) -> list[str]:
    out: list[str] = []
    in_block = False
    spans: dict[str, tuple[int, int]] = {}
    key_index = {tuple(str(u[k]).strip() for k in key_cols): u for u in updates}
    for line in raw:
        row = line.rstrip("\r\n")
        ending = line[len(row) :]
        if row.startswith(header_prefix):
            spans = _parse_fixed_header_spans(row)
            if required_cols and not required_cols.issubset(set(spans.keys())):
                out.append(line)
                in_block = False
                continue
            in_block = True
            out.append(line)
            continue
        if in_block:
            if row.startswith("*") or row.startswith("@") or not row.strip() or row.lstrip().startswith("!"):
                in_block = False
                out.append(line)
                continue
            if not spans:
                out.append(line)
                continue
            key = tuple(row[spans[c][0] : spans[c][1]].strip() for c in key_cols)
            upd = key_index.get(key)
            if upd is None:
                out.append(line)
                continue
            row_chars = list(row)
            orig_len = len(row)
            for c, v in upd.items():
                if c in key_cols:
                    continue
                if c not in spans:
                    continue
                a, b = spans[c]
                existing = row[a:b]
                width = b - a
                repl = _format_like_field(existing, width, float(v))
                row_chars[a:b] = list(repl)
            new_row = "".join(row_chars)
            if len(new_row) != orig_len:
                raise RuntimeError(f"Row length mismatch in fixed block: {len(new_row)} != {orig_len}")
            for c, v in upd.items():
                if c in key_cols or c not in spans:
                    continue
                a, b = spans[c]
                got = new_row[a:b].strip()
                want = _format_like_field(row[a:b], b - a, float(v)).strip()
                if got != want:
                    raise RuntimeError(f"Round-trip mismatch for {c} in fixed block: {got} != {want}")
            out.append(new_row + ending)
            continue
        out.append(line)
    return out


def _rewrite_fixed_block(
    path: Path,
    header_prefix: str,
    key_cols: list[str],
    updates: list[dict[str, float]],
    required_cols: set[str] | None = None,
) -> None:
    raw = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    out = _apply_fixed_block_updates(raw, header_prefix, key_cols, updates, required_cols)
    path.write_text("".join(out), encoding="utf-8")


def _rewrite_fixed_block_from_template(
    template_path: Path,
    output_path: Path,
    header_prefix: str,
    key_cols: list[str],
    updates: list[dict[str, float]],
    required_cols: set[str] | None = None,
) -> None:
    raw = template_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    out = _apply_fixed_block_updates(raw, header_prefix, key_cols, updates, required_cols)
    output_path.write_text("".join(out), encoding="utf-8")


def rewrite_wth_daily(wth_path: Path, updates_by_date: list[dict[str, float]]) -> None:
    _rewrite_fixed_block(wth_path, "@DATE", ["DATE"], updates_by_date)


def rewrite_sol_layers(sol_path: Path, updates_by_slb: list[dict[str, float]]) -> None:
    _rewrite_fixed_block(sol_path, "@SLB", ["SLB"], updates_by_slb)


def _parse_trts(value: str) -> list[int]:
    out: list[int] = []
    for tok in re.split(r"[\s,;]+", (value or "").strip()):
        if not tok:
            continue
        out.append(int(tok))
    if not out:
        raise ValueError("Empty DSSAT_TRTS")
    return out


def _extract_metrics_from_row(row: dict[str, str], var_codes: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for code in var_codes:
        code_u = str(code).strip().upper()
        if not code_u:
            continue
        v = pick_eval_value(row, code_u, prefer_suffix="S")
        if v is None:
            continue
        out[code_u.lower()] = float(v)
    return out


def _extract_eval_metrics(eval_path: Path, var_codes: list[str]) -> dict[str, float]:
    row = read_eval_row(eval_path)
    return _extract_metrics_from_row(row, var_codes)


def _extract_table_metrics(path: Path, var_codes: list[str]) -> dict[str, float]:
    row = read_table_row(path)
    return _extract_metrics_from_row(row, var_codes)


def _read_wht_dates_by_trt(wht_path: Path, trts: list[int]) -> dict[int, list[int]]:
    if not wht_path.exists():
        return {}
    lines = wht_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = None
    for line in lines:
        if line.startswith("@TRNO"):
            header = line
            break
    if not header:
        return {}

    cols = [c.lstrip("@").strip() for c in header.split()]
    if "TRNO" not in cols or "DATE" not in cols:
        return {}
    i_trno = cols.index("TRNO")
    i_date = cols.index("DATE")

    dates_by_trt: dict[int, list[int]] = {}
    wanted = {int(t) for t in trts}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("!") or line.startswith("@") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) <= max(i_trno, i_date):
            continue
        try:
            trno = int(parts[i_trno])
            date = int(parts[i_date])
        except ValueError:
            continue
        if int(trno) not in wanted:
            continue
        dates_by_trt.setdefault(int(trno), []).append(int(date))

    for trt, ds in list(dates_by_trt.items()):
        dates_by_trt[int(trt)] = sorted(set(int(d) for d in ds))

    return dates_by_trt


def _yyddd_to_year_doy(yyddd: int) -> tuple[int, int]:
    yy = int(yyddd) // 1000
    doy = int(yyddd) % 1000
    year = 1900 + yy if yy >= 30 else 2000 + yy
    return int(year), int(doy)


def _extract_plantgro_vars_at_dates(
    plantgro_path: Path, yyddd_dates: list[int], var_codes: list[str], allow_missing: bool | None = None
) -> dict[int, dict[str, float]]:
    if not yyddd_dates:
        return {}
    if not plantgro_path.exists():
        raise RuntimeError(f"PlantGro.OUT missing: {plantgro_path}")
    lines = plantgro_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = None
    data_start = 0
    for i, line in enumerate(lines):
        if line.startswith("@YEAR"):
            header = line
            data_start = i + 1
            break
    if not header:
        raise RuntimeError(f"PlantGro.OUT missing @YEAR header: {plantgro_path}")

    header_matches = list(re.finditer(r"\S+", header))
    cols = [m.group(0).lstrip("@").strip() for m in header_matches]
    starts = [m.start() for m in header_matches]
    ends = [m.end() for m in header_matches]
    need = {"YEAR", "DOY"} | {str(v).strip().upper() for v in var_codes if str(v).strip()}
    missing_vars = sorted([v for v in need if v not in set(str(c).strip().upper() for c in cols)])
    if {"YEAR", "DOY"} & set(missing_vars):
        raise RuntimeError(f"PlantGro.OUT columns missing {sorted({'YEAR','DOY'})}: {cols}")
    missing_series = [v for v in missing_vars if v not in {"YEAR", "DOY"}]
    if missing_series:
        raise RuntimeError(f"PlantGro.OUT columns missing {missing_series} for dates {yyddd_dates}: {cols}")
    i_year = cols.index("YEAR")
    i_doy = cols.index("DOY")
    col_upper = [str(c).strip().upper() for c in cols]
    var_to_idx: dict[str, int] = {}
    for v in var_codes:
        v_u = str(v).strip().upper()
        if not v_u:
            continue
        if v_u in col_upper:
            var_to_idx[v_u] = int(col_upper.index(v_u))

    vals_by_year: dict[int, dict[int, dict[str, float]]] = {}

    def _slice_by_starts(raw: str, idx: int) -> str:
        if idx < 0 or idx >= len(starts):
            return ""
        a = int(starts[idx])
        b = int(starts[idx + 1]) if (idx + 1) < len(starts) else None
        if a >= len(raw):
            return ""
        return raw[a:b].strip() if b is not None else raw[a:].strip()

    def _slice_by_ends(raw: str, idx: int) -> str:
        if idx < 0 or idx >= len(ends):
            return ""
        a = int(ends[idx - 1]) if idx > 0 else 0
        b = int(ends[idx])
        if a >= len(raw):
            return ""
        return raw[a:b].strip()

    for line in lines[data_start:]:
        if not line.strip() or line.lstrip().startswith("!") or line.startswith("*") or line.startswith("@"):
            continue

        raw = line.replace("\x00", " ")
        parsed = False
        try:
            parts = re.split(r"\s+", raw.strip())
            if len(parts) > max([i_year, i_doy] + list(var_to_idx.values())):
                y = int(parts[i_year])
                doy = int(parts[i_doy])
                if y < 100:
                    y = 1900 + y if y >= 30 else 2000 + y
                vals: dict[str, float] = {}
                for v_u, idx in var_to_idx.items():
                    vals[v_u.lower()] = float(parts[int(idx)])
                parsed = True
        except ValueError:
            parsed = False

        if not parsed:
            try:
                y = int(_slice_by_starts(raw, i_year))
                doy = int(_slice_by_starts(raw, i_doy))
                if y < 100:
                    y = 1900 + y if y >= 30 else 2000 + y
                vals = {}
                for v_u, idx in var_to_idx.items():
                    val_s = _slice_by_starts(raw, int(idx))
                    try:
                        vals[v_u.lower()] = float(val_s)
                    except ValueError:
                        vals[v_u.lower()] = float(_slice_by_ends(raw, int(idx)))
                parsed = True
            except ValueError:
                parsed = False

        if not parsed:
            continue

        if vals:
            vals_by_year.setdefault(int(y), {})[int(doy)] = {k: float(v) for k, v in vals.items()}

    out: dict[int, dict[str, float]] = {}
    missing: list[int] = []
    max_back_days = 7
    for d in yyddd_dates:
        year, doy = _yyddd_to_year_doy(int(d))
        recs = vals_by_year.get(int(year))
        if not recs:
            missing.append(int(d))
            continue
        if int(doy) in recs:
            out[int(d)] = recs[int(doy)]
            continue
        prev_doys = [dd for dd in recs.keys() if int(dd) <= int(doy)]
        if not prev_doys:
            missing.append(int(d))
            continue
        dd = int(max(prev_doys))
        if int(doy) - int(dd) > int(max_back_days):
            missing.append(int(d))
            continue
        out[int(d)] = recs[int(dd)]

    if missing:
        if allow_missing is None:
            allow_missing = os.environ.get("DSSAT_ALLOW_MISSING_WHT_DATES", "").strip().lower() in {"1", "true", "yes", "y"}
        if not allow_missing:
            raise RuntimeError(f"PlantGro.OUT missing requested dates {missing} in {plantgro_path}")
        else:
            # PEST expects an output line to exist for every expected date. Provide zeros if missing.
            for d in missing:
                out[int(d)] = {v: 0.0 for v in var_codes}

    return out


def _extract_cultivar_code(filex_path: Path) -> str:
    return extract_cultivar_code(filex_path)


def _rewrite_cul_params(cul_path: Path, cultivar_code: str, updates: dict[str, float]) -> None:
    rewrite_cul_values(cul_path, cultivar_code, {str(k).strip().upper(): float(v) for k, v in updates.items()})


def _infer_cul_path_from_inp(dssat_dir: Path, cfg: dict) -> Path | None:
    cfg_paths = cfg.get("paths", {})
    inp_name = str(cfg_paths.get("inp_name", "")).strip() or "DSSAT48.INP"
    inp_path = dssat_dir / inp_name
    if not inp_path.exists():
        inp_path = dssat_dir / "DSSAT48.INP"
        if not inp_path.exists():
            return None

    cul_file_name = None
    cul_src_dir = None
    for raw in inp_path.read_text(encoding="utf-8", errors="ignore").splitlines():
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

    geno_dir = dssat_dir / "GENOTYPE"
    if cul_file_name and geno_dir.exists():
        in_case = geno_dir / cul_file_name
        if in_case.exists():
            return in_case

    if cul_src_dir and cul_file_name:
        try:
            src = (Path(cul_src_dir) / cul_file_name).resolve()
            if src.exists():
                return src
        except Exception:
            return None

    return None


def main() -> None:
    cwd = Path.cwd()
    params_path = Path(os.environ.get("PARAMS_PATH", str(cwd / "params.dat")))
    params = _read_params(params_path)

    trts_env = os.environ.get("DSSAT_TRTS", "").strip()
    if trts_env:
        trts = _parse_trts(trts_env)
    else:
        trts_path = cwd / "dssat_trts.txt"
        if trts_path.exists():
            trts = _parse_trts(trts_path.read_text(encoding="utf-8", errors="ignore"))
        else:
            trts = [int(os.environ.get("DSSAT_TRT", "1"))]

    keep_outputs = os.environ.get("DSSAT_KEEP_OUTPUTS", "0").strip().lower() in {"1", "true", "yes", "y"}

    project_root = Path(__file__).resolve().parents[1]
    cfg = _load_project_config(project_root)
    dssat_dir = _choose_case_dir(cwd, project_root, cfg)
    param_map, _ = resolve_param_mapping(cfg, dssat_dir)
    if param_map:
        mapped_params: dict[str, float] = {}
        for k, v in params.items():
            k_l = str(k).strip().lower()
            mapped = param_map.get(k_l, k_l)
            mapped_params[mapped] = float(v)
        params = mapped_params

    filex_name = cfg.get("scenario", {}).get("filex", "KSAS8101.WHX")
    base_filex = cfg.get("scenario", {}).get("base_filex", "KSAS8101_base.WHX")
    base = dssat_dir / base_filex
    if not base.exists():
        raise FileNotFoundError(f"Missing base FileX template: {base}")

    live_filex = dssat_dir / filex_name
    if not live_filex.exists():
        raise FileNotFoundError(f"Missing live FileX: {live_filex}")
    live_original = live_filex.read_text(encoding="utf-8", errors="ignore")

    cul_env = os.environ.get("CUL_PATH", "").strip() or os.environ.get("WH_CUL_PATH", "").strip()
    if cul_env:
        cul_path = Path(cul_env)
    else:
        cfg_paths = cfg.get("paths", {})
        cfg_cul = str(cfg_paths.get("cul_path", "")).strip() or str(cfg_paths.get("wh_cul_path", "")).strip()
        if cfg_cul:
            cul_path = Path(cfg_cul)
        else:
            inferred = _infer_cul_path_from_inp(dssat_dir, cfg)
            if inferred is not None:
                cul_path = inferred
            else:
                geno_dir = dssat_dir / "GENOTYPE"
                culs = sorted(geno_dir.glob("*.CUL")) if geno_dir.exists() else []
                cul_path = culs[0] if culs else Path(r"C:\DSSAT48\Genotype\WHCER048.CUL")
    cul_original = cul_path.read_text(encoding="utf-8", errors="ignore")
    cultivar_code = _extract_cultivar_code(live_filex)

    if cul_path.exists() and (dssat_dir / "GENOTYPE").exists() and cul_path.parent.resolve() == (dssat_dir / "GENOTYPE").resolve():
        _patch_cultivar_dir_in_inp_inh(dssat_dir, cul_path.parent)

    cfg_paths = cfg.get("paths", {})
    t_path_raw = str(cfg_paths.get("obs_t_path", "")).strip() or str(cfg_paths.get("wht_path", "")).strip()
    wht_dates_by_trt: dict[int, list[int]] = {}
    if t_path_raw:
        wht_path = Path(t_path_raw)
        if not wht_path.is_absolute():
            wht_path = dssat_dir / wht_path
        if wht_path.exists():
            wht_dates_by_trt = _read_wht_dates_by_trt(wht_path, trts)

    adapter = cfg.get("adapter", {})
    wth_updates = adapter.get("wth_updates", [])
    sol_updates = adapter.get("sol_updates", [])
    wth_path_raw = str(adapter.get("wth_path", "")).strip()
    sol_path_raw = str(adapter.get("sol_path", "")).strip()
    wth_path = Path(wth_path_raw) if wth_path_raw else None
    sol_path = Path(sol_path_raw) if sol_path_raw else None
    if wth_path and not wth_path.is_absolute():
        wth_path = dssat_dir / wth_path
    if sol_path and not sol_path.is_absolute():
        sol_path = dssat_dir / sol_path

    wth_original = None
    sol_original = None
    if wth_updates:
        if not wth_path or not wth_path.exists():
            raise FileNotFoundError("WTH path not found for wth_updates")
        wth_original = wth_path.read_text(encoding="utf-8", errors="ignore")
        rewrite_wth_daily(wth_path, wth_updates)
    if sol_updates:
        if not sol_path or not sol_path.exists():
            raise FileNotFoundError("SOL path not found for sol_updates")
        sol_original = sol_path.read_text(encoding="utf-8", errors="ignore")
        rewrite_sol_layers(sol_path, sol_updates)

    for p in ["Evaluate.OUT", "Summary.OUT", "PlantGro.OUT", "PlantGr2.OUT", "WARNING.OUT"]:
        _try_unlink(dssat_dir / p)

    has_sh2o = any(str(k).lower().startswith("sh2o_") for k in params.keys())
    sh2o_by_icbl = {15: params.get("sh2o_15", 0.205), 30: params.get("sh2o_30", 0.170)} if has_sh2o else {}

    cul_updates: dict[str, float] = {}
    cfg_cul_params = cfg.get("cul", {}).get("params", None)
    if isinstance(cfg_cul_params, list) and cfg_cul_params:
        wanted = []
        for x in cfg_cul_params:
            x_l = str(x).strip().lower()
            if not x_l:
                continue
            wanted.append(param_map.get(x_l, x_l))
    else:
        wanted = [str(k).strip().lower() for k in params.keys() if not str(k).lower().startswith("sh2o_")]
    for k in wanted:
        if k in params:
            cul_updates[k] = float(params[k])
    metrics_cfg = cfg.get("metrics", {}) or cfg.get("variables", {}) or {}
    
    # Abstract yields
    yield_var_cfg = str(metrics_cfg.get("yield_var", "YIELD")).strip().upper()
    yield_code = yield_var_cfg if yield_var_cfg != "YIELD" else "HWAM"
    
    laix_code = str(metrics_cfg.get("laix_var", "LAIX")).strip().upper()
    cfg_paths = cfg.get("paths", {})
    a_path_env = os.environ.get("DSSAT_OBS_A_PATH") if "DSSAT_OBS_A_PATH" in os.environ else None
    a_path_raw = str(a_path_env).strip() if a_path_env is not None else (str(cfg_paths.get("obs_a_path", "")).strip() or str(cfg_paths.get("wha_path", "")).strip())
    a_path = None
    if a_path_raw and not str(a_path_raw).strip().lower().startswith("__skip__"):
        a_path = Path(a_path_raw)
        if not a_path.is_absolute():
            a_path = dssat_dir / a_path
    if a_path is None:
        suf = live_filex.suffix
        if suf.upper().endswith("X") and len(suf) >= 2:
            a_path = live_filex.with_suffix(suf[:-1] + "A")
        else:
            a_path = live_filex.with_suffix(".A")
    if not a_path.exists():
        yield_code = ""
        laix_code = ""
    else:
        try:
            header = None
            for line in a_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("@TRNO"):
                    header = line
                    break
            if not header:
                yield_code = ""
                laix_code = ""
            else:
                cols_u = {c.lstrip("@").strip().upper() for c in header.split()}
                if yield_code and yield_code not in cols_u:
                    yield_code = ""
                if laix_code and laix_code not in cols_u:
                    laix_code = ""
        except Exception:
            yield_code = ""
            laix_code = ""
    
    # In run_model.py, we still use the configured names (or HWAM fallback) to query dssat_io. 
    # dssat_io's pick_eval_value will handle the HWAM -> CWAM -> PRCM internal fallback.
    var_codes = [c for c in [yield_code, laix_code] if c]
    allow_missing_dates = os.environ.get("DSSAT_ALLOW_MISSING_WHT_DATES", "").strip().lower() in {"1", "true", "yes", "y"}
    if not allow_missing_dates:
        allow_missing_dates = bool((cfg.get("observations", {}) or {}).get("allow_missing_obs_files", False))
    try:
        if has_sh2o:
            _rewrite_initial_sh2o(base, live_filex, sh2o_by_icbl)
        if cul_updates:
            _rewrite_cul_params(cul_path, cultivar_code, cul_updates)

        metrics_by_trt: dict[int, dict[str, float]] = {}
        for trt in trts:
            for p in ["Evaluate.OUT", "Summary.OUT", "PlantGro.OUT", "PlantGr2.OUT", "WARNING.OUT"]:
                _try_unlink(dssat_dir / p)
            _run_dssat(filex_name, int(trt), dssat_dir, cfg)
            eval_path = dssat_dir / "Evaluate.OUT"
            m = _extract_eval_metrics(eval_path, var_codes)
            summary_path = dssat_dir / "Summary.OUT"
            if summary_path.exists():
                try:
                    m_summary = _extract_table_metrics(summary_path, var_codes)
                    for k, v in m_summary.items():
                        if k not in m:
                            m[k] = v
                except Exception:
                    pass

            if int(trt) in wht_dates_by_trt and wht_dates_by_trt[int(trt)]:
                plantgro_path = dssat_dir / "PlantGro.OUT"
                t_vars_cfg = metrics_cfg.get("t_vars", None)
                if isinstance(t_vars_cfg, list) and t_vars_cfg:
                    t_vars = [str(v).strip().upper() for v in t_vars_cfg if str(v).strip()]
                else:
                    t_vars = ["LAID", "LWAD", "SWAD"]
                try:
                    ts = _extract_plantgro_vars_at_dates(
                        plantgro_path, wht_dates_by_trt[int(trt)], t_vars, allow_missing=allow_missing_dates
                    )
                except RuntimeError as e:
                    raise RuntimeError(f"[TRT {int(trt)}] {e}")
                for d, vals in ts.items():
                    for k, v in vals.items():
                        m[f"{str(k).strip().lower()}_d{int(d)}"] = float(v)

            metrics_by_trt[int(trt)] = m
    finally:
        live_filex.write_text(live_original, encoding="utf-8")
        cul_path.write_text(cul_original, encoding="utf-8")
        if wth_original is not None and wth_path:
            wth_path.write_text(wth_original, encoding="utf-8")
        if sol_original is not None and sol_path:
            sol_path.write_text(sol_original, encoding="utf-8")
        if not keep_outputs:
            for p in ["Evaluate.OUT", "Summary.OUT", "PlantGro.OUT", "PlantGr2.OUT", "WARNING.OUT"]:
                _try_unlink(dssat_dir / p)

    lines: list[str] = []
    if len(trts) == 1 and not trts_env:
        t0 = trts[0]
        m = metrics_by_trt[int(t0)]
        if yield_code and yield_code.lower() in m:
            lines.append(f"{yield_code.lower()} {m[yield_code.lower()]:.6f} ")
        if laix_code and laix_code.lower() in m:
            lines.append(f"{laix_code.lower()} {m[laix_code.lower()]:.6f} ")
        out_text = "\n".join(lines) + "\n"
    else:
        for trt in trts:
            m = metrics_by_trt[int(trt)]
            if yield_code and yield_code.lower() in m:
                lines.append(f"{yield_code.lower()}_t{int(trt):02d} {m[yield_code.lower()]:.6f} ")
            if laix_code and laix_code.lower() in m:
                lines.append(f"{laix_code.lower()}_t{int(trt):02d} {m[laix_code.lower()]:.6f} ")
            if int(trt) in wht_dates_by_trt and wht_dates_by_trt[int(trt)]:
                for d in wht_dates_by_trt[int(trt)]:
                    laid_key = f"laid_d{int(d)}"
                    if laid_key in m:
                        lines.append(f"laid_t{int(trt):02d}_d{int(d)} {m[laid_key]:.6f} ")
                    for extra in ["lwad", "swad"]:
                        k2 = f"{extra}_d{int(d)}"
                        if k2 in m:
                            lines.append(f"{extra}_t{int(trt):02d}_d{int(d)} {m[k2]:.6f} ")
        out_text = "\n".join(lines) + "\n"

    (cwd / "pest_out.dat").write_text(out_text, encoding="utf-8")


if __name__ == "__main__":
    main()
