from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in os.sys.path:
    os.sys.path.insert(0, str(SRC))

import run_model


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_WHEAT_DSSAT_ACCEPTANCE") == "1",
    "Set RUN_LIVE_WHEAT_DSSAT_ACCEPTANCE=1 to run live Wheat acceptance.",
)
class TestLiveWheatAcceptance(unittest.TestCase):
    def test_live_wheat_execute_case_minimum_closure(self) -> None:
        source_case_dir = Path(r"C:\DSSAT48\Wheat")
        if not source_case_dir.exists():
            self.skipTest("Missing DSSAT Wheat case directory")

        whx_name = os.environ.get("LIVE_WHEAT_FILEX", "SWSW7501.WHX")
        wha_name = os.environ.get("LIVE_WHEAT_CUL", "SWSW7501.WHA")
        whx_source = source_case_dir / whx_name
        wha_source = source_case_dir / wha_name
        if not whx_source.exists() or not wha_source.exists():
            self.skipTest("Missing live Wheat FileX or cultivar file")

        dssat_root = Path(os.environ.get("LIVE_DSSAT_ROOT", r"C:\DSSAT48"))
        if not dssat_root.exists():
            self.skipTest("Missing LIVE_DSSAT_ROOT")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_dir = root / "runtime_case"
            shutil.copytree(source_case_dir, case_dir)
            (root / "params.dat").write_text("", encoding="utf-8")

            project_cfg = root / "project.live_wheat.json"
            project_cfg.write_text(
                (
                    "{\n"
                    '  "id": "live_wheat_acceptance",\n'
                    '  "crop": "wheat",\n'
                    f'  "dssat_root": "{str(dssat_root).replace("\\", "\\\\")}",\n'
                    f'  "dssat_filex": "{whx_name}",\n'
                    f'  "cultivar_template": "{wha_name}",\n'
                    '  "target_variable": "HWAM",\n'
                    '  "parameters": [],\n'
                    '  "bounds": {},\n'
                    '  "phase0_observations": {},\n'
                    '  "treatment_mapping": {"1": "WW22"},\n'
                    '  "data": {"treatment_mapping": {"1": "WW22"}}\n'
                    "}\n"
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "PEST_PROJECT_CONFIG": str(project_cfg),
                    "DSSAT_CASE_DIR": str(case_dir),
                    "DSSAT_FILEX": whx_name,
                    "DSSAT_CUL_FILE": wha_name,
                    "DSSAT_CUL_FILE_RESOLVED": wha_name,
                    "DSSAT_CULTIVAR_CODE": "990002",
                    "TRTNO": "1",
                },
                clear=False,
            ):
                prepared = run_model.prepare_case_run(root)
                metrics_by_trt, treatment_calls = run_model.execute_case(
                    prepared.base,
                    prepared.live_filex,
                    prepared.cul_path,
                    prepared.cultivar_code,
                    prepared.filex_name,
                    prepared.dssat_dir,
                    prepared.cfg,
                    prepared.trts,
                    prepared.case_runtime,
                    prepared.file_state,
                    prepared.keep_outputs,
                )

        self.assertEqual(prepared.trts, [1])
        self.assertEqual(treatment_calls, 1)
        self.assertIn(1, metrics_by_trt)
        self.assertIn("hwam", metrics_by_trt[1])
        self.assertTrue(np.isfinite(metrics_by_trt[1]["hwam"]))


if __name__ == "__main__":
    unittest.main()
