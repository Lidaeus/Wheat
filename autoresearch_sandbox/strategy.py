import numpy as np

def calculate_loss(sim_yield, obs_yield, sim_lai, obs_lai):
    # fitness = exp(-(sim - obs)^2 / (2 * (0.5 * obs)^2))
    sigma_y = 0.5 * obs_yield + 1e-8
    fitness_y = np.exp(-((sim_yield - obs_yield)**2) / (2 * sigma_y**2))
    
    sigma_l = 0.5 * obs_lai + 1e-8
    fitness_l = np.exp(-((sim_lai - obs_lai)**2) / (2 * sigma_l**2))
    
    # Exponents from IMPORTANCE_EXPONENT: yield=10, lai=1
    fit_y_penalized = fitness_y ** 10.0
    fit_l_penalized = fitness_l ** 1.0
    
    # minimize negative fitness
    total_loss = - (np.prod(fit_y_penalized) * np.prod(fit_l_penalized))
    return total_loss
