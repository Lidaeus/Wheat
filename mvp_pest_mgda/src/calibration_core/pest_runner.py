from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from html import escape
from pathlib import Path
from typing import Any, Callable

import numpy as np

from calibration_core.atomic_io import atomic_write_json


@dataclass(frozen=True)
class ProtocolExecutionContext:
    run_id: str
    crop: str
    runtime_dir: Path
    case_dir: Path | None = None
    project_root: Path | None = None
    project_config_path: Path | None = None
    filex_name: str = ""
    trts: tuple[int, ...] = ()


@dataclass(frozen=True)
class ProtocolExecution:
    cwd: Path
    python_executable: str = ""
    env_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProtocolOptions:
    weight: str = ""
    engine: str = ""
    budget: str = ""
    sequence: str = ""
    grouping: str = ""
    weight_mode: str = ""
    keep_outputs: bool = False
    allow_missing_wht_dates: bool = False
    active_metrics: tuple[str, ...] = ()
    split_assignments: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProtocolIssue:
    code: str
    severity: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


RUNTIME_REQUEST_PREFIXES = ("AR_", "DSSAT_", "PEST_", "MGDA_")
RUNTIME_REQUEST_EXACT_KEYS = frozenset(
    {
        "CUL_PATH",
        "WH_CUL_PATH",
        "PARAMS_PATH",
        "PROJECT_CONFIG",
        "PROJECT_CROP",
        "USE_MGDA_ALPHAS",
        "OFFICIAL_BOUNDS_PATH",
    }
)


def _is_runtime_request_key(name: object) -> bool:
    key = str(name).strip()
    if not key:
        return False
    if key in RUNTIME_REQUEST_EXACT_KEYS:
        return True
    return any(key.startswith(prefix) for prefix in RUNTIME_REQUEST_PREFIXES)


def extract_runtime_request_env(env: Mapping[str, object] | None) -> dict[str, str]:
    payload: dict[str, str] = {}
    for key, value in (env or {}).items():
        if not _is_runtime_request_key(key):
            continue
        payload[str(key)] = str(value)
    return dict(sorted(payload.items()))


def strip_runtime_request_env(env: Mapping[str, object] | None) -> dict[str, str]:
    stripped: dict[str, str] = {}
    for key, value in (env or {}).items():
        if _is_runtime_request_key(key):
            continue
        stripped[str(key)] = str(value)
    return stripped


def write_runtime_request(
    work_dir: Path,
    *,
    artifact_name: str,
    env: Mapping[str, object],
    purpose: str,
    script_path: Path | None = None,
) -> Path:
    request_path = Path(work_dir) / artifact_name
    request_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "purpose": str(purpose).strip(),
        "work_dir": str(Path(work_dir)),
        "env": extract_runtime_request_env(env),
    }
    if script_path is not None:
        payload["script_path"] = str(Path(script_path))
    return update_json_artifact(request_path, payload)


def load_runtime_request_env(request_path: Path) -> dict[str, str]:
    payload = load_json_artifact(Path(request_path))
    env_payload = payload.get("env", {})
    if not isinstance(env_payload, Mapping):
        raise RuntimeError(f"Invalid runtime request payload: {request_path}")
    return {str(key): str(value) for key, value in env_payload.items() if str(key).strip()}


def prepare_runtime_request_process_env(
    work_dir: Path,
    *,
    artifact_name: str,
    env: Mapping[str, object],
    purpose: str,
    script_path: Path | None = None,
) -> tuple[dict[str, str], Path]:
    request_path = write_runtime_request(
        Path(work_dir),
        artifact_name=artifact_name,
        env=env,
        purpose=purpose,
        script_path=script_path,
    )
    process_env = strip_runtime_request_env(env)
    process_env["AR_RUNTIME_REQUEST_PATH"] = str(request_path)
    return process_env, request_path


def normalize_protocol_codes(codes: Iterable[object] | None) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    if codes is None:
        return ()
    for code in codes:
        code_u = str(code).strip().upper()
        if not code_u or code_u in seen:
            continue
        seen.add(code_u)
        normalized.append(code_u)
    return tuple(normalized)


def resolve_protocol_options(
    *,
    weight: str | None = None,
    engine: str | None = None,
    budget: str | None = None,
    sequence: str | None = None,
    grouping: str | None = None,
    weight_mode: str | None = None,
    keep_outputs: bool = False,
    allow_missing_wht_dates: bool = False,
    active_metrics: Iterable[object] | None = None,
    split_assignments: Mapping[int | str, object] | None = None,
) -> ProtocolOptions:
    active_codes = normalize_protocol_codes(
        active_metrics
        if active_metrics is not None
        else os.environ.get("PEST_ACTIVE_METRICS", "").replace(";", ",").split(",")
    )
    split_payload = {
        str(key): str(value)
        for key, value in sorted((split_assignments or {}).items(), key=lambda item: str(item[0]))
        if str(value).strip()
    }
    return ProtocolOptions(
        weight=str(weight if weight is not None else os.environ.get("AR_WEIGHTING", "")).strip(),
        engine=str(engine if engine is not None else os.environ.get("AR_ENGINE", "")).strip(),
        budget=str(budget if budget is not None else os.environ.get("AR_BUDGET", "")).strip(),
        sequence=str(sequence if sequence is not None else os.environ.get("AR_SEQUENCE", "")).strip(),
        grouping=str(grouping if grouping is not None else os.environ.get("AR_GROUPING", "")).strip(),
        weight_mode=str(weight_mode or "").strip(),
        keep_outputs=bool(keep_outputs),
        allow_missing_wht_dates=bool(allow_missing_wht_dates),
        active_metrics=active_codes,
        split_assignments=split_payload,
    )


