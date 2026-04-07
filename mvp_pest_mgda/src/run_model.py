from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import random
import re
import subprocess
import time
from pathlib import Path

from calibration_core.fixed_width import rewrite_initial_sh2o, rewrite_sol_layers, rewrite_wth_daily
from pest_runner import (
    ProtocolExecutionContext,
    ProtocolIssue,
    build_contract_report_payload,
    build_protocol_execution,
    build_run_manifest_payload,
    load_runtime_request_env,
    resolve_protocol_options,
    write_contract_report,
    write_run_manifest,
)
from result_schema import MetricsByTreatment, TreatmentMetrics, build_pest_output_text
from case_runtime import (
    CaseRuntime,
    RuntimeFileState,
    ensure_case_support_files,
    ensure_local_runtime,
    ensure_nonempty_cultivar_file,
    infer_cul_path_from_inp,
    patch_cultivar_dir_in_inp_inh,
    resolve_case_runtime,
    resolve_case_dir,
    resolve_cultivar_path,
    resolve_metrics_cfg,
    resolve_summary_var_codes,
    resolve_t_vars,
    resolve_runtime_file_state,
)
from dssat_io import (
    extract_cultivar_code,
    load_project_config,
    pick_eval_value,
    read_eval_row,
    read_table_row,
    resolve_crop_family,
    resolve_dssat_exe_path,
    resolve_dssat_genotype_dir,
    resolve_param_mapping,
    resolve_project_config_path,
    rewrite_cul_values,
)


OUTPUT_FILES = ["Evaluate.OUT", "Summary.OUT", "PlantGro.OUT", "PlantGr2.OUT", "WARNING.OUT"]


