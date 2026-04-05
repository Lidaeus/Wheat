from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable


def write_pest_output_instruction_file(
    path: Path,
    trts: list[int],
    summary_metrics: list[str],
    wht_dates_by_trt: dict[int, list[int]] | None = None,
    wht_second: str = "",
) -> None:
    lines = ["pif ~"]
    for trt in trts:
        for metric_code in summary_metrics:
            obs_key = f"{str(metric_code).strip().lower()}_t{int(trt):02d}"
            lines.append(f"~{obs_key}~ !{obs_key}!")
        if wht_dates_by_trt and int(trt) in wht_dates_by_trt:
            for date in wht_dates_by_trt[int(trt)]:
                obs_key = f"laid_t{int(trt):02d}_d{int(date)}"
                lines.append(f"~{obs_key}~ !{obs_key}!")
                if wht_second:
                    obs_key2 = f"{str(wht_second).strip().lower()}_t{int(trt):02d}_d{int(date)}"
                    lines.append(f"~{obs_key2}~ !{obs_key2}!")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_build_pest_setup_script() -> Path:
    return Path(__file__).resolve().parents[1] / "build_pest_setup.py"


def create_pst(pyemu_module: Any, pst_filename: str = "ksas_mvp.pst") -> Any:
    return pyemu_module.utils.helpers.pst_from_io_files(
        tpl_files=["params.tpl"],
        in_files=["params.dat"],
        ins_files=["pest_out.ins"],
        out_files=["pest_out.dat"],
        pst_filename=pst_filename,
    )


def configure_pst_for_estimation(
    pst: Any,
    model_command: str,
    noptmax: int,
    ies_num_reals: int | None = None,
    ies_subset_size: int | None = None,
) -> Any:
    pst.model_command = [str(model_command)]
    pst.control_data.noptmax = int(noptmax)
    pst.control_data.pestmode = "estimation"
    if ies_num_reals is not None:
        pst.pestpp_options["ies_num_reals"] = int(ies_num_reals)
    if ies_subset_size is not None:
        pst.pestpp_options["ies_subset_size"] = int(ies_subset_size)
    pst.pestpp_options["ies_save_binary"] = False
    return pst


def apply_parameter_configuration(
    pst: Any,
    pst_bounds: dict[str, tuple[float, float, str]],
    params: dict[str, float],
    active_params: set[str] | None = None,
) -> Any:
    for param_name, (lb, ub, group_name) in pst_bounds.items():
        if param_name not in pst.parameter_data.index:
            continue
        pst.parameter_data.loc[param_name, "parlbnd"] = float(lb)
        pst.parameter_data.loc[param_name, "parubnd"] = float(ub)
        pst.parameter_data.loc[param_name, "pargp"] = str(group_name)
        pst.parameter_data.loc[param_name, "partrans"] = "none"
        pst.parameter_data.loc[param_name, "parval1"] = float(params.get(param_name, pst.parameter_data.loc[param_name, "parval1"]))
    if active_params:
        active = {str(name).strip().lower() for name in active_params}
        for pname in pst.parameter_data.index.astype(str).tolist():
            if str(pname).strip().lower() not in active:
                pst.parameter_data.loc[pname, "partrans"] = "fixed"
    return pst


def ensure_parameter_groups(
    pst: Any,
    group_specs: dict[str, tuple[str, float]],
    group_defaults: dict[str, Any],
) -> Any:
    pst.parameter_groups.index = pst.parameter_groups.pargpnme
    base_group = pst.parameter_groups.iloc[0].copy()
    for group_name, (inctyp, derinc) in group_specs.items():
        if group_name not in pst.parameter_groups.index:
            pst.parameter_groups.loc[group_name, :] = base_group
            pst.parameter_groups.loc[group_name, "pargpnme"] = group_name
        pst.parameter_groups.loc[group_name, "inctyp"] = str(inctyp)
        pst.parameter_groups.loc[group_name, "derinc"] = float(derinc)
        for key, value in group_defaults.items():
            pst.parameter_groups.loc[group_name, key] = value
    return pst