def build_protocol_execution(
    *,
    cwd: Path,
    python_executable: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProtocolExecution:
    env_keys = tuple(sorted(str(key) for key in (env or os.environ).keys() if str(key).strip()))
    return ProtocolExecution(
        cwd=Path(cwd),
        python_executable=str(python_executable or sys.executable),
        env_keys=env_keys,
    )


def _protocol_options_payload(options: ProtocolOptions) -> dict[str, Any]:
    payload = asdict(options)
    split_assignments = payload.pop("split_assignments", {})
    if split_assignments:
        payload["split"] = {"assignments": split_assignments}
    return payload


def _protocol_issues_payload(issues: Sequence[ProtocolIssue | Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for issue in issues:
        if isinstance(issue, ProtocolIssue):
            normalized.append(asdict(issue))
        else:
            normalized.append(_jsonify_artifact_value(issue))
    return normalized


def build_run_manifest_payload(
    context: ProtocolExecutionContext,
    *,
    protocol: ProtocolOptions | None = None,
    execution: ProtocolExecution | None = None,
    scenario: Mapping[str, Any] | None = None,
    paths: Mapping[str, Any] | None = None,
    observations: Mapping[str, Any] | None = None,
    resolved_output: Mapping[str, Any] | None = None,
    results: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": context.run_id,
        "crop": context.crop,
        "project_root": context.project_root,
        "runtime_dir": context.runtime_dir,
        "project_config_path": context.project_config_path,
        "scenario": dict(scenario or {"filex_name": context.filex_name, "trts": list(context.trts)}),
        "paths": dict(paths or {"case_dir": context.case_dir}),
    }
    if protocol is not None:
        payload["protocol"] = _protocol_options_payload(protocol)
    if execution is not None:
        payload["execution"] = asdict(execution)
    if observations:
        payload["observations"] = dict(observations)
    if resolved_output:
        payload["resolved_output"] = dict(resolved_output)
    if results:
        payload["results"] = dict(results)
    return payload


def build_contract_report_payload(
    context: ProtocolExecutionContext,
    *,
    status: str,
    requested: Mapping[str, Any],
    resolved: Mapping[str, Any],
    paths: Mapping[str, Any] | None = None,
    protocol: ProtocolOptions | None = None,
    execution: ProtocolExecution | None = None,
    issues: Sequence[ProtocolIssue | Mapping[str, Any]] = (),
    details: Mapping[str, Any] | None = None,
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": context.run_id,
        "status": str(status).strip(),
        "crop": context.crop,
        "requested": dict(requested),
        "resolved": dict(resolved),
        "paths": dict(paths or {"runtime_dir": context.runtime_dir, "case_dir": context.case_dir}),
        "issues": _protocol_issues_payload(issues),
    }
    if protocol is not None:
        payload["protocol"] = _protocol_options_payload(protocol)
    if execution is not None:
        payload["execution"] = asdict(execution)
    if details:
        payload.update(_jsonify_artifact_value(details))
    if summary:
        payload["summary"] = dict(summary)
    return payload


def resolve_run_model_script() -> Path:
    return Path(__file__).resolve().parents[1] / "run_model.py"


def build_process_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    if env is None:
        return dict(os.environ)
    return {str(key): str(value) for key, value in env.items()}


def _jsonify_artifact_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _jsonify_artifact_value(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple, set)):
        return [_jsonify_artifact_value(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _merge_artifact_dict(base: dict[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        key_s = str(key)
        normalized = _jsonify_artifact_value(value)
        if isinstance(normalized, dict) and isinstance(merged.get(key_s), dict):
            merged[key_s] = _merge_artifact_dict(dict(merged[key_s]), normalized)
        else:
            merged[key_s] = normalized
    return merged


def load_json_artifact(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def update_json_artifact(path: Path, payload: Mapping[str, Any]) -> Path:
    merged = _merge_artifact_dict(load_json_artifact(path), payload)
    return atomic_write_json(path, merged)


def write_run_manifest(work_dir: Path, payload: Mapping[str, Any]) -> Path:
    return update_json_artifact(Path(work_dir) / "run_manifest.json", payload)


def write_contract_report(work_dir: Path, payload: Mapping[str, Any]) -> Path:
    return update_json_artifact(Path(work_dir) / "contract_report.json", payload)


def resolve_pestpp_executable(
    exe_name: str,
    pestpp_root: Path,
    env: dict[str, str] | None = None,
) -> Path:
    env_map = env or {}
    env_key = "PESTPP_IES" if str(exe_name).strip().lower() == "pestpp-ies.exe" else "PESTPP_GLM"
    configured = str(env_map.get(env_key, "")).strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            pestpp_root / exe_name,
            pestpp_root / "bin" / exe_name,
            pestpp_root / "vendor" / "pestpp_5.2.16_iwin" / "bin" / exe_name,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"{exe_name} not found. Checked: {', '.join(str(path) for path in candidates)}")


def cleanup_pestpp_outputs(work_dir: Path, stem: str = "ksas_mvp") -> None:
    for path in work_dir.glob(f"{stem}*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def read_key_value_output(
    path: Path,
    comment_prefixes: tuple[str, ...] = (),
) -> dict[str, float]:
    values: dict[str, float] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        if comment_prefixes and line.startswith(comment_prefixes):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            values[parts[0].strip().lower()] = float(parts[1])
        except ValueError:
            continue
    return values


def read_pst_observation_weights(pyemu_module: Any, pst_path: Path) -> dict[str, float]:
    if not pst_path.exists():
        return {}
    try:
        pst = pyemu_module.Pst(str(pst_path))
    except Exception:
        return {}
    return {
        str(obs_name).strip().lower(): float(row.weight)
        for obs_name, row in pst.observation_data.iterrows()
    }


def materialize_params_dat(source_path: Path, target_path: Path) -> Path:
    if str(source_path.suffix).lower() != ".par":
        shutil.copy(source_path, target_path)
        return target_path
    rows: list[str] = []
    for raw in source_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = raw.strip().split()
        if not parts:
            continue
        name = parts[0].strip()
        if name.startswith("!") or name.lower() in {"single", "point", "parameter"}:
            continue
        if len(parts) < 2:
            continue
        try:
            value = float(parts[1])
        except ValueError:
            continue
        rows.append(f"{name.lower()} {value}")
    target_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return target_path


def resolve_compare_param_files(
    mode: str,
    work_dir: Path,
    project_root: Path,
    env: dict[str, str] | None = None,
) -> dict[str, Path]:
    env_map = env or {}
    mode_name = str(mode).strip().lower()
    if mode_name == "tournament":
        return {
            "baseline": Path(
                str(env_map.get("TOURNAMENT_BASELINE", project_root / "work" / "params.dat"))
            ),
            "pest": Path(
                str(env_map.get("TOURNAMENT_PEST", project_root / "results" / "final_pest_params.dat"))
            ),
            "mgda": Path(
                str(env_map.get("TOURNAMENT_MGDA", project_root / "results" / "final_mgda_params.dat"))
            ),
        }
    if mode_name == "progress":
        return {
            "mgda": Path(str(env_map.get("MGDA_PARAMS_PATH", work_dir / "params_mgda.dat"))),
        }
    return {
        "baseline": work_dir / "params_baseline.dat",
        "pest": work_dir / "ksas_mvp_est.par",
        "mgda": work_dir / "params_mgda.dat",
    }


def run_compare_scenarios(
    param_files: dict[str, Path],
    work_dir: Path,
    runner: Callable[[str, Path, Path], dict[str, float]],
    skip_missing: bool = True,
) -> dict[str, dict[str, float]]:
    sim_results: dict[str, dict[str, float]] = {}
    for scenario, source_path in param_files.items():
        if not source_path.exists():
            if skip_missing:
                continue
            raise FileNotFoundError(
                f"Missing parameter file for scenario '{scenario}': {source_path}"
            )
        scenario_dir = work_dir / scenario
        scenario_dir.mkdir(exist_ok=True)
        params_path = scenario_dir / "params.dat"
        materialize_params_dat(source_path, params_path)
        sim_results[scenario] = runner(scenario, scenario_dir, params_path)
    return sim_results


def run_process(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    failure_label: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{failure_label} failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def run_python_entrypoint(
    python_executable: str,
    script_path: Path,
    cwd: Path,
    env: dict[str, str],
    failure_label: str,
    args: Sequence[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [python_executable, str(script_path)]
    if args:
        command.extend(str(arg) for arg in args)
    return run_process(command, cwd, env, failure_label)


def build_run_model_env(
    params_path: Path,
    trts: list[int] | None = None,
    keep_outputs: bool = False,
    base_env: Mapping[str, str] | None = None,
    extra_env: Mapping[str, str] | None = None,
    project_config_path: Path | None = None,
    case_dir: Path | None = None,
    cul_path: Path | None = None,
    extra_summary_vars: Sequence[str] | None = None,
    allow_missing_wht_dates: bool | None = None,
) -> dict[str, str]:
    env = build_process_env(base_env)
    if extra_env:
        env.update({str(key): str(value) for key, value in extra_env.items()})
    env["PARAMS_PATH"] = str(params_path)
    env["DSSAT_KEEP_OUTPUTS"] = "1" if keep_outputs else "0"
    if trts:
        env["DSSAT_TRTS"] = ",".join(str(int(trt)) for trt in trts)
    else:
        env.pop("DSSAT_TRTS", None)
    if project_config_path is not None:
        env["PROJECT_CONFIG"] = str(project_config_path)
    if case_dir is not None:
        env["DSSAT_CASE_DIR"] = str(case_dir)
    if extra_summary_vars is not None:
        env["DSSAT_EXTRA_SUMMARY_VARS"] = ",".join(
            str(code).strip() for code in extra_summary_vars if str(code).strip()
        )
    if cul_path is not None:
        env["CUL_PATH"] = str(cul_path)
        env["WH_CUL_PATH"] = str(cul_path)
    if allow_missing_wht_dates is True:
        env["DSSAT_ALLOW_MISSING_WHT_DATES"] = "1"
    elif allow_missing_wht_dates is False:
        env.pop("DSSAT_ALLOW_MISSING_WHT_DATES", None)
    return env


def run_model_with_params(
    work_dir: Path,
    params_path: Path,
    trts: list[int] | None = None,
    keep_outputs: bool = False,
    python_executable: str | None = None,
    run_model_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
    failure_label: str = "run_model.py",
) -> subprocess.CompletedProcess[str]:
    resolved_run_model_path = run_model_path or resolve_run_model_script()
    env = build_run_model_env(
        params_path=Path(params_path),
        trts=trts,
        keep_outputs=keep_outputs,
        base_env=os.environ,
        extra_env=extra_env,
    )
    process_env, request_path = prepare_runtime_request_process_env(
        Path(work_dir),
        artifact_name="run_model_request.json",
        env=env,
        purpose="run_model",
        script_path=resolved_run_model_path,
    )
    return run_python_entrypoint(
        python_executable or sys.executable,
        resolved_run_model_path,
        Path(work_dir),
        process_env,
        failure_label,
        args=["--runtime-request", str(request_path)],
    )


def run_compare_model(
    work_dir: Path,
    params_path: Path,
    trts: list[int] | None = None,
    keep_outputs: bool = False,
    python_executable: str | None = None,
    run_model_path: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
    failure_label: str = "compare run_model.py",
    output_path: Path | None = None,
) -> dict[str, float]:
    run_model_with_params(
        work_dir=Path(work_dir),
        params_path=Path(params_path),
        trts=trts,
        keep_outputs=keep_outputs,
        python_executable=python_executable,
        run_model_path=run_model_path,
        extra_env=dict(extra_env) if extra_env is not None else None,
        failure_label=failure_label,
    )
    return read_key_value_output(
        output_path or (Path(work_dir) / "pest_out.dat"),
        comment_prefixes=("*", "!"),
    )


def run_pestpp_executable(
    exe_name: str,
    pestpp_root: Path,
    cwd: Path,
    env: dict[str, str],
    pst_filename: str = "ksas_mvp.pst",
    failure_label: str | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = resolve_pestpp_executable(exe_name, pestpp_root, env)
    return run_process(
        [str(executable), str(pst_filename)],
        cwd,
        env,
        failure_label or f"{Path(exe_name).stem} execution",
    )


def run_pestpp_cli(
    exe_name: str,
    pestpp_root: str | Path,
    work_dir: str | Path,
    env: Mapping[str, str] | None = None,
    pst_filename: str = "ksas_mvp.pst",
    failure_label: str | None = None,
) -> subprocess.CompletedProcess[str]:
    resolved_failure_label = str(failure_label).strip() if failure_label is not None else ""
    return run_pestpp_executable(
        exe_name=str(exe_name).strip(),
        pestpp_root=Path(pestpp_root).resolve(),
        cwd=Path(work_dir).resolve(),
        env=build_process_env(env),
        pst_filename=str(pst_filename).strip() or "ksas_mvp.pst",
        failure_label=resolved_failure_label or None,
    )


def parse_best_glm_result(
    work_dir: Path,
    start_params: np.ndarray,
    param_names: list[str],
    clip_params: Callable[[np.ndarray], np.ndarray],
    stem: str = "ksas_mvp",
) -> tuple[np.ndarray, float]:
    candidate_paths = [
        work_dir / f"{stem}_est.par",
        work_dir / f"{stem}.par",
    ]
    par_path = next((candidate for candidate in candidate_paths if candidate.exists()), None)
    if par_path is None:
        raise RuntimeError(
            "Missing calibrated parameter file after pestpp-glm execution. "
            f"Checked: {', '.join(str(path.name) for path in candidate_paths)}"
        )
    return parse_single_point_par(par_path, start_params, param_names, clip_params), float("nan")


def parse_single_point_par(
    par_path: Path,
    start_params: np.ndarray,
    param_names: list[str],
    clip_params: Callable[[np.ndarray], np.ndarray],
) -> np.ndarray:
    params = np.array(start_params, dtype=float)
    if not par_path.exists():
        return params
    names = [str(name).strip().lower() for name in param_names]
    with open(par_path, "r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            parts = raw.split()
            if len(parts) < 2:
                continue
            name = parts[0].strip().lower()
            if name not in names:
                continue
            try:
                value = float(parts[1])
            except ValueError:
                continue
            params[names.index(name)] = value
    return clip_params(params)


def parse_best_ies_result(
    work_dir: Path,
    start_params: np.ndarray,
    param_names: list[str],
    clip_params: Callable[[np.ndarray], np.ndarray],
    stem: str = "ksas_mvp",
) -> tuple[np.ndarray, float]:
    phi_path = work_dir / f"{stem}.phi.actual.csv"
    if not phi_path.exists():
        raise RuntimeError(f"Missing {phi_path.name} after pestpp-ies execution")
    with open(phi_path, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError(f"{phi_path.name} is empty")
    last_row = rows[-1]
    try:
        iter_idx = int(float(last_row["iteration"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Cannot parse iteration from {phi_path.name}") from exc
    ignored = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
    best_real = None
    best_phi = float("inf")
    for key, raw_value in last_row.items():
        if key in ignored or raw_value in {None, ""}:
            continue
        try:
            phi_value = float(raw_value)
        except ValueError:
            continue
        if np.isfinite(phi_value) and phi_value < best_phi:
            best_phi = float(phi_value)
            best_real = str(key).strip()
    if not best_real:
        raise RuntimeError(f"Cannot determine best realization from {phi_path.name}")
    if best_real.lower() == "base":
        for candidate in [work_dir / f"{stem}.{iter_idx}.base.par", work_dir / f"{stem}.base.par"]:
            if candidate.exists():
                return parse_single_point_par(candidate, start_params, param_names, clip_params), best_phi
        raise RuntimeError("Best realization is base but no base par file was written")
    par_csv = work_dir / f"{stem}.{iter_idx}.par.csv"
    if not par_csv.exists():
        raise RuntimeError(f"Missing parameter ensemble file: {par_csv}")
    params = np.array(start_params, dtype=float)
    with open(par_csv, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if str(row.get("real_name", "")).strip() != best_real:
                continue
            for idx, name in enumerate(param_names):
                raw_value = row.get(name)
                if raw_value in {None, ""}:
                    continue
                try:
                    params[idx] = float(str(raw_value))
                except ValueError:
                    continue
            return clip_params(params), best_phi
    raise RuntimeError(f"Realization {best_real} not found in {par_csv.name}")


def resolve_ies_iteration(work_dir: Path, stem: str = "ksas_mvp") -> int:
    phi_path = work_dir / f"{stem}.phi.actual.csv"
    if not phi_path.exists():
        raise RuntimeError(f"Missing {phi_path.name} after pestpp-ies execution")
    with open(phi_path, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError(f"{phi_path.name} is empty")
    try:
        return int(float(rows[-1]["iteration"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Cannot parse iteration from {phi_path.name}") from exc


def load_posterior_ensemble(
    work_dir: Path,
    stem: str = "ksas_mvp",
    iteration: int | None = None,
) -> tuple[int, list[dict[str, float]]]:
    iter_idx = int(iteration) if iteration is not None else resolve_ies_iteration(work_dir, stem=stem)
    par_csv = work_dir / f"{stem}.{iter_idx}.par.csv"
    if not par_csv.exists():
        raise RuntimeError(f"Missing parameter ensemble file: {par_csv}")
    samples: list[dict[str, float]] = []
    with open(par_csv, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RuntimeError(f"{par_csv.name} is missing a header row")
        for row in reader:
            sample: dict[str, float] = {}
            for key, raw_value in row.items():
                key_name = str(key or "").strip().lower()
                if not key_name or key_name == "real_name" or raw_value in {None, ""}:
                    continue
                try:
                    sample[key_name] = float(raw_value)
                except ValueError:
                    continue
            if sample:
                samples.append(sample)
    if not samples:
        raise RuntimeError(f"{par_csv.name} does not contain numeric parameter samples")
    return iter_idx, samples


def _safe_artifact_name(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(name).strip().lower())
    return safe or "artifact"


def _write_parameter_distribution_svg(
    output_path: Path,
    parameter: str,
    posterior_values: np.ndarray,
    prior_value: float | None = None,
    best_value: float | None = None,
    prior_lower: float | None = None,
    prior_upper: float | None = None,
    posterior_median: float | None = None,
) -> Path:
    values = np.asarray(posterior_values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise RuntimeError(f"No finite posterior samples found for parameter '{parameter}'")
    xmin = float(np.min(values))
    xmax = float(np.max(values))
    extra_values = [
        value
        for value in [prior_value, best_value, prior_lower, prior_upper, posterior_median]
        if value is not None and np.isfinite(value)
    ]
    if extra_values:
        xmin = min([xmin] + [float(value) for value in extra_values])
        xmax = max([xmax] + [float(value) for value in extra_values])
    if xmin == xmax:
        xmin -= 0.5
        xmax += 0.5
    bins = min(12, max(5, int(np.sqrt(values.size))))
    hist, edges = np.histogram(values, bins=bins, range=(xmin, xmax))
    hist_max = max(float(np.max(hist)), 1.0)
    width = 760
    height = 320
    left = 70
    right = 30
    top = 30
    bottom = 55
    plot_width = width - left - right
    plot_height = height - top - bottom
    rects: list[str] = []
    for idx, count in enumerate(hist):
        x0 = left + ((edges[idx] - xmin) / (xmax - xmin)) * plot_width
        x1 = left + ((edges[idx + 1] - xmin) / (xmax - xmin)) * plot_width
        bar_height = (float(count) / hist_max) * plot_height
        y = top + plot_height - bar_height
        rects.append(
            f'<rect x="{x0:.2f}" y="{y:.2f}" width="{max(x1 - x0 - 2.0, 1.0):.2f}" '
            f'height="{bar_height:.2f}" fill="#4C78A8" opacity="0.85" />'
        )

    def build_marker(value: float | None, color: str, label: str, dash: str = "") -> str:
        if value is None or not np.isfinite(value):
            return ""
        x = left + ((float(value) - xmin) / (xmax - xmin)) * plot_width
        return (
            f'<line x1="{x:.2f}" y1="{top:.2f}" x2="{x:.2f}" y2="{top + plot_height:.2f}" '
            f'stroke="{color}" stroke-width="2" stroke-dasharray="{dash}" />'
            f'<text x="{x + 4:.2f}" y="{top + 14:.2f}" fill="{color}" font-size="11">{escape(label)}</text>'
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="100%" height="100%" fill="white" />'
        f'<text x="{left}" y="18" font-size="16" font-family="Segoe UI, Arial">{escape(parameter)} posterior</text>'
        f'<line x1="{left}" y1="{top + plot_height:.2f}" x2="{left + plot_width}" y2="{top + plot_height:.2f}" stroke="#333" />'
        f'<line x1="{left}" y1="{top:.2f}" x2="{left}" y2="{top + plot_height:.2f}" stroke="#333" />'
        + "".join(rects)
        + build_marker(prior_value, "#E45756", "prior")
        + build_marker(best_value, "#54A24B", "best")
        + build_marker(prior_lower, "#F58518", "prior_lb", "6,4")
        + build_marker(prior_upper, "#F58518", "prior_ub", "6,4")
        + build_marker(posterior_median, "#B279A2", "median", "3,3")
        + f'<text x="{left}" y="{height - 18}" font-size="11" font-family="Segoe UI, Arial">{xmin:.4f}</text>'
        + f'<text x="{left + plot_width - 40}" y="{height - 18}" font-size="11" font-family="Segoe UI, Arial">{xmax:.4f}</text>'
        + f'<text x="12" y="{top + 8:.2f}" font-size="11" font-family="Segoe UI, Arial">{hist_max:.0f}</text>'
        + f'<text x="12" y="{top + plot_height:.2f}" font-size="11" font-family="Segoe UI, Arial">0</text>'
        + "</svg>"
    )
    output_path.write_text(svg, encoding="utf-8")
    return output_path


def export_posterior_diagnostics(
    work_dir: Path,
    prior_params: dict[str, float] | None = None,
    stem: str = "ksas_mvp",
    iteration: int | None = None,
    output_dir: Path | None = None,
    include_params: list[str] | None = None,
    parameter_groups: dict[str, str] | None = None,
    prior_bounds: dict[str, tuple[float, float]] | None = None,
    parameter_order: Sequence[str] | None = None,
) -> dict[str, Path]:
    iter_idx, samples = load_posterior_ensemble(work_dir, stem=stem, iteration=iteration)
    output_root = output_dir or (work_dir / "posterior_diagnostics")
    plots_dir = output_root / "plots"
    if plots_dir.exists():
        shutil.rmtree(plots_dir)
    plots_dir.mkdir(parents=True, exist_ok=True)
    prior_map = {str(name).strip().lower(): float(value) for name, value in (prior_params or {}).items()}
    include_set = {str(name).strip().lower() for name in (include_params or []) if str(name).strip()}
    group_map = {
        str(name).strip().lower(): str(group).strip()
        for name, group in (parameter_groups or {}).items()
        if str(name).strip() and str(group).strip()
    }
    bounds_map = {
        str(name).strip().lower(): (float(bounds[0]), float(bounds[1]))
        for name, bounds in (prior_bounds or {}).items()
        if str(name).strip()
    }
    discovered_names = {
        name for sample in samples for name in sample.keys() if not include_set or name in include_set
    }
    preferred_order: list[str] = []
    for raw_name in parameter_order or ():
        name = str(raw_name).strip().lower()
        if name and name not in preferred_order:
            preferred_order.append(name)
    for raw_name in include_params or []:
        name = str(raw_name).strip().lower()
        if name and name not in preferred_order:
            preferred_order.append(name)
    for name in prior_map.keys():
        if name not in preferred_order:
            preferred_order.append(name)
    parameter_names = [name for name in preferred_order if name in discovered_names]
    parameter_names.extend(sorted(name for name in discovered_names if name not in parameter_names))
    summary_rows: list[dict[str, float | int | str]] = []
    best_by_param: dict[str, float] = {}
    par_csv = work_dir / f"{stem}.{iter_idx}.par.csv"
    phi_path = work_dir / f"{stem}.phi.actual.csv"
    with open(phi_path, "r", encoding="utf-8", newline="") as handle:
        phi_rows = list(csv.DictReader(handle))
    best_real = ""
    best_phi = float("inf")
    if phi_rows:
        last_row = phi_rows[-1]
        ignored = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
        for key, raw_value in last_row.items():
            if key in ignored or raw_value in {None, ""}:
                continue
            try:
                phi_value = float(raw_value)
            except ValueError:
                continue
            if np.isfinite(phi_value) and phi_value < best_phi:
                best_phi = float(phi_value)
                best_real = str(key).strip()
    if best_real:
        with open(par_csv, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if str(row.get("real_name", "")).strip() != best_real:
                    continue
                for key, raw_value in row.items():
                    key_name = str(key or "").strip().lower()
                    if not key_name or key_name == "real_name" or raw_value in {None, ""}:
                        continue
                    try:
                        best_by_param[key_name] = float(raw_value)
                    except ValueError:
                        continue
                break
    for name in parameter_names:
        values = np.array([sample[name] for sample in samples if name in sample], dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            continue
        summary_rows.append(
            {
                "parameter": name,
                "group": group_map.get(name, ""),
                "iteration": iter_idx,
                "sample_count": int(values.size),
                "prior": prior_map.get(name, ""),
                "best": best_by_param.get(name, ""),
                "prior_lower": bounds_map.get(name, ("", ""))[0] if name in bounds_map else "",
                "prior_upper": bounds_map.get(name, ("", ""))[1] if name in bounds_map else "",
                "posterior_mean": float(np.mean(values)),
                "posterior_std": float(np.std(values)),
                "posterior_p05": float(np.quantile(values, 0.05)),
                "posterior_p50": float(np.quantile(values, 0.50)),
                "posterior_p95": float(np.quantile(values, 0.95)),
            }
        )
        _write_parameter_distribution_svg(
            plots_dir / f"{_safe_artifact_name(name)}.svg",
            name,
            values,
            prior_value=prior_map.get(name),
            best_value=best_by_param.get(name),
            prior_lower=bounds_map.get(name, (None, None))[0] if name in bounds_map else None,
            prior_upper=bounds_map.get(name, (None, None))[1] if name in bounds_map else None,
            posterior_median=float(np.quantile(values, 0.50)),
        )
    if not summary_rows:
        raise RuntimeError(f"No posterior diagnostics could be created from {par_csv.name}")
    summary_path = output_root / "posterior_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "parameter",
                "group",
                "iteration",
                "sample_count",
                "prior",
                "best",
                "prior_lower",
                "prior_upper",
                "posterior_mean",
                "posterior_std",
                "posterior_p05",
                "posterior_p50",
                "posterior_p95",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)
    manifest_path = output_root / "posterior_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["parameter", "group", "plot_path"])
        writer.writeheader()
        for name in parameter_names:
            plot_path = plots_dir / f"{_safe_artifact_name(name)}.svg"
            if plot_path.exists():
                writer.writerow({"parameter": name, "group": group_map.get(name, ""), "plot_path": str(plot_path)})
    atlas_dir = output_root / "group_atlas"
    if atlas_dir.exists():
        shutil.rmtree(atlas_dir)
    atlas_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[str]] = {}
    for name in parameter_names:
        group_name = group_map.get(name, "ungrouped") or "ungrouped"
        groups.setdefault(group_name, []).append(name)
    for group_name, names in groups.items():
        html_rows = []
        for name in names:
            plot_path = plots_dir / f"{_safe_artifact_name(name)}.svg"
            if not plot_path.exists():
                continue
            rel_plot = plot_path.relative_to(output_root)
            html_rows.append(
                f'<h2>{escape(name)}</h2><img src="{escape(rel_plot.as_posix())}" alt="{escape(name)}" style="max-width:100%;height:auto;" />'
            )
        atlas_path = atlas_dir / f"{_safe_artifact_name(group_name)}.html"
        atlas_path.write_text(
            "<html><body><h1>"
            + escape(group_name)
            + "</h1>"
            + "".join(html_rows)
            + "</body></html>",
            encoding="utf-8",
        )
    return {
        "summary_csv": summary_path,
        "manifest_csv": manifest_path,
        "plots_dir": plots_dir,
        "atlas_dir": atlas_dir,
    }


def _read_params_dat(params_path: Path) -> dict[str, float]:
    params: dict[str, float] = {}
    if not params_path.exists():
        return params
    for raw in params_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = raw.split()
        if len(parts) < 2:
            continue
        try:
            params[str(parts[0]).strip().lower()] = float(parts[1])
        except ValueError:
            continue
    return params


def _read_bounds_preview_metadata(
    bounds_preview_path: Path,
) -> tuple[dict[str, tuple[float, float]], dict[str, str], list[str]]:
    if not bounds_preview_path.exists():
        return {}, {}, []
    bounds: dict[str, tuple[float, float]] = {}
    groups: dict[str, str] = {}
    order: list[str] = []
    with bounds_preview_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = str(row.get("parameter", "")).strip().lower()
            if not name:
                continue
            if name not in order:
                order.append(name)
            raw_lower = row.get("lower")
            raw_upper = row.get("upper")
            try:
                if raw_lower not in {None, ""} and raw_upper not in {None, ""}:
                    bounds[name] = (float(str(raw_lower)), float(str(raw_upper)))
            except ValueError:
                pass
            group = str(row.get("group", "")).strip()
            if group:
                groups[name] = group
    return bounds, groups, order


def _read_bounds_preview(
    bounds_preview_path: Path,
) -> tuple[dict[str, tuple[float, float]], dict[str, str]]:
    bounds, groups, _ = _read_bounds_preview_metadata(bounds_preview_path)
    return bounds, groups


def _resolve_posterior_reference_inputs(
    work_dir: Path,
    *,
    prior_params_path: str = "",
    bounds_preview_path: str = "",
) -> tuple[dict[str, float], dict[str, tuple[float, float]], dict[str, str], list[str]]:
    manifest = load_json_artifact(work_dir / "run_manifest.json")
    manifest_paths = manifest.get("paths", {}) if isinstance(manifest.get("paths", {}), Mapping) else {}

    prior_path_raw = str(prior_params_path).strip() or str(manifest_paths.get("params_path", "")).strip()
    prior_params = _read_params_dat(Path(prior_path_raw).resolve()) if prior_path_raw else {}

    bounds_path_raw = str(bounds_preview_path).strip() or str(manifest_paths.get("bounds_preview_path", "")).strip()
    if bounds_path_raw:
        prior_bounds, parameter_groups, parameter_order = _read_bounds_preview_metadata(Path(bounds_path_raw).resolve())
    else:
        prior_bounds, parameter_groups, parameter_order = {}, {}, []

    if not parameter_order:
        parameter_order = list(prior_params.keys())
    return prior_params, prior_bounds, parameter_groups, parameter_order


def _parse_name_list(raw: str) -> list[str]:
    return [part.strip().lower() for part in str(raw).split(",") if part.strip()]


def _format_optional_table_float(value: object) -> str:
    if value in {None, ""}:
        return f"{'':>10}"
    try:
        return f"{float(str(value)):>10.4f}"
    except (TypeError, ValueError):
        return f"{str(value):>10}"


def format_posterior_summary_table(summary_csv: Path, limit: int = 12) -> str:
    if not summary_csv.exists():
        return ""
    with summary_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return ""
    selected = rows[: max(1, int(limit))]
    header = (
        f"{'parameter':<14} {'group':<12} {'n':>4} {'prior':>10} {'best':>10} "
        f"{'mean':>10} {'p50':>10} {'lb':>10} {'ub':>10}"
    )
    lines = [header, "-" * len(header)]
    for row in selected:
        lines.append(
            f"{str(row.get('parameter', '')):<14} "
            f"{str(row.get('group', '')):<12} "
            f"{int(float(row.get('sample_count', '0') or 0)):>4} "
            f"{str(row.get('prior', '')):>10} "
            f"{str(row.get('best', '')):>10} "
            f"{_format_optional_table_float(row.get('posterior_mean', 'nan'))} "
            f"{_format_optional_table_float(row.get('posterior_p50', 'nan'))} "
            f"{_format_optional_table_float(row.get('prior_lower', 'nan'))} "
            f"{_format_optional_table_float(row.get('prior_upper', 'nan'))}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--exe-name", required=True)
    run_parser.add_argument("--pestpp-root", required=True)
    run_parser.add_argument("--work-dir", required=True)
    run_parser.add_argument("--pst-filename", default="ksas_mvp.pst")
    run_parser.add_argument("--failure-label", default="")

    export_parser = subparsers.add_parser("export-posterior")
    export_parser.add_argument("--work-dir", required=True)
    export_parser.add_argument("--stem", default="ksas_mvp")
    export_parser.add_argument("--iteration", type=int, default=None)
    export_parser.add_argument("--prior-params", default="")
    export_parser.add_argument("--bounds-preview", default="")
    export_parser.add_argument("--output-dir", default="")
    export_parser.add_argument("--include-params", default="")
    export_parser.add_argument("--table-limit", type=int, default=12)

    args = parser.parse_args()
    if args.command == "run":
        run_pestpp_cli(
            exe_name=args.exe_name,
            pestpp_root=args.pestpp_root,
            work_dir=args.work_dir,
            env=os.environ,
            pst_filename=args.pst_filename,
            failure_label=str(args.failure_label).strip() or None,
        )
        return
    if args.command != "export-posterior":
        parser.print_help()
        return

    work_dir = Path(args.work_dir).resolve()
    prior_params, prior_bounds, parameter_groups, parameter_order = _resolve_posterior_reference_inputs(
        work_dir,
        prior_params_path=str(args.prior_params),
        bounds_preview_path=str(args.bounds_preview),
    )
    output_dir = Path(args.output_dir).resolve() if str(args.output_dir).strip() else None
    artifacts = export_posterior_diagnostics(
        work_dir=work_dir,
        prior_params=prior_params,
        stem=str(args.stem).strip() or "ksas_mvp",
        iteration=args.iteration,
        output_dir=output_dir,
        include_params=_parse_name_list(args.include_params),
        parameter_groups=parameter_groups,
        prior_bounds=prior_bounds,
        parameter_order=parameter_order,
    )
    print(f"Posterior summary saved to {artifacts['summary_csv']}")
    print(f"Posterior manifest saved to {artifacts['manifest_csv']}")
    print(f"Posterior plots saved to {artifacts['plots_dir']}")
    print(f"Posterior atlas saved to {artifacts['atlas_dir']}")
    table_text = format_posterior_summary_table(artifacts["summary_csv"], limit=args.table_limit)
    if table_text:
        print(table_text)


if __name__ == "__main__":
    main()
