from __future__ import annotations

import csv
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


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class TestPhase1PostprocessOffline(unittest.TestCase):
    def test_postprocess_derives_baseline_deltas_and_combo_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)
            workspace_root = session_dir / "workspaces"
            workspace_root.mkdir()

            summary_rows = [
                {
                    "run_id": "wheat_b0_rep0",
                    "combo_key": "B0",
                    "crop": "wheat",
                    "weight": "W0",
                    "engine": "O1",
                    "sequence": "S1",
                    "grouping": "G1",
                    "budget": "quick",
                    "status": "ok",
                    "score": "10",
                    "train_mean_nrmse": "0.10",
                    "valid_mean_nrmse": "0.12",
                    "all_mean_nrmse": "0.11",
                    "eval_call_count": "10",
                    "run_model_invocations": "1",
                    "dssat_treatment_calls": "4",
                    "dssat_wall_sec": "2.0",
                    "workspace_dir": str(workspace_root / "wheat_b0_rep0" / "workspace"),
                },
                {
                    "run_id": "wheat_b1_rep0",
                    "combo_key": "B1",
                    "crop": "wheat",
                    "weight": "W0",
                    "engine": "O2",
                    "sequence": "S1",
                    "grouping": "G1",
                    "budget": "quick",
                    "status": "ok",
                    "score": "11",
                    "train_mean_nrmse": "0.11",
                    "valid_mean_nrmse": "0.13",
                    "all_mean_nrmse": "0.12",
                    "eval_call_count": "11",
                    "run_model_invocations": "1",
                    "dssat_treatment_calls": "4",
                    "dssat_wall_sec": "2.1",
                    "workspace_dir": str(workspace_root / "wheat_b1_rep0" / "workspace"),
                },
                {
                    "run_id": "wheat_w8_o1_s2_g3_rep0",
                    "combo_key": "W8_O1_S2_G3",
                    "crop": "wheat",
                    "weight": "W8",
                    "engine": "O1",
                    "sequence": "S2",
                    "grouping": "G3",
                    "budget": "standard",
                    "status": "ok",
                    "score": "7",
                    "train_mean_nrmse": "0.07",
                    "valid_mean_nrmse": "0.10",
                    "all_mean_nrmse": "0.08",
                    "eval_call_count": "20",
                    "run_model_invocations": "2",
                    "dssat_treatment_calls": "8",
                    "dssat_wall_sec": "3.0",
                    "workspace_dir": str(workspace_root / "wheat_w8_o1_s2_g3_rep0" / "workspace"),
                },
                {
                    "run_id": "wheat_w8_o1_s2_g3_rep1",
                    "combo_key": "W8_O1_S2_G3",
                    "crop": "wheat",
                    "weight": "W8",
                    "engine": "O1",
                    "sequence": "S2",
                    "grouping": "G3",
                    "budget": "standard",
                    "status": "ok",
                    "score": "8",
                    "train_mean_nrmse": "0.08",
                    "valid_mean_nrmse": "0.11",
                    "all_mean_nrmse": "0.09",
                    "eval_call_count": "21",
                    "run_model_invocations": "2",
                    "dssat_treatment_calls": "8",
                    "dssat_wall_sec": "3.1",
                    "workspace_dir": str(workspace_root / "wheat_w8_o1_s2_g3_rep1" / "workspace"),
                },
            ]
            write_tsv(session_dir / "phase1_experiment_summary.tsv", summary_rows)

            aggregate_rows = [
                {"run_id": "wheat_w8_o1_s2_g3_rep0", "split": "train", "metric": "yield", "group_label": "yield", "nrmse": "0.10"},
                {"run_id": "wheat_w8_o1_s2_g3_rep0", "split": "train", "metric": "phenology", "group_label": "phenology", "nrmse": "0.30"},
                {"run_id": "wheat_w8_o1_s2_g3_rep1", "split": "train", "metric": "yield", "group_label": "yield", "nrmse": "0.20"},
                {"run_id": "wheat_w8_o1_s2_g3_rep1", "split": "train", "metric": "phenology", "group_label": "phenology", "nrmse": "0.40"},
            ]
            write_tsv(session_dir / "phase1_aggregate_metrics.tsv", aggregate_rows)

            parameter_rows = [
                {"run_id": "wheat_w8_o1_s2_g3_rep0", "param_name": "P1", "normalized_distance_to_b0": "0.20", "is_at_lower_bound": "false", "is_at_upper_bound": "false"},
                {"run_id": "wheat_w8_o1_s2_g3_rep0", "param_name": "P2", "normalized_distance_to_b0": "0.60", "is_at_lower_bound": "true", "is_at_upper_bound": "false"},
                {"run_id": "wheat_w8_o1_s2_g3_rep1", "param_name": "P1", "normalized_distance_to_b0": "0.40", "is_at_lower_bound": "false", "is_at_upper_bound": "true"},
                {"run_id": "wheat_w8_o1_s2_g3_rep1", "param_name": "P2", "normalized_distance_to_b0": "0.80", "is_at_lower_bound": "false", "is_at_upper_bound": "false"},
            ]
            write_tsv(session_dir / "phase1_parameters.tsv", parameter_rows)

            with patch.object(sys, "argv", ["phase1_postprocess.py", "--input-dir", str(session_dir)]):
                phase1_postprocess.main()

            derived_rows = read_tsv(session_dir / "phase1_derived_metrics.tsv")
            target_rows = [row for row in derived_rows if row["combo_key"] == "W8_O1_S2_G3"]
            self.assertEqual(len(target_rows), 2)
            self.assertEqual(target_rows[0]["better_than_b0"], "True")
            self.assertAlmostEqual(float(target_rows[0]["delta_vs_b0"]), -3.0)
            self.assertAlmostEqual(float(target_rows[0]["boundary_hit_rate"]), 0.5)
            self.assertAlmostEqual(float(target_rows[0]["param_shift_norm"]), 0.4)
            self.assertAlmostEqual(float(target_rows[0]["group_balance_index"]), 0.1)

            combo_summary_rows = read_tsv(session_dir / "phase1_combo_summary.tsv")
            combo_row = next(row for row in combo_summary_rows if row["combo_key"] == "W8_O1_S2_G3")
            self.assertEqual(combo_row["run_count"], "2")
            self.assertAlmostEqual(float(combo_row["better_than_b0_rate"]), 1.0)
            self.assertAlmostEqual(float(combo_row["score_mean"]), 7.5)
            self.assertAlmostEqual(float(combo_row["primary_score_mean"]), 0.105)
            self.assertAlmostEqual(float(combo_row["boundary_hit_rate_mean"]), 0.5)
            self.assertAlmostEqual(float(combo_row["group_balance_index_mean"]), 0.1)


if __name__ == "__main__":
    unittest.main()
