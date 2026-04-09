from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

import pyemu

from case_runtime import resolve_t_vars
from crop_registry import resolve_crop_profile_from_context
from pest_builder import (
    build_pst,
    compute_group_weights,
    write_pest_output_instruction_file,
)
from pest_runner import (
    ProtocolExecutionContext,
    ProtocolIssue,
    build_contract_report_payload,
    build_protocol_execution,
    build_run_manifest_payload,
    build_run_model_env,
    load_runtime_request_env,
    resolve_protocol_options,
    run_model_with_params,
    write_contract_report,
    write_run_manifest,
)
from dssat_io import (
    extract_trts_from_filex,
    load_project_config,
    load_bounds_source,
    resolve_crop_family,
    resolve_dssat_root,
    resolve_project_config_path,
    resolve_param_mapping,
    resolve_parameter_bounds,
    write_parameter_bounds_report,
)

SUMMARY_AFILE_COLUMN_MAP = resolve_crop_profile_from_context({"crop_family": "wheat"}).summary_afile_column_map()
DEFAULT_OBSERVATION_GROUPS = resolve_crop_profile_from_context({"crop_family": "wheat"}).observation_groups_config()


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


def _copy_if_needed(src: Path, dst: Path, tries: int = 10, sleep_s: float = 0.1) -> None:
    try:
        if src.resolve() == dst.resolve():
            return
    except Exception:
        pass

    dst.parent.mkdir(parents=True, exist_ok=True)
    src_size = src.stat().st_size if src.exists() else -1
    if dst.exists():
        try:
            if src_size >= 0 and dst.stat().st_size == src_size:
                return
        except PermissionError:
            if src_size > 0:
                return

    last_error: PermissionError | None = None
    for _ in range(max(1, int(tries))):
        try:
            shutil.copy2(src, dst)
            return
        except PermissionError as exc:
            last_error = exc
            try:
                if dst.exists() and src_size > 0 and dst.stat().st_size == src_size:
                    return
            except PermissionError:
                if src_size > 0:
                    return
            time.sleep(float(sleep_s))
    if last_error is not None:
        raise last_error


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
        params[parts[0].strip().lower()] = float(parts[1])
    return params


