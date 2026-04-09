from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from crop_registry import (
    resolve_crop_family_name,
    resolve_crop_profile_from_context,
    resolve_cultivar_file_by_trial_prefix,
)

LEGACY_WHEAT_PARAM_ORDER = ("p1v", "p1d", "p5", "g1", "g2", "g3", "phint")
LEGACY_WHEAT_INITIAL_VALUES = {
    "p1v": 9.33,
    "p1d": 3.12,
    "p5": 331.4,
    "g1": 12.87,
    "g2": 62.22,
    "g3": 2.215,
    "phint": 86.0,
}
LEGACY_WHEAT_BOUNDS = {
    "p1v": (5.0, 65.0),
    "p1d": (0.0, 95.0),
    "p5": (300.0, 999.0),
    "g1": (5.0, 45.0),
    "g2": (30.0, 65.0),
    "g3": (0.5, 2.5),
    "phint": (80.0, 167.0),
}

LEGACY_DSSAT_ROOT = Path(r"C:\DSSAT48")


def resolve_requested_crop_family(
    crop: object | None = None,
    *,
    env_var_names: Sequence[str] = ("PROJECT_CROP", "AR_CROP", "DSSAT_CROP"),
) -> str:
    resolved = resolve_crop_family_name(crop)
    if resolved:
        return resolved
    for env_var_name in env_var_names:
        resolved = resolve_crop_family_name(os.environ.get(str(env_var_name).strip(), ""))
        if resolved:
            return resolved
    return ""


def resolve_project_config_candidates(
    project_root: Path,
    *,
    candidate_relatives: tuple[str, ...] = ("config/project.json",),
    crop: object | None = None,
    env_var_names: Sequence[str] = ("PROJECT_CROP", "AR_CROP", "DSSAT_CROP"),
) -> tuple[str, ...]:
    ordered_candidates: list[str] = []

    def append_candidate(value: object) -> None:
        normalized = str(value).strip()
        if normalized and normalized not in ordered_candidates:
            ordered_candidates.append(normalized)

    resolved_crop = resolve_requested_crop_family(crop, env_var_names=env_var_names)
    if resolved_crop:
        append_candidate(f"config/multi/project_{resolved_crop}.json")
        append_candidate(f"config/project_{resolved_crop}.json")
        append_candidate(f"project_{resolved_crop}.json")
    for relative in candidate_relatives:
        append_candidate(relative)
    return tuple(ordered_candidates)


def resolve_project_config_path(
    project_root: Path,
    *,
    env_var: str = "PROJECT_CONFIG",
    candidate_relatives: tuple[str, ...] = ("config/project.json",),
    crop: object | None = None,
    crop_env_var_names: Sequence[str] = ("PROJECT_CROP", "AR_CROP", "DSSAT_CROP"),
) -> Path | None:
    resolved_crop = resolve_requested_crop_family(crop, env_var_names=crop_env_var_names)
    cfg_path = os.environ.get(env_var, "").strip()
    if not cfg_path and env_var == "PROJECT_CONFIG":
        cfg_path = os.environ.get("PEST_PROJECT_CONFIG", "").strip()
    resolved_env_path = Path(cfg_path).resolve() if cfg_path else None
    if resolved_env_path is not None and not resolved_env_path.exists():
        resolved_env_path = None
    generic_relatives = resolve_project_config_candidates(
        project_root,
        candidate_relatives=candidate_relatives,
        crop=None,
        env_var_names=(),
    )
    generic_candidate_paths: set[Path] = set()
    for relative in generic_relatives:
        candidate = Path(relative)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        generic_candidate_paths.add(candidate.resolve())
    if resolved_env_path is not None and (not resolved_crop or resolved_env_path not in generic_candidate_paths):
        return resolved_env_path
    if resolved_crop:
        for relative in (
            f"config/multi/project_{resolved_crop}.json",
            f"config/project_{resolved_crop}.json",
            f"project_{resolved_crop}.json",
        ):
            candidate = (project_root / relative).resolve()
            if candidate.exists():
                return candidate
    if resolved_env_path is not None:
        return resolved_env_path
    for relative in generic_relatives:
        candidate = Path(relative)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.exists():
            return candidate
    return None


def load_project_config(
    project_root: Path,
    *,
    env_var: str = "PROJECT_CONFIG",
    candidate_relatives: tuple[str, ...] = ("config/project.json",),
    crop: object | None = None,
    crop_env_var_names: Sequence[str] = ("PROJECT_CROP", "AR_CROP", "DSSAT_CROP"),
) -> dict:
    path = resolve_project_config_path(
        project_root,
        env_var=env_var,
        candidate_relatives=candidate_relatives,
        crop=crop,
        crop_env_var_names=crop_env_var_names,
    )
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe_paths_in_order(paths: Sequence[Path]) -> list[Path]:
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in seen:
            continue
        ordered.append(resolved)
        seen.add(resolved)
    return ordered