def compute_group_weights(
    group_defs: dict[str, dict[str, Any]],
    group_variances: dict[str, float],
    group_maxima: dict[str, float],
    weight_mode: str,
    mgda_alphas: dict[str, float] | None = None,
) -> dict[str, float]:
    group_weights: dict[str, float] = {}
    alphas = {str(name): float(value) for name, value in (mgda_alphas or {}).items()}
    alpha_count = len(alphas)
    for group_name in set(group_variances.keys()) | set(group_maxima.keys()):
        variance = float(group_variances.get(group_name, float("nan")))
        maximum = float(group_maxima.get(group_name, float("nan")))
        fallback_weight = float(group_defs.get(group_name, {}).get("weight", 1.0))
        sigma = float(group_defs.get(group_name, {}).get("sigma", 1.0))
        if str(weight_mode).strip().lower() == "w8_dssat_group_max":
            if math.isfinite(maximum) and maximum > 0.0:
                base_weight = 1.0 / maximum
            else:
                base_weight = fallback_weight
        else:
            std = math.sqrt(variance) if (math.isfinite(variance) and variance > 0.0) else sigma
            if std > 0.0:
                base_weight = 1.0 / std
            else:
                base_weight = fallback_weight
        if group_name in alphas and alpha_count > 0:
            modulation = math.sqrt(float(alphas[group_name]) * alpha_count)
            group_weights[group_name] = float(base_weight * modulation)
        else:
            group_weights[group_name] = float(base_weight)
    return group_weights


def apply_observation_configuration(
    pst: Any,
    meas: dict[str, float],
    group_defs: dict[str, dict[str, Any]],
    group_weights: dict[str, float],
    weights_overrides: dict[str, float],
    split_by_trt: dict[int, str],
    active_metrics: set[str],
    yield_prefix: str,
    laix_prefix: str,
    resolve_obs_group_name: Callable[[str, dict[str, dict[str, Any]], str, str], str],
    extract_metric_from_obs_name: Callable[[str], str],
    extract_trt_from_obs_name: Callable[[str], int | None],
) -> Any:
    for oname, obsval in meas.items():
        if oname in pst.observation_data.index:
            pst.observation_data.loc[oname, "obsval"] = float(obsval)
    for oname in pst.observation_data.index.astype(str).tolist():
        name_l = oname.lower()
        group_name = resolve_obs_group_name(oname, group_defs, yield_prefix, laix_prefix)
        pst.observation_data.loc[oname, "obgnme"] = str(group_name)
        pst.observation_data.loc[oname, "weight"] = float(group_weights.get(group_name, 1.0))
        if name_l in weights_overrides:
            pst.observation_data.loc[oname, "weight"] = float(weights_overrides[name_l])
        if active_metrics and extract_metric_from_obs_name(oname) not in active_metrics:
            pst.observation_data.loc[oname, "weight"] = 0.0
        trt = extract_trt_from_obs_name(oname)
        if (trt is not None) and (split_by_trt.get(int(trt)) == "valid"):
            pst.observation_data.loc[oname, "weight"] = 0.0
        if oname not in meas:
            pst.observation_data.loc[oname, "weight"] = 0.0
    return pst


