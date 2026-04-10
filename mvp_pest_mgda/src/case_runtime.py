from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
from pathlib import Path

from observations import (
    CaseRuntimeConfig,
    ObservationRuntime,
    OutputContract,
    dedupe_codes,
    parse_var_codes,
    read_wht_dates_by_trt,
    resolve_allow_missing_dates,
    resolve_case_runtime_config,
    resolve_metrics_cfg,
    resolve_obs_a_path,
    resolve_observation_contracts,
    resolve_observation_runtime,
    resolve_optional_case_path,
    resolve_output_contract,
    resolve_primary_metric_codes,
    resolve_summary_var_codes,
    resolve_t_vars,
    resolve_wht_path,
)
from crop_registry import resolve_crop_profile_from_context
from dssat_io import resolve_dssat_case_dir, resolve_dssat_exe_path, resolve_dssat_genotype_dir, resolve_dssat_root
from result_schema import build_pest_output_text

__all__ = [
    "CaseRuntimeConfig",
    "ObservationRuntime",
    "OutputContract",
    "dedupe_codes",
    "parse_var_codes",
    "read_wht_dates_by_trt",
    "resolve_allow_missing_dates",
    "resolve_case_runtime_config",
    "resolve_metrics_cfg",
    "resolve_obs_a_path",
    "resolve_observation_runtime",
    "resolve_output_contract",
    "resolve_primary_metric_codes",
    "resolve_summary_var_codes",
    "resolve_t_vars",
    "resolve_wht_path",
    "CaseInputPlan",
    "CaseRuntime",
    "RuntimeFileState",
    "resolve_case_dir",
    "resolve_runtime_root",
    "candidate_cul_sources",
    "candidate_case_support_sources",
    "candidate_genotype_sources",
    "build_pest_output_text",
    "rewrite_cultivar_path_row",
    "parse_inp_cultivar_reference",
    "infer_cul_path_from_inp",
    "resolve_cultivar_path",
    "resolve_adapter_paths",
    "resolve_sh2o_updates",
    "resolve_cul_updates",
    "resolve_input_plan",
    "resolve_runtime_file_state",
    "resolve_case_runtime",
    "ensure_local_dssatpro",
]


@dataclass(frozen=True)
class CaseInputPlan:
    has_sh2o: bool
    sh2o_by_icbl: dict[int, float]
    cul_updates: dict[str, float]
    wth_updates: list
    sol_updates: list
    wth_path: Path | None
    sol_path: Path | None


@dataclass(frozen=True)
class CaseRuntime:
    observation: ObservationRuntime
    output: OutputContract
    input_plan: CaseInputPlan


@dataclass(frozen=True)
class RuntimeFileState:
    live_filex_path: Path
    live_filex_original: str
    cul_path: Path
    cul_original: str
    wth_path: Path | None
    wth_original: str | None
    sol_path: Path | None
    sol_original: str | None


def resolve_case_dir(
    cwd: Path,
    project_root: Path,
    cfg: dict,
    env_case_dir: str = "",
    local_case_exists: bool | None = None,
) -> Path:
    env_dir = str(env_case_dir).strip()
    if env_dir:
        return Path(env_dir).resolve()
    cfg_dir = str((cfg.get("paths", {}) or {}).get("dssat_case_dir", "")).strip()
    if cfg_dir:
        resolved_cfg_dir = resolve_dssat_case_dir(project_root, cfg=cfg)
        if resolved_cfg_dir.exists():
            return resolved_cfg_dir
    local = (cwd / "dssat_case").resolve()
    exists = local.exists() if local_case_exists is None else bool(local_case_exists)
    if exists:
        return local
    return (project_root / "data" / "dssat").resolve()


def resolve_runtime_root(project_root: Path, env_runtime_root: str = "") -> Path:
    raw = str(env_runtime_root).strip()
    if raw:
        return Path(raw).resolve()
    return (project_root.parent / "local_dssat").resolve()


def dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved not in out:
            out.append(resolved)
    return out


def candidate_cul_sources(project_root: Path, dssat_dir: Path, cul_name: str) -> list[Path]:
    return dedupe_paths(
        [
            dssat_dir / "GENOTYPE" / cul_name,
            project_root / "scripts" / "dssat_case" / "GENOTYPE" / cul_name,
            project_root.parent / "autoresearch_sandbox" / "dssat_case" / "GENOTYPE" / cul_name,
            resolve_dssat_genotype_dir(project_root) / cul_name,
        ]
    )