def _candidate_dssat_roots(
    project_root: Path,
    *,
    cfg: dict | None = None,
    env_dssat_root: str = "",
) -> list[Path]:
    cfg_paths = (cfg or {}).get("paths", {}) or {}
    configured_root = str(cfg_paths.get("dssat_root", "")).strip()
    configured_exe = str(cfg_paths.get("dssat_exe", "")).strip()
    configured_case_dir = str(cfg_paths.get("dssat_case_dir", "")).strip()
    configured_cul = str(cfg_paths.get("cul_path", "")).strip() or str(cfg_paths.get("wh_cul_path", "")).strip()
    env_root = str(env_dssat_root).strip() or str(os.environ.get("DSSAT_ROOT", "")).strip()

    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root))
    if configured_root:
        candidates.append(Path(configured_root))
    if configured_exe:
        candidates.append(Path(configured_exe).parent)
    if configured_case_dir:
        candidates.append(Path(configured_case_dir).parent)
    if configured_cul:
        candidates.append(Path(configured_cul).parent.parent)
    candidates.extend(
        [
            (project_root.parent / "local_dssat"),
            (project_root / "data" / "dssat"),
            LEGACY_DSSAT_ROOT,
        ]
    )
    return _dedupe_paths_in_order(candidates)


def resolve_dssat_root(
    project_root: Path,
    *,
    cfg: dict | None = None,
    env_dssat_root: str = "",
) -> Path:
    ordered = _candidate_dssat_roots(project_root, cfg=cfg, env_dssat_root=env_dssat_root)
    for candidate in ordered:
        if candidate.exists():
            return candidate
    return ordered[0] if ordered else LEGACY_DSSAT_ROOT


def resolve_dssat_genotype_dir(
    project_root: Path,
    *,
    cfg: dict | None = None,
    env_dssat_root: str = "",
) -> Path:
    root_candidates = _candidate_dssat_roots(project_root, cfg=cfg, env_dssat_root=env_dssat_root)
    for root in root_candidates:
        for name in ("Genotype", "GENOTYPE"):
            candidate = root / name
            if candidate.exists():
                return candidate
    root = resolve_dssat_root(project_root, cfg=cfg, env_dssat_root=env_dssat_root)
    for name in ("Genotype", "GENOTYPE"):
        candidate = root / name
        if candidate.exists():
            return candidate
    return root / "Genotype"


def resolve_dssat_case_dir(
    project_root: Path,
    *,
    cfg: dict | None = None,
    env_case_dir: str = "",
    env_dssat_root: str = "",
) -> Path:
    raw_case_dir = str(env_case_dir).strip() or str(((cfg or {}).get("paths", {}) or {}).get("dssat_case_dir", "")).strip()
    if raw_case_dir:
        candidate = Path(raw_case_dir)
        if candidate.is_absolute():
            return candidate.resolve()
        for root in _candidate_dssat_roots(project_root, cfg=cfg, env_dssat_root=env_dssat_root):
            resolved = (root / candidate).resolve()
            if resolved.exists():
                return resolved
        return (resolve_dssat_root(project_root, cfg=cfg, env_dssat_root=env_dssat_root) / candidate).resolve()
    return (project_root / "data" / "dssat").resolve()


def resolve_dssat_exe_path(
    project_root: Path,
    *,
    cfg: dict | None = None,
    env_dssat_exe: str = "",
    env_dssat_root: str = "",
) -> Path:
    cfg_paths = (cfg or {}).get("paths", {}) or {}
    configured_exe = str(cfg_paths.get("dssat_exe", "")).strip()
    env_exe = str(env_dssat_exe).strip() or str(os.environ.get("DSSAT_EXE", "")).strip()
    candidates: list[Path] = []
    if env_exe:
        candidates.append(Path(env_exe))
    if configured_exe:
        candidates.append(Path(configured_exe))
    resolved_root = resolve_dssat_root(project_root, cfg=cfg, env_dssat_root=env_dssat_root)
    candidates.extend(
        [
            resolved_root / "DSCSM048.EXE",
            (project_root.parent / "local_dssat" / "DSCSM048.EXE"),
            (LEGACY_DSSAT_ROOT / "DSCSM048.EXE"),
        ]
    )
    ordered = _dedupe_paths_in_order(candidates)
    for candidate in ordered:
        if candidate.exists():
            return candidate
    return ordered[0] if ordered else LEGACY_DSSAT_ROOT / "DSCSM048.EXE"


def _normalize_parameter_name(name: object) -> str:
    return str(name).strip().lower()


def _append_unique_names(target: list[str], raw_names: object) -> None:
    values: Iterable[object]
    if isinstance(raw_names, dict):
        values = raw_names.keys()
    elif isinstance(raw_names, (list, tuple)):
        values = raw_names
    else:
        return
    seen = set(target)
    for raw_name in values:
        name = _normalize_parameter_name(raw_name)
        if not name or name in seen:
            continue
        target.append(name)
        seen.add(name)


def resolve_baseline_profile_name(cfg: dict) -> str:
    baselines = cfg.get("baselines", {}) or {}
    return str(baselines.get("negative_optimization_reference", "b0_official_frozen")).strip() or "b0_official_frozen"


