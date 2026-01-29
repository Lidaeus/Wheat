from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


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
    lines = filex_in.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    out_lines: list[str] = []
    in_ic_table = False
    for raw in lines:
        line = raw
        if line.startswith("@C") and "ICBL" in line and "SH2O" in line:
            in_ic_table = True
            out_lines.append(line)
            continue
        if in_ic_table:
            if line.startswith("*") or line.startswith("@"):
                in_ic_table = False
                out_lines.append(line)
                continue
            m = re.match(r"^(\s*)(\d+)\s+(\d+)\s+([-\.\d]+)\s+([-\.\d]+)\s+([-\.\d]+)(\s*)$", line.rstrip("\r\n"))
            if m:
                lead, c, icbl_s, sh2o_s, snh4_s, sno3_s, tail = m.groups()
                c_i = int(c)
                icbl_i = int(icbl_s)
                if icbl_i in sh2o_by_icbl:
                    sh2o_s = _sh2o_token(sh2o_by_icbl[icbl_i])
                sh2o_fmt = f"{sh2o_s:>6s}"
                snh4 = float(snh4_s)
                sno3 = float(sno3_s)
                rebuilt = f"{lead}{c_i:>2d}{icbl_i:6d}{sh2o_fmt}{snh4:6.1f}{sno3:6.1f}{tail}\n"
                out_lines.append(rebuilt)
                continue
        out_lines.append(line)
    filex_out.write_text("".join(out_lines), encoding="utf-8")


def _run_dssat(filex: str, trt: int, cwd: Path) -> None:
    exe = Path(os.environ.get("DSSAT_EXE", r"C:\DSSAT48\DSCSM048.EXE"))
    cmd = [str(exe), "C", filex, str(trt)]
    cp = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if cp.returncode != 0:
        raise RuntimeError(f"DSSAT failed: {cp.returncode}\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}")


def _extract_eval_metrics(eval_path: Path) -> dict[str, float]:
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
    cols = header.split()
    vals = last_row.split()
    if len(vals) < len(cols):
        raise RuntimeError("Evaluate.OUT row shorter than header")
    row = dict(zip(cols, vals))
    hwam = float(row["HWAMS"])
    laix = float(row["LAIXS"])
    return {"hwam": hwam, "laix": laix}


def main() -> None:
    cwd = Path.cwd()
    dssat_dir = Path(__file__).resolve().parents[1]
    params_path = cwd / "params.dat"
    params = _read_params(params_path)

    base = cwd / "KSAS8101_base.WHX"
    live = dssat_dir / "KSAS8101.WHX"
    if not base.exists():
        base.write_text(live.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

    for p in ["Evaluate.OUT", "Summary.OUT", "WARNING.OUT"]:
        fp = dssat_dir / p
        if fp.exists():
            fp.unlink()

    sh2o_by_icbl = {
        15: params.get("sh2o_15", 0.205),
        30: params.get("sh2o_30", 0.170),
    }
    _rewrite_initial_sh2o(base, live, sh2o_by_icbl)
    try:
        _run_dssat("KSAS8101.WHX", 1, dssat_dir)
        metrics = _extract_eval_metrics(dssat_dir / "Evaluate.OUT")
    finally:
        _rewrite_initial_sh2o(base, live, {15: 0.205, 30: 0.170})

    (cwd / "pest_out.dat").write_text(
        f"hwam {metrics['hwam']:.3f}\nlaix {metrics['laix']:.3f}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
