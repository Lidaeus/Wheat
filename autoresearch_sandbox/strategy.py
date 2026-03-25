import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    log_sim_y = np.log(np.clip(sim_yield, 1e-8, None))
    log_obs_y = np.log(np.clip(obs_yield, 1e-8, None))
    
    log_sim_l = np.log(np.clip(sim_lai, 1e-8, None))
    log_obs_l = np.log(np.clip(obs_lai, 1e-8, None))
    
    loss_y = np.mean((log_sim_y - log_obs_y)**2)
    loss_l = np.mean((log_sim_l - log_obs_l)**2)
    
    return loss_y + loss_l