def candidate_case_support_sources(project_root: Path, name: str) -> list[Path]:
    return dedupe_paths(
        [
            project_root.parent / "autoresearch_sandbox" / "dssat_case" / name,
            project_root / "data" / "dssat" / name,
            project_root.parent / name,
            resolve_dssat_exe_path(project_root).parent / name,
        ]
    )


def candidate_genotype_sources(
    project_root: Path,
    dssat_dir: Path,
    base_name: str,
    suffix: str,
    cul_path: Path,
) -> list[Path]:
    file_name = f"{base_name}{suffix}"
    legacy_root = Path(r"C:\DSSAT48")
    candidates = [
        cul_path if suffix.upper() == ".CUL" else None,
        cul_path.parent / file_name if cul_path else None,
        dssat_dir / "GENOTYPE" / file_name,
        project_root / "scripts" / "dssat_case" / "GENOTYPE" / file_name,
        project_root.parent / "autoresearch_sandbox" / "dssat_case" / "GENOTYPE" / file_name,
        resolve_dssat_genotype_dir(project_root) / file_name,
        legacy_root / "Genotype" / file_name,
        legacy_root / "GENOTYPE" / file_name,
    ]
    return dedupe_paths([path for path in candidates if path is not None])


def runtime_cultivar_dir_text(cultivar_dir: Path) -> str:
    return str(cultivar_dir.resolve()) + "\\"


def rewrite_cultivar_path_row(file_name: str, row: str, new_dir: str) -> tuple[str, bool]:
    upper_name = str(file_name).upper()
    path_match = re.search(r"[A-Za-z]:\\.*$", row)
    if upper_name.endswith(".INP"):
        should_replace = (
            row.startswith("SPECIES")
            or row.startswith("ECOTYPE")
            or row.startswith("CULTIVAR")
        ) and path_match is not None
        error_prefix = "DSSAT48.INP"
    else:
        should_replace = any(ext in row.upper() for ext in (".CUL", ".ECO", ".SPE")) and path_match is not None
        error_prefix = "DSSAT48.INH"

    if not should_replace:
        return row, False

    if path_match is None:
        return row, False

    idx = int(path_match.start())
    old_tail = row[idx:]
    repl = new_dir.ljust(len(old_tail))[: len(old_tail)]
    orig_len = len(row)
    updated = row[:idx] + repl
    if len(updated) != orig_len:
        raise RuntimeError(f"{error_prefix} row length mismatch after path replace")
    if updated[idx : idx + len(old_tail)] != repl:
        raise RuntimeError(f"{error_prefix} path slice mismatch after replace")
    return updated, True


def rewrite_cultivar_path_lines(file_name: str, raw_lines: list[str], cultivar_dir: Path) -> tuple[list[str], bool]:
    new_dir = runtime_cultivar_dir_text(cultivar_dir)
    out: list[str] = []
    changed = False
    for line in raw_lines:
        row = line.rstrip("\r\n")
        ending = line[len(row) :]
        updated, row_changed = rewrite_cultivar_path_row(file_name, row, new_dir)
        out.append(updated + ending)
        changed = changed or row_changed
    return out, changed


def patch_cultivar_dir_in_inp_inh(dssat_dir: Path, cultivar_dir: Path) -> None:
    targets = [dssat_dir / "DSSAT48.INP", dssat_dir / "DSSAT48.INH"]
    for path in targets:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        out, changed = rewrite_cultivar_path_lines(path.name, raw, cultivar_dir)
        if changed:
            path.write_text("".join(out), encoding="utf-8")


def parse_inp_cultivar_reference(lines: list[str]) -> tuple[str | None, str | None]:
    cul_file_name = None
    cul_src_dir = None
    for raw in lines:
        cleaned = raw.replace("\x00", "").strip()
        if not cleaned.startswith("CULTIVAR"):
            continue
        if ".CUL" not in cleaned.upper():
            continue
        for token in cleaned.split():
            if token.upper().endswith(".CUL"):
                cul_file_name = token.strip()
                break
        import re
        drive_match = re.search(r"[A-Za-z]:\\", cleaned)
        if drive_match:
            cul_src_dir = cleaned[drive_match.start() :].strip()
        break
    return cul_file_name, cul_src_dir