def resolve_baseline_parameter_values(cfg: dict, profile_name: str = "") -> dict[str, float]:
    baselines = cfg.get("baselines", {}) or {}
    profiles = baselines.get("profiles", {}) or {}
    resolved_profile_name = str(profile_name).strip() or resolve_baseline_profile_name(cfg)
    profile = profiles.get(resolved_profile_name, {}) if isinstance(profiles, dict) else {}
    param_source = (profile.get("param_source", {}) or {}) if isinstance(profile, dict) else {}
    if str(param_source.get("type", "")).strip().lower() != "inline_values":
        return {}
    values = param_source.get("values", {}) or {}
    if not isinstance(values, dict):
        return {}
    out: dict[str, float] = {}
    for raw_name, raw_value in values.items():
        name = _normalize_parameter_name(raw_name)
        if not name:
            continue
        try:
            out[name] = float(raw_value)
        except (TypeError, ValueError):
            continue
    return out


def resolve_parameter_names(cfg: dict, default_names: tuple[str, ...] = LEGACY_WHEAT_PARAM_ORDER) -> list[str]:
    params_cfg = cfg.get("params", {}) or {}
    ordered: list[str] = []
    _append_unique_names(ordered, params_cfg.get("order", params_cfg.get("names", [])))
    _append_unique_names(ordered, params_cfg.get("bounds", {}))
    _append_unique_names(ordered, params_cfg.get("initial_values", {}))
    _append_unique_names(ordered, resolve_baseline_parameter_values(cfg))
    if not ordered:
        registry_defaults = resolve_crop_profile_from_context(cfg).parameter_order
        _append_unique_names(ordered, registry_defaults or default_names)
    return ordered


def resolve_initial_parameter_values(cfg: dict, parameter_names: list[str]) -> list[float]:
    params_cfg = cfg.get("params", {}) or {}
    initial_values_cfg = params_cfg.get("initial_values", {}) or {}
    initial_values: dict[str, float] = {}
    if isinstance(initial_values_cfg, dict):
        for raw_name, raw_value in initial_values_cfg.items():
            name = _normalize_parameter_name(raw_name)
            if not name:
                continue
            try:
                initial_values[name] = float(raw_value)
            except (TypeError, ValueError):
                continue
    baseline_values = resolve_baseline_parameter_values(cfg)
    bounds_cfg = params_cfg.get("bounds", {}) or {}
    resolved: list[float] = []
    for raw_name in parameter_names:
        name = _normalize_parameter_name(raw_name)
        if name in initial_values:
            resolved.append(initial_values[name])
            continue
        if name in baseline_values:
            resolved.append(float(baseline_values[name]))
            continue
        raw_bound = bounds_cfg.get(name) if isinstance(bounds_cfg, dict) else None
        if isinstance(raw_bound, list) and len(raw_bound) >= 2:
            try:
                resolved.append((float(raw_bound[0]) + float(raw_bound[1])) / 2.0)
                continue
            except (TypeError, ValueError):
                pass
        resolved.append(float(LEGACY_WHEAT_INITIAL_VALUES.get(name, 0.0)))
    return resolved


def resolve_parameter_bounds_pairs(cfg: dict, parameter_names: list[str]) -> list[tuple[float, float]]:
    params_cfg = cfg.get("params", {}) or {}
    custom_bounds = params_cfg.get("bounds", {})
    fallback_mode = str(
        params_cfg.get("fallback_mode", params_cfg.get("bounds_fallback_mode", "relative_30"))
    ).strip() or "relative_30"
    default_group = str(params_cfg.get("default_group", "g_cul")).strip() or "g_cul"
    initial_values = {
        name: value
        for name, value in zip(parameter_names, resolve_initial_parameter_values(cfg, parameter_names))
    }
    resolved_bounds_map, _ = resolve_parameter_bounds(
        initial_values=initial_values,
        custom_bounds=custom_bounds if isinstance(custom_bounds, dict) else {},
        fallback_mode=fallback_mode,
        default_group=default_group,
        crop_family=resolve_crop_family(cfg),
    )
    bounds: list[tuple[float, float]] = []
    for raw_name in parameter_names:
        name = _normalize_parameter_name(raw_name)
        raw_bound = resolved_bounds_map.get(name)
        if isinstance(raw_bound, list) and len(raw_bound) >= 2:
            try:
                bounds.append((float(raw_bound[0]), float(raw_bound[1])))
                continue
            except (TypeError, ValueError):
                pass
        if name in LEGACY_WHEAT_BOUNDS:
            bounds.append(LEGACY_WHEAT_BOUNDS[name])
            continue
        initial = float(initial_values.get(name, 0.0))
        bounds.append(_fallback_bounds_for_value(initial, fallback_mode))
    return bounds


