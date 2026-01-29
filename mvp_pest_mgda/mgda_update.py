from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pyemu


def _min_norm_two(g1: np.ndarray, g2: np.ndarray) -> tuple[float, np.ndarray]:
    d = g1 - g2
    denom = float(np.dot(d, d))
    if denom <= 0.0:
        alpha = 0.5
    else:
        alpha = float(np.dot(g2, g2 - g1) / denom)
        alpha = max(0.0, min(1.0, alpha))
    g = alpha * g1 + (1.0 - alpha) * g2
    return alpha, g


def _read_current_params(pst: pyemu.Pst) -> dict[str, float]:
    return pst.parameter_data.parval1.to_dict()


def _write_params_dat(path: Path, params: dict[str, float]) -> None:
    lines = [f"{k} {v:.6f}" for k, v in params.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    cwd = Path.cwd()
    pst_path = cwd / "ksas_mvp.pst"
    jco_path = cwd / "ksas_mvp.jco"
    if not jco_path.exists():
        jco_path = cwd / "ksas_mvp.jcb"
    rei_path = cwd / "ksas_mvp.rei"

    pst = pyemu.Pst(str(pst_path))
    jco = pyemu.Jco.from_binary(str(jco_path))
    res = pyemu.pst_utils.read_resfile(str(rei_path))

    obs = pst.observation_data.copy()
    obs = obs.loc[jco.row_names, :]
    res = res.loc[jco.row_names, :]

    resid = res.residual.to_numpy(dtype=float)
    names = list(jco.row_names)
    par_names = list(jco.col_names)
    J = np.asarray(jco.x, dtype=float)

    idx_y = [i for i, n in enumerate(names) if obs.loc[n, "obgnme"] == "obs_yield"]
    idx_l = [i for i, n in enumerate(names) if obs.loc[n, "obgnme"] == "obs_laix"]
    if not idx_y or not idx_l:
        raise RuntimeError("Expected obs_yield and obs_laix groups")

    r_y = resid[idx_y]
    r_l = resid[idx_l]
    J_y = J[idx_y, :]
    J_l = J[idx_l, :]

    g_y = -(J_y.T @ r_y)
    g_l = -(J_l.T @ r_l)
    ny = float(np.linalg.norm(g_y))
    nl = float(np.linalg.norm(g_l))
    if ny > 0:
        g_y = g_y / ny
    if nl > 0:
        g_l = g_l / nl

    if ny <= 0.0 and nl <= 0.0:
        raise RuntimeError("Both objective gradients are zero")
    if ny > 0.0 and nl <= 0.0:
        alpha, g = 1.0, g_y
    elif nl > 0.0 and ny <= 0.0:
        alpha, g = 0.0, g_l
    else:
        alpha, g = _min_norm_two(g_y, g_l)
    d = -g

    p0 = _read_current_params(pst)
    lb = pst.parameter_data.parlbnd.to_dict()
    ub = pst.parameter_data.parubnd.to_dict()

    x0 = np.array([(p0[p] - lb[p]) / (ub[p] - lb[p]) for p in par_names], dtype=float)
    scale = np.array([(ub[p] - lb[p]) for p in par_names], dtype=float)
    grad_x = d * scale
    ng = float(np.linalg.norm(grad_x))
    if ng <= 0.0 or not math.isfinite(ng):
        raise RuntimeError("MGDA direction is degenerate")
    grad_x = grad_x / ng

    step = float((cwd / "step.txt").read_text(encoding="utf-8").strip()) if (cwd / "step.txt").exists() else 0.2
    x1 = np.clip(x0 + step * grad_x, 0.0, 1.0)
    p1 = {p: float(lb[p] + x1[i] * (ub[p] - lb[p])) for i, p in enumerate(par_names)}

    _write_params_dat(cwd / "params.dat", p1)
    (cwd / "mgda_report.txt").write_text(
        f"alpha_yield={alpha:.6f}\nstep={step:.6f}\n" + "\n".join([f"{k}={v:.6f}" for k, v in p1.items()]) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