def infer_cul_path_from_inp(dssat_dir: Path, cfg: dict) -> Path | None:
    cfg_paths = cfg.get("paths", {})
    inp_name = str(cfg_paths.get("inp_name", "")).strip() or "DSSAT48.INP"
    inp_path = dssat_dir / inp_name
    if not inp_path.exists():
        inp_path = dssat_dir / "DSSAT48.INP"
        if not inp_path.exists():
            return None

    cul_file_name, cul_src_dir = parse_inp_cultivar_reference(
        inp_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    )

    geno_dir = dssat_dir / "GENOTYPE"
    if cul_file_name and geno_dir.exists():
        in_case = geno_dir / cul_file_name
        if in_case.exists():
            return in_case

    if cul_src_dir and cul_file_name:
        try:
            src = (Path(cul_src_dir) / cul_file_name).resolve()
        except Exception:
            src = None
        if src and src.exists():
            return src

    return None


def resolve_cultivar_path(
    dssat_dir: Path,
    cfg: dict,
    env_cul_path: str = "",
    env_wh_cul_path: str = "",
    project_root: Path | None = None,
) -> Path:
    cul_env = str(env_cul_path).strip() or str(env_wh_cul_path).strip()
    if cul_env:
        return Path(cul_env)

    inferred = infer_cul_path_from_inp(dssat_dir, cfg)
    if inferred is not None:
        return inferred

    geno_dir = dssat_dir / "GENOTYPE"
    in_case_culs = sorted(geno_dir.glob("*.CUL")) if geno_dir.exists() else []
    cfg_paths = cfg.get("paths", {})
    cfg_cul = str(cfg_paths.get("cul_path", "")).strip() or str(cfg_paths.get("wh_cul_path", "")).strip()
    if in_case_culs:
        return in_case_culs[0]
    if cfg_cul:
        resolved_cfg_cul = Path(cfg_cul)
        if not resolved_cfg_cul.is_absolute():
            resolved_cfg_cul = resolve_dssat_root(project_root or Path.cwd(), cfg=cfg) / resolved_cfg_cul
        if resolved_cfg_cul.exists():
            return resolved_cfg_cul

    fallback_cultivar = resolve_crop_profile_from_context(cfg, dssat_dir).cultivar_file
    genotype_dir = resolve_dssat_genotype_dir(project_root or dssat_dir.parent, cfg=cfg)
    if fallback_cultivar:
        return genotype_dir / fallback_cultivar
    return genotype_dir / "WHCER048.CUL"


def ensure_case_support_files(dssat_dir: Path, project_root: Path) -> None:
    dssat_dir.mkdir(parents=True, exist_ok=True)
    for name in ("DSSAT48.INP", "DSSAT48.INH"):
        target = dssat_dir / name
        if target.exists() and target.stat().st_size > 0:
            continue
        for src in candidate_case_support_sources(project_root, name):
            if not src.exists() or src.stat().st_size <= 0:
                continue
            shutil.copy2(src, target)
            break


def ensure_nonempty_cultivar_file(target: Path, project_root: Path, dssat_dir: Path) -> None:
    for src in candidate_cul_sources(project_root, dssat_dir, target.name):
        if src == target:
            continue
        if not src.exists() or src.stat().st_size <= 0:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if (not target.exists()) or target.stat().st_size <= 0:
            shutil.copy2(src, target)
        return


def ensure_local_runtime(
    project_root: Path,
    dssat_dir: Path,
    cul_path: Path,
    cfg: dict,
    env_runtime_root: str = "",
    env_dssat_exe: str = "",
) -> tuple[Path, Path]:
    runtime_root = resolve_runtime_root(project_root, env_runtime_root)
    runtime_genotype = runtime_root / "Genotype"
    runtime_root.mkdir(parents=True, exist_ok=True)
    runtime_genotype.mkdir(parents=True, exist_ok=True)

    src_exe = resolve_dssat_exe_path(project_root, cfg=cfg, env_dssat_exe=env_dssat_exe)
    runtime_exe = runtime_root / src_exe.name
    if src_exe.exists():
        need_copy = True
        if runtime_exe.exists():
            try:
                src_stat = src_exe.stat()
                dst_stat = runtime_exe.stat()
                need_copy = (dst_stat.st_size != src_stat.st_size) or (dst_stat.st_mtime < src_stat.st_mtime)
            except Exception:
                need_copy = True
        if need_copy:
            shutil.copy2(src_exe, runtime_exe)

    src_dssatpro = project_root / "DSSATPRO.v48"
    if src_dssatpro.exists() and src_dssatpro.stat().st_size > 0:
        dst_dssatpro = runtime_root / "DSSATPRO.v48"
        need_copy = True
        if dst_dssatpro.exists():
            try:
                src_stat = src_dssatpro.stat()
                dst_stat = dst_dssatpro.stat()
                need_copy = (dst_stat.st_size != src_stat.st_size) or (dst_stat.st_mtime < src_stat.st_mtime)
            except Exception:
                need_copy = True
        if need_copy:
            shutil.copy2(src_dssatpro, dst_dssatpro)

    base_name = cul_path.stem
    for suffix in (".CUL", ".ECO", ".SPE"):
        target = runtime_genotype / f"{base_name}{suffix}"
        file_name = f"{base_name}{suffix}"
        src_candidate = next(
            (
                src
                for src in candidate_genotype_sources(project_root, dssat_dir, base_name, suffix, cul_path)
                if src.exists() and src.stat().st_size > 0
            ),
            None,
        )
        if src_candidate is None:
            searched = [str(p) for p in candidate_genotype_sources(project_root, dssat_dir, base_name, suffix, cul_path)]
            raise FileNotFoundError(
                f"Missing genotype support file '{file_name}'. "
                f"Searched={searched}"
            )
        need_copy = True
        if target.exists():
            try:
                src_stat = src_candidate.stat()
                dst_stat = target.stat()
                need_copy = (dst_stat.st_size != src_stat.st_size) or (dst_stat.st_mtime < src_stat.st_mtime)
            except Exception:
                need_copy = True
        if need_copy:
            shutil.copy2(src_candidate, target)

    return runtime_exe, runtime_genotype