def load_bounds_source(source_path: Path, crop_family: str = "") -> dict[str, object]:
    if not source_path.exists():
        return {}
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    family_key = str(crop_family).strip().lower()
    candidates: list[object] = []
    if family_key:
        candidates.extend(
            [
                raw.get(family_key),
                (raw.get("families", {}) or {}).get(family_key) if isinstance(raw.get("families"), dict) else None,
                (raw.get("crops", {}) or {}).get(family_key) if isinstance(raw.get("crops"), dict) else None,
            ]
        )
    candidates.extend([raw.get("bounds"), raw])
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if "bounds" in candidate and isinstance(candidate.get("bounds"), dict):
            return {
                str(name).strip().lower(): value
                for name, value in candidate["bounds"].items()
                if str(name).strip()
            }
        if candidate and all(str(name).strip() for name in candidate.keys()):
            return {
                str(name).strip().lower(): value
                for name, value in candidate.items()
                if str(name).strip()
            }
    return {}


def resolve_crop_family(cfg: dict, dssat_dir: Path | None = None) -> str:
    return resolve_crop_profile_from_context(cfg, dssat_dir).family


def resolve_param_mapping(cfg: dict, dssat_dir: Path | None = None) -> tuple[dict[str, str], dict[str, str]]:
    params_cfg = cfg.get("params", {}) or {}
    family_map = params_cfg.get("family_map", {}) or {}
    aliases = params_cfg.get("aliases", params_cfg.get("alias", {})) or {}
    family = resolve_crop_family(cfg, dssat_dir)
    mapping: dict[str, str] = {}
    if isinstance(family_map, dict) and family and family in family_map and isinstance(family_map[family], dict):
        for k, v in family_map[family].items():
            if str(k).strip() and str(v).strip():
                mapping[str(k).strip().lower()] = str(v).strip().lower()
    if isinstance(aliases, dict):
        for k, v in aliases.items():
            if str(k).strip() and str(v).strip():
                mapping[str(k).strip().lower()] = str(v).strip().lower()
    inverse = {v: k for k, v in mapping.items()}
    return mapping, inverse


def guess_related_path(filex_path: Path, new_suffix: str) -> Path:
    suf = str(new_suffix).strip()
    if not suf.startswith("."):
        suf = "." + suf
    return filex_path.with_suffix(suf)


def extract_trts_from_filex(filex_path: Path) -> list[int]:
    lines = filex_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    in_trt = False
    trts: list[int] = []
    for line in lines:
        if line.startswith("*TREATMENTS"):
            in_trt = True
            continue
        if in_trt:
            if line.startswith("*"):
                break
            if not line.strip() or line.lstrip().startswith("!") or line.startswith("@"):
                continue
            parts = line.split()
            if not parts:
                continue
            try:
                trts.append(int(parts[0]))
            except ValueError:
                continue
    if not trts:
        raise RuntimeError(f"No TRNO found in *TREATMENTS section of {filex_path}")
    return trts


def extract_cultivar_code(filex_path: Path) -> str:
    lines = filex_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    in_section = False
    for line in lines:
        if line.startswith("*CULTIVARS"):
            in_section = True
            continue
        if in_section:
            if not line.strip() or line.startswith("@"):
                continue
            if line.startswith("*"):
                break
            parts = line.split()
            if len(parts) >= 3:
                return parts[2].strip()
    raise RuntimeError(f"Could not parse cultivar code from {filex_path}")


def read_eval_row(eval_path: Path) -> dict[str, str]:
    lines = eval_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header, last_row = _read_last_table_record(lines, header_prefix="@RUN")
    if not header or not last_row:
        raise RuntimeError("Evaluate.OUT did not contain expected table")
    return _parse_table_row_by_header(header, last_row)


