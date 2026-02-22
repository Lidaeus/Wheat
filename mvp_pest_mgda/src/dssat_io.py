from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
from pathlib import Path


def load_project_config(project_root: Path) -> dict:
    cfg_path = os.environ.get("PROJECT_CONFIG", "").strip()
    if cfg_path:
        path = Path(cfg_path)
    else:
        path = project_root / "config" / "project.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_crop_family(cfg: dict, dssat_dir: Path | None = None) -> str:
    family = str(cfg.get("crop_family", "")).strip().lower()
    if not family:
        family = str(cfg.get("family", "")).strip().lower()
    if not family:
        family = str((cfg.get("params", {}) or {}).get("family", "")).strip().lower()
    if not family and dssat_dir is not None:
        family = str(dssat_dir.name).strip().lower()
    return family


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
    header = None
    last_row = None
    for line in lines:
        if line.startswith("@RUN"):
            header = line
            continue
        if header and re.match(r"^\s*\d+\s+", line):
            last_row = line
    if not header or not last_row:
        raise RuntimeError("Evaluate.OUT did not contain expected table")
    cols = [c.lstrip("@").strip().upper() for c in header.split()]
    vals = last_row.split()
    return {c: v for c, v in zip(cols, vals)}


def read_table_row(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = None
    last_row = None
    for line in lines:
        if line.startswith("@"):
            header = line
            continue
        if header and re.match(r"^\s*\d+\s+", line):
            last_row = line
    if not header or not last_row:
        raise RuntimeError(f"{path.name} did not contain expected table")
    cols = [c.lstrip("@").strip().upper() for c in header.split()]
    vals = last_row.split()
    return {c: v for c, v in zip(cols, vals)}


def pick_eval_value(row: dict[str, str], var_code: str, prefer_suffix: str = "S") -> float | None:
    vc = str(var_code).strip().upper()
    if not vc:
        return None
    suf = str(prefer_suffix).strip().upper()
    candidates: list[str] = []
    if suf and not vc.endswith(suf):
        candidates.append(vc + suf)
    if vc != "S" and not vc.endswith("S"):
        candidates.append(vc + "S")
    candidates.append(vc)
    if not vc.endswith("M"):
        candidates.append(vc + "M")
    if not vc.endswith("A"):
        candidates.append(vc + "A")
    for c in candidates:
        if c in row:
            try:
                return float(row[c])
            except ValueError:
                return None
    return None


def rewrite_cul_values(cul_path: Path, cultivar_code: str, updates: dict[str, float]) -> None:
    raw_lines = cul_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    updates_u = {str(k).strip().upper(): float(v) for k, v in updates.items()}
    if not updates_u:
        return

    header_cols: list[str] | None = None

    def _line_ending(raw: str) -> str:
        if raw.endswith("\r\n"):
            return "\r\n"
        if raw.endswith("\n"):
            return "\n"
        if raw.endswith("\r"):
            return "\r"
        return ""

    def _format_like(existing: str, width: int, value: float) -> str:
        s = existing.strip()
        if not s:
            out = f"{value:>{width}.2f}"
        elif "." in s:
            decimals = len(s.split(".", 1)[1])
            out = f"{value:>{width}.{decimals}f}"
        else:
            out = f"{int(round(value)):>{width}d}"
        if len(out) > width:
            out = out[-width:]
        return out

    out_lines: list[str] = []
    updated = False
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        if stripped.startswith("!"):
            out_lines.append(line)
            continue
        if stripped.startswith("@"):
            header_cols = [c.lstrip("@").strip().upper() for c in stripped.split()]
            out_lines.append(line)
            continue
        if stripped.startswith("*"):
            header_cols = None
            out_lines.append(line)
            continue
        if not line.startswith(cultivar_code):
            out_lines.append(line)
            continue

        if not header_cols:
            raise RuntimeError(f"Missing header before cultivar row {cultivar_code} in {cul_path}")

        ending = _line_ending(line)
        row = line.rstrip("\r\n")
        matches = list(re.finditer(r"\S+", row))
        if len(matches) != len(header_cols):
            if len(matches) < len(header_cols):
                raise RuntimeError(f"Unexpected cultivar row format for {cultivar_code} in {cul_path}: {row}")
            header_cols = header_cols + [f"__EXTRA_{i}__" for i in range(len(matches) - len(header_cols))]

        col_to_span = {col: (m.start(), m.end()) for col, m in zip(header_cols, matches)}
        unknown = [k for k in updates_u.keys() if k not in col_to_span]
        if unknown:
            raise RuntimeError(f"Unknown CUL columns {unknown} in {cul_path}")

        row_chars = list(row)
        for col, value in updates_u.items():
            a, b = col_to_span[col]
            width = b - a
            existing = row[a:b]
            repl = _format_like(existing, width, value)
            row_chars[a:b] = list(repl)

        new_row = "".join(row_chars)
        if len(new_row) != len(row):
            raise RuntimeError(
                f"CUL row length mismatch for {cultivar_code} in {cul_path}: {len(new_row)} != {len(row)}"
            )
        for col, value in updates_u.items():
            a, b = col_to_span[col]
            width = b - a
            existing = row[a:b]
            repl = _format_like(existing, width, value)
            if new_row[a:b].strip() != repl.strip():
                raise RuntimeError(f"CUL round-trip mismatch for {cultivar_code} {col} in {cul_path}")

        out_lines.append(new_row + ending)
        updated = True

    if not updated:
        raise RuntimeError(f"Cultivar code {cultivar_code} not found in {cul_path}")
    cul_path.write_text("".join(out_lines), encoding="utf-8")


def scan_dssat_trials(root: Path) -> list[dict[str, str]]:
    root = root.resolve()
    prefix_to_cul = {
        "WH": "WHCER048.CUL",
        "MZ": "MZCER048.CUL",
        "RI": "RICER048.CUL",
        "CB": "CBGRO048.CUL",
        "CS": "CSCAS048.CUL",
        "PT": "PTSUB048.CUL",
        "SB": "SBGRO048.CUL",
    }
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
        cul_name = prefix_to_cul.get(prefix, "")
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
        root = Path(r"C:\DSSAT48")
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
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("!"):
            continue
        if stripped.startswith("@"):
            header_cols = [c.lstrip("@").strip().upper() for c in stripped.split()]
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


def _bounds_from_values(vals: dict[str, float]) -> dict[str, list[float | str]]:
    bounds: dict[str, list[float | str]] = {}
    for k, v in vals.items():
        if v == 0:
            lb, ub = -0.1, 0.1
        else:
            lb = v * 0.7
            ub = v * 1.3
        if lb > ub:
            lb, ub = ub, lb
        bounds[str(k).strip().lower()] = [float(lb), float(ub), "g_cul"]
    return bounds


def _build_project_config(
    crop_dir: str,
    file_a: Path,
    file_t: Path,
    file_x: Path,
    cul_path: Path | None,
    trts: list[int],
    bounds: dict[str, list[float | str]],
    seed: int,
) -> dict:
    filex_name = file_x.name
    cfg = {
        "paths": {
            "dssat_case_dir": str(file_x.parent.resolve()),
            "wha_path": str(file_a.resolve()),
            "wht_path": str(file_t.resolve()),
            "obs_a_path": str(file_a.resolve()),
            "obs_t_path": str(file_t.resolve()),
            "cul_path": str(cul_path.resolve()) if cul_path else "",
            "dssat_exe": r"C:\DSSAT48\DSCSM048.EXE",
        },
        "scenario": {"filex": filex_name, "base_filex": filex_name, "trts": trts},
        "adapter": {"wth_path": "", "sol_path": "", "wth_updates": [], "sol_updates": []},
        "split": {"mode": "ratio", "valid_ratio": 0.2, "seed": seed, "train_trts": [], "valid_trts": []},
        "params": {"bounds": bounds, "groups": {"g_cul": {"inctyp": "relative", "derinc": 0.05}}},
        "observations": {
            "allow_missing_obs_files": True,
            "groups": {
                "obs_yield": {"patterns": ["hwam_"], "weight": 1.0},
                "obs_laix": {"patterns": ["laix_"], "weight": 1.0},
                "obs_laid": {"patterns": ["laid_"], "weight": 1.0},
                "obs_swad": {"patterns": ["swad_"], "weight": 1.0},
            },
            "weights": {},
        },
        "metrics": {"yield_var": "HWAM", "laix_var": "LAIX", "t_vars": ["LAID", "LWAD", "SWAD"]},
    }
    cfg["crop_family"] = crop_dir
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

        cfg = _build_project_config(crop, file_a, file_t, file_x, cul_path, trts, bounds, int(args.seed))
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