def build_pst(
    pyemu_module: Any,
    model_command: str,
    noptmax: int,
    pst_bounds: dict[str, tuple[float, float, str]],
    params: dict[str, float],
    group_specs: dict[str, tuple[str, float]],
    group_defaults: dict[str, Any],
    meas: dict[str, float],
    group_defs: dict[str, dict[str, Any]],
    group_weights: dict[str, float],
    weights_overrides: dict[str, float],
    split_by_trt: dict[int, str],
    active_metrics: set[str],
    yield_prefix: str,
    laix_prefix: str,
    resolve_obs_group_name: Callable[[str, dict[str, dict[str, Any]], str, str], str],
    extract_metric_from_obs_name: Callable[[str], str],
    extract_trt_from_obs_name: Callable[[str], int | None],
    active_params: set[str] | None = None,
    pst_filename: str = "ksas_mvp.pst",
    ies_num_reals: int | None = None,
    ies_subset_size: int | None = None,
    pestpp_options: dict[str, Any] | None = None,
) -> Any:
    pst = create_pst(pyemu_module, pst_filename=pst_filename)
    configure_pst_for_estimation(
        pst,
        model_command=model_command,
        noptmax=noptmax,
        ies_num_reals=ies_num_reals,
        ies_subset_size=ies_subset_size,
    )
    for option_name, option_value in (pestpp_options or {}).items():
        pst.pestpp_options[str(option_name)] = option_value
    apply_parameter_configuration(pst, pst_bounds, params, active_params if active_params else None)
    ensure_parameter_groups(pst, group_specs, group_defaults)
    apply_observation_configuration(
        pst,
        meas,
        group_defs,
        group_weights,
        weights_overrides,
        split_by_trt,
        active_metrics,
        yield_prefix,
        laix_prefix,
        resolve_obs_group_name,
        extract_metric_from_obs_name,
        extract_trt_from_obs_name,
    )
    return pst


def build_pst_via_script(
    script_path: Path,
    working_dir: Path,
    env: dict[str, str],
    run_process_fn: Callable[[list[str], Path, dict[str, str], str], Any],
    python_executable: str | None = None,
    label: str = "build_pest_setup.py",
) -> Any:
    return run_process_fn(
        [str(python_executable or sys.executable), str(script_path)],
        Path(working_dir),
        dict(env),
        str(label),
    )


def run_build_pest_setup(
    working_dir: Path,
    env: dict[str, str],
    python_executable: str | None = None,
    script_path: Path | None = None,
    label: str = "build_pest_setup.py",
) -> Any:
    from calibration_core.pest_runner import prepare_runtime_request_process_env, run_python_entrypoint

    resolved_script_path = script_path or resolve_build_pest_setup_script()
    process_env, request_path = prepare_runtime_request_process_env(
        Path(working_dir),
        artifact_name="build_pest_setup_request.json",
        env=env,
        purpose="build_pest_setup",
        script_path=resolved_script_path,
    )

    return run_python_entrypoint(
        python_executable or sys.executable,
        resolved_script_path,
        Path(working_dir),
        process_env,
        str(label),
        args=["--runtime-request", str(request_path)],
    )


def run_build_pest_setup_cli(
    work_dir: str | Path,
    env: Mapping[str, str] | None = None,
    python_executable: str | None = None,
    script_path: str | Path | None = None,
    label: str | None = None,
) -> Any:
    from calibration_core.pest_runner import build_process_env

    resolved_script_path = Path(script_path).resolve() if script_path is not None and str(script_path).strip() else None
    resolved_label = str(label).strip() if label is not None else ""
    resolved_python_executable = str(python_executable).strip() if python_executable is not None else ""
    return run_build_pest_setup(
        working_dir=Path(work_dir).resolve(),
        env=build_process_env(env),
        python_executable=resolved_python_executable or None,
        script_path=resolved_script_path,
        label=resolved_label or "build_pest_setup.py",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--work-dir", required=True)
    run_parser.add_argument("--python-executable", default="")
    run_parser.add_argument("--script-path", default="")
    run_parser.add_argument("--label", default="build_pest_setup.py")

    args = parser.parse_args()
    if args.command != "run":
        parser.print_help()
        return
    run_build_pest_setup_cli(
        work_dir=args.work_dir,
        env=os.environ,
        python_executable=args.python_executable,
        script_path=args.script_path,
        label=args.label,
    )


__all__ = [
    "write_pest_output_instruction_file",
    "resolve_build_pest_setup_script",
    "create_pst",
    "configure_pst_for_estimation",
    "apply_parameter_configuration",
    "ensure_parameter_groups",
    "compute_group_weights",
    "apply_observation_configuration",
    "build_pst",
    "build_pst_via_script",
    "run_build_pest_setup",
    "run_build_pest_setup_cli",
]


if __name__ == "__main__":
    main()
