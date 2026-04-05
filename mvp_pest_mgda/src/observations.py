from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from crop_registry import resolve_crop_profile_from_context


@dataclass(frozen=True)
class CaseRuntimeConfig:
    var_codes: list[str]
    t_vars: list[str]
    allow_missing_dates: bool
    wht_dates_by_trt: dict[int, list[int]]


@dataclass(frozen=True)
class ObservationRuntime:
    obs_a_path: Path
    obs_wht_path: Path | None
    wht_dates_by_trt: dict[int, list[int]]


@dataclass(frozen=True)
class OutputContract:
    var_codes: list[str]
    t_vars: list[str]
    allow_missing_dates: bool


def resolve_optional_case_path(dssat_dir: Path, raw_path: str) -> Path | None:
    raw = str(raw_path).strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = dssat_dir / path
    return path


def resolve_wht_path(dssat_dir: Path, cfg: dict) -> Path | None:
    cfg_paths = cfg.get("paths", {})
    raw = str(cfg_paths.get("obs_t_path", "")).strip() or str(cfg_paths.get("wht_path", "")).strip()
    return resolve_optional_case_path(dssat_dir, raw)


def resolve_obs_a_path(dssat_dir: Path, cfg: dict, live_filex: Path, env_obs_a_path: str = "") -> Path:
    cfg_paths = cfg.get("paths", {})
    a_path_env = str(env_obs_a_path).strip()
    a_path_raw = a_path_env or str(cfg_paths.get("obs_a_path", "")).strip() or str(cfg_paths.get("wha_path", "")).strip()
    a_path = None
    if a_path_raw and not a_path_raw.lower().startswith("__skip__"):
        a_path = resolve_optional_case_path(dssat_dir, a_path_raw)
    if a_path is not None:
        return a_path
    suffix = live_filex.suffix
    if suffix.upper().endswith("X") and len(suffix) >= 2:
        return live_filex.with_suffix(suffix[:-1] + "A")
    return live_filex.with_suffix(".A")


def resolve_metrics_cfg(cfg: dict) -> dict:
    return cfg.get("metrics", {}) or cfg.get("variables", {}) or {}


def parse_var_codes(value: str) -> list[str]:
    out: list[str] = []
    for token in re.split(r"[\s,;]+", str(value or "").strip()):
        code = str(token).strip().upper()
        if code:
            out.append(code)
    return out


