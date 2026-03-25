import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    loss_y = np.mean((sim_yield - obs_yield)**2)
    loss_l = np.mean((sim_lai - obs_lai)**2)
    
    # Dynamically balance by multiplying each by the inverse of the other's loss to equalize gradients roughly
    weight_y = 1.0 / (loss_y + 1e-8)
    weight_l = 1.0 / (loss_l + 1e-8)
    
    # Normalize weights
    sum_w = weight_y + weight_l
    weight_y /= sum_w
    weight_l /= sum_w
    
    return weight_y * loss_y + weight_l * loss_l