def read_table_row(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header, last_row = _read_last_table_record(lines, header_prefix="@")
    if not header or not last_row:
        raise RuntimeError(f"{path.name} did not contain expected table")
    return _parse_table_row_by_header(header, last_row)


def _read_last_table_record(lines: list[str], header_prefix: str) -> tuple[str | None, str | None]:
    header = None
    current: list[str] = []
    last_row = None
    for line in lines:
        if line.startswith(header_prefix):
            if current:
                last_row = "".join(current)
                current = []
            header = line
            continue
        if not header:
            continue
        if re.match(r"^\s*\d+\s+", line):
            if current:
                last_row = "".join(current)
            current = [line]
            continue
        if current and line and not line.startswith("@") and not line.startswith("*") and not line.lstrip().startswith("!"):
            current.append(line)
            continue
        if current:
            last_row = "".join(current)
            current = []
    if current:
        last_row = "".join(current)
    return header, last_row


def _parse_table_row_by_header(header: str, row: str) -> dict[str, str]:
    matches = list(re.finditer(r"\S+", header))
    cols = [m.group(0).lstrip("@").strip().upper() for m in matches]
    starts = [m.start() for m in matches]
    out: dict[str, str] = {}
    for idx, col in enumerate(cols):
        start = starts[idx]
        end = starts[idx + 1] if idx + 1 < len(starts) else None
        if start >= len(row):
            out[col] = ""
            continue
        out[col] = row[start:end].strip() if end is not None else row[start:].strip()
    return out


def pick_eval_value(row: dict[str, str], var_code: str, prefer_suffix: str = "S") -> float | None:
    vc = str(var_code).strip().upper()
    if not vc:
        return None
    suf = str(prefer_suffix).strip().upper()
    
    # Priority list for yield fallbacks (Dry weight > Fresh weight)
    yield_fallbacks = ["HWAM", "CWAM", "PRCM", "HWUM", "HWAH"]
    is_yield = vc in {"HWAM", "YIELD"}
    
    # Base candidates list
    base_vcs = yield_fallbacks if is_yield else [vc]
    
    candidates: list[str] = []
    for base_vc in base_vcs:
        if suf and not base_vc.endswith(suf):
            candidates.append(base_vc + suf)
        if base_vc != "S" and not base_vc.endswith("S"):
            candidates.append(base_vc + "S")
        candidates.append(base_vc)
        if not base_vc.endswith("M"):
            candidates.append(base_vc + "M")
        if not base_vc.endswith("A"):
            candidates.append(base_vc + "A")
            
    for c in candidates:
        if c in row:
            try:
                # Discard invalid values like -99.0
                val = float(row[c])
                if val <= -90.0:
                    continue
                return val
            except ValueError:
                continue
    return None


def rewrite_cul_values(cul_path: Path, cultivar_code: str, updates: dict[str, float]) -> None:
    """
    Updates specific parameter columns in a DSSAT .CUL file for a given cultivar.
    This implementation dynamically identifies column positions using the '@' header line,
    making it compatible with any crop cultivar file.
    """
    raw_lines = cul_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    updates_u = {str(k).strip().upper(): float(v) for k, v in updates.items()}
    if not updates_u:
        return

    header_cols: list[str] | None = None
    fixed_numeric_order = ["P1V", "P1D", "P5", "G1", "G2", "G3", "PHINT"]
    fixed_numeric_formats = {
        "P1V": (6, 3),
        "P1D": (6, 2),
        "P5": (6, 1),
        "G1": (6, 2),
        "G2": (6, 2),
        "G3": (6, 3),
        "PHINT": (6, 2),
    }

    def _line_ending(raw: str) -> str:
        if raw.endswith("\r\n"):
            return "\r\n"
        if raw.endswith("\n"):
            return "\n"
        return ""

    def _format_fixed_numeric(col_name: str, value: float) -> str:
        width, decimals = fixed_numeric_formats[col_name]
        out = f"{float(value):>{width}.{decimals}f}"
        if len(out) > width:
            raise ValueError(f"Value {value} for {col_name} exceeds DSSAT width {width}")
        return out

    def _format_like_existing(existing_text: str, width: int, value: float) -> str:
        s = existing_text.strip()
        if "." in s:
            decimals = len(s.split(".", 1)[1])
            out = f"{float(value):>{width}.{decimals}f}"
        else:
            out = f"{int(round(float(value))):>{width}d}"
        if len(out) > width:
            raise ValueError(f"Value {value} exceeds DSSAT width {width} for column '{s}'")
        return out

    out_lines: list[str] = []
    updated = False
    
    # Pass 1: Find the header line and cultivar row to build the map
    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped.startswith("@"):
            header_cols = [c.lstrip("@").strip().upper() for c in line.split()]
            out_lines.append(line)
            continue
        
        # We only care about rows starting with our cultivar code
        if header_cols and line.startswith(cultivar_code):
            row_text = line.rstrip("\r\n")
            ending = _line_ending(line)
            
            row_matches = list(re.finditer(r"\S+", row_text))
            if len(row_matches) < len(header_cols):
                out_lines.append(line)
                continue

            row_tokens = [match.group(0) for match in row_matches[: len(header_cols)]]
            row_by_col = {str(col).strip().upper(): row_tokens[idx] for idx, col in enumerate(header_cols)}

            fixed_cols_applied: set[str] = set()
            can_use_fixed_numeric_template = all(col in row_by_col for col in fixed_numeric_order)
            if can_use_fixed_numeric_template and any(col in updates_u for col in fixed_numeric_order):
                first_numeric_col = fixed_numeric_order[0]
                first_numeric_idx = header_cols.index(first_numeric_col)
                numeric_start = row_matches[first_numeric_idx].start()
                prefix = row_text[:numeric_start]
                trailing = row_text[row_matches[-1].end():]
                numeric_values = {
                    col: float(row_by_col[col]) if col in row_by_col else 0.0
                    for col in fixed_numeric_order
                }
                for col_name, new_val in updates_u.items():
                    if col_name in numeric_values:
                        numeric_values[col_name] = float(new_val)
                        fixed_cols_applied.add(col_name)
                numeric_block = "".join(_format_fixed_numeric(col, numeric_values[col]) for col in fixed_numeric_order)
                row_text = prefix + numeric_block + trailing
                row_matches = list(re.finditer(r"\S+", row_text))

            col_to_span: dict[str, tuple[int, int]] = {}
            for col, match in zip(header_cols, row_matches):
                start = int(match.start())
                end = int(match.end())
                col_to_span[str(col).strip().upper()] = (start, end)
            
            row_chars = list(row_text)
            for col_name, new_val in updates_u.items():
                if col_name in fixed_cols_applied:
                    continue
                if col_name in col_to_span:
                    a, b = col_to_span[col_name]
                    width = b - a
                    existing = "".join(row_chars[a:b])
                    formatted = _format_like_existing(existing, width, new_val)
                    row_chars[a:b] = list(formatted)
            
            out_lines.append("".join(row_chars) + ending)
            updated = True
        else:
            out_lines.append(line)

    if not updated:
        # If not found, it might be in a different section or missing
        # We don't raise error here to allow quiet skipping of non-matching files
        return 

    cul_path.write_text("".join(out_lines), encoding="utf-8")


def scan_dssat_trials(root: Path) -> list[dict[str, str]]:
    root = root.resolve()
    geno_root = root / "Genotype"
    groups: dict[tuple[str, str], dict[str, Path]] = {}
    for path in root.rglob("*.*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) != 2:
            continue
        suf = path.suffix
        if len(suf) != 4:
            continue
        suf_up = suf.upper()
        if suf_up[-1] not in {"A", "T", "X"}:
            continue
        prefix = suf_up[1:3]
        if not prefix.isalpha():
            continue
        key = (rel.parts[0], path.stem)
        groups.setdefault(key, {})[suf_up[-1]] = path
    rows: list[dict[str, str]] = []
    for (crop_dir, stem), items in groups.items():
        if not all(k in items for k in ("A", "T", "X")):
            continue
        prefix = items["X"].suffix.upper()[1:3]
        cul_name = resolve_cultivar_file_by_trial_prefix(prefix)
        cul_path = str((geno_root / cul_name)) if cul_name else ""
        if cul_path and not Path(cul_path).exists():
            cul_path = ""
        rows.append(
            {
                "crop_dir": crop_dir,
                "fileA": str(items["A"]),
                "fileT": str(items["T"]),
                "fileX": str(items["X"]),
                "cul": cul_path,
            }
        )
    rows.sort(key=lambda r: (r["crop_dir"], r["fileX"]))
    return rows


def _write_trial_csv(rows: list[dict[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["crop_dir", "fileA", "fileT", "fileX", "cul"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _cli_scan_trials(argv: list[str]) -> int:
    if not argv:
        project_root = Path(__file__).resolve().parents[1]
        root = resolve_dssat_root(project_root)
        out_path = Path.cwd() / "dssat_trials.csv"
    else:
        root = Path(argv[0])
        out_path = Path(argv[1]) if len(argv) > 1 else Path.cwd() / "dssat_trials.csv"
    rows = scan_dssat_trials(root)
    _write_trial_csv(rows, out_path)
    return 0


def _read_trial_csv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: str(v).strip() for k, v in row.items()})
    return rows


def _sample_trts(trts: list[int], max_trts: int, seed_key: str) -> list[int]:
    if max_trts <= 0 or len(trts) <= max_trts:
        return list(trts)
    seed = f"{seed_key}"
    rng = random.Random(seed)
    pool = list(trts)
    rng.shuffle(pool)
    return sorted(pool[:max_trts])


def _parse_cul_header_and_row(cul_path: Path, cultivar_code: str) -> tuple[list[str], dict[str, float]]:
    lines = cul_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header_cols: list[str] | None = None
    def _normalize_cul_col(name: str) -> str:
        return str(name).lstrip("@").replace("\ufeff", "").strip().upper()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("!"):
            continue
        if stripped.startswith("@"):
            header_cols = [_normalize_cul_col(c) for c in stripped.split()]
            continue
        if stripped.startswith("*"):
            header_cols = None
            continue
        if not header_cols:
            continue
        if not line.startswith(cultivar_code):
            continue
        row = line.rstrip("\r\n")
        matches = list(re.finditer(r"\S+", row))
        if len(matches) < len(header_cols):
            continue
        cols = list(header_cols)
        if len(matches) > len(cols):
            cols = cols + [f"__EXTRA_{i}__" for i in range(len(matches) - len(cols))]
        out_vals: dict[str, float] = {}
        for col, m in zip(cols, matches):
            raw = row[m.start() : m.end()].strip()
            try:
                out_vals[col] = float(raw)
            except ValueError:
                continue
        return cols, out_vals
    return [], {}


def _find_cul_path(cul_hint: str, dssat_dir: Path, cultivar_code: str) -> Path | None:
    if cul_hint:
        cand = Path(cul_hint)
        if cand.exists():
            return cand
    geno_dir = dssat_dir / "Genotype"
    if not geno_dir.exists():
        geno_dir = dssat_dir / "GENOTYPE"
    if not geno_dir.exists():
        return None
    for cul in sorted(geno_dir.glob("*.CUL")):
        lines = cul.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines:
            if line.startswith(cultivar_code):
                return cul
    culs = sorted(geno_dir.glob("*.CUL"))
    return culs[0] if culs else None


def _select_cul_params(cols: list[str], values: dict[str, float], max_params: int) -> dict[str, float]:
    preferred = [
        "P1",
        "P2",
        "P2O",
        "P2R",
        "P5",
        "P1V",
        "P1D",
        "PHINT",
        "G1",
        "G2",
        "G3",
        "G4",
        "CSDL",
        "PPSEN",
        "EM-FL",
        "FL-SH",
        "FL-SD",
        "SD-PM",
        "LFMAX",
        "SLAVR",
        "SIZLF",
        "XFRT",
        "SFDUR",
        "SDPDV",
        "SWSP",
        "SLA",
        "SST",
        "SDPRO",
        "LFN",
    ]
    picks: list[str] = []
    for name in preferred:
        if name in values:
            picks.append(name)
        if len(picks) >= max_params:
            break
    if not picks:
        for col in cols:
            col_u = str(col).strip().upper()
            if col_u in {"VAR#", "VAR", "ECO#", "ECO", "NAME"}:
                continue
            if col_u.startswith("__EXTRA_"):
                continue
            if col_u not in values:
                continue
            picks.append(col_u)
            if len(picks) >= max_params:
                break
    return {p: float(values[p]) for p in picks if p in values}


def _normalize_bound_pair(lower: float, upper: float) -> tuple[float, float]:
    lb = float(lower)
    ub = float(upper)
    if lb > ub:
        lb, ub = ub, lb
    return lb, ub


def _coerce_bound_entry(
    raw_entry: object,
    default_group: str,
) -> tuple[float, float, str] | None:
    if isinstance(raw_entry, dict):
        lower = raw_entry.get("lower", raw_entry.get("lb"))
        upper = raw_entry.get("upper", raw_entry.get("ub"))
        group = str(raw_entry.get("group", default_group)).strip() or default_group
        if lower is None or upper is None:
            return None
        return (*_normalize_bound_pair(float(lower), float(upper)), group)
    if isinstance(raw_entry, (list, tuple)) and len(raw_entry) >= 2:
        group = default_group
        if len(raw_entry) >= 3 and str(raw_entry[2]).strip():
            group = str(raw_entry[2]).strip()
        return (*_normalize_bound_pair(float(raw_entry[0]), float(raw_entry[1])), group)
    return None


def _fallback_bounds_for_value(value: float, fallback_mode: str) -> tuple[float, float]:
    if float(value) == 0.0:
        return -0.1, 0.1
    mode_name = str(fallback_mode).strip().lower()
    ratio = 0.15 if mode_name in {"15", "relative_15", "fallback_15", "tight"} else 0.30
    lower = float(value) * (1.0 - ratio)
    upper = float(value) * (1.0 + ratio)
    return _normalize_bound_pair(lower, upper)


def resolve_parameter_bounds(
    initial_values: dict[str, float],
    custom_bounds: dict[str, object] | None = None,
    official_bounds: dict[str, object] | None = None,
    fallback_mode: str = "relative_30",
    default_group: str = "g_cul",
    crop_family: str = "",
    official_source_path: str = "",
) -> tuple[dict[str, list[float | str]], list[dict[str, str | float]]]:
    custom_map = custom_bounds or {}
    official_map = official_bounds or {}
    names = {
        str(name).strip().lower()
        for name in list(initial_values.keys()) + list(custom_map.keys()) + list(official_map.keys())
        if str(name).strip()
    }
    bounds: dict[str, list[float | str]] = {}
    report_rows: list[dict[str, str | float]] = []
    for name in sorted(names):
        initial = float(initial_values.get(name, 0.0))
        custom_entry = _coerce_bound_entry(custom_map.get(name), default_group) if name in custom_map else None
        official_entry = _coerce_bound_entry(official_map.get(name), default_group) if name in official_map else None
        if custom_entry is not None:
            lower, upper, group = custom_entry
            source = "custom"
            priority_rank = 1
            row_official_source_path = ""
        elif official_entry is not None:
            lower, upper, group = official_entry
            source = "official"
            priority_rank = 2
            row_official_source_path = official_source_path
        else:
            lower, upper = _fallback_bounds_for_value(initial, fallback_mode)
            group = default_group
            source = "fallback_15" if "15" in str(fallback_mode) else "fallback_30"
            priority_rank = 3
            row_official_source_path = ""
        bounds[name] = [float(lower), float(upper), group]
        report_rows.append(
            {
                "parameter": name,
                "crop_family": str(crop_family).strip().lower(),
                "initial": initial,
                "lower": float(lower),
                "upper": float(upper),
                "group": group,
                "source": source,
                "priority_rank": priority_rank,
                "official_source_path": row_official_source_path,
                "span": float(upper - lower),
            }
        )
    return bounds, report_rows


def write_parameter_bounds_report(
    report_path: Path,
    rows: list[dict[str, str | float]],
    parameter_order: Sequence[str] = (),
) -> Path:
    if not rows:
        return report_path
    order_index = {
        str(name).strip().lower(): idx
        for idx, name in enumerate(parameter_order)
        if str(name).strip()
    }
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            order_index.get(str(row.get("parameter", "")).strip().lower(), len(order_index) + 1),
            str(row.get("source", "")),
            int(row.get("priority_rank", 99)),
            str(row.get("parameter", "")),
        ),
    )
    with report_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "parameter",
                "crop_family",
                "initial",
                "lower",
                "upper",
                "group",
                "source",
                "priority_rank",
                "official_source_path",
                "span",
            ],
        )
        writer.writeheader()
        writer.writerows(sorted_rows)
    return report_path