def dedupe_codes(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        code_u = str(code).strip().upper()
        if not code_u or code_u in seen:
            continue
        seen.add(code_u)
        out.append(code_u)
    return out


def resolve_summary_var_codes(yield_code: str, laix_code: str, env_extra_summary_vars: str = "") -> list[str]:
    extra_summary_codes = parse_var_codes(env_extra_summary_vars)
    return dedupe_codes([code for code in [yield_code, laix_code, *extra_summary_codes] if str(code).strip()])


def resolve_allow_missing_dates(cfg: dict, env_allow_missing: str = "") -> bool:
    raw = str(env_allow_missing).strip().lower()
    if raw in {"1", "true", "yes", "y"}:
        return True
    return bool((cfg.get("observations", {}) or {}).get("allow_missing_obs_files", False))


def _resolve_metric_defaults(cfg: dict | None = None) -> tuple[str, str, list[str]]:
    profile = resolve_crop_profile_from_context(cfg or {})
    t_vars = [str(value).strip().upper() for value in profile.timeseries_metrics if str(value).strip()]
    if not t_vars:
        t_vars = ["LAID", "LWAD", "SWAD"]
    return profile.yield_metric or "HWAM", profile.laix_metric or "LAIX", t_vars


def resolve_t_vars(metrics_cfg: dict, cfg: dict | None = None) -> list[str]:
    t_vars_cfg = metrics_cfg.get("t_vars", None)
    if isinstance(t_vars_cfg, list) and t_vars_cfg:
        out = [str(value).strip().upper() for value in t_vars_cfg if str(value).strip()]
        if out:
            return out
    return _resolve_metric_defaults(cfg)[2]


def resolve_primary_metric_codes(metrics_cfg: dict, a_path: Path, cfg: dict | None = None) -> tuple[str, str]:
    default_yield_code, default_laix_code, _ = _resolve_metric_defaults(cfg)
    yield_var_cfg = str(metrics_cfg.get("yield_var", "YIELD")).strip().upper()
    yield_code = yield_var_cfg if yield_var_cfg != "YIELD" else default_yield_code
    laix_code = str(metrics_cfg.get("laix_var", default_laix_code)).strip().upper()
    if not a_path.exists():
        return "", ""
    try:
        header = None
        for line in a_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("@TRNO"):
                header = line
                break
        if not header:
            return "", ""
        cols_u = {col.lstrip("@").strip().upper() for col in header.split()}
        if yield_code and yield_code not in cols_u:
            yield_code = ""
        if laix_code and laix_code not in cols_u:
            laix_code = ""
        return yield_code, laix_code
    except Exception:
        return "", ""


def read_wht_dates_by_trt(wht_path: Path, trts: list[int]) -> dict[int, list[int]]:
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

    cols = [column.lstrip("@").strip() for column in header.split()]
    if "TRNO" not in cols or "DATE" not in cols:
        return {}
    i_trno = cols.index("TRNO")
    i_date = cols.index("DATE")

    dates_by_trt: dict[int, list[int]] = {}
    wanted = {int(trt) for trt in trts}
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
        if trno not in wanted:
            continue
        dates_by_trt.setdefault(trno, []).append(date)

    for trt, dates in list(dates_by_trt.items()):
        dates_by_trt[int(trt)] = sorted(set(int(date) for date in dates))
    return dates_by_trt


def resolve_case_runtime_config(
    cfg: dict,
    a_path: Path,
    wht_dates_by_trt: dict[int, list[int]],
    env_extra_summary_vars: str = "",
    env_allow_missing: str = "",
) -> CaseRuntimeConfig:
    metrics_cfg = resolve_metrics_cfg(cfg)
    yield_code, laix_code = resolve_primary_metric_codes(metrics_cfg, a_path, cfg)
    return CaseRuntimeConfig(
        var_codes=resolve_summary_var_codes(yield_code, laix_code, env_extra_summary_vars=env_extra_summary_vars),
        t_vars=resolve_t_vars(metrics_cfg, cfg),
        allow_missing_dates=resolve_allow_missing_dates(cfg, env_allow_missing=env_allow_missing),
        wht_dates_by_trt={int(trt): [int(date) for date in dates] for trt, dates in wht_dates_by_trt.items()},
    )


def resolve_observation_runtime(
    dssat_dir: Path,
    cfg: dict,
    live_filex: Path,
    trts: list[int],
    env_obs_a_path: str = "",
) -> ObservationRuntime:
    obs_wht_path = resolve_wht_path(dssat_dir, cfg)
    if obs_wht_path is not None and obs_wht_path.exists():
        wht_dates_by_trt = read_wht_dates_by_trt(obs_wht_path, trts)
    else:
        wht_dates_by_trt = {}
    obs_a_path = resolve_obs_a_path(dssat_dir, cfg, live_filex, env_obs_a_path=env_obs_a_path)
    return ObservationRuntime(
        obs_a_path=obs_a_path,
        obs_wht_path=obs_wht_path,
        wht_dates_by_trt=wht_dates_by_trt,
    )


def resolve_output_contract(
    cfg: dict,
    a_path: Path,
    env_extra_summary_vars: str = "",
    env_allow_missing: str = "",
) -> OutputContract:
    metrics_cfg = resolve_metrics_cfg(cfg)
    yield_code, laix_code = resolve_primary_metric_codes(metrics_cfg, a_path, cfg)
    return OutputContract(
        var_codes=resolve_summary_var_codes(yield_code, laix_code, env_extra_summary_vars=env_extra_summary_vars),
        t_vars=resolve_t_vars(metrics_cfg, cfg),
        allow_missing_dates=resolve_allow_missing_dates(cfg, env_allow_missing=env_allow_missing),
    )


def resolve_observation_contracts(
    dssat_dir: Path,
    cfg: dict,
    live_filex: Path,
    trts: list[int],
    env_obs_a_path: str = "",
    env_extra_summary_vars: str = "",
    env_allow_missing: str = "",
) -> tuple[ObservationRuntime, OutputContract]:
    observation = resolve_observation_runtime(
        dssat_dir,
        cfg,
        live_filex,
        trts,
        env_obs_a_path=env_obs_a_path,
    )
    output = resolve_output_contract(
        cfg,
        observation.obs_a_path,
        env_extra_summary_vars=env_extra_summary_vars,
        env_allow_missing=env_allow_missing,
    )
    return observation, output