def _float_or_default(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _prepare_parameter_bounds(cwd: Path, project_root: Path, cfg: dict) -> list[dict[str, str | float]]:
    params_cfg = cfg.setdefault("params", {})
    custom_bounds = params_cfg.get("bounds", {})
    official_bounds = params_cfg.get("official_bounds", {})
    crop_family = resolve_crop_family(cfg)
    official_source_raw = str(
        os.environ.get(
            "OFFICIAL_BOUNDS_PATH",
            params_cfg.get("official_bounds_source", ""),
        )
    ).strip()
    fallback_mode = str(
        params_cfg.get(
            "fallback_mode",
            params_cfg.get("bounds_fallback_mode", "relative_30"),
        )
    ).strip() or "relative_30"
    default_group = str(params_cfg.get("default_group", "g_cul")).strip() or "g_cul"
    official_source_path: Path | None = None
    initial_values: dict[str, float] = {}
    seed_paths = [
        cwd / "params.dat",
        cwd / "params_baseline.dat",
        project_root / "work" / "params.dat",
    ]
    for candidate in seed_paths:
        if not candidate.exists():
            continue
        initial_values = _read_params(candidate)
        if initial_values:
            break
    if official_source_raw:
        official_source_path = Path(official_source_raw)
        if not official_source_path.is_absolute():
            official_source_path = project_root / official_source_path
        loaded_official_bounds = load_bounds_source(
            official_source_path,
            crop_family=crop_family,
        )
        if loaded_official_bounds:
            official_bounds = {
                **loaded_official_bounds,
                **(official_bounds if isinstance(official_bounds, dict) else {}),
            }
    official_source_text = str(official_source_path.resolve()) if official_source_path is not None else ""
    resolved_bounds, report_rows = resolve_parameter_bounds(
        initial_values=initial_values,
        custom_bounds=custom_bounds if isinstance(custom_bounds, dict) else {},
        official_bounds=official_bounds if isinstance(official_bounds, dict) else {},
        fallback_mode=fallback_mode,
        default_group=default_group,
        crop_family=crop_family,
        official_source_path=official_source_text,
    )
    params_cfg["bounds"] = resolved_bounds
    parameter_order = list(resolve_crop_profile_from_context(cfg, cwd).parameter_order)
    parameter_order.extend(
        name for name in resolved_bounds.keys() if name not in parameter_order
    )
    report_path = write_parameter_bounds_report(
        cwd / "parameter_bounds_preview.csv",
        report_rows,
        parameter_order=parameter_order,
    )
    if report_rows:
        sorted_rows = sorted(
            report_rows,
            key=lambda row: (
                parameter_order.index(str(row.get("parameter", "")).strip().lower())
                if str(row.get("parameter", "")).strip().lower() in parameter_order
                else len(parameter_order) + 1,
                str(row.get("source", "")),
                int(row.get("priority_rank", 99)),
                str(row.get("parameter", "")),
            ),
        )
        source_counts: dict[str, int] = {}
        for row in sorted_rows:
            source = str(row["source"])
            source_counts[source] = source_counts.get(source, 0) + 1
        counts_text = ", ".join(f"{source}={count}" for source, count in sorted(source_counts.items()))
        print(f"Parameter bounds preview saved to {report_path}")
        print(f"Parameter bounds sources: {counts_text}")
        header = f"{'parameter':<14} {'source':<12} {'rank':<4} {'lower':>10} {'upper':>10} {'initial':>10} {'group':<14}"
        print(header)
        print("-" * len(header))
        for row in sorted_rows:
            print(
                f"{str(row['parameter']):<14} "
                f"{str(row['source']):<12} "
                f"{int(row['priority_rank']):<4} "
                f"{float(row['lower']):>10.4f} "
                f"{float(row['upper']):>10.4f} "
                f"{float(row['initial']):>10.4f} "
                f"{str(row['group']):<14}"
            )
    return report_rows


def _read_pest_out_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            float(parts[1])
        except ValueError:
            continue
        keys.add(parts[0].strip().lower())
    return keys


def _has_summary_metric_key(sim_keys: set[str], metric_code: str, trts: list[int]) -> bool:
    prefix = f"{str(metric_code).strip().lower()}_t"
    for trt in trts:
        if f"{prefix}{int(trt):02d}" in sim_keys:
            return True
    return False


def _filter_wht_dates_by_sim_keys(sim_keys: set[str], wht_dates_by_trt: dict[int, list[int]]) -> dict[int, list[int]]:
    filtered: dict[int, list[int]] = {}
    for trt, dates in wht_dates_by_trt.items():
        kept = [int(date) for date in dates if f"laid_t{int(trt):02d}_d{int(date)}" in sim_keys]
        if kept:
            filtered[int(trt)] = kept
    return filtered


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


def _extract_metric_from_obs_name(name: str) -> str:
    name_l = str(name).strip().lower()
    if "_t" in name_l:
        return name_l.split("_t", 1)[0]
    return name_l.split("_", 1)[0]


def _parse_name_list(value: str) -> set[str]:
    out: set[str] = set()
    for token in str(value or "").replace(";", ",").split(","):
        cleaned = str(token).strip().lower()
        if cleaned:
            out.add(cleaned)
    return out


def _resolve_crop_profile(cfg: dict, dssat_dir: Path | None = None):
    return resolve_crop_profile_from_context(cfg, dssat_dir)


def _resolve_summary_afile_column_map(cfg: dict, dssat_dir: Path | None = None) -> dict[str, str]:
    return _resolve_crop_profile(cfg, dssat_dir).summary_afile_column_map()


def _resolve_default_observation_groups(cfg: dict, dssat_dir: Path | None = None) -> dict[str, dict[str, object]]:
    return _resolve_crop_profile(cfg, dssat_dir).observation_groups_config()


def _resolve_summary_metrics(cfg: dict, yield_var: str, laix_var: str | None) -> list[str]:
    requested: list[str] = []
    if str(yield_var).strip():
        requested.append(str(yield_var).strip().upper())
    if laix_var:
        requested.append(str(laix_var).strip().upper())

    metrics_cfg = cfg.get("metrics", {}) or cfg.get("variables", {}) or {}
    extras_cfg = metrics_cfg.get("extra_summary_vars", [])
    if isinstance(extras_cfg, str):
        extras = [tok.strip().upper() for tok in extras_cfg.replace(";", ",").split(",") if tok.strip()]
    else:
        extras = [str(tok).strip().upper() for tok in extras_cfg if str(tok).strip()]

    extras_env = os.environ.get("DSSAT_EXTRA_SUMMARY_VARS", "")
    if extras_env.strip():
        extras.extend([tok.strip().upper() for tok in extras_env.replace(";", ",").split(",") if tok.strip()])

    active_metrics = _parse_name_list(os.environ.get("PEST_ACTIVE_METRICS", ""))
    if active_metrics:
        requested = [code for code in requested if code.lower() in active_metrics]
        extras = [code for code in extras if code.lower() in active_metrics]

    ordered: list[str] = []
    seen: set[str] = set()
    for code in [*requested, *extras]:
        code_u = str(code).strip().upper()
        if not code_u or code_u in seen:
            continue
        seen.add(code_u)
        ordered.append(code_u)
    return ordered


def _write_build_setup_protocol_artifacts(
    cwd: Path,
    project_root: Path,
    cfg: dict,
    dssat_dir: Path,
    filex_path: Path,
    trts: list[int],
    requested_summary_metrics: list[str],
    resolved_summary_metrics: list[str],
    requested_t_vars: list[str],
    split_by_trt: dict[int, str],
    weight_mode: str,
    active_metrics: set[str],
    allow_missing_obs_files: bool,
    a_path: Path,
    wht_path: Path,
    wht_dates_by_trt: dict[int, list[int]],
    meas: dict[str, float],
    group_defs: dict[str, dict[str, object]],
    group_variances: dict[str, float],
    group_maxima: dict[str, float],
    group_weights: dict[str, float],
    weights_overrides: dict[str, float],
    yield_prefix: str,
    laix_prefix: str,
    observation_count: int,
) -> None:
    bounds_preview_path = cwd / "parameter_bounds_preview.csv"
    project_config_path = resolve_project_config_path(project_root, crop=os.environ.get("PROJECT_CROP", ""))
    run_id = str(os.environ.get("AR_RUN_ID", "")).strip() or cwd.name
    context = ProtocolExecutionContext(
        run_id=run_id,
        crop=resolve_crop_family(cfg, dssat_dir),
        runtime_dir=cwd,
        case_dir=dssat_dir,
        project_root=project_root,
        project_config_path=project_config_path,
        filex_name=filex_path.name,
        trts=tuple(int(trt) for trt in trts),
    )
    protocol = resolve_protocol_options(
        weight_mode=weight_mode,
        keep_outputs=True,
        allow_missing_wht_dates=allow_missing_obs_files,
        active_metrics=active_metrics,
        split_assignments=split_by_trt,
    )
    execution = build_protocol_execution(cwd=cwd, env=os.environ)
    resolved_t_vars = list(requested_t_vars) if wht_dates_by_trt else []
    missing_summary = [code for code in requested_summary_metrics if code not in resolved_summary_metrics]
    missing_treatment_dates = sorted(
        int(trt) for trt in trts if requested_t_vars and not wht_dates_by_trt.get(int(trt))
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
    if requested_t_vars and not wht_path.exists():
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
    active_groups = sorted(
        group_name for group_name, weight in group_weights.items() if float(weight) > 0.0
    )
    dropped_groups = _build_dropped_group_records(group_defs, group_weights)
    weight_fallbacks = _build_weight_fallback_records(
        group_defs,
        group_variances,
        group_maxima,
        group_weights,
        weight_mode,
    )
    zero_weight_observations = _build_zero_weight_observation_records(
        meas,
        group_defs,
        group_weights,
        weights_overrides,
        split_by_trt,
        active_metrics,
        yield_prefix,
        laix_prefix,
    )
    split_counts: dict[str, int] = {}
    for split_name in split_by_trt.values():
        split_counts[str(split_name)] = split_counts.get(str(split_name), 0) + 1
    resolved_dates = {
        str(int(trt)): [int(date) for date in dates]
        for trt, dates in sorted(wht_dates_by_trt.items())
    }
    write_run_manifest(
        cwd,
        build_run_manifest_payload(
            context,
            protocol=protocol,
            execution=execution,
            scenario={
                "filex_name": filex_path.name,
                "trts": [int(trt) for trt in trts],
            },
            paths={
                "case_dir": dssat_dir,
                "filex_path": filex_path,
                "params_path": cwd / "params.dat",
                "bounds_preview_path": bounds_preview_path,
                "obs_a_path": a_path,
                "obs_wht_path": wht_path,
                "runtime_request_path": str(os.environ.get("AR_RUNTIME_REQUEST_PATH", "")).strip(),
            },
            observations={
                "requested_summary_metrics": list(requested_summary_metrics),
                "resolved_summary_metrics": list(resolved_summary_metrics),
                "requested_t_vars": list(requested_t_vars),
                "resolved_t_vars": list(resolved_t_vars),
                "wht_dates_by_trt": resolved_dates,
            },
            resolved_output={
                "summary_metrics": list(resolved_summary_metrics),
                "t_vars": list(resolved_t_vars),
                "wht_dates_by_trt": resolved_dates,
                "active_groups": active_groups,
            },
        ),
    )
    write_contract_report(
        cwd,
        build_contract_report_payload(
            context,
            status="degraded" if issues or dropped_groups or weight_fallbacks else "ok",
            requested={
                "summary_metrics": list(requested_summary_metrics),
                "t_vars": list(requested_t_vars),
                "trts": [int(trt) for trt in trts],
            },
            resolved={
                "summary_metrics": list(resolved_summary_metrics),
                "t_vars": list(resolved_t_vars),
                "allow_missing_dates": bool(allow_missing_obs_files),
                "wht_dates_by_trt": resolved_dates,
            },
            paths={
                "runtime_dir": cwd,
                "case_dir": dssat_dir,
                "filex_path": filex_path,
                "bounds_preview_path": bounds_preview_path,
                "obs_a_path": a_path,
                "obs_wht_path": wht_path,
            },
            protocol=protocol,
            execution=execution,
            issues=issues,
            details={
                "active_groups": active_groups,
                "fallback_metrics": missing_summary,
                "dropped_groups": dropped_groups,
                "weight_fallbacks": weight_fallbacks,
                "zero_weight_observations": zero_weight_observations,
            },
            summary={
                "active_groups": active_groups,
                "active_metric_count": len({code for code in [*resolved_summary_metrics, *resolved_t_vars] if str(code).strip()}),
                "active_observation_count": int(observation_count),
                "weight_mode": str(weight_mode).strip(),
                "split_counts": split_counts,
                "fallback_metrics": missing_summary,
                "dropped_group_count": len(dropped_groups),
                "weight_fallback_count": len(weight_fallbacks),
                "zero_weight_observation_count": len(zero_weight_observations),
                "resolved_output_context": {
                    "summary_metric_count": len(resolved_summary_metrics),
                    "t_var_count": len(resolved_t_vars),
                    "wht_observation_file_present": bool(wht_path.exists()),
                    "parameter_bounds_preview_present": bounds_preview_path.exists(),
                },
            },
        ),
    )


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


def _calc_group_maxima(
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
            v = abs(float(oval))
        except Exception:
            continue
        g = _resolve_obs_group_name(oname, group_defs, yield_prefix, laix_prefix)
        group_vals.setdefault(g, []).append(v)
    out: dict[str, float] = {}
    for g, vals in group_vals.items():
        out[g] = max(vals) if vals else float("nan")
    return out


def _calc_group_rms(
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
        if not vals:
            out[g] = float("nan")
            continue
        out[g] = float(math.sqrt(sum(float(v) ** 2 for v in vals) / float(len(vals))))
    return out


def _calc_group_mean_abs(
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
            v = abs(float(oval))
        except Exception:
            continue
        g = _resolve_obs_group_name(oname, group_defs, yield_prefix, laix_prefix)
        group_vals.setdefault(g, []).append(v)
    out: dict[str, float] = {}
    for g, vals in group_vals.items():
        if not vals:
            out[g] = float("nan")
            continue
        out[g] = float(sum(vals) / float(len(vals)))
    return out


def _build_dropped_group_records(
    group_defs: dict[str, dict[str, object]],
    group_weights: dict[str, float],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for group_name in sorted(group_defs):
        if group_name not in group_weights:
            records.append({"group": str(group_name), "reason": "no_train_observations"})
            continue
        if float(group_weights.get(group_name, 0.0)) <= 0.0:
            records.append({"group": str(group_name), "reason": "non_positive_group_weight"})
    return records


def _build_weight_fallback_records(
    group_defs: dict[str, dict[str, object]],
    group_variances: dict[str, float],
    group_maxima: dict[str, float],
    group_weights: dict[str, float],
    weight_mode: str,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    weight_mode_name = str(weight_mode).strip().lower()
    for group_name in sorted(group_defs):
        if group_name not in group_weights:
            continue
        gspec = group_defs.get(group_name, {})
        configured_weight = _float_or_default(gspec.get("weight", 1.0), 1.0)
        sigma = _float_or_default(gspec.get("sigma", 1.0), 1.0)
        applied_weight = float(group_weights.get(group_name, configured_weight))
        if weight_mode_name == "w8_dssat_group_max":
            maximum = float(group_maxima.get(group_name, float("nan")))
            if not math.isfinite(maximum) or maximum <= 0.0:
                records.append(
                    {
                        "group": str(group_name),
                        "reason": "missing_or_non_positive_group_maximum",
                        "configured_weight": configured_weight,
                        "applied_weight": applied_weight,
                    }
                )
            continue
        variance = float(group_variances.get(group_name, float("nan")))
        if math.isfinite(variance) and variance > 0.0:
            continue
        if sigma > 0.0:
            records.append(
                {
                    "group": str(group_name),
                    "reason": "variance_unavailable_used_sigma",
                    "sigma": sigma,
                    "applied_weight": applied_weight,
                }
            )
            continue
        records.append(
            {
                "group": str(group_name),
                "reason": "variance_and_sigma_unavailable_used_configured_weight",
                "configured_weight": configured_weight,
                "applied_weight": applied_weight,
            }
        )
    return records


def _build_zero_weight_observation_records(
    meas: dict[str, float],
    group_defs: dict[str, dict[str, object]],
    group_weights: dict[str, float],
    weights_overrides: dict[str, float],
    split_by_trt: dict[int, str],
    active_metrics: set[str],
    yield_prefix: str,
    laix_prefix: str,
) -> list[dict[str, object]]:
    normalized_active_metrics = {str(metric).strip().lower() for metric in active_metrics if str(metric).strip()}
    normalized_overrides = {
        str(name).strip().lower(): float(weight)
        for name, weight in weights_overrides.items()
        if str(name).strip()
    }
    records: list[dict[str, object]] = []
    for oname in sorted(meas):
        metric = _extract_metric_from_obs_name(oname)
        group_name = _resolve_obs_group_name(oname, group_defs, yield_prefix, laix_prefix)
        trt = _extract_trt_from_obs_name(oname)
        name_l = str(oname).strip().lower()
        reason = ""
        if (trt is not None) and (split_by_trt.get(int(trt)) == "valid"):
            reason = "validation_split"
        elif normalized_active_metrics and metric not in normalized_active_metrics:
            reason = "inactive_metric"
        elif name_l in normalized_overrides and float(normalized_overrides[name_l]) <= 0.0:
            reason = "explicit_weight_override"
        elif float(group_weights.get(group_name, 1.0)) <= 0.0:
            reason = "non_positive_group_weight"
        if not reason:
            continue
        record: dict[str, object] = {
            "obs_name": str(oname),
            "group": str(group_name),
            "metric": str(metric),
            "reason": reason,
        }
        if trt is not None:
            record["trt"] = int(trt)
        records.append(record)
    return records


def _extract_measured_from_obs_a(
    a_path: Path,
    trts: list[int],
    metric_codes: list[str],
    column_map: dict[str, str] | None = None,
    allow_missing: bool = False,
) -> dict[str, float]:
    if not metric_codes:
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

    cols = [c.lstrip("@").strip().upper() for c in header.split()]
    if "TRNO" not in cols:
        raise RuntimeError(f"TRNO column missing in {a_path}")
    i_trno = cols.index("TRNO")
    resolved_column_map = {str(key).strip().upper(): str(value).strip().upper() for key, value in (column_map or {}).items()}
    idx_by_metric: dict[str, int] = {}
    for code in metric_codes:
        code_u = str(code).strip().upper()
        col_name = resolved_column_map.get(code_u, code_u)
        if col_name and col_name in cols:
            idx_by_metric[code_u] = cols.index(col_name)
    if not idx_by_metric:
        return {}

    rows: dict[int, dict[str, float]] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("!") or line.startswith("@") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) <= max([i_trno, *idx_by_metric.values()]):
            continue
        try:
            trno = int(parts[i_trno])
        except ValueError:
            continue
        try:
            rec: dict[str, float] = {}
            for code_u, idx_col in idx_by_metric.items():
                rec[str(code_u).strip().lower()] = float(parts[idx_col])
            if not rec:
                continue
            rows[int(trno)] = rec
        except ValueError:
            continue

    out: dict[str, float] = {}
    for trt in trts:
        if int(trt) not in rows:
            continue
        for metric_name, metric_value in rows[int(trt)].items():
            out[f"{metric_name}_t{int(trt):02d}"] = float(metric_value)

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
        aggregated_by_date: dict[int, list[tuple[float, float | None]]] = {}
        for d, laid, swad in recs_sorted:
            aggregated_by_date.setdefault(int(d), []).append((float(laid), None if swad is None else float(swad)))
        unique_dates = sorted(aggregated_by_date.keys())
        dates_by_trt[int(trt)] = unique_dates
        for d in unique_dates:
            values = aggregated_by_date[int(d)]
            laid_values = [laid for laid, _ in values]
            second_values = [float(v) for _, v in values if v is not None]
            out[f"laid_t{int(trt):02d}_d{int(d)}"] = float(sum(laid_values) / len(laid_values))
            if second and second_values:
                out[f"{second}_t{int(trt):02d}_d{int(d)}"] = float(sum(second_values) / len(second_values))

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
    summary_metrics: list[str],
    wht_dates_by_trt: dict[int, list[int]] | None = None,
    wht_second: str = "",
) -> None:
    write_pest_output_instruction_file(path, trts, summary_metrics, wht_dates_by_trt, wht_second)


def _ensure_case_files(case_dir: Path, project_root: Path, cfg: dict) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)

    params_dat = case_dir / "params.dat"
    dssat_dir_raw = str(cfg.get("paths", {}).get("dssat_case_dir", "")).strip()
    if dssat_dir_raw:
        dssat_dir = Path(dssat_dir_raw)
        if not dssat_dir.is_absolute():
            dssat_dir = resolve_dssat_root(project_root, cfg=cfg) / dssat_dir
    else:
        dssat_dir = None
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
            registry_priority = list(resolve_crop_profile_from_context(cfg, dssat_dir).parameter_order)
            ordered_keys = [
                key
                for key in registry_priority
                if key in vals
            ]
            ordered_keys.extend(
                key for key in desired.keys() if key in vals and key not in ordered_keys
            )
            ordered_keys.extend(sorted(key for key in vals if key not in ordered_keys))
            params_dat.write_text(
                "\n".join([f"{k} {vals[k]:.6f}" for k in ordered_keys]) + "\n",
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
    if template_root:
        template_path = Path(str(template_root).strip())
        if not template_path.is_absolute():
            template_path = resolve_dssat_root(project_root, cfg=cfg) / template_path
        template = template_path.resolve()
    else:
        template = (project_root / "data" / "dssat").resolve()
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
            _copy_if_needed(src, dst)

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
        _copy_if_needed(src_cul, dst_cul)

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
    args = parse_args()
    _apply_runtime_request(args.runtime_request)
    cwd = Path.cwd()
    template_dir = Path(__file__).resolve().parent
    project_root = template_dir.parent
    cfg = _load_project_config(project_root)
    _prepare_parameter_bounds(cwd, project_root, cfg)
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
    requested_summary_metrics = _resolve_summary_metrics(cfg, yield_var, laix_var)
    summary_metrics = list(requested_summary_metrics)
    summary_afile_column_map = _resolve_summary_afile_column_map(cfg, dssat_dir)

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
                summary_metrics = [
                    code
                    for code in summary_metrics
                    if summary_afile_column_map.get(code, code) in cols_u
                ]
                if yield_var and yield_var.upper() not in cols_u:
                    yield_var = ""
                if laix_var and laix_var.upper() not in cols_u:
                    laix_var = None
            else:
                summary_metrics = []
                yield_var = ""
                laix_var = None
        except Exception:
            summary_metrics = []
            yield_var = ""
            laix_var = None
    else:
        summary_metrics = []
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

    a_meas = _extract_measured_from_obs_a(
        a_path,
        trts,
        summary_metrics,
        column_map=summary_afile_column_map,
        allow_missing=allow_missing_obs_files,
    )

    (cwd / "dssat_trts.txt").write_text(",".join([str(int(t)) for t in trts]) + "\n", encoding="utf-8")

    # Multi-start seeding (LHS)
    mgda_cfg = cfg.get("optimization", {}).get("mgda", {})
    start_mode = str(mgda_cfg.get("start_mode", "")).strip().lower() or os.environ.get("MGDA_START_MODE", "").strip().lower()
    start_count = int(mgda_cfg.get("start_count", os.environ.get("MGDA_START_COUNT", "1")))
    start_index = int(mgda_cfg.get("start_index", os.environ.get("MGDA_START_INDEX", "0")))
    if start_mode in ("lhs", "random"):
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
                
        params_seed: dict[str, float] = {}
        if start_mode == "random":
            import random as _rnd
            rng = _rnd.Random() # we don't necessarily want fixed seed here, so different runs get different starts
            for k, (lb, ub) in bounds_seed.items():
                params_seed[k] = float(lb + rng.random() * (ub - lb))
        else: # lhs style
            start_count = max(1, start_count)
            s = max(0, min(start_index, max(0, start_count - 1)))
            try:
                from scipy.stats import qmc
                sampler = qmc.LatinHypercube(d=len(bounds_seed), seed=42)
                sample = sampler.random(n=start_count)
                for i, (k, (lb, ub)) in enumerate(bounds_seed.items()):
                    params_seed[k] = float(lb + sample[s, i] * (ub - lb))
            except ImportError:
                # Fallback to simple grid if scipy is missing
                x = (s + 0.5) / float(start_count)
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

    run_env_overrides = {
        "MGDA_START_MODE": start_mode or os.environ.get("MGDA_START_MODE", ""),
        "MGDA_START_COUNT": str(start_count),
        "MGDA_START_INDEX": str(start_index),
    }
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
    env = build_run_model_env(
        params_path=cwd / "params.dat",
        trts=trts,
        keep_outputs=True,
        base_env=os.environ,
        extra_env=run_env_overrides,
        case_dir=dssat_dir,
        cul_path=cul_path,
        extra_summary_vars=[code for code in summary_metrics if code not in {yield_var, laix_var or ""}],
        allow_missing_wht_dates=allow_missing_obs_files,
    )
    run_model_with_params(
        cwd,
        cwd / "params.dat",
        trts=trts,
        keep_outputs=True,
        run_model_path=run_model_path,
        extra_env=env,
        failure_label="build_pest_setup run_model.py",
    )
    sim_keys = _read_pest_out_keys(cwd / "pest_out.dat")
    summary_metrics = [code for code in summary_metrics if _has_summary_metric_key(sim_keys, code, trts)]
    wht_dates_by_trt = _filter_wht_dates_by_sim_keys(sim_keys, wht_dates_by_trt)
    a_meas = {key: value for key, value in a_meas.items() if key in sim_keys}
    wht_meas = {key: value for key, value in wht_meas.items() if key in sim_keys}
    _write_pest_out_ins(cwd / "pest_out.ins", trts, summary_metrics, wht_dates_by_trt, wht_second)
    meas = dict(a_meas)
    meas.update(wht_meas)

    for p in ["Evaluate.OUT", "Summary.OUT", "WARNING.OUT"]:
        _try_unlink(dssat_dir / p)
    params = _read_params(cwd / "params.dat")

    ies_num_reals = os.environ.get("PESTPP_IES_NUM_REALS", "").strip()
    ies_subset_size = os.environ.get("PESTPP_IES_SUBSET_SIZE", "").strip()

    # Define parameters from configuration (mandatory)
    # The config 'bounds' keys should match the DSSAT header names (case-insensitive)
    pst_bounds: dict[str, tuple[float, float, str]] = {}
    cfg_params = cfg.get("params", {})
    cfg_bounds = cfg_params.get("bounds", {})
    
    if not cfg_bounds:
        raise RuntimeError("No parameter bounds defined in project config")

    for k, v in cfg_bounds.items():
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            k_l = str(k).strip().lower()
            mapped = param_map.get(k_l, k_l)
            pst_bounds[mapped] = (float(v[0]), float(v[1]), str(v[2]))
        else:
            print(f"Warning: Invalid bound format for parameter {k}, expected [lb, ub, group]")

    active_params_raw = _parse_name_list(os.environ.get("PEST_ACTIVE_PARAMS", ""))
    active_params = {param_map.get(name, name) for name in active_params_raw}
    group_defaults = {
        "derinclb": 0.0,
        "forcen": "switch",
        "derincmul": 2.0,
        "dermthd": "parabolic",
        "splitthresh": 1.0e-5,
        "splitreldiff": 0.5,
        "splitaction": "smaller",
    }

    # Define parameter groups from configuration
    pst_group_specs: dict[str, tuple[str, float]] = {}
    cfg_groups = cfg_params.get("groups", {})
    for g, spec in cfg_groups.items():
        if isinstance(spec, dict) and "inctyp" in spec and "derinc" in spec:
            pst_group_specs[str(g)] = (str(spec["inctyp"]), float(spec["derinc"]))

    cfg_obs = cfg.get("observations", {})
    group_defs = dict(_resolve_default_observation_groups(cfg, dssat_dir))
    for gname, gspec in (cfg_obs.get("groups", {}) or {}).items():
        if isinstance(gspec, dict):
            group_defs[str(gname)] = dict(gspec)
    weights_overrides = {str(k).strip().lower(): float(v) for k, v in cfg_obs.get("weights", {}).items()}
    
    # 深度对齐设计：强制 PEST 权重 = 1 / sigma
    # 这样 PEST 算出的梯度模长与 MGDA 各组的模长就处于同一个量级，消除梯度霸凌。
    split_by_trt = _resolve_split(cfg, trts)
    yield_prefix = str(yield_var).strip().lower() if yield_var else ""
    laix_prefix = str(laix_var).strip().lower() if laix_var else ""
    
    # 计算观测值的先验方差（基于 train 集）
    weight_mode = str(os.environ.get("PEST_OBS_WEIGHT_MODE", "")).strip().lower() or str(
        cfg_obs.get("weight_mode", "w1_inverse_variance")
    ).strip().lower()
    group_variances = _calc_group_variances(meas, split_by_trt, group_defs, yield_prefix, laix_prefix)
    group_maxima = _calc_group_maxima(meas, split_by_trt, group_defs, yield_prefix, laix_prefix)
    group_rms = _calc_group_rms(meas, split_by_trt, group_defs, yield_prefix, laix_prefix)
    group_mean_abs = _calc_group_mean_abs(meas, split_by_trt, group_defs, yield_prefix, laix_prefix)
    
    # 尝试加载 MGDA 的反馈 Alpha 权重 (显式开启)
    mgda_alphas: dict[str, float] = {}
    use_mgda_alphas = os.environ.get("USE_MGDA_ALPHAS", "0").strip() == "1"
    alpha_path = cwd / "mgda_alphas.json"
    
    if use_mgda_alphas and alpha_path.exists():
        try:
            mgda_alphas = json.loads(alpha_path.read_text(encoding="utf-8"))
            print(f"Applying MGDA Alpha-Feedback: {mgda_alphas}")
        except Exception as e:
            print(f"Warning: Could not read feedback alphas: {e}")
    elif use_mgda_alphas:
        print(f"USE_MGDA_ALPHAS=1 but {alpha_path} not found. Using uniform prior weights.")
    else:
        print("Using standard inverse-variance weights (Alpha-Feedback disabled).")

    group_weights = compute_group_weights(
        group_defs,
        group_variances,
        group_maxima,
        group_rms,
        group_mean_abs,
        weight_mode,
        mgda_alphas,
    )
    active_metrics = _parse_name_list(os.environ.get("PEST_ACTIVE_METRICS", ""))
    _write_build_setup_protocol_artifacts(
        cwd=cwd,
        project_root=project_root,
        cfg=cfg,
        dssat_dir=dssat_dir,
        filex_path=filex_path,
        trts=trts,
        requested_summary_metrics=requested_summary_metrics,
        resolved_summary_metrics=summary_metrics,
        requested_t_vars=resolve_t_vars(metrics_cfg),
        split_by_trt=split_by_trt,
        weight_mode=weight_mode,
        active_metrics=active_metrics,
        allow_missing_obs_files=allow_missing_obs_files,
        a_path=a_path,
        wht_path=wht_path,
        wht_dates_by_trt=wht_dates_by_trt,
        meas=meas,
        group_defs=group_defs,
        group_variances=group_variances,
        group_maxima=group_maxima,
        group_weights=group_weights,
        weights_overrides=weights_overrides,
        yield_prefix=yield_prefix,
        laix_prefix=laix_prefix,
        observation_count=len(meas),
    )
    run_model_python = str(os.environ.get("PEST_RUN_MODEL_PYTHON", "")).strip() or sys.executable
    pst = build_pst(
        pyemu_module=pyemu,
        model_command=f'"{run_model_python}" "{run_model_path}"',
        noptmax=int(os.environ.get("PEST_NOPTMAX", "10")),
        pst_bounds=pst_bounds,
        params=params,
        group_specs=pst_group_specs,
        group_defaults=group_defaults,
        meas=meas,
        group_defs=group_defs,
        group_weights=group_weights,
        weights_overrides=weights_overrides,
        split_by_trt=split_by_trt,
        active_metrics=active_metrics,
        yield_prefix=yield_prefix,
        laix_prefix=laix_prefix,
        resolve_obs_group_name=_resolve_obs_group_name,
        extract_metric_from_obs_name=_extract_metric_from_obs_name,
        extract_trt_from_obs_name=_extract_trt_from_obs_name,
        active_params=active_params if active_params else None,
        pst_filename="ksas_mvp.pst",
        ies_num_reals=int(ies_num_reals) if ies_num_reals else None,
        ies_subset_size=int(ies_subset_size) if ies_subset_size else None,
    )

    if not any(float(w) > 0.0 for w in pst.observation_data.weight.astype(float).tolist()):
        raise RuntimeError("No usable observations: A/T files missing or empty after filtering")

    pst.write(cwd / "ksas_mvp.pst")


if __name__ == "__main__":
    main()