def append_run_stats(*, cwd: Path, trts: list[int], treatment_calls: int, duration_sec: float, status: str) -> None:
    stats_path_raw = str(os.environ.get("DSSAT_RUN_STATS_PATH", "")).strip()
    if not stats_path_raw:
        return
    stats_path = Path(stats_path_raw).resolve()
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cwd": str(cwd),
        "status": str(status),
        "trt_count_requested": len(trts),
        "treatment_calls": int(treatment_calls),
        "dssat_calls": int(treatment_calls),
        "duration_sec": float(duration_sec),
    }
    with open(stats_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _apply_runtime_request(runtime_request_path: str) -> Path | None:
    request_path_raw = str(runtime_request_path).strip() or str(os.environ.get("AR_RUNTIME_REQUEST_PATH", "")).strip()
    if not request_path_raw:
        return None
    request_path = Path(request_path_raw).resolve()
    os.environ.update(load_runtime_request_env(request_path))
    os.environ["AR_RUNTIME_REQUEST_PATH"] = str(request_path)
    return request_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-request", default="")
    args, _ = parser.parse_known_args()
    return args


@dataclass(frozen=True)
class PreparedCaseRun:
    cfg: dict
    project_config_path: Path | None
    dssat_dir: Path
    filex_name: str
    trts: list[int]
    case_runtime: CaseRuntime
    file_state: RuntimeFileState
    keep_outputs: bool
    base: Path
    live_filex: Path
    cul_path: Path
    cultivar_code: str
    trts_env: str


def _resolve_run_id(cwd: Path) -> str:
    return str(os.environ.get("AR_RUN_ID", "")).strip() or cwd.name


def _resolve_requested_summary_codes(cfg: dict) -> list[str]:
    metrics_cfg = resolve_metrics_cfg(cfg)
    yield_code = str(metrics_cfg.get("yield_var", "YIELD")).strip().upper()
    if yield_code == "YIELD":
        yield_code = "HWAM"
    laix_code = str(metrics_cfg.get("laix_var", "LAIX")).strip().upper()
    return resolve_summary_var_codes(
        yield_code,
        laix_code,
        env_extra_summary_vars=os.environ.get("DSSAT_EXTRA_SUMMARY_VARS", ""),
    )


def _resolve_split_assignments(cfg: dict, trts: list[int]) -> dict[int, str]:
    split_cfg = cfg.get("split", {})
    mode = str(split_cfg.get("mode", "trt")).strip().lower()
    all_trts = [int(trt) for trt in trts]
    train = {int(trt) for trt in (split_cfg.get("train_trts") or []) if str(trt).strip()}
    valid = {int(trt) for trt in (split_cfg.get("valid_trts") or []) if str(trt).strip()}

    ratio = None
    if "valid_ratio" in split_cfg:
        try:
            ratio = float(split_cfg.get("valid_ratio"))
        except (TypeError, ValueError):
            ratio = None
    if ratio is None and not train and not valid and len(all_trts) > 1:
        ratio = 0.2

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

    return {int(trt): ("valid" if int(trt) in valid else "train") for trt in all_trts}


def _build_runtime_manifest_payload(prepared: PreparedCaseRun, cwd: Path) -> dict[str, object]:
    project_root = Path(__file__).resolve().parents[1]
    output_files = [name for name in OUTPUT_FILES if (prepared.dssat_dir / name).exists()]
    bounds_preview_path = cwd / "parameter_bounds_preview.csv"
    split_assignments = _resolve_split_assignments(prepared.cfg, prepared.trts)
    context = ProtocolExecutionContext(
        run_id=_resolve_run_id(cwd),
        crop=resolve_crop_family(prepared.cfg, prepared.dssat_dir),
        runtime_dir=cwd,
        case_dir=prepared.dssat_dir,
        project_root=project_root,
        project_config_path=prepared.project_config_path,
        filex_name=prepared.filex_name,
        trts=tuple(int(trt) for trt in prepared.trts),
    )
    protocol = resolve_protocol_options(
        keep_outputs=prepared.keep_outputs,
        allow_missing_wht_dates=prepared.case_runtime.output.allow_missing_dates,
        split_assignments=split_assignments,
    )
    execution = build_protocol_execution(cwd=cwd, env=os.environ)
    return build_run_manifest_payload(
        context,
        protocol=protocol,
        execution=execution,
        scenario={
            "filex_name": prepared.filex_name,
            "base_filex_name": prepared.base.name,
            "trts": [int(trt) for trt in prepared.trts],
        },
        paths={
            "case_dir": prepared.dssat_dir,
            "params_path": Path(os.environ.get("PARAMS_PATH", str(cwd / "params.dat"))),
            "bounds_preview_path": bounds_preview_path,
            "cul_path": prepared.cul_path,
            "obs_a_path": prepared.case_runtime.observation.obs_a_path,
            "obs_wht_path": prepared.case_runtime.observation.obs_wht_path,
            "dssat_exe": str((prepared.cfg.get("paths", {}) or {}).get("dssat_exe", "")),
            "pest_output_path": cwd / "pest_out.dat",
            "runtime_request_path": str(os.environ.get("AR_RUNTIME_REQUEST_PATH", "")).strip(),
        },
        resolved_output={
            "summary_metrics": list(prepared.case_runtime.output.var_codes),
            "t_vars": list(prepared.case_runtime.output.t_vars),
            "wht_dates_by_trt": {
                str(int(trt)): [int(date) for date in dates]
                for trt, dates in sorted(prepared.case_runtime.observation.wht_dates_by_trt.items())
            },
            "available_output_files": output_files,
        },
    )


def _build_contract_report(prepared: PreparedCaseRun, cwd: Path) -> dict[str, object]:
    metrics_cfg = resolve_metrics_cfg(prepared.cfg)
    requested_summary_codes = _resolve_requested_summary_codes(prepared.cfg)
    requested_t_vars = resolve_t_vars(metrics_cfg)
    resolved_summary_codes = list(prepared.case_runtime.output.var_codes)
    resolved_t_vars = list(prepared.case_runtime.output.t_vars)
    split_assignments = _resolve_split_assignments(prepared.cfg, prepared.trts)
    missing_summary = [code for code in requested_summary_codes if code not in resolved_summary_codes]
    missing_treatment_dates = sorted(
        int(trt)
        for trt in prepared.trts
        if requested_t_vars and not prepared.case_runtime.observation.wht_dates_by_trt.get(int(trt))
    )
    issues: list[ProtocolIssue] = []
    if missing_summary:
        issues.append(
            ProtocolIssue(
                code="missing_summary_metrics",
                severity="warning",
                message="Requested summary metrics are not fully available in the resolved observation contract.",
                details={"metrics": missing_summary},
            )
        )
    obs_wht_path = prepared.case_runtime.observation.obs_wht_path
    if requested_t_vars and (obs_wht_path is None or not obs_wht_path.exists()):
        issues.append(
            ProtocolIssue(
                code="missing_wht_observations",
                severity="warning",
                message="Timeseries metrics were requested but the observation T/WHT file is missing.",
                details={"requested_t_vars": requested_t_vars},
            )
        )
    elif missing_treatment_dates:
        issues.append(
            ProtocolIssue(
                code="missing_wht_dates",
                severity="warning",
                message="Some treatments do not have observation dates in the resolved T/WHT contract.",
                details={"trts": missing_treatment_dates},
            )
        )
    context = ProtocolExecutionContext(
        run_id=_resolve_run_id(cwd),
        crop=resolve_crop_family(prepared.cfg, prepared.dssat_dir),
        runtime_dir=cwd,
        case_dir=prepared.dssat_dir,
        project_root=Path(__file__).resolve().parents[1],
        project_config_path=prepared.project_config_path,
        filex_name=prepared.filex_name,
        trts=tuple(int(trt) for trt in prepared.trts),
    )
    protocol = resolve_protocol_options(
        keep_outputs=prepared.keep_outputs,
        allow_missing_wht_dates=prepared.case_runtime.output.allow_missing_dates,
        split_assignments=split_assignments,
    )
    execution = build_protocol_execution(cwd=cwd, env=os.environ)
    bounds_preview_path = cwd / "parameter_bounds_preview.csv"
    split_counts: dict[str, int] = {}
    for split_name in split_assignments.values():
        split_counts[str(split_name)] = split_counts.get(str(split_name), 0) + 1
    return build_contract_report_payload(
        context,
        status="degraded" if issues else "ok",
        requested={
            "summary_metrics": requested_summary_codes,
            "t_vars": requested_t_vars,
            "yield_var": str(metrics_cfg.get("yield_var", "YIELD")).strip().upper() or "YIELD",
            "laix_var": str(metrics_cfg.get("laix_var", "LAIX")).strip().upper() or "LAIX",
            "trts": [int(trt) for trt in prepared.trts],
        },
        resolved={
            "summary_metrics": resolved_summary_codes,
            "t_vars": resolved_t_vars,
            "allow_missing_dates": bool(prepared.case_runtime.output.allow_missing_dates),
            "wht_dates_by_trt": {
                str(int(trt)): [int(date) for date in dates]
                for trt, dates in sorted(prepared.case_runtime.observation.wht_dates_by_trt.items())
            },
        },
        paths={
            "runtime_dir": cwd,
            "obs_a_path": prepared.case_runtime.observation.obs_a_path,
            "obs_wht_path": prepared.case_runtime.observation.obs_wht_path,
            "case_dir": prepared.dssat_dir,
            "bounds_preview_path": bounds_preview_path,
        },
        protocol=protocol,
        execution=execution,
        issues=issues,
        summary={
            "issue_count": len(issues),
            "missing_summary_metrics": missing_summary,
            "missing_wht_treatments": missing_treatment_dates,
            "split_counts": split_counts,
            "parameter_bounds_preview_present": bounds_preview_path.exists(),
        },
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


def _kill_dssat_processes(exe: Path) -> None:
    if os.environ.get("DSSAT_SKIP_TASKKILL", "").strip().lower() in {"1", "true", "yes", "y"}:
        return
    image_name = exe.name.strip()
    if not image_name:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", image_name],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return


def _load_project_config(project_root: Path) -> dict:
    return load_project_config(project_root, crop=os.environ.get("PROJECT_CROP", ""))


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


def _run_dssat(filex: str, trt: int, cwd: Path, cfg: dict) -> None:
    exe = resolve_dssat_exe_path(Path(__file__).resolve().parents[1], cfg=cfg)
    cmd = [str(exe), "C", filex, str(trt)]
    last_error = None
    for attempt in range(3):
        _kill_dssat_processes(exe)
        _try_unlink(cwd / "LUN.LST", tries=5, sleep_s=0.1)
        cp = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
        if cp.returncode == 0:
            return
        last_error = RuntimeError(f"DSSAT failed: {cp.returncode}\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}")
        stderr_u = (cp.stderr or "").upper()
        if "LUN.LST" not in stderr_u and "SEVERE (38)" not in stderr_u:
            break
        _kill_dssat_processes(exe)
        time.sleep(0.2 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _choose_case_dir(cwd: Path, project_root: Path, cfg: dict) -> Path:
    return resolve_case_dir(cwd, project_root, cfg, env_case_dir=os.environ.get("DSSAT_CASE_DIR", ""))




def _parse_trts(value: str) -> list[int]:
    out: list[int] = []
    for tok in re.split(r"[\s,;]+", (value or "").strip()):
        if not tok:
            continue
        out.append(int(tok))
    if not out:
        raise ValueError("Empty DSSAT_TRTS")
    return out


def _extract_metrics_from_row(row: dict[str, str], var_codes: list[str]) -> TreatmentMetrics:
    out: TreatmentMetrics = {}
    for code in var_codes:
        code_u = str(code).strip().upper()
        if not code_u:
            continue
        v = pick_eval_value(row, code_u, prefer_suffix="S")
        if v is None:
            continue
        out[code_u.lower()] = float(v)
    return out


def _extract_eval_metrics(eval_path: Path, var_codes: list[str]) -> TreatmentMetrics:
    row = read_eval_row(eval_path)
    return _extract_metrics_from_row(row, var_codes)


def _extract_table_metrics(path: Path, var_codes: list[str]) -> TreatmentMetrics:
    row = read_table_row(path)
    return _extract_metrics_from_row(row, var_codes)


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
        # PEST expects an output line to exist for every expected date. Provide zeros if missing.
        for d in missing:
            out[int(d)] = {v: 0.0 for v in var_codes}

    return out



def _extract_cultivar_code(filex_path: Path) -> str:
    return extract_cultivar_code(filex_path)


def _rewrite_cul_params(cul_path: Path, cultivar_code: str, updates: dict[str, float]) -> None:
    rewrite_cul_values(cul_path, cultivar_code, {str(k).strip().upper(): float(v) for k, v in updates.items()})


def _clear_output_files(dssat_dir: Path) -> None:
    for name in OUTPUT_FILES:
        _try_unlink(dssat_dir / name)


def execute_treatment(trt: int, filex_name: str, dssat_dir: Path, cfg: dict, case_runtime: CaseRuntime) -> TreatmentMetrics:
    _clear_output_files(dssat_dir)
    _run_dssat(filex_name, int(trt), dssat_dir, cfg)
    eval_path = dssat_dir / "Evaluate.OUT"
    metrics = _extract_eval_metrics(eval_path, case_runtime.output.var_codes)
    summary_path = dssat_dir / "Summary.OUT"
    if summary_path.exists():
        try:
            summary_metrics = _extract_table_metrics(summary_path, case_runtime.output.var_codes)
            for key, value in summary_metrics.items():
                if key not in metrics:
                    metrics[key] = value
        except Exception:
            pass

    dates = case_runtime.observation.wht_dates_by_trt.get(int(trt), [])
    if dates:
        plantgro_path = dssat_dir / "PlantGro.OUT"
        try:
            timeseries = _extract_plantgro_vars_at_dates(
                plantgro_path,
                dates,
                case_runtime.output.t_vars,
                allow_missing=case_runtime.output.allow_missing_dates,
            )
        except RuntimeError as e:
            raise RuntimeError(f"[TRT {int(trt)}] {e}")
        for date, values in timeseries.items():
            for key, value in values.items():
                metrics[f"{str(key).strip().lower()}_d{int(date)}"] = float(value)

    return metrics


def _restore_runtime_files(file_state: RuntimeFileState) -> None:
    file_state.live_filex_path.write_text(file_state.live_filex_original, encoding="utf-8")
    file_state.cul_path.write_text(file_state.cul_original, encoding="utf-8")
    if file_state.wth_original is not None and file_state.wth_path:
        file_state.wth_path.write_text(file_state.wth_original, encoding="utf-8")
    if file_state.sol_original is not None and file_state.sol_path:
        file_state.sol_path.write_text(file_state.sol_original, encoding="utf-8")


def execute_case(
    base: Path,
    live_filex: Path,
    cul_path: Path,
    cultivar_code: str,
    filex_name: str,
    dssat_dir: Path,
    cfg: dict,
    trts: list[int],
    case_runtime: CaseRuntime,
    file_state: RuntimeFileState,
    keep_outputs: bool,
) -> tuple[MetricsByTreatment, int]:
    if case_runtime.input_plan.wth_updates and case_runtime.input_plan.wth_path is not None:
        rewrite_wth_daily(case_runtime.input_plan.wth_path, case_runtime.input_plan.wth_updates)
    if case_runtime.input_plan.sol_updates and case_runtime.input_plan.sol_path is not None:
        rewrite_sol_layers(case_runtime.input_plan.sol_path, case_runtime.input_plan.sol_updates)

    _clear_output_files(dssat_dir)

    try:
        if case_runtime.input_plan.has_sh2o:
            rewrite_initial_sh2o(base, live_filex, case_runtime.input_plan.sh2o_by_icbl)
        if case_runtime.input_plan.cul_updates:
            _rewrite_cul_params(cul_path, cultivar_code, case_runtime.input_plan.cul_updates)

        metrics_by_trt: MetricsByTreatment = {}
        treatment_calls = 0
        for trt in trts:
            treatment_calls += 1
            metrics_by_trt[int(trt)] = execute_treatment(int(trt), filex_name, dssat_dir, cfg, case_runtime)
        return metrics_by_trt, treatment_calls
    finally:
        _restore_runtime_files(file_state)
        if not keep_outputs:
            _clear_output_files(dssat_dir)


def prepare_case_run(cwd: Path | None = None) -> PreparedCaseRun:
    run_cwd = Path.cwd() if cwd is None else Path(cwd)
    params_path = Path(os.environ.get("PARAMS_PATH", str(run_cwd / "params.dat")))
    params = _read_params(params_path)

    trts_env = os.environ.get("DSSAT_TRTS", "").strip()
    if trts_env:
        trts = _parse_trts(trts_env)
    else:
        trts_path = run_cwd / "dssat_trts.txt"
        if trts_path.exists():
            trts = _parse_trts(trts_path.read_text(encoding="utf-8", errors="ignore"))
        else:
            trts = [int(os.environ.get("DSSAT_TRT", "1"))]

    keep_outputs = os.environ.get("DSSAT_KEEP_OUTPUTS", "0").strip().lower() in {"1", "true", "yes", "y"}

    project_root = Path(__file__).resolve().parents[1]
    project_config_path = resolve_project_config_path(project_root, crop=os.environ.get("PROJECT_CROP", ""))
    cfg = _load_project_config(project_root)
    dssat_dir = _choose_case_dir(run_cwd, project_root, cfg)
    ensure_case_support_files(dssat_dir, project_root)
    param_map, _ = resolve_param_mapping(cfg, dssat_dir)
    if param_map:
        mapped_params: dict[str, float] = {}
        for key, value in params.items():
            key_l = str(key).strip().lower()
            mapped = param_map.get(key_l, key_l)
            mapped_params[mapped] = float(value)
        params = mapped_params

    filex_name = cfg.get("scenario", {}).get("filex", "KSAS8101.WHX")
    base_filex = cfg.get("scenario", {}).get("base_filex", "KSAS8101_base.WHX")
    base = dssat_dir / base_filex
    if not base.exists():
        raise FileNotFoundError(f"Missing base FileX template: {base}")

    live_filex = dssat_dir / filex_name
    if not live_filex.exists():
        raise FileNotFoundError(f"Missing live FileX: {live_filex}")

    cul_path = resolve_cultivar_path(
        dssat_dir,
        cfg,
        env_cul_path=os.environ.get("CUL_PATH", ""),
        env_wh_cul_path=os.environ.get("WH_CUL_PATH", ""),
        project_root=project_root,
    )
    ensure_nonempty_cultivar_file(cul_path, project_root, dssat_dir)
    inferred_cul = infer_cul_path_from_inp(dssat_dir, cfg)
    if inferred_cul is not None:
        ensure_nonempty_cultivar_file(inferred_cul, project_root, dssat_dir)
    fallback_root_cul = resolve_dssat_genotype_dir(project_root, cfg=cfg) / cul_path.name
    ensure_nonempty_cultivar_file(fallback_root_cul, project_root, dssat_dir)
    runtime_exe, runtime_genotype = ensure_local_runtime(
        project_root,
        dssat_dir,
        cul_path,
        cfg,
        env_runtime_root=os.environ.get("DSSAT_RUNTIME_ROOT", ""),
        env_dssat_exe=os.environ.get("DSSAT_EXE", ""),
    )
    cfg.setdefault("paths", {})["dssat_exe"] = str(runtime_exe)
    runtime_cul_path = runtime_genotype / cul_path.name
    cultivar_code = _extract_cultivar_code(live_filex)

    patch_cultivar_dir_in_inp_inh(dssat_dir, runtime_genotype)
    case_runtime = resolve_case_runtime(
        dssat_dir,
        cfg,
        live_filex,
        trts,
        params,
        param_map,
        env_obs_a_path=os.environ.get("DSSAT_OBS_A_PATH", ""),
        env_extra_summary_vars=os.environ.get("DSSAT_EXTRA_SUMMARY_VARS", ""),
        env_allow_missing=os.environ.get("DSSAT_ALLOW_MISSING_WHT_DATES", ""),
    )
    file_state = resolve_runtime_file_state(live_filex, runtime_cul_path, case_runtime.input_plan)
    return PreparedCaseRun(
        cfg=cfg,
        project_config_path=project_config_path,
        dssat_dir=dssat_dir,
        filex_name=filex_name,
        trts=trts,
        case_runtime=case_runtime,
        file_state=file_state,
        keep_outputs=keep_outputs,
        base=base,
        live_filex=live_filex,
        cul_path=runtime_cul_path,
        cultivar_code=cultivar_code,
        trts_env=trts_env,
    )


def main() -> None:
    args = parse_args()
    _apply_runtime_request(args.runtime_request)
    prepared = prepare_case_run()
    cwd = Path.cwd()
    write_run_manifest(cwd, _build_runtime_manifest_payload(prepared, cwd))
    write_contract_report(cwd, _build_contract_report(prepared, cwd))
    started_at = time.time()
    treatment_calls = 0
    try:
        metrics_by_trt, treatment_calls = execute_case(
            prepared.base,
            prepared.live_filex,
            prepared.cul_path,
            prepared.cultivar_code,
            prepared.filex_name,
            prepared.dssat_dir,
            prepared.cfg,
            prepared.trts,
            prepared.case_runtime,
            prepared.file_state,
            prepared.keep_outputs,
        )
        append_run_stats(
            cwd=cwd,
            trts=prepared.trts,
            treatment_calls=treatment_calls,
            duration_sec=time.time() - started_at,
            status="success",
        )
    except Exception:
        append_run_stats(
            cwd=cwd,
            trts=prepared.trts,
            treatment_calls=treatment_calls,
            duration_sec=time.time() - started_at,
            status="failed",
        )
        raise

    out_text = build_pest_output_text(
        metrics_by_trt,
        prepared.trts,
        prepared.trts_env,
        prepared.case_runtime.output.var_codes,
        prepared.case_runtime.observation.wht_dates_by_trt,
    )
    (cwd / "pest_out.dat").write_text(out_text, encoding="utf-8")
    write_run_manifest(
        cwd,
        {
            "results": {
                "metrics_by_trt": {
                    str(int(trt)): {str(key): float(value) for key, value in metrics.items()}
                    for trt, metrics in sorted(metrics_by_trt.items())
                }
            },
            "paths": {"pest_output_path": cwd / "pest_out.dat"},
        },
    )


if __name__ == "__main__":
    main()