DSSATPRO_TEMPLATE = """*** *  DSSAT PROFILE * ***
DDB {root}
DTB {root}
DTE {root}
DTO {root}
DAT {root}
DPT {root}
DIM {root}
DTP {root}
DPF {root}
DFO {root}
DIS {root}
DDW {root}
DWG {root}
DWC {root}
DDS {root}
DTS {root}
DDG {root}
DCG {root}\\TOOLS\\GENCALC GENCALC2.EXE
DGL {root}\\TOOLS\\GLUE GLUE.BAT
DPM {root}
DDE {root}
TOG {root}\\TOOLS\\GBUILD GBUILD.EXE
WED {wed}
SLD {sld}
CRD {crd}
"""


def _to_dssatpro_path(p: Path) -> str:
    import os
    p_abs = os.path.abspath(str(p))
    drive, rest = os.path.splitdrive(p_abs)
    rest = rest.replace("/", "\\")
    if not rest.startswith("\\"):
        rest = "\\" + rest
    return f"{drive} {rest}"


def _from_dssatpro_path(s: str) -> Path | None:
    s = str(s or "").strip()
    if not s:
        return None
    m = re.match(r"^([A-Za-z]:)\s+(\\.+)$", s)
    if not m:
        return None
    import os
    return Path(os.path.normpath(m.group(1) + m.group(2)))


def _resolve_profile_dir(preferred: Path, fallback: Path) -> Path:
    if preferred.exists():
        return preferred
    return fallback


def ensure_local_dssatpro(dssat_dir: Path, runtime_genotype: Path, runtime_root: Path) -> Path:
    runtime_root.mkdir(parents=True, exist_ok=True)
    dssatpro_path = runtime_root / "DSSATPRO.v48"
    project_root = Path(__file__).resolve().parents[1]
    source_profile = project_root / "DSSATPRO.v48"

    runtime_weather = _resolve_profile_dir(runtime_root / "Weather", runtime_root)
    runtime_soil = _resolve_profile_dir(runtime_root / "Soil", dssat_dir / "Soil")
    crd_text = _to_dssatpro_path(runtime_genotype)
    wed_text = _to_dssatpro_path(runtime_weather)
    sld_text = _to_dssatpro_path(runtime_soil)
    if source_profile.exists() and source_profile.stat().st_size > 0:
        shutil.copy2(source_profile, dssatpro_path)
        raw_lines = dssatpro_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        out_lines: list[str] = []
        replaced_crd = False
        replaced_wed = False
        replaced_sld = False
        for line in raw_lines:
            upper_line = line.strip().upper()
            if upper_line.startswith("CRD "):
                out_lines.append(f"CRD {crd_text}")
                replaced_crd = True
            elif upper_line.startswith("WED "):
                out_lines.append(f"WED {wed_text}")
                replaced_wed = True
            elif upper_line.startswith("SLD "):
                out_lines.append(f"SLD {sld_text}")
                replaced_sld = True
            else:
                out_lines.append(line)
        if not replaced_crd:
            out_lines.append(f"CRD {crd_text}")
        if not replaced_wed:
            out_lines.append(f"WED {wed_text}")
        if not replaced_sld:
            out_lines.append(f"SLD {sld_text}")
        dssatpro_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        return dssatpro_path

    root_text = _to_dssatpro_path(runtime_root)
    crd_fallback = _to_dssatpro_path(runtime_genotype)
    content = DSSATPRO_TEMPLATE.format(root=root_text, wed=wed_text, sld=sld_text, crd=crd_fallback)
    dssatpro_path.write_text(content, encoding="utf-8")
    return dssatpro_path