def _bounds_from_values(vals: dict[str, float]) -> dict[str, list[float | str]]:
    bounds, _ = resolve_parameter_bounds(vals)
    return bounds


def _build_project_config(
    crop_dir: str,
    file_a: Path,
    file_t: Path,
    file_x: Path,
    cul_path: Path | None,
    trts: list[int],
    initial_values: dict[str, float],
    bounds: dict[str, list[float | str]],
    seed: int,
) -> dict:
    filex_name = file_x.name
    crop_profile = resolve_crop_profile_from_context({"crop_family": crop_dir})
    cfg: dict[str, object] = {
        "paths": {
            "dssat_case_dir": str(file_x.parent.resolve()),
            "wha_path": str(file_a.resolve()),
            "wht_path": str(file_t.resolve()),
            "obs_a_path": str(file_a.resolve()),
            "obs_t_path": str(file_t.resolve()),
            "cul_path": str(cul_path.resolve()) if cul_path else "",
            "dssat_exe": "",
        },
        "scenario": {"filex": filex_name, "base_filex": filex_name, "trts": trts},
        "adapter": {"wth_path": "", "sol_path": "", "wth_updates": [], "sol_updates": []},
        "split": {"mode": "ratio", "valid_ratio": 0.2, "seed": seed, "train_trts": [], "valid_trts": []},
        "params": {"bounds": bounds, "groups": {"g_cul": {"inctyp": "relative", "derinc": 0.05}}},
        "observations": {
            "allow_missing_obs_files": True,
            "groups": crop_profile.observation_groups_config(),
            "weights": {},
        },
        "metrics": crop_profile.metrics_config(),
    }
    cfg["crop_family"] = crop_profile.family or str(crop_dir).strip().lower()
    raw_params_cfg = cfg.get("params", {})
    params_cfg: dict[str, object] = dict(raw_params_cfg) if isinstance(raw_params_cfg, dict) else {}
    params_cfg["order"] = list(bounds.keys())
    params_cfg["initial_values"] = {
        str(name).strip().lower(): float(value)
        for name, value in initial_values.items()
        if str(name).strip()
    }
    cfg["params"] = params_cfg
    return cfg


