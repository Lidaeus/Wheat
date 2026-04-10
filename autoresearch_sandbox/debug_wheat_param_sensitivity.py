from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

def _load_eval_module(sandbox_dir: Path) -> object:
    eval_path = sandbox_dir / "eval.py"
    spec = importlib.util.spec_from_file_location("ar_eval", str(eval_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load eval module from {eval_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_cul_row_values(cul_path: Path, cultivar_code: str) -> dict[str, float]:
    header_cols: list[str] | None = None
    fixed_numeric_order = ["P1V", "P1D", "P5", "G1", "G2", "G3", "PHINT"]
    for raw in cul_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("@"):
            header_cols = [c.lstrip("@").strip().upper() for c in stripped.split()]
            continue
        if stripped.startswith("*") or stripped.startswith("!"):
            continue
        if not header_cols:
            continue
        if not line.startswith(cultivar_code):
            continue
        row_text = line
        block_len = 6 * len(fixed_numeric_order)
        numeric_start: int | None = None
        for s in range(0, max(0, len(row_text) - block_len) + 1):
            ok = True
            for k in range(len(fixed_numeric_order)):
                seg = row_text[s + (6 * k) : s + (6 * (k + 1))]
                t = seg.strip()
                if not t or not any(ch.isdigit() for ch in t):
                    ok = False
                    break
                try:
                    float(t)
                except ValueError:
                    ok = False
                    break
            if ok:
                numeric_start = s
                break

        out: dict[str, float] = {}
        if numeric_start is not None:
            for idx, name in enumerate(fixed_numeric_order):
                seg = row_text[numeric_start + (6 * idx) : numeric_start + (6 * (idx + 1))]
                out[name] = float(seg.strip())

        tokens = line.split()
        for idx, col in enumerate(header_cols):
            if idx >= len(tokens):
                break
            try:
                out.setdefault(col, float(tokens[idx]))
            except ValueError:
                continue
        return out
    return {}


def _write_params_dat(path: Path, params: dict[str, float]) -> None:
    lines = [f"{str(k).strip()} {float(v)}" for k, v in sorted(params.items(), key=lambda kv: str(kv[0]).lower())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _parse_pest_out(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = raw.split()
        if len(parts) < 2:
            continue
        name = str(parts[0]).strip().lower()
        try:
            out[name] = float(parts[1])
        except ValueError:
            continue
    return out


def _build_sim_metrics(pest_values: dict[str, float], metrics: list[str], trts: list[int]) -> dict[str, np.ndarray]:
    sim: dict[str, np.ndarray] = {}
    for metric in metrics:
        key = str(metric).strip().lower()
        values: list[float] = []
        for trt in trts:
            name = f"{key}_t{int(trt):02d}"
            values.append(float(pest_values.get(name, float("nan"))))
        sim[key] = np.array(values, dtype=float)
    return sim


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sandbox_dir = Path(__file__).resolve().parent
    mvp_root = repo_root / "mvp_pest_mgda"
    mvp_src = mvp_root / "src"
    python_exe = mvp_root / ".venv" / "Scripts" / "python.exe"

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="", help="Directory to write debug artifacts into")
    args = parser.parse_args()

    os.environ.setdefault("AR_PROJECT_CONFIG", str((sandbox_dir / "project_wheat.json").resolve()))
    os.environ.setdefault("AR_MVP_ROOT", str(mvp_root.resolve()))

    eval_mod = _load_eval_module(sandbox_dir)
    trts = [int(v) for v in getattr(eval_mod, "SCENARIO_TRTS")]
    metrics = [str(v).strip().lower() for v in getattr(eval_mod, "comparable_evaluation_metrics")()]

    with open(os.environ["AR_PROJECT_CONFIG"], "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    filex_path = Path(str(((cfg.get("scenario", {}) or {}).get("filex", "")).strip())).resolve()
    cul_path = Path(str(((cfg.get("paths", {}) or {}).get("cul_path", "")).strip())).resolve()
    case_dir = Path(str(((cfg.get("paths", {}) or {}).get("dssat_case_dir", "")).strip())).resolve()

    sys.path.insert(0, str(mvp_src))
    from calibration_core.pest_runner import run_model_with_params
    from dssat_io import extract_cultivar_code, read_eval_row, read_table_row

    cultivar_code = extract_cultivar_code(filex_path)
    cul_vals = _parse_cul_row_values(cul_path, cultivar_code)
    base_p1d = float(cul_vals.get("P1D", float("nan")))
    base_p5 = float(cul_vals.get("P5", float("nan")))
    base_phint = float(cul_vals.get("PHINT", float("nan")))

    if not args.output_root.strip():
        output_root = sandbox_dir / "debug_runs" / time.strftime("%Y%m%d_%H%M%S_wheat_param_sensitivity")
    else:
        output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    scenarios: list[tuple[str, dict[str, float]]] = [
        ("official_default", {}),
        (
            "low_p1d_p5_phint",
            {"p1d": base_p1d * 0.5, "p5": base_p5 * 0.5, "phint": base_phint * 0.5},
        ),
        (
            "high_p1d_p5_phint",
            {"p1d": base_p1d * 1.5, "p5": base_p5 * 1.5, "phint": base_phint * 1.5},
        ),
    ]

    summary: dict[str, object] = {
        "trts": trts,
        "metrics": metrics,
        "cultivar_code": cultivar_code,
        "cul_path": str(cul_path),
        "cul_baseline": {"p1d": base_p1d, "p5": base_p5, "phint": base_phint},
        "runs": {},
    }

    for name, param_updates in scenarios:
        work_dir = output_root / name
        runtime_root = work_dir / "runtime"
        work_dir.mkdir(parents=True, exist_ok=True)
        _write_params_dat(work_dir / "params.dat", param_updates)
        extra_env = {
            "PROJECT_CROP": "wheat",
            "DSSAT_CASE_DIR": str(case_dir),
            "DSSAT_RUNTIME_ROOT": str(runtime_root),
            "DSSAT_COPY_OUTPUTS_PER_TRT": "1",
            "DSSAT_SKIP_TASKKILL": "1",
            "CUL_PATH": str(cul_path),
        }
        cp = run_model_with_params(
            work_dir=work_dir,
            params_path=work_dir / "params.dat",
            trts=trts,
            keep_outputs=True,
            python_executable=str(python_exe) if python_exe.exists() else None,
            extra_env=extra_env,
            failure_label=f"run_model {name}",
        )
        pest_map = _parse_pest_out(work_dir / "pest_out.dat")
        sim_metrics = _build_sim_metrics(pest_map, metrics, trts)
        train_score = float(getattr(eval_mod, "score_metrics")(sim_metrics, metrics, "train"))
        all_score = float(getattr(eval_mod, "score_metrics")(sim_metrics, metrics, "all"))

        per_trt: dict[int, dict[str, object]] = {}
        for trt in trts:
            eval_path = runtime_root / f"Evaluate.OUT.trt{int(trt):02d}"
            sum_path = runtime_root / f"Summary.OUT.trt{int(trt):02d}"
            warn_path = runtime_root / f"WARNING.OUT.trt{int(trt):02d}"
            eval_row = read_eval_row(eval_path) if eval_path.exists() else {}
            sum_row = read_table_row(sum_path) if sum_path.exists() else {}
            warn_tail = ""
            if warn_path.exists():
                warn_tail = "\n".join(warn_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-12:])
            per_trt[int(trt)] = {
                "eval": {k: eval_row.get(k) for k in ["TRNO", "ADAPS", "ADAPM", "MDAPS", "MDAPM", "HWAMS", "HWAMM", "LAIXS", "LAIXM"]},
                "summary": {k: sum_row.get(k) for k in ["TRNO", "ADAT", "MDAT", "HWAM", "LAIX", "CWAM", "PRCM"]},
                "warn_tail": warn_tail,
            }

        summary["runs"][name] = {
            "params": param_updates,
            "returncode": int(cp.returncode),
            "train_score": train_score,
            "all_score": all_score,
            "per_trt": per_trt,
            "runtime_root": str(runtime_root),
        }

    (output_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
