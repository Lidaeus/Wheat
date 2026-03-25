import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    err_y = np.abs(sim_yield - obs_yield)
    err_l = np.abs(sim_lai - obs_lai)
    
    max_err_y = np.max(obs_yield) + 1e-8
    max_err_l = np.max(obs_lai) + 1e-8
    
    norm_y = np.mean(err_y / max_err_y)
    norm_l = np.mean(err_l / max_err_l)
    
    return norm_y + norm_l
