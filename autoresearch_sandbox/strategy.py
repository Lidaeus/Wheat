import numpy as np

def _metric_loss(sim, obs, kind):
    eps = 1e-8
    err = sim - obs
    abs_obs = np.abs(obs) + eps
    rel = np.abs(err) / abs_obs
    if kind == "nrmse":
        return float(np.sqrt(np.mean(err**2)) / (np.mean(np.abs(obs)) + eps))
    if kind == "relative_mae":
        return float(np.mean(rel))
    if kind == "smape":
        return float(np.mean((2.0 * np.abs(err)) / (np.abs(sim) + np.abs(obs) + eps)))
    if kind == "log_rmse":
        log_sim = np.log(np.clip(sim, eps, None))
        log_obs = np.log(np.clip(obs, eps, None))
        return float(np.sqrt(np.mean((log_sim - log_obs)**2)))
    delta = 0.25
    huber = np.where(rel <= delta, 0.5 * rel**2, delta * (rel - 0.5 * delta))
    return float(np.mean(huber))

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    eps = 1e-8
    loss_y = _metric_loss(sim_yield, obs_yield, "smape")
    loss_l = _metric_loss(sim_lai, obs_lai, "log_rmse")
    shaped = np.power(np.clip(np.array([loss_y, loss_l], dtype=float), eps, None), 1.15)
    if "l2" == "sum":
        base = float(np.sum(shaped))
    elif "l2" == "l2":
        base = float(np.sqrt(np.sum(shaped**2)))
    else:
        base = float(0.5 * np.mean(shaped) + 0.5 * np.max(shaped))
    imbalance = float(np.abs(shaped[0] - shaped[1]))
    rel_y = np.abs(sim_yield - obs_yield) / (np.abs(obs_yield) + eps)
    rel_l = np.abs(sim_lai - obs_lai) / (np.abs(obs_lai) + eps)
    treatment_penalty = float(np.var(rel_y) + np.var(rel_l))
    cross_penalty = float(np.sqrt(np.clip(loss_y * loss_l, eps, None)))
    total = base + (0.25 * imbalance) + (0.12 * treatment_penalty) + (0.05 * cross_penalty)
    return float(total if np.isfinite(total) else 1e9)