def resolve_adapter_paths(dssat_dir: Path, cfg: dict) -> tuple[list, list, Path | None, Path | None]:
    adapter = cfg.get("adapter", {})
    wth_updates = adapter.get("wth_updates", [])
    sol_updates = adapter.get("sol_updates", [])
    wth_path = resolve_optional_case_path(dssat_dir, str(adapter.get("wth_path", "")).strip())
    sol_path = resolve_optional_case_path(dssat_dir, str(adapter.get("sol_path", "")).strip())
    return wth_updates, sol_updates, wth_path, sol_path


def resolve_sh2o_updates(params: dict[str, float]) -> tuple[bool, dict[int, float]]:
    has_sh2o = any(str(key).lower().startswith("sh2o_") for key in params.keys())
    if not has_sh2o:
        return False, {}
    return True, {15: float(params.get("sh2o_15", 0.205)), 30: float(params.get("sh2o_30", 0.170))}


def resolve_cul_updates(params: dict[str, float], cfg: dict, param_map: dict[str, str]) -> dict[str, float]:
    cul_updates: dict[str, float] = {}
    cfg_cul_params = cfg.get("cul", {}).get("params", None)
    if isinstance(cfg_cul_params, list) and cfg_cul_params:
        wanted: list[str] = []
        for value in cfg_cul_params:
            key = str(value).strip().lower()
            if not key:
                continue
            wanted.append(param_map.get(key, key))
    else:
        wanted = [str(key).strip().lower() for key in params.keys() if not str(key).lower().startswith("sh2o_")]
    for key in wanted:
        if key in params:
            cul_updates[key] = float(params[key])
    return cul_updates


def resolve_input_plan(dssat_dir: Path, cfg: dict, params: dict[str, float], param_map: dict[str, str]) -> CaseInputPlan:
    has_sh2o, sh2o_by_icbl = resolve_sh2o_updates(params)
    cul_updates = resolve_cul_updates(params, cfg, param_map)
    wth_updates, sol_updates, wth_path, sol_path = resolve_adapter_paths(dssat_dir, cfg)
    return CaseInputPlan(
        has_sh2o=has_sh2o,
        sh2o_by_icbl=sh2o_by_icbl,
        cul_updates=cul_updates,
        wth_updates=wth_updates,
        sol_updates=sol_updates,
        wth_path=wth_path,
        sol_path=sol_path,
    )


def resolve_runtime_file_state(live_filex: Path, cul_path: Path, input_plan: CaseInputPlan) -> RuntimeFileState:
    wth_original = None
    sol_original = None
    if input_plan.wth_updates:
        if input_plan.wth_path is None or not input_plan.wth_path.exists():
            raise FileNotFoundError("WTH path not found for wth_updates")
        wth_original = input_plan.wth_path.read_text(encoding="utf-8", errors="ignore")
    if input_plan.sol_updates:
        if input_plan.sol_path is None or not input_plan.sol_path.exists():
            raise FileNotFoundError("SOL path not found for sol_updates")
        sol_original = input_plan.sol_path.read_text(encoding="utf-8", errors="ignore")
    return RuntimeFileState(
        live_filex_path=live_filex,
        live_filex_original=live_filex.read_text(encoding="utf-8", errors="ignore"),
        cul_path=cul_path,
        cul_original=cul_path.read_text(encoding="utf-8", errors="ignore"),
        wth_path=input_plan.wth_path,
        wth_original=wth_original,
        sol_path=input_plan.sol_path,
        sol_original=sol_original,
    )


def resolve_case_runtime(
    dssat_dir: Path,
    cfg: dict,
    live_filex: Path,
    trts: list[int],
    params: dict[str, float],
    param_map: dict[str, str],
    env_obs_a_path: str = "",
    env_extra_summary_vars: str = "",
    env_allow_missing: str = "",
) -> CaseRuntime:
    observation, output = resolve_observation_contracts(
        dssat_dir,
        cfg,
        live_filex,
        trts,
        env_obs_a_path=env_obs_a_path,
        env_extra_summary_vars=env_extra_summary_vars,
        env_allow_missing=env_allow_missing,
    )
    return CaseRuntime(
        observation=observation,
        output=output,
        input_plan=resolve_input_plan(dssat_dir, cfg, params, param_map),
    )
