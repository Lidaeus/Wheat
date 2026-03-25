import numpy as np

def calculate_loss(obs_yield, sim_yield, obs_lai, sim_lai):
    """
    Calculate the objective function (Loss) for the crop model optimizer.
    
    This is the ONLY file the AI Agent should modify.
    Try different weighting schemes: Inverse Variance, Min-Max Normalization, 
    Log Transformation, or dynamic penalties based on CV.
    
    Args:
        obs_yield: np.array, Observed yield (e.g. ~6000 kg/ha)
        sim_yield: np.array, Simulated yield
        obs_lai: np.array, Observed Leaf Area Index (e.g. ~3.0)
        sim_lai: np.array, Simulated Leaf Area Index
        
    Returns:
        float: The scalar loss value that the optimizer will try to minimize.
    """
    # [BASELINE VERSION]: Simple Sum of Squared Errors
    # Warning: Because Yield is ~10^3 and LAI is ~10^0, Yield will dominate the loss.
    
    loss_yield = np.sum((obs_yield - sim_yield) ** 2)
    loss_lai = np.sum((obs_lai - sim_lai) ** 2)
    
    total_loss = loss_yield + loss_lai
    return total_loss
