from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path

import numpy as np
import pyemu
from pest_runner import run_compare_model


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


def _read_par_params(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            out[parts[0].strip().lower()] = float(parts[1])
        except ValueError:
            continue
    return out

def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return bool(default)
    s = str(val).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _load_project_config(project_root: Path) -> dict:
    from dssat_io import load_project_config

    return load_project_config(project_root, crop=os.environ.get("PROJECT_CROP", ""))


def _extract_trt_from_obs_name(name: str) -> int | None:
    import re as _re
    m = _re.search(r"_t(\d{2})", str(name).lower())
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _extract_dap_from_obs_name(name: str) -> int | None:
    import re as _re
    m = _re.search(r"_d(\d{1,3})$", str(name).lower())
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _resolve_split(cfg: dict, trts: list[int]) -> dict[int, str]:
    split_cfg = cfg.get("split", {})
    mode = str(split_cfg.get("mode", "trt")).strip().lower()
    all_trts = [int(t) for t in trts]

    # mode='none' or 'all' → every TRT is training, no validation
    if mode in {"none", "all"}:
        return {int(t): "train" for t in all_trts}

    train = {int(t) for t in (split_cfg.get("train_trts") or []) if str(t).strip()}
    valid = {int(t) for t in (split_cfg.get("valid_trts") or []) if str(t).strip()}

    ratio = None
    if "valid_ratio" in split_cfg:
        try:
            ratio = float(split_cfg.get("valid_ratio"))
        except Exception:
            ratio = None
    if ratio is None and not train and not valid and len(all_trts) > 1:
        ratio = 0.2

    if mode == "ratio" and ratio is not None:
        rnd = random.Random(int(split_cfg.get("seed", split_cfg.get("random_seed", 0))))
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


def _resolve_obs_group_name(name: str, default_group: str, cfg: dict) -> str:
    cfg_obs = cfg.get("observations", {})
    group_defs = cfg_obs.get("groups", {})
    name_l = str(name).strip().lower()
    for gname, gspec in group_defs.items():
        pats = [str(p).lower() for p in (gspec.get("patterns") or [])]
        if any(name_l.startswith(p) for p in pats):
            return str(gname)
    metrics_cfg = cfg.get("metrics", {}) or cfg.get("variables", {}) or {}
    yield_prefix = str(metrics_cfg.get("yield_var", "HWAM")).strip().lower()
    laix_prefix = str(metrics_cfg.get("laix_var", "LAIX")).strip().lower()
    if yield_prefix and name_l.startswith(yield_prefix + "_"):
        return "obs_yield"
    if laix_prefix and name_l.startswith(laix_prefix + "_"):
        return "obs_laix"
    if name_l.startswith("laid_"):
        return "obs_laid"
    if name_l.startswith("swad_"):
        return "obs_swad"
    if name_l.startswith("lwad_"):
        return "obs_lwad"
    return str(default_group)


def _calc_group_variances(obs, split_by_trt: dict[int, str], cfg: dict) -> dict[str, float]:
    group_vals: dict[str, list[float]] = {}
    for oname, row in obs.iterrows():
        trt = _extract_trt_from_obs_name(oname)
        if (trt is not None) and (split_by_trt.get(int(trt)) == "valid"):
            continue
        try:
            v = float(row.obsval)
        except Exception:
            continue
        default_group = str(row.obgnme) if "obgnme" in obs.columns else "obs"
        g = _resolve_obs_group_name(oname, default_group, cfg)
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


def _calc_phi(
    pst: pyemu.Pst, 
    sim: dict[str, float], 
    cfg: dict, 
    group_sizes: dict[str, int],
    loss_type: str = "mse",
    huber_delta: float = 1.0
) -> float:
    """
    计算加权目标函数 Phi。
    深度对齐：直接使用 pst.observation_data.weight (即 1/sigma)
    """
    obs = pst.observation_data
    phi = 0.0
    
    for oname, row in obs.iterrows():
        k = str(oname).strip().lower()
        if k not in sim:
            continue
        try:
            # 深度对齐：直接读取 PEST 控制文件中的权重 (w = 1/sigma)
            w = float(row.weight)
            o = float(row.obsval)
        except Exception:
            continue
            
        e = float(sim[k]) - o
        
        # 寻找对应的组
        gn = _resolve_obs_group_name(k, "obs", cfg)
        size = float(group_sizes.get(gn, 1.0))
        if size <= 0.0:
            size = 1.0
            
        # 归一化误差：e_norm = e * w = e / sigma
        e_norm = (e * w)
        
        if loss_type == "huber":
            abs_e = abs(e_norm)
            if abs_e <= huber_delta:
                phi += (0.5 * (e_norm ** 2)) / size
            else:
                phi += (huber_delta * (abs_e - 0.5 * huber_delta)) / size
        else:
            phi += (0.5 * (e_norm ** 2)) / size
        
    return float(phi)


def _evaluate_phi(
    work_dir: Path,
    pst: pyemu.Pst,
    params: dict[str, float],
    cfg: dict,
    group_sizes: dict[str, int],
    loss_type: str = "mse",
    huber_delta: float = 1.0,
) -> float:
    eval_params_path = work_dir / "_mgda_eval_params.dat"
    _write_params_dat(eval_params_path, params)

    sim = run_compare_model(
        work_dir=work_dir,
        params_path=eval_params_path,
        keep_outputs=False,
        failure_label="mgda_update run_model.py",
    )
    return _calc_phi(pst, sim, cfg, group_sizes, loss_type, huber_delta)


def _write_params_dat(path: Path, params: dict[str, float]) -> None:
    lines = [f"{k} {v:.6f}" for k, v in params.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fw_min_norm_simplex(G: np.ndarray, max_iter: int = 200, tol: float = 1.0e-10) -> np.ndarray:
    k = int(G.shape[1])
    Q = G.T @ G

    norms = np.diag(Q)
    j0 = int(np.argmin(norms))
    a = np.zeros(k, dtype=float)
    a[j0] = 1.0

    for _ in range(max_iter):
        grad = 2.0 * (Q @ a)
        j = int(np.argmin(grad))
        s_dir = np.zeros(k, dtype=float)
        s_dir[j] = 1.0
        d = s_dir - a

        denom = float(d @ (Q @ d))
        if denom <= 0.0:
            gamma = 1.0
        else:
            gamma = float(-(d @ (Q @ a)) / denom)
            gamma = max(0.0, min(1.0, gamma))
        a_next = a + gamma * d

        if float(np.linalg.norm(a_next - a)) <= tol:
            a = a_next
            break
        a = a_next

    a = np.clip(a, 0.0, 1.0)
    s_sum = float(a.sum())
    if s_sum > 0:
        a = a / s_sum
    else:
        a[:] = 1.0 / k
    return a


def main() -> None:
    cwd = Path.cwd()
    project_root = Path(__file__).resolve().parents[1]
    cfg = _load_project_config(project_root)
    out_params_path = Path(os.environ.get("OUT_PARAMS_PATH", str(cwd / "params.dat")))
    pst_path = cwd / "ksas_mvp.pst"
    jco_path = cwd / "ksas_mvp.jco"
    if not jco_path.exists():
        jco_path = cwd / "ksas_mvp.jcb"
    rei_path = cwd / "ksas_mvp.rei"
    if not rei_path.exists():
        rei_path = cwd / "ksas_mvp.rei1"
    if not rei_path.exists():
        candidates = list(cwd.glob("ksas_mvp*.rei"))
        if candidates:
            rei_path = max(candidates, key=lambda p: p.stat().st_mtime)

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

    p0_src = "pst"
    p0_par: dict[str, float] = {}
    if (cwd / "ksas_mvp_est.par").exists():
        p0_src = "ksas_mvp_est.par"
        p0_par = _read_par_params(cwd / "ksas_mvp_est.par")
    elif (cwd / "ksas_mvp.par").exists():
        p0_src = "ksas_mvp.par"
        p0_par = _read_par_params(cwd / "ksas_mvp.par")
    p0_pst = _read_current_params(pst)
    p0 = {p: float(p0_par.get(p, p0_pst[p])) for p in par_names}

    cfg_obs = cfg.get("observations", {})
    group_defs = cfg_obs.get("groups", {})
    trts_from_obs: list[int] = []
    seen_trt: set[int] = set()
    for n in obs.index.astype(str).tolist():
        trt = _extract_trt_from_obs_name(n)
        if trt is None:
            continue
        if int(trt) in seen_trt:
            continue
        seen_trt.add(int(trt))
        trts_from_obs.append(int(trt))
    split_by_trt = _resolve_split(cfg, trts_from_obs)

    group_index: dict[str, list[int]] = {}
    for i, n in enumerate(names):
        default_group = str(obs.loc[n, "obgnme"]) if "obgnme" in obs.columns else "obs"
        gn = _resolve_obs_group_name(n, default_group, cfg)
        trt = _extract_trt_from_obs_name(n)
        if (trt is not None) and (split_by_trt.get(int(trt)) == "valid"):
            continue
        group_index.setdefault(gn, []).append(i)

    # 深度对齐：不再动态计算 group_obs_std，直接信任 PEST 控制文件中的权重
    mgda_cfg = cfg.get("optimization", {}).get("mgda", {})
    sigma_whiten = bool(mgda_cfg.get("sigma_prewhiten", mgda_cfg.get("sigma_whiten", False)))
    norm_strategy = str(mgda_cfg.get("normalize", "l2")).strip().lower()

    # Loss settings (MSE or Huber)
    loss_type = str(mgda_cfg.get("loss_type", os.environ.get("MGDA_LOSS_TYPE", "mse"))).strip().lower()
    huber_delta = float(mgda_cfg.get("huber_delta", os.environ.get("MGDA_HUBER_DELTA", "1.0")))

    # Time-decay settings
    time_decay_cfg = mgda_cfg.get("time_decay", {})
    w_base = float(time_decay_cfg.get("w_base", 1.0))
    w_max = float(time_decay_cfg.get("w_max", 2.0))
    k_slope = float(time_decay_cfg.get("k_slope", 0.05))
    t_mid = float(time_decay_cfg.get("t_mid", 60.0))
    eff_mode = str(mgda_cfg.get("eff_n_mode", "sqrt")).strip().lower()
    near_zero_eps = float(os.environ.get("MGDA_NEAR_ZERO_EPS", mgda_cfg.get("near_zero_eps", "1e-12")))
    trust_rel = float(os.environ.get("MGDA_TRUST_REL", mgda_cfg.get("trust_rel", "0.1")))
    reg_lambda = float(os.environ.get("MGDA_REG_LAMBDA", mgda_cfg.get("reg_lambda", "0.0")))

    groups: list[tuple[str, np.ndarray]] = []
    raw_norms: dict[str, float] = {}
    post_norms: dict[str, float] = {}
    group_sizes: dict[str, int] = {}
    group_sigmas: dict[str, float] = {}
    group_effn: dict[str, float] = {}
    applied_weights: dict[str, float] = {}
    near_zero_groups: list[str] = []
    active_groups: list[str] = []
    for gn, idx in group_index.items():
        if not idx:
            continue
        r = resid[idx]
        Jg = J[idx, :]
        spec = cfg.get("observations", {}).get("groups", {}).get(gn, {})
        sigma = float(spec.get("sigma", 1.0))

        # Intra-group time-decay computation
        obs_names_in_group = [names[i] for i in idx]
        daps = [_extract_dap_from_obs_name(n) for n in obs_names_in_group]
        
        # Apply time-decay weights if at least one observation has a valid DAP and time_decay is enabled
        decay_weights = np.ones(len(idx), dtype=float)
        if any(d is not None for d in daps) and w_max > w_base:
            # Fallback max DAP if t_mid is configured as percentage (e.g. 0.5)
            # Find max valid DAP to map percentage
            valid_daps = [d for d in daps if d is not None]
            local_t_mid = t_mid
            if 0.0 < t_mid < 1.0 and valid_daps:
                local_t_mid = max(valid_daps) * t_mid
            
            for j, d in enumerate(daps):
                if d is not None:
                    # Logistic bounded decay: w_base + (w_max - w_base) / (1 + exp(-k * (t - t_mid)))
                    decay_weights[j] = w_base + (w_max - w_base) / (1.0 + math.exp(-k_slope * (float(d) - local_t_mid)))
        
        # 深度对齐：直接从 PEST 提取权重 (w = 1/sigma)
        w_pest = obs.weight.iloc[idx].to_numpy(dtype=float)
        
        # 应用时间加权和 PEST 预设权重
        # r = (sim - obs) * w_pest * decay_weights
        w_factor = decay_weights * w_pest
        r = r * w_factor
        Jg = Jg * w_factor[:, np.newaxis]
        
        # Apply robust loss gradient clipping
        if loss_type == "huber":
            mask = np.abs(r) > huber_delta
            r[mask] = huber_delta * np.sign(r[mask])

        if sigma_whiten and math.isfinite(sigma) and sigma != 1.0:
            r = r / sigma
            Jg = Jg / sigma
        
        size = int(len(idx))
        if size > 0:
            g = -(Jg.T @ r) / float(size)
        else:
            g = np.zeros(Jg.shape[1], dtype=float)
            
        w_group = float(group_defs.get(gn, {}).get("weight", 1.0))
        g = g * w_group
        eff_n = spec.get("eff_n", None)
        if eff_n is not None:
            try:
                eff = float(eff_n)
                if eff > 0 and size > 0:
                    if eff_mode == "sqrt":
                        g = g * math.sqrt(eff / float(size))
                    elif eff_mode == "linear":
                        g = g * (eff / float(size))
            except Exception:
                pass
        ng = float(np.linalg.norm(g))
        raw_norms[gn] = ng
        group_sizes[gn] = size
        group_sigmas[gn] = float(sigma) if sigma_whiten else float("nan")
        applied_weights[gn] = w_group
        group_effn[gn] = float(eff_n) if eff_n is not None else float("nan")
        if ng <= near_zero_eps or not math.isfinite(ng):
            near_zero_groups.append(gn)
            post_norms[gn] = float(np.linalg.norm(g))
            continue
        if norm_strategy == "l2":
            g = g / ng
            # Apply dynamic weight AFTER normalization so it's not cancelled out
            g = g * w_group
        post_norms[gn] = float(np.linalg.norm(g))
        if float(np.linalg.norm(g)) > 0.0 and all(math.isfinite(x) for x in g):
            groups.append((gn, g))
            active_groups.append(gn)

    if not groups:
        _write_params_dat(out_params_path, p0)
        (cwd / "mgda_report.txt").write_text(
            "status=pareto_stationary\nreason=all_objective_gradients_near_zero\n"
            + f"near_zero_eps={near_zero_eps:.6e}\n"
            + ("near_zero_groups=" + ",".join(near_zero_groups) + "\n" if near_zero_groups else "")
            + "step=0.000000\n"
            + "\n".join([f"{k}={v:.6f}" for k, v in p0.items()])
            + "\n",
            encoding="utf-8",
        )
        return

    # Optional regularization group toward prior
    if reg_lambda > 0.0 and math.isfinite(reg_lambda):
        lb = pst.parameter_data.parlbnd.to_dict()
        ub = pst.parameter_data.parubnd.to_dict()
        scale = np.array([(ub[p] - lb[p]) for p in par_names], dtype=float)
        x0 = np.array([(p0[p] - lb[p]) / (ub[p] - lb[p]) for p in par_names], dtype=float)
        prior = _read_current_params(pst)
        x_prior = np.array([(prior[p] - lb[p]) / (ub[p] - lb[p]) for p in par_names], dtype=float)
        g_reg = reg_lambda * (x0 - x_prior) / scale
        ng_reg = float(np.linalg.norm(g_reg))
        raw_norms["reg"] = ng_reg
        post_norms["reg"] = float(np.linalg.norm(g_reg))
        if ng_reg > near_zero_eps and all(math.isfinite(x) for x in g_reg):
            groups.append(("reg", g_reg))
            active_groups.append("reg")

    if len(groups) == 1:
        alpha_vec = np.array([1.0], dtype=float)
        g = groups[0][1]
        alpha_by_group = {groups[0][0]: 1.0}
    elif len(groups) == 2:
        a, g = _min_norm_two(groups[0][1], groups[1][1])
        alpha_vec = np.array([a, 1.0 - a], dtype=float)
        alpha_by_group = {groups[0][0]: float(alpha_vec[0]), groups[1][0]: float(alpha_vec[1])}
    else:
        G = np.column_stack([g for _, g in groups])
        alpha_vec = _fw_min_norm_simplex(G)
        g = G @ alpha_vec
        alpha_by_group = {gn: float(alpha_vec[i]) for i, (gn, _) in enumerate(groups)}

    d = -g
    lb = pst.parameter_data.parlbnd.to_dict()
    ub = pst.parameter_data.parubnd.to_dict()

    x0 = np.array([(p0[p] - lb[p]) / (ub[p] - lb[p]) for p in par_names], dtype=float)
    scale = np.array([(ub[p] - lb[p]) for p in par_names], dtype=float)
    grad_x = d * scale
    ng = float(np.linalg.norm(grad_x))
    if ng <= 0.0 or not math.isfinite(ng):
        raise RuntimeError("MGDA direction is degenerate")
    grad_x = grad_x / ng

    step0 = float((cwd / "step.txt").read_text(encoding="utf-8").strip()) if (cwd / "step.txt").exists() else 0.2
    safe = _bool_env("MGDA_SAFE_STEP", True)
    phi0 = float("nan")
    phi1 = float("nan")
    accepted = True
    backtracks = 0
    step = float(step0)
    p1 = dict(p0)

    if safe:
        phi0 = _evaluate_phi(cwd, pst, p0, cfg, group_sizes, loss_type, huber_delta)
        phi_tol = float(os.environ.get("MGDA_PHI_TOL", "0.0"))
        max_back = int(os.environ.get("MGDA_MAX_BACKTRACK", "8"))
        accepted = False
        for k in range(max_back + 1):
            delta = step * grad_x
            if trust_rel > 0.0 and math.isfinite(trust_rel):
                delta = np.clip(delta, -trust_rel, trust_rel)
            x1 = np.clip(x0 + delta, 0.0, 1.0)
            cand = {p: float(lb[p] + x1[i] * (ub[p] - lb[p])) for i, p in enumerate(par_names)}
            try:
                phi_c = _evaluate_phi(cwd, pst, cand, cfg, group_sizes, loss_type, huber_delta)
            except Exception:
                phi_c = float("inf")
            if math.isfinite(phi_c) and phi_c <= phi0 * (1.0 + phi_tol):
                p1 = cand
                phi1 = float(phi_c)
                backtracks = int(k)
                accepted = True
                break
            step *= 0.5
        if not accepted:
            step = 0.0
            p1 = dict(p0)
    else:
        delta = step * grad_x
        if trust_rel > 0.0 and math.isfinite(trust_rel):
            delta = np.clip(delta, -trust_rel, trust_rel)
        x1 = np.clip(x0 + delta, 0.0, 1.0)
        p1 = {p: float(lb[p] + x1[i] * (ub[p] - lb[p])) for i, p in enumerate(par_names)}

    _write_params_dat(out_params_path, p1)
    alpha_lines = "\n".join([f"alpha[{k}]={v:.6f}" for k, v in alpha_by_group.items()])
    norm_lines = "\n".join([f"grad_norm_raw[{k}]={v:.6e}" for k, v in raw_norms.items()])
    post_norm_lines = "\n".join([f"grad_norm_post[{k}]={v:.6e}" for k, v in post_norms.items()])
    size_lines = "\n".join([f"group_size[{k}]={v:d}" for k, v in group_sizes.items()])
    sigma_lines = "\n".join([f"group_sigma[{k}]={v:.6f}" for k, v in group_sigmas.items() if not math.isnan(v)])
    effn_lines = "\n".join([f"group_eff_n[{k}]={v:.6f}" for k, v in group_effn.items() if not math.isnan(v)])
    weight_lines = "\n".join([f"group_weight[{k}]={v:.6f}" for k, v in applied_weights.items()])
    near_zero_line = f"near_zero_eps={near_zero_eps:.6e}"
    near_zero_groups_line = "near_zero_groups=" + ",".join(near_zero_groups) if near_zero_groups else ""
    active_groups_line = "active_groups=" + ",".join(active_groups) if active_groups else ""
    ang_lines = ""
    if len(groups) >= 2:
        vecs = {gn: g for gn, g in groups}
        keys = list(vecs.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                gi = vecs[keys[i]]
                gj = vecs[keys[j]]
                ni = float(np.linalg.norm(gi))
                nj = float(np.linalg.norm(gj))
                if ni > 0 and nj > 0:
                    c = float(np.clip((gi @ gj) / (ni * nj), -1.0, 1.0))
                    ang = float(math.degrees(math.acos(c)))
                    ang_lines += f"angle[{keys[i]},{keys[j]}]={ang:.6f}\n"

    # Export alphas for feedback loop
    alpha_json_path = cwd / "mgda_alphas.json"
    try:
        alpha_json_path.write_text(json.dumps(alpha_by_group, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not write mgda_alphas.json: {e}")

    (cwd / "mgda_report.txt").write_text(
        ("status=updated\n" if accepted else "status=rejected\n")
        + f"p0_source={p0_src}\n"
        + f"safe_step={int(safe)}\n"
        + f"trust_rel={trust_rel:.6f}\n"
        + (f"reg_lambda={reg_lambda:.6f}\n" if reg_lambda > 0.0 else "")
        + (f"loss_type={loss_type}\n")
        + (f"huber_delta={huber_delta:.6f}\n" if loss_type == "huber" else "")
        + (f"phi0={phi0:.6f}\n" if math.isfinite(phi0) else "")
        + (f"phi1={phi1:.6f}\n" if math.isfinite(phi1) else "")
        + (f"backtracks={backtracks}\n" if safe else "")
        + near_zero_line
        + ("\n" + near_zero_groups_line if near_zero_groups_line else "")
        + ("\n" + active_groups_line if active_groups_line else "")
        + "\n"
        + norm_lines
        + "\n"
        + post_norm_lines
        + "\n"
        + size_lines
        + ("\n" + sigma_lines if sigma_lines else "")
        + ("\n" + effn_lines if effn_lines else "")
        + "\n"
        + weight_lines
        + "\n"
        + ang_lines
        + alpha_lines
        + f"\nstep={step:.6f}\n"
        + "\n".join([f"{k}={v:.6f}" for k, v in p1.items()])
        + "\n",
        encoding="utf-8",
    )

    if accepted and step > 0:
        # Heuristic expansion: if we succeeded with 0 or 1 backtracks, try a larger step next time.
        # If we struggled (backtracks >= 2), stay at the successful step size.
        next_step = step
        if backtracks <= 1:
            next_step = step * 1.5
        (cwd / "step_next.txt").write_text(f"{next_step:.6f}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
