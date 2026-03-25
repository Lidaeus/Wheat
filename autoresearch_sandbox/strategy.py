import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    # Step 1: pseudo-variances
    var_y = np.var(sim_yield - obs_yield) + 1e-8
    var_l = np.var(sim_lai - obs_lai) + 1e-8
    
    # Step 2: WLS
    loss_y = np.mean((sim_yield - obs_yield)**2) / var_y
    loss_l = np.mean((sim_lai - obs_lai)**2) / var_l
    
    return loss_y + loss_l
