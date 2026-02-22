import math
import unittest
from pathlib import Path
from typing import cast

from compare_three import TrtRow, _calc_summary, _resolve_family_param_keys


class TestMetrics(unittest.TestCase):
    def test_calc_summary_single_row(self):
        row = cast(TrtRow, {
            "scenario": "pest",
            "trt": 1,
            "split": "train",
            "obs_yield": 100.0,
            "sim_yield": 110.0,
            "err_yield": 10.0,
            "obs_laix": float("nan"),
            "sim_laix": float("nan"),
            "err_laix": float("nan"),
            "n_wht_dates": 0,
            "n_wht_lwad": 0,
            "n_wht_swad": 0,
            "phi_yield": 100.0,
            "phi_laix": 0.0,
            "phi_laid": 0.0,
            "phi_lwad": 0.0,
            "phi_swad": 0.0,
            "phi": 100.0,
            "phi_w": 100.0,
        })
        s = _calc_summary([row])
        self.assertEqual(s["n_trt"], 1)
        self.assertTrue(math.isfinite(float(s["rmse_yield"])))
        self.assertAlmostEqual(float(s["rmse_yield"]), 10.0, places=6)
        self.assertAlmostEqual(float(s["mae_yield"]), 10.0, places=6)
        self.assertAlmostEqual(float(s["bias_yield"]), 10.0, places=6)

    def test_family_param_order_wheat(self):
        cfg = {"crop_family": "wheat"}
        dssat_dir = Path("WHEAT")
        keys = ["g2", "p5", "g1", "phint", "p1d", "p1v", "sh2o_30", "sh2o_15", "foo"]
        out = _resolve_family_param_keys(cfg, dssat_dir, keys)
        exp = ["sh2o_15", "sh2o_30", "p1v", "p1d", "p5", "phint", "g1", "g2"]
        self.assertEqual(out[: len(exp)], exp)

    def test_family_param_order_sunflower(self):
        cfg = {"crop_family": "sunflower"}
        dssat_dir = Path("SUNFLOWER")
        keys = ["wtpsd", "ppsen", "slavr", "xfrt", "sfdur", "sh2o_15"]
        out = _resolve_family_param_keys(cfg, dssat_dir, keys)
        exp = ["ppsen", "sfdur", "slavr", "wtpsd", "xfrt", "sh2o_15"]
        self.assertEqual(out[: len(exp)], exp)


if __name__ == "__main__":
    unittest.main()
