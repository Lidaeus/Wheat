import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    nrmse_y = np.sqrt(np.mean((sim_yield - obs_yield)**2)) / (np.mean(obs_yield) + 1e-8)
    nrmse_l = np.sqrt(np.mean((sim_lai - obs_lai)**2)) / (np.mean(obs_lai) + 1e-8)
    
    # Scalarize pareto logic: distance to origin (0,0) + penalty for imbalance
    distance = np.sqrt(nrmse_y**2 + nrmse_l**2)
    imbalance = np.abs(nrmse_y - nrmse_l)
    
    return distance + 0.5 * imbalance