def _cli_gen_projects(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trials_csv", type=str)
    parser.add_argument("output_dir", type=str)
    parser.add_argument("--max-trts", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260210)
    parser.add_argument("--max-params", type=int, default=6)
    parser.add_argument(
        "--crops",
        type=str,
        default="Wheat,Maize,Rice,Cabbage,Cassava,Potato,Soybean",
    )
    args = parser.parse_args(argv)

    trials = _read_trial_csv(Path(args.trials_csv))
    by_crop: dict[str, list[dict[str, str]]] = {}
    for row in trials:
        crop = str(row.get("crop_dir", "")).strip()
        if not crop:
            continue
        by_crop.setdefault(crop, []).append(row)
    crops = [c.strip() for c in str(args.crops).split(",") if c.strip()]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    for crop in crops:
        candidates = by_crop.get(crop, [])
        if not candidates:
            continue
        row = candidates[0]
        file_a = Path(row["fileA"])
        file_t = Path(row["fileT"])
        file_x = Path(row["fileX"])
        if not (file_a.exists() and file_t.exists() and file_x.exists()):
            continue
        cultivar_code = extract_cultivar_code(file_x)
        cul_path = _find_cul_path(row.get("cul", ""), file_x.parent, cultivar_code)
        cols: list[str] = []
        vals: dict[str, float] = {}
        if cul_path and cul_path.exists():
            cols, vals = _parse_cul_header_and_row(cul_path, cultivar_code)
        picked = _select_cul_params(cols, vals, int(args.max_params))
        bounds = _bounds_from_values(picked)

        all_trts = extract_trts_from_filex(file_x)
        trts = _sample_trts(all_trts, int(args.max_trts), f"{args.seed}:{crop}")

        cfg = _build_project_config(crop, file_a, file_t, file_x, cul_path, trts, picked, bounds, int(args.seed))
        out_path = out_dir / f"project_{crop.lower()}.json"
        out_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        created += 1
    return 0 if created > 0 else 1


def _cli_main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0].lower().endswith(".csv"):
        return _cli_gen_projects(argv)
    if argv and argv[0] in {"scan", "trials"}:
        return _cli_scan_trials(argv[1:])
    if argv and argv[0] in {"gen", "projects"}:
        return _cli_gen_projects(argv[1:])
    return _cli_scan_trials(argv)


if __name__ == "__main__":
    sys.exit(_cli_main(sys.argv[1:]))
