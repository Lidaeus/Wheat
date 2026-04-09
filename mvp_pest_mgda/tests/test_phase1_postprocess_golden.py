from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT.parent / "autoresearch_sandbox"
if str(SANDBOX) not in sys.path:
    sys.path.insert(0, str(SANDBOX))

import phase1_postprocess

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "golden" / "phase1_postprocess"


class TestPhase1PostprocessGolden(unittest.TestCase):
    def test_outputs_match_golden_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)
            for fixture_name in (
                "phase1_experiment_summary.tsv",
                "phase1_aggregate_metrics.tsv",
                "phase1_parameters.tsv",
            ):
                shutil.copy2(FIXTURE_ROOT / fixture_name, session_dir / fixture_name)

            with patch.object(sys, "argv", ["phase1_postprocess.py", "--input-dir", str(session_dir)]):
                phase1_postprocess.main()

            derived_actual = (session_dir / "phase1_derived_metrics.tsv").read_text(encoding="utf-8")
            combo_actual = (session_dir / "phase1_combo_summary.tsv").read_text(encoding="utf-8")
            derived_expected = (FIXTURE_ROOT / "expected_phase1_derived_metrics.tsv").read_text(encoding="utf-8")
            combo_expected = (FIXTURE_ROOT / "expected_phase1_combo_summary.tsv").read_text(encoding="utf-8")

        self.assertEqual(derived_actual, derived_expected)
        self.assertEqual(combo_actual, combo_expected)


if __name__ == "__main__":
    unittest.main()
