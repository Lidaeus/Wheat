import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyemu

def main():
    cwd = Path('c:/DSSAT48/Wheat/mvp_pest_mgda/runs/_runs/20260301_013940/iter_001')
    jco = pyemu.Jco.from_binary(str(cwd / 'ksas_mvp.jcb'))
    res = pyemu.pst_utils.read_resfile(str(cwd / 'ksas_mvp.rei'))
    pst = pyemu.Pst(str(cwd / 'ksas_mvp.pst'))
    
    obs = pst.observation_data.loc[jco.row_names, :].copy()
    res = res.loc[jco.row_names, :]
    resid = res.residual.to_numpy(dtype=float)
    J = np.asarray(jco.x, dtype=float)
    
    # Just grab indexing for `obs_laix`
    idx = np.where(obs.obgnme == 'obs_laix')[0]
    
    obs_vals = obs.obsval.iloc[idx].to_numpy(dtype=float)
    stdev = float(np.std(obs_vals, ddof=1))
    
    r = resid[idx]
    Jg = J[idx, :]
    
    w_factor = 1.0 / stdev # simplified decay weight
    r_w = r * w_factor
    Jg_w = Jg * w_factor
    
    g = -(Jg_w.T @ r_w) / float(len(idx))
    
    print("obs_laix stdev:", stdev)
    print("max Jg (raw):", np.max(np.abs(Jg)))
    print("max r (raw):", np.max(np.abs(r)))
    print("max Jg_w:", np.max(np.abs(Jg_w)))
    print("max r_w:", np.max(np.abs(r_w)))
    print("obs names for laix:", obs.iloc[idx].index.tolist())
    print("r vector:", r)

if __name__ == "__main__":
    main()
